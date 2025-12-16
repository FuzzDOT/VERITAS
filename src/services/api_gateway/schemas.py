"""
API Gateway Schemas - Production-Grade Request/Response Models
================================================================

Defines all schemas for the solvency evaluation API with exhaustive validation.
These schemas enforce strict invariants required for institutional-grade operation.

Design Principles:
- All inputs must be explicitly validated with clear bounds
- Ambiguous or underspecified requests are rejected
- Schemas are immutable after creation
- All fields use deterministic normalization
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Optional, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
    computed_field,
)

from shared.schemas import TruthStatus, ConfidenceLevel


# =============================================================================
# Constants & Bounds
# =============================================================================

# Jurisdiction allowlist - ISO 3166-1 alpha-2 codes of supported jurisdictions
SUPPORTED_JURISDICTIONS: frozenset[str] = frozenset({
    # G20 Nations
    "US", "CA", "MX", "BR", "AR",  # Americas
    "GB", "DE", "FR", "IT", "ES", "NL", "CH", "BE", "AT", "IE", "LU",  # Europe
    "JP", "CN", "KR", "IN", "AU", "SG", "HK",  # Asia-Pacific
    "ZA", "SA", "AE",  # Africa & Middle East
    # EU Members
    "PL", "SE", "DK", "FI", "NO", "PT", "GR", "CZ", "RO", "HU",
})

# Analysis horizon bounds (in months)
MIN_HORIZON_MONTHS: int = 1
MAX_HORIZON_MONTHS: int = 120  # 10 years max

# Scenario shock bounds (as percentages, e.g., -50.0 means -50%)
MIN_SHOCK_PERCENT: Decimal = Decimal("-100.0")  # Cannot lose more than 100%
MAX_SHOCK_PERCENT: Decimal = Decimal("500.0")  # Max 5x increase

# Confidence threshold bounds
MIN_CONFIDENCE_THRESHOLD: Decimal = Decimal("0.0")
MAX_CONFIDENCE_THRESHOLD: Decimal = Decimal("1.0")

# Entity ID length constraints
MIN_ENTITY_ID_LENGTH: int = 1
MAX_ENTITY_ID_LENGTH: int = 128

# Currency allowlist - ISO 4217 codes
SUPPORTED_CURRENCIES: frozenset[str] = frozenset({
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY", "HKD", "SGD",
    "KRW", "INR", "BRL", "MXN", "ZAR", "SAR", "AED", "SEK", "NOK", "DKK",
})

# Maximum values for financial figures (prevents overflow/abuse)
MAX_MONETARY_VALUE: Decimal = Decimal("1e18")  # Quintillion
MIN_MONETARY_VALUE: Decimal = Decimal("-1e18")


# =============================================================================
# Enums
# =============================================================================


class EntityClassification(str, Enum):
    """Classification of the entity being evaluated."""
    
    BANK = "bank"
    INSURANCE_COMPANY = "insurance_company"
    ASSET_MANAGER = "asset_manager"
    PENSION_FUND = "pension_fund"
    HEDGE_FUND = "hedge_fund"
    BROKER_DEALER = "broker_dealer"
    CORPORATE = "corporate"
    SOVEREIGN = "sovereign"
    MUNICIPAL = "municipal"
    SPV = "spv"  # Special Purpose Vehicle


class RegulatoryFramework(str, Enum):
    """Applicable regulatory framework for solvency assessment."""
    
    BASEL_III = "basel_iii"
    BASEL_IV = "basel_iv"
    SOLVENCY_II = "solvency_ii"
    IFRS_17 = "ifrs_17"
    US_GAAP = "us_gaap"
    DODD_FRANK = "dodd_frank"
    SEC_RULE_15C3_1 = "sec_rule_15c3_1"  # Net capital rule
    CUSTOM = "custom"


class ScenarioType(str, Enum):
    """Type of stress scenario."""
    
    BASELINE = "baseline"
    ADVERSE = "adverse"
    SEVERELY_ADVERSE = "severely_adverse"
    CUSTOM = "custom"


class ShockVariable(str, Enum):
    """Variables that can be shocked in stress scenarios."""
    
    INTEREST_RATE = "interest_rate"
    CREDIT_SPREAD = "credit_spread"
    EQUITY_PRICE = "equity_price"
    FX_RATE = "fx_rate"
    COMMODITY_PRICE = "commodity_price"
    REAL_ESTATE = "real_estate"
    VOLATILITY = "volatility"
    GDP_GROWTH = "gdp_growth"
    UNEMPLOYMENT = "unemployment"
    INFLATION = "inflation"
    DEFAULT_RATE = "default_rate"
    RECOVERY_RATE = "recovery_rate"
    LIQUIDITY = "liquidity"


class OutputFormat(str, Enum):
    """Requested output format."""
    
    FULL = "full"
    SUMMARY = "summary"
    METRICS_ONLY = "metrics_only"


class Priority(str, Enum):
    """Request priority level."""
    
    STANDARD = "standard"
    HIGH = "high"
    CRITICAL = "critical"


# =============================================================================
# Sub-Schemas
# =============================================================================


class ScenarioShock(BaseModel):
    """A single shock to apply in a stress scenario."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    variable: ShockVariable = Field(
        ...,
        description="The variable to shock"
    )
    shock_percent: Decimal = Field(
        ...,
        ge=MIN_SHOCK_PERCENT,
        le=MAX_SHOCK_PERCENT,
        description="Shock magnitude as percentage (e.g., -20.0 for -20%)"
    )
    time_horizon_months: int = Field(
        default=12,
        ge=MIN_HORIZON_MONTHS,
        le=MAX_HORIZON_MONTHS,
        description="Duration over which shock occurs"
    )
    
    @field_validator("shock_percent", mode="before")
    @classmethod
    def normalize_shock_percent(cls, v: Any) -> Decimal:
        """Normalize shock percent to Decimal with 4 decimal places."""
        if isinstance(v, (int, float)):
            v = Decimal(str(v))
        if isinstance(v, Decimal):
            return v.quantize(Decimal("0.0001"))
        raise ValueError(f"Cannot convert {type(v)} to Decimal")


