"""
Claim Service Schemas - Production-Grade Claim Models
======================================================

Defines all schemas for solvency claim processing with exhaustive validation.
The Claim Service receives validated requests from the API Gateway and performs
semantic analysis to derive the canonical claim structure and required facts.

Design Principles:
- Claims are typed and only SOLVENCY claims are accepted in A3
- Entity resolution follows strict CIK/LEI/ticker rules
- Required facts are deterministically derived from claim parameters
- Semantic refusals capture economically meaningless or underspecified claims
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum, auto
from typing import Any, FrozenSet, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# Constants & Bounds
# =============================================================================

# Minimum analysis horizon for meaningful solvency analysis (in months)
MIN_MEANINGFUL_HORIZON_MONTHS: int = 3

# Minimum horizon for each reporting granularity
REPORTING_GRANULARITY_MIN_HORIZON: dict[str, int] = {
    "quarterly": 3,  # Need at least 3 months for quarterly reporting
    "semi_annual": 6,
    "annual": 12,
}

# Entity types with solvency semantics (can be evaluated for solvency)
ENTITIES_WITH_SOLVENCY_SEMANTICS: frozenset[str] = frozenset({
    "bank",
    "insurance_company",
    "broker_dealer",
    "corporate",
    "asset_manager",
    "pension_fund",
    "hedge_fund",
})

# Entity types WITHOUT solvency semantics (cannot be evaluated)
ENTITIES_WITHOUT_SOLVENCY_SEMANTICS: frozenset[str] = frozenset({
    "sovereign",  # Sovereigns can print money, solvency is political
    "municipal",  # Municipal solvency is highly jurisdiction-dependent
    "spv",  # SPVs are pass-through, solvency depends on underlying assets
})

# Shock variables supported per entity classification
SUPPORTED_SHOCKS_BY_ENTITY: dict[str, frozenset[str]] = {
    "bank": frozenset({
        "interest_rate", "credit_spread", "fx_rate", "default_rate",
        "recovery_rate", "liquidity", "real_estate",
    }),
    "insurance_company": frozenset({
        "interest_rate", "credit_spread", "equity_price", "real_estate",
        "volatility", "default_rate", "recovery_rate",
    }),
    "broker_dealer": frozenset({
        "interest_rate", "credit_spread", "equity_price", "fx_rate",
        "volatility", "liquidity",
    }),
    "corporate": frozenset({
        "interest_rate", "credit_spread", "fx_rate", "commodity_price",
        "gdp_growth", "unemployment", "inflation",
    }),
    "asset_manager": frozenset({
        "equity_price", "credit_spread", "interest_rate", "fx_rate",
        "volatility", "liquidity",
    }),
    "pension_fund": frozenset({
        "interest_rate", "equity_price", "inflation", "real_estate",
        "credit_spread", "volatility",
    }),
    "hedge_fund": frozenset({
        "equity_price", "credit_spread", "interest_rate", "fx_rate",
        "commodity_price", "volatility", "liquidity",
    }),
}

# ID type validation rules
ENTITY_ID_RULES: dict[str, dict[str, Any]] = {
    "LEI": {
        "length": 20,
        "pattern": r"^[A-Z0-9]{20}$",
        "description": "Legal Entity Identifier (ISO 17442)",
    },
    "CIK": {
        "length": 10,
        "pattern": r"^[0-9]{10}$",
        "padded": True,
        "description": "SEC Central Index Key",
    },
    "CUSIP": {
        "length": 9,
        "pattern": r"^[A-Z0-9]{9}$",
        "description": "CUSIP identifier",
    },
    "ISIN": {
        "length": 12,
        "pattern": r"^[A-Z]{2}[A-Z0-9]{10}$",
        "description": "International Securities Identification Number",
    },
    "TICKER": {
        "min_length": 1,
        "max_length": 10,
        "pattern": r"^[A-Z]{1,10}$",
        "requires_exchange": True,
        "description": "Stock ticker symbol",
    },
    "INTERNAL": {
        "min_length": 1,
        "max_length": 128,
        "description": "Internal identifier",
    },
}

# Required regulatory filings by jurisdiction and entity type
JURISDICTION_FILING_REQUIREMENTS: dict[str, dict[str, list[str]]] = {
    "US": {
        "bank": ["10-K", "10-Q", "FR Y-9C", "FFIEC 031/041"],
        "insurance_company": ["10-K", "10-Q", "Statutory Annual Statement"],
        "broker_dealer": ["10-K", "10-Q", "FOCUS Report"],
        "corporate": ["10-K", "10-Q"],
    },
    "GB": {
        "bank": ["Annual Report", "Pillar 3 Disclosure"],
        "insurance_company": ["SFCR", "Annual Report"],
        "corporate": ["Annual Report"],
    },
    # Default for other jurisdictions
    "_default": {
        "bank": ["Annual Report", "Regulatory Filings"],
        "insurance_company": ["Annual Report", "Regulatory Filings"],
        "corporate": ["Annual Report"],
    },
}


# =============================================================================
# Enums
# =============================================================================


class ClaimType(str, Enum):
    """Types of claims the system can process."""
    
    SOLVENCY = "solvency"  # A3 supports only this type
    # Future claim types:
    # LIQUIDITY = "liquidity"
    # CREDIT_QUALITY = "credit_quality"
    # MARKET_RISK = "market_risk"


class SemanticRefusalCode(str, Enum):
    """Codes for semantic refusals of claims."""
    
    # Entity-related refusals
    ENTITY_TYPE_NO_SOLVENCY_SEMANTICS = "entity_type_no_solvency_semantics"
    ENTITY_ID_INVALID_FORMAT = "entity_id_invalid_format"
    ENTITY_UNRESOLVABLE = "entity_unresolvable"
    ENTITY_TICKER_MISSING_EXCHANGE = "entity_ticker_missing_exchange"
    
    # Horizon-related refusals
    HORIZON_BELOW_REPORTING_GRANULARITY = "horizon_below_reporting_granularity"
    HORIZON_TOO_SHORT_FOR_MEANINGFUL_ANALYSIS = "horizon_too_short_meaningful"
    HORIZON_EXCEEDS_PROJECTION_CAPABILITY = "horizon_exceeds_projection"
    
    # Scenario-related refusals
    SHOCK_UNSUPPORTED_FOR_ENTITY_TYPE = "shock_unsupported_for_entity"
    SHOCK_HORIZON_EXCEEDS_ANALYSIS_HORIZON = "shock_horizon_exceeds_analysis"
    SCENARIO_INTERNALLY_INCONSISTENT = "scenario_internally_inconsistent"
    SCENARIO_ECONOMICALLY_MEANINGLESS = "scenario_economically_meaningless"
    
    # Claim structure refusals
    CLAIM_UNDERSPECIFIED = "claim_underspecified"
    CLAIM_INTERNALLY_INCONSISTENT = "claim_internally_inconsistent"
    JURISDICTION_FRAMEWORK_MISMATCH = "jurisdiction_framework_mismatch"
    
    # Other
    UNSUPPORTED_CLAIM_TYPE = "unsupported_claim_type"


class FactCategory(str, Enum):
    """Categories of financial facts."""
    
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    REGULATORY_CAPITAL = "regulatory_capital"
    DEBT_SCHEDULE = "debt_schedule"
    COVENANT = "covenant"
    OFF_BALANCE_SHEET = "off_balance_sheet"
    DERIVATIVE = "derivative"
    CONTINGENT_LIABILITY = "contingent_liability"


class FactPriority(str, Enum):
    """Priority of facts for solvency determination."""
    
    REQUIRED = "required"  # Must have for any determination
    MATERIAL = "material"  # Significantly impacts conclusion
    SUPPLEMENTARY = "supplementary"  # Improves confidence but not essential


class EntityResolutionStatus(str, Enum):
    """Status of entity identifier resolution."""
    
    RESOLVED = "resolved"  # Successfully resolved to canonical form
    NORMALIZED = "normalized"  # Normalized but not cross-verified
    UNRESOLVED = "unresolved"  # Could not resolve
    INVALID = "invalid"  # Invalid format


# =============================================================================
# Sub-Schemas
# =============================================================================


class ResolvedEntityIdentifier(BaseModel):
    """Entity identifier after resolution and normalization."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    external_id: str = Field(..., description="Original external ID (normalized)")
    id_type: str = Field(..., description="Type of identifier")
    canonical_id: str = Field(..., description="System canonical ID")
    name: str = Field(..., description="Entity name (normalized)")
    resolution_status: EntityResolutionStatus = Field(
        ..., description="Status of ID resolution"
    )
    resolution_notes: list[str] = Field(
        default_factory=list,
        description="Notes from resolution process"
    )
    alternative_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Alternative identifiers discovered during resolution"
    )


