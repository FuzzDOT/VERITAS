"""
Report Service Schemas
========================

Defines all schemas for the Report Service:
- ReportMetadata: Immutable report metadata
- ReportContent: Structured content for deterministic rendering
- EvidenceProvenance: Evidence in the provenance appendix
- FactProvenance: Fact provenance in the report
- IntegritySection: All integrity hashes for reproducibility

Design Principles:
- All schemas are frozen (immutable)
- Report content is deterministic and reproducible
- Numeric formatting uses stable precision
- Timestamps use only truth_version.created_at for reproducibility
"""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Constants
# =============================================================================

# Report service version for tracking
REPORT_SERVICE_VERSION: str = "1.0.0"

# Renderer version (pinned for determinism)
HTML_RENDERER_VERSION: str = "1.0.0"
PDF_RENDERER_VERSION: str = "weasyprint-62.3"

# Numeric formatting constants
PROBABILITY_DECIMAL_PLACES: int = 4
PERCENTAGE_DECIMAL_PLACES: int = 2
CURRENCY_DECIMAL_PLACES: int = 2
SCORE_DECIMAL_PLACES: int = 4

# Date format for deterministic rendering
CANONICAL_DATE_FORMAT: str = "%Y-%m-%d"
CANONICAL_DATETIME_FORMAT: str = "%Y-%m-%dT%H:%M:%SZ"


# =============================================================================
# Formatting Functions
# =============================================================================


def format_probability(value: Decimal) -> str:
    """Format probability with stable precision."""
    quantized = value.quantize(
        Decimal(f"0.{'0' * PROBABILITY_DECIMAL_PLACES}"),
        rounding=ROUND_HALF_UP,
    )
    return str(quantized)


def format_percentage(value: Decimal) -> str:
    """Format as percentage with stable precision."""
    pct = value * Decimal("100")
    quantized = pct.quantize(
        Decimal(f"0.{'0' * PERCENTAGE_DECIMAL_PLACES}"),
        rounding=ROUND_HALF_UP,
    )
    return f"{quantized}%"


def format_currency(value: Decimal, currency: str = "USD") -> str:
    """Format currency with stable precision and symbol."""
    quantized = value.quantize(
        Decimal(f"0.{'0' * CURRENCY_DECIMAL_PLACES}"),
        rounding=ROUND_HALF_UP,
    )
    # Add thousands separator
    formatted = f"{quantized:,.{CURRENCY_DECIMAL_PLACES}f}"
    return f"{currency} {formatted}"


def format_score(value: Decimal) -> str:
    """Format a score (0-1) with stable precision."""
    quantized = value.quantize(
        Decimal(f"0.{'0' * SCORE_DECIMAL_PLACES}"),
        rounding=ROUND_HALF_UP,
    )
    return str(quantized)


def format_date(dt: date) -> str:
    """Format date deterministically."""
    return dt.strftime(CANONICAL_DATE_FORMAT)


def format_datetime(dt: datetime) -> str:
    """Format datetime deterministically in UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime(CANONICAL_DATETIME_FORMAT)


# =============================================================================
# Enums
# =============================================================================


class ReportStatus(str, Enum):
    """Status of a generated report."""
    
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportType(str, Enum):
    """Types of reports."""
    
    SOLVENCY_DETERMINATION = "solvency_determination"
    REFUSAL_SUMMARY = "refusal_summary"


# =============================================================================
# Evidence Provenance
# =============================================================================


class EvidenceProvenance(BaseModel):
    """Evidence item in the provenance appendix."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    evidence_id: str = Field(..., description="Evidence ID")
    source_type: str = Field(..., description="Source type")
    published_at: Optional[datetime] = Field(None, description="Publication date")
    retrieved_at: Optional[datetime] = Field(None, description="Retrieval timestamp")
    sha256_hash: str = Field(..., description="SHA256 content hash")
    reliability: str = Field(..., description="Reliability tier")
    entity_id: Optional[str] = Field(None, description="Linked entity ID")
    entity_id_type: Optional[str] = Field(None, description="Entity ID type")


