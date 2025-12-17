"""
Reasoning Engine Schemas - Production-Grade Solvency Evaluation Models
========================================================================

Defines all schemas for deterministic solvency evaluation:
- SolvencyEvaluationRequest: Input for evaluation
- SolvencyEvaluationResult: Complete output with probability interval
- ReasoningRefusal: Structured refusal when evaluation cannot proceed
- SensitivityAnalysis: Fragility and driver analysis
- ReasoningArtifact: Intermediate computation trace for audit

Design Principles:
- All computation is deterministic given inputs + seed
- Probability is expressed as an interval [p_low, p_high]
- Refusals enumerate missing facts and explain why they matter
- Sensitivity analysis identifies top risk drivers
- No LLM integration, no probabilistic guessing
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, FrozenSet, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# Constants
# =============================================================================

# Engine version for reproducibility
ENGINE_VERSION: str = "1.0.0"

# Default Monte Carlo sample count
DEFAULT_SAMPLE_COUNT: int = 10_000

# Minimum sample count for meaningful results
MIN_SAMPLE_COUNT: int = 1_000

# Maximum sample count to prevent excessive computation
MAX_SAMPLE_COUNT: int = 100_000

# Confidence threshold for fact inclusion (default)
DEFAULT_MIN_CONFIDENCE: Decimal = Decimal("0.60")

# Maximum staleness for facts (days from as_of_date to reference_date)
DEFAULT_MAX_STALENESS_DAYS: int = 365

# Mapping from confidence to distribution width (standard deviation multiplier)
# Higher confidence = narrower distribution = less uncertainty
CONFIDENCE_TO_UNCERTAINTY: dict[str, Decimal] = {
    "1.00": Decimal("0.00"),    # Perfect confidence = no uncertainty
    "0.95": Decimal("0.02"),    # Very high confidence
    "0.90": Decimal("0.05"),    # High confidence
    "0.80": Decimal("0.10"),    # Medium-high confidence
    "0.70": Decimal("0.15"),    # Medium confidence
    "0.60": Decimal("0.20"),    # Medium-low confidence (threshold)
    "0.50": Decimal("0.30"),    # Low confidence
    "0.40": Decimal("0.40"),    # Very low confidence
}

# Required fact types for basic solvency (minimum set)
REQUIRED_SOLVENCY_FACTS: frozenset[str] = frozenset({
    "total_assets",
    "total_liabilities",
    "cash_and_equivalents",
    "total_debt",
    "operating_income",
    "interest_expense",
})

# Material facts that improve analysis quality
MATERIAL_SOLVENCY_FACTS: frozenset[str] = frozenset({
    "total_equity",
    "current_assets",
    "current_liabilities",
    "operating_cash_flow",
    "net_income",
    "revenue",
})

# Supported scenario shock types
SUPPORTED_SHOCK_TYPES: frozenset[str] = frozenset({
    "interest_rate",
    "credit_spread",
    "refinancing_spread",
    "revenue_decline",
    "cost_increase",
    "asset_impairment",
})


# =============================================================================
# Enums
# =============================================================================


class EvaluationStatus(str, Enum):
    """Status of a solvency evaluation."""
    
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    REFUSED = "refused"
    FAILED = "failed"


class SolvencyOutcome(str, Enum):
    """Discrete solvency outcome."""
    
    SOLVENT = "solvent"           # Entity can meet obligations
    DISTRESSED = "distressed"     # Entity at risk but not insolvent
    INSOLVENT = "insolvent"       # Entity cannot meet obligations
    INDETERMINATE = "indeterminate"  # Cannot determine with available data


class RefusalCode(str, Enum):
    """Codes for evaluation refusals."""
    
    # Fact-related refusals
    REQUIRED_FACTS_MISSING = "required_facts_missing"
    FACTS_STALE = "facts_stale"
    FACTS_LOW_CONFIDENCE = "facts_low_confidence"
    FACTS_INCONSISTENT = "facts_inconsistent"
    
    # Claim-related refusals
    CLAIM_NOT_FOUND = "claim_not_found"
    CLAIM_INVALID = "claim_invalid"
    ENTITY_NOT_FOUND = "entity_not_found"
    
    # Scenario-related refusals
    SHOCK_UNSUPPORTED = "shock_unsupported"
    SCENARIO_INVALID = "scenario_invalid"
    
    # Computation-related refusals
    COMPUTATION_ERROR = "computation_error"
    SEED_INVALID = "seed_invalid"


class FailureMode(str, Enum):
    """Types of solvency failure modes."""
    
    LIQUIDITY_SHORTFALL = "liquidity_shortfall"
    INTEREST_COVERAGE_BREACH = "interest_coverage_breach"
    DEBT_SERVICE_FAILURE = "debt_service_failure"
    MATURITY_REFINANCING_STRESS = "maturity_refinancing_stress"
    COVENANT_BREACH = "covenant_breach"
    REGULATORY_CAPITAL_BREACH = "regulatory_capital_breach"
    NEGATIVE_EQUITY = "negative_equity"


class SensitivityDriver(str, Enum):
    """Categories of sensitivity drivers."""
    
    CASH_POSITION = "cash_position"
    INTEREST_EXPENSE = "interest_expense"
    OPERATING_CASH_FLOW = "operating_cash_flow"
    REFINANCING_SPREAD = "refinancing_spread"
    REVENUE = "revenue"
    DEBT_LEVEL = "debt_level"
    CURRENT_RATIO = "current_ratio"


# =============================================================================
# Sub-Schemas: Scenario Shocks
# =============================================================================


class ScenarioShock(BaseModel):
    """A single shock to apply in a scenario."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    shock_type: str = Field(..., description="Type of shock")
    magnitude_bps: int = Field(
        ..., description="Shock magnitude in basis points"
    )
    direction: Literal["up", "down"] = Field(
        default="up", description="Direction of shock"
    )
    
    @field_validator("shock_type")
    @classmethod
    def validate_shock_type(cls, v: str) -> str:
        if v not in SUPPORTED_SHOCK_TYPES:
            raise ValueError(f"Unsupported shock type: {v}")
        return v


