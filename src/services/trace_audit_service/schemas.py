"""
Trace & Audit Service Schemas
==============================

Comprehensive Pydantic models for the immutable Reasoning Trace Graph
and append-only Audit Log system.

Node Types:
- CLAIM: The solvency claim being evaluated
- POLICY: Fact selection policy constraints
- EVIDENCE: Source evidence documents
- FACT: Financial facts extracted from evidence
- ASSUMPTION: Model assumptions (thresholds, etc.)
- COMPUTATION: Intermediate computations
- METRIC: Computed financial metrics
- FAILURE_MODE: Triggered failure mode detection
- MONTE_CARLO_RUN: Monte Carlo simulation run
- SENSITIVITY: Sensitivity analysis result
- CONCLUSION: Final solvency outcome
- REFUSAL: Refusal when evaluation cannot proceed

Edge Types:
- SUPPORTS: A → B means A supports the conclusion of B
- DERIVED_FROM: A → B means A is derived from B
- USED_IN: A → B means A was used in computation B
- PRODUCES: A → B means computation A produces output B
- CONSTRAINS: A → B means A constrains evaluation B
- TRIGGERS: A → B means condition A triggers failure B
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# Constants
# =============================================================================

# Trace service version for reproducibility
TRACE_SERVICE_VERSION: str = "1.0.0"

# Hash algorithm used for canonical hashes
HASH_ALGORITHM: str = "sha256"

# Genesis hash for audit chain
GENESIS_HASH: str = "0" * 64


# =============================================================================
# Enums
# =============================================================================


class TraceNodeType(str, Enum):
    """Types of nodes in the reasoning trace graph."""
    
    CLAIM = "claim"
    POLICY = "policy"
    EVIDENCE = "evidence"
    FACT = "fact"
    ASSUMPTION = "assumption"
    COMPUTATION = "computation"
    METRIC = "metric"
    FAILURE_MODE = "failure_mode"
    MONTE_CARLO_RUN = "monte_carlo_run"
    SENSITIVITY = "sensitivity"
    CONCLUSION = "conclusion"
    REFUSAL = "refusal"


class TraceEdgeType(str, Enum):
    """Types of edges in the reasoning trace graph."""
    
    SUPPORTS = "supports"           # A supports conclusion of B
    DERIVED_FROM = "derived_from"   # A is derived from B
    USED_IN = "used_in"             # A was used in computation B
    PRODUCES = "produces"           # Computation A produces output B
    CONSTRAINS = "constrains"       # Policy A constrains evaluation B
    TRIGGERS = "triggers"           # Condition A triggers failure B
    CITES = "cites"                 # A cites/references B
    SELECTS = "selects"             # Policy A selected fact B
    EXCLUDES = "excludes"           # Policy A excluded fact B


class AuditRecordType(str, Enum):
    """Types of audit log records."""
    
    EVALUATION_STARTED = "evaluation_started"
    EVALUATION_COMPLETED = "evaluation_completed"
    EVALUATION_REFUSED = "evaluation_refused"
    TRACE_BUILT = "trace_built"
    MANIFEST_GENERATED = "manifest_generated"
    REPLAY_VERIFIED = "replay_verified"
    REPLAY_MISMATCH = "replay_mismatch"


class ReplayStatus(str, Enum):
    """Status of replay verification."""
    
    SUCCESS = "success"           # All hashes match
    HASH_MISMATCH = "hash_mismatch"  # Computed hash differs
    INPUT_MISSING = "input_missing"  # Cannot retrieve inputs
    ENGINE_MISMATCH = "engine_mismatch"  # Different engine version


# =============================================================================
# Trace Node Schemas
# =============================================================================


class TraceNode(BaseModel):
    """Base class for all trace graph nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    node_id: str = Field(..., description="Unique node identifier")
    node_type: TraceNodeType = Field(..., description="Type of node")
    node_hash: str = Field(..., description="Hash of node content")
    
    # Content (type-specific payload)
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Node-specific data"
    )
    
    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ClaimNode(BaseModel):
    """Payload for CLAIM nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    claim_id: str = Field(...)
    claim_hash: str = Field(...)
    entity_id: str = Field(...)
    entity_id_type: str = Field(...)
    reference_date: date = Field(...)
    horizon_months: int = Field(...)
    currency: str = Field(default="USD")


class PolicyNode(BaseModel):
    """Payload for POLICY nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    min_confidence: Decimal = Field(...)
    max_staleness_days: int = Field(...)
    prefer_higher_confidence: bool = Field(...)
    prefer_newer_date: bool = Field(...)
    policy_hash: str = Field(...)


