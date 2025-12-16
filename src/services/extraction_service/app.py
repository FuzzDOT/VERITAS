"""
Extraction Service API Application
===================================

RESTful API for the Extraction Service:
- POST /v1/extract/run         - Trigger extraction job
- GET  /v1/extract/status/{id} - Get job status
- GET  /v1/facts/by-entity     - Get facts by entity
- GET  /v1/facts/by-claim      - Get facts by claim
- GET  /v1/facts/{fact_id}     - Get single fact
- GET  /v1/passages/{id}       - Get passage by ID
- GET  /health                 - Health check
"""

import base64
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from shared.config import get_settings
from shared.logging import configure_logging, get_logger
from shared.schemas import HealthCheck, HealthStatus

from .service_impl import ExtractionService
from .schemas import (
    ExtractionMethod,
    ExtractionJobStatus,
    ExtractionRefusalCode,
    FactConfidence,
    FinancialFact,
    EvidencePassage,
    ExtractionJob,
    ExtractionJobRequest,
    DEFAULT_MIN_CONFIDENCE,
)


# =============================================================================
# Logger
# =============================================================================

logger = get_logger(__name__)


# =============================================================================
# API Request/Response Models
# =============================================================================


class RunExtractionRequest(BaseModel):
    """Request to run extraction on evidence."""
    
    model_config = ConfigDict(extra="forbid")
    
    evidence_ids: list[str] = Field(..., min_length=1, max_length=100)
    claim_id: Optional[str] = None
    trace_id: Optional[str] = None
    min_confidence: Decimal = Field(default=DEFAULT_MIN_CONFIDENCE, ge=0, le=1)
    allow_low_confidence: bool = False
    force_reextract: bool = False


class RunExtractionResponse(BaseModel):
    """Response from running extraction."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    job_id: str
    status: ExtractionJobStatus
    evidence_count: int
    message: str


class JobStatusResponse(BaseModel):
    """Job status response."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    job_id: str
    status: ExtractionJobStatus
    evidence_count: int
    completed_count: int
    failed_count: int
    total_facts: int
    total_passages: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    results: list[dict[str, Any]]


class FactResponse(BaseModel):
    """Single fact response."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    fact_id: str
    fact_hash: str
    fact_type: str
    category: str
    value: Decimal
    unit: str
    currency: Optional[str]
    scale: int
    as_of_date: str
    period_start: Optional[str]
    period_end: Optional[str]
    fiscal_year: Optional[int]
    fiscal_quarter: Optional[int]
    confidence: Decimal
    confidence_level: FactConfidence
    extraction_method: ExtractionMethod
    entity_id: Optional[str]
    entity_id_type: Optional[str]
    evidence_id: str


class FactListResponse(BaseModel):
    """List of facts response."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    facts: list[FactResponse]
    total: int
    offset: int
    limit: int


class PassageResponse(BaseModel):
    """Passage response."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    passage_id: str
    passage_hash: str
    evidence_id: str
    page_number: Optional[int]
    section_title: Optional[str]
    text_content: str
    passage_type: str


class DirectExtractRequest(BaseModel):
    """Request for direct extraction (testing)."""
    
    model_config = ConfigDict(extra="forbid")
    
    evidence_id: str
    content_base64: str  # Base64 encoded content
    source_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    min_confidence: Decimal = Field(default=DEFAULT_MIN_CONFIDENCE, ge=0, le=1)
    allow_low_confidence: bool = False


class DirectExtractResponse(BaseModel):
    """Response from direct extraction."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    success: bool
    evidence_id: str
    facts_extracted: int
    passages_extracted: int
    fact_ids: list[str]
    passage_ids: list[str]
    extraction_method: Optional[str]
    extraction_duration_ms: int
    refusal_code: Optional[str] = None
    error_message: Optional[str] = None


# =============================================================================
# Service Singleton
# =============================================================================

_service: Optional[ExtractionService] = None


def get_service() -> ExtractionService:
    """Get or create extraction service instance."""
    global _service
    if _service is None:
        _service = ExtractionService()
    return _service


def reset_service() -> None:
    """Reset service instance (for testing)."""
    global _service
    _service = None