class NormalizedHorizon(BaseModel):
    """Analysis horizon after normalization and validation."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    months: int = Field(..., ge=1, le=120, description="Horizon in months")
    reference_date: date = Field(..., description="Reference date")
    end_date: date = Field(..., description="Computed end date")
    reporting_periods: int = Field(
        ..., ge=1, description="Number of reporting periods covered"
    )
    reporting_granularity: Literal["quarterly", "semi_annual", "annual"] = Field(
        ..., description="Assumed reporting granularity"
    )


class ValidatedScenario(BaseModel):
    """Stress scenario after validation against entity type."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    scenario_id: str = Field(..., description="Unique scenario identifier")
    scenario_type: str = Field(..., description="Type of scenario")
    name: str = Field(..., description="Scenario name")
    validated_shocks: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Shocks validated for this entity type"
    )
    unsupported_shocks_removed: list[str] = Field(
        default_factory=list,
        description="Shocks removed as unsupported (warnings issued)"
    )
    is_valid: bool = Field(default=True, description="Whether scenario is valid")


class RequiredFact(BaseModel):
    """A fact required to evaluate the solvency claim."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    fact_id: str = Field(..., description="Unique fact identifier")
    fact_name: str = Field(..., description="Human-readable fact name")
    category: FactCategory = Field(..., description="Fact category")
    priority: FactPriority = Field(..., description="Priority level")
    description: str = Field(..., description="What this fact represents")
    
    # Temporal requirements
    as_of_date: Optional[date] = Field(
        None, description="Required as-of date for the fact"
    )
    period_type: Literal["point_in_time", "period"] = Field(
        default="point_in_time",
        description="Whether fact is point-in-time or period-based"
    )
    period_months: Optional[int] = Field(
        None, description="Period length in months (for period-based facts)"
    )
    
    # Data requirements
    expected_unit: Optional[str] = Field(
        None, description="Expected unit (e.g., 'USD', 'ratio', 'percent')"
    )
    acceptable_sources: list[str] = Field(
        default_factory=list,
        description="Acceptable evidence sources for this fact"
    )
    
    # Scenario linkage
    applies_to_scenarios: list[str] = Field(
        default_factory=list,
        description="Scenario IDs this fact is needed for (empty = baseline)"
    )
    
    # Derivation information
    derivation_rule: Optional[str] = Field(
        None, description="How to derive if not directly available"
    )
    components: list[str] = Field(
        default_factory=list,
        description="Component fact IDs if this is a derived fact"
    )


class RequiredFactsContract(BaseModel):
    """
    The complete contract of facts required to evaluate a claim.
    
    This is a closed set - downstream services use this as the definitive
    list of facts that must be gathered.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    contract_id: str = Field(..., description="Unique contract identifier")
    claim_id: str = Field(..., description="Associated claim ID")
    version: int = Field(default=1, description="Contract version")
    
    # Facts organized by priority
    required_facts: list[RequiredFact] = Field(
        ..., description="Facts marked as REQUIRED"
    )
    material_facts: list[RequiredFact] = Field(
        default_factory=list,
        description="Facts marked as MATERIAL"
    )
    supplementary_facts: list[RequiredFact] = Field(
        default_factory=list,
        description="Facts marked as SUPPLEMENTARY"
    )
    
    # Contract metadata
    total_facts: int = Field(..., description="Total number of facts")
    categories_covered: list[FactCategory] = Field(
        ..., description="Fact categories included"
    )
    
    # Determinism guarantee
    contract_hash: str = Field(
        ..., description="Deterministic hash of the contract"
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    @classmethod
    def compute_total(cls, required: list, material: list, supplementary: list) -> int:
        """Compute total facts count."""
        return len(required) + len(material) + len(supplementary)


# =============================================================================
# Semantic Refusal
# =============================================================================


class SemanticRefusal(BaseModel):
    """
    A structured refusal for semantically invalid claims.
    
    Unlike validation errors which are syntactic, semantic refusals indicate
    that a claim is economically meaningless, internally inconsistent, or
    underspecified even though it passes schema validation.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    code: SemanticRefusalCode = Field(..., description="Refusal code")
    message: str = Field(..., description="Human-readable explanation")
    field_path: Optional[str] = Field(
        None, description="Path to problematic field (if applicable)"
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context for the refusal"
    )
    suggestion: Optional[str] = Field(
        None, description="Suggested remediation"
    )


class SemanticValidationResult(BaseModel):
    """Result of semantic validation."""
    
    model_config = ConfigDict(frozen=True)
    
    is_valid: bool = Field(..., description="Whether claim passed semantic validation")
    refusals: list[SemanticRefusal] = Field(
        default_factory=list,
        description="List of semantic refusals"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings"
    )
    
    def add_refusal(
        self,
        code: SemanticRefusalCode,
        message: str,
        field_path: Optional[str] = None,
        details: Optional[dict] = None,
        suggestion: Optional[str] = None,
    ) -> "SemanticValidationResult":
        """Return a new result with the refusal added."""
        new_refusal = SemanticRefusal(
            code=code,
            message=message,
            field_path=field_path,
            details=details or {},
            suggestion=suggestion,
        )
        return SemanticValidationResult(
            is_valid=False,
            refusals=list(self.refusals) + [new_refusal],
            warnings=list(self.warnings),
        )
    
    def add_warning(self, warning: str) -> "SemanticValidationResult":
        """Return a new result with the warning added."""
        return SemanticValidationResult(
            is_valid=self.is_valid,
            refusals=list(self.refusals),
            warnings=list(self.warnings) + [warning],
        )


# =============================================================================
# Canonical Claim
# =============================================================================


class CanonicalSolvencyClaim(BaseModel):
    """
    The canonical representation of a solvency claim.
    
    This is the output of the Claim Service after:
    - Entity resolution and normalization
    - Jurisdiction confirmation
    - Horizon interpretation
    - Scenario validation
    - Required facts derivation
    
    This object plus its RequiredFactsContract form the complete
    specification that downstream services rely on.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Identity
    claim_id: str = Field(..., description="System canonical claim ID")
    claim_type: ClaimType = Field(
        default=ClaimType.SOLVENCY,
        description="Type of claim (always SOLVENCY for A3)"
    )
    version: int = Field(default=1, description="Claim version")
    
    # Resolved entity
    entity: ResolvedEntityIdentifier = Field(
        ..., description="Resolved entity identifier"
    )
    entity_classification: str = Field(
        ..., description="Classification of the entity"
    )
    
    # Jurisdiction and regulatory
    jurisdiction: str = Field(..., description="ISO 3166-1 alpha-2 jurisdiction")
    regulatory_framework: str = Field(..., description="Applicable regulatory framework")
    
    # Normalized horizon
    analysis_horizon: NormalizedHorizon = Field(
        ..., description="Normalized analysis horizon"
    )
    
    # Validated scenarios
    baseline_scenario: ValidatedScenario = Field(
        ..., description="Baseline scenario (always present)"
    )
    stress_scenarios: list[ValidatedScenario] = Field(
        default_factory=list,
        description="Validated stress scenarios"
    )
    
    # Configuration
    reporting_currency: str = Field(..., description="ISO 4217 currency code")
    thresholds: dict[str, Decimal] = Field(
        default_factory=dict,
        description="Threshold configuration"
    )
    
    # Evidence requirements
    require_audited_statements: bool = Field(default=True)
    max_statement_age_days: int = Field(default=365)
    
    # Claim hash for determinism
    claim_hash: str = Field(
        ..., description="Deterministic hash of the canonical claim"
    )
    
    # Metadata
    source_request_hash: str = Field(
        ..., description="Hash of the source API request"
    )
    trace_id: str = Field(..., description="Trace ID for correlation")
    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    # Warnings accumulated during processing
    processing_warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings from processing"
    )


