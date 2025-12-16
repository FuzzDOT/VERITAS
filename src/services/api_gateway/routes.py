"""
API Gateway Routes
==================

Defines all API routes and their handlers.
Routes delegate to internal services for actual processing.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from shared.schemas import (
    ClaimSummary,
    ConfidenceLevel,
    PaginatedResponse,
    PaginationParams,
    SuccessResponse,
    TruthStatus,
)


router = APIRouter()


# ============================================================================
# Request/Response Schemas
# ============================================================================


class CreateClaimRequest(BaseModel):
    """Request to create a new claim for verification."""

    content: str = Field(..., min_length=1, max_length=10000, description="The claim content")
    source: Optional[str] = Field(None, description="Source of the claim")
    organization_id: Optional[str] = Field(None, description="Organization context")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class CreateClaimResponse(BaseModel):
    """Response after creating a claim."""

    id: str
    content_hash: str
    status: TruthStatus
    created_at: datetime


class SubmitEvidenceRequest(BaseModel):
    """Request to submit evidence for a claim."""

    claim_id: str = Field(..., description="The claim this evidence supports or refutes")
    source_type: str = Field(..., description="Type of evidence source")
    source_uri: Optional[str] = Field(None, description="URI of the evidence source")
    content: Optional[str] = Field(None, description="Raw evidence content")
    metadata: dict = Field(default_factory=dict)


class SubmitEvidenceResponse(BaseModel):
    """Response after submitting evidence."""

    id: str
    claim_id: str
    content_hash: str
    source_type: str
    created_at: datetime


class GetClaimResponse(BaseModel):
    """Full claim details response."""

    id: str
    content_hash: str
    status: TruthStatus
    confidence: Optional[ConfidenceLevel]
    source: Optional[str]
    current_version: int
    evidence_count: int
    created_at: datetime
    updated_at: datetime


class TruthStatusResponse(BaseModel):
    """Current truth status of a claim."""

    claim_id: str
    status: TruthStatus
    confidence: ConfidenceLevel
    version: int
    reasoning_trace_id: Optional[str]
    last_evaluated: datetime


# ============================================================================
# Claim Endpoints
# ============================================================================


@router.post("/claims", response_model=SuccessResponse[CreateClaimResponse], tags=["Claims"])
async def create_claim(request: CreateClaimRequest) -> SuccessResponse[CreateClaimResponse]:
    """
    Create a new claim for verification.

    The claim will be queued for processing through the truth verification workflow.
    """
    # EXTENSION_POINT: A1+ will implement actual claim creation
    # This is just the interface definition
    response = CreateClaimResponse(
        id="CLM_placeholder",
        content_hash="sha256v1:placeholder",
        status=TruthStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    return SuccessResponse(data=response)


@router.get("/claims/{claim_id}", response_model=SuccessResponse[GetClaimResponse], tags=["Claims"])
async def get_claim(claim_id: str) -> SuccessResponse[GetClaimResponse]:
    """
    Get details of a specific claim.

    Returns the current state of the claim including its truth status.
    """
    # EXTENSION_POINT: A1+ will implement actual claim retrieval
    response = GetClaimResponse(
        id=claim_id,
        content_hash="sha256v1:placeholder",
        status=TruthStatus.PENDING,
        confidence=None,
        source=None,
        current_version=1,
        evidence_count=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return SuccessResponse(data=response)


@router.get("/claims", response_model=PaginatedResponse[ClaimSummary], tags=["Claims"])
async def list_claims(
    status: Optional[TruthStatus] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> PaginatedResponse[ClaimSummary]:
    """
    List claims with optional filtering.

    Returns a paginated list of claim summaries.
    """
    # EXTENSION_POINT: A1+ will implement actual claim listing
    return PaginatedResponse(
        items=[],
        total=0,
        page=page,
        page_size=page_size,
        total_pages=0,
        has_next=False,
        has_previous=False,
    )


@router.get(
    "/claims/{claim_id}/status",
    response_model=SuccessResponse[TruthStatusResponse],
    tags=["Claims"],
)
async def get_claim_status(claim_id: str) -> SuccessResponse[TruthStatusResponse]:
    """
    Get the current truth status of a claim.

    Returns the latest truth determination and confidence level.
    """
    # EXTENSION_POINT: A1+ will implement actual status retrieval
    response = TruthStatusResponse(
        claim_id=claim_id,
        status=TruthStatus.PENDING,
        confidence=ConfidenceLevel.UNKNOWN,
        version=1,
        reasoning_trace_id=None,
        last_evaluated=datetime.now(timezone.utc),
    )
    return SuccessResponse(data=response)


# ============================================================================
# Evidence Endpoints
# ============================================================================


@router.post(
    "/evidence",
    response_model=SuccessResponse[SubmitEvidenceResponse],
    tags=["Evidence"],
)
async def submit_evidence(
    request: SubmitEvidenceRequest,
) -> SuccessResponse[SubmitEvidenceResponse]:
    """
    Submit evidence for a claim.

    Evidence can support or refute a claim. The system will process
    the evidence and update the claim's truth status accordingly.
    """
    # EXTENSION_POINT: A1+ will implement actual evidence submission
    response = SubmitEvidenceResponse(
        id="EVD_placeholder",
        claim_id=request.claim_id,
        content_hash="sha256v1:placeholder",
        source_type=request.source_type,
        created_at=datetime.now(timezone.utc),
    )
    return SuccessResponse(data=response)


@router.get("/claims/{claim_id}/evidence", tags=["Evidence"])
async def list_claim_evidence(
    claim_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> PaginatedResponse:
    """
    List all evidence for a specific claim.

    Returns a paginated list of evidence items.
    """
    # EXTENSION_POINT: A1+ will implement actual evidence listing
    return PaginatedResponse(
        items=[],
        total=0,
        page=page,
        page_size=page_size,
        total_pages=0,
        has_next=False,
        has_previous=False,
    )


# ============================================================================
# Report Endpoints
# ============================================================================


class GenerateReportRequest(BaseModel):
    """Request to generate a report."""

    claim_id: str
    report_type: str = Field(default="summary", description="Type of report to generate")
    format: str = Field(default="json", description="Output format (json, pdf, html)")


class ReportResponse(BaseModel):
    """Response containing report information."""

    id: str
    claim_id: str
    report_type: str
    format: str
    status: str
    download_url: Optional[str]
    created_at: datetime


@router.post("/reports", response_model=SuccessResponse[ReportResponse], tags=["Reports"])
async def generate_report(
    request: GenerateReportRequest,
) -> SuccessResponse[ReportResponse]:
    """
    Generate a report for a claim.

    Reports provide formatted summaries of truth determinations.
    """
    # EXTENSION_POINT: A1+ will implement actual report generation
    response = ReportResponse(
        id="RPT_placeholder",
        claim_id=request.claim_id,
        report_type=request.report_type,
        format=request.format,
        status="pending",
        download_url=None,
        created_at=datetime.now(timezone.utc),
    )
    return SuccessResponse(data=response)


@router.get("/reports/{report_id}", response_model=SuccessResponse[ReportResponse], tags=["Reports"])
async def get_report(report_id: str) -> SuccessResponse[ReportResponse]:
    """
    Get a report by ID.

    Returns report metadata and download URL if available.
    """
    # EXTENSION_POINT: A1+ will implement actual report retrieval
    response = ReportResponse(
        id=report_id,
        claim_id="CLM_placeholder",
        report_type="summary",
        format="json",
        status="pending",
        download_url=None,
        created_at=datetime.now(timezone.utc),
    )
    return SuccessResponse(data=response)


# ============================================================================
# Audit Endpoints
# ============================================================================


class AuditEntryResponse(BaseModel):
    """Response containing audit entry information."""

    id: str
    trace_id: str
    operation: str
    entity_type: str
    entity_id: str
    action: str
    timestamp: datetime


@router.get(
    "/claims/{claim_id}/audit",
    response_model=PaginatedResponse[AuditEntryResponse],
    tags=["Audit"],
)
async def get_claim_audit_trail(
    claim_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> PaginatedResponse[AuditEntryResponse]:
    """
    Get the audit trail for a claim.

    Returns all audit entries related to the specified claim.
    """
    # EXTENSION_POINT: A1+ will implement actual audit trail retrieval
    return PaginatedResponse(
        items=[],
        total=0,
        page=page,
        page_size=page_size,
        total_pages=0,
        has_next=False,
        has_previous=False,
    )


# ============================================================================
# Version History Endpoints
# ============================================================================


class VersionHistoryResponse(BaseModel):
    """Response containing version history."""

    id: str
    claim_id: str
    version_number: int
    status: TruthStatus
    confidence: Optional[ConfidenceLevel]
    state_hash: str
    created_at: datetime


@router.get(
    "/claims/{claim_id}/versions",
    response_model=PaginatedResponse[VersionHistoryResponse],
    tags=["Versioning"],
)
async def get_claim_versions(
    claim_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> PaginatedResponse[VersionHistoryResponse]:
    """
    Get the version history for a claim.

    Returns all truth versions for the specified claim.
    """
    # EXTENSION_POINT: A1+ will implement actual version history retrieval
    return PaginatedResponse(
        items=[],
        total=0,
        page=page,
        page_size=page_size,
        total_pages=0,
        has_next=False,
        has_previous=False,
    )