class StressScenario(BaseModel):
    """A stress scenario consisting of multiple shocks."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    scenario_type: ScenarioType = Field(
        ...,
        description="Type of stress scenario"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Human-readable scenario name"
    )
    shocks: list[ScenarioShock] = Field(
        default_factory=list,
        max_length=50,
        description="List of shocks to apply"
    )
    description: Optional[str] = Field(
        None,
        max_length=2000,
        description="Detailed scenario description"
    )
    
    @model_validator(mode="after")
    def validate_custom_has_shocks(self) -> "StressScenario":
        """Custom scenarios must have at least one shock defined."""
        if self.scenario_type == ScenarioType.CUSTOM and len(self.shocks) == 0:
            raise ValueError("Custom scenarios must define at least one shock")
        return self
    
    @model_validator(mode="after")
    def validate_no_duplicate_shocks(self) -> "StressScenario":
        """Each variable can only be shocked once per scenario."""
        variables = [s.variable for s in self.shocks]
        if len(variables) != len(set(variables)):
            raise ValueError("Duplicate shock variables are not allowed in a single scenario")
        return self


class AnalysisHorizon(BaseModel):
    """Time horizon for solvency analysis."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    months: int = Field(
        ...,
        ge=MIN_HORIZON_MONTHS,
        le=MAX_HORIZON_MONTHS,
        description="Analysis horizon in months"
    )
    reference_date: date = Field(
        ...,
        description="Reference date for the analysis (YYYY-MM-DD)"
    )
    
    @field_validator("reference_date", mode="after")
    @classmethod
    def validate_reference_date(cls, v: date) -> date:
        """Reference date must not be more than 1 year in the past or future."""
        today = date.today()
        days_diff = abs((v - today).days)
        if days_diff > 365:
            raise ValueError("Reference date must be within 1 year of today")
        return v


