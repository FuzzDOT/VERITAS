"""
Evidence Service Schemas - Production-Grade Evidence Models
=============================================================

Defines all schemas for evidence management with comprehensive validation.
The Evidence Service handles evidence lifecycle:
- Ingestion from verified sources (SEC filings, audited statements, macro data)
- Content-addressable storage with deterministic deduplication
- Policy-based evidence retrieval for claims
- Conflict detection and missing evidence identification

Design Principles:
- Evidence is immutable once ingested
- All evidence has cryptographic provenance (SHA256 hash)
- Only document-level truth is managed (no content extraction)
- Policy enforcement is explicit and auditable
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, FrozenSet, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# Constants & Bounds
# =============================================================================

# Maximum document age for admissibility (in days)
DEFAULT_MAX_STATEMENT_AGE_DAYS: int = 365

# Minimum reliability score for automatic acceptance
MIN_RELIABILITY_SCORE: Decimal = Decimal("0.80")

# Supported source types (only these are accepted)
SUPPORTED_SOURCE_TYPES: frozenset[str] = frozenset({
    # SEC Filings
    "sec_10k",
    "sec_10q",
    "sec_8k",
    # Audited Statements
    "audited_financial_statement",
    "audited_annual_report",
    "auditor_opinion",
    # Macroeconomic Reference Data
    "interest_rate_curve",
    "treasury_yield_curve",
    "economic_indicators",
    "central_bank_rates",
})

# Source types that require entity linkage
ENTITY_LINKED_SOURCES: frozenset[str] = frozenset({
    "sec_10k",
    "sec_10q",
    "sec_8k",
    "audited_financial_statement",
    "audited_annual_report",
    "auditor_opinion",
})

# Macroeconomic sources (global, not entity-linked)
MACROECONOMIC_SOURCES: frozenset[str] = frozenset({
    "interest_rate_curve",
    "treasury_yield_curve",
    "economic_indicators",
    "central_bank_rates",
})

# SEC filing types with their full names
SEC_FILING_TYPES: dict[str, str] = {
    "sec_10k": "Form 10-K Annual Report",
    "sec_10q": "Form 10-Q Quarterly Report",
    "sec_8k": "Form 8-K Current Report",
}

# Reliability tiers by source type
SOURCE_RELIABILITY_TIER: dict[str, int] = {
    "sec_10k": 1,  # Highest reliability (audited, regulatory)
    "sec_10q": 1,
    "sec_8k": 2,  # High reliability (regulatory, may not be audited)
    "audited_financial_statement": 1,
    "audited_annual_report": 1,
    "auditor_opinion": 1,
    "interest_rate_curve": 1,
    "treasury_yield_curve": 1,
    "economic_indicators": 2,
    "central_bank_rates": 1,
}

# Filing frequency expectations
FILING_FREQUENCY_MONTHS: dict[str, int] = {
    "sec_10k": 12,  # Annual
    "sec_10q": 3,   # Quarterly
    "sec_8k": 0,    # Event-driven
    "audited_annual_report": 12,
    "audited_financial_statement": 12,
}

# Entity identifier types accepted for evidence linkage
EVIDENCE_ENTITY_ID_TYPES: frozenset[str] = frozenset({
    "CIK",  # SEC Central Index Key
    "LEI",  # Legal Entity Identifier
    "TICKER",  # Stock ticker (requires exchange)
    "CUSIP",  # CUSIP identifier
    "ISIN",  # ISIN identifier
})


# =============================================================================
# Enums
# =============================================================================


class EvidenceStatus(str, Enum):
    """Status of evidence in the system."""
    
    PENDING = "pending"  # Received but not yet validated
    VALIDATED = "validated"  # Passed all validation checks
    REJECTED = "rejected"  # Failed validation, not admissible
    SUPERSEDED = "superseded"  # Replaced by newer version


class EvidenceSourceType(str, Enum):
    """Canonical evidence source types."""
    
    # SEC Filings
    SEC_10K = "sec_10k"
    SEC_10Q = "sec_10q"
    SEC_8K = "sec_8k"
    
    # Audited Statements
    AUDITED_FINANCIAL_STATEMENT = "audited_financial_statement"
    AUDITED_ANNUAL_REPORT = "audited_annual_report"
    AUDITOR_OPINION = "auditor_opinion"
    
    # Macroeconomic Reference Data
    INTEREST_RATE_CURVE = "interest_rate_curve"
    TREASURY_YIELD_CURVE = "treasury_yield_curve"
    ECONOMIC_INDICATORS = "economic_indicators"
    CENTRAL_BANK_RATES = "central_bank_rates"


class RejectionCode(str, Enum):
    """Codes for evidence rejection."""
    
    # Source validation failures
    UNSUPPORTED_SOURCE_TYPE = "unsupported_source_type"
    UNVERIFIABLE_SOURCE = "unverifiable_source"
    SOURCE_NOT_AUTHORITATIVE = "source_not_authoritative"
    
    # Entity validation failures
    MISSING_ENTITY_IDENTIFIER = "missing_entity_identifier"
    INVALID_ENTITY_IDENTIFIER = "invalid_entity_identifier"
    ENTITY_MISMATCH = "entity_mismatch"
    
    # Document validation failures
    INVALID_DOCUMENT_FORMAT = "invalid_document_format"
    DOCUMENT_CORRUPTED = "document_corrupted"
    HASH_MISMATCH = "hash_mismatch"
    
    # Temporal validation failures
    DOCUMENT_EXPIRED = "document_expired"
    FUTURE_DATED_DOCUMENT = "future_dated_document"
    PUBLICATION_DATE_MISSING = "publication_date_missing"
    
    # Policy failures
    JURISDICTION_NOT_ALLOWED = "jurisdiction_not_allowed"
    SOURCE_TYPE_NOT_ALLOWED = "source_type_not_allowed"
    RELIABILITY_BELOW_THRESHOLD = "reliability_below_threshold"
    
    # Duplicate handling
    DUPLICATE_CONTENT = "duplicate_content"


class ConflictType(str, Enum):
    """Types of evidence conflicts."""
    
    # Multiple filings for same period
    DUPLICATE_PERIOD_FILING = "duplicate_period_filing"
    
    # Conflicting values across documents
    CONFLICTING_VALUES = "conflicting_values"
    
    # Superseded but still referenced
    SUPERSEDED_REFERENCE = "superseded_reference"
    
    # Amendment without clear supersession
    AMBIGUOUS_AMENDMENT = "ambiguous_amendment"


class MissingEvidenceReason(str, Enum):
    """Reasons for missing evidence."""
    
    NO_MATCHING_DOCUMENTS = "no_matching_documents"
    DOCUMENTS_EXPIRED = "documents_expired"
    SOURCE_TYPE_UNAVAILABLE = "source_type_unavailable"
    ENTITY_NOT_LINKED = "entity_not_linked"
    PERIOD_NOT_COVERED = "period_not_covered"


# =============================================================================
# Sub-Schemas: Entity Identifiers for Evidence
# =============================================================================


class EvidenceEntityIdentifier(BaseModel):
    """Entity identifier attached to evidence."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    id_type: str = Field(..., description="Type of identifier (CIK, LEI, TICKER, etc.)")
    id_value: str = Field(..., description="The identifier value (normalized)")
    exchange: Optional[str] = Field(
        None, description="Exchange code (required for TICKER)"
    )
    is_primary: bool = Field(
        default=False, description="Whether this is the primary identifier"
    )
    
    @field_validator("id_type")
    @classmethod
    def validate_id_type(cls, v: str) -> str:
        """Validate id_type is supported."""
        if v.upper() not in EVIDENCE_ENTITY_ID_TYPES:
            raise ValueError(f"Unsupported entity ID type: {v}")
        return v.upper()
    
    @model_validator(mode="after")
    def validate_ticker_has_exchange(self) -> "EvidenceEntityIdentifier":
        """Ensure TICKER has exchange."""
        if self.id_type == "TICKER" and not self.exchange:
            raise ValueError("TICKER identifier requires exchange")
        return self


