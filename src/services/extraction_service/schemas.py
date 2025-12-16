"""
Extraction Service Schemas - Production-Grade Fact Extraction Models
======================================================================

Defines all schemas for deterministic fact extraction from evidence:
- FinancialFact: Typed fact records suitable for solvency computation
- EvidencePassage: Audit-grade provenance for extracted facts
- ExtractionJob: Job orchestration for extraction runs

Design Principles:
- All extraction is deterministic and reproducible
- Facts align to A3 RequiredFactType categories
- Every fact has traceable provenance to evidence
- No LLM integration, no probabilistic guessing
- XBRL-first for SEC filings, deterministic fallbacks
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, FrozenSet, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# Constants & Bounds
# =============================================================================

# Minimum confidence for facts to be included by default
DEFAULT_MIN_CONFIDENCE: Decimal = Decimal("0.80")

# Confidence levels by extraction method
EXTRACTION_METHOD_CONFIDENCE: dict[str, Decimal] = {
    "XBRL": Decimal("1.00"),  # XBRL is authoritative
    "TABLE": Decimal("0.70"),  # Table extraction is medium confidence
    "TEXT": Decimal("0.40"),  # Text extraction is low confidence
    "MACRO": Decimal("1.00"),  # Macro data from authoritative sources
}

# XBRL namespace mappings for standard concepts
XBRL_US_GAAP_NAMESPACE = "http://fasb.org/us-gaap"
XBRL_DEI_NAMESPACE = "http://xbrl.sec.gov/dei"

# Standard XBRL tags for core solvency facts (US-GAAP 2023)
XBRL_FACT_MAPPINGS: dict[str, list[str]] = {
    "total_assets": [
        "us-gaap:Assets",
        "us-gaap:AssetsCurrent",
    ],
    "total_liabilities": [
        "us-gaap:Liabilities",
        "us-gaap:LiabilitiesAndStockholdersEquity",
    ],
    "total_equity": [
        "us-gaap:StockholdersEquity",
        "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cash_and_equivalents": [
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:Cash",
    ],
    "total_debt": [
        "us-gaap:LongTermDebt",
        "us-gaap:DebtAndCapitalLeaseObligations",
    ],
    "current_assets": [
        "us-gaap:AssetsCurrent",
    ],
    "current_liabilities": [
        "us-gaap:LiabilitiesCurrent",
    ],
    "operating_income": [
        "us-gaap:OperatingIncomeLoss",
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ],
    "interest_expense": [
        "us-gaap:InterestExpense",
        "us-gaap:InterestExpenseDebt",
    ],
    "net_income": [
        "us-gaap:NetIncomeLoss",
        "us-gaap:ProfitLoss",
    ],
    "revenue": [
        "us-gaap:Revenues",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    ],
    "operating_cash_flow": [
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    ],
    "capital_expenditures": [
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        "us-gaap:CapitalExpendituresIncurredButNotYetPaid",
    ],
}

# Supported fact types aligned to A3 RequiredFact names
SUPPORTED_FACT_TYPES: frozenset[str] = frozenset({
    # Balance Sheet
    "total_assets",
    "total_liabilities",
    "total_equity",
    "cash_and_equivalents",
    "total_debt",
    "current_assets",
    "current_liabilities",
    "long_term_debt",
    "short_term_debt",
    "goodwill",
    "intangible_assets",
    # Income Statement
    "operating_income",
    "interest_expense",
    "net_income",
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_expenses",
    "depreciation_amortization",
    # Cash Flow
    "operating_cash_flow",
    "investing_cash_flow",
    "financing_cash_flow",
    "capital_expenditures",
    "free_cash_flow",
    # Regulatory
    "tier1_capital",
    "tier2_capital",
    "risk_weighted_assets",
    "common_equity_tier1",
    "total_capital_ratio",
    # Debt Schedule
    "debt_maturity_schedule",
    "interest_rate_sensitivity",
    # Macroeconomic
    "interest_rate",
    "treasury_yield",
    "inflation_rate",
    "gdp_growth_rate",
    "unemployment_rate",
})

# Categories aligned to A3 FactCategory
FACT_CATEGORY_MAPPING: dict[str, str] = {
    "total_assets": "balance_sheet",
    "total_liabilities": "balance_sheet",
    "total_equity": "balance_sheet",
    "cash_and_equivalents": "balance_sheet",
    "total_debt": "balance_sheet",
    "current_assets": "balance_sheet",
    "current_liabilities": "balance_sheet",
    "long_term_debt": "balance_sheet",
    "short_term_debt": "balance_sheet",
    "goodwill": "balance_sheet",
    "intangible_assets": "balance_sheet",
    "operating_income": "income_statement",
    "interest_expense": "income_statement",
    "net_income": "income_statement",
    "revenue": "income_statement",
    "cost_of_revenue": "income_statement",
    "gross_profit": "income_statement",
    "operating_expenses": "income_statement",
    "depreciation_amortization": "income_statement",
    "operating_cash_flow": "cash_flow",
    "investing_cash_flow": "cash_flow",
    "financing_cash_flow": "cash_flow",
    "capital_expenditures": "cash_flow",
    "free_cash_flow": "cash_flow",
    "tier1_capital": "regulatory_capital",
    "tier2_capital": "regulatory_capital",
    "risk_weighted_assets": "regulatory_capital",
    "common_equity_tier1": "regulatory_capital",
    "total_capital_ratio": "regulatory_capital",
    "debt_maturity_schedule": "debt_schedule",
    "interest_rate_sensitivity": "debt_schedule",
    "interest_rate": "macroeconomic",
    "treasury_yield": "macroeconomic",
    "inflation_rate": "macroeconomic",
    "gdp_growth_rate": "macroeconomic",
    "unemployment_rate": "macroeconomic",
}


# =============================================================================
# Enums
# =============================================================================


class ExtractionMethod(str, Enum):
    """Method used to extract a fact."""
    
    XBRL = "XBRL"  # Direct XBRL tag extraction (highest confidence)
    TABLE = "TABLE"  # Deterministic table parsing
    TEXT = "TEXT"  # Deterministic text pattern matching (low confidence)
    MACRO = "MACRO"  # Macroeconomic data series


class FactConfidence(str, Enum):
    """Confidence level of extracted facts."""
    
    HIGH = "high"  # XBRL or authoritative macro data (>= 0.90)
    MEDIUM = "medium"  # Table extraction (0.60 - 0.89)
    LOW = "low"  # Text extraction (< 0.60)


class ExtractionJobStatus(str, Enum):
    """Status of an extraction job."""
    
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # Some extractions succeeded, some failed


class ExtractionRefusalCode(str, Enum):
    """Codes for extraction refusals."""
    
    # Evidence issues
    EVIDENCE_NOT_FOUND = "evidence_not_found"
    EVIDENCE_MALFORMED = "evidence_malformed"
    EVIDENCE_UNVERIFIABLE = "evidence_unverifiable"
    EVIDENCE_TYPE_UNSUPPORTED = "evidence_type_unsupported"
    
    # Content issues
    NO_XBRL_AVAILABLE = "no_xbrl_available"
    XBRL_PARSE_ERROR = "xbrl_parse_error"
    TABLE_PARSE_ERROR = "table_parse_error"
    
    # Fact issues
    FACT_TYPE_UNKNOWN = "fact_type_unknown"
    FACT_VALUE_UNPARSEABLE = "fact_value_unparseable"
    FACT_PERIOD_MISMATCH = "fact_period_mismatch"
    
    # Policy issues
    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"


class FactUnit(str, Enum):
    """Units for fact values."""
    
    CURRENCY = "currency"
    RATIO = "ratio"
    PERCENT = "percent"
    INTEGER = "integer"
    DECIMAL = "decimal"
    SHARES = "shares"
    BASIS_POINTS = "basis_points"


# =============================================================================
# Source Location Models
# =============================================================================


class XBRLLocation(BaseModel):
    """Location information for XBRL-extracted facts."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    namespace: str = Field(..., description="XBRL namespace")
    tag_name: str = Field(..., description="XBRL tag name")
    context_ref: str = Field(..., description="XBRL context reference")
    unit_ref: Optional[str] = Field(None, description="XBRL unit reference")
    decimals: Optional[int] = Field(None, description="XBRL decimals attribute")


