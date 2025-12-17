"""
Trace Graph Builder
===================

Builds a typed directed graph (DAG) from A6 evaluation outputs,
linking back to A5/A4 provenance.

The trace graph captures:
1. The claim being evaluated (root CLAIM node)
2. Policy constraints (POLICY node)
3. Evidence sources (EVIDENCE nodes)
4. Facts used and their provenance (FACT nodes)
5. Assumptions made (ASSUMPTION nodes)
6. Intermediate computations (COMPUTATION nodes)
7. Computed metrics (METRIC nodes)
8. Triggered failure modes (FAILURE_MODE nodes)
9. Monte Carlo simulation (MONTE_CARLO_RUN node)
10. Sensitivity analysis (SENSITIVITY nodes)
11. Final conclusion or refusal (CONCLUSION/REFUSAL node)

All nodes and edges are linked to form an auditable reasoning chain.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from shared.canonical_id import EntityType, generate_canonical_id

from .canonical import (
    canonical_hash,
    canonical_policy_hash,
    canonical_trace_hash,
    canonical_evidence_set_hash,
)
from .schemas import (
    TRACE_SERVICE_VERSION,
    TraceNodeType,
    TraceEdgeType,
    TraceNode,
    TraceEdge,
    TraceGraph,
    ClaimNode,
    PolicyNode,
    EvidenceNode,
    FactNode,
    AssumptionNode,
    ComputationNode,
    MetricNode,
    FailureModeNode,
    MonteCarloRunNode,
    SensitivityNode,
    ConclusionNode,
    RefusalNode,
)

from services.reasoning_engine.schemas import (
    ENGINE_VERSION,
    SolvencyEvaluationResult,
    ReasoningArtifact,
    SelectedFact,
    ComputedMetrics,
    TriggeredFailureMode,
    SensitivityAnalysis,
    SensitivityResult,
    ReasoningRefusal,
    ProbabilityInterval,
    FactSelectionPolicy,
    EvaluationStatus,
)


# =============================================================================
# Constants
# =============================================================================

# Default thresholds for assumption nodes
DEFAULT_THRESHOLDS: dict[str, Decimal] = {
    "liquidity_threshold": Decimal("1.0"),
    "interest_coverage_threshold": Decimal("1.5"),
    "debt_service_threshold": Decimal("1.2"),
    "cash_runway_months_threshold": Decimal("6"),
}


# =============================================================================
# Builder Context
# =============================================================================


@dataclass
class TraceBuilderContext:
    """
    Context for building a trace graph.
    
    Accumulates nodes and edges during build process.
    """
    evaluation_id: str
    engine_version: str = ENGINE_VERSION
    trace_service_version: str = TRACE_SERVICE_VERSION
    
    # Accumulated nodes and edges
    nodes: list[TraceNode] = field(default_factory=list)
    edges: list[TraceEdge] = field(default_factory=list)
    
    # Node ID maps for linking
    node_id_map: dict[str, str] = field(default_factory=dict)
    
    # Root node references
    claim_node_id: Optional[str] = None
    conclusion_node_id: Optional[str] = None
    refusal_node_id: Optional[str] = None
    
    def add_node(
        self,
        node_type: TraceNodeType,
        payload: dict[str, Any],
        key: Optional[str] = None,
    ) -> str:
        """Add a node and return its ID."""
        node_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
        node_hash = canonical_hash(payload)
        
        node = TraceNode(
            node_id=node_id,
            node_type=node_type,
            node_hash=node_hash,
            payload=payload,
        )
        
        self.nodes.append(node)
        
        if key:
            self.node_id_map[key] = node_id
        
        return node_id
    
    def add_edge(
        self,
        edge_type: TraceEdgeType,
        source_id: str,
        target_id: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Add an edge and return its ID."""
        edge_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
        
        edge_data = {
            "edge_type": edge_type.value,
            "source_node_id": source_id,
            "target_node_id": target_id,
            "metadata": metadata or {},
        }
        edge_hash = canonical_hash(edge_data)
        
        edge = TraceEdge(
            edge_id=edge_id,
            edge_type=edge_type,
            source_node_id=source_id,
            target_node_id=target_id,
            metadata=metadata or {},
            edge_hash=edge_hash,
        )
        
        self.edges.append(edge)
        return edge_id
    
    def get_node_id(self, key: str) -> Optional[str]:
        """Get node ID by key."""
        return self.node_id_map.get(key)