# =============================================================================
# Sub-Schemas: Evidence Provenance
# =============================================================================


class EvidenceProvenance(BaseModel):
    """Immutable provenance record for evidence."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Source information
    source_type: EvidenceSourceType = Field(..., description="Type of evidence source")
    source_uri: Optional[str] = Field(
        None, description="Original source URI (if available)"
    )
    source_name: str = Field(..., description="Human-readable source name")
    
    # Temporal information
    published_at: datetime = Field(
        ..., description="When the document was originally published"
    )
    retrieved_at: datetime = Field(
        ..., description="When we retrieved/ingested the document"
    )
    period_start: Optional[date] = Field(
        None, description="Start of period covered by document"
    )
    period_end: Optional[date] = Field(
        None, description="End of period covered by document"
    )
    fiscal_year: Optional[int] = Field(
        None, description="Fiscal year (for annual filings)"
    )
    fiscal_quarter: Optional[int] = Field(
        None, ge=1, le=4, description="Fiscal quarter (for quarterly filings)"
    )
    
    # Reliability metadata
    reliability_tier: int = Field(
        ..., ge=1, le=5, description="Reliability tier (1=highest)"
    )
    is_audited: bool = Field(
        default=False, description="Whether content is audited"
    )
    auditor_name: Optional[str] = Field(
        None, description="Name of auditing firm (if audited)"
    )
    
    # SEC-specific metadata
    accession_number: Optional[str] = Field(
        None, description="SEC accession number (for SEC filings)"
    )
    filing_date: Optional[date] = Field(
        None, description="SEC filing date (for SEC filings)"
    )
    
    # Jurisdiction
    jurisdiction: Optional[str] = Field(
        None, description="ISO 3166-1 alpha-2 jurisdiction code"
    )


# =============================================================================
# Sub-Schemas: Evidence Reliability
# =============================================================================


class EvidenceReliability(BaseModel):
    """Reliability assessment of evidence."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    overall_score: Decimal = Field(
        ..., ge=Decimal("0"), le=Decimal("1"),
        description="Overall reliability score (0-1)"
    )
    source_tier: int = Field(
        ..., ge=1, le=5, description="Source reliability tier"
    )
    is_primary_source: bool = Field(
        default=False, description="Whether this is a primary source"
    )
    is_audited: bool = Field(
        default=False, description="Whether content is audited"
    )
    age_days: int = Field(
        ..., ge=0, description="Age of document in days"
    )
    is_stale: bool = Field(
        default=False, description="Whether document is considered stale"
    )
    staleness_threshold_days: int = Field(
        default=365, description="Threshold for staleness"
    )