class Scenario(BaseModel):
    """A complete scenario specification."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    scenario_id: str = Field(..., description="Unique scenario ID")
    name: str = Field(..., description="Human-readable name")
    shocks: list[ScenarioShock] = Field(
        default_factory=list, description="List of shocks"
    )
    is_baseline: bool = Field(default=False, description="Is this the baseline?")


# =============================================================================
# Sub-Schemas: Fact Selection
# =============================================================================


class FactSelectionPolicy(BaseModel):
    """Policy for selecting facts for evaluation."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    min_confidence: Decimal = Field(
        default=DEFAULT_MIN_CONFIDENCE,
        ge=Decimal("0"), le=Decimal("1"),
        description="Minimum confidence threshold"
    )
    max_staleness_days: int = Field(
        default=DEFAULT_MAX_STALENESS_DAYS,
        ge=1,
        description="Maximum days from as_of_date to reference_date"
    )
    prefer_higher_confidence: bool = Field(
        default=True,
        description="When tie-breaking, prefer higher confidence"
    )
    prefer_newer_date: bool = Field(
        default=True,
        description="When tie-breaking, prefer more recent facts"
    )


class SelectedFact(BaseModel):
    """A fact selected for use in evaluation."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    fact_id: str = Field(..., description="Fact ID")
    fact_type: str = Field(..., description="Type of fact")
    value: Decimal = Field(..., description="Fact value")
    currency: Optional[str] = Field(None, description="Currency if applicable")
    scale: int = Field(default=0, description="Scale factor")
    as_of_date: date = Field(..., description="As-of date")
    confidence: Decimal = Field(..., description="Confidence score")
    evidence_id: str = Field(..., description="Source evidence ID")
    
    # Selection metadata
    selection_rank: int = Field(
        default=1, description="Rank among candidates (1 = selected)"
    )
    candidates_considered: int = Field(
        default=1, description="Number of candidates for this fact type"
    )


class MissingFact(BaseModel):
    """A required fact that could not be found."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    fact_type: str = Field(..., description="Type of missing fact")
    priority: str = Field(..., description="Priority (required/material)")
    reason: str = Field(..., description="Why it's needed")
    impact: str = Field(..., description="Impact on analysis")


# =============================================================================
# Sub-Schemas: Computed Metrics
# =============================================================================


