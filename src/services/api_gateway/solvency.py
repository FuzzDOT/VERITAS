"""
API Gateway Solvency Endpoint - Production-Grade Implementation
================================================================

Implements the single external endpoint for solvency evaluation:
POST /v1/claims/solvency:evaluate

Design Principles:
- Single responsibility: validate, normalize, route to orchestrator
- All validation happens before routing
- Refusals are first-class responses
- Full trace correlation throughout
"""

from datetime import datetime, timezone
from typing import Optional, Any
import uuid

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from shared.canonical_id import generate_canonical_id, EntityType
from shared.errors import (
    RefusalError,
    ValidationRefusalError,
    PreconditionNotMetError,
    ServiceUnavailableError,
    ConflictError,
    RefusalCategory,
)
from shared.logging import get_logger, bind_trace_context
from shared.schemas import SuccessResponse

from services.api_gateway.schemas import (
    SolvencyEvaluationRequest,
    SolvencyEvaluationAccepted,
    RefusalResponse,
    CanonicalSolvencyRequest,
)
from services.api_gateway.validation import (
    SolvencyRequestValidator,
    IdempotencyManager,
    create_validator,
    create_idempotency_manager,
)


logger = get_logger(__name__)


# =============================================================================
# Router Setup
# =============================================================================

solvency_router = APIRouter(prefix="/claims/solvency", tags=["Solvency"])


# =============================================================================
# Dependencies
# =============================================================================


# Singleton instances for the lifetime of the application
_validator: Optional[SolvencyRequestValidator] = None
_idempotency_manager: Optional[IdempotencyManager] = None


def get_validator() -> SolvencyRequestValidator:
    """Get or create the request validator."""
    global _validator
    if _validator is None:
        _validator = create_validator()
    return _validator


def get_idempotency_manager() -> IdempotencyManager:
    """Get or create the idempotency manager."""
    global _idempotency_manager
    if _idempotency_manager is None:
        _idempotency_manager = create_idempotency_manager()
    return _idempotency_manager


def get_trace_id(request: Request) -> str:
    """Extract or generate trace ID from request."""
    return request.headers.get("X-Trace-ID", str(uuid.uuid4()))


# =============================================================================
# Orchestrator Client
# =============================================================================