# =============================================================================
# Node Builders
# =============================================================================


def build_claim_node(
    ctx: TraceBuilderContext,
    claim_id: str,
    claim_hash: str,
    entity_id: str,
    entity_id_type: str,
    reference_date: date,
    horizon_months: int,
    currency: str = "USD",
) -> str:
    """Build and add CLAIM node."""
    payload = ClaimNode(
        claim_id=claim_id,
        claim_hash=claim_hash,
        entity_id=entity_id,
        entity_id_type=entity_id_type,
        reference_date=reference_date,
        horizon_months=horizon_months,
        currency=currency,
    ).model_dump()
    
    node_id = ctx.add_node(TraceNodeType.CLAIM, payload, key=f"claim:{claim_id}")
    ctx.claim_node_id = node_id
    return node_id


def build_policy_node(
    ctx: TraceBuilderContext,
    policy: FactSelectionPolicy,
) -> str:
    """Build and add POLICY node."""
    policy_hash = canonical_policy_hash(
        policy.min_confidence,
        policy.max_staleness_days,
        policy.prefer_higher_confidence,
        policy.prefer_newer_date,
    )
    
    payload = PolicyNode(
        min_confidence=policy.min_confidence,
        max_staleness_days=policy.max_staleness_days,
        prefer_higher_confidence=policy.prefer_higher_confidence,
        prefer_newer_date=policy.prefer_newer_date,
        policy_hash=policy_hash,
    ).model_dump()
    
    return ctx.add_node(TraceNodeType.POLICY, payload, key="policy")


def build_evidence_node(
    ctx: TraceBuilderContext,
    evidence_id: str,
    evidence_hash: str,
    source_type: str,
    published_at: Optional[datetime] = None,
    entity_id: Optional[str] = None,
    object_key: Optional[str] = None,
) -> str:
    """Build and add EVIDENCE node."""
    payload = EvidenceNode(
        evidence_id=evidence_id,
        evidence_hash=evidence_hash,
        source_type=source_type,
        published_at=published_at,
        entity_id=entity_id,
        object_key=object_key,
    ).model_dump()
    
    return ctx.add_node(
        TraceNodeType.EVIDENCE,
        payload,
        key=f"evidence:{evidence_id}"
    )


def build_fact_node(
    ctx: TraceBuilderContext,
    fact: SelectedFact,
    evidence_hash: str,
    location: Optional[dict[str, Any]] = None,
) -> str:
    """Build and add FACT node."""
    payload = FactNode(
        fact_id=fact.fact_id,
        fact_hash=canonical_hash({
            "fact_id": fact.fact_id,
            "fact_type": fact.fact_type,
            "value": fact.value,
        }),
        fact_type=fact.fact_type,
        value=fact.value,
        currency=fact.currency,
        scale=fact.scale,
        as_of_date=fact.as_of_date,
        confidence=fact.confidence,
        evidence_id=fact.evidence_id,
        evidence_hash=evidence_hash,
        location=location,
    ).model_dump()
    
    return ctx.add_node(
        TraceNodeType.FACT,
        payload,
        key=f"fact:{fact.fact_id}"
    )


def build_assumption_node(
    ctx: TraceBuilderContext,
    assumption_type: str,
    description: str,
    value: Any,
    source: str = "engine_default",
) -> str:
    """Build and add ASSUMPTION node."""
    assumption_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
    
    payload = AssumptionNode(
        assumption_id=assumption_id,
        assumption_type=assumption_type,
        description=description,
        value=value,
        source=source,
    ).model_dump()
    
    return ctx.add_node(
        TraceNodeType.ASSUMPTION,
        payload,
        key=f"assumption:{assumption_type}"
    )