class FactProvenance(BaseModel):
    """Fact item in the provenance appendix."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    fact_id: str = Field(..., description="Fact ID")
    fact_type: str = Field(..., description="Fact type")
    value: str = Field(..., description="Formatted value")
    unit: Optional[str] = Field(None, description="Unit of measure")
    currency: Optional[str] = Field(None, description="Currency if monetary")
    as_of_date: Optional[date] = Field(None, description="As-of date")
    period_end: Optional[date] = Field(None, description="Period end date")
    confidence: str = Field(..., description="Confidence level")
    extraction_method: str = Field(..., description="How extracted")
    derived_from_evidence_id: str = Field(..., description="Source evidence ID")
    location: Optional[str] = Field(None, description="Location in document")


# =============================================================================
# Report Content Sections
# =============================================================================


class ClaimSection(BaseModel):
    """Claim summary section of the report."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    canonical_claim_summary: str = Field(..., description="Human-readable claim")
    claim_class_key: str = Field(..., description="Canonical claim class key")
    entity_id: str = Field(..., description="Entity identifier")
    entity_id_type: str = Field(..., description="Entity ID type")
    jurisdiction: str = Field(..., description="Legal jurisdiction")
    scenario_name: str = Field(..., description="Stress scenario name")
    horizon_months: int = Field(..., description="Evaluation horizon")
    as_of_date: date = Field(..., description="As-of date")


class EvaluationMetadataSection(BaseModel):
    """Evaluation metadata section."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    evaluation_id: str = Field(..., description="Evaluation ID from A6")
    truth_version_id: str = Field(..., description="Truth version ID from A8")
    engine_version: str = Field(..., description="Reasoning engine version")
    report_generated_at: datetime = Field(..., description="Report generation time")


class PolicySummarySection(BaseModel):
    """Policy configuration summary."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    policy_hash: str = Field(..., description="Hash of policy configuration")
    policy_summary: str = Field(..., description="Human-readable policy summary")


class ConclusionSection(BaseModel):
    """Conclusion or refusal section."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    conclusion: str = Field(..., description="solvent, insolvent, or refused")
    is_refusal: bool = Field(..., description="Whether this is a refusal")
    refusal_code: Optional[str] = Field(None, description="Refusal code if refused")
    refusal_message: Optional[str] = Field(None, description="Refusal message")
    missing_facts: list[str] = Field(
        default_factory=list, description="Missing facts if refused"
    )


class ProbabilitySection(BaseModel):
    """Probability interval summary section."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    has_probability: bool = Field(..., description="Whether probability available")
    p_low: Optional[str] = Field(None, description="Lower bound (formatted)")
    p_mid: Optional[str] = Field(None, description="Point estimate (formatted)")
    p_high: Optional[str] = Field(None, description="Upper bound (formatted)")
    p_low_pct: Optional[str] = Field(None, description="Lower bound as percentage")
    p_mid_pct: Optional[str] = Field(None, description="Point estimate as percentage")
    p_high_pct: Optional[str] = Field(None, description="Upper bound as percentage")


class RiskAnalysisSection(BaseModel):
    """Risk analysis section."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    fragility_score: Optional[str] = Field(None, description="Fragility score (formatted)")
    fragility_interpretation: Optional[str] = Field(
        None, description="Human-readable interpretation"
    )
    top_sensitivity_driver: Optional[str] = Field(
        None, description="Most impactful sensitivity driver"
    )
    key_risks: list[dict[str, str]] = Field(
        default_factory=list, description="Key risks list"
    )


class MetricsSummarySection(BaseModel):
    """Intermediate metrics summary."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    metrics: list[dict[str, str]] = Field(
        default_factory=list, description="Computed metrics"
    )