class ComputedMetrics(BaseModel):
    """Financial metrics computed from facts."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Liquidity metrics
    current_ratio: Optional[Decimal] = Field(
        None, description="Current assets / current liabilities"
    )
    quick_ratio: Optional[Decimal] = Field(
        None, description="(Current assets - inventory) / current liabilities"
    )
    cash_ratio: Optional[Decimal] = Field(
        None, description="Cash / current liabilities"
    )
    
    # Leverage metrics
    debt_to_equity: Optional[Decimal] = Field(
        None, description="Total debt / total equity"
    )
    debt_to_assets: Optional[Decimal] = Field(
        None, description="Total debt / total assets"
    )
    
    # Coverage metrics
    interest_coverage: Optional[Decimal] = Field(
        None, description="Operating income / interest expense"
    )
    debt_service_coverage: Optional[Decimal] = Field(
        None, description="Operating cash flow / debt service"
    )
    
    # Cash flow metrics
    free_cash_flow: Optional[Decimal] = Field(
        None, description="Operating cash flow - capex"
    )
    cash_burn_months: Optional[Decimal] = Field(
        None, description="Months of runway at current burn"
    )
    
    # Computed from facts
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class StressedMetrics(BaseModel):
    """Metrics after applying scenario shocks."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    scenario_id: str = Field(..., description="Scenario that was applied")
    baseline_metrics: ComputedMetrics = Field(
        ..., description="Metrics before stress"
    )
    stressed_metrics: ComputedMetrics = Field(
        ..., description="Metrics after stress"
    )
    
    # Delta analysis
    interest_coverage_delta: Optional[Decimal] = Field(None)
    cash_ratio_delta: Optional[Decimal] = Field(None)


# =============================================================================
# Sub-Schemas: Failure Modes
# =============================================================================


class TriggeredFailureMode(BaseModel):
    """A failure mode that was triggered in simulation."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    mode: FailureMode = Field(..., description="Type of failure")
    trigger_threshold: Decimal = Field(
        ..., description="Threshold that was breached"
    )
    actual_value: Decimal = Field(
        ..., description="Actual value that triggered"
    )
    frequency: Decimal = Field(
        ..., ge=Decimal("0"), le=Decimal("1"),
        description="Frequency in Monte Carlo samples"
    )
    contribution_to_insolvency: Decimal = Field(
        ..., ge=Decimal("0"), le=Decimal("1"),
        description="Contribution to overall insolvency probability"
    )


# =============================================================================
# Sub-Schemas: Probability Interval
# =============================================================================


class ProbabilityInterval(BaseModel):
    """
    Probability expressed as an interval rather than point estimate.
    
    The interval reflects both sampling uncertainty and model uncertainty.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    p_low: Decimal = Field(
        ..., ge=Decimal("0"), le=Decimal("1"),
        description="Lower bound of probability interval"
    )
    p_mid: Decimal = Field(
        ..., ge=Decimal("0"), le=Decimal("1"),
        description="Point estimate (median)"
    )
    p_high: Decimal = Field(
        ..., ge=Decimal("0"), le=Decimal("1"),
        description="Upper bound of probability interval"
    )
    
    # Uncertainty sources
    sampling_uncertainty: Decimal = Field(
        ..., ge=Decimal("0"),
        description="Uncertainty from Monte Carlo sampling"
    )
    model_uncertainty: Decimal = Field(
        ..., ge=Decimal("0"),
        description="Uncertainty from model assumptions"
    )
    
    @model_validator(mode="after")
    def validate_ordering(self) -> "ProbabilityInterval":
        """Ensure p_low <= p_mid <= p_high."""
        if not (self.p_low <= self.p_mid <= self.p_high):
            raise ValueError("Must have p_low <= p_mid <= p_high")
        return self


# =============================================================================
# Sub-Schemas: Sensitivity Analysis
# =============================================================================


class SensitivityResult(BaseModel):
    """Result of sensitivity analysis for one input."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    driver: SensitivityDriver = Field(..., description="The input driver")
    fact_type: Optional[str] = Field(
        None, description="Associated fact type if any"
    )
    
    # Perturbation analysis
    base_value: Decimal = Field(..., description="Base value")
    perturbation_pct: Decimal = Field(
        default=Decimal("10"),
        description="Perturbation percentage applied"
    )
    
    # Impact on insolvency probability
    p_insolvency_base: Decimal = Field(
        ..., description="Insolvency probability at base"
    )
    p_insolvency_perturbed: Decimal = Field(
        ..., description="Insolvency probability after perturbation"
    )
    delta_p: Decimal = Field(
        ..., description="Change in insolvency probability"
    )
    
    # Ranking
    rank: int = Field(..., ge=1, description="Rank by impact")
    normalized_contribution: Decimal = Field(
        ..., ge=Decimal("0"), le=Decimal("1"),
        description="Normalized contribution to total sensitivity"
    )


class SensitivityAnalysis(BaseModel):
    """Complete sensitivity analysis results."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    drivers: list[SensitivityResult] = Field(
        default_factory=list,
        description="Sensitivity results ranked by impact"
    )
    
    # Summary
    top_driver: Optional[SensitivityDriver] = Field(
        None, description="Most impactful driver"
    )
    fragility_score: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"), le=Decimal("1"),
        description="Overall fragility (0=robust, 1=fragile)"
    )
    
    # Analysis metadata
    perturbation_method: str = Field(
        default="one_at_a_time",
        description="Method used for perturbation"
    )