def build_computation_node(
    ctx: TraceBuilderContext,
    computation_type: str,
    inputs_used: list[str],
) -> str:
    """Build and add COMPUTATION node."""
    computation_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
    
    payload = ComputationNode(
        computation_id=computation_id,
        computation_type=computation_type,
        inputs_used=inputs_used,
        engine_version=ctx.engine_version,
        computation_hash=canonical_hash({
            "type": computation_type,
            "inputs": sorted(inputs_used),
        }),
    ).model_dump()
    
    return ctx.add_node(
        TraceNodeType.COMPUTATION,
        payload,
        key=f"computation:{computation_type}"
    )


def build_metric_node(
    ctx: TraceBuilderContext,
    metric_name: str,
    value: Optional[Decimal],
    threshold: Optional[Decimal] = None,
) -> str:
    """Build and add METRIC node."""
    metric_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
    is_breach = False
    if value is not None and threshold is not None:
        is_breach = value < threshold
    
    payload = MetricNode(
        metric_id=metric_id,
        metric_name=metric_name,
        value=value,
        threshold=threshold,
        is_breach=is_breach,
    ).model_dump()
    
    return ctx.add_node(
        TraceNodeType.METRIC,
        payload,
        key=f"metric:{metric_name}"
    )


def build_failure_mode_node(
    ctx: TraceBuilderContext,
    failure: TriggeredFailureMode,
) -> str:
    """Build and add FAILURE_MODE node."""
    mode_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
    
    payload = FailureModeNode(
        mode_id=mode_id,
        mode_type=failure.mode.value,
        trigger_threshold=failure.trigger_threshold,
        actual_value=failure.actual_value,
        frequency=failure.frequency,
        contribution=failure.contribution_to_insolvency,
    ).model_dump()
    
    return ctx.add_node(
        TraceNodeType.FAILURE_MODE,
        payload,
        key=f"failure:{failure.mode.value}"
    )


def build_monte_carlo_node(
    ctx: TraceBuilderContext,
    seed: int,
    sample_count: int,
    insolvent_count: int,
    solvent_count: int,
    scenarios_count: int,
) -> str:
    """Build and add MONTE_CARLO_RUN node."""
    run_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
    
    run_hash = canonical_hash({
        "seed": seed,
        "sample_count": sample_count,
        "insolvent_count": insolvent_count,
        "solvent_count": solvent_count,
    })
    
    payload = MonteCarloRunNode(
        run_id=run_id,
        seed=seed,
        sample_count=sample_count,
        insolvent_count=insolvent_count,
        solvent_count=solvent_count,
        scenarios_count=scenarios_count,
        run_hash=run_hash,
    ).model_dump()
    
    return ctx.add_node(
        TraceNodeType.MONTE_CARLO_RUN,
        payload,
        key="monte_carlo"
    )


def build_sensitivity_node(
    ctx: TraceBuilderContext,
    sensitivity: SensitivityResult,
) -> str:
    """Build and add SENSITIVITY node."""
    sensitivity_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
    
    payload = SensitivityNode(
        sensitivity_id=sensitivity_id,
        driver=sensitivity.driver.value,
        fact_type=sensitivity.fact_type,
        rank=sensitivity.rank,
        delta_p=sensitivity.delta_p,
        normalized_contribution=sensitivity.normalized_contribution,
    ).model_dump()
    
    return ctx.add_node(
        TraceNodeType.SENSITIVITY,
        payload,
        key=f"sensitivity:{sensitivity.driver.value}"
    )


def build_conclusion_node(
    ctx: TraceBuilderContext,
    outcome: str,
    probability: ProbabilityInterval,
) -> str:
    """Build and add CONCLUSION node."""
    conclusion_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
    
    conclusion_hash = canonical_hash({
        "outcome": outcome,
        "p_low": probability.p_low,
        "p_mid": probability.p_mid,
        "p_high": probability.p_high,
    })
    
    payload = ConclusionNode(
        conclusion_id=conclusion_id,
        outcome=outcome,
        p_low=probability.p_low,
        p_mid=probability.p_mid,
        p_high=probability.p_high,
        sampling_uncertainty=probability.sampling_uncertainty,
        model_uncertainty=probability.model_uncertainty,
        conclusion_hash=conclusion_hash,
    ).model_dump()
    
    node_id = ctx.add_node(
        TraceNodeType.CONCLUSION,
        payload,
        key="conclusion"
    )
    ctx.conclusion_node_id = node_id
    return node_id


