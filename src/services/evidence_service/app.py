"""
Evidence Service - FastAPI Application (Production A4)
========================================================

Production-grade API for evidence management with:
- Evidence ingestion with validation and deduplication
- Entity and claim-based evidence lookup
- Policy-based evidence retrieval
- Conflict detection and missing evidence identification
- Health and readiness endpoints
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Request, Query, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shared.config import get_settings
from shared.logging import configure_logging, get_logger
from shared.schemas import HealthCheck, HealthStatus
from shared.errors import RefusalError, ResourceNotFoundError

from .service import EvidenceService
from .schemas import (
    EvidenceDocument,
    EvidenceSet,
    EvidenceStatus,
    EvidenceSourceType,
    IngestEvidenceRequest,
    IngestEvidenceResponse,
    LookupByEntityRequest,
    LookupByEntityResponse,
    ListEvidenceResponse,
    GetEvidenceResponse,
)


logger = get_logger(__name__)

# Global service instance
_evidence_service: Optional[EvidenceService] = None


def get_evidence_service() -> EvidenceService:
    """Get the evidence service instance."""
    global _evidence_service
    if _evidence_service is None:
        _evidence_service = EvidenceService()
    return _evidence_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    global _evidence_service
    settings = get_settings()
    configure_logging(
        service_name="evidence-service",
        log_level=settings.log_level,
        json_output=not settings.debug,
    )
    logger.info("Starting Evidence Service (A4)", version=settings.service_version)
    
    # Initialize service
    _evidence_service = EvidenceService()
    
    yield
    
    logger.info("Shutting down Evidence Service")
    _evidence_service = None


# =============================================================================
# Request/Response Models
# =============================================================================


class ReadinessResponse(BaseModel):
    """Readiness check response."""
    ready: bool = Field(..., description="Whether the service is ready")
    checks: dict[str, bool] = Field(
        default_factory=dict,
        description="Individual component checks"
    )


class EvidenceByClaimRequest(BaseModel):
    """Request to get evidence for a claim."""
    claim_id: str = Field(..., description="Claim ID to look up evidence for")
    include_excluded: bool = Field(
        default=False,
        description="Include excluded evidence in response"
    )


class EvidenceCountResponse(BaseModel):
    """Response for evidence count."""
    total_count: int = Field(..., description="Total evidence count")
    by_source_type: dict[str, int] = Field(
        default_factory=dict,
        description="Count by source type"
    )


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Evidence Service",
        description="Evidence management for the Financial Solvency Truth Engine",
        version=settings.service_version,
        docs_url=settings.docs_url if settings.debug else None,
        lifespan=lifespan,
    )
    
    # =========================================================================
    # Health Endpoints
    # =========================================================================

    @app.get("/health", response_model=HealthCheck, tags=["Health"])
    async def health_check() -> HealthCheck:
        """Check service health."""
        return HealthCheck(
            status=HealthStatus.HEALTHY,
            service="evidence-service",
            version=settings.service_version,
        )
    
    @app.get("/ready", response_model=ReadinessResponse, tags=["Health"])
    async def readiness_check() -> ReadinessResponse:
        """Check service readiness."""
        service = get_evidence_service()
        
        checks = {
            "service_initialized": service is not None,
            "object_store_available": service._object_store is not None,
        }
        
        return ReadinessResponse(
            ready=all(checks.values()),
            checks=checks,
        )
    
    # =========================================================================
    # Evidence Ingestion Endpoints
    # =========================================================================

    @app.post(
        "/v1/evidence/ingest",
        response_model=IngestEvidenceResponse,
        tags=["Evidence Ingestion"],
        summary="Ingest new evidence",
        description="""
        Ingest new evidence into the system.
        
        Supports:
        - SEC filings (10-K, 10-Q, 8-K)
        - Audited financial statements
        - Macroeconomic reference data
        
        Performs validation, deduplication, and stores with full provenance.
        """,
    )
    async def ingest_evidence(
        request: IngestEvidenceRequest,
    ) -> IngestEvidenceResponse:
        """Ingest new evidence."""
        service = get_evidence_service()
        
        try:
            response = await service.ingest(request)
            return response
        except Exception as e:
            logger.error(
                "Evidence ingestion failed",
                error=str(e),
                trace_id=request.trace_id,
            )
            raise HTTPException(status_code=500, detail=str(e))
    
    # =========================================================================
    # Evidence Lookup Endpoints
    # =========================================================================

    @app.get(
        "/v1/evidence/{evidence_id}",
        response_model=GetEvidenceResponse,
        tags=["Evidence Lookup"],
        summary="Get evidence by ID",
    )
    async def get_evidence(
        evidence_id: str = Path(..., description="Evidence ID"),
    ) -> GetEvidenceResponse:
        """Get a single evidence document by ID."""
        service = get_evidence_service()
        
        document = await service.get(evidence_id)
        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Evidence not found: {evidence_id}",
            )
        
        # Get presigned URL for content download
        download_url = None
        if service._object_store:
            download_url = await service._object_store.get_presigned_url(
                document.object_key,
                expires_in=3600,
            )
        
        return GetEvidenceResponse(
            evidence=document,
            download_url=download_url,
        )
    
    @app.get(
        "/v1/evidence/{evidence_id}/content",
        tags=["Evidence Lookup"],
        summary="Get evidence content",
        response_description="Raw document content",
    )
    async def get_evidence_content(
        evidence_id: str = Path(..., description="Evidence ID"),
    ) -> bytes:
        """Get raw content of evidence document."""
        service = get_evidence_service()
        
        content = await service.get_content(evidence_id)
        if content is None:
            raise HTTPException(
                status_code=404,
                detail=f"Evidence content not found: {evidence_id}",
            )
        
        return JSONResponse(
            content={"message": "Use presigned URL for content download"},
            status_code=200,
        )
    
    @app.post(
        "/v1/evidence/by-entity",
        response_model=LookupByEntityResponse,
        tags=["Evidence Lookup"],
        summary="Lookup evidence by entity",
        description="""
        Find evidence documents linked to an entity identifier.
        
        Supports:
        - CIK (SEC Central Index Key)
        - LEI (Legal Entity Identifier)
        - TICKER (with exchange)
        - CUSIP, ISIN
        """,
    )
    async def lookup_by_entity(
        request: LookupByEntityRequest,
    ) -> LookupByEntityResponse:
        """Find evidence by entity identifier."""
        service = get_evidence_service()
        
        return await service.find_by_entity(request)
    
    @app.get(
        "/v1/evidence/by-entity/{id_type}/{id_value}",
        response_model=LookupByEntityResponse,
        tags=["Evidence Lookup"],
        summary="Lookup evidence by entity (GET)",
    )
    async def lookup_by_entity_get(
        id_type: str = Path(..., description="Entity ID type (CIK, LEI, etc.)"),
        id_value: str = Path(..., description="Entity ID value"),
        exchange: Optional[str] = Query(None, description="Exchange (for TICKER)"),
        source_types: Optional[str] = Query(None, description="Comma-separated source types"),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        trace_id: str = Query(..., description="Trace ID"),
    ) -> LookupByEntityResponse:
        """Find evidence by entity identifier (GET method)."""
        service = get_evidence_service()
        
        # Parse source types
        parsed_source_types: Optional[list[EvidenceSourceType]] = None
        if source_types:
            parsed_source_types = [
                EvidenceSourceType(st.strip())
                for st in source_types.split(",")
            ]
        
        request = LookupByEntityRequest(
            entity_id_type=id_type,
            entity_id_value=id_value,
            exchange=exchange,
            source_types=parsed_source_types,
            offset=offset,
            limit=limit,
            trace_id=trace_id,
        )
        
        return await service.find_by_entity(request)
    
    @app.get(
        "/v1/claims/{claim_id}/evidence",
        response_model=ListEvidenceResponse,
        tags=["Evidence Lookup"],
        summary="List evidence for claim",
    )
    async def list_evidence_for_claim(
        claim_id: str = Path(..., description="Claim ID"),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ) -> ListEvidenceResponse:
        """List all evidence linked to a claim."""
        service = get_evidence_service()
        
        documents, total = await service.list_for_claim(
            claim_id=claim_id,
            offset=offset,
            limit=limit,
        )
        
        return ListEvidenceResponse(
            evidence=documents,
            total_count=total,
            offset=offset,
            limit=limit,
            has_more=(offset + len(documents) < total),
        )
    
    @app.post(
        "/v1/claims/{claim_id}/evidence/{evidence_id}/link",
        tags=["Evidence Management"],
        summary="Link evidence to claim",
    )
    async def link_evidence_to_claim(
        claim_id: str = Path(..., description="Claim ID"),
        evidence_id: str = Path(..., description="Evidence ID"),
    ) -> dict[str, Any]:
        """Link an existing evidence document to a claim."""
        service = get_evidence_service()
        
        success = await service.link_evidence_to_claim(claim_id, evidence_id)
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Evidence not found: {evidence_id}",
            )
        
        return {
            "success": True,
            "claim_id": claim_id,
            "evidence_id": evidence_id,
            "message": "Evidence linked to claim",
        }
    
    # =========================================================================
    # Exception Handlers
    # =========================================================================
    
    @app.exception_handler(RefusalError)
    async def refusal_error_handler(
        request: Request, exc: RefusalError
    ) -> JSONResponse:
        """Handle refusal errors."""
        return JSONResponse(
            status_code=400,
            content={
                "error": "refusal",
                "message": exc.reason,
                "operation": exc.operation,
                "details": exc.details,
            },
        )
    
    @app.exception_handler(ResourceNotFoundError)
    async def not_found_handler(
        request: Request, exc: ResourceNotFoundError
    ) -> JSONResponse:
        """Handle not found errors."""
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_found",
                "message": exc.reason,
            },
        )

    return app


app = create_app()
