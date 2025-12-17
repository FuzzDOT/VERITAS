"""
Truth Versioning Service Schemas
==================================

Defines all schemas for truth versioning:
- TruthVersion: Immutable versioned outcome for a canonical solvency claim
- ClaimClassKey: Deterministic grouping key for version continuity
- TruthDiff: Structured diff between two truth versions
- ImpactAnalysis: Recomputation impact assessment

Design Principles:
- All schemas are frozen (immutable)
- Claim class keys use deterministic bucketing for comparability
- Diffs cite trace node identifiers where possible
- Impact analysis is deterministic given inputs
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# Constants
# =============================================================================

# Service version for tracking
TRUTH_VERSION_SERVICE_VERSION: str = "1.0.0"

# Horizon buckets for canonical grouping (months)
HORIZON_BUCKETS: tuple[int, ...] = (3, 6, 12, 24, 60, 120)

# As-of-date buckets: quarter-end months
QUARTER_END_MONTHS: frozenset[int] = frozenset({3, 6, 9, 12})

# Probability interval tolerance for "same" determination
PROBABILITY_TOLERANCE: Decimal = Decimal("0.01")

# Fragility tolerance for "same" determination
FRAGILITY_TOLERANCE: Decimal = Decimal("0.05")


# =============================================================================
# Enums
# =============================================================================


class TruthVersionStatus(str, Enum):
    """Status of a truth version."""
    
    CURRENT = "current"  # Latest version for claim class
    SUPERSEDED = "superseded"  # Replaced by newer version
    RETRACTED = "retracted"  # Explicitly invalidated (rare)


class PromotionResult(str, Enum):
    """Result of promotion attempt."""
    
    CREATED = "created"  # New version created
    DEDUPLICATED = "deduplicated"  # Matched existing, no new version
    SUPERSEDED_PRIOR = "superseded_prior"  # Created and superseded prior
    REJECTED_NOT_VERIFIED = "rejected_not_verified"  # Failed replay verification
    REJECTED_NO_TRACE = "rejected_no_trace"  # No trace record found
    REJECTED_NO_AUDIT = "rejected_no_audit"  # No audit record found


class DiffChangeType(str, Enum):
    """Type of change in a diff."""
    
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


class RecomputeTaskStatus(str, Enum):
    """Status of a recompute task."""
    
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# =============================================================================
# Bucketing Functions
# =============================================================================


def bucket_horizon(horizon_months: int) -> int:
    """
    Bucket horizon to standard intervals for comparability.
    
    Buckets: 3, 6, 12, 24, 60, 120 months
    Returns the smallest bucket >= horizon_months.
    """
    for bucket in HORIZON_BUCKETS:
        if horizon_months <= bucket:
            return bucket
    return HORIZON_BUCKETS[-1]


def bucket_as_of_date(as_of_date: date) -> date:
    """
    Bucket as-of date to quarter-end for comparability.
    
    Returns the quarter-end date that contains as_of_date.
    Q1: Jan-Mar -> Mar 31
    Q2: Apr-Jun -> Jun 30
    Q3: Jul-Sep -> Sep 30
    Q4: Oct-Dec -> Dec 31
    """
    month = as_of_date.month
    year = as_of_date.year
    
    if month <= 3:
        return date(year, 3, 31)
    elif month <= 6:
        return date(year, 6, 30)
    elif month <= 9:
        return date(year, 9, 30)
    else:
        return date(year, 12, 31)


def derive_claim_class_key(
    entity_id: str,
    entity_id_type: str,
    jurisdiction: str,
    scenario_name: str,
    scenario_shocks_hash: str,
    horizon_months: int,
    as_of_date: date,
) -> str:
    """
    Derive deterministic claim class key for version continuity.
    
    Components:
    - entity_id + entity_id_type (normalized)
    - jurisdiction
    - scenario_name + shocks_hash (defines the stress scenario)
    - bucketed horizon
    - bucketed as_of_date (quarter-end)
    
    Returns a canonical string key.
    """
    bucketed_horizon = bucket_horizon(horizon_months)
    bucketed_date = bucket_as_of_date(as_of_date)
    
    # Normalize components
    entity_key = f"{entity_id_type.upper()}:{entity_id.upper()}"
    jurisdiction_key = jurisdiction.upper()
    scenario_key = f"{scenario_name}:{scenario_shocks_hash[:16]}"
    horizon_key = f"H{bucketed_horizon}M"
    date_key = bucketed_date.strftime("%Y-Q%q").replace(
        "%q", str((bucketed_date.month - 1) // 3 + 1)
    )
    # Manual quarter calculation since strftime doesn't have %q
    quarter = (bucketed_date.month - 1) // 3 + 1
    date_key = f"{bucketed_date.year}-Q{quarter}"
    
    return f"{entity_key}|{jurisdiction_key}|{scenario_key}|{horizon_key}|{date_key}"


# =============================================================================
# Core Schemas
# =============================================================================


class ClaimClassKey(BaseModel):
    """
    Canonical claim class key for version grouping.
    
    This defines what makes two evaluations "about the same thing"
    for purposes of version continuity.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Entity identity
    entity_id: str = Field(..., description="Entity identifier")
    entity_id_type: str = Field(..., description="Type of entity ID")
    
    # Jurisdiction
    jurisdiction: str = Field(..., description="Legal jurisdiction")
    
    # Scenario identity
    scenario_name: str = Field(..., description="Scenario name")
    scenario_shocks_hash: str = Field(
        ..., description="Hash of scenario shocks for identity"
    )
    
    # Bucketed parameters
    horizon_bucket: int = Field(..., description="Bucketed horizon (months)")
    as_of_date_bucket: date = Field(..., description="Bucketed as-of date")
    
    # Derived key
    key: str = Field(..., description="Canonical string key")
    
    @classmethod
    def from_components(
        cls,
        entity_id: str,
        entity_id_type: str,
        jurisdiction: str,
        scenario_name: str,
        scenario_shocks_hash: str,
        horizon_months: int,
        as_of_date: date,
    ) -> "ClaimClassKey":
        """Construct from raw components."""
        key = derive_claim_class_key(
            entity_id=entity_id,
            entity_id_type=entity_id_type,
            jurisdiction=jurisdiction,
            scenario_name=scenario_name,
            scenario_shocks_hash=scenario_shocks_hash,
            horizon_months=horizon_months,
            as_of_date=as_of_date,
        )
        return cls(
            entity_id=entity_id.upper(),
            entity_id_type=entity_id_type.upper(),
            jurisdiction=jurisdiction.upper(),
            scenario_name=scenario_name,
            scenario_shocks_hash=scenario_shocks_hash,
            horizon_bucket=bucket_horizon(horizon_months),
            as_of_date_bucket=bucket_as_of_date(as_of_date),
            key=key,
        )