def build_refusal_node(
    ctx: TraceBuilderContext,
    refusal: ReasoningRefusal,
) -> str:
    """Build and add REFUSAL node."""
    refusal_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
    
    payload = RefusalNode(
        refusal_id=refusal_id,
        refusal_code=refusal.code.value,
        message=refusal.message,
        missing_facts=[f.model_dump() for f in refusal.missing_facts],
        excluded_facts=refusal.excluded_facts,
    ).model_dump()
    
    node_id = ctx.add_node(
        TraceNodeType.REFUSAL,
        payload,
        key="refusal"
    )
    ctx.refusal_node_id = node_id
    return node_id


# =============================================================================
# Trace Graph Builder
# =============================================================================


@dataclass
class EvidenceInfo:
    """Evidence information for linking facts."""
    evidence_id: str
    evidence_hash: str
    source_type: str
    published_at: Optional[datetime] = None


def build_trace_graph(
    evaluation_id: str,
    result: SolvencyEvaluationResult,
    artifact: ReasoningArtifact,
    policy: FactSelectionPolicy,
    claim_id: str,
    claim_hash: str,
    entity_id: str,
    entity_id_type: str,
    reference_date: date,
    horizon_months: int,
    evidence_info: dict[str, EvidenceInfo],  # evidence_id -> info
    currency: str = "USD",
) -> TraceGraph:
    """
    Build complete trace graph from evaluation outputs.
    
    Args:
        evaluation_id: The evaluation being traced
        result: The SolvencyEvaluationResult from A6
        artifact: The ReasoningArtifact with intermediate results
        policy: The FactSelectionPolicy used
        claim_id: The claim ID
        claim_hash: Hash of the claim
        entity_id: Entity being evaluated
        entity_id_type: Type of entity ID
        reference_date: Evaluation reference date
        horizon_months: Evaluation horizon
        evidence_info: Mapping of evidence IDs to metadata
        currency: Currency of evaluation
        
    Returns:
        Complete TraceGraph with all nodes and edges
    """
    ctx = TraceBuilderContext(
        evaluation_id=evaluation_id,
        engine_version=artifact.engine_version,
    )
    
    # 1. Build CLAIM node (root)
    claim_node_id = build_claim_node(
        ctx, claim_id, claim_hash, entity_id, entity_id_type,
        reference_date, horizon_months, currency
    )
    
    # 2. Build POLICY node and link to claim
    policy_node_id = build_policy_node(ctx, policy)
    ctx.add_edge(
        TraceEdgeType.CONSTRAINS,
        policy_node_id,
        claim_node_id,
    )
    
    # 3. Build EVIDENCE nodes
    evidence_node_ids: dict[str, str] = {}
    for ev_id, ev_info in evidence_info.items():
        ev_node_id = build_evidence_node(
            ctx,
            evidence_id=ev_info.evidence_id,
            evidence_hash=ev_info.evidence_hash,
            source_type=ev_info.source_type,
            published_at=ev_info.published_at,
            entity_id=entity_id,
        )
        evidence_node_ids[ev_id] = ev_node_id
    
    # 4. Build FACT nodes from selected facts
    fact_node_ids: list[str] = []
    for selected_fact in artifact.selected_facts:
        # Get evidence info
        ev_info = evidence_info.get(selected_fact.evidence_id)
        ev_hash = ev_info.evidence_hash if ev_info else ""
        
        fact_node_id = build_fact_node(
            ctx,
            selected_fact,
            evidence_hash=ev_hash,
        )
        fact_node_ids.append(fact_node_id)
        
        # Link fact to evidence (DERIVED_FROM)
        if selected_fact.evidence_id in evidence_node_ids:
            ctx.add_edge(
                TraceEdgeType.DERIVED_FROM,
                fact_node_id,
                evidence_node_ids[selected_fact.evidence_id],
            )
        
        # Link policy to fact (SELECTS)
        ctx.add_edge(
            TraceEdgeType.SELECTS,
            policy_node_id,
            fact_node_id,
        )
    
    # 5. Build ASSUMPTION nodes for thresholds
    assumption_node_ids: list[str] = []
    for threshold_name, threshold_value in DEFAULT_THRESHOLDS.items():
        assumption_id = build_assumption_node(
            ctx,
            assumption_type=threshold_name,
            description=f"Default {threshold_name.replace('_', ' ')}",
            value=threshold_value,
        )
        assumption_node_ids.append(assumption_id)
    
    # 6. Build COMPUTATION node for metric calculation
    metric_computation_id = build_computation_node(
        ctx,
        computation_type="metric_calculation",
        inputs_used=fact_node_ids,
    )
    
    # Link facts to computation (USED_IN)
    for fact_id in fact_node_ids:
        ctx.add_edge(
            TraceEdgeType.USED_IN,
            fact_id,
            metric_computation_id,
        )
    
    # 7. Build METRIC nodes
    metric_node_ids: list[str] = []
    if artifact.baseline_metrics:
        metrics = artifact.baseline_metrics
        
        metric_configs = [
            ("current_ratio", metrics.current_ratio, Decimal("1.0")),
            ("quick_ratio", metrics.quick_ratio, None),
            ("cash_ratio", metrics.cash_ratio, None),
            ("debt_to_equity", metrics.debt_to_equity, None),
            ("interest_coverage", metrics.interest_coverage, Decimal("1.5")),
            ("debt_service_coverage", metrics.debt_service_coverage, Decimal("1.2")),
            ("cash_burn_months", metrics.cash_burn_months, Decimal("6")),
        ]
        
        for name, value, threshold in metric_configs:
            if value is not None:
                metric_id = build_metric_node(ctx, name, value, threshold)
                metric_node_ids.append(metric_id)
                
                # Link computation to metric (PRODUCES)
                ctx.add_edge(
                    TraceEdgeType.PRODUCES,
                    metric_computation_id,
                    metric_id,
                )
    
    # 8. Build MONTE_CARLO_RUN node
    monte_carlo_node_id: Optional[str] = None
    if artifact.sample_count and artifact.seed:
        # Estimate insolvent count from probability
        total = artifact.sample_count
        if result.solvency_probability:
            insolvent_count = int(
                total * (1 - float(result.solvency_probability.p_mid))
            )
            solvent_count = total - insolvent_count
        else:
            insolvent_count = 0
            solvent_count = total
        
        monte_carlo_node_id = build_monte_carlo_node(
            ctx,
            seed=artifact.seed,
            sample_count=artifact.sample_count,
            insolvent_count=insolvent_count,
            solvent_count=solvent_count,
            scenarios_count=len(artifact.stressed_metrics),
        )
        
        # Link metrics to monte carlo (USED_IN)
        for metric_id in metric_node_ids:
            ctx.add_edge(
                TraceEdgeType.USED_IN,
                metric_id,
                monte_carlo_node_id,
            )
        
        # Link assumptions to monte carlo (CONSTRAINS)
        for assumption_id in assumption_node_ids:
            ctx.add_edge(
                TraceEdgeType.CONSTRAINS,
                assumption_id,
                monte_carlo_node_id,
            )
    
    # 9. Build FAILURE_MODE nodes
    failure_node_ids: list[str] = []
    for failure in artifact.triggered_failure_modes:
        failure_id = build_failure_mode_node(ctx, failure)
        failure_node_ids.append(failure_id)
        
        # Link monte carlo to failure (TRIGGERS)
        if monte_carlo_node_id:
            ctx.add_edge(
                TraceEdgeType.TRIGGERS,
                monte_carlo_node_id,
                failure_id,
            )
    
    # 10. Build SENSITIVITY nodes
    sensitivity_node_ids: list[str] = []
    if artifact.sensitivity_analysis:
        for driver_result in artifact.sensitivity_analysis.drivers:
            sensitivity_id = build_sensitivity_node(ctx, driver_result)
            sensitivity_node_ids.append(sensitivity_id)
            
            # Link monte carlo to sensitivity (PRODUCES)
            if monte_carlo_node_id:
                ctx.add_edge(
                    TraceEdgeType.PRODUCES,
                    monte_carlo_node_id,
                    sensitivity_id,
                )
    
    # 11. Build CONCLUSION or REFUSAL node
    if result.status == EvaluationStatus.COMPLETED and result.outcome:
        if result.solvency_probability:
            conclusion_id = build_conclusion_node(
                ctx,
                outcome=result.outcome.value,
                probability=result.solvency_probability,
            )
            
            # Link monte carlo to conclusion (PRODUCES)
            if monte_carlo_node_id:
                ctx.add_edge(
                    TraceEdgeType.PRODUCES,
                    monte_carlo_node_id,
                    conclusion_id,
                )
            
            # Link failures to conclusion (SUPPORTS)
            for failure_id in failure_node_ids:
                ctx.add_edge(
                    TraceEdgeType.SUPPORTS,
                    failure_id,
                    conclusion_id,
                )
            
            # Link conclusion to claim (SUPPORTS)
            ctx.add_edge(
                TraceEdgeType.SUPPORTS,
                conclusion_id,
                claim_node_id,
            )
    
    elif result.status == EvaluationStatus.REFUSED and result.refusal:
        refusal_id = build_refusal_node(ctx, result.refusal)
        
        # Link policy to refusal (explains why facts were missing/excluded)
        ctx.add_edge(
            TraceEdgeType.CONSTRAINS,
            policy_node_id,
            refusal_id,
        )
        
        # Link refusal to claim
        ctx.add_edge(
            TraceEdgeType.SUPPORTS,
            refusal_id,
            claim_node_id,
        )
    
    # 12. Compute trace hash
    nodes_dict = [n.model_dump() for n in ctx.nodes]
    edges_dict = [e.model_dump() for e in ctx.edges]
    trace_hash = canonical_trace_hash(nodes_dict, edges_dict)
    
    # 13. Generate trace ID
    trace_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
    
    # 14. Build final TraceGraph
    return TraceGraph(
        trace_id=trace_id,
        evaluation_id=evaluation_id,
        nodes=ctx.nodes,
        edges=ctx.edges,
        node_count=len(ctx.nodes),
        edge_count=len(ctx.edges),
        trace_hash=trace_hash,
        engine_version=ctx.engine_version,
        trace_service_version=ctx.trace_service_version,
        claim_node_id=ctx.claim_node_id or "",
        conclusion_node_id=ctx.conclusion_node_id,
        refusal_node_id=ctx.refusal_node_id,
    )