# =============================================================================
# Core Evidence Models
# =============================================================================


class EvidenceDocument(BaseModel):
    """A stored evidence document with full provenance."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Identity
    evidence_id: str = Field(..., description="Stable evidence identifier")
    content_hash: str = Field(
        ..., description="SHA256 hash of document content"
    )
    
    # Status
    status: EvidenceStatus = Field(
        default=EvidenceStatus.VALIDATED,
        description="Current status of evidence"
    )
    
    # Entity linkage
    entity_identifiers: list[EvidenceEntityIdentifier] = Field(
        default_factory=list,
        description="Entity identifiers linked to this evidence"
    )
    
    # Provenance (immutable)
    provenance: EvidenceProvenance = Field(
        ..., description="Complete provenance record"
    )
    
    # Reliability assessment
    reliability: EvidenceReliability = Field(
        ..., description="Reliability assessment"
    )
    
    # Storage
    object_key: str = Field(..., description="Object storage key")
    content_type: str = Field(
        default="application/octet-stream",
        description="MIME type of stored content"
    )
    size_bytes: int = Field(..., ge=0, description="Size of document in bytes")
    
    # Metadata
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )
    
    # Timestamps
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When evidence was ingested into system"
    )
    
    # Supersession
    supersedes_evidence_id: Optional[str] = Field(
        None, description="ID of evidence this supersedes (if any)"
    )
    superseded_by_evidence_id: Optional[str] = Field(
        None, description="ID of evidence that supersedes this (if any)"
    )


# =============================================================================
# Ingestion Models
# =============================================================================


class SECFilingMetadata(BaseModel):
    """Metadata specific to SEC filings."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    form_type: str = Field(..., description="SEC form type (10-K, 10-Q, 8-K)")
    cik: str = Field(..., description="SEC Central Index Key")
    accession_number: str = Field(..., description="SEC accession number")
    filing_date: date = Field(..., description="Filing date with SEC")
    period_of_report: date = Field(..., description="Period end date")
    fiscal_year_end: Optional[str] = Field(
        None, description="Fiscal year end (MMDD format)"
    )
    company_name: str = Field(..., description="Company name from filing")
    ticker: Optional[str] = Field(None, description="Stock ticker if available")
    exchange: Optional[str] = Field(None, description="Exchange if available")