class EvidenceNode(BaseModel):
    """Payload for EVIDENCE nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    evidence_id: str = Field(...)
    evidence_hash: str = Field(...)
    source_type: str = Field(...)
    published_at: Optional[datetime] = Field(None)
    entity_id: Optional[str] = Field(None)
    object_key: Optional[str] = Field(None)


class FactNode(BaseModel):
    """Payload for FACT nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    fact_id: str = Field(...)
    fact_hash: str = Field(...)
    fact_type: str = Field(...)
    value: Decimal = Field(...)
    currency: Optional[str] = Field(None)
    scale: int = Field(default=0)
    as_of_date: date = Field(...)
    confidence: Decimal = Field(...)
    
    # Provenance linkage
    evidence_id: str = Field(...)
    evidence_hash: str = Field(...)
    location: Optional[dict[str, Any]] = Field(None)


class AssumptionNode(BaseModel):
    """Payload for ASSUMPTION nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    assumption_id: str = Field(...)
    assumption_type: str = Field(...)
    description: str = Field(...)
    value: Any = Field(...)
    source: str = Field(default="engine_default")


class ComputationNode(BaseModel):
    """Payload for COMPUTATION nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    computation_id: str = Field(...)
    computation_type: str = Field(...)  # e.g., "metric_calculation", "monte_carlo"
    inputs_used: list[str] = Field(default_factory=list)  # Node IDs
    engine_version: str = Field(...)
    computation_hash: str = Field(...)


class MetricNode(BaseModel):
    """Payload for METRIC nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    metric_id: str = Field(...)
    metric_name: str = Field(...)
    value: Optional[Decimal] = Field(None)
    threshold: Optional[Decimal] = Field(None)
    is_breach: bool = Field(default=False)


class FailureModeNode(BaseModel):
    """Payload for FAILURE_MODE nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    mode_id: str = Field(...)
    mode_type: str = Field(...)
    trigger_threshold: Decimal = Field(...)
    actual_value: Decimal = Field(...)
    frequency: Decimal = Field(...)
    contribution: Decimal = Field(...)


class MonteCarloRunNode(BaseModel):
    """Payload for MONTE_CARLO_RUN nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    run_id: str = Field(...)
    seed: int = Field(...)
    sample_count: int = Field(...)
    insolvent_count: int = Field(...)
    solvent_count: int = Field(...)
    scenarios_count: int = Field(...)
    run_hash: str = Field(...)


class SensitivityNode(BaseModel):
    """Payload for SENSITIVITY nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    sensitivity_id: str = Field(...)
    driver: str = Field(...)
    fact_type: Optional[str] = Field(None)
    rank: int = Field(...)
    delta_p: Decimal = Field(...)
    normalized_contribution: Decimal = Field(...)