def build_refusal_trace_graph(
    evaluation_id: str,
    refusal: ReasoningRefusal,
    claim_id: str,
    claim_hash: str,
    entity_id: str,
    entity_id_type: str,
    reference_date: date,
    policy: FactSelectionPolicy,
) -> TraceGraph:
    """
    Build trace graph for a refused evaluation.
    
    Even refusals get a trace explaining why evaluation was refused.
    """
    ctx = TraceBuilderContext(
        evaluation_id=evaluation_id,
    )
    
    # Build CLAIM node
    claim_node_id = build_claim_node(
        ctx, claim_id, claim_hash, entity_id, entity_id_type,
        reference_date, 12, "USD"
    )
    
    # Build POLICY node
    policy_node_id = build_policy_node(ctx, policy)
    ctx.add_edge(TraceEdgeType.CONSTRAINS, policy_node_id, claim_node_id)
    
    # Build REFUSAL node
    refusal_node_id = build_refusal_node(ctx, refusal)
    ctx.add_edge(TraceEdgeType.CONSTRAINS, policy_node_id, refusal_node_id)
    ctx.add_edge(TraceEdgeType.SUPPORTS, refusal_node_id, claim_node_id)
    
    # Compute trace hash
    nodes_dict = [n.model_dump() for n in ctx.nodes]
    edges_dict = [e.model_dump() for e in ctx.edges]
    trace_hash = canonical_trace_hash(nodes_dict, edges_dict)
    
    trace_id = str(generate_canonical_id(EntityType.REASONING_TRACE))
    
    return TraceGraph(
        trace_id=trace_id,
        evaluation_id=evaluation_id,
        nodes=ctx.nodes,
        edges=ctx.edges,
        node_count=len(ctx.nodes),
        edge_count=len(ctx.edges),
        trace_hash=trace_hash,
        engine_version=ENGINE_VERSION,
        trace_service_version=TRACE_SERVICE_VERSION,
        claim_node_id=claim_node_id,
        conclusion_node_id=None,
        refusal_node_id=refusal_node_id,
    )