class ProbabilityIntervalSummary(BaseModel):
    """Probability interval for truth version."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    p_low: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))
    p_mid: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))
    p_high: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))


class KeyRisk(BaseModel):
    """A key risk identified in the evaluation."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    risk_type: str = Field(..., description="Type of risk")
    description: str = Field(..., description="Risk description")
    severity: str = Field(..., description="Severity level")
    trace_node_id: Optional[str] = Field(
        None, description="Reference to trace node"
    )


class TruthVersion(BaseModel):
    """
    Immutable versioned truth outcome for a canonical solvency claim.
    
    This is the authoritative record of a solvency determination.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Identity
    truth_version_id: str = Field(..., description="Unique version ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    
    # Claim class
    claim_class_key: ClaimClassKey = Field(
        ..., description="Canonical claim class key"
    )
    canonical_claim_hash: str = Field(
        ..., description="Hash of canonical claim"
    )
    canonical_claim_summary: str = Field(
        ..., description="Human-readable claim summary"
    )
    
    # Source evaluation
    evaluation_id: str = Field(
        ..., description="Source evaluation ID (from A6)"
    )
    
    # Outcome
    conclusion: str = Field(
        ..., description="Conclusion: solvent, insolvent, or refused"
    )
    refusal_code: Optional[str] = Field(
        None, description="Refusal code if refused"
    )
    refusal_message: Optional[str] = Field(
        None, description="Refusal message if refused"
    )
    
    # Probability (if not refused)
    probability_interval: Optional[ProbabilityIntervalSummary] = Field(
        None, description="Solvency probability interval"
    )
    
    # Risk analysis
    fragility_score: Optional[Decimal] = Field(
        None, ge=Decimal("0"), le=Decimal("1"),
        description="Fragility score (0=robust, 1=fragile)"
    )
    key_risks: list[KeyRisk] = Field(
        default_factory=list, description="Key identified risks"
    )
    top_sensitivity_driver: Optional[str] = Field(
        None, description="Most impactful sensitivity driver"
    )
    
    # Provenance hashes
    engine_version: str = Field(..., description="Reasoning engine version")
    evidence_set_hash: str = Field(..., description="Hash of evidence set")
    facts_snapshot_hash: str = Field(..., description="Hash of facts snapshot")
    policy_hash: str = Field(..., description="Hash of policy config")
    trace_hash: str = Field(..., description="Hash of trace graph")
    result_hash: str = Field(..., description="Hash of evaluation result")
    
    # Versioning
    version_number: int = Field(
        ..., ge=1, description="Version number within claim class"
    )
    status: TruthVersionStatus = Field(
        default=TruthVersionStatus.CURRENT,
        description="Version status"
    )
    supersedes_truth_version_id: Optional[str] = Field(
        None, description="Previous version this supersedes"
    )
    superseded_by_truth_version_id: Optional[str] = Field(
        None, description="Version that superseded this"
    )
    
    # Service metadata
    truth_service_version: str = Field(
        default=TRUTH_VERSION_SERVICE_VERSION,
        description="Truth versioning service version"
    )


# =============================================================================
# Diff Schemas
# =============================================================================


class EvidenceChange(BaseModel):
    """Change in evidence between versions."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    change_type: DiffChangeType = Field(..., description="Type of change")
    evidence_id: str = Field(..., description="Evidence ID")
    evidence_hash: Optional[str] = Field(None, description="Evidence hash")
    description: Optional[str] = Field(None, description="Change description")