class AuditedStatementMetadata(BaseModel):
    """Metadata specific to audited financial statements."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    statement_type: str = Field(..., description="Type of statement")
    auditor_name: str = Field(..., description="Name of auditing firm")
    audit_opinion: str = Field(..., description="Audit opinion type")
    opinion_date: date = Field(..., description="Date of audit opinion")
    period_start: date = Field(..., description="Period start date")
    period_end: date = Field(..., description="Period end date")
    fiscal_year: int = Field(..., description="Fiscal year covered")
    entity_name: str = Field(..., description="Entity name")
    entity_jurisdiction: str = Field(..., description="Entity jurisdiction")


class MacroeconomicDataMetadata(BaseModel):
    """Metadata specific to macroeconomic reference data."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    data_type: str = Field(..., description="Type of economic data")
    source_institution: str = Field(
        ..., description="Source institution (e.g., Federal Reserve)"
    )
    publication_date: date = Field(..., description="Publication date")
    effective_date: date = Field(..., description="Date data is effective")
    currency: Optional[str] = Field(None, description="Currency (if applicable)")
    region: Optional[str] = Field(None, description="Geographic region")
    frequency: Optional[str] = Field(
        None, description="Data frequency (daily, weekly, etc.)"
    )


class IngestEvidenceRequest(BaseModel):
    """Request to ingest new evidence into the system."""
    
    model_config = ConfigDict(extra="forbid")
    
    # Source type
    source_type: EvidenceSourceType = Field(
        ..., description="Type of evidence source"
    )
    
    # Document content (either raw bytes or reference)
    content: Optional[bytes] = Field(
        None, description="Raw document content"
    )
    content_reference: Optional[str] = Field(
        None, description="URI reference to content (for large documents)"
    )
    expected_hash: Optional[str] = Field(
        None, description="Expected SHA256 hash (for verification)"
    )
    
    # Entity identifiers
    entity_identifiers: list[EvidenceEntityIdentifier] = Field(
        default_factory=list,
        description="Entity identifiers to link"
    )
    
    # Source metadata
    source_uri: Optional[str] = Field(None, description="Original source URI")
    source_name: str = Field(..., description="Human-readable source name")
    
    # Temporal information
    published_at: datetime = Field(
        ..., description="When document was published"
    )
    period_start: Optional[date] = Field(None, description="Period start")
    period_end: Optional[date] = Field(None, description="Period end")
    fiscal_year: Optional[int] = Field(None, description="Fiscal year")
    fiscal_quarter: Optional[int] = Field(None, ge=1, le=4, description="Fiscal quarter")
    
    # Type-specific metadata
    sec_metadata: Optional[SECFilingMetadata] = Field(
        None, description="SEC-specific metadata"
    )
    audited_statement_metadata: Optional[AuditedStatementMetadata] = Field(
        None, description="Audited statement metadata"
    )
    macroeconomic_metadata: Optional[MacroeconomicDataMetadata] = Field(
        None, description="Macroeconomic data metadata"
    )
    
    # Additional metadata
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )
    
    # Tracing
    trace_id: str = Field(..., description="Trace ID for correlation")
    
    @model_validator(mode="after")
    def validate_content_provided(self) -> "IngestEvidenceRequest":
        """Ensure content or reference is provided."""
        if not self.content and not self.content_reference:
            raise ValueError("Either content or content_reference must be provided")
        return self
    
    @model_validator(mode="after")
    def validate_entity_for_linked_sources(self) -> "IngestEvidenceRequest":
        """Ensure entity identifiers are provided for entity-linked sources."""
        if self.source_type.value in ENTITY_LINKED_SOURCES:
            if not self.entity_identifiers:
                raise ValueError(
                    f"Entity identifiers required for source type: {self.source_type}"
                )
        return self