class ClaimProcessingResult(BaseModel):
    """Result of claim processing."""
    
    model_config = ConfigDict(frozen=True)
    
    success: bool = Field(..., description="Whether processing succeeded")
    
    # On success
    canonical_claim: Optional[CanonicalSolvencyClaim] = Field(
        None, description="The canonical claim (if successful)"
    )
    required_facts_contract: Optional[RequiredFactsContract] = Field(
        None, description="The required facts contract (if successful)"
    )
    
    # On failure
    semantic_refusals: list[SemanticRefusal] = Field(
        default_factory=list,
        description="Semantic refusals (if failed)"
    )
    
    # Always present
    warnings: list[str] = Field(
        default_factory=list,
        description="Processing warnings"
    )
    processing_time_ms: int = Field(
        default=0,
        description="Processing time in milliseconds"
    )
    trace_id: str = Field(..., description="Trace ID")


# =============================================================================
# API Request/Response Schemas
# =============================================================================


class ProcessClaimRequest(BaseModel):
    """Request to process a claim from API Gateway."""
    
    model_config = ConfigDict(extra="forbid")
    
    # The validated request from API Gateway
    api_request: dict[str, Any] = Field(
        ..., description="The validated SolvencyEvaluationRequest as dict"
    )
    request_hash: str = Field(
        ..., description="Hash of the API request"
    )
    trace_id: str = Field(
        ..., description="Trace ID from API Gateway"
    )
    received_at: datetime = Field(
        ..., description="When API Gateway received the request"
    )


class ProcessClaimResponse(BaseModel):
    """Response from claim processing."""
    
    model_config = ConfigDict(frozen=True)
    
    success: bool
    claim_id: Optional[str] = None
    claim_hash: Optional[str] = None
    required_facts_count: Optional[int] = None
    contract_id: Optional[str] = None
    
    # On failure
    refused: bool = False
    refusal_codes: list[str] = Field(default_factory=list)
    refusal_messages: list[str] = Field(default_factory=list)
    
    # Metadata
    warnings: list[str] = Field(default_factory=list)
    processing_time_ms: int = 0
    trace_id: str