class FactChange(BaseModel):
    """Change in a fact between versions."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    change_type: DiffChangeType = Field(..., description="Type of change")
    fact_id: str = Field(..., description="Fact ID")
    fact_type: str = Field(..., description="Fact type")
    
    # Value changes
    old_value: Optional[str] = Field(None, description="Previous value")
    new_value: Optional[str] = Field(None, description="New value")
    value_delta: Optional[str] = Field(None, description="Value difference")
    
    # Confidence/method changes
    old_confidence: Optional[str] = Field(None)
    new_confidence: Optional[str] = Field(None)
    old_extraction_method: Optional[str] = Field(None)
    new_extraction_method: Optional[str] = Field(None)
    
    # Trace reference
    trace_node_id: Optional[str] = Field(
        None, description="Reference to trace node"
    )


class PolicyChange(BaseModel):
    """Change in policy configuration."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    policy_field: str = Field(..., description="Policy field that changed")
    old_value: Optional[str] = Field(None)
    new_value: Optional[str] = Field(None)


class DecisionChange(BaseModel):
    """Change in the decision/conclusion."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    conclusion_changed: bool = Field(..., description="Did conclusion change?")
    old_conclusion: Optional[str] = Field(None)
    new_conclusion: Optional[str] = Field(None)
    
    probability_changed: bool = Field(
        ..., description="Did probability change beyond tolerance?"
    )
    old_p_mid: Optional[Decimal] = Field(None)
    new_p_mid: Optional[Decimal] = Field(None)
    p_delta: Optional[Decimal] = Field(None)
    
    fragility_changed: bool = Field(
        ..., description="Did fragility change beyond tolerance?"
    )
    old_fragility: Optional[Decimal] = Field(None)
    new_fragility: Optional[Decimal] = Field(None)
    fragility_delta: Optional[Decimal] = Field(None)
    
    top_risks_changed: bool = Field(..., description="Did top risks change?")
    risks_added: list[str] = Field(default_factory=list)
    risks_removed: list[str] = Field(default_factory=list)
    
    sensitivities_changed: bool = Field(
        ..., description="Did top sensitivities change?"
    )
    old_top_driver: Optional[str] = Field(None)
    new_top_driver: Optional[str] = Field(None)


class TruthDiff(BaseModel):
    """
    Deterministic structured diff between two truth versions.
    
    Cites trace node identifiers where possible.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Versions compared
    version_a_id: str = Field(..., description="First version ID")
    version_b_id: str = Field(..., description="Second version ID")
    
    # Metadata
    diff_generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    diff_hash: str = Field(..., description="Deterministic hash of this diff")
    
    # Evidence changes
    evidence_added: list[EvidenceChange] = Field(default_factory=list)
    evidence_removed: list[EvidenceChange] = Field(default_factory=list)
    
    # Fact changes
    facts_added: list[FactChange] = Field(default_factory=list)
    facts_removed: list[FactChange] = Field(default_factory=list)
    facts_modified: list[FactChange] = Field(default_factory=list)
    
    # Policy changes
    policies_changed: list[PolicyChange] = Field(default_factory=list)
    
    # Engine version change
    engine_version_changed: bool = Field(default=False)
    old_engine_version: Optional[str] = Field(None)
    new_engine_version: Optional[str] = Field(None)
    
    # Decision change
    decision_change: DecisionChange = Field(..., description="Decision changes")
    
    # Summary
    is_material_change: bool = Field(
        ..., description="Whether this is a material change"
    )
    change_summary: str = Field(..., description="Human-readable summary")


# =============================================================================
# Impact Analysis Schemas
# =============================================================================