class TableLocation(BaseModel):
    """Location information for table-extracted facts."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    page_number: int = Field(..., ge=1, description="Page number (1-indexed)")
    table_index: int = Field(..., ge=0, description="Table index on page")
    row_index: int = Field(..., ge=0, description="Row index in table")
    column_index: int = Field(..., ge=0, description="Column index in table")
    row_header: Optional[str] = Field(None, description="Row header text")
    column_header: Optional[str] = Field(None, description="Column header text")


class TextLocation(BaseModel):
    """Location information for text-extracted facts."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    page_number: int = Field(..., ge=1, description="Page number (1-indexed)")
    start_offset: int = Field(..., ge=0, description="Character offset start")
    end_offset: int = Field(..., ge=0, description="Character offset end")
    line_number: Optional[int] = Field(None, description="Line number")
    surrounding_context: Optional[str] = Field(
        None, max_length=500, description="Surrounding text for context"
    )


class MacroLocation(BaseModel):
    """Location information for macroeconomic data facts."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    series_id: str = Field(..., description="Time series identifier")
    data_source: str = Field(..., description="Data source name")
    observation_date: date = Field(..., description="Observation date")


# =============================================================================
# Fact Provenance (derived_from)
# =============================================================================


class FactProvenance(BaseModel):
    """
    Complete provenance for a fact linking it to source evidence.
    
    Every fact must have traceable provenance to evidence.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    evidence_id: str = Field(..., description="Source evidence ID")
    evidence_hash: str = Field(..., description="Content hash of source evidence")
    passage_id: Optional[str] = Field(
        None, description="Associated passage ID (for audit trail)"
    )
    
    # Location information (one of these must be present)
    xbrl_location: Optional[XBRLLocation] = Field(None)
    table_location: Optional[TableLocation] = Field(None)
    text_location: Optional[TextLocation] = Field(None)
    macro_location: Optional[MacroLocation] = Field(None)
    
    @model_validator(mode="after")
    def validate_location_present(self) -> "FactProvenance":
        """Ensure at least one location is provided."""
        locations = [
            self.xbrl_location,
            self.table_location,
            self.text_location,
            self.macro_location,
        ]
        if not any(locations):
            raise ValueError("At least one location type must be provided")
        return self


