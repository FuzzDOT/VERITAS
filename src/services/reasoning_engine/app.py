"""
Reasoning Engine REST API
==========================

FastAPI application providing REST endpoints for solvency evaluation.

Endpoints:
- POST /v1/reasoning/evaluate - Evaluate solvency for a claim
- GET /v1/reasoning/result/{evaluation_id} - Get evaluation result
- GET /v1/reasoning/metrics/{evaluation_id} - Get metrics and sensitivity

Design:
- Thin API layer wrapping pure computation module
- Service layer handles fact retrieval and persistence
- Engine layer is pure (no I/O)
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shared.canonical_id import EntityType, generate_canonical_id

from .schemas import (
    ENGINE_VERSION,
    DEFAULT_SAMPLE_COUNT,
    DEFAULT_MIN_CONFIDENCE,
    EvaluationStatus,
    SolvencyOutcome,
    RefusalCode,
    Scenario,
    ScenarioShock,
    FactSelectionPolicy,
    SelectedFact,
    ComputedMetrics,
    TriggeredFailureMode,
    SensitivityAnalysis,
    ReasoningRefusal,
    ReasoningArtifact,
    SolvencyEvaluationResult,
    EvaluateRequest,
    EvaluateResponse,
    GetResultResponse,
    GetMetricsResponse,
    MissingFact,
    ProbabilityInterval,
)

from .solvency import (
    FactCandidate,
    ClaimContext,
    EvaluationInput,
    derive_seed,
    compute_evidence_set_hash,
    evaluate_solvency,
)


# =============================================================================
# Application Setup
# =============================================================================


def create_app() -> FastAPI:
    """Create configured FastAPI application."""
    app = FastAPI(
        title="Reasoning Engine",
        description="Deterministic solvency evaluation engine",
        version=ENGINE_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    
    # Register routes
    _register_routes(app)
    
    return app


def _register_routes(app: FastAPI) -> None:
    """Register all API routes."""
    
    @app.get("/health")
    async def health_check() -> dict[str, Any]:
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "reasoning-engine",
            "version": ENGINE_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    @app.post(
        "/v1/reasoning/evaluate",
        response_model=EvaluateResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def evaluate(request: EvaluateRequest) -> EvaluateResponse:
        """
        Evaluate solvency for a claim.
        
        Returns immediately with evaluation_id. Use GET /result/{id}
        to retrieve the full result.
        """
        service = get_service()
        return await service.evaluate(request)
    
    @app.get(
        "/v1/reasoning/result/{evaluation_id}",
        response_model=GetResultResponse,
    )
    async def get_result(evaluation_id: str) -> GetResultResponse:
        """Get evaluation result by ID."""
        service = get_service()
        result = await service.get_result(evaluation_id)
        
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evaluation not found: {evaluation_id}",
            )
        
        return GetResultResponse(result=result)
    
    @app.get(
        "/v1/reasoning/metrics/{evaluation_id}",
        response_model=GetMetricsResponse,
    )
    async def get_metrics(evaluation_id: str) -> GetMetricsResponse:
        """Get evaluation metrics and sensitivity analysis."""
        service = get_service()
        result = await service.get_result(evaluation_id)
        
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evaluation not found: {evaluation_id}",
            )
        
        return GetMetricsResponse(
            evaluation_id=evaluation_id,
            metrics=result.key_metrics,
            sensitivity=result.sensitivity_analysis,
            failure_modes=list(result.triggered_failure_modes),
        )
    
    @app.get("/v1/reasoning/artifact/{artifact_id}")
    async def get_artifact(artifact_id: str) -> dict[str, Any]:
        """Get reasoning artifact for audit."""
        service = get_service()
        artifact = await service.get_artifact(artifact_id)
        
        if artifact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact not found: {artifact_id}",
            )
        
        return artifact.model_dump(mode="json")


# =============================================================================
# Service Layer
# =============================================================================


class ReasoningService:
    """
    Service layer for Reasoning Engine.
    
    Handles:
    - Fact retrieval from A5 Extraction Service
    - Claim context retrieval from A3 Claim Service
    - Result and artifact persistence
    - Coordination with pure computation module
    """
    
    def __init__(self) -> None:
        # In-memory stores for results and artifacts
        self._results: dict[str, SolvencyEvaluationResult] = {}
        self._artifacts: dict[str, ReasoningArtifact] = {}
        
        # Mock fact store (in production, would integrate with A5)
        self._fact_candidates: dict[str, list[FactCandidate]] = {}
        
        # Mock claim store (in production, would integrate with A3)
        self._claims: dict[str, ClaimContext] = {}
    
    async def evaluate(self, request: EvaluateRequest) -> EvaluateResponse:
        """Process evaluation request."""
        trace_id = request.trace_id or f"trace_{uuid.uuid4().hex[:16]}"
        
        # Get or create claim context
        claim_context = await self._get_or_create_claim_context(request)
        
        if claim_context is None:
            # Create refused result
            evaluation_id = str(generate_canonical_id(EntityType.EXTRACTION))
            refusal = ReasoningRefusal(
                code=RefusalCode.CLAIM_NOT_FOUND,
                message="Could not resolve claim or entity",
                missing_facts=[],
                excluded_facts=[],
                remediation="Provide valid claim_id or entity_id",
                trace_id=trace_id,
            )
            
            result = SolvencyEvaluationResult(
                evaluation_id=evaluation_id,
                claim_id=request.claim_id or "",
                status=EvaluationStatus.REFUSED,
                outcome=None,
                solvency_probability=None,
                key_metrics=None,
                triggered_failure_modes=[],
                sensitivity_analysis=None,
                refusal=refusal,
                facts_used_count=0,
                facts_excluded_count=0,
                artifact_id=None,
                seed=None,
                engine_version=ENGINE_VERSION,
                output_hash="refused",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                computation_time_ms=0,
                trace_id=trace_id,
            )
            
            self._results[evaluation_id] = result
            
            return EvaluateResponse(
                evaluation_id=evaluation_id,
                status=EvaluationStatus.REFUSED,
                message="Evaluation refused: could not resolve claim",
            )
        
        # Get fact candidates
        fact_candidates = await self._get_fact_candidates(
            claim_context.entity_id,
            claim_context.entity_id_type,
        )
        
        # Build evaluation input
        policy = FactSelectionPolicy(
            min_confidence=request.min_confidence or DEFAULT_MIN_CONFIDENCE,
        )
        
        # Derive seed if not provided
        evidence_hash = compute_evidence_set_hash(fact_candidates)
        seed = request.seed
        if seed is None:
            seed = derive_seed(claim_context.claim_hash, evidence_hash)
        
        eval_input = EvaluationInput(
            claim_context=claim_context,
            fact_candidates=tuple(fact_candidates),
            scenarios=tuple(request.scenarios),
            policy=policy,
            sample_count=request.sample_count,
            seed=seed,
            trace_id=trace_id,
        )
        
        # Run evaluation (pure computation)
        result, artifact = evaluate_solvency(eval_input)
        
        # Store results
        self._results[result.evaluation_id] = result
        if artifact.artifact_id:
            self._artifacts[artifact.artifact_id] = artifact
        
        return EvaluateResponse(
            evaluation_id=result.evaluation_id,
            status=result.status,
            message=f"Evaluation {result.status.value}",
        )
    
    async def get_result(
        self, evaluation_id: str
    ) -> Optional[SolvencyEvaluationResult]:
        """Get evaluation result by ID."""
        return self._results.get(evaluation_id)
    
    async def get_artifact(
        self, artifact_id: str
    ) -> Optional[ReasoningArtifact]:
        """Get reasoning artifact by ID."""
        return self._artifacts.get(artifact_id)
    
    async def _get_or_create_claim_context(
        self, request: EvaluateRequest
    ) -> Optional[ClaimContext]:
        """Get or create claim context from request."""
        # If claim_id provided, look it up
        if request.claim_id and request.claim_id in self._claims:
            return self._claims[request.claim_id]
        
        # If entity provided, create context
        if request.entity_id and request.entity_id_type:
            claim_id = f"claim_{request.entity_id}"
            claim_hash = f"hash_{request.entity_id}"
            
            context = ClaimContext(
                claim_id=claim_id,
                claim_hash=claim_hash,
                entity_id=request.entity_id,
                entity_id_type=request.entity_id_type,
                entity_classification="corporate",  # Default
                reference_date=request.reference_date or date.today(),
                horizon_months=request.horizon_months,
                currency="USD",
            )
            
            self._claims[claim_id] = context
            return context
        
        return None
    
    async def _get_fact_candidates(
        self,
        entity_id: str,
        entity_id_type: str,
    ) -> list[FactCandidate]:
        """Get fact candidates for entity."""
        key = f"{entity_id_type}:{entity_id}"
        return self._fact_candidates.get(key, [])
    
    # =========================================================================
    # Methods for testing/integration
    # =========================================================================
    
    def register_claim(self, claim_id: str, context: ClaimContext) -> None:
        """Register a claim context (for testing)."""
        self._claims[claim_id] = context
    
    def register_facts(
        self,
        entity_id: str,
        entity_id_type: str,
        facts: list[FactCandidate],
    ) -> None:
        """Register fact candidates (for testing/integration with A5)."""
        key = f"{entity_id_type}:{entity_id}"
        self._fact_candidates[key] = facts
    
    def clear(self) -> None:
        """Clear all stored data (for testing)."""
        self._results.clear()
        self._artifacts.clear()
        self._fact_candidates.clear()
        self._claims.clear()


# =============================================================================
# Global Service Instance
# =============================================================================


_service: Optional[ReasoningService] = None


def get_service() -> ReasoningService:
    """Get the global reasoning service instance."""
    global _service
    if _service is None:
        _service = ReasoningService()
    return _service


def reset_service() -> None:
    """Reset the service (for testing)."""
    global _service
    if _service is not None:
        _service.clear()
    _service = None


# =============================================================================
# App Instance
# =============================================================================


app = create_app()
