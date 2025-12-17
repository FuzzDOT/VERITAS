"""
Report Service Tests (A9)
===========================

Comprehensive tests for the Report Service covering:
- Canonical HTML determinism
- Stable ordering of evidence/facts
- Correct inclusion of all required fields/hashes
- Idempotency behavior
- Correct handling of refusal TruthVersions
- Correct URI storage
- End-to-end generation from synthetic TruthVersion

Test Categories:
1. Schema Tests - Formatting functions and models
2. Content Builder Tests - Deterministic content building
3. HTML Renderer Tests - Template rendering
4. Store Tests - Postgres and artifact storage
5. Generator Tests - Full generation pipeline
6. Route Tests - REST API endpoints
7. Determinism Tests - Byte-for-byte reproducibility
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Test Fixtures: Synthetic TruthVersion and Related Data
# =============================================================================


class MockClaimClassKey(BaseModel):
    """Mock ClaimClassKey for testing."""
    
    model_config = ConfigDict(frozen=True)
    
    entity_id: str = "AAPL"
    entity_id_type: str = "TICKER"
    jurisdiction: str = "US"
    scenario_name: str = "baseline"
    scenario_shocks_hash: str = "abc123def456"
    horizon_bucket: int = 12
    as_of_date_bucket: date = date(2024, 12, 31)
    key: str = "TICKER:AAPL|US|baseline:abc123def456|H12M|2024-Q4"


class MockProbabilityInterval(BaseModel):
    """Mock probability interval."""
    
    model_config = ConfigDict(frozen=True)
    
    p_low: Decimal = Decimal("0.75")
    p_mid: Decimal = Decimal("0.85")
    p_high: Decimal = Decimal("0.92")


class MockKeyRisk(BaseModel):
    """Mock key risk."""
    
    model_config = ConfigDict(frozen=True)
    
    risk_type: str
    description: str
    severity: str


class MockTruthVersion(BaseModel):
    """Mock TruthVersion for testing."""
    
    model_config = ConfigDict(frozen=True)
    
    truth_version_id: str = "tv-test-001"
    created_at: datetime = datetime(2024, 12, 15, 10, 30, 0, tzinfo=timezone.utc)
    claim_class_key: MockClaimClassKey = Field(default_factory=MockClaimClassKey)
    canonical_claim_hash: str = "claim-hash-123"
    canonical_claim_summary: str = "Solvency determination for AAPL under baseline scenario"
    evaluation_id: str = "eval-test-001"
    conclusion: str = "solvent"
    refusal_code: Optional[str] = None
    refusal_message: Optional[str] = None
    probability_interval: Optional[MockProbabilityInterval] = Field(
        default_factory=MockProbabilityInterval
    )
    fragility_score: Optional[Decimal] = Decimal("0.35")
    key_risks: list[MockKeyRisk] = Field(default_factory=lambda: [
        MockKeyRisk(
            risk_type="market_risk",
            description="Exposure to market volatility",
            severity="medium",
        ),
        MockKeyRisk(
            risk_type="credit_risk",
            description="Counterparty credit exposure",
            severity="low",
        ),
    ])
    top_sensitivity_driver: Optional[str] = "interest_rate_shock"
    engine_version: str = "1.0.0"
    evidence_set_hash: str = "evidence-hash-abc"
    facts_snapshot_hash: str = "facts-hash-def"
    policy_hash: str = "policy-hash-ghi"
    trace_hash: str = "trace-hash-jkl"
    result_hash: str = "result-hash-mno"
    version_number: int = 1
    status: str = "current"
    supersedes_truth_version_id: Optional[str] = None
    superseded_by_truth_version_id: Optional[str] = None
    truth_service_version: str = "1.0.0"


def create_mock_truth_version(**overrides) -> MockTruthVersion:
    """Create a mock TruthVersion with optional overrides."""
    return MockTruthVersion(**overrides)


def create_mock_refusal_truth_version() -> MockTruthVersion:
    """Create a mock refused TruthVersion."""
    return MockTruthVersion(
        truth_version_id="tv-refused-001",
        conclusion="refused",
        refusal_code="INSUFFICIENT_DATA",
        refusal_message="Missing facts: total_assets, total_liabilities",
        probability_interval=None,
        fragility_score=None,
        key_risks=[],
        top_sensitivity_driver=None,
    )


SAMPLE_EVIDENCE_LIST = [
    {
        "evidence_id": "ev-001",
        "source_type": "sec_10k",
        "published_at": datetime(2024, 3, 15, tzinfo=timezone.utc),
        "retrieved_at": datetime(2024, 3, 16, tzinfo=timezone.utc),
        "sha256_hash": "sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        "reliability": "tier1",
        "entity_id": "AAPL",
        "entity_id_type": "TICKER",
    },
    {
        "evidence_id": "ev-002",
        "source_type": "audited_annual_report",
        "published_at": datetime(2024, 2, 28, tzinfo=timezone.utc),
        "retrieved_at": datetime(2024, 3, 1, tzinfo=timezone.utc),
        "sha256_hash": "sha256:fedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321",
        "reliability": "tier1",
        "entity_id": "AAPL",
        "entity_id_type": "TICKER",
    },
]


SAMPLE_FACTS_LIST = [
    {
        "fact_id": "fact-001",
        "fact_type": "total_assets",
        "value": "352000000000",
        "unit": "USD",
        "currency": "USD",
        "as_of_date": date(2024, 12, 31),
        "period_end": date(2024, 12, 31),
        "confidence": "0.95",
        "extraction_method": "xbrl",
        "evidence_id": "ev-001",
        "location": "Balance Sheet",
    },
    {
        "fact_id": "fact-002",
        "fact_type": "total_liabilities",
        "value": "290000000000",
        "unit": "USD",
        "currency": "USD",
        "as_of_date": date(2024, 12, 31),
        "period_end": date(2024, 12, 31),
        "confidence": "0.95",
        "extraction_method": "xbrl",
        "evidence_id": "ev-001",
        "location": "Balance Sheet",
    },
]


# =============================================================================
# Schema Tests
# =============================================================================


class TestFormattingFunctions:
    """Test deterministic formatting functions."""
    
    def test_format_probability_stable_precision(self):
        """Test probability formatting with stable precision."""
        from services.report_service.schemas import format_probability
        
        result = format_probability(Decimal("0.8567"))
        assert result == "0.8567"
        
        result = format_probability(Decimal("0.5"))
        assert result == "0.5000"
        
        # Test rounding
        result = format_probability(Decimal("0.85679"))
        assert result == "0.8568"
    
    def test_format_percentage_stable_precision(self):
        """Test percentage formatting."""
        from services.report_service.schemas import format_percentage
        
        result = format_percentage(Decimal("0.85"))
        assert result == "85.00%"
        
        result = format_percentage(Decimal("0.8567"))
        assert result == "85.67%"
    
    def test_format_score_stable_precision(self):
        """Test score formatting."""
        from services.report_service.schemas import format_score
        
        result = format_score(Decimal("0.35"))
        assert result == "0.3500"
    
    def test_format_date_deterministic(self):
        """Test date formatting is deterministic."""
        from services.report_service.schemas import format_date
        
        d = date(2024, 12, 31)
        result = format_date(d)
        assert result == "2024-12-31"
    
    def test_format_datetime_deterministic_utc(self):
        """Test datetime formatting is deterministic UTC."""
        from services.report_service.schemas import format_datetime
        
        dt = datetime(2024, 12, 15, 10, 30, 45, tzinfo=timezone.utc)
        result = format_datetime(dt)
        assert result == "2024-12-15T10:30:45Z"


class TestReportMetadataSchema:
    """Test ReportMetadata schema."""
    
    def test_create_report_metadata(self):
        """Test creating ReportMetadata."""
        from services.report_service.schemas import ReportMetadata, ReportStatus
        
        metadata = ReportMetadata(
            report_id="rpt-001",
            truth_version_id="tv-001",
            created_at=datetime(2024, 12, 15, tzinfo=timezone.utc),
            html_hash="html-hash-123",
            pdf_hash="pdf-hash-456",
            html_uri="s3://reports/html/rpt-001.html",
            pdf_uri="s3://reports/pdf/rpt-001.pdf",
            renderer_version="1.0.0",
            pdf_renderer_version="weasyprint-62.3",
            status=ReportStatus.COMPLETED,
        )
        
        assert metadata.report_id == "rpt-001"
        assert metadata.status == ReportStatus.COMPLETED
    
    def test_report_metadata_frozen(self):
        """Test ReportMetadata is immutable."""
        from services.report_service.schemas import ReportMetadata, ReportStatus
        
        metadata = ReportMetadata(
            report_id="rpt-001",
            truth_version_id="tv-001",
            created_at=datetime(2024, 12, 15, tzinfo=timezone.utc),
            html_hash="html-hash-123",
            html_uri="s3://reports/html/rpt-001.html",
            renderer_version="1.0.0",
            status=ReportStatus.COMPLETED,
        )
        
        with pytest.raises(Exception):  # Frozen models raise error on assignment
            metadata.report_id = "changed"  # type: ignore


class TestReportContentSchemas:
    """Test report content section schemas."""
    
    def test_claim_section(self):
        """Test ClaimSection schema."""
        from services.report_service.schemas import ClaimSection
        
        section = ClaimSection(
            canonical_claim_summary="Test claim",
            claim_class_key="TEST:KEY",
            entity_id="AAPL",
            entity_id_type="TICKER",
            jurisdiction="US",
            scenario_name="baseline",
            horizon_months=12,
            as_of_date=date(2024, 12, 31),
        )
        
        assert section.entity_id == "AAPL"
        assert section.horizon_months == 12
    
    def test_probability_section_with_values(self):
        """Test ProbabilitySection with values."""
        from services.report_service.schemas import ProbabilitySection
        
        section = ProbabilitySection(
            has_probability=True,
            p_low="0.7500",
            p_mid="0.8500",
            p_high="0.9200",
            p_low_pct="75.00%",
            p_mid_pct="85.00%",
            p_high_pct="92.00%",
        )
        
        assert section.has_probability is True
        assert section.p_mid == "0.8500"
    
    def test_probability_section_without_values(self):
        """Test ProbabilitySection for refusals."""
        from services.report_service.schemas import ProbabilitySection
        
        section = ProbabilitySection(has_probability=False)
        
        assert section.has_probability is False
        assert section.p_mid is None
    
    def test_integrity_section(self):
        """Test IntegritySection with all hashes."""
        from services.report_service.schemas import IntegritySection
        
        section = IntegritySection(
            trace_id="trace-001",
            trace_hash="trace-hash",
            audit_hash="audit-hash",
            facts_snapshot_hash="facts-hash",
            evidence_set_hash="evidence-hash",
            policy_hash="policy-hash",
            result_hash="result-hash",
            replay_endpoint="/v1/trace/replay",
            replay_instructions="POST to endpoint",
        )
        
        assert section.trace_hash == "trace-hash"
        assert section.replay_endpoint == "/v1/trace/replay"


# =============================================================================
# Content Builder Tests
# =============================================================================


class TestReportContentBuilder:
    """Test ReportContentBuilder."""
    
    def test_build_content_from_truth_version(self):
        """Test building content from TruthVersion."""
        from services.report_service.generator import ReportContentBuilder
        from services.report_service.schemas import ReportType
        
        tv = create_mock_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=SAMPLE_EVIDENCE_LIST,
            facts_list=SAMPLE_FACTS_LIST,
            trace_id="trace-001",
            audit_hash="audit-hash-001",
        )
        
        content = builder.build()
        
        assert content.report_type == ReportType.SOLVENCY_DETERMINATION
        assert content.claim.entity_id == "AAPL"
        assert content.evaluation_metadata.evaluation_id == "eval-test-001"
        assert content.conclusion.conclusion == "solvent"
        assert content.conclusion.is_refusal is False
    
    def test_build_content_for_refusal(self):
        """Test building content for refusal TruthVersion."""
        from services.report_service.generator import ReportContentBuilder
        from services.report_service.schemas import ReportType
        
        tv = create_mock_refusal_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=[],
            facts_list=[],
        )
        
        content = builder.build()
        
        assert content.report_type == ReportType.REFUSAL_SUMMARY
        assert content.conclusion.is_refusal is True
        assert content.conclusion.refusal_code == "INSUFFICIENT_DATA"
        assert content.probability.has_probability is False
    
    def test_evidence_sorted_by_id(self):
        """Test evidence is sorted alphabetically by ID."""
        from services.report_service.generator import ReportContentBuilder
        
        # Provide evidence out of order
        evidence = [
            {"evidence_id": "ev-003", "source_type": "test", "sha256_hash": "hash3", "reliability": "tier1"},
            {"evidence_id": "ev-001", "source_type": "test", "sha256_hash": "hash1", "reliability": "tier1"},
            {"evidence_id": "ev-002", "source_type": "test", "sha256_hash": "hash2", "reliability": "tier1"},
        ]
        
        tv = create_mock_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=evidence,
            facts_list=[],
        )
        
        content = builder.build()
        
        # Should be sorted
        assert content.provenance.evidence_list[0].evidence_id == "ev-001"
        assert content.provenance.evidence_list[1].evidence_id == "ev-002"
        assert content.provenance.evidence_list[2].evidence_id == "ev-003"
    
    def test_facts_sorted_by_id(self):
        """Test facts are sorted alphabetically by ID."""
        from services.report_service.generator import ReportContentBuilder
        
        facts = [
            {"fact_id": "fact-003", "fact_type": "test", "value": "3", "confidence": "0.9", "extraction_method": "test", "evidence_id": "ev-001"},
            {"fact_id": "fact-001", "fact_type": "test", "value": "1", "confidence": "0.9", "extraction_method": "test", "evidence_id": "ev-001"},
            {"fact_id": "fact-002", "fact_type": "test", "value": "2", "confidence": "0.9", "extraction_method": "test", "evidence_id": "ev-001"},
        ]
        
        tv = create_mock_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=[],
            facts_list=facts,
        )
        
        content = builder.build()
        
        assert content.provenance.facts_list[0].fact_id == "fact-001"
        assert content.provenance.facts_list[1].fact_id == "fact-002"
        assert content.provenance.facts_list[2].fact_id == "fact-003"
    
    def test_key_risks_sorted_by_type(self):
        """Test key risks are sorted by type."""
        from services.report_service.generator import ReportContentBuilder
        
        tv = create_mock_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=[],
            facts_list=[],
        )
        
        content = builder.build()
        
        # credit_risk comes before market_risk alphabetically
        assert content.risk_analysis.key_risks[0]["risk_type"] == "credit_risk"
        assert content.risk_analysis.key_risks[1]["risk_type"] == "market_risk"
    
    def test_fragility_interpretation(self):
        """Test fragility score interpretation."""
        from services.report_service.generator import ReportContentBuilder
        
        tv = create_mock_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=[],
            facts_list=[],
        )
        
        content = builder.build()
        
        assert content.risk_analysis.fragility_score == "0.3500"
        assert "Moderate" in content.risk_analysis.fragility_interpretation


# =============================================================================
# HTML Renderer Tests
# =============================================================================


class TestHTMLRenderer:
    """Test HTMLRenderer."""
    
    def test_render_produces_bytes(self):
        """Test renderer produces UTF-8 bytes."""
        from services.report_service.generator import HTMLRenderer, ReportContentBuilder
        
        tv = create_mock_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=SAMPLE_EVIDENCE_LIST,
            facts_list=SAMPLE_FACTS_LIST,
        )
        content = builder.build()
        
        renderer = HTMLRenderer()
        html = renderer.render(content)
        
        assert isinstance(html, bytes)
        assert b"<!DOCTYPE html>" in html
        assert b"AAPL" in html
    
    def test_render_includes_claim_summary(self):
        """Test rendered HTML includes claim summary."""
        from services.report_service.generator import HTMLRenderer, ReportContentBuilder
        
        tv = create_mock_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=[],
            facts_list=[],
        )
        content = builder.build()
        
        renderer = HTMLRenderer()
        html = renderer.render(content)
        
        assert b"Solvency determination for AAPL" in html
    
    def test_render_includes_truth_version_id(self):
        """Test rendered HTML includes truth_version_id."""
        from services.report_service.generator import HTMLRenderer, ReportContentBuilder
        
        tv = create_mock_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=[],
            facts_list=[],
        )
        content = builder.build()
        
        renderer = HTMLRenderer()
        html = renderer.render(content)
        
        assert b"tv-test-001" in html
    
    def test_render_includes_all_hashes(self):
        """Test rendered HTML includes all integrity hashes."""
        from services.report_service.generator import HTMLRenderer, ReportContentBuilder
        
        tv = create_mock_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=[],
            facts_list=[],
            trace_id="trace-001",
            audit_hash="audit-hash-001",
        )
        content = builder.build()
        
        renderer = HTMLRenderer()
        html = renderer.render(content)
        
        assert b"trace-hash-jkl" in html
        assert b"facts-hash-def" in html
        assert b"evidence-hash-abc" in html
        assert b"policy-hash-ghi" in html
        assert b"result-hash-mno" in html
    
    def test_render_solvent_conclusion(self):
        """Test rendered HTML shows solvent conclusion correctly."""
        from services.report_service.generator import HTMLRenderer, ReportContentBuilder
        
        tv = create_mock_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=[],
            facts_list=[],
        )
        content = builder.build()
        
        renderer = HTMLRenderer()
        html = renderer.render(content)
        
        assert b"Solvent" in html
        assert b"conclusion-solvent" in html
    
    def test_render_refusal(self):
        """Test rendered HTML shows refusal correctly."""
        from services.report_service.generator import HTMLRenderer, ReportContentBuilder
        
        tv = create_mock_refusal_truth_version()
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=[],
            facts_list=[],
        )
        content = builder.build()
        
        renderer = HTMLRenderer()
        html = renderer.render(content)
        
        assert b"Evaluation Refused" in html
        assert b"INSUFFICIENT_DATA" in html


# =============================================================================
# Determinism Tests
# =============================================================================


class TestHTMLDeterminism:
    """Test HTML generation is byte-for-byte deterministic."""
    
    def test_same_input_produces_same_output(self):
        """Test identical inputs produce identical HTML bytes."""
        from services.report_service.generator import HTMLRenderer, ReportContentBuilder
        
        tv = create_mock_truth_version()
        
        # Build and render twice
        builder1 = ReportContentBuilder(
            truth_version=tv,
            evidence_list=SAMPLE_EVIDENCE_LIST,
            facts_list=SAMPLE_FACTS_LIST,
            trace_id="trace-001",
            audit_hash="audit-001",
            report_generated_at=tv.created_at,  # Use fixed timestamp
        )
        content1 = builder1.build()
        
        builder2 = ReportContentBuilder(
            truth_version=tv,
            evidence_list=SAMPLE_EVIDENCE_LIST,
            facts_list=SAMPLE_FACTS_LIST,
            trace_id="trace-001",
            audit_hash="audit-001",
            report_generated_at=tv.created_at,
        )
        content2 = builder2.build()
        
        renderer = HTMLRenderer()
        html1 = renderer.render(content1)
        html2 = renderer.render(content2)
        
        assert html1 == html2
    
    def test_different_evidence_order_produces_same_output(self):
        """Test evidence ordering doesn't affect output."""
        from services.report_service.generator import HTMLRenderer, ReportContentBuilder
        
        tv = create_mock_truth_version()
        
        evidence_ordered = [
            {"evidence_id": "ev-001", "source_type": "test", "sha256_hash": "h1", "reliability": "t1"},
            {"evidence_id": "ev-002", "source_type": "test", "sha256_hash": "h2", "reliability": "t1"},
        ]
        evidence_reversed = [
            {"evidence_id": "ev-002", "source_type": "test", "sha256_hash": "h2", "reliability": "t1"},
            {"evidence_id": "ev-001", "source_type": "test", "sha256_hash": "h1", "reliability": "t1"},
        ]
        
        builder1 = ReportContentBuilder(
            truth_version=tv,
            evidence_list=evidence_ordered,
            facts_list=[],
            report_generated_at=tv.created_at,
        )
        builder2 = ReportContentBuilder(
            truth_version=tv,
            evidence_list=evidence_reversed,
            facts_list=[],
            report_generated_at=tv.created_at,
        )
        
        renderer = HTMLRenderer()
        html1 = renderer.render(builder1.build())
        html2 = renderer.render(builder2.build())
        
        assert html1 == html2