# =============================================================================
# Financial Fact
# =============================================================================


class FinancialFact(BaseModel):
    """
    A typed financial fact suitable for solvency computation.
    
    This is the core output of the Extraction Service. Facts:
    - Have a canonical fact_type aligned to A3 RequiredFactType
    - Include value, unit, and currency (if applicable)
    - Have temporal context (as_of_date or period)
    - Include confidence and extraction method
    - Are fully traceable via derived_from provenance
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Identity
    fact_id: str = Field(..., description="Unique fact identifier")
    fact_hash: str = Field(
        ..., description="Deterministic hash of fact content for deduplication"
    )
    
    # Type (aligned to A3 RequiredFactType)
    fact_type: str = Field(..., description="Canonical fact type name")
    category: str = Field(..., description="Fact category (balance_sheet, etc.)")
    
    # Value
    value: Decimal = Field(..., description="Numeric value of the fact")
    unit: FactUnit = Field(..., description="Unit of the value")
    currency: Optional[str] = Field(
        None, max_length=3, description="ISO 4217 currency code"
    )
    scale: int = Field(
        default=0,
        description="Scale factor (0=units, 3=thousands, 6=millions, 9=billions)"
    )
    
    # Temporal context
    as_of_date: date = Field(..., description="Date the fact is as-of")
    period_start: Optional[date] = Field(
        None, description="Period start (for income/cash flow)"
    )
    period_end: Optional[date] = Field(
        None, description="Period end (for income/cash flow)"
    )
    fiscal_year: Optional[int] = Field(None, description="Fiscal year")
    fiscal_quarter: Optional[int] = Field(
        None, ge=1, le=4, description="Fiscal quarter"
    )
    
    # Extraction metadata
    confidence: Decimal = Field(
        ..., ge=Decimal("0"), le=Decimal("1"),
        description="Confidence score 0.0-1.0"
    )
    confidence_level: FactConfidence = Field(..., description="Confidence category")
    extraction_method: ExtractionMethod = Field(
        ..., description="Method used to extract"
    )
    extractor_version: str = Field(..., description="Version of extractor used")
    
    # Provenance
    derived_from: FactProvenance = Field(
        ..., description="Provenance linking to source evidence"
    )
    
    # Entity linkage
    entity_id: Optional[str] = Field(
        None, description="Entity ID (CIK, LEI) if entity-linked"
    )
    entity_id_type: Optional[str] = Field(None, description="Type of entity ID")
    
    # Timestamps
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    @field_validator("fact_type")
    @classmethod
    def validate_fact_type(cls, v: str) -> str:
        """Validate fact_type is in supported set."""
        if v not in SUPPORTED_FACT_TYPES:
            raise ValueError(f"Unsupported fact type: {v}")
        return v
    
    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: Optional[str]) -> Optional[str]:
        """Normalize currency to uppercase."""
        if v:
            return v.upper()
        return v
    
    @model_validator(mode="after")
    def validate_currency_required(self) -> "FinancialFact":
        """Currency is required for currency-denominated facts."""
        if self.unit == FactUnit.CURRENCY and not self.currency:
            raise ValueError("Currency is required when unit is CURRENCY")
        return self


# =============================================================================
# Evidence Passage
# =============================================================================


class EvidencePassage(BaseModel):
    """
    An audit-grade passage extracted from evidence.
    
    Passages provide human-readable provenance for facts and
    capture key narrative items (debt maturity, covenants).
    
    Passages are:
    - Deduplicated by content hash
    - Linked to source evidence
    - Minimal (only audit-critical content)
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Identity
    passage_id: str = Field(..., description="Unique passage identifier")
    passage_hash: str = Field(
        ..., description="SHA256 hash of passage content for deduplication"
    )
    
    # Source evidence
    evidence_id: str = Field(..., description="Source evidence ID")
    evidence_hash: str = Field(..., description="Hash of source evidence")
    
    # Location
    page_number: Optional[int] = Field(None, ge=1, description="Page number")
    section_title: Optional[str] = Field(None, description="Section title")
    xbrl_tag: Optional[str] = Field(None, description="Associated XBRL tag")
    
    # Content
    text_content: str = Field(
        ..., min_length=1, max_length=10000,
        description="Passage text content"
    )
    passage_type: str = Field(
        ..., description="Type of passage (fact_context, debt_maturity, covenant, etc.)"
    )
    
    # Linkage
    linked_fact_ids: list[str] = Field(
        default_factory=list,
        description="Fact IDs this passage supports"
    )
    
    # Timestamps
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# =============================================================================
# Extraction Job
# =============================================================================


