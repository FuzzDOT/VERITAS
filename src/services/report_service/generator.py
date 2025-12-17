"""
Report Service - Report Generator
====================================

Production-grade deterministic report generation:
- HTML rendering via Jinja2 with stable output
- PDF rendering via WeasyPrint (pinned version)
- Idempotent generation (same inputs = same outputs)
- Content-addressed storage for artifacts

Design Principles:
- All output is byte-for-byte reproducible
- Stable ordering of all lists (alphabetical by ID)
- Stable numeric formatting (fixed precision)
- Timestamps only from truth_version.created_at
"""

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import hash_content

from .schemas import (
    REPORT_SERVICE_VERSION,
    HTML_RENDERER_VERSION,
    PDF_RENDERER_VERSION,
    CANONICAL_DATE_FORMAT,
    CANONICAL_DATETIME_FORMAT,
    format_probability,
    format_percentage,
    format_score,
    format_date,
    format_datetime,
    ReportStatus,
    ReportType,
    ReportMetadata,
    ReportContent,
    ClaimSection,
    EvaluationMetadataSection,
    PolicySummarySection,
    ConclusionSection,
    ProbabilitySection,
    RiskAnalysisSection,
    MetricsSummarySection,
    IntegritySection,
    ProvenanceAppendix,
    EvidenceProvenance,
    FactProvenance,
    GenerateReportResponse,
)
from .stores import ReportStore, ArtifactStore


# =============================================================================
# Template Setup
# =============================================================================

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"