class EntityIdentifier(BaseModel):
    """Unique identifier for the entity being evaluated."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    external_id: str = Field(
        ...,
        min_length=MIN_ENTITY_ID_LENGTH,
        max_length=MAX_ENTITY_ID_LENGTH,
        description="External identifier (e.g., LEI, CUSIP, internal ID)"
    )
    id_type: str = Field(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[A-Z][A-Z0-9_]*$",
        description="Type of identifier (e.g., LEI, CUSIP, INTERNAL)"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Legal name of the entity"
    )
    
    @field_validator("external_id", mode="after")
    @classmethod
    def normalize_external_id(cls, v: str) -> str:
        """Normalize external ID: strip whitespace, uppercase."""
        return v.strip().upper()
    
    @field_validator("name", mode="after")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        """Normalize entity name: strip extra whitespace."""
        return " ".join(v.split())


class ThresholdConfiguration(BaseModel):
    """Configuration for solvency thresholds."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    minimum_capital_ratio: Optional[Decimal] = Field(
        None,
        ge=Decimal("0.0"),
        le=Decimal("1.0"),
        description="Minimum required capital ratio (0.0-1.0)"
    )
    target_capital_ratio: Optional[Decimal] = Field(
        None,
        ge=Decimal("0.0"),
        le=Decimal("1.0"),
        description="Target capital ratio (0.0-1.0)"
    )
    liquidity_coverage_ratio: Optional[Decimal] = Field(
        None,
        ge=Decimal("0.0"),
        le=Decimal("10.0"),
        description="Minimum liquidity coverage ratio"
    )
    confidence_threshold: Decimal = Field(
        default=Decimal("0.95"),
        ge=MIN_CONFIDENCE_THRESHOLD,
        le=MAX_CONFIDENCE_THRESHOLD,
        description="Minimum confidence level required for determination"
    )
    
    @model_validator(mode="after")
    def validate_threshold_ordering(self) -> "ThresholdConfiguration":
        """Target ratio must be >= minimum ratio if both specified."""
        if self.minimum_capital_ratio is not None and self.target_capital_ratio is not None:
            if self.target_capital_ratio < self.minimum_capital_ratio:
                raise ValueError("Target capital ratio must be >= minimum capital ratio")
        return self


class OutputPolicy(BaseModel):
    """Policy governing output generation."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    format: OutputFormat = Field(
        default=OutputFormat.FULL,
        description="Output format level"
    )
    include_evidence_chain: bool = Field(
        default=True,
        description="Whether to include evidence chain in response"
    )
    include_reasoning_trace: bool = Field(
        default=True,
        description="Whether to include reasoning trace"
    )
    include_sensitivity_analysis: bool = Field(
        default=False,
        description="Whether to include sensitivity analysis"
    )
    max_evidence_items: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum evidence items to return"
    )


class EvidencePolicy(BaseModel):
    """Policy governing evidence requirements."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    require_audited_statements: bool = Field(
        default=True,
        description="Whether to require audited financial statements"
    )
    max_statement_age_days: int = Field(
        default=365,
        ge=1,
        le=730,
        description="Maximum age of financial statements in days"
    )
    minimum_evidence_sources: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Minimum number of independent evidence sources"
    )
    accept_provisional_data: bool = Field(
        default=False,
        description="Whether to accept unaudited/provisional data"
    )


# =============================================================================
# Main Request Schema
# =============================================================================