class IngestEvidenceResponse(BaseModel):
    """Response from evidence ingestion."""
    
    model_config = ConfigDict(frozen=True)
    
    success: bool = Field(..., description="Whether ingestion succeeded")
    evidence_id: Optional[str] = Field(None, description="Assigned evidence ID")
    content_hash: Optional[str] = Field(None, description="Computed content hash")
    is_duplicate: bool = Field(
        default=False, description="Whether this was a duplicate"
    )
    duplicate_evidence_id: Optional[str] = Field(
        None, description="ID of existing duplicate (if is_duplicate)"
    )
    
    # On rejection
    rejected: bool = Field(default=False, description="Whether evidence was rejected")
    rejection_code: Optional[RejectionCode] = Field(
        None, description="Rejection code"
    )
    rejection_message: Optional[str] = Field(
        None, description="Rejection explanation"
    )
    
    # Metadata
    warnings: list[str] = Field(default_factory=list, description="Warnings")
    trace_id: str = Field(..., description="Trace ID")


# =============================================================================
# Rejection Models
# =============================================================================


class EvidenceRejection(BaseModel):
    """A structured rejection for evidence that cannot be accepted."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    code: RejectionCode = Field(..., description="Rejection code")
    message: str = Field(..., description="Human-readable explanation")
    field_path: Optional[str] = Field(
        None, description="Path to problematic field"
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional rejection context"
    )
    suggestion: Optional[str] = Field(
        None, description="Suggested remediation"
    )


# =============================================================================
# Policy Models
# =============================================================================


class EvidencePolicy(BaseModel):
    """Policy governing evidence admissibility for a claim."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Source restrictions
    allowed_source_types: frozenset[EvidenceSourceType] = Field(
        default=frozenset(EvidenceSourceType),
        description="Allowed source types"
    )
    require_audited_statements: bool = Field(
        default=True, description="Whether audited statements are required"
    )
    
    # Temporal restrictions
    max_document_age_days: int = Field(
        default=365, description="Maximum age of documents in days"
    )
    reference_date: date = Field(
        default_factory=date.today,
        description="Reference date for age calculation"
    )
    
    # Reliability requirements
    minimum_reliability_score: Decimal = Field(
        default=Decimal("0.80"),
        description="Minimum reliability score"
    )
    require_primary_sources: bool = Field(
        default=False, description="Whether primary sources are required"
    )
    
    # Jurisdiction restrictions
    allowed_jurisdictions: Optional[frozenset[str]] = Field(
        None, description="Allowed jurisdictions (None = all)"
    )
    
    # Entity linkage requirements
    require_entity_linkage: bool = Field(
        default=True, description="Whether entity linkage is required"
    )
    
    @classmethod
    def from_canonical_claim(cls, claim: Any) -> "EvidencePolicy":
        """Derive policy from a CanonicalSolvencyClaim."""
        allowed_types = set(EvidenceSourceType)
        
        return cls(
            allowed_source_types=frozenset(allowed_types),
            require_audited_statements=claim.require_audited_statements,
            max_document_age_days=claim.max_statement_age_days,
            reference_date=claim.analysis_horizon.reference_date,
            minimum_reliability_score=Decimal("0.80"),
            require_primary_sources=False,
            allowed_jurisdictions=frozenset({claim.jurisdiction}),
            require_entity_linkage=True,
        )


# =============================================================================
# Evidence Set Models
# =============================================================================


class MissingEvidence(BaseModel):
    """Description of missing evidence for a specific fact."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    fact_id: str = Field(..., description="ID of fact requiring evidence")
    fact_name: str = Field(..., description="Name of fact")
    reason: MissingEvidenceReason = Field(..., description="Why evidence is missing")
    acceptable_source_types: list[EvidenceSourceType] = Field(
        ..., description="Source types that would satisfy this"
    )
    required_period: Optional[tuple[date, date]] = Field(
        None, description="Required period coverage"
    )
    message: str = Field(..., description="Human-readable description")


class EvidenceConflict(BaseModel):
    """Description of conflicting evidence."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    conflict_type: ConflictType = Field(..., description="Type of conflict")
    evidence_ids: list[str] = Field(
        ..., min_length=2, description="IDs of conflicting evidence"
    )
    affected_facts: list[str] = Field(
        default_factory=list,
        description="Fact IDs affected by this conflict"
    )
    description: str = Field(..., description="Description of conflict")
    resolution_suggestion: Optional[str] = Field(
        None, description="Suggested resolution"
    )