def create_jinja_environment() -> Environment:
    """
    Create a Jinja2 environment with deterministic settings.
    
    No auto-escaping randomness, strict undefined handling.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    
    # Add deterministic filters
    env.filters["format_date"] = format_date
    env.filters["format_datetime"] = format_datetime
    env.filters["format_probability"] = format_probability
    env.filters["format_percentage"] = format_percentage
    env.filters["format_score"] = format_score
    
    return env


# =============================================================================
# Content Builder
# =============================================================================


class ReportContentBuilder:
    """
    Builds structured report content from a TruthVersion.
    
    All data extraction and formatting is deterministic.
    """
    
    def __init__(
        self,
        truth_version: Any,  # TruthVersion from A8
        evidence_list: list[dict[str, Any]],
        facts_list: list[dict[str, Any]],
        trace_id: Optional[str] = None,
        audit_hash: Optional[str] = None,
        metrics: Optional[list[dict[str, str]]] = None,
        report_generated_at: Optional[datetime] = None,
    ):
        self._truth_version = truth_version
        self._evidence_list = evidence_list
        self._facts_list = facts_list
        self._trace_id = trace_id
        self._audit_hash = audit_hash
        self._metrics = metrics or []
        # Use truth_version.created_at for reproducibility
        self._report_generated_at = report_generated_at or truth_version.created_at
    
    def build(self) -> ReportContent:
        """Build the complete report content."""
        tv = self._truth_version
        
        # Determine report type
        report_type = (
            ReportType.REFUSAL_SUMMARY
            if tv.conclusion == "refused"
            else ReportType.SOLVENCY_DETERMINATION
        )
        
        return ReportContent(
            report_type=report_type,
            renderer_version=HTML_RENDERER_VERSION,
            claim=self._build_claim_section(),
            evaluation_metadata=self._build_evaluation_metadata_section(),
            policy_summary=self._build_policy_summary_section(),
            conclusion=self._build_conclusion_section(),
            probability=self._build_probability_section(),
            risk_analysis=self._build_risk_analysis_section(),
            metrics_summary=self._build_metrics_summary_section(),
            integrity=self._build_integrity_section(),
            provenance=self._build_provenance_appendix(),
        )
    
    def _build_claim_section(self) -> ClaimSection:
        """Build claim summary section."""
        tv = self._truth_version
        cck = tv.claim_class_key
        
        return ClaimSection(
            canonical_claim_summary=tv.canonical_claim_summary,
            claim_class_key=cck.key,
            entity_id=cck.entity_id,
            entity_id_type=cck.entity_id_type,
            jurisdiction=cck.jurisdiction,
            scenario_name=cck.scenario_name,
            horizon_months=cck.horizon_bucket,
            as_of_date=cck.as_of_date_bucket,
        )
    
    def _build_evaluation_metadata_section(self) -> EvaluationMetadataSection:
        """Build evaluation metadata section."""
        tv = self._truth_version
        
        return EvaluationMetadataSection(
            evaluation_id=tv.evaluation_id,
            truth_version_id=tv.truth_version_id,
            engine_version=tv.engine_version,
            report_generated_at=self._report_generated_at,
        )
    
    def _build_policy_summary_section(self) -> PolicySummarySection:
        """Build policy summary section."""
        tv = self._truth_version
        
        # Generate a human-readable policy summary
        policy_summary = (
            f"Evaluation performed under policy {tv.policy_hash[:16]}... "
            f"with engine version {tv.engine_version}"
        )
        
        return PolicySummarySection(
            policy_hash=tv.policy_hash,
            policy_summary=policy_summary,
        )
    
    def _build_conclusion_section(self) -> ConclusionSection:
        """Build conclusion section."""
        tv = self._truth_version
        is_refusal = tv.conclusion == "refused"
        
        # Extract missing facts from refusal message if available
        missing_facts: list[str] = []
        if is_refusal and tv.refusal_message:
            # Parse missing facts from refusal message
            # Format: "Missing facts: fact1, fact2, fact3"
            if "missing" in tv.refusal_message.lower():
                parts = tv.refusal_message.split(":")
                if len(parts) > 1:
                    facts_str = parts[-1].strip()
                    missing_facts = [f.strip() for f in facts_str.split(",") if f.strip()]
        
        return ConclusionSection(
            conclusion=tv.conclusion,
            is_refusal=is_refusal,
            refusal_code=tv.refusal_code,
            refusal_message=tv.refusal_message,
            missing_facts=sorted(missing_facts),  # Deterministic ordering
        )
    
    def _build_probability_section(self) -> ProbabilitySection:
        """Build probability interval section."""
        tv = self._truth_version
        pi = tv.probability_interval
        
        if not pi:
            return ProbabilitySection(
                has_probability=False,
                p_low=None,
                p_mid=None,
                p_high=None,
                p_low_pct=None,
                p_mid_pct=None,
                p_high_pct=None,
            )
        
        return ProbabilitySection(
            has_probability=True,
            p_low=format_probability(pi.p_low),
            p_mid=format_probability(pi.p_mid),
            p_high=format_probability(pi.p_high),
            p_low_pct=format_percentage(pi.p_low),
            p_mid_pct=format_percentage(pi.p_mid),
            p_high_pct=format_percentage(pi.p_high),
        )
    
    def _build_risk_analysis_section(self) -> RiskAnalysisSection:
        """Build risk analysis section."""
        tv = self._truth_version
        
        fragility_score: Optional[str] = None
        fragility_interpretation: Optional[str] = None
        
        if tv.fragility_score is not None:
            fragility_score = format_score(tv.fragility_score)
            # Interpret fragility
            fs = tv.fragility_score
            if fs < Decimal("0.2"):
                fragility_interpretation = "Robust - determination is stable under variations"
            elif fs < Decimal("0.4"):
                fragility_interpretation = "Moderate - some sensitivity to input changes"
            elif fs < Decimal("0.6"):
                fragility_interpretation = "Elevated - determination may change with moderate input variations"
            elif fs < Decimal("0.8"):
                fragility_interpretation = "High - determination is sensitive to input changes"
            else:
                fragility_interpretation = "Critical - determination is highly unstable"
        
        # Build key risks with stable ordering
        key_risks = [
            {
                "risk_type": risk.risk_type,
                "description": risk.description,
                "severity": risk.severity,
            }
            for risk in sorted(tv.key_risks, key=lambda r: r.risk_type)
        ]
        
        return RiskAnalysisSection(
            fragility_score=fragility_score,
            fragility_interpretation=fragility_interpretation,
            top_sensitivity_driver=tv.top_sensitivity_driver,
            key_risks=key_risks,
        )
    
    def _build_metrics_summary_section(self) -> MetricsSummarySection:
        """Build metrics summary section."""
        # Sort metrics by name for stability
        sorted_metrics = sorted(self._metrics, key=lambda m: m.get("name", ""))
        return MetricsSummarySection(metrics=sorted_metrics)
    
    def _build_integrity_section(self) -> IntegritySection:
        """Build integrity and reproducibility section."""
        tv = self._truth_version
        
        # Build replay instructions
        replay_instructions = (
            f"POST /v1/trace/replay\n"
            f"{{\n"
            f'  "evaluation_id": "{tv.evaluation_id}",\n'
            f'  "expected_trace_hash": "{tv.trace_hash}",\n'
            f'  "expected_result_hash": "{tv.result_hash}"\n'
            f"}}\n\n"
            f"Expected response: ReplayStatus.SUCCESS with matching hashes."
        )
        
        return IntegritySection(
            trace_id=self._trace_id,
            trace_hash=tv.trace_hash,
            audit_hash=self._audit_hash,
            facts_snapshot_hash=tv.facts_snapshot_hash,
            evidence_set_hash=tv.evidence_set_hash,
            policy_hash=tv.policy_hash,
            result_hash=tv.result_hash,
            replay_endpoint="/v1/trace/replay",
            replay_instructions=replay_instructions,
        )
    
    def _build_provenance_appendix(self) -> ProvenanceAppendix:
        """Build provenance appendix with sorted evidence and facts."""
        # Sort evidence by evidence_id for stable ordering
        evidence_list = [
            EvidenceProvenance(
                evidence_id=ev.get("evidence_id", ""),
                source_type=ev.get("source_type", ""),
                published_at=ev.get("published_at"),
                retrieved_at=ev.get("retrieved_at"),
                sha256_hash=ev.get("sha256_hash", ev.get("content_hash", "")),
                reliability=ev.get("reliability", "unknown"),
                entity_id=ev.get("entity_id"),
                entity_id_type=ev.get("entity_id_type"),
            )
            for ev in sorted(self._evidence_list, key=lambda e: e.get("evidence_id", ""))
        ]
        
        # Sort facts by fact_id for stable ordering
        facts_list = [
            FactProvenance(
                fact_id=f.get("fact_id", ""),
                fact_type=f.get("fact_type", ""),
                value=str(f.get("value", "")),
                unit=f.get("unit"),
                currency=f.get("currency"),
                as_of_date=f.get("as_of_date"),
                period_end=f.get("period_end"),
                confidence=str(f.get("confidence", "")),
                extraction_method=f.get("extraction_method", ""),
                derived_from_evidence_id=f.get("evidence_id", ""),
                location=f.get("location"),
            )
            for f in sorted(self._facts_list, key=lambda x: x.get("fact_id", ""))
        ]
        
        return ProvenanceAppendix(
            evidence_list=evidence_list,
            facts_list=facts_list,
        )


# =============================================================================
# HTML Renderer
# =============================================================================


class HTMLRenderer:
    """
    Renders deterministic canonical HTML from ReportContent.
    
    Uses Jinja2 with stable settings to ensure byte-for-byte reproducibility.
    """
    
    def __init__(self):
        self._env = create_jinja_environment()
        self._template = self._env.get_template("solvency_report.html.j2")
    
    def render(self, content: ReportContent) -> bytes:
        """
        Render ReportContent to canonical HTML bytes.
        
        Returns UTF-8 encoded HTML.
        """
        # Convert content to dict for template
        context = self._content_to_dict(content)
        
        # Render template
        html = self._template.render(**context)
        
        # Normalize line endings for determinism
        html = html.replace("\r\n", "\n")
        
        return html.encode("utf-8")
    
    def _content_to_dict(self, content: ReportContent) -> dict[str, Any]:
        """Convert ReportContent to template context dict."""
        # Format dates and datetimes for the template
        claim_dict = content.claim.model_dump()
        claim_dict["as_of_date"] = format_date(content.claim.as_of_date)
        
        eval_dict = content.evaluation_metadata.model_dump()
        eval_dict["report_generated_at"] = format_datetime(
            content.evaluation_metadata.report_generated_at
        )
        
        # Format evidence published_at and retrieved_at
        evidence_list = []
        for ev in content.provenance.evidence_list:
            ev_dict = ev.model_dump()
            if ev.published_at:
                ev_dict["published_at"] = format_datetime(ev.published_at)
            if ev.retrieved_at:
                ev_dict["retrieved_at"] = format_datetime(ev.retrieved_at)
            evidence_list.append(ev_dict)
        
        # Format facts as_of_date and period_end
        facts_list = []
        for f in content.provenance.facts_list:
            f_dict = f.model_dump()
            if f.as_of_date:
                f_dict["as_of_date"] = format_date(f.as_of_date)
            if f.period_end:
                f_dict["period_end"] = format_date(f.period_end)
            facts_list.append(f_dict)
        
        return {
            "report_type": content.report_type.value,
            "renderer_version": content.renderer_version,
            "claim": claim_dict,
            "evaluation_metadata": eval_dict,
            "policy_summary": content.policy_summary.model_dump(),
            "conclusion": content.conclusion.model_dump(),
            "probability": content.probability.model_dump(),
            "risk_analysis": content.risk_analysis.model_dump(),
            "metrics_summary": content.metrics_summary.model_dump(),
            "integrity": content.integrity.model_dump(),
            "provenance": {
                "evidence_list": evidence_list,
                "facts_list": facts_list,
            },
        }


# =============================================================================
# PDF Renderer
# =============================================================================


class PDFRenderer:
    """
    Renders PDF from HTML using WeasyPrint.
    
    Note: PDF rendering may not be perfectly deterministic due to font
    rendering differences. The canonical HTML hash is authoritative.
    """
    
    def __init__(self):
        self._version = PDF_RENDERER_VERSION
    
    @property
    def version(self) -> str:
        """Get PDF renderer version."""
        return self._version
    
    def render(self, html_content: bytes) -> bytes:
        """
        Render HTML to PDF.
        
        Returns PDF bytes.
        """
        try:
            from weasyprint import HTML  # type: ignore[import-not-found]
            
            # Render PDF from HTML
            html = HTML(string=html_content.decode("utf-8"))
            pdf_bytes = html.write_pdf()
            
            return pdf_bytes
        except ImportError:
            # WeasyPrint not installed - return empty PDF marker
            raise RuntimeError(
                "WeasyPrint is not installed. Install with: pip install weasyprint"
            )


# =============================================================================
# Report Generator
# =============================================================================


class ReportGenerator:
    """
    Main report generation orchestrator.
    
    Handles:
    - Idempotency (return cached report if exists)
    - Deterministic HTML generation
    - Optional PDF generation
    - Artifact storage
    - Metadata registration
    """
    
    def __init__(
        self,
        session: AsyncSession,
        report_store: ReportStore,
        artifact_store: ArtifactStore,
        html_renderer: Optional[HTMLRenderer] = None,
        pdf_renderer: Optional[PDFRenderer] = None,
    ):
        self._session = session
        self._report_store = report_store
        self._artifact_store = artifact_store
        self._html_renderer = html_renderer or HTMLRenderer()
        self._pdf_renderer = pdf_renderer
    
    async def generate(
        self,
        truth_version: Any,  # TruthVersion from A8
        evidence_list: list[dict[str, Any]],
        facts_list: list[dict[str, Any]],
        trace_id: Optional[str] = None,
        audit_hash: Optional[str] = None,
        metrics: Optional[list[dict[str, str]]] = None,
        include_pdf: bool = True,
    ) -> GenerateReportResponse:
        """
        Generate a report for a TruthVersion.
        
        Returns GenerateReportResponse with report details.
        """
        # Check for existing report (idempotency)
        existing = await self._report_store.find_existing(
            truth_version_id=truth_version.truth_version_id,
            renderer_version=HTML_RENDERER_VERSION,
        )
        
        if existing:
            return GenerateReportResponse(
                report_id=existing.report_id,
                truth_version_id=existing.truth_version_id,
                was_cached=True,
                html_uri=existing.html_uri,
                pdf_uri=existing.pdf_uri,
                html_hash=existing.html_hash,
                pdf_hash=existing.pdf_hash,
                message=f"Returned cached report {existing.report_id}",
            )
        
        # Generate report ID
        report_id = str(generate_canonical_id(EntityType.REPORT))
        
        # Build content
        builder = ReportContentBuilder(
            truth_version=truth_version,
            evidence_list=evidence_list,
            facts_list=facts_list,
            trace_id=trace_id,
            audit_hash=audit_hash,
            metrics=metrics,
        )
        content = builder.build()
        
        # Render HTML
        html_content = self._html_renderer.render(content)
        
        # Store HTML
        html_uri, html_hash = await self._artifact_store.store_html(
            report_id=report_id,
            truth_version_id=truth_version.truth_version_id,
            html_content=html_content,
        )
        
        # Render and store PDF if requested
        pdf_uri: Optional[str] = None
        pdf_hash: Optional[str] = None
        pdf_renderer_version: Optional[str] = None
        
        if include_pdf and self._pdf_renderer:
            try:
                pdf_content = self._pdf_renderer.render(html_content)
                pdf_uri, pdf_hash = await self._artifact_store.store_pdf(
                    report_id=report_id,
                    truth_version_id=truth_version.truth_version_id,
                    pdf_content=pdf_content,
                )
                pdf_renderer_version = self._pdf_renderer.version
            except RuntimeError:
                # PDF rendering not available - continue without PDF
                pass
        
        # Create metadata
        metadata = ReportMetadata(
            report_id=report_id,
            truth_version_id=truth_version.truth_version_id,
            created_at=truth_version.created_at,  # Use truth version timestamp
            html_hash=html_hash,
            pdf_hash=pdf_hash,
            html_uri=html_uri,
            pdf_uri=pdf_uri,
            renderer_version=HTML_RENDERER_VERSION,
            pdf_renderer_version=pdf_renderer_version,
            report_service_version=REPORT_SERVICE_VERSION,
            status=ReportStatus.COMPLETED,
        )
        
        # Store metadata
        await self._report_store.store(metadata)
        await self._session.commit()
        
        return GenerateReportResponse(
            report_id=report_id,
            truth_version_id=truth_version.truth_version_id,
            was_cached=False,
            html_uri=html_uri,
            pdf_uri=pdf_uri,
            html_hash=html_hash,
            pdf_hash=pdf_hash,
            message=f"Generated report {report_id}",
        )


# =============================================================================
# Factory Functions
# =============================================================================


def create_html_renderer() -> HTMLRenderer:
    """Create an HTMLRenderer instance."""
    return HTMLRenderer()


def create_pdf_renderer() -> Optional[PDFRenderer]:
    """
    Create a PDFRenderer instance if WeasyPrint is available.
    
    Returns None if WeasyPrint is not installed.
    """
    try:
        import weasyprint  # type: ignore[import-not-found]  # noqa: F401
        return PDFRenderer()
    except ImportError:
        return None


def create_report_generator(
    session: AsyncSession,
    report_store: ReportStore,
    artifact_store: ArtifactStore,
) -> ReportGenerator:
    """Create a ReportGenerator with default renderers."""
    return ReportGenerator(
        session=session,
        report_store=report_store,
        artifact_store=artifact_store,
        html_renderer=create_html_renderer(),
        pdf_renderer=create_pdf_renderer(),
    )