class ExtractionJobRequest(BaseModel):
    """Request to run extraction on evidence."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Specific evidence IDs to extract from"
    )
    claim_id: Optional[str] = Field(
        None, description="Claim ID to extract evidence for"
    )
    
    # Options
    min_confidence: Decimal = Field(
        default=DEFAULT_MIN_CONFIDENCE,
        ge=Decimal("0"), le=Decimal("1"),
        description="Minimum confidence threshold"
    )
    allow_low_confidence: bool = Field(
        default=False,
        description="Include LOW confidence facts (TEXT extraction)"
    )
    force_reextract: bool = Field(
        default=False,
        description="Re-extract even if already processed"
    )
    
    # Tracing
    trace_id: Optional[str] = Field(
        None, description="Trace ID for correlation (auto-generated if not provided)"
    )
    
    @model_validator(mode="after")
    def validate_at_least_one_target(self) -> "ExtractionJobRequest":
        """Ensure at least one target is specified."""
        if not self.evidence_ids and not self.claim_id:
            raise ValueError("Either evidence_ids or claim_id must be provided")
        return self


class ExtractionJobResult(BaseModel):
    """Result of extraction for a single evidence item."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    evidence_id: str = Field(..., description="Evidence ID processed")
    evidence_hash: str = Field(..., description="Evidence content hash")
    
    success: bool = Field(..., description="Whether extraction succeeded")
    facts_extracted: int = Field(default=0, description="Number of facts extracted")
    passages_extracted: int = Field(default=0, description="Number of passages")
    
    # Fact IDs produced
    fact_ids: list[str] = Field(default_factory=list)
    passage_ids: list[str] = Field(default_factory=list)
    
    # Errors if failed
    refusal_code: Optional[ExtractionRefusalCode] = Field(None)
    error_message: Optional[str] = Field(None)
    
    # Method used
    extraction_method: Optional[ExtractionMethod] = Field(None)
    
    # Timing
    extraction_duration_ms: int = Field(default=0)


