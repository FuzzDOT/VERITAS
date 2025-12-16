"""
Claim Service - FastAPI Application (Production A3)
=====================================================

Production-grade API for claim processing with:
- Semantic validation and refusals
- Entity resolution and normalization
- Required facts contract derivation
- Health and readiness endpoints
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shared.config import get_settings
from shared.logging import configure_logging, get_logger
from shared.schemas import HealthCheck, HealthStatus
from shared.errors import RefusalError, ValidationRefusalError

from .service import ClaimService
from .schemas import (
    ProcessClaimRequest,
    ProcessClaimResponse,
    CanonicalSolvencyClaim,
    RequiredFactsContract,
)


logger = get_logger(__name__)

# Global service instance
_claim_service: Optional[ClaimService] = None


def get_claim_service() -> ClaimService:
    """Get the claim service instance."""
    global _claim_service
    if _claim_service is None:
        _claim_service = ClaimService()
    return _claim_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    global _claim_service
    settings = get_settings()
    configure_logging(
        service_name="claim-service",
        log_level=settings.log_level,
        json_output=not settings.debug,
    )
    logger.info("Starting Claim Service (A3)", version=settings.service_version)
    
    # Initialize service
    _claim_service = ClaimService()
    
    yield
    
    logger.info("Shutting down Claim Service")
    _claim_service = None


# =============================================================================
# Request/Response Models
# =============================================================================


class ProcessClaimAPIRequest(BaseModel):
    """API request for processing a solvency claim."""
    
    api_request: dict[str, Any] = Field(
        ..., description="The validated SolvencyEvaluationRequest from API Gateway"
    )
    request_hash: str = Field(
        ..., description="Hash of the API request for idempotency"
    )
    trace_id: str = Field(
        ..., description="Trace ID for correlation"
    )
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the request was received"
    )


class ClaimStatusResponse(BaseModel):
    """Response for claim status queries."""
    
    claim_id: str
    status: str
    claim_hash: Optional[str] = None
    entity_name: Optional[str] = None
    entity_classification: Optional[str] = None
    jurisdiction: Optional[str] = None
    required_facts_count: Optional[int] = None
    trace_id: Optional[str] = None


class RequiredFactsResponse(BaseModel):
    """Response containing required facts contract."""
    
    contract_id: str
    claim_id: str
    total_facts: int
    required_count: int
    material_count: int
    supplementary_count: int
    categories: list[str]
    contract_hash: str


class ReadinessResponse(BaseModel):
    """Readiness check response."""
    
    ready: bool
    checks: dict[str, bool] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Claim Service",
        description="Production claim processing for the Financial Solvency Truth Engine",
        version=settings.service_version,
        docs_url=settings.docs_url if settings.debug else None,
        lifespan=lifespan,
    )
    
    # =========================================================================
    # Exception Handlers
    # =========================================================================
    
    @app.exception_handler(RefusalError)
    async def refusal_error_handler(request: Request, exc: RefusalError) -> JSONResponse:
        """Handle refusal errors."""
        return JSONResponse(
            status_code=400,
            content={
                "refused": True,
                "category": exc.category.value,
                "reason": exc.reason,
                "operation": exc.operation,
                "details": exc.details,
                "trace_id": exc.context.trace_id,
            },
        )
    
    @app.exception_handler(ValidationRefusalError)
    async def validation_error_handler(request: Request, exc: ValidationRefusalError) -> JSONResponse:
        """Handle validation refusal errors."""
        return JSONResponse(
            status_code=422,
            content={
                "refused": True,
                "category": exc.category.value,
                "reason": exc.reason,
                "details": exc.details,
            },
        )

    # =========================================================================
    # Health Endpoints
    # =========================================================================

    @app.get("/health", response_model=HealthCheck, tags=["Health"])
    async def health_check() -> HealthCheck:
        """Health check endpoint."""
        return HealthCheck(
            status=HealthStatus.HEALTHY,
            service="claim-service",
            version=settings.service_version,
        )
    
    @app.get("/ready", response_model=ReadinessResponse, tags=["Health"])
    async def readiness_check() -> ReadinessResponse:
        """Readiness check endpoint."""
        service = get_claim_service()
        
        checks = {
            "service_initialized": service is not None,
            "processor_ready": service._processor is not None if service else False,
        }
        
        return ReadinessResponse(
            ready=all(checks.values()),
            checks=checks,
        )

    # =========================================================================
    # Claim Processing Endpoints
    # =========================================================================

    @app.post(
        "/v1/claims/process",
        response_model=ProcessClaimResponse,
        tags=["Claims"],
        summary="Process a solvency claim",
        description="Process a solvency evaluation request into a canonical claim with required facts contract",
    )
    async def process_claim(request: ProcessClaimAPIRequest) -> ProcessClaimResponse:
        """
        Process a solvency evaluation request.
        
        This endpoint receives validated requests from the API Gateway and:
        1. Performs semantic validation
        2. Resolves and normalizes entity identifiers
        3. Validates scenarios against entity type
        4. Derives the required facts contract
        5. Creates the canonical claim
        
        Returns either:
        - Success with claim_id, claim_hash, and required_facts_count
        - Refusal with semantic error codes and messages
        """
        service = get_claim_service()
        
        process_request = ProcessClaimRequest(
            api_request=request.api_request,
            request_hash=request.request_hash,
            trace_id=request.trace_id,
            received_at=request.received_at,
        )
        
        response = await service.process_solvency_claim(process_request)
        
        logger.info(
            "Claim processed",
            claim_id=response.claim_id,
            success=response.success,
            trace_id=request.trace_id,
        )
        
        return response

    @app.get(
        "/v1/claims/{claim_id}",
        response_model=ClaimStatusResponse,
        tags=["Claims"],
        summary="Get claim status",
    )
    async def get_claim(claim_id: str) -> ClaimStatusResponse:
        """Get the status of a processed claim."""
        service = get_claim_service()
        
        canonical_claim = await service.get_canonical_claim(claim_id)
        if not canonical_claim:
            raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
        
        contract = await service.get_required_facts_contract(claim_id)
        
        return ClaimStatusResponse(
            claim_id=canonical_claim.claim_id,
            status="processed",
            claim_hash=canonical_claim.claim_hash,
            entity_name=canonical_claim.entity.name,
            entity_classification=canonical_claim.entity_classification,
            jurisdiction=canonical_claim.jurisdiction,
            required_facts_count=contract.total_facts if contract else None,
            trace_id=canonical_claim.trace_id,
        )

    @app.get(
        "/v1/claims/{claim_id}/canonical",
        tags=["Claims"],
        summary="Get canonical claim",
    )
    async def get_canonical_claim(claim_id: str) -> dict[str, Any]:
        """Get the full canonical claim object."""
        service = get_claim_service()
        
        canonical_claim = await service.get_canonical_claim(claim_id)
        if not canonical_claim:
            raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
        
        return canonical_claim.model_dump(mode="json")

    @app.get(
        "/v1/claims/{claim_id}/required-facts",
        response_model=RequiredFactsResponse,
        tags=["Claims"],
        summary="Get required facts contract",
    )
    async def get_required_facts(claim_id: str) -> RequiredFactsResponse:
        """Get the required facts contract for a claim."""
        service = get_claim_service()
        
        contract = await service.get_required_facts_contract(claim_id)
        if not contract:
            raise HTTPException(status_code=404, detail=f"Required facts contract for claim {claim_id} not found")
        
        return RequiredFactsResponse(
            contract_id=contract.contract_id,
            claim_id=contract.claim_id,
            total_facts=contract.total_facts,
            required_count=len(contract.required_facts),
            material_count=len(contract.material_facts),
            supplementary_count=len(contract.supplementary_facts),
            categories=[c.value for c in contract.categories_covered],
            contract_hash=contract.contract_hash,
        )

    @app.get(
        "/v1/claims/{claim_id}/required-facts/full",
        tags=["Claims"],
        summary="Get full required facts contract",
    )
    async def get_required_facts_full(claim_id: str) -> dict[str, Any]:
        """Get the complete required facts contract with all fact details."""
        service = get_claim_service()
        
        contract = await service.get_required_facts_contract(claim_id)
        if not contract:
            raise HTTPException(status_code=404, detail=f"Required facts contract for claim {claim_id} not found")
        
        return contract.model_dump(mode="json")

    return app


app = create_app()