# =============================================================================
# Store Tests
# =============================================================================


class TestReportStore:
    """Test ReportStore."""
    
    @pytest.mark.asyncio
    async def test_store_and_get(self):
        """Test storing and retrieving report metadata."""
        from services.report_service.stores import ReportStore
        from services.report_service.schemas import ReportMetadata, ReportStatus
        from unittest.mock import AsyncMock, MagicMock
        
        # Create mock session
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        
        store = ReportStore(session)
        
        metadata = ReportMetadata(
            report_id="rpt-001",
            truth_version_id="tv-001",
            created_at=datetime(2024, 12, 15, tzinfo=timezone.utc),
            html_hash="html-hash",
            html_uri="s3://reports/rpt-001.html",
            renderer_version="1.0.0",
            status=ReportStatus.COMPLETED,
        )
        
        report_id = await store.store(metadata)
        
        assert report_id == "rpt-001"
        session.add.assert_called_once()
        session.flush.assert_called_once()


class TestArtifactStore:
    """Test ArtifactStore."""
    
    @pytest.mark.asyncio
    async def test_store_html(self):
        """Test storing HTML artifact."""
        from services.report_service.stores import ArtifactStore
        from unittest.mock import AsyncMock, MagicMock
        
        # Create mock object store
        object_store = AsyncMock()
        mock_metadata = MagicMock()
        mock_metadata.key = "reports/tv-001/rpt-001.html"
        mock_metadata.content_hash = "sha256:abc123"
        object_store.put = AsyncMock(return_value=mock_metadata)
        
        store = ArtifactStore(object_store)
        
        uri, content_hash = await store.store_html(
            report_id="rpt-001",
            truth_version_id="tv-001",
            html_content=b"<html></html>",
        )
        
        assert "s3://reports/" in uri
        assert content_hash == "sha256:abc123"
    
    @pytest.mark.asyncio
    async def test_get_html(self):
        """Test retrieving HTML artifact."""
        from services.report_service.stores import ArtifactStore
        from unittest.mock import AsyncMock, MagicMock
        
        object_store = AsyncMock()
        mock_obj = MagicMock()
        mock_obj.content = b"<html>test</html>"
        object_store.get = AsyncMock(return_value=mock_obj)
        
        store = ArtifactStore(object_store)
        
        content = await store.get_html("s3://reports/reports/tv-001/rpt-001.html")
        
        assert content == b"<html>test</html>"