# =============================================================================
# Lifespan
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    settings = get_settings()
    configure_logging(
        service_name="extraction-service",
        log_level=settings.log_level,
        json_output=not settings.debug,
    )
    logger.info("Starting Extraction Service", version=settings.service_version)
    # Initialize service
    get_service()
    yield
    logger.info("Shutting down Extraction Service")


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    application = FastAPI(
        title="Extraction Service",
        description="Deterministic fact extraction from financial evidence",
        version=settings.service_version,
        docs_url=settings.docs_url if settings.debug else None,
        lifespan=lifespan,
    )

    # =========================================================================
    # Health Endpoint
    # =========================================================================

    @application.get("/health", response_model=HealthCheck, tags=["Health"])
    async def health_check() -> HealthCheck:
        return HealthCheck(
            status=HealthStatus.HEALTHY,
            service="extraction-service",
            version=settings.service_version,
        )

    # =========================================================================
    # Extraction Endpoints
    # =========================================================================

    @application.post(
        "/v1/extract/run",
        response_model=RunExtractionResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["extraction"],
    )
    async def run_extraction(request: RunExtractionRequest) -> RunExtractionResponse:
        """
        Run extraction on specified evidence.
        
        This triggers an extraction job that processes each evidence item
        and extracts FinancialFact and EvidencePassage records.
        """
        service = get_service()
        
        # Generate trace_id if not provided
        import uuid
        trace_id = request.trace_id or f"trace_{uuid.uuid4().hex[:16]}"
        
        job_request = ExtractionJobRequest(
            evidence_ids=request.evidence_ids,
            claim_id=request.claim_id,
            trace_id=trace_id,
            min_confidence=request.min_confidence,
            allow_low_confidence=request.allow_low_confidence,
            force_reextract=request.force_reextract,
        )
        
        job = await service.run_extraction(job_request)
        
        return RunExtractionResponse(
            job_id=job.job_id,
            status=job.status,
            evidence_count=job.evidence_count,
            message=f"Extraction job created with {job.evidence_count} evidence items",
        )

    @application.get(
        "/v1/extract/status/{job_id}",
        response_model=JobStatusResponse,
        tags=["extraction"],
    )
    async def get_job_status(job_id: str) -> JobStatusResponse:
        """Get extraction job status."""
        service = get_service()
        
        job = await service.get_job(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job not found: {job_id}",
            )
        
        return JobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            evidence_count=job.evidence_count,
            completed_count=job.completed_count,
            failed_count=job.failed_count,
            total_facts=job.total_facts,
            total_passages=job.total_passages,
            started_at=job.started_at,
            completed_at=job.completed_at,
            results=[
                {
                    "evidence_id": r.evidence_id,
                    "success": r.success,
                    "facts_extracted": r.facts_extracted,
                    "passages_extracted": r.passages_extracted,
                    "extraction_method": r.extraction_method.value if r.extraction_method else None,
                    "refusal_code": r.refusal_code.value if r.refusal_code else None,
                    "error_message": r.error_message,
                }
                for r in job.results
            ],
        )

    @application.post(
        "/v1/extract/direct",
        response_model=DirectExtractResponse,
        tags=["extraction"],
    )
    async def extract_direct(request: DirectExtractRequest) -> DirectExtractResponse:
        """
        Direct extraction from content (for testing).
        
        This endpoint accepts base64-encoded content and extracts facts directly.
        """
        service = get_service()
        
        try:
            content = base64.b64decode(request.content_base64)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid base64 content: {e}",
            )
        
        result = await service.extract_from_evidence(
            evidence_id=request.evidence_id,
            content=content,
            source_type=request.source_type,
            metadata=request.metadata,
            min_confidence=request.min_confidence,
            allow_low_confidence=request.allow_low_confidence,
        )
        
        return DirectExtractResponse(
            success=result.success,
            evidence_id=result.evidence_id,
            facts_extracted=result.facts_extracted,
            passages_extracted=result.passages_extracted,
            fact_ids=result.fact_ids,
            passage_ids=result.passage_ids,
            extraction_method=result.extraction_method.value if result.extraction_method else None,
            extraction_duration_ms=result.extraction_duration_ms,
            refusal_code=result.refusal_code.value if result.refusal_code else None,
            error_message=result.error_message,
        )

    # =========================================================================
    # Fact Endpoints
    # =========================================================================

    def _fact_to_response(fact: FinancialFact) -> FactResponse:
        """Convert FinancialFact to API response."""
        return FactResponse(
            fact_id=fact.fact_id,
            fact_hash=fact.fact_hash,
            fact_type=fact.fact_type,
            category=fact.category,
            value=fact.value,
            unit=fact.unit.value,
            currency=fact.currency,
            scale=fact.scale,
            as_of_date=fact.as_of_date.isoformat(),
            period_start=fact.period_start.isoformat() if fact.period_start else None,
            period_end=fact.period_end.isoformat() if fact.period_end else None,
            fiscal_year=fact.fiscal_year,
            fiscal_quarter=fact.fiscal_quarter,
            confidence=fact.confidence,
            confidence_level=fact.confidence_level,
            extraction_method=fact.extraction_method,
            entity_id=fact.entity_id,
            entity_id_type=fact.entity_id_type,
            evidence_id=fact.derived_from.evidence_id,
        )

    # Define static routes BEFORE dynamic routes to avoid path conflicts
    @application.get(
        "/v1/facts/by-entity",
        response_model=FactListResponse,
        tags=["facts"],
    )
    async def get_facts_by_entity(
        entity_id_type: str = Query(..., description="Entity ID type (e.g., 'CIK')"),
        entity_id: str = Query(..., description="Entity identifier"),
        fact_types: Optional[str] = Query(None, description="Comma-separated fact types"),
        min_confidence: Optional[Decimal] = Query(None, ge=0, le=1),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
    ) -> FactListResponse:
        """Get facts for an entity."""
        service = get_service()
        
        type_list = fact_types.split(",") if fact_types else None
        
        facts, total = await service.find_facts_by_entity(
            entity_id_type=entity_id_type,
            entity_id=entity_id,
            fact_types=type_list,
            min_confidence=min_confidence,
            offset=offset,
            limit=limit,
        )
        
        return FactListResponse(
            facts=[_fact_to_response(f) for f in facts],
            total=total,
            offset=offset,
            limit=limit,
        )

    @application.get(
        "/v1/facts/by-claim",
        response_model=FactListResponse,
        tags=["facts"],
    )
    async def get_facts_by_claim(
        claim_id: str = Query(..., description="Claim ID"),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
    ) -> FactListResponse:
        """Get facts linked to a claim."""
        service = get_service()
        
        facts, total = await service.find_facts_by_claim(
            claim_id=claim_id,
            offset=offset,
            limit=limit,
        )
        
        return FactListResponse(
            facts=[_fact_to_response(f) for f in facts],
            total=total,
            offset=offset,
            limit=limit,
        )

    @application.get(
        "/v1/facts/by-evidence/{evidence_id}",
        response_model=FactListResponse,
        tags=["facts"],
    )
    async def get_facts_by_evidence(evidence_id: str) -> FactListResponse:
        """Get all facts extracted from an evidence item."""
        service = get_service()
        
        facts = await service.find_facts_by_evidence(evidence_id)
        
        return FactListResponse(
            facts=[_fact_to_response(f) for f in facts],
            total=len(facts),
            offset=0,
            limit=len(facts),
        )

    # Dynamic route AFTER static routes
    @application.get(
        "/v1/facts/{fact_id}",
        response_model=FactResponse,
        tags=["facts"],
    )
    async def get_fact(fact_id: str) -> FactResponse:
        """Get a single fact by ID."""
        service = get_service()
        
        fact = await service.get_fact(fact_id)
        if not fact:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Fact not found: {fact_id}",
            )
        
        return _fact_to_response(fact)

    # =========================================================================
    # Passage Endpoints
    # =========================================================================

    @application.get(
        "/v1/passages/{passage_id}",
        response_model=PassageResponse,
        tags=["passages"],
    )
    async def get_passage(passage_id: str) -> PassageResponse:
        """Get a passage by ID."""
        service = get_service()
        
        passage = await service.get_passage(passage_id)
        if not passage:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Passage not found: {passage_id}",
            )
        
        return PassageResponse(
            passage_id=passage.passage_id,
            passage_hash=passage.passage_hash,
            evidence_id=passage.evidence_id,
            page_number=passage.page_number,
            section_title=passage.section_title,
            text_content=passage.text_content,
            passage_type=passage.passage_type,
        )

    return application


app = create_app()


# =============================================================================
# Main Entry Point
# =============================================================================


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("EXTRACTION_SERVICE_PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)