class SolvencyEvaluationRequest(BaseModel):
    """
    Production-grade solvency evaluation request.
    
    This schema enforces all invariants required for institutional clients:
    - All required fields must be present and valid
    - Jurisdiction must be supported
    - Horizons must be within bounds
    - Scenario shocks must be within valid ranges
    - Entity identification must be unambiguous
    """
    
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )
    
    # === Required Fields ===
    
    entity: EntityIdentifier = Field(
        ...,
        description="The entity to evaluate"
    )
    jurisdiction: str = Field(
        ...,
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z]{2}$",
        description="ISO 3166-1 alpha-2 jurisdiction code"
    )
    entity_classification: EntityClassification = Field(
        ...,
        description="Classification of the entity"
    )
    regulatory_framework: RegulatoryFramework = Field(
        ...,
        description="Applicable regulatory framework"
    )
    analysis_horizon: AnalysisHorizon = Field(
        ...,
        description="Time horizon for analysis"
    )
    reporting_currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 currency code for reporting"
    )
    
    # === Optional Fields with Defaults ===
    
    stress_scenarios: list[StressScenario] = Field(
        default_factory=list,
        max_length=20,
        description="Stress scenarios to evaluate"
    )
    thresholds: ThresholdConfiguration = Field(
        default_factory=ThresholdConfiguration,
        description="Threshold configuration"
    )
    output_policy: OutputPolicy = Field(
        default_factory=OutputPolicy,
        description="Output generation policy"
    )
    evidence_policy: EvidencePolicy = Field(
        default_factory=EvidencePolicy,
        description="Evidence requirements policy"
    )
    priority: Priority = Field(
        default=Priority.STANDARD,
        description="Request priority"
    )
    
    # === Client Context ===
    
    client_request_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9_\-\.]+$",
        description="Client-provided request ID for idempotency"
    )
    callback_url: Optional[str] = Field(
        None,
        max_length=2048,
        pattern=r"^https://",
        description="Webhook URL for async result delivery (must be HTTPS)"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Client-provided metadata (not used in evaluation)"
    )
    
    # === Validators ===
    
    @field_validator("jurisdiction", mode="after")
    @classmethod
    def validate_jurisdiction(cls, v: str) -> str:
        """Validate jurisdiction is supported."""
        normalized = v.upper()
        if normalized not in SUPPORTED_JURISDICTIONS:
            raise ValueError(
                f"Jurisdiction '{v}' is not supported. "
                f"Supported jurisdictions: {sorted(SUPPORTED_JURISDICTIONS)}"
            )
        return normalized
    
    @field_validator("reporting_currency", mode="after")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Validate currency is supported."""
        normalized = v.upper()
        if normalized not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Currency '{v}' is not supported. "
                f"Supported currencies: {sorted(SUPPORTED_CURRENCIES)}"
            )
        return normalized
    
    @model_validator(mode="after")
    def validate_framework_jurisdiction_compatibility(self) -> "SolvencyEvaluationRequest":
        """Validate regulatory framework is applicable to jurisdiction."""
        eu_frameworks = {RegulatoryFramework.SOLVENCY_II, RegulatoryFramework.IFRS_17}
        us_frameworks = {
            RegulatoryFramework.DODD_FRANK, 
            RegulatoryFramework.SEC_RULE_15C3_1,
            RegulatoryFramework.US_GAAP,
        }
        eu_jurisdictions = {
            "DE", "FR", "IT", "ES", "NL", "BE", "AT", "IE", "LU", 
            "PL", "SE", "DK", "FI", "PT", "GR", "CZ", "RO", "HU"
        }
        
        if self.regulatory_framework in eu_frameworks and self.jurisdiction not in eu_jurisdictions:
            if self.jurisdiction == "US":
                raise ValueError(
                    f"Regulatory framework '{self.regulatory_framework.value}' "
                    f"is not applicable in jurisdiction '{self.jurisdiction}'"
                )
        
        if self.regulatory_framework in us_frameworks and self.jurisdiction not in {"US"}:
            # Allow US frameworks for entities operating under US rules even in other jurisdictions
            pass  # This is a soft warning, not an error
        
        return self
    
    @model_validator(mode="after")
    def validate_entity_classification_framework(self) -> "SolvencyEvaluationRequest":
        """Validate entity classification matches regulatory framework."""
        bank_frameworks = {
            RegulatoryFramework.BASEL_III, 
            RegulatoryFramework.BASEL_IV,
            RegulatoryFramework.DODD_FRANK,
        }
        insurance_frameworks = {
            RegulatoryFramework.SOLVENCY_II, 
            RegulatoryFramework.IFRS_17,
        }
        broker_frameworks = {RegulatoryFramework.SEC_RULE_15C3_1}
        
        if self.entity_classification == EntityClassification.BANK:
            if self.regulatory_framework not in bank_frameworks | {RegulatoryFramework.CUSTOM}:
                raise ValueError(
                    f"Banks typically require Basel/Dodd-Frank framework, "
                    f"not '{self.regulatory_framework.value}'"
                )
        
        if self.entity_classification == EntityClassification.INSURANCE_COMPANY:
            if self.regulatory_framework not in insurance_frameworks | {RegulatoryFramework.CUSTOM}:
                raise ValueError(
                    f"Insurance companies typically require Solvency II/IFRS 17, "
                    f"not '{self.regulatory_framework.value}'"
                )
        
        if self.entity_classification == EntityClassification.BROKER_DEALER:
            if self.regulatory_framework not in broker_frameworks | {RegulatoryFramework.CUSTOM}:
                raise ValueError(
                    f"Broker-dealers typically require SEC Rule 15c3-1, "
                    f"not '{self.regulatory_framework.value}'"
                )
        
        return self


# =============================================================================
# Canonical Request (Internal)
# =============================================================================


class CanonicalSolvencyRequest(BaseModel):
    """
    Canonicalized, validated request ready for orchestration.
    
    This is the internal representation after all validation and normalization.
    It includes computed fields like the request hash for idempotency.
    """
    
    model_config = ConfigDict(frozen=True)
    
    # Canonical ID assigned by the system
    claim_id: str = Field(..., description="System-assigned claim ID")
    
    # Original request (frozen)
    request: SolvencyEvaluationRequest
    
    # Computed fields
    request_hash: str = Field(..., description="Deterministic hash of the request")
    trace_id: str = Field(..., description="Trace ID for request correlation")
    received_at: datetime = Field(..., description="Timestamp when request was received")
    
    # Normalization metadata
    normalized_at: datetime = Field(..., description="Timestamp of normalization")
    api_version: str = Field(default="v1", description="API version used")


# =============================================================================
# Response Schemas
# =============================================================================


class SolvencyEvaluationAccepted(BaseModel):
    """Response when a solvency evaluation request is accepted."""
    
    model_config = ConfigDict(frozen=True)
    
    claim_id: str = Field(..., description="Assigned claim ID for tracking")
    request_hash: str = Field(..., description="Hash of the normalized request")
    status: Literal["accepted"] = "accepted"
    message: str = Field(
        default="Solvency evaluation request accepted for processing",
        description="Human-readable status message"
    )
    trace_id: str = Field(..., description="Trace ID for support reference")
    estimated_completion_seconds: Optional[int] = Field(
        None,
        description="Estimated processing time in seconds"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class RefusalResponse(BaseModel):
    """Structured refusal response for rejected requests."""
    
    model_config = ConfigDict(frozen=True)
    
    refused: Literal[True] = True
    reason: str = Field(..., description="Primary refusal reason")
    category: str = Field(..., description="Refusal category")
    field_errors: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Field-level validation errors"
    )
    policy_violations: list[str] = Field(
        default_factory=list,
        description="List of violated policies"
    )
    trace_id: str = Field(..., description="Trace ID for support reference")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class HealthResponse(BaseModel):
    """Health check response."""
    
    status: Literal["healthy", "degraded", "unhealthy"]
    service: str = "api-gateway"
    version: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    checks: dict[str, str] = Field(default_factory=dict)


class ReadinessResponse(BaseModel):
    """Readiness check response."""
    
    ready: bool
    checks: dict[str, bool] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
