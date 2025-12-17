"""
Trace & Audit Service - REST API Routes
=========================================

Provides:
- Trace graph building and retrieval
- Audit record access
- Daily manifest operations
- Replay verification
"""

from datetime import date, datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.logging import get_logger
from shared.errors import RefusalError

from infrastructure.postgres.session import get_session
from infrastructure.object_store import NullObjectStore, ObjectStoreInterface

from .schemas import (
    TRACE_SERVICE_VERSION,
    TraceGraph,
    AuditRecord,
    AuditManifest,
    ReplayResult,
    ReplayStatus,
    BuildTraceRequest,
    BuildTraceResponse,
    GetTraceResponse,
    GetAuditResponse,
    GetManifestResponse,
    ReplayVerificationRequest,
    ReplayVerificationResponse,
)
from .stores import (
    TraceStore,
    AuditStore,
    ManifestService,
    ReplayService,
    TraceAuditServiceV2,
)


logger = get_logger(__name__)


# =============================================================================
# Dependencies
# =============================================================================


async def get_db():
    """Get database session."""
    async with get_session() as session:
        yield session


async def get_object_store() -> ObjectStoreInterface:
    """Get object store (null implementation for A0)."""
    return NullObjectStore()


async def get_trace_audit_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    object_store: Annotated[ObjectStoreInterface, Depends(get_object_store)],
) -> TraceAuditServiceV2:
    """Get the unified trace/audit service."""
    return TraceAuditServiceV2(session, object_store)


# =============================================================================
# Request/Response Models
# =============================================================================


class ChainVerificationRequest(BaseModel):
    """Request to verify audit chain integrity."""
    
    model_config = ConfigDict(frozen=True)
    
    start_position: int = Field(default=0, ge=0, description="Start position in chain")
    end_position: Optional[int] = Field(default=None, ge=0, description="End position")


class ChainVerificationResponse(BaseModel):
    """Response from chain verification."""
    
    model_config = ConfigDict(frozen=True)
    
    is_valid: bool = Field(..., description="Whether chain is valid")
    first_invalid_audit_id: Optional[str] = Field(None, description="First invalid record ID")
    message: str = Field(..., description="Verification result message")


class TraceStatsResponse(BaseModel):
    """Statistics about traces."""
    
    model_config = ConfigDict(frozen=True)
    
    total_traces: int
    service_version: str


# =============================================================================
# Router
# =============================================================================


router = APIRouter(tags=["Trace & Audit"])


# -----------------------------------------------------------------------------
# Trace Endpoints
# -----------------------------------------------------------------------------


@router.get("/trace/{trace_id}", response_model=GetTraceResponse)
async def get_trace(
    trace_id: Annotated[str, Path(..., description="Trace ID")],
    service: Annotated[TraceAuditServiceV2, Depends(get_trace_audit_service)],
) -> GetTraceResponse:
    """
    Get a trace graph by ID.
    """
    trace = await service.trace_store.get(trace_id)
    
    if not trace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace not found: {trace_id}",
        )
    
    return GetTraceResponse(trace=trace)


@router.get("/trace/by-evaluation/{evaluation_id}", response_model=GetTraceResponse)
async def get_trace_by_evaluation(
    evaluation_id: Annotated[str, Path(..., description="Evaluation ID")],
    service: Annotated[TraceAuditServiceV2, Depends(get_trace_audit_service)],
) -> GetTraceResponse:
    """
    Get a trace graph by evaluation ID.
    """
    trace = await service.trace_store.get_by_evaluation(evaluation_id)
    
    if not trace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace not found for evaluation: {evaluation_id}",
        )
    
    return GetTraceResponse(trace=trace)


@router.get("/trace/by-hash/{trace_hash}", response_model=GetTraceResponse)
async def get_trace_by_hash(
    trace_hash: Annotated[str, Path(..., description="Trace hash")],
    service: Annotated[TraceAuditServiceV2, Depends(get_trace_audit_service)],
) -> GetTraceResponse:
    """
    Get a trace graph by its hash.
    """
    trace = await service.trace_store.get_by_hash(trace_hash)
    
    if not trace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace not found with hash: {trace_hash}",
        )
    
    return GetTraceResponse(trace=trace)


# -----------------------------------------------------------------------------
# Audit Endpoints
# -----------------------------------------------------------------------------


@router.get("/audit/{evaluation_id}", response_model=GetAuditResponse)
async def get_audit_record(
    evaluation_id: Annotated[str, Path(..., description="Evaluation ID")],
    service: Annotated[TraceAuditServiceV2, Depends(get_trace_audit_service)],
) -> GetAuditResponse:
    """
    Get an audit record by evaluation ID.
    """
    audit = await service.audit_store.get_by_evaluation(evaluation_id)
    
    if not audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit record not found for evaluation: {evaluation_id}",
        )
    
    return GetAuditResponse(audit=audit)


@router.get("/audit/by-id/{audit_id}", response_model=GetAuditResponse)
async def get_audit_by_id(
    audit_id: Annotated[str, Path(..., description="Audit record ID")],
    service: Annotated[TraceAuditServiceV2, Depends(get_trace_audit_service)],
) -> GetAuditResponse:
    """
    Get an audit record by its ID.
    """
    audit = await service.audit_store.get(audit_id)
    
    if not audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit record not found: {audit_id}",
        )
    
    return GetAuditResponse(audit=audit)