class ImpactedClaimClass(BaseModel):
    """A claim class impacted by an update."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    claim_class_key: str = Field(..., description="Claim class key")
    current_truth_version_id: Optional[str] = Field(
        None, description="Current truth version if exists"
    )
    impact_reason: str = Field(..., description="Why this class is impacted")
    priority: int = Field(
        default=1, ge=1, le=10,
        description="Recomputation priority (1=highest)"
    )


class RecomputeTask(BaseModel):
    """A queued recomputation task."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    task_id: str = Field(..., description="Task ID")
    claim_class_key: str = Field(..., description="Claim class to recompute")
    current_truth_version_id: Optional[str] = Field(None)
    
    # Trigger info
    triggered_by_evidence_id: Optional[str] = Field(None)
    triggered_by_entity_id: Optional[str] = Field(None)
    trigger_reason: str = Field(..., description="Why recomputation needed")
    
    # Status
    status: RecomputeTaskStatus = Field(default=RecomputeTaskStatus.PENDING)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    priority: int = Field(default=1, ge=1, le=10)


class ImpactAnalysisResult(BaseModel):
    """Result of impact analysis."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    analysis_id: str = Field(..., description="Analysis ID")
    analyzed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    # Trigger
    evidence_id: Optional[str] = Field(None)
    entity_id: Optional[str] = Field(None)
    entity_id_type: Optional[str] = Field(None)
    date_range_start: Optional[date] = Field(None)
    date_range_end: Optional[date] = Field(None)
    
    # Results
    impacted_claim_classes: list[ImpactedClaimClass] = Field(default_factory=list)
    tasks_queued: list[RecomputeTask] = Field(default_factory=list)
    
    # Summary
    total_impacted: int = Field(default=0)
    total_queued: int = Field(default=0)


# =============================================================================
# API Request/Response Schemas
# =============================================================================


class PromoteRequest(BaseModel):
    """Request to promote an evaluation to a truth version."""
    
    model_config = ConfigDict(extra="forbid")
    
    evaluation_id: str = Field(..., description="Evaluation ID to promote")
    force_supersede: bool = Field(
        default=False,
        description="Force supersession even if hashes match"
    )


class PromoteResponse(BaseModel):
    """Response from promotion."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    result: PromotionResult = Field(..., description="Promotion result")
    truth_version_id: Optional[str] = Field(
        None, description="Created or matched version ID"
    )
    truth_version: Optional[TruthVersion] = Field(
        None, description="Full version if created"
    )
    superseded_version_id: Optional[str] = Field(
        None, description="Version that was superseded"
    )
    message: str = Field(..., description="Result message")


class GetCurrentRequest(BaseModel):
    """Request to get current truth version."""
    
    model_config = ConfigDict(extra="forbid")
    
    # By claim class key components
    entity_id: Optional[str] = Field(None)
    entity_id_type: Optional[str] = Field(None)
    jurisdiction: Optional[str] = Field(None)
    scenario_name: Optional[str] = Field(None)
    horizon_months: Optional[int] = Field(None)
    as_of_date: Optional[date] = Field(None)
    
    # Or by pre-computed key
    claim_class_key: Optional[str] = Field(None)


class GetHistoryRequest(BaseModel):
    """Request to get version history."""
    
    model_config = ConfigDict(extra="forbid")
    
    claim_class_key: str = Field(..., description="Claim class key")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
    include_superseded: bool = Field(default=True)


class GetHistoryResponse(BaseModel):
    """Response with version history."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    claim_class_key: str = Field(...)
    versions: list[TruthVersion] = Field(default_factory=list)
    total_count: int = Field(default=0)
    has_more: bool = Field(default=False)


class GetDiffRequest(BaseModel):
    """Request to diff two versions."""
    
    model_config = ConfigDict(extra="forbid")
    
    version_a_id: str = Field(..., description="First version ID")
    version_b_id: str = Field(..., description="Second version ID")


class ImpactAnalysisRequest(BaseModel):
    """Request for impact analysis."""
    
    model_config = ConfigDict(extra="forbid")
    
    # By evidence
    evidence_id: Optional[str] = Field(None)
    
    # By entity + date range
    entity_id: Optional[str] = Field(None)
    entity_id_type: Optional[str] = Field(None)
    date_range_start: Optional[date] = Field(None)
    date_range_end: Optional[date] = Field(None)
    
    # Options
    queue_tasks: bool = Field(
        default=True,
        description="Whether to queue recompute tasks"
    )
    priority: int = Field(default=5, ge=1, le=10)
    
    @model_validator(mode="after")
    def validate_trigger(self) -> "ImpactAnalysisRequest":
        """Ensure at least one trigger is provided."""
        if not self.evidence_id and not self.entity_id:
            raise ValueError("Either evidence_id or entity_id must be provided")
        return self