class OrchestratorClient:
    """
    Client for communicating with the Truth Orchestrator service.
    
    In production, this would use HTTP or gRPC to call the orchestrator.
    For A1, we provide the interface and can inject a mock for testing.
    """
    
    def __init__(self) -> None:
        self._logger = get_logger(__name__)
        # EXTENSION_POINT: Configure orchestrator connection
        self._orchestrator_url = "http://truth-orchestrator:8001"
    
    async def submit_evaluation(
        self,
        canonical_request: CanonicalSolvencyRequest,
    ) -> dict[str, Any]:
        """
        Submit a canonical request to the orchestrator.
        
        Args:
            canonical_request: Validated, normalized request
        
        Returns:
            Orchestrator response with workflow ID
        
        Raises:
            ServiceUnavailableError: If orchestrator is unreachable
        """
        self._logger.info(
            "Submitting to orchestrator",
            claim_id=canonical_request.claim_id,
            trace_id=canonical_request.trace_id,
            request_hash=canonical_request.request_hash,
        )
        
        # EXTENSION_POINT: Implement actual HTTP call to orchestrator
        # For now, we return a mock response that simulates acceptance
        
        # In production:
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(
        #         f"{self._orchestrator_url}/api/v1/process",
        #         json=canonical_request.model_dump(mode="json"),
        #         headers={"X-Trace-ID": canonical_request.trace_id},
        #     )
        #     if response.status_code != 202:
        #         raise ServiceUnavailableError(...)
        
        # Mock response for A1
        return {
            "workflow_id": str(generate_canonical_id(EntityType.WORKFLOW)),
            "status": "accepted",
            "estimated_completion_seconds": self._estimate_completion_time(canonical_request),
        }
    
    def _estimate_completion_time(self, request: CanonicalSolvencyRequest) -> int:
        """Estimate processing time based on request complexity."""
        base_time = 30  # Base 30 seconds
        
        # Add time for scenarios
        scenario_time = len(request.request.stress_scenarios) * 10
        
        # Add time for horizon
        horizon_time = request.request.analysis_horizon.months // 12 * 5
        
        # Add time for sensitivity analysis
        if request.request.output_policy.include_sensitivity_analysis:
            base_time += 60
        
        return base_time + scenario_time + horizon_time


# Singleton orchestrator client
_orchestrator_client: Optional[OrchestratorClient] = None


def get_orchestrator_client() -> OrchestratorClient:
    """Get or create the orchestrator client."""
    global _orchestrator_client
    if _orchestrator_client is None:
        _orchestrator_client = OrchestratorClient()
    return _orchestrator_client


# =============================================================================
# Endpoint Implementation
# =============================================================================


@solvency_router.post(
    ":evaluate",
    response_model=SuccessResponse[SolvencyEvaluationAccepted],
    responses={
        202: {
            "description": "Request accepted for processing",
            "model": SuccessResponse[SolvencyEvaluationAccepted],
        },
        400: {
            "description": "Invalid request format",
            "model": RefusalResponse,
        },
        409: {
            "description": "Duplicate request (idempotent return)",
            "model": SuccessResponse[SolvencyEvaluationAccepted],
        },
        422: {
            "description": "Validation failed",
            "model": RefusalResponse,
        },
        503: {
            "description": "Orchestrator unavailable",
            "model": RefusalResponse,
        },
    },
    status_code=202,
    summary="Evaluate Solvency Claim",
    description="""
    Submit a solvency evaluation request for a financial entity.
    
    This endpoint validates the request exhaustively, normalizes all inputs,
    computes a deterministic request hash for idempotency, and routes the
    request to the Truth Orchestrator for processing.
    
    ## Request Requirements
    
    - **Entity**: Must include a valid identifier (LEI, CUSIP, or internal ID)
    - **Jurisdiction**: Must be a supported ISO 3166-1 alpha-2 code
    - **Regulatory Framework**: Must match the entity classification
    - **Analysis Horizon**: Must be between 1-120 months
    - **Stress Scenarios**: Shock values must be within bounds (-100% to +500%)
    
    ## Idempotency
    
    Duplicate requests (same entity, horizon, scenarios, thresholds) return
    the same claim_id without creating a new evaluation.
    
    ## Response
    
    On success, returns a claim_id for tracking and an estimated completion time.
    The actual evaluation result can be retrieved via the status endpoint.
    """,
)
async def evaluate_solvency(
    request: Request,
    validator: SolvencyRequestValidator = Depends(get_validator),
    idempotency: IdempotencyManager = Depends(get_idempotency_manager),
    orchestrator: OrchestratorClient = Depends(get_orchestrator_client),
) -> JSONResponse:
    """
    Evaluate a solvency claim.
    
    This is the single external endpoint for institutional clients to submit
    solvency evaluation requests.
    """
    trace_id = get_trace_id(request)
    bind_trace_context(trace_id)
    received_at = datetime.now(timezone.utc)
    
    logger.info(
        "Received solvency evaluation request",
        trace_id=trace_id,
        client_ip=request.client.host if request.client else "unknown",
        content_length=request.headers.get("content-length"),
    )
    
    # Step 1: Parse raw request body
    try:
        raw_data = await request.json()
    except Exception as e:
        logger.warning(
            "Failed to parse request body",
            trace_id=trace_id,
            error=str(e),
        )
        return _create_refusal_response(
            reason="Invalid JSON in request body",
            category="validation_failed",
            trace_id=trace_id,
            field_errors=[{
                "field": "body",
                "message": f"JSON parsing error: {str(e)}",
            }],
            status_code=400,
        )
    
    # Step 2: Validate and normalize
    validation_result, canonical_request = validator.validate_and_normalize(
        raw_data=raw_data,
        trace_id=trace_id,
    )
    
    if not validation_result.is_valid:
        logger.warning(
            "Request validation failed",
            trace_id=trace_id,
            error_count=len(validation_result.errors),
            policy_violations=validation_result.policy_violations,
        )
        return _create_refusal_response(
            reason="Request validation failed",
            category="validation_failed",
            trace_id=trace_id,
            field_errors=[
                {
                    "field": e.field,
                    "message": e.message,
                    "value": str(e.value) if e.value is not None else None,
                    "constraint": e.constraint,
                }
                for e in validation_result.errors
            ],
            policy_violations=validation_result.policy_violations,
            status_code=422,
        )
    
    # Type narrowing: canonical_request is guaranteed non-None when validation passes
    assert canonical_request is not None, "canonical_request should not be None when validation passes"
    
    # Step 3: Check idempotency
    existing_claim_id = idempotency.check_duplicate(
        request_hash=canonical_request.request_hash,
        client_request_id=canonical_request.request.client_request_id,
    )
    
    if existing_claim_id:
        logger.info(
            "Returning cached response for duplicate request",
            trace_id=trace_id,
            existing_claim_id=existing_claim_id,
            request_hash=canonical_request.request_hash,
        )
        
        response = SolvencyEvaluationAccepted(
            claim_id=existing_claim_id,
            request_hash=canonical_request.request_hash,
            status="accepted",
            message="Duplicate request - returning existing claim",
            trace_id=trace_id,
            estimated_completion_seconds=None,
        )
        
        return JSONResponse(
            status_code=200,  # 200 for idempotent return, not 202
            content=SuccessResponse(data=response, trace_id=trace_id).model_dump(mode="json"),
            headers={"X-Trace-ID": trace_id, "X-Idempotent": "true"},
        )
    
    # Step 4: Submit to orchestrator
    try:
        orchestrator_response = await orchestrator.submit_evaluation(canonical_request)
    except ServiceUnavailableError as e:
        logger.error(
            "Orchestrator unavailable",
            trace_id=trace_id,
            error=str(e),
        )
        return _create_refusal_response(
            reason="Truth Orchestrator service is temporarily unavailable",
            category="service_unavailable",
            trace_id=trace_id,
            status_code=503,
        )
    except Exception as e:
        logger.exception(
            "Unexpected error submitting to orchestrator",
            trace_id=trace_id,
            error=str(e),
        )
        return _create_refusal_response(
            reason="Internal error processing request",
            category="internal_error",
            trace_id=trace_id,
            status_code=500,
        )
    
    # Step 5: Record for idempotency
    idempotency.record_request(
        request_hash=canonical_request.request_hash,
        claim_id=canonical_request.claim_id,
        client_request_id=canonical_request.request.client_request_id,
    )
    
    # Step 6: Return success response
    response = SolvencyEvaluationAccepted(
        claim_id=canonical_request.claim_id,
        request_hash=canonical_request.request_hash,
        status="accepted",
        message="Solvency evaluation request accepted for processing",
        trace_id=trace_id,
        estimated_completion_seconds=orchestrator_response.get("estimated_completion_seconds"),
    )
    
    logger.info(
        "Solvency evaluation request accepted",
        trace_id=trace_id,
        claim_id=canonical_request.claim_id,
        request_hash=canonical_request.request_hash,
        entity_id=canonical_request.request.entity.external_id,
        jurisdiction=canonical_request.request.jurisdiction,
        estimated_seconds=orchestrator_response.get("estimated_completion_seconds"),
    )
    
    return JSONResponse(
        status_code=202,
        content=SuccessResponse(data=response, trace_id=trace_id).model_dump(mode="json"),
        headers={"X-Trace-ID": trace_id},
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _create_refusal_response(
    reason: str,
    category: str,
    trace_id: str,
    field_errors: Optional[list[dict[str, Any]]] = None,
    policy_violations: Optional[list[str]] = None,
    status_code: int = 422,
) -> JSONResponse:
    """Create a structured refusal response."""
    response = RefusalResponse(
        refused=True,
        reason=reason,
        category=category,
        field_errors=field_errors or [],
        policy_violations=policy_violations or [],
        trace_id=trace_id,
    )
    
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json"),
        headers={"X-Trace-ID": trace_id},
    )


# =============================================================================
# Status Endpoint (for checking evaluation progress)
# =============================================================================


@solvency_router.get(
    "/{claim_id}/status",
    summary="Get Evaluation Status",
    description="Check the status of a solvency evaluation request.",
    responses={
        200: {"description": "Current status of the evaluation"},
        404: {"description": "Claim not found"},
    },
)
async def get_evaluation_status(
    claim_id: str,
    request: Request,
) -> JSONResponse:
    """
    Get the current status of a solvency evaluation.
    
    EXTENSION_POINT: This will query the orchestrator for workflow status.
    """
    trace_id = get_trace_id(request)
    
    logger.info(
        "Status check requested",
        trace_id=trace_id,
        claim_id=claim_id,
    )
    
    # EXTENSION_POINT: Query orchestrator for actual status
    # For now, return a placeholder
    return JSONResponse(
        status_code=200,
        content={
            "claim_id": claim_id,
            "status": "processing",
            "current_step": "evidence_gathering",
            "progress_percent": 25,
            "trace_id": trace_id,
            "message": "Evaluation in progress",
        },
        headers={"X-Trace-ID": trace_id},
    )