@router.get("/audit/by-hash/{audit_hash}", response_model=GetAuditResponse)
async def get_audit_by_hash(
    audit_hash: Annotated[str, Path(..., description="Audit record hash")],
    service: Annotated[TraceAuditServiceV2, Depends(get_trace_audit_service)],
) -> GetAuditResponse:
    """
    Get an audit record by its hash.
    """
    audit = await service.audit_store.get_by_hash(audit_hash)
    
    if not audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit record not found with hash: {audit_hash}",
        )
    
    return GetAuditResponse(audit=audit)


@router.post("/audit/verify-chain", response_model=ChainVerificationResponse)
async def verify_audit_chain(
    request: ChainVerificationRequest,
    service: Annotated[TraceAuditServiceV2, Depends(get_trace_audit_service)],
) -> ChainVerificationResponse:
    """
    Verify the integrity of the audit chain.
    
    Returns whether the chain is valid and, if not, the first invalid record.
    """
    is_valid, first_invalid = await service.audit_store.verify_chain(
        start_position=request.start_position,
        end_position=request.end_position,
    )
    
    if is_valid:
        return ChainVerificationResponse(
            is_valid=True,
            first_invalid_audit_id=None,
            message="Audit chain integrity verified",
        )
    else:
        return ChainVerificationResponse(
            is_valid=False,
            first_invalid_audit_id=first_invalid,
            message=f"Chain broken at audit record: {first_invalid}",
        )


# -----------------------------------------------------------------------------
# Manifest Endpoints
# -----------------------------------------------------------------------------


@router.get("/audit/manifest/{manifest_date}", response_model=GetManifestResponse)
async def get_manifest(
    manifest_date: Annotated[date, Path(..., description="Manifest date (YYYY-MM-DD)")],
    service: Annotated[TraceAuditServiceV2, Depends(get_trace_audit_service)],
) -> GetManifestResponse:
    """
    Get the audit manifest for a specific date.
    """
    manifest = await service.manifest_service.get_manifest(manifest_date)
    
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Manifest not found for date: {manifest_date}",
        )
    
    return GetManifestResponse(manifest=manifest)


@router.post("/audit/manifest/{manifest_date}/generate", response_model=GetManifestResponse)
async def generate_manifest(
    manifest_date: Annotated[date, Path(..., description="Manifest date (YYYY-MM-DD)")],
    service: Annotated[TraceAuditServiceV2, Depends(get_trace_audit_service)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> GetManifestResponse:
    """
    Generate and store the audit manifest for a specific date.
    
    This should be called at the end of each day to create a signed manifest.
    """
    # Check if manifest already exists
    existing = await service.manifest_service.get_manifest(manifest_date)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Manifest already exists for date: {manifest_date}",
        )
    
    manifest = await service.manifest_service.generate_manifest(manifest_date)
    await session.commit()
    
    logger.info(
        "Generated daily manifest",
        manifest_date=manifest_date.isoformat(),
        record_count=manifest.record_count,
        manifest_hash=manifest.manifest_hash,
    )
    
    return GetManifestResponse(manifest=manifest)


# -----------------------------------------------------------------------------
# Replay Endpoints
# -----------------------------------------------------------------------------


@router.get("/replay/{evaluation_id}", response_model=ReplayVerificationResponse)
async def verify_replay(
    evaluation_id: Annotated[str, Path(..., description="Evaluation ID")],
    service: Annotated[TraceAuditServiceV2, Depends(get_trace_audit_service)],
) -> ReplayVerificationResponse:
    """
    Verify replay consistency for an evaluation.
    
    Checks that stored trace and audit data is internally consistent.
    """
    result = await service.replay_service.verify_replay(evaluation_id)
    
    return ReplayVerificationResponse(result=result)


@router.post("/replay/{evaluation_id}/verify", response_model=ReplayVerificationResponse)
async def verify_replay_with_hashes(
    evaluation_id: Annotated[str, Path(..., description="Evaluation ID")],
    request: ReplayVerificationRequest,
    service: Annotated[TraceAuditServiceV2, Depends(get_trace_audit_service)],
) -> ReplayVerificationResponse:
    """
    Verify replay by comparing provided hashes against stored values.
    
    This is used when re-running an evaluation to verify determinism.
    """
    result = await service.replay_service.verify_replay(
        evaluation_id=evaluation_id,
        recomputed_trace_hash=request.recomputed_trace_hash,
        recomputed_result_hash=request.recomputed_result_hash,
        recomputed_facts_hash=request.recomputed_facts_hash,
    )
    
    return ReplayVerificationResponse(result=result)


# -----------------------------------------------------------------------------
# Utility Endpoints
# -----------------------------------------------------------------------------


@router.get("/version")
async def get_version() -> dict[str, str]:
    """Get service version information."""
    return {
        "service": "trace-audit-service",
        "version": TRACE_SERVICE_VERSION,
    }