# =============================================================================
# Generator Tests
# =============================================================================


class TestReportGenerator:
    """Test ReportGenerator."""
    
    @pytest.mark.asyncio
    async def test_generate_creates_report(self):
        """Test generating a report."""
        from services.report_service.generator import ReportGenerator, HTMLRenderer
        from services.report_service.stores import ReportStore, ArtifactStore
        from unittest.mock import AsyncMock, MagicMock
        
        # Mock dependencies
        session = AsyncMock()
        session.commit = AsyncMock()
        
        report_store = AsyncMock(spec=ReportStore)
        report_store.find_existing = AsyncMock(return_value=None)
        report_store.store = AsyncMock()
        
        artifact_store = AsyncMock(spec=ArtifactStore)
        artifact_store.store_html = AsyncMock(return_value=("s3://html", "html-hash"))
        artifact_store.store_pdf = AsyncMock(return_value=("s3://pdf", "pdf-hash"))
        
        html_renderer = HTMLRenderer()
        
        generator = ReportGenerator(
            session=session,
            report_store=report_store,
            artifact_store=artifact_store,
            html_renderer=html_renderer,
            pdf_renderer=None,  # Skip PDF
        )
        
        tv = create_mock_truth_version()
        
        response = await generator.generate(
            truth_version=tv,
            evidence_list=SAMPLE_EVIDENCE_LIST,
            facts_list=SAMPLE_FACTS_LIST,
            include_pdf=False,
        )
        
        assert response.was_cached is False
        assert response.html_uri == "s3://html"
        assert response.html_hash == "html-hash"
        report_store.store.assert_called_once()
        session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_generate_returns_cached(self):
        """Test idempotent generation returns cached report."""
        from services.report_service.generator import ReportGenerator
        from services.report_service.stores import ReportStore, ArtifactStore
        from services.report_service.schemas import ReportMetadata, ReportStatus
        from unittest.mock import AsyncMock
        
        session = AsyncMock()
        
        # Simulate existing report
        existing = ReportMetadata(
            report_id="cached-001",
            truth_version_id="tv-test-001",
            created_at=datetime(2024, 12, 15, tzinfo=timezone.utc),
            html_hash="cached-html-hash",
            html_uri="s3://cached-html",
            renderer_version="1.0.0",
            status=ReportStatus.COMPLETED,
        )
        
        report_store = AsyncMock(spec=ReportStore)
        report_store.find_existing = AsyncMock(return_value=existing)
        
        artifact_store = AsyncMock(spec=ArtifactStore)
        
        generator = ReportGenerator(
            session=session,
            report_store=report_store,
            artifact_store=artifact_store,
        )
        
        tv = create_mock_truth_version()
        
        response = await generator.generate(
            truth_version=tv,
            evidence_list=[],
            facts_list=[],
        )
        
        assert response.was_cached is True
        assert response.report_id == "cached-001"
        assert response.html_hash == "cached-html-hash"


