"""
Report Service - REST API Routes
===================================

Production-grade endpoints for report generation and retrieval:
- POST /v1/reports/generate: Generate report by truth_version_id
- GET /v1/reports/{report_id}/html: Get HTML artifact
- GET /v1/reports/{report_id}/pdf: Get PDF artifact  
- GET /v1/reports/by-truth/{truth_version_id}: Get reports for truth version
- GET /v1/reports/current: Get report for current truth of claim class

All endpoints follow RESTful conventions with proper error handling.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.logging import get_logger
from infrastructure.postgres.session import get_session
from infrastructure.object_store import ObjectStoreInterface

from .schemas import (
    REPORT_SERVICE_VERSION,
    HTML_RENDERER_VERSION,
    ReportMetadata,
    ReportStatus,
    GenerateReportRequest,
    GenerateReportByClaimClassRequest,
    GenerateReportResponse,
    GetReportResponse,
    ListReportsResponse,
)
from .stores import ReportStore, ArtifactStore
from .generator import ReportGenerator, create_html_renderer, create_pdf_renderer


logger = get_logger(__name__)


# =============================================================================
# Router
# =============================================================================

router = APIRouter(prefix="/v1/reports", tags=["Reports"])


# =============================================================================
# Dependencies
# =============================================================================


# Placeholder object store - in production this would be injected
_object_store: Optional[ObjectStoreInterface] = None


def get_object_store() -> ObjectStoreInterface:
    """Get object store instance."""
    if _object_store is None:
        raise HTTPException(
            status_code=503,
            detail="Object store not configured"
        )
    return _object_store


def set_object_store(store: ObjectStoreInterface) -> None:
    """Set object store instance (for testing/configuration)."""
    global _object_store
    _object_store = store


async def get_db():
    """Get database session - wrapper for FastAPI Depends."""
    async with get_session() as session:
        yield session


async def get_report_store(
    session: AsyncSession = Depends(get_db),
) -> ReportStore:
    """Get report store instance."""
    return ReportStore(session)


async def get_artifact_store(
    object_store: ObjectStoreInterface = Depends(get_object_store),
) -> ArtifactStore:
    """Get artifact store instance."""
    return ArtifactStore(object_store)


async def get_report_generator(
    session: AsyncSession = Depends(get_db),
    report_store: ReportStore = Depends(get_report_store),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
) -> ReportGenerator:
    """Get report generator instance."""
    return ReportGenerator(
        session=session,
        report_store=report_store,
        artifact_store=artifact_store,
        html_renderer=create_html_renderer(),
        pdf_renderer=create_pdf_renderer(),
    )


# =============================================================================
# Request/Response Models for Routes
# =============================================================================


class GenerateReportRequestBody(BaseModel):
    """Request body for report generation."""
    
    truth_version_id: str = Field(..., description="Truth version ID to report on")
    include_pdf: bool = Field(True, description="Whether to generate PDF")
    
    # Optional: Provide evidence and facts directly
    # In production, these would be fetched from the respective services
    evidence_list: list[dict] = Field(
        default_factory=list,
        description="Evidence items for provenance (optional)"
    )
    facts_list: list[dict] = Field(
        default_factory=list,
        description="Facts for provenance (optional)"
    )
    trace_id: Optional[str] = Field(None, description="Trace ID (optional)")
    audit_hash: Optional[str] = Field(None, description="Audit hash (optional)")
    metrics: list[dict] = Field(
        default_factory=list,
        description="Intermediate metrics (optional)"
    )


class GenerateByClaimClassRequestBody(BaseModel):
    """Request body for generating report by claim class."""
    
    claim_class_key: str = Field(..., description="Claim class key")
    include_pdf: bool = Field(True, description="Whether to generate PDF")


class VersionInfoResponse(BaseModel):
    """Response with service version info."""
    
    service_version: str
    html_renderer_version: str
    pdf_renderer_available: bool


# =============================================================================
# Endpoints
# =============================================================================


@router.post("/generate", response_model=GenerateReportResponse)
async def generate_report(
    request: GenerateReportRequestBody,
    session: AsyncSession = Depends(get_db),
    report_store: ReportStore = Depends(get_report_store),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
) -> GenerateReportResponse:
    """
    Generate a report for a truth version.
    
    Idempotent: If a report already exists for this truth_version_id
    and renderer_version, returns the existing report.
    """
    # In production, we would fetch the TruthVersion from A8 here
    # For now, we require a TruthVersion-like object to be passed or fetched
    
    # Check for existing report first (idempotency)
    existing = await report_store.find_existing(
        truth_version_id=request.truth_version_id,
        renderer_version=HTML_RENDERER_VERSION,
    )
    
    if existing:
        logger.info(
            "Returning cached report",
            report_id=existing.report_id,
            truth_version_id=request.truth_version_id,
        )
        return GenerateReportResponse(
            report_id=existing.report_id,
            truth_version_id=existing.truth_version_id,
            was_cached=True,
            html_uri=existing.html_uri,
            pdf_uri=existing.pdf_uri,
            html_hash=existing.html_hash,
            pdf_hash=existing.pdf_hash,
            message=f"Returned cached report {existing.report_id}",
        )
    
    # In production, fetch TruthVersion from truth versioning service
    # For now, return error indicating truth version must be fetched
    raise HTTPException(
        status_code=501,
        detail=(
            "Full report generation requires integration with A8 Truth Versioning Service. "
            "Use the internal API for testing."
        )
    )


# Version endpoint MUST be defined before /{report_id} to avoid path collision
@router.get("/version", response_model=VersionInfoResponse)
async def get_version_info() -> VersionInfoResponse:
    """Get report service version information."""
    pdf_available = False
    try:
        import weasyprint  # type: ignore[import-not-found]  # noqa: F401
        pdf_available = True
    except ImportError:
        pass
    
    return VersionInfoResponse(
        service_version=REPORT_SERVICE_VERSION,
        html_renderer_version=HTML_RENDERER_VERSION,
        pdf_renderer_available=pdf_available,
    )


@router.get("/{report_id}", response_model=GetReportResponse)
async def get_report(
    report_id: str,
    report_store: ReportStore = Depends(get_report_store),
) -> GetReportResponse:
    """Get report metadata by ID."""
    report = await report_store.get(report_id)
    
    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"Report {report_id} not found"
        )
    
    return GetReportResponse(report=report)


@router.get("/{report_id}/html")
async def get_report_html(
    report_id: str,
    report_store: ReportStore = Depends(get_report_store),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
) -> Response:
    """Get HTML artifact for a report."""
    report = await report_store.get(report_id)
    
    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"Report {report_id} not found"
        )
    
    html_content = await artifact_store.get_html(report.html_uri)
    
    if not html_content:
        raise HTTPException(
            status_code=404,
            detail=f"HTML artifact not found for report {report_id}"
        )
    
    return Response(
        content=html_content,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="report-{report_id}.html"',
            "X-Report-ID": report_id,
            "X-HTML-Hash": report.html_hash,
        },
    )


@router.get("/{report_id}/pdf")
async def get_report_pdf(
    report_id: str,
    report_store: ReportStore = Depends(get_report_store),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
) -> Response:
    """Get PDF artifact for a report."""
    report = await report_store.get(report_id)
    
    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"Report {report_id} not found"
        )
    
    if not report.pdf_uri:
        raise HTTPException(
            status_code=404,
            detail=f"PDF artifact not available for report {report_id}"
        )
    
    pdf_content = await artifact_store.get_pdf(report.pdf_uri)
    
    if not pdf_content:
        raise HTTPException(
            status_code=404,
            detail=f"PDF artifact not found for report {report_id}"
        )
    
    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="report-{report_id}.pdf"',
            "X-Report-ID": report_id,
            "X-PDF-Hash": report.pdf_hash or "",
        },
    )


@router.get("/by-truth/{truth_version_id}", response_model=ListReportsResponse)
async def get_reports_by_truth_version(
    truth_version_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    report_store: ReportStore = Depends(get_report_store),
) -> ListReportsResponse:
    """Get all reports for a truth version."""
    reports, total = await report_store.list_for_truth_version(
        truth_version_id=truth_version_id,
        offset=offset,
        limit=limit,
    )
    
    return ListReportsResponse(reports=reports, total=total)


@router.post("/current", response_model=GenerateReportResponse)
async def generate_report_for_current_truth(
    request: GenerateByClaimClassRequestBody,
    session: AsyncSession = Depends(get_db),
) -> GenerateReportResponse:
    """
    Generate a report for the current truth version of a claim class.
    
    First looks up the current truth version for the claim class,
    then generates (or returns cached) report for that version.
    """
    # In production, we would:
    # 1. Query A8 TruthVersionStore.get_current(claim_class_key)
    # 2. Generate report for that truth version
    
    raise HTTPException(
        status_code=501,
        detail=(
            "Report generation by claim class requires integration with A8. "
            "Use POST /v1/reports/generate with a truth_version_id."
        )
    )


# =============================================================================
# Internal API (for direct use within the service)
# =============================================================================


async def generate_report_internal(
    session: AsyncSession,
    truth_version: object,
    evidence_list: list[dict],
    facts_list: list[dict],
    object_store: ObjectStoreInterface,
    trace_id: Optional[str] = None,
    audit_hash: Optional[str] = None,
    metrics: Optional[list[dict]] = None,
    include_pdf: bool = True,
) -> GenerateReportResponse:
    """
    Internal API for report generation.
    
    This is called by other services or tests with full TruthVersion object.
    """
    report_store = ReportStore(session)
    artifact_store = ArtifactStore(object_store)
    
    generator = ReportGenerator(
        session=session,
        report_store=report_store,
        artifact_store=artifact_store,
        html_renderer=create_html_renderer(),
        pdf_renderer=create_pdf_renderer(),
    )
    
    return await generator.generate(
        truth_version=truth_version,
        evidence_list=evidence_list,
        facts_list=facts_list,
        trace_id=trace_id,
        audit_hash=audit_hash,
        metrics=metrics,
        include_pdf=include_pdf,
    )