class IntegritySection(BaseModel):
    """Integrity and reproducibility section."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Trace identifiers
    trace_id: Optional[str] = Field(None, description="Trace graph ID")
    
    # All integrity hashes
    trace_hash: str = Field(..., description="Hash of trace graph")
    audit_hash: Optional[str] = Field(None, description="Hash of audit record")
    facts_snapshot_hash: str = Field(..., description="Hash of facts snapshot")
    evidence_set_hash: str = Field(..., description="Hash of evidence set")
    policy_hash: str = Field(..., description="Hash of policy config")
    result_hash: str = Field(..., description="Hash of evaluation result")
    
    # Replay instructions
    replay_endpoint: str = Field(
        ..., description="Endpoint URL for replay verification"
    )
    replay_instructions: str = Field(
        ..., description="Human-readable replay instructions"
    )


class ProvenanceAppendix(BaseModel):
    """Full provenance appendix."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    evidence_list: list[EvidenceProvenance] = Field(
        default_factory=list, description="All evidence used"
    )
    facts_list: list[FactProvenance] = Field(
        default_factory=list, description="All facts used"
    )


# =============================================================================
# Complete Report Content
# =============================================================================


class ReportContent(BaseModel):
    """Complete structured report content for rendering."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Report metadata
    report_type: ReportType = Field(..., description="Type of report")
    renderer_version: str = Field(..., description="HTML renderer version")
    
    # Sections
    claim: ClaimSection = Field(..., description="Claim section")
    evaluation_metadata: EvaluationMetadataSection = Field(
        ..., description="Evaluation metadata"
    )
    policy_summary: PolicySummarySection = Field(..., description="Policy summary")
    conclusion: ConclusionSection = Field(..., description="Conclusion section")
    probability: ProbabilitySection = Field(..., description="Probability section")
    risk_analysis: RiskAnalysisSection = Field(..., description="Risk analysis")
    metrics_summary: MetricsSummarySection = Field(..., description="Metrics summary")
    integrity: IntegritySection = Field(..., description="Integrity section")
    provenance: ProvenanceAppendix = Field(..., description="Provenance appendix")


# =============================================================================
# Report Metadata
# =============================================================================


class ReportMetadata(BaseModel):
    """Metadata for a generated report."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    report_id: str = Field(..., description="Unique report ID")
    truth_version_id: str = Field(..., description="Source truth version ID")
    created_at: datetime = Field(..., description="Report creation timestamp")
    
    # Artifact hashes
    html_hash: str = Field(..., description="Hash of canonical HTML")
    pdf_hash: Optional[str] = Field(None, description="Hash of PDF (if generated)")
    
    # Storage URIs
    html_uri: str = Field(..., description="Object storage URI for HTML")
    pdf_uri: Optional[str] = Field(None, description="Object storage URI for PDF")
    
    # Versioning
    renderer_version: str = Field(..., description="HTML renderer version")
    pdf_renderer_version: Optional[str] = Field(
        None, description="PDF renderer version"
    )
    report_service_version: str = Field(
        default=REPORT_SERVICE_VERSION, description="Report service version"
    )
    
    # Status
    status: ReportStatus = Field(..., description="Report generation status")


# =============================================================================
# API Request/Response Schemas
# =============================================================================


class GenerateReportRequest(BaseModel):
    """Request to generate a report."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    truth_version_id: str = Field(..., description="Truth version to report on")
    include_pdf: bool = Field(True, description="Whether to generate PDF")


class GenerateReportByClaimClassRequest(BaseModel):
    """Request to generate report for current truth of a claim class."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    claim_class_key: str = Field(..., description="Claim class key")
    include_pdf: bool = Field(True, description="Whether to generate PDF")


class GenerateReportResponse(BaseModel):
    """Response from report generation."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    report_id: str = Field(..., description="Report ID")
    truth_version_id: str = Field(..., description="Truth version ID")
    was_cached: bool = Field(..., description="Whether returned from cache")
    html_uri: str = Field(..., description="HTML artifact URI")
    pdf_uri: Optional[str] = Field(None, description="PDF artifact URI (if generated)")
    html_hash: str = Field(..., description="Hash of HTML")
    pdf_hash: Optional[str] = Field(None, description="Hash of PDF")
    message: str = Field(..., description="Status message")


class GetReportResponse(BaseModel):
    """Response with report metadata."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    report: ReportMetadata = Field(..., description="Report metadata")


class ListReportsResponse(BaseModel):
    """Response listing reports for a truth version."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    reports: list[ReportMetadata] = Field(..., description="List of reports")
    total: int = Field(..., description="Total count")