class ExtractionJob(BaseModel):
    """Extraction job status and results."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    job_id: str = Field(..., description="Unique job identifier")
    status: ExtractionJobStatus = Field(..., description="Current job status")
    
    # Request info
    evidence_count: int = Field(..., description="Number of evidence items")
    claim_id: Optional[str] = Field(None, description="Associated claim ID")
    trace_id: str = Field(..., description="Trace ID")
    
    # Progress
    completed_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    
    # Results
    results: list[ExtractionJobResult] = Field(default_factory=list)
    
    # Aggregate stats
    total_facts: int = Field(default=0)
    total_passages: int = Field(default=0)
    
    # Timing
    started_at: Optional[datetime] = Field(None)
    completed_at: Optional[datetime] = Field(None)
    
    # Errors
    error_message: Optional[str] = Field(None)


# =============================================================================
# API Request/Response Models
# =============================================================================


class RunExtractionRequest(BaseModel):
    """API request to run extraction."""
    
    model_config = ConfigDict(extra="forbid")
    
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence IDs to extract from"
    )
    claim_id: Optional[str] = Field(
        None, description="Claim ID to get evidence for"
    )
    min_confidence: Decimal = Field(
        default=DEFAULT_MIN_CONFIDENCE,
        description="Minimum confidence threshold"
    )
    allow_low_confidence: bool = Field(default=False)
    force_reextract: bool = Field(default=False)
    trace_id: Optional[str] = Field(None)


class RunExtractionResponse(BaseModel):
    """API response for extraction request."""
    
    model_config = ConfigDict(frozen=True)
    
    job_id: str = Field(..., description="Job ID for status tracking")
    status: ExtractionJobStatus = Field(...)
    evidence_count: int = Field(...)
    message: str = Field(default="Extraction job started")


class GetFactsRequest(BaseModel):
    """Request to get facts by entity or claim."""
    
    model_config = ConfigDict(extra="forbid")
    
    entity_id: Optional[str] = Field(None, description="Entity ID")
    entity_id_type: Optional[str] = Field(None, description="Type of entity ID")
    claim_id: Optional[str] = Field(None, description="Claim ID")
    fact_types: Optional[list[str]] = Field(
        None, description="Filter by fact types"
    )
    min_confidence: Optional[Decimal] = Field(None)
    as_of_date_start: Optional[date] = Field(None)
    as_of_date_end: Optional[date] = Field(None)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class GetFactsResponse(BaseModel):
    """Response with facts."""
    
    model_config = ConfigDict(frozen=True)
    
    facts: list[FinancialFact] = Field(default_factory=list)
    total_count: int = Field(...)
    offset: int = Field(...)
    limit: int = Field(...)


class ExtractionRefusal(BaseModel):
    """Structured refusal for extraction failures."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    code: ExtractionRefusalCode = Field(..., description="Refusal code")
    message: str = Field(..., description="Human-readable message")
    evidence_id: Optional[str] = Field(None)
    details: dict[str, Any] = Field(default_factory=dict)