# =============================================================================
# Reasoning Refusal
# =============================================================================


class ReasoningRefusal(BaseModel):
    """
    Structured refusal when evaluation cannot proceed.
    
    Refusals are first-class outputs that explain why evaluation
    was refused and what would be needed to proceed.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    code: RefusalCode = Field(..., description="Refusal code")
    message: str = Field(..., description="Human-readable explanation")
    
    # Missing facts if applicable
    missing_facts: list[MissingFact] = Field(
        default_factory=list,
        description="Required facts that are missing"
    )
    
    # Stale/low-confidence facts if applicable
    excluded_facts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Facts excluded due to policy"
    )
    
    # Remediation guidance
    remediation: Optional[str] = Field(
        None, description="How to resolve the refusal"
    )
    
    # Trace
    trace_id: str = Field(..., description="Trace ID for debugging")


# =============================================================================
# Reasoning Artifact (Intermediate Trace)
# =============================================================================


class ReasoningArtifact(BaseModel):
    """
    Intermediate computation trace for audit.
    
    This is NOT the full A7 trace, but captures key intermediate
    results that A7 will consume later.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    artifact_id: str = Field(..., description="Unique artifact ID")
    evaluation_id: str = Field(..., description="Parent evaluation ID")
    
    # Inputs used
    claim_id: str = Field(..., description="Claim ID evaluated")
    claim_hash: str = Field(..., description="Claim hash")
    fact_ids_used: list[str] = Field(
        default_factory=list, description="Fact IDs used"
    )
    evidence_set_hash: str = Field(
        ..., description="Hash of evidence set"
    )
    
    # Determinism
    seed: int = Field(..., description="RNG seed used")
    engine_version: str = Field(
        default=ENGINE_VERSION, description="Engine version"
    )
    sample_count: int = Field(
        default=DEFAULT_SAMPLE_COUNT, description="Monte Carlo samples"
    )
    
    # Intermediate computations
    selected_facts: list[SelectedFact] = Field(
        default_factory=list, description="Facts selected for evaluation"
    )
    baseline_metrics: Optional[ComputedMetrics] = Field(
        None, description="Baseline metrics computed"
    )
    stressed_metrics: list[StressedMetrics] = Field(
        default_factory=list, description="Stressed metrics per scenario"
    )
    
    # Failure modes
    triggered_failure_modes: list[TriggeredFailureMode] = Field(
        default_factory=list, description="Failure modes triggered"
    )
    
    # Sensitivity
    sensitivity_analysis: Optional[SensitivityAnalysis] = Field(
        None, description="Sensitivity analysis results"
    )
    
    # Timestamps
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: Optional[datetime] = Field(None)
    computation_time_ms: int = Field(default=0)


# =============================================================================
# Evaluation Request
# =============================================================================


class SolvencyEvaluationRequest(BaseModel):
    """Request to evaluate solvency for a claim."""
    
    model_config = ConfigDict(extra="forbid")
    
    # Either claim_id OR inline claim must be provided
    claim_id: Optional[str] = Field(
        None, description="Existing claim ID to evaluate"
    )
    
    # Inline claim components (if not using claim_id)
    entity_id: Optional[str] = Field(None, description="Entity ID")
    entity_id_type: Optional[str] = Field(None, description="Entity ID type")
    
    # Evaluation parameters
    reference_date: date = Field(
        default_factory=date.today,
        description="Reference date for evaluation"
    )
    horizon_months: int = Field(
        default=12, ge=3, le=60,
        description="Analysis horizon in months"
    )
    
    # Scenarios
    scenarios: list[Scenario] = Field(
        default_factory=list,
        description="Stress scenarios to evaluate"
    )
    
    # Fact selection policy
    fact_policy: FactSelectionPolicy = Field(
        default_factory=FactSelectionPolicy,
        description="Policy for fact selection"
    )
    
    # Monte Carlo parameters
    sample_count: int = Field(
        default=DEFAULT_SAMPLE_COUNT,
        ge=MIN_SAMPLE_COUNT, le=MAX_SAMPLE_COUNT,
        description="Number of Monte Carlo samples"
    )
    
    # Determinism
    seed: Optional[int] = Field(
        None, description="RNG seed (auto-derived if not provided)"
    )
    
    # Tracing
    trace_id: Optional[str] = Field(
        None, description="Trace ID for correlation"
    )
    
    @model_validator(mode="after")
    def validate_claim_source(self) -> "SolvencyEvaluationRequest":
        """Ensure either claim_id or entity is provided."""
        if not self.claim_id and not (self.entity_id and self.entity_id_type):
            raise ValueError(
                "Either claim_id or (entity_id + entity_id_type) must be provided"
            )
        return self