class EvidenceSet(BaseModel):
    """
    Complete evidence set for a claim evaluation.
    
    This is the output of evidence retrieval for a claim and its
    required facts contract.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Identity
    evidence_set_id: str = Field(..., description="Unique evidence set ID")
    claim_id: str = Field(..., description="Associated claim ID")
    contract_id: str = Field(..., description="Required facts contract ID")
    
    # Admissible evidence
    admissible_evidence: list[EvidenceDocument] = Field(
        default_factory=list,
        description="Evidence that passes policy checks"
    )
    
    # Non-admissible evidence (available but excluded)
    excluded_evidence: list[tuple[EvidenceDocument, EvidenceRejection]] = Field(
        default_factory=list,
        description="Evidence excluded and reasons"
    )
    
    # Missing evidence
    missing_evidence: list[MissingEvidence] = Field(
        default_factory=list,
        description="Evidence needed but not found"
    )
    
    # Conflicts
    conflicts: list[EvidenceConflict] = Field(
        default_factory=list,
        description="Detected evidence conflicts"
    )
    
    # Coverage summary
    facts_fully_covered: list[str] = Field(
        default_factory=list,
        description="Fact IDs with sufficient evidence"
    )
    facts_partially_covered: list[str] = Field(
        default_factory=list,
        description="Fact IDs with some but not all evidence"
    )
    facts_not_covered: list[str] = Field(
        default_factory=list,
        description="Fact IDs with no evidence"
    )
    
    # Policy applied
    policy_applied: EvidencePolicy = Field(
        ..., description="Policy used for filtering"
    )
    
    # Completeness
    is_complete: bool = Field(
        default=False,
        description="Whether evidence is complete for required facts"
    )
    completeness_ratio: Decimal = Field(
        default=Decimal("0"),
        description="Ratio of covered to required facts"
    )
    
    # Metadata
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    evidence_set_hash: str = Field(
        ..., description="Deterministic hash of the evidence set"
    )


# =============================================================================
# Lookup Models
# =============================================================================


class LookupByClaimRequest(BaseModel):
    """Request to look up evidence for a claim."""
    
    model_config = ConfigDict(extra="forbid")
    
    claim_id: str = Field(..., description="Claim ID to look up evidence for")
    include_excluded: bool = Field(
        default=False,
        description="Include excluded evidence in response"
    )
    trace_id: str = Field(..., description="Trace ID")


class LookupByEntityRequest(BaseModel):
    """Request to look up evidence by entity identifier."""
    
    model_config = ConfigDict(extra="forbid")
    
    entity_id_type: str = Field(..., description="Type of entity identifier")
    entity_id_value: str = Field(..., description="Entity identifier value")
    exchange: Optional[str] = Field(None, description="Exchange (for TICKER)")
    
    # Filters
    source_types: Optional[list[EvidenceSourceType]] = Field(
        None, description="Filter by source types"
    )
    published_after: Optional[datetime] = Field(
        None, description="Filter by publication date"
    )
    published_before: Optional[datetime] = Field(
        None, description="Filter by publication date"
    )
    status: Optional[EvidenceStatus] = Field(
        None, description="Filter by status"
    )
    
    # Pagination
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
    
    trace_id: str = Field(..., description="Trace ID")


class LookupByEntityResponse(BaseModel):
    """Response from entity evidence lookup."""
    
    model_config = ConfigDict(frozen=True)
    
    evidence: list[EvidenceDocument] = Field(
        default_factory=list,
        description="Evidence documents found"
    )
    total_count: int = Field(..., description="Total matching count")
    offset: int = Field(..., description="Current offset")
    limit: int = Field(..., description="Applied limit")
    trace_id: str = Field(..., description="Trace ID")


# =============================================================================
# API Request/Response Models
# =============================================================================


class GetEvidenceResponse(BaseModel):
    """Response for getting a single evidence document."""
    
    model_config = ConfigDict(frozen=True)
    
    evidence: EvidenceDocument = Field(..., description="The evidence document")
    download_url: Optional[str] = Field(
        None, description="Presigned URL for content download"
    )


class ListEvidenceResponse(BaseModel):
    """Response for listing evidence."""
    
    model_config = ConfigDict(frozen=True)
    
    evidence: list[EvidenceDocument] = Field(default_factory=list)
    total_count: int = Field(..., description="Total count")
    offset: int = Field(default=0)
    limit: int = Field(default=50)
    has_more: bool = Field(default=False)
