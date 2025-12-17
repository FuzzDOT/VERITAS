"""
Reasoning Engine
================

Pure, side-effect-free reasoning functions for truth determination.
This engine evaluates claims against evidence to produce truth judgments.

CRITICAL DESIGN PRINCIPLE:
All functions in this module must be PURE - no side effects, no I/O,
no database access, no network calls. Given the same inputs, they
must always produce the same outputs.

A6 Implementation:
- Solvency evaluation with deterministic Monte Carlo
- Fact selection with policy-based filtering
- Scenario shock application
- Sensitivity analysis
- Probability interval computation
"""

# Legacy A0 exports (kept for compatibility)
from services.reasoning_engine.engine import (
    ReasoningEngine,
    ReasoningInput,
    ReasoningOutput,
    ClaimData,
    EvidenceItem,
    EvidenceStrength,
    ReasoningStep,
    reason_about_claim,
)

# A6 Solvency evaluation exports
from services.reasoning_engine.schemas import (
    ENGINE_VERSION,
    EvaluationStatus,
    SolvencyOutcome,
    RefusalCode,
    FailureMode,
    SensitivityDriver,
    Scenario,
    ScenarioShock,
    FactSelectionPolicy,
    SelectedFact,
    MissingFact,
    ComputedMetrics,
    TriggeredFailureMode,
    ProbabilityInterval,
    SensitivityResult,
    SensitivityAnalysis,
    ReasoningRefusal,
    ReasoningArtifact,
    SolvencyEvaluationRequest,
    SolvencyEvaluationResult,
)

from services.reasoning_engine.solvency import (
    FactCandidate,
    ClaimContext,
    EvaluationInput,
    derive_seed,
    compute_evidence_set_hash,
    evaluate_solvency,
    select_facts,
    compute_metrics,
    apply_scenario_shocks,
    run_monte_carlo,
    compute_probability_interval,
    compute_sensitivity,
)

from services.reasoning_engine.app import (
    create_app,
    app,
    get_service,
    reset_service,
    ReasoningService,
)

__all__ = [
    # Legacy A0
    "ReasoningEngine",
    "ReasoningInput",
    "ReasoningOutput",
    "ClaimData",
    "EvidenceItem",
    "EvidenceStrength",
    "ReasoningStep",
    "reason_about_claim",
    # A6 Schemas
    "ENGINE_VERSION",
    "EvaluationStatus",
    "SolvencyOutcome",
    "RefusalCode",
    "FailureMode",
    "SensitivityDriver",
    "Scenario",
    "ScenarioShock",
    "FactSelectionPolicy",
    "SelectedFact",
    "MissingFact",
    "ComputedMetrics",
    "TriggeredFailureMode",
    "ProbabilityInterval",
    "SensitivityResult",
    "SensitivityAnalysis",
    "ReasoningRefusal",
    "ReasoningArtifact",
    "SolvencyEvaluationRequest",
    "SolvencyEvaluationResult",
    # A6 Solvency functions
    "FactCandidate",
    "ClaimContext",
    "EvaluationInput",
    "derive_seed",
    "compute_evidence_set_hash",
    "evaluate_solvency",
    "select_facts",
    "compute_metrics",
    "apply_scenario_shocks",
    "run_monte_carlo",
    "compute_probability_interval",
    "compute_sensitivity",
    # A6 App
    "create_app",
    "app",
    "get_service",
    "reset_service",
    "ReasoningService",
]