# =============================================================================
# Route Tests
# =============================================================================


class TestReportRoutes:
    """Test REST API routes."""
    
    def test_version_endpoint(self):
        """Test version info endpoint."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from services.report_service.routes import router
        
        # Create a simple app without lifespan for testing
        test_app = FastAPI()
        test_app.include_router(router)
        
        client = TestClient(test_app)
        response = client.get("/v1/reports/version")
        
        assert response.status_code == 200
        data = response.json()
        assert "service_version" in data
        assert "html_renderer_version" in data
        assert "pdf_renderer_available" in data
    
    def test_health_endpoint(self):
        """Test health check endpoint."""
        from fastapi.testclient import TestClient
        from services.report_service.app import app
        
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "report-service"


# =============================================================================
# End-to-End Tests
# =============================================================================


class TestEndToEnd:
    """End-to-end tests for report generation."""
    
    def test_full_content_build_and_render(self):
        """Test full pipeline from TruthVersion to HTML."""
        from services.report_service.generator import ReportContentBuilder, HTMLRenderer
        from shared.hashing import hash_content
        
        tv = create_mock_truth_version()
        
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=SAMPLE_EVIDENCE_LIST,
            facts_list=SAMPLE_FACTS_LIST,
            trace_id="trace-001",
            audit_hash="audit-hash-001",
            metrics=[
                {"name": "current_ratio", "value": "1.21", "unit": "ratio"},
                {"name": "debt_to_equity", "value": "0.82", "unit": "ratio"},
            ],
        )
        
        content = builder.build()
        
        # Verify all required sections
        assert content.claim.entity_id == "AAPL"
        assert content.evaluation_metadata.evaluation_id == "eval-test-001"
        assert content.conclusion.conclusion == "solvent"
        assert content.probability.has_probability is True
        assert content.risk_analysis.fragility_score is not None
        assert len(content.provenance.evidence_list) == 2
        assert len(content.provenance.facts_list) == 2
        
        # Render to HTML
        renderer = HTMLRenderer()
        html = renderer.render(content)
        
        # Verify HTML
        assert b"<!DOCTYPE html>" in html
        assert b"AAPL" in html
        assert b"Solvent" in html
        assert b"current_ratio" in html
        
        # Verify deterministic hash
        html_hash1 = hash_content(html)
        html_hash2 = hash_content(html)
        assert html_hash1.digest == html_hash2.digest
    
    def test_full_refusal_content_build_and_render(self):
        """Test full pipeline for refusal TruthVersion."""
        from services.report_service.generator import ReportContentBuilder, HTMLRenderer
        
        tv = create_mock_refusal_truth_version()
        
        builder = ReportContentBuilder(
            truth_version=tv,
            evidence_list=[],
            facts_list=[],
        )
        
        content = builder.build()
        
        # Verify refusal handling
        assert content.conclusion.is_refusal is True
        assert content.conclusion.refusal_code == "INSUFFICIENT_DATA"
        assert content.probability.has_probability is False
        
        # Render to HTML
        renderer = HTMLRenderer()
        html = renderer.render(content)
        
        # Verify refusal in HTML
        assert b"Evaluation Refused" in html
        assert b"INSUFFICIENT_DATA" in html


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Test service constants."""
    
    def test_service_version_format(self):
        """Test service version is valid semver."""
        from services.report_service.schemas import REPORT_SERVICE_VERSION
        
        parts = REPORT_SERVICE_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)
    
    def test_renderer_version_format(self):
        """Test HTML renderer version is valid semver."""
        from services.report_service.schemas import HTML_RENDERER_VERSION
        
        parts = HTML_RENDERER_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)
    
    def test_pdf_renderer_version_pinned(self):
        """Test PDF renderer version is pinned."""
        from services.report_service.schemas import PDF_RENDERER_VERSION
        
        assert "weasyprint" in PDF_RENDERER_VERSION
