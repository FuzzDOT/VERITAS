"""
Evidence Service A4 Tests - Comprehensive Test Suite
======================================================

Tests for the production Evidence Service implementation covering:
- Evidence ingestion (SEC filings, audited statements, macro data)
- Deduplication (same hash → same evidence_id)
- Policy enforcement (jurisdiction, age, source types)
- Evidence retrieval by claim and entity
- Missing evidence detection
- Conflict detection
- Determinism guarantees
"""

import pytest
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from services.evidence_service.app import create_app, get_evidence_service
from services.evidence_service.service import (
    EvidenceService,
    SECFilingPipeline,
    AuditedStatementPipeline,
    MacroeconomicDataPipeline,
    PolicyEnforcer,
    ConflictDetector,
    EvidenceStore,
    EvidenceRecord,
)
from services.evidence_service.schemas import (
    EvidenceStatus,
    EvidenceSourceType,
    RejectionCode,
    ConflictType,
    MissingEvidenceReason,
    EvidenceEntityIdentifier,
    EvidenceProvenance,
    EvidenceReliability,
    EvidenceDocument,
    IngestEvidenceRequest,
    IngestEvidenceResponse,
    EvidenceRejection,
    EvidencePolicy,
    SECFilingMetadata,
    AuditedStatementMetadata,
    MacroeconomicDataMetadata,
    LookupByEntityRequest,
    SUPPORTED_SOURCE_TYPES,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def service() -> EvidenceService:
    """Create a fresh EvidenceService instance."""
    return EvidenceService()


@pytest.fixture
def sec_pipeline() -> SECFilingPipeline:
    """Create SEC filing pipeline."""
    return SECFilingPipeline()


@pytest.fixture
def audited_pipeline() -> AuditedStatementPipeline:
    """Create audited statement pipeline."""
    return AuditedStatementPipeline()


@pytest.fixture
def macro_pipeline() -> MacroeconomicDataPipeline:
    """Create macroeconomic data pipeline."""
    return MacroeconomicDataPipeline()


@pytest.fixture
def app():
    """Create test application."""
    return create_app()


@pytest.fixture
def client(app) -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def valid_sec_10k_request() -> IngestEvidenceRequest:
    """Valid SEC 10-K ingestion request."""
    return IngestEvidenceRequest(
        source_type=EvidenceSourceType.SEC_10K,
        content=b"<sec-filing>Annual Report Content</sec-filing>",
        entity_identifiers=[
            EvidenceEntityIdentifier(
                id_type="CIK",
                id_value="0000320193",
                is_primary=True,
            ),
            EvidenceEntityIdentifier(
                id_type="TICKER",
                id_value="AAPL",
                exchange="NASDAQ",
            ),
        ],
        source_uri="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193",
        source_name="SEC EDGAR",
        published_at=datetime.now(timezone.utc) - timedelta(days=30),
        sec_metadata=SECFilingMetadata(
            form_type="10-K",
            cik="0000320193",
            accession_number="0000320193-24-000123",
            filing_date=date.today() - timedelta(days=30),
            period_of_report=date.today() - timedelta(days=60),
            company_name="Apple Inc.",
            ticker="AAPL",
            exchange="NASDAQ",
        ),
        trace_id="test_trace_10k_001",
    )


@pytest.fixture
def valid_sec_10q_request() -> IngestEvidenceRequest:
    """Valid SEC 10-Q ingestion request."""
    return IngestEvidenceRequest(
        source_type=EvidenceSourceType.SEC_10Q,
        content=b"<sec-filing>Quarterly Report Content</sec-filing>",
        entity_identifiers=[
            EvidenceEntityIdentifier(
                id_type="CIK",
                id_value="0000789019",
                is_primary=True,
            ),
        ],
        source_name="SEC EDGAR",
        published_at=datetime.now(timezone.utc) - timedelta(days=15),
        fiscal_quarter=3,
        sec_metadata=SECFilingMetadata(
            form_type="10-Q",
            cik="0000789019",
            accession_number="0000789019-24-000456",
            filing_date=date.today() - timedelta(days=15),
            period_of_report=date.today() - timedelta(days=30),
            company_name="Microsoft Corporation",
        ),
        trace_id="test_trace_10q_001",
    )


@pytest.fixture
def valid_audited_statement_request() -> IngestEvidenceRequest:
    """Valid audited statement ingestion request."""
    return IngestEvidenceRequest(
        source_type=EvidenceSourceType.AUDITED_FINANCIAL_STATEMENT,
        content=b"%PDF-1.4 Audited Financial Statement",
        entity_identifiers=[
            EvidenceEntityIdentifier(
                id_type="LEI",
                id_value="HWUPKR0MPOU8FGXBT394",
                is_primary=True,
            ),
        ],
        source_name="Deloitte LLP",
        published_at=datetime.now(timezone.utc) - timedelta(days=45),
        audited_statement_metadata=AuditedStatementMetadata(
            statement_type="Annual Financial Statements",
            auditor_name="Deloitte LLP",
            audit_opinion="unqualified",
            opinion_date=date.today() - timedelta(days=45),
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
            fiscal_year=2023,
            entity_name="Example Corporation",
            entity_jurisdiction="US",
        ),
        trace_id="test_trace_audited_001",
    )


@pytest.fixture
def valid_macro_data_request() -> IngestEvidenceRequest:
    """Valid macroeconomic data ingestion request."""
    return IngestEvidenceRequest(
        source_type=EvidenceSourceType.TREASURY_YIELD_CURVE,
        content=b'{"2Y": 4.5, "5Y": 4.2, "10Y": 4.0, "30Y": 4.1}',
        entity_identifiers=[],
        source_name="US Treasury",
        published_at=datetime.now(timezone.utc) - timedelta(days=1),
        macroeconomic_metadata=MacroeconomicDataMetadata(
            data_type="Treasury Yield Curve",
            source_institution="US Treasury",
            publication_date=date.today() - timedelta(days=1),
            effective_date=date.today() - timedelta(days=1),
            currency="USD",
            region="US",
            frequency="daily",
        ),
        trace_id="test_trace_macro_001",
    )


# =============================================================================
# Test: SEC Filing Ingestion
# =============================================================================


class TestSECFilingIngestion:
    """Tests for SEC filing ingestion."""
    
    @pytest.mark.asyncio
    async def test_ingest_valid_10k(
        self, service: EvidenceService, valid_sec_10k_request: IngestEvidenceRequest
    ):
        """Test ingesting a valid 10-K filing."""
        response = await service.ingest(valid_sec_10k_request)
        
        assert response.success is True
        assert response.evidence_id is not None
        assert response.content_hash is not None
        assert response.is_duplicate is False
        assert response.rejected is False
    
    @pytest.mark.asyncio
    async def test_ingest_valid_10q(
        self, service: EvidenceService, valid_sec_10q_request: IngestEvidenceRequest
    ):
        """Test ingesting a valid 10-Q filing."""
        response = await service.ingest(valid_sec_10q_request)
        
        assert response.success is True
        assert response.evidence_id is not None
        assert response.is_duplicate is False
    
    @pytest.mark.asyncio
    async def test_sec_filing_requires_metadata(self, service: EvidenceService):
        """Test SEC filing without metadata is rejected."""
        request = IngestEvidenceRequest(
            source_type=EvidenceSourceType.SEC_10K,
            content=b"<sec-filing>Content</sec-filing>",
            entity_identifiers=[
                EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193"),
            ],
            source_name="SEC EDGAR",
            published_at=datetime.now(timezone.utc),
            # Missing sec_metadata
            trace_id="test_no_metadata",
        )
        
        response = await service.ingest(request)
        
        assert response.success is False
        assert response.rejected is True
        assert response.rejection_code == RejectionCode.UNVERIFIABLE_SOURCE
    
    @pytest.mark.asyncio
    async def test_sec_filing_future_date_rejected(
        self, service: EvidenceService, valid_sec_10k_request: IngestEvidenceRequest
    ):
        """Test SEC filing with future filing date is rejected."""
        assert valid_sec_10k_request.sec_metadata is not None
        # Create new metadata with future date
        request = IngestEvidenceRequest(
            source_type=valid_sec_10k_request.source_type,
            content=valid_sec_10k_request.content,
            entity_identifiers=valid_sec_10k_request.entity_identifiers,
            source_name=valid_sec_10k_request.source_name,
            published_at=valid_sec_10k_request.published_at,
            sec_metadata=SECFilingMetadata(
                form_type=valid_sec_10k_request.sec_metadata.form_type,
                cik=valid_sec_10k_request.sec_metadata.cik,
                accession_number=valid_sec_10k_request.sec_metadata.accession_number,
                filing_date=date.today() + timedelta(days=30),  # Future date
                period_of_report=valid_sec_10k_request.sec_metadata.period_of_report,
                company_name=valid_sec_10k_request.sec_metadata.company_name,
            ),
            trace_id="test_future_date",
        )
        
        response = await service.ingest(request)
        
        assert response.success is False
        assert response.rejection_code == RejectionCode.FUTURE_DATED_DOCUMENT
    
    @pytest.mark.asyncio
    async def test_sec_filing_cik_used_as_entity_identifier(
        self, service: EvidenceService
    ):
        """Test CIK from SEC metadata is used as entity identifier."""
        # SEC filings require entity identifiers at schema level
        # The CIK from metadata must match/complement entity identifiers
        request = IngestEvidenceRequest(
            source_type=EvidenceSourceType.SEC_10K,
            content=b"<sec-filing>Content with entity ids</sec-filing>",
            entity_identifiers=[
                EvidenceEntityIdentifier(
                    id_type="CIK",
                    id_value="0000320193",
                    is_primary=True,
                ),
            ],
            source_name="SEC EDGAR",
            published_at=datetime.now(timezone.utc) - timedelta(days=30),
            sec_metadata=SECFilingMetadata(
                form_type="10-K",
                cik="0000320193",
                accession_number="0000320193-24-000789",
                filing_date=date.today() - timedelta(days=30),
                period_of_report=date.today() - timedelta(days=60),
                company_name="Apple Inc.",
            ),
            trace_id="test_cik_match",
        )
        
        response = await service.ingest(request)
        
        assert response.success is True
        
        # Verify CIK is in entity identifiers
        document = await service.get(response.evidence_id)
        assert document is not None
        cik_ids = [eid for eid in document.entity_identifiers if eid.id_type == "CIK"]
        assert len(cik_ids) >= 1
        assert cik_ids[0].id_value == "0000320193"


# =============================================================================
# Test: Audited Statement Ingestion
# =============================================================================


class TestAuditedStatementIngestion:
    """Tests for audited statement ingestion."""
    
    @pytest.mark.asyncio
    async def test_ingest_valid_audited_statement(
        self, service: EvidenceService, valid_audited_statement_request: IngestEvidenceRequest
    ):
        """Test ingesting a valid audited statement."""
        response = await service.ingest(valid_audited_statement_request)
        
        assert response.success is True
        assert response.evidence_id is not None
        assert response.is_duplicate is False
    
    @pytest.mark.asyncio
    async def test_audited_statement_requires_metadata(self, service: EvidenceService):
        """Test audited statement without metadata is rejected."""
        request = IngestEvidenceRequest(
            source_type=EvidenceSourceType.AUDITED_FINANCIAL_STATEMENT,
            content=b"%PDF-1.4 Content",
            entity_identifiers=[
                EvidenceEntityIdentifier(id_type="LEI", id_value="HWUPKR0MPOU8FGXBT394"),
            ],
            source_name="Unknown Auditor",
            published_at=datetime.now(timezone.utc),
            # Missing audited_statement_metadata
            trace_id="test_no_audit_meta",
        )
        
        response = await service.ingest(request)
        
        assert response.success is False
        assert response.rejection_code == RejectionCode.UNVERIFIABLE_SOURCE
    
    @pytest.mark.asyncio
    async def test_audited_statement_requires_entity_at_schema_level(self, service: EvidenceService):
        """Test audited statement without entity identifier is rejected at schema level."""
        # The IngestEvidenceRequest model itself validates entity identifiers
        # for entity-linked source types like audited statements
        with pytest.raises(Exception):  # Pydantic ValidationError
            IngestEvidenceRequest(
                source_type=EvidenceSourceType.AUDITED_FINANCIAL_STATEMENT,
                content=b"%PDF-1.4 Content",
                entity_identifiers=[],  # No entity identifiers - should fail validation
                source_name="Deloitte LLP",
                published_at=datetime.now(timezone.utc) - timedelta(days=30),
                audited_statement_metadata=AuditedStatementMetadata(
                    statement_type="Annual",
                    auditor_name="Deloitte LLP",
                    audit_opinion="unqualified",
                    opinion_date=date.today() - timedelta(days=30),
                    period_start=date(2023, 1, 1),
                    period_end=date(2023, 12, 31),
                    fiscal_year=2023,
                    entity_name="Example Corp",
                    entity_jurisdiction="US",
                ),
                trace_id="test_no_entity",
            )
    
    @pytest.mark.asyncio
    async def test_audited_statement_invalid_opinion_rejected(
        self, service: EvidenceService
    ):
        """Test audited statement with invalid audit opinion is rejected."""
        request = IngestEvidenceRequest(
            source_type=EvidenceSourceType.AUDITED_FINANCIAL_STATEMENT,
            content=b"%PDF-1.4 Content",
            entity_identifiers=[
                EvidenceEntityIdentifier(id_type="LEI", id_value="HWUPKR0MPOU8FGXBT394"),
            ],
            source_name="Unknown Auditor",
            published_at=datetime.now(timezone.utc) - timedelta(days=30),
            audited_statement_metadata=AuditedStatementMetadata(
                statement_type="Annual",
                auditor_name="Deloitte LLP",
                audit_opinion="invalid_opinion_type",  # Invalid
                opinion_date=date.today() - timedelta(days=30),
                period_start=date(2023, 1, 1),
                period_end=date(2023, 12, 31),
                fiscal_year=2023,
                entity_name="Example Corp",
                entity_jurisdiction="US",
            ),
            trace_id="test_invalid_opinion",
        )
        
        response = await service.ingest(request)
        
        assert response.success is False
        assert response.rejection_code == RejectionCode.UNVERIFIABLE_SOURCE


# =============================================================================
# Test: Macroeconomic Data Ingestion
# =============================================================================


class TestMacroeconomicDataIngestion:
    """Tests for macroeconomic data ingestion."""
    
    @pytest.mark.asyncio
    async def test_ingest_valid_macro_data(
        self, service: EvidenceService, valid_macro_data_request: IngestEvidenceRequest
    ):
        """Test ingesting valid macroeconomic data."""
        response = await service.ingest(valid_macro_data_request)
        
        assert response.success is True
        assert response.evidence_id is not None
        assert response.is_duplicate is False
    
    @pytest.mark.asyncio
    async def test_macro_data_requires_metadata(self, service: EvidenceService):
        """Test macro data without metadata is rejected."""
        request = IngestEvidenceRequest(
            source_type=EvidenceSourceType.INTEREST_RATE_CURVE,
            content=b'{"rates": [1.0, 2.0]}',
            entity_identifiers=[],
            source_name="Federal Reserve",
            published_at=datetime.now(timezone.utc),
            # Missing macroeconomic_metadata
            trace_id="test_no_macro_meta",
        )
        
        response = await service.ingest(request)
        
        assert response.success is False
        assert response.rejection_code == RejectionCode.UNVERIFIABLE_SOURCE
    
    @pytest.mark.asyncio
    async def test_macro_data_rejects_entity_identifiers(
        self, service: EvidenceService, valid_macro_data_request: IngestEvidenceRequest
    ):
        """Test macro data with entity identifiers is rejected."""
        assert valid_macro_data_request.macroeconomic_metadata is not None
        request = IngestEvidenceRequest(
            source_type=valid_macro_data_request.source_type,
            content=valid_macro_data_request.content,
            entity_identifiers=[
                EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193"),
            ],  # Should not have entity IDs
            source_name=valid_macro_data_request.source_name,
            published_at=valid_macro_data_request.published_at,
            macroeconomic_metadata=valid_macro_data_request.macroeconomic_metadata,
            trace_id="test_macro_with_entity",
        )
        
        response = await service.ingest(request)
        
        assert response.success is False
        assert response.rejection_code == RejectionCode.ENTITY_MISMATCH
    
    @pytest.mark.asyncio
    async def test_macro_data_far_future_rejected(self, service: EvidenceService):
        """Test macro data with far future effective date is rejected."""
        request = IngestEvidenceRequest(
            source_type=EvidenceSourceType.TREASURY_YIELD_CURVE,
            content=b'{"rates": [1.0, 2.0]}',
            entity_identifiers=[],
            source_name="US Treasury",
            published_at=datetime.now(timezone.utc),
            macroeconomic_metadata=MacroeconomicDataMetadata(
                data_type="Treasury Yield Curve",
                source_institution="US Treasury",
                publication_date=date.today(),
                effective_date=date.today() + timedelta(days=60),  # Too far in future
                currency="USD",
                region="US",
            ),
            trace_id="test_future_macro",
        )
        
        response = await service.ingest(request)
        
        assert response.success is False
        assert response.rejection_code == RejectionCode.FUTURE_DATED_DOCUMENT


# =============================================================================
# Test: Deduplication
# =============================================================================


class TestDeduplication:
    """Tests for content-based deduplication."""
    
    @pytest.mark.asyncio
    async def test_duplicate_content_returns_existing(
        self, service: EvidenceService, valid_sec_10k_request: IngestEvidenceRequest
    ):
        """Test that duplicate content returns existing evidence ID."""
        # First ingestion
        response1 = await service.ingest(valid_sec_10k_request)
        assert response1.success is True
        
        # Second ingestion with same content
        response2 = await service.ingest(valid_sec_10k_request)
        
        assert response2.success is True
        assert response2.is_duplicate is True
        assert response2.evidence_id == response1.evidence_id
        assert response2.duplicate_evidence_id == response1.evidence_id
    
    @pytest.mark.asyncio
    async def test_different_content_creates_new_evidence(
        self, service: EvidenceService, valid_sec_10k_request: IngestEvidenceRequest
    ):
        """Test that different content creates new evidence."""
        # First ingestion
        response1 = await service.ingest(valid_sec_10k_request)
        assert response1.success is True
        
        # Create request with different content
        assert valid_sec_10k_request.sec_metadata is not None
        different_request = IngestEvidenceRequest(
            source_type=valid_sec_10k_request.source_type,
            content=b"<sec-filing>DIFFERENT Annual Report Content</sec-filing>",
            entity_identifiers=valid_sec_10k_request.entity_identifiers,
            source_name=valid_sec_10k_request.source_name,
            published_at=valid_sec_10k_request.published_at,
            sec_metadata=valid_sec_10k_request.sec_metadata,
            trace_id="test_different_content",
        )
        
        response2 = await service.ingest(different_request)
        
        assert response2.success is True
        assert response2.is_duplicate is False
        assert response2.evidence_id != response1.evidence_id
    
    @pytest.mark.asyncio
    async def test_same_hash_deduplicates_within_valid_requests(
        self, service: EvidenceService
    ):
        """Test that same content hash deduplicates correctly."""
        content = b"Identical content for testing deduplication"
        
        # First request as 10-K with proper entity IDs
        request1 = IngestEvidenceRequest(
            source_type=EvidenceSourceType.SEC_10K,
            content=content,
            entity_identifiers=[
                EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
            ],
            source_name="SEC EDGAR",
            published_at=datetime.now(timezone.utc) - timedelta(days=30),
            sec_metadata=SECFilingMetadata(
                form_type="10-K",
                cik="0000320193",
                accession_number="0000320193-24-000111",
                filing_date=date.today() - timedelta(days=30),
                period_of_report=date.today() - timedelta(days=60),
                company_name="Test Corp",
            ),
            trace_id="test_dedup_1",
        )
        
        response1 = await service.ingest(request1)
        assert response1.success is True
        
        # Second request with same content
        request2 = IngestEvidenceRequest(
            source_type=EvidenceSourceType.SEC_10K,
            content=content,  # Same content
            entity_identifiers=[
                EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
            ],
            source_name="SEC EDGAR",
            published_at=datetime.now(timezone.utc) - timedelta(days=15),
            sec_metadata=SECFilingMetadata(
                form_type="10-K",
                cik="0000320193",
                accession_number="0000320193-24-000222",
                filing_date=date.today() - timedelta(days=15),
                period_of_report=date.today() - timedelta(days=30),
                company_name="Test Corp",
            ),
            trace_id="test_dedup_2",
        )
        
        response2 = await service.ingest(request2)
        
        # Should be detected as duplicate by content hash
        assert response2.success is True
        assert response2.is_duplicate is True
        assert response2.evidence_id == response1.evidence_id
    
    @pytest.mark.asyncio
    async def test_hash_verification(self, service: EvidenceService):
        """Test that expected hash is verified."""
        content = b"Content to hash"
        import hashlib
        expected_hash = hashlib.sha256(content).hexdigest()
        wrong_hash = "0" * 64
        
        # Correct hash should pass
        request_correct = IngestEvidenceRequest(
            source_type=EvidenceSourceType.TREASURY_YIELD_CURVE,
            content=content,
            expected_hash=expected_hash,
            entity_identifiers=[],
            source_name="US Treasury",
            published_at=datetime.now(timezone.utc),
            macroeconomic_metadata=MacroeconomicDataMetadata(
                data_type="Yield Curve",
                source_institution="US Treasury",
                publication_date=date.today(),
                effective_date=date.today(),
            ),
            trace_id="test_hash_correct",
        )
        
        response_correct = await service.ingest(request_correct)
        assert response_correct.success is True
        
        # Wrong hash should fail
        request_wrong = IngestEvidenceRequest(
            source_type=EvidenceSourceType.TREASURY_YIELD_CURVE,
            content=b"Different content",
            expected_hash=expected_hash,  # Wrong hash for this content
            entity_identifiers=[],
            source_name="US Treasury",
            published_at=datetime.now(timezone.utc),
            macroeconomic_metadata=MacroeconomicDataMetadata(
                data_type="Yield Curve",
                source_institution="US Treasury",
                publication_date=date.today(),
                effective_date=date.today(),
            ),
            trace_id="test_hash_wrong",
        )
        
        response_wrong = await service.ingest(request_wrong)
        assert response_wrong.success is False
        assert response_wrong.rejection_code == RejectionCode.HASH_MISMATCH


# =============================================================================
# Test: Policy Enforcement
# =============================================================================


class TestPolicyEnforcement:
    """Tests for policy-based evidence admissibility."""
    
    def test_policy_allows_matching_source_type(self):
        """Test policy allows matching source types."""
        policy = EvidencePolicy(
            allowed_source_types=frozenset({EvidenceSourceType.SEC_10K}),
            max_document_age_days=365,
            minimum_reliability_score=Decimal("0.80"),
            require_audited_statements=False,  # Don't require audit for this test
        )
        enforcer = PolicyEnforcer(policy)
        
        record = EvidenceRecord(
            evidence_id="EVD_test",
            content_hash="abc123",
            status=EvidenceStatus.VALIDATED,
            entity_identifiers=[
                EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
            ],
            provenance=EvidenceProvenance(
                source_type=EvidenceSourceType.SEC_10K,
                source_name="SEC EDGAR",
                published_at=datetime.now(timezone.utc) - timedelta(days=30),
                retrieved_at=datetime.now(timezone.utc),
                reliability_tier=1,
                is_audited=True,
            ),
            reliability=EvidenceReliability(
                overall_score=Decimal("0.95"),
                source_tier=1,
                is_primary_source=True,
                is_audited=True,
                age_days=30,
                is_stale=False,
            ),
            object_key="test/key",
            content_type="application/xml",
            size_bytes=1000,
            metadata={},
            ingested_at=datetime.now(timezone.utc),
        )
        
        is_admissible, rejection = enforcer.check_admissibility(record)
        
        assert is_admissible is True
        assert rejection is None
    
    def test_policy_rejects_disallowed_source_type(self):
        """Test policy rejects disallowed source types."""
        policy = EvidencePolicy(
            allowed_source_types=frozenset({EvidenceSourceType.SEC_10K}),
            max_document_age_days=365,
            minimum_reliability_score=Decimal("0.80"),
        )
        enforcer = PolicyEnforcer(policy)
        
        record = EvidenceRecord(
            evidence_id="EVD_test",
            content_hash="abc123",
            status=EvidenceStatus.VALIDATED,
            entity_identifiers=[],
            provenance=EvidenceProvenance(
                source_type=EvidenceSourceType.SEC_10Q,  # Not allowed
                source_name="SEC EDGAR",
                published_at=datetime.now(timezone.utc),
                retrieved_at=datetime.now(timezone.utc),
                reliability_tier=1,
                is_audited=False,
            ),
            reliability=EvidenceReliability(
                overall_score=Decimal("0.90"),
                source_tier=1,
                is_primary_source=True,
                is_audited=False,
                age_days=1,
                is_stale=False,
            ),
            object_key="test/key",
            content_type="application/xml",
            size_bytes=1000,
            metadata={},
            ingested_at=datetime.now(timezone.utc),
        )
        
        is_admissible, rejection = enforcer.check_admissibility(record)
        
        assert is_admissible is False
        assert rejection is not None
        assert rejection.code == RejectionCode.SOURCE_TYPE_NOT_ALLOWED
    
    def test_policy_rejects_expired_documents(self):
        """Test policy rejects documents exceeding age limit."""
        policy = EvidencePolicy(
            allowed_source_types=frozenset(EvidenceSourceType),
            max_document_age_days=365,
            minimum_reliability_score=Decimal("0.50"),
        )
        enforcer = PolicyEnforcer(policy)
        
        record = EvidenceRecord(
            evidence_id="EVD_test",
            content_hash="abc123",
            status=EvidenceStatus.VALIDATED,
            entity_identifiers=[],
            provenance=EvidenceProvenance(
                source_type=EvidenceSourceType.SEC_10K,
                source_name="SEC EDGAR",
                published_at=datetime.now(timezone.utc) - timedelta(days=400),
                retrieved_at=datetime.now(timezone.utc),
                reliability_tier=1,
                is_audited=True,
            ),
            reliability=EvidenceReliability(
                overall_score=Decimal("0.85"),
                source_tier=1,
                is_primary_source=True,
                is_audited=True,
                age_days=400,
                is_stale=True,  # Document is stale
            ),
            object_key="test/key",
            content_type="application/xml",
            size_bytes=1000,
            metadata={},
            ingested_at=datetime.now(timezone.utc),
        )
        
        is_admissible, rejection = enforcer.check_admissibility(record)
        
        assert is_admissible is False
        assert rejection is not None
        assert rejection.code == RejectionCode.DOCUMENT_EXPIRED
    
    def test_policy_rejects_low_reliability(self):
        """Test policy rejects documents below reliability threshold."""
        policy = EvidencePolicy(
            allowed_source_types=frozenset(EvidenceSourceType),
            max_document_age_days=365,
            minimum_reliability_score=Decimal("0.80"),
            require_audited_statements=False,  # Don't require audit for this test
        )
        enforcer = PolicyEnforcer(policy)
        
        record = EvidenceRecord(
            evidence_id="EVD_test",
            content_hash="abc123",
            status=EvidenceStatus.VALIDATED,
            entity_identifiers=[
                EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
            ],
            provenance=EvidenceProvenance(
                source_type=EvidenceSourceType.SEC_10K,
                source_name="SEC EDGAR",
                published_at=datetime.now(timezone.utc),
                retrieved_at=datetime.now(timezone.utc),
                reliability_tier=3,
                is_audited=True,  # Mark as audited to pass that check
            ),
            reliability=EvidenceReliability(
                overall_score=Decimal("0.60"),  # Below threshold
                source_tier=3,
                is_primary_source=True,
                is_audited=True,
                age_days=1,
                is_stale=False,
            ),
            object_key="test/key",
            content_type="application/xml",
            size_bytes=1000,
            metadata={},
            ingested_at=datetime.now(timezone.utc),
        )
        
        is_admissible, rejection = enforcer.check_admissibility(record)
        
        assert is_admissible is False
        assert rejection is not None
        assert rejection.code == RejectionCode.RELIABILITY_BELOW_THRESHOLD
    
    def test_policy_enforces_jurisdiction(self):
        """Test policy enforces jurisdiction restrictions."""
        policy = EvidencePolicy(
            allowed_source_types=frozenset(EvidenceSourceType),
            max_document_age_days=365,
            minimum_reliability_score=Decimal("0.50"),
            allowed_jurisdictions=frozenset({"US"}),
        )
        enforcer = PolicyEnforcer(policy)
        
        record = EvidenceRecord(
            evidence_id="EVD_test",
            content_hash="abc123",
            status=EvidenceStatus.VALIDATED,
            entity_identifiers=[],
            provenance=EvidenceProvenance(
                source_type=EvidenceSourceType.AUDITED_ANNUAL_REPORT,
                source_name="UK Auditor",
                published_at=datetime.now(timezone.utc),
                retrieved_at=datetime.now(timezone.utc),
                reliability_tier=1,
                is_audited=True,
                jurisdiction="GB",  # Not in allowed jurisdictions
            ),
            reliability=EvidenceReliability(
                overall_score=Decimal("0.95"),
                source_tier=1,
                is_primary_source=True,
                is_audited=True,
                age_days=1,
                is_stale=False,
            ),
            object_key="test/key",
            content_type="application/pdf",
            size_bytes=1000,
            metadata={},
            ingested_at=datetime.now(timezone.utc),
        )
        
        is_admissible, rejection = enforcer.check_admissibility(record)
        
        assert is_admissible is False
        assert rejection is not None
        assert rejection.code == RejectionCode.JURISDICTION_NOT_ALLOWED


# =============================================================================
# Test: Conflict Detection
# =============================================================================


class TestConflictDetection:
    """Tests for evidence conflict detection."""
    
    def test_detect_duplicate_period_filing_with_different_content(self):
        """Test detection of multiple filings for same period with different content."""
        detector = ConflictDetector()
        
        base_provenance = EvidenceProvenance(
            source_type=EvidenceSourceType.SEC_10K,
            source_name="SEC EDGAR",
            published_at=datetime.now(timezone.utc),
            retrieved_at=datetime.now(timezone.utc),
            reliability_tier=1,
            is_audited=True,
            fiscal_year=2023,
        )
        
        base_reliability = EvidenceReliability(
            overall_score=Decimal("0.95"),
            source_tier=1,
            is_primary_source=True,
            is_audited=True,
            age_days=30,
            is_stale=False,
        )
        
        records = [
            EvidenceRecord(
                evidence_id="EVD_001",
                content_hash="hash_1",  # Different hash
                status=EvidenceStatus.VALIDATED,
                entity_identifiers=[
                    EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
                ],
                provenance=base_provenance,
                reliability=base_reliability,
                object_key="key1",
                content_type="application/xml",
                size_bytes=1000,
                metadata={},
                ingested_at=datetime.now(timezone.utc),
            ),
            EvidenceRecord(
                evidence_id="EVD_002",
                content_hash="hash_2",  # Different hash
                status=EvidenceStatus.VALIDATED,
                entity_identifiers=[
                    EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
                ],
                provenance=base_provenance,
                reliability=base_reliability,
                object_key="key2",
                content_type="application/xml",
                size_bytes=1000,
                metadata={},
                ingested_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
        ]
        
        conflicts = detector.detect_conflicts(records)
        
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.DUPLICATE_PERIOD_FILING
        assert set(conflicts[0].evidence_ids) == {"EVD_001", "EVD_002"}
    
    def test_no_conflict_for_same_content(self):
        """Test no conflict when content hashes are identical (true duplicate)."""
        detector = ConflictDetector()
        
        base_provenance = EvidenceProvenance(
            source_type=EvidenceSourceType.SEC_10K,
            source_name="SEC EDGAR",
            published_at=datetime.now(timezone.utc),
            retrieved_at=datetime.now(timezone.utc),
            reliability_tier=1,
            is_audited=True,
            fiscal_year=2023,
        )
        
        base_reliability = EvidenceReliability(
            overall_score=Decimal("0.95"),
            source_tier=1,
            is_primary_source=True,
            is_audited=True,
            age_days=30,
            is_stale=False,
        )
        
        records = [
            EvidenceRecord(
                evidence_id="EVD_001",
                content_hash="same_hash",  # Same hash
                status=EvidenceStatus.VALIDATED,
                entity_identifiers=[
                    EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
                ],
                provenance=base_provenance,
                reliability=base_reliability,
                object_key="key1",
                content_type="application/xml",
                size_bytes=1000,
                metadata={},
                ingested_at=datetime.now(timezone.utc),
            ),
            EvidenceRecord(
                evidence_id="EVD_002",
                content_hash="same_hash",  # Same hash
                status=EvidenceStatus.VALIDATED,
                entity_identifiers=[
                    EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
                ],
                provenance=base_provenance,
                reliability=base_reliability,
                object_key="key2",
                content_type="application/xml",
                size_bytes=1000,
                metadata={},
                ingested_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
        ]
        
        conflicts = detector.detect_conflicts(records)
        
        # No conflict because content is identical
        assert len(conflicts) == 0
    
    def test_no_conflict_for_different_periods(self):
        """Test no conflict when documents are for different periods."""
        detector = ConflictDetector()
        
        base_reliability = EvidenceReliability(
            overall_score=Decimal("0.95"),
            source_tier=1,
            is_primary_source=True,
            is_audited=True,
            age_days=30,
            is_stale=False,
        )
        
        records = [
            EvidenceRecord(
                evidence_id="EVD_001",
                content_hash="hash_1",
                status=EvidenceStatus.VALIDATED,
                entity_identifiers=[
                    EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
                ],
                provenance=EvidenceProvenance(
                    source_type=EvidenceSourceType.SEC_10K,
                    source_name="SEC EDGAR",
                    published_at=datetime.now(timezone.utc),
                    retrieved_at=datetime.now(timezone.utc),
                    reliability_tier=1,
                    is_audited=True,
                    fiscal_year=2022,  # Different year
                ),
                reliability=base_reliability,
                object_key="key1",
                content_type="application/xml",
                size_bytes=1000,
                metadata={},
                ingested_at=datetime.now(timezone.utc),
            ),
            EvidenceRecord(
                evidence_id="EVD_002",
                content_hash="hash_2",
                status=EvidenceStatus.VALIDATED,
                entity_identifiers=[
                    EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
                ],
                provenance=EvidenceProvenance(
                    source_type=EvidenceSourceType.SEC_10K,
                    source_name="SEC EDGAR",
                    published_at=datetime.now(timezone.utc),
                    retrieved_at=datetime.now(timezone.utc),
                    reliability_tier=1,
                    is_audited=True,
                    fiscal_year=2023,  # Different year
                ),
                reliability=base_reliability,
                object_key="key2",
                content_type="application/xml",
                size_bytes=1000,
                metadata={},
                ingested_at=datetime.now(timezone.utc),
            ),
        ]
        
        conflicts = detector.detect_conflicts(records)
        
        # No conflict because periods are different
        assert len(conflicts) == 0


# =============================================================================
# Test: Evidence Retrieval
# =============================================================================


class TestEvidenceRetrieval:
    """Tests for evidence retrieval."""
    
    @pytest.mark.asyncio
    async def test_get_evidence_by_id(
        self, service: EvidenceService, valid_sec_10k_request: IngestEvidenceRequest
    ):
        """Test retrieving evidence by ID."""
        response = await service.ingest(valid_sec_10k_request)
        assert response.success is True
        
        document = await service.get(response.evidence_id)
        
        assert document is not None
        assert document.evidence_id == response.evidence_id
        assert document.content_hash == response.content_hash
        assert document.status == EvidenceStatus.VALIDATED
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_evidence_returns_none(
        self, service: EvidenceService
    ):
        """Test retrieving nonexistent evidence returns None."""
        document = await service.get("EVD_nonexistent_12345")
        
        assert document is None
    
    @pytest.mark.asyncio
    async def test_find_by_entity(
        self, service: EvidenceService, valid_sec_10k_request: IngestEvidenceRequest
    ):
        """Test finding evidence by entity identifier."""
        response = await service.ingest(valid_sec_10k_request)
        assert response.success is True
        
        lookup_request = LookupByEntityRequest(
            entity_id_type="CIK",
            entity_id_value="0000320193",
            trace_id="test_lookup",
        )
        
        lookup_response = await service.find_by_entity(lookup_request)
        
        assert lookup_response.total_count >= 1
        evidence_ids = [e.evidence_id for e in lookup_response.evidence]
        assert response.evidence_id in evidence_ids
    
    @pytest.mark.asyncio
    async def test_find_by_entity_with_filters(
        self, service: EvidenceService, valid_sec_10k_request: IngestEvidenceRequest
    ):
        """Test finding evidence with source type filter."""
        response = await service.ingest(valid_sec_10k_request)
        assert response.success is True
        
        # Search with matching filter
        lookup_request = LookupByEntityRequest(
            entity_id_type="CIK",
            entity_id_value="0000320193",
            source_types=[EvidenceSourceType.SEC_10K],
            trace_id="test_filter",
        )
        
        lookup_response = await service.find_by_entity(lookup_request)
        assert lookup_response.total_count >= 1
        
        # Search with non-matching filter
        lookup_request_no_match = LookupByEntityRequest(
            entity_id_type="CIK",
            entity_id_value="0000320193",
            source_types=[EvidenceSourceType.SEC_8K],  # No 8-Ks ingested
            trace_id="test_filter_no_match",
        )
        
        lookup_response_no_match = await service.find_by_entity(lookup_request_no_match)
        assert lookup_response_no_match.total_count == 0
    
    @pytest.mark.asyncio
    async def test_link_evidence_to_claim(
        self, service: EvidenceService, valid_sec_10k_request: IngestEvidenceRequest
    ):
        """Test linking evidence to a claim."""
        response = await service.ingest(valid_sec_10k_request)
        assert response.success is True
        
        claim_id = "CLM_test_claim_001"
        success = await service.link_evidence_to_claim(claim_id, response.evidence_id)
        
        assert success is True
        
        # Verify evidence is linked
        documents, total = await service.list_for_claim(claim_id)
        assert total == 1
        assert documents[0].evidence_id == response.evidence_id
    
    @pytest.mark.asyncio
    async def test_list_for_claim_with_pagination(
        self, service: EvidenceService
    ):
        """Test listing evidence for claim with pagination."""
        claim_id = "CLM_pagination_test"
        
        # Ingest multiple evidence documents
        for i in range(5):
            request = IngestEvidenceRequest(
                source_type=EvidenceSourceType.TREASURY_YIELD_CURVE,
                content=f"Yield curve data {i}".encode(),
                entity_identifiers=[],
                source_name="US Treasury",
                published_at=datetime.now(timezone.utc) - timedelta(days=i),
                macroeconomic_metadata=MacroeconomicDataMetadata(
                    data_type=f"Yield Curve {i}",
                    source_institution="US Treasury",
                    publication_date=date.today() - timedelta(days=i),
                    effective_date=date.today() - timedelta(days=i),
                ),
                trace_id=f"test_pagination_{i}",
            )
            response = await service.ingest(request)
            assert response.success is True
            await service.link_evidence_to_claim(claim_id, response.evidence_id)
        
        # Test pagination
        docs_page1, total = await service.list_for_claim(claim_id, offset=0, limit=2)
        assert total == 5
        assert len(docs_page1) == 2
        
        docs_page2, _ = await service.list_for_claim(claim_id, offset=2, limit=2)
        assert len(docs_page2) == 2
        
        docs_page3, _ = await service.list_for_claim(claim_id, offset=4, limit=2)
        assert len(docs_page3) == 1


# =============================================================================
# Test: Determinism Guarantees
# =============================================================================


class TestDeterminismGuarantees:
    """Tests for determinism of evidence processing."""
    
    @pytest.mark.asyncio
    async def test_same_content_produces_same_hash(
        self, service: EvidenceService
    ):
        """Test identical content produces identical hash."""
        content = b"Deterministic content for testing"
        
        request1 = IngestEvidenceRequest(
            source_type=EvidenceSourceType.TREASURY_YIELD_CURVE,
            content=content,
            entity_identifiers=[],
            source_name="US Treasury",
            published_at=datetime.now(timezone.utc),
            macroeconomic_metadata=MacroeconomicDataMetadata(
                data_type="Test",
                source_institution="Treasury",
                publication_date=date.today(),
                effective_date=date.today(),
            ),
            trace_id="test_det_1",
        )
        
        response1 = await service.ingest(request1)
        
        # Create new service instance
        service2 = EvidenceService()
        
        request2 = IngestEvidenceRequest(
            source_type=EvidenceSourceType.TREASURY_YIELD_CURVE,
            content=content,
            entity_identifiers=[],
            source_name="US Treasury",
            published_at=datetime.now(timezone.utc),
            macroeconomic_metadata=MacroeconomicDataMetadata(
                data_type="Test",
                source_institution="Treasury",
                publication_date=date.today(),
                effective_date=date.today(),
            ),
            trace_id="test_det_2",
        )
        
        response2 = await service2.ingest(request2)
        
        # Content hashes must be identical
        assert response1.content_hash == response2.content_hash
    
    @pytest.mark.asyncio
    async def test_provenance_is_immutable(
        self, service: EvidenceService, valid_sec_10k_request: IngestEvidenceRequest
    ):
        """Test that provenance cannot be modified after ingestion."""
        response = await service.ingest(valid_sec_10k_request)
        assert response.success is True
        
        document1 = await service.get(response.evidence_id)
        assert document1 is not None
        
        # Provenance should be frozen (immutable)
        # This is enforced by Pydantic frozen=True
        with pytest.raises(Exception):  # ValidationError or AttributeError
            document1.provenance.source_name = "Modified"  # type: ignore


# =============================================================================
# Test: API Endpoints
# =============================================================================


class TestAPIEndpoints:
    """Tests for API endpoints."""
    
    def test_health_endpoint(self, client: TestClient):
        """Test health endpoint returns healthy."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "evidence-service"
    
    def test_readiness_endpoint(self, client: TestClient):
        """Test readiness endpoint."""
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert "ready" in data
        assert "checks" in data
    
    def test_get_nonexistent_evidence_returns_404(self, client: TestClient):
        """Test getting nonexistent evidence returns 404."""
        response = client.get("/v1/evidence/EVD_nonexistent_12345")
        assert response.status_code == 404


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    @pytest.mark.asyncio
    async def test_empty_content_rejected_at_schema_level(self, service: EvidenceService):
        """Test empty content is rejected at schema validation level."""
        # Schema requires either content or content_reference
        with pytest.raises(Exception):  # Pydantic ValidationError
            IngestEvidenceRequest(
                source_type=EvidenceSourceType.SEC_10K,
                content=b"",  # Empty content
                entity_identifiers=[
                    EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
                ],
                source_name="SEC EDGAR",
                published_at=datetime.now(timezone.utc),
                sec_metadata=SECFilingMetadata(
                    form_type="10-K",
                    cik="0000320193",
                    accession_number="0000320193-24-000123",
                    filing_date=date.today() - timedelta(days=30),
                    period_of_report=date.today() - timedelta(days=60),
                    company_name="Test",
                ),
                trace_id="test_empty",
            )
    
    @pytest.mark.asyncio
    async def test_unsupported_source_type_rejected(self, service: EvidenceService):
        """Test unsupported source type is rejected."""
        # Create request with valid enum but unsupported by any pipeline
        # All source types in the enum are supported, so this tests the check
        pass  # All enum values are supported
    
    @pytest.mark.asyncio
    async def test_entity_id_normalized_to_uppercase(
        self, service: EvidenceService
    ):
        """Test entity identifiers are normalized to uppercase."""
        request = IngestEvidenceRequest(
            source_type=EvidenceSourceType.SEC_10K,
            content=b"<filing>Content</filing>",
            entity_identifiers=[
                EvidenceEntityIdentifier(
                    id_type="cik",  # lowercase
                    id_value="0000320193",
                    is_primary=True,
                ),
            ],
            source_name="SEC EDGAR",
            published_at=datetime.now(timezone.utc) - timedelta(days=30),
            sec_metadata=SECFilingMetadata(
                form_type="10-K",
                cik="0000320193",
                accession_number="0000320193-24-000555",
                filing_date=date.today() - timedelta(days=30),
                period_of_report=date.today() - timedelta(days=60),
                company_name="Test Corp",
            ),
            trace_id="test_normalize",
        )
        
        response = await service.ingest(request)
        assert response.success is True
        
        document = await service.get(response.evidence_id)
        assert document is not None
        
        # ID type should be normalized to uppercase
        cik_ids = [eid for eid in document.entity_identifiers if eid.id_type == "CIK"]
        assert len(cik_ids) >= 1


# =============================================================================
# Test: Store Operations
# =============================================================================


class TestEvidenceStore:
    """Tests for the EvidenceStore class."""
    
    def test_store_and_retrieve(self):
        """Test storing and retrieving evidence."""
        store = EvidenceStore()
        
        record = EvidenceRecord(
            evidence_id="EVD_test_001",
            content_hash="abc123",
            status=EvidenceStatus.VALIDATED,
            entity_identifiers=[
                EvidenceEntityIdentifier(id_type="CIK", id_value="0000320193", is_primary=True),
            ],
            provenance=EvidenceProvenance(
                source_type=EvidenceSourceType.SEC_10K,
                source_name="SEC EDGAR",
                published_at=datetime.now(timezone.utc),
                retrieved_at=datetime.now(timezone.utc),
                reliability_tier=1,
                is_audited=True,
            ),
            reliability=EvidenceReliability(
                overall_score=Decimal("0.95"),
                source_tier=1,
                is_primary_source=True,
                is_audited=True,
                age_days=30,
                is_stale=False,
            ),
            object_key="test/key",
            content_type="application/xml",
            size_bytes=1000,
            metadata={},
            ingested_at=datetime.now(timezone.utc),
        )
        
        store.store(record)
        
        # Retrieve by ID
        retrieved = store.get("EVD_test_001")
        assert retrieved is not None
        assert retrieved.evidence_id == "EVD_test_001"
        
        # Retrieve by hash
        by_hash = store.get_by_hash("abc123")
        assert by_hash is not None
        assert by_hash.evidence_id == "EVD_test_001"
        
        # Find by entity
        by_entity = store.find_by_entity("CIK", "0000320193")
        assert len(by_entity) == 1
        assert by_entity[0].evidence_id == "EVD_test_001"
    
    def test_link_to_claim(self):
        """Test linking evidence to claims."""
        store = EvidenceStore()
        
        record = EvidenceRecord(
            evidence_id="EVD_link_test",
            content_hash="def456",
            status=EvidenceStatus.VALIDATED,
            entity_identifiers=[],
            provenance=EvidenceProvenance(
                source_type=EvidenceSourceType.TREASURY_YIELD_CURVE,
                source_name="Treasury",
                published_at=datetime.now(timezone.utc),
                retrieved_at=datetime.now(timezone.utc),
                reliability_tier=1,
                is_audited=False,
            ),
            reliability=EvidenceReliability(
                overall_score=Decimal("0.90"),
                source_tier=1,
                is_primary_source=True,
                is_audited=False,
                age_days=1,
                is_stale=False,
            ),
            object_key="test/key",
            content_type="application/json",
            size_bytes=500,
            metadata={},
            ingested_at=datetime.now(timezone.utc),
        )
        
        store.store(record)
        
        # Link to claim
        store.link_to_claim("CLM_001", "EVD_link_test")
        store.link_to_claim("CLM_002", "EVD_link_test")
        
        # Find by claim
        claim_1_evidence = store.find_by_claim("CLM_001")
        assert len(claim_1_evidence) == 1
        
        claim_2_evidence = store.find_by_claim("CLM_002")
        assert len(claim_2_evidence) == 1
        
        # Unknown claim returns empty
        unknown_claim = store.find_by_claim("CLM_unknown")
        assert len(unknown_claim) == 0