class ConclusionNode(BaseModel):
    """Payload for CONCLUSION nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    conclusion_id: str = Field(...)
    outcome: str = Field(...)  # "solvent", "insolvent", "distressed", "indeterminate"
    p_low: Decimal = Field(...)
    p_mid: Decimal = Field(...)
    p_high: Decimal = Field(...)
    sampling_uncertainty: Decimal = Field(...)
    model_uncertainty: Decimal = Field(...)
    conclusion_hash: str = Field(...)


class RefusalNode(BaseModel):
    """Payload for REFUSAL nodes."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    refusal_id: str = Field(...)
    refusal_code: str = Field(...)
    message: str = Field(...)
    missing_facts: list[dict[str, Any]] = Field(default_factory=list)
    excluded_facts: list[dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# Trace Edge Schema
# =============================================================================


class TraceEdge(BaseModel):
    """An edge in the reasoning trace graph."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    edge_id: str = Field(..., description="Unique edge identifier")
    edge_type: TraceEdgeType = Field(..., description="Type of edge")
    source_node_id: str = Field(..., description="Source node ID")
    target_node_id: str = Field(..., description="Target node ID")
    
    # Edge metadata
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Edge-specific metadata"
    )
    edge_hash: str = Field(..., description="Hash of edge content")


# =============================================================================
# Trace Graph Schema
# =============================================================================


class TraceGraph(BaseModel):
    """
    Complete reasoning trace graph for an evaluation.
    
    This is the full DAG (Directed Acyclic Graph) capturing
    all nodes and edges for a single solvency evaluation.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    trace_id: str = Field(..., description="Unique trace identifier")
    evaluation_id: str = Field(..., description="Associated evaluation ID")
    
    # Graph structure
    nodes: list[TraceNode] = Field(default_factory=list)
    edges: list[TraceEdge] = Field(default_factory=list)
    
    # Graph summary
    node_count: int = Field(default=0)
    edge_count: int = Field(default=0)
    
    # Determinism
    trace_hash: str = Field(..., description="Canonical hash of trace")
    engine_version: str = Field(...)
    trace_service_version: str = Field(default=TRACE_SERVICE_VERSION)
    
    # Root nodes (entry points)
    claim_node_id: str = Field(..., description="Root CLAIM node ID")
    conclusion_node_id: Optional[str] = Field(None, description="CONCLUSION node ID")
    refusal_node_id: Optional[str] = Field(None, description="REFUSAL node ID")
    
    # Timestamps
    built_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# =============================================================================
# Audit Record Schemas
# =============================================================================


class AuditRecord(BaseModel):
    """
    Canonical audit record for an evaluation.
    
    This is an append-only record written for every evaluation,
    enabling tamper-evident verification and full reproducibility.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Identity
    audit_id: str = Field(..., description="Unique audit record ID")
    evaluation_id: str = Field(..., description="Associated evaluation ID")
    
    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    # Engine metadata
    engine_version: str = Field(...)
    trace_service_version: str = Field(default=TRACE_SERVICE_VERSION)
    
    # Input hashes (what was evaluated)
    claim_hash: str = Field(..., description="Hash of the claim")
    evidence_set_hash: str = Field(..., description="Hash of evidence set")
    policy_hash: str = Field(..., description="Hash of fact selection policy")
    
    # Facts snapshot (exact facts used)
    facts_snapshot: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Snapshot of fact_ids + values used"
    )
    facts_snapshot_hash: str = Field(..., description="Hash of facts snapshot")
    
    # Computation trace
    trace_hash: str = Field(..., description="Hash of canonical trace")
    
    # Output hash
    result_hash: str = Field(..., description="Hash of evaluation result")
    
    # Outcome summary
    outcome: str = Field(..., description="Outcome: completed, refused, failed")
    
    # Chain link (for append-only verification)
    previous_audit_hash: Optional[str] = Field(
        None, description="Hash of previous audit record"
    )
    audit_hash: str = Field(..., description="Hash of this audit record")


class AuditManifest(BaseModel):
    """
    Daily signed manifest of audit records.
    
    Contains a list of audit record hashes chained with a rolling hash,
    enabling efficient batch verification and compliance reporting.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    manifest_id: str = Field(..., description="Unique manifest ID")
    manifest_date: date = Field(..., description="Date of manifest")
    
    # Records covered
    record_count: int = Field(default=0)
    first_audit_id: Optional[str] = Field(None)
    last_audit_id: Optional[str] = Field(None)
    
    # Hash chain
    record_hashes: list[str] = Field(
        default_factory=list,
        description="Ordered list of audit record hashes"
    )
    rolling_hash: str = Field(
        ..., description="Rolling hash of all records"
    )
    
    # Previous manifest link
    previous_manifest_hash: Optional[str] = Field(None)
    manifest_hash: str = Field(..., description="Hash of this manifest")
    
    # Metadata
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    object_key: Optional[str] = Field(
        None, description="Object storage key for manifest file"
    )


# =============================================================================
# Replay Verification Schemas
# =============================================================================


class ReplayResult(BaseModel):
    """Result of replay verification."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    evaluation_id: str = Field(...)
    status: ReplayStatus = Field(...)
    
    # Original hashes
    original_trace_hash: str = Field(...)
    original_result_hash: str = Field(...)
    original_facts_hash: str = Field(...)
    
    # Reproduced hashes
    reproduced_trace_hash: Optional[str] = Field(None)
    reproduced_result_hash: Optional[str] = Field(None)
    reproduced_facts_hash: Optional[str] = Field(None)
    
    # Match results
    trace_matches: bool = Field(...)
    result_matches: bool = Field(...)
    facts_match: bool = Field(...)
    
    # Mismatch details (if any)
    mismatch_details: Optional[dict[str, Any]] = Field(None)
    
    # Metadata
    original_engine_version: str = Field(...)
    replay_engine_version: str = Field(...)
    replayed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# =============================================================================
# API Request/Response Schemas
# =============================================================================


class BuildTraceRequest(BaseModel):
    """Request to build a trace for an evaluation."""
    
    model_config = ConfigDict(extra="forbid")
    
    evaluation_id: str = Field(..., description="Evaluation ID to trace")
    force_rebuild: bool = Field(
        default=False,
        description="Rebuild even if trace exists"
    )
    include_evidence_details: bool = Field(
        default=True,
        description="Include evidence source details in trace"
    )


class BuildTraceResponse(BaseModel):
    """Response for trace build request."""
    
    model_config = ConfigDict(frozen=True)
    
    trace: Optional["TraceGraph"] = Field(None, description="Built trace graph")
    trace_id: str = Field(...)
    evaluation_id: str = Field(...)
    trace_hash: str = Field(...)
    node_count: int = Field(...)
    edge_count: int = Field(...)
    built_at: datetime = Field(...)
    message: str = Field(default="Trace built successfully")


class GetTraceResponse(BaseModel):
    """Response for getting a trace."""
    
    model_config = ConfigDict(frozen=True)
    
    trace: TraceGraph = Field(...)


class GetAuditResponse(BaseModel):
    """Response for getting an audit record."""
    
    model_config = ConfigDict(frozen=True)
    
    audit: AuditRecord = Field(...)


class GetManifestResponse(BaseModel):
    """Response for getting an audit manifest."""
    
    model_config = ConfigDict(frozen=True)
    
    manifest: AuditManifest = Field(...)


class ReplayRequest(BaseModel):
    """Request to replay and verify an evaluation."""
    
    model_config = ConfigDict(extra="forbid")
    
    evaluation_id: str = Field(..., description="Evaluation ID to replay")


class ReplayVerificationRequest(BaseModel):
    """Request to verify replay with recomputed hashes."""
    
    model_config = ConfigDict(extra="forbid")
    
    evaluation_id: str = Field(..., description="Evaluation ID to verify")
    recomputed_trace_hash: Optional[str] = Field(
        None, description="Recomputed trace hash from replay"
    )
    recomputed_result_hash: Optional[str] = Field(
        None, description="Recomputed result hash from replay"
    )
    recomputed_facts_hash: Optional[str] = Field(
        None, description="Recomputed facts hash from replay"
    )


class ReplayResponse(BaseModel):
    """Response for replay verification."""
    
    model_config = ConfigDict(frozen=True)
    
    result: ReplayResult = Field(...)
    message: str = Field(...)


class ReplayVerificationResponse(BaseModel):
    """Response for replay verification with hash comparison."""
    
    model_config = ConfigDict(frozen=True)
    
    result: ReplayResult = Field(...)


# =============================================================================
# Canonical Serialization Schema
# =============================================================================


class CanonicalFormat(BaseModel):
    """
    Configuration for canonical serialization.
    
    Ensures deterministic serialization across environments.
    """
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    # Key ordering
    sort_keys: bool = Field(default=True)
    
    # Decimal handling
    decimal_precision: int = Field(default=10)
    decimal_rounding: str = Field(default="ROUND_HALF_UP")
    
    # Float handling (should not use floats, but just in case)
    float_precision: int = Field(default=15)
    
    # Date/time formatting
    datetime_format: str = Field(default="iso8601")
    date_format: str = Field(default="iso8601")
    use_utc: bool = Field(default=True)
    
    # String normalization
    normalize_unicode: bool = Field(default=True)
    
    # Node ordering (for trace graph)
    node_order: str = Field(
        default="topological",  # or "id_sorted"
        description="How to order nodes in serialization"
    )