# =============================================================================
# Evaluation Result
# =============================================================================


class SolvencyEvaluationResult(BaseModel):
    """Complete result of solvency evaluation."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Identity
    evaluation_id: str = Field(..., description="Unique evaluation ID")
    claim_id: str = Field(..., description="Claim that was evaluated")
    
    # Status
    status: EvaluationStatus = Field(..., description="Evaluation status")
    
    # Outcome (if completed)
    outcome: Optional[SolvencyOutcome] = Field(
        None, description="Discrete solvency outcome"
    )
    
    # Probability interval (if completed)
    solvency_probability: Optional[ProbabilityInterval] = Field(
        None, description="Probability of solvency as interval"
    )
    
    # Key metrics (if completed)
    key_metrics: Optional[ComputedMetrics] = Field(
        None, description="Key financial metrics"
    )
    
    # Risk analysis (if completed)
    triggered_failure_modes: list[TriggeredFailureMode] = Field(
        default_factory=list,
        description="Failure modes that were triggered"
    )
    sensitivity_analysis: Optional[SensitivityAnalysis] = Field(
        None, description="Sensitivity analysis"
    )
    
    # Refusal (if refused)
    refusal: Optional[ReasoningRefusal] = Field(
        None, description="Refusal details if status=REFUSED"
    )
    
    # Facts used
    facts_used_count: int = Field(default=0)
    facts_excluded_count: int = Field(default=0)
    
    # Artifact reference
    artifact_id: Optional[str] = Field(
        None, description="Reference to full reasoning artifact"
    )
    
    # Determinism verification
    seed: Optional[int] = Field(None, description="RNG seed used")
    engine_version: str = Field(
        default=ENGINE_VERSION, description="Engine version"
    )
    output_hash: str = Field(
        ..., description="Deterministic hash of output"
    )
    
    # Timestamps
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: Optional[datetime] = Field(None)
    computation_time_ms: int = Field(default=0)
    
    # Tracing
    trace_id: str = Field(..., description="Trace ID")


# =============================================================================
# API Request/Response Models
# =============================================================================


class EvaluateRequest(BaseModel):
    """API request to evaluate solvency."""
    
    model_config = ConfigDict(extra="forbid")
    
    claim_id: Optional[str] = Field(None)
    entity_id: Optional[str] = Field(None)
    entity_id_type: Optional[str] = Field(None)
    reference_date: Optional[date] = Field(None)
    horizon_months: int = Field(default=12)
    scenarios: list[Scenario] = Field(default_factory=list)
    sample_count: int = Field(default=DEFAULT_SAMPLE_COUNT)
    min_confidence: Optional[Decimal] = Field(None)
    seed: Optional[int] = Field(None)
    trace_id: Optional[str] = Field(None)


class EvaluateResponse(BaseModel):
    """API response for evaluation request."""
    
    model_config = ConfigDict(frozen=True)
    
    evaluation_id: str = Field(..., description="Evaluation ID for tracking")
    status: EvaluationStatus = Field(..., description="Current status")
    message: str = Field(default="Evaluation started")


class GetResultResponse(BaseModel):
    """API response for getting evaluation result."""
    
    model_config = ConfigDict(frozen=True)
    
    result: SolvencyEvaluationResult = Field(..., description="Full result")


class GetMetricsResponse(BaseModel):
    """API response for getting evaluation metrics."""
    
    model_config = ConfigDict(frozen=True)
    
    evaluation_id: str = Field(...)
    metrics: Optional[ComputedMetrics] = Field(None)
    sensitivity: Optional[SensitivityAnalysis] = Field(None)
    failure_modes: list[TriggeredFailureMode] = Field(default_factory=list)
