"""
Truth Versioning Service - REST API Routes
============================================

Provides REST endpoints for:
- Promoting evaluations to truth versions
- Retrieving truth versions by ID, claim class, or evaluation
- Version history and diffs
- Impact analysis and recomputation triggers
"""

from datetime import date, datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.logging import get_logger
from shared.canonical_id import EntityType, generate_canonical_id

from infrastructure.postgres.session import get_session

from .schemas import (
    TRUTH_VERSION_SERVICE_VERSION,
    TruthVersion,
    TruthDiff,
    ClaimClassKey,
    PromoteRequest,
    PromoteResponse,
    GetHistoryRequest,
    GetHistoryResponse,
    GetDiffRequest,
    ImpactAnalysisRequest,
    ImpactAnalysisResult,
    PromotionResult,
    bucket_horizon,
    bucket_as_of_date,
    derive_claim_class_key,
)
from .stores import (
    TruthVersionStore,
    RecomputeQueue,
    ClaimClassIndex,
    ReplayVerifier,
)
from .promotion import (
    PromotionService,
    DiffService,
    ImpactAnalysisService,
)


logger = get_logger(__name__)


# =============================================================================
# Dependencies
# =============================================================================


async def get_db():
    """Get database session."""
    async with get_session() as session:
        yield session


def get_version_store(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TruthVersionStore:
    """Get truth version store."""
    return TruthVersionStore(session)


def get_recompute_queue(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RecomputeQueue:
    """Get recompute queue."""
    return RecomputeQueue(session)


def get_claim_class_index(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ClaimClassIndex:
    """Get claim class index."""
    return ClaimClassIndex(session)


def get_verifier(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ReplayVerifier:
    """Get replay verifier."""
    return ReplayVerifier(session)


def get_promotion_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    version_store: Annotated[TruthVersionStore, Depends(get_version_store)],
    verifier: Annotated[ReplayVerifier, Depends(get_verifier)],
    claim_class_index: Annotated[ClaimClassIndex, Depends(get_claim_class_index)],
) -> PromotionService:
    """Get promotion service."""
    return PromotionService(session, version_store, verifier, claim_class_index)


def get_diff_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    version_store: Annotated[TruthVersionStore, Depends(get_version_store)],
) -> DiffService:
    """Get diff service."""
    return DiffService(session, version_store)


def get_impact_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    claim_class_index: Annotated[ClaimClassIndex, Depends(get_claim_class_index)],
    recompute_queue: Annotated[RecomputeQueue, Depends(get_recompute_queue)],
) -> ImpactAnalysisService:
    """Get impact analysis service."""
    return ImpactAnalysisService(session, claim_class_index, recompute_queue)


# =============================================================================
# Request/Response Models
# =============================================================================


class PromoteEvaluationRequest(BaseModel):
    """Request to promote an evaluation."""
    
    model_config = ConfigDict(extra="forbid")
    
    evaluation_id: str = Field(..., description="Evaluation ID to promote")
    
    # Claim class components (required for claim class key derivation)
    entity_id: str = Field(..., description="Entity ID")
    entity_id_type: str = Field(..., description="Entity ID type")
    jurisdiction: str = Field(..., description="Jurisdiction")
    scenario_name: str = Field(default="baseline", description="Scenario name")
    scenario_shocks_hash: str = Field(
        default="0" * 64, description="Hash of scenario shocks"
    )
    horizon_months: int = Field(..., ge=3, le=120, description="Horizon in months")
    as_of_date: date = Field(..., description="As-of date")
    
    # Claim summary
    canonical_claim_hash: str = Field(..., description="Canonical claim hash")
    canonical_claim_summary: str = Field(..., description="Claim summary")
    
    # Evidence used
    evidence_ids: list[str] = Field(
        default_factory=list, description="Evidence IDs used"
    )
    
    # Options
    force_supersede: bool = Field(
        default=False, description="Force supersession even if hashes match"
    )


class GetCurrentRequest(BaseModel):
    """Request to get current truth version."""
    
    model_config = ConfigDict(extra="forbid")
    
    # By claim class key components
    entity_id: Optional[str] = Field(None)
    entity_id_type: Optional[str] = Field(None)
    jurisdiction: Optional[str] = Field(None)
    scenario_name: Optional[str] = Field(default="baseline")
    scenario_shocks_hash: Optional[str] = Field(default="0" * 64)
    horizon_months: Optional[int] = Field(None)
    as_of_date: Optional[date] = Field(None)
    
    # Or by pre-computed key
    claim_class_key: Optional[str] = Field(None)


class GetTruthVersionResponse(BaseModel):
    """Response with truth version."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    truth_version: TruthVersion


class GetDiffResponse(BaseModel):
    """Response with diff."""
    
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    diff: TruthDiff


# =============================================================================
# Router
# =============================================================================


router = APIRouter(tags=["Truth Versioning"])


# -----------------------------------------------------------------------------
# Promotion Endpoints
# -----------------------------------------------------------------------------


@router.post("/truth/promote", response_model=PromoteResponse)
async def promote_evaluation(
    request: PromoteEvaluationRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    promotion_service: Annotated[PromotionService, Depends(get_promotion_service)],
) -> PromoteResponse:
    """
    Promote an evaluation to a truth version.
    
    Creates a new TruthVersion if:
    - Evaluation has stored trace and audit records
    - Evaluation is replay-verified
    - Either no prior version exists, or hashes differ from prior
    """
    # Derive claim class key
    claim_class_key = ClaimClassKey.from_components(
        entity_id=request.entity_id,
        entity_id_type=request.entity_id_type,
        jurisdiction=request.jurisdiction,
        scenario_name=request.scenario_name,
        scenario_shocks_hash=request.scenario_shocks_hash,
        horizon_months=request.horizon_months,
        as_of_date=request.as_of_date,
    )
    
    result = await promotion_service.promote(
        evaluation_id=request.evaluation_id,
        claim_class_key=claim_class_key,
        canonical_claim_hash=request.canonical_claim_hash,
        canonical_claim_summary=request.canonical_claim_summary,
        evidence_ids=request.evidence_ids,
        force_supersede=request.force_supersede,
    )
    
    logger.info(
        "Promotion completed",
        evaluation_id=request.evaluation_id,
        result=result.result.value,
        truth_version_id=result.truth_version_id,
    )
    
    return result


# -----------------------------------------------------------------------------
# Retrieval Endpoints
# -----------------------------------------------------------------------------


@router.get("/truth/{truth_version_id}", response_model=GetTruthVersionResponse)
async def get_truth_version(
    truth_version_id: Annotated[str, Path(..., description="Truth version ID")],
    version_store: Annotated[TruthVersionStore, Depends(get_version_store)],
) -> GetTruthVersionResponse:
    """Get a truth version by ID."""
    version = await version_store.get(truth_version_id)
    
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Truth version not found: {truth_version_id}",
        )
    
    return GetTruthVersionResponse(truth_version=version)


@router.get("/truth/by-evaluation/{evaluation_id}", response_model=GetTruthVersionResponse)
async def get_truth_version_by_evaluation(
    evaluation_id: Annotated[str, Path(..., description="Evaluation ID")],
    version_store: Annotated[TruthVersionStore, Depends(get_version_store)],
) -> GetTruthVersionResponse:
    """Get truth version by evaluation ID."""
    version = await version_store.get_by_evaluation(evaluation_id)
    
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No truth version found for evaluation: {evaluation_id}",
        )
    
    return GetTruthVersionResponse(truth_version=version)


@router.post("/truth/current", response_model=GetTruthVersionResponse)
async def get_current_truth_version(
    request: GetCurrentRequest,
    version_store: Annotated[TruthVersionStore, Depends(get_version_store)],
) -> GetTruthVersionResponse:
    """
    Get the current (latest) truth version for a claim class.
    
    Can provide either:
    - claim_class_key directly, OR
    - Individual components to derive the key
    """
    if request.claim_class_key:
        key = request.claim_class_key
    elif (request.entity_id and request.entity_id_type and 
          request.jurisdiction and request.horizon_months and request.as_of_date):
        key = derive_claim_class_key(
            entity_id=request.entity_id,
            entity_id_type=request.entity_id_type,
            jurisdiction=request.jurisdiction,
            scenario_name=request.scenario_name or "baseline",
            scenario_shocks_hash=request.scenario_shocks_hash or "0" * 64,
            horizon_months=request.horizon_months,
            as_of_date=request.as_of_date,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide claim_class_key or all component fields",
        )
    
    version = await version_store.get_current(key)
    
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No current truth version for claim class: {key}",
        )
    
    return GetTruthVersionResponse(truth_version=version)


@router.post("/truth/history", response_model=GetHistoryResponse)
async def get_truth_history(
    request: GetHistoryRequest,
    version_store: Annotated[TruthVersionStore, Depends(get_version_store)],
) -> GetHistoryResponse:
    """Get version history for a claim class."""
    versions, total = await version_store.get_history(
        claim_class_key=request.claim_class_key,
        offset=request.offset,
        limit=request.limit,
        include_superseded=request.include_superseded,
    )
    
    has_more = request.offset + len(versions) < total
    
    return GetHistoryResponse(
        claim_class_key=request.claim_class_key,
        versions=versions,
        total_count=total,
        has_more=has_more,
    )


# -----------------------------------------------------------------------------
# Diff Endpoints
# -----------------------------------------------------------------------------


@router.post("/truth/diff", response_model=GetDiffResponse)
async def get_truth_diff(
    request: GetDiffRequest,
    diff_service: Annotated[DiffService, Depends(get_diff_service)],
) -> GetDiffResponse:
    """
    Generate a structured diff between two truth versions.
    
    The diff is deterministic and includes:
    - Evidence changes
    - Fact changes
    - Policy changes
    - Engine version changes
    - Decision/conclusion changes
    """
    diff = await diff_service.generate_diff(
        version_a_id=request.version_a_id,
        version_b_id=request.version_b_id,
    )
    
    if not diff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both versions not found",
        )
    
    return GetDiffResponse(diff=diff)


# -----------------------------------------------------------------------------
# Impact Analysis Endpoints
# -----------------------------------------------------------------------------


@router.post("/truth/impact/analyze", response_model=ImpactAnalysisResult)
async def analyze_impact(
    request: ImpactAnalysisRequest,
    impact_service: Annotated[ImpactAnalysisService, Depends(get_impact_service)],
) -> ImpactAnalysisResult:
    """
    Analyze impact of evidence or entity updates.
    
    Returns impacted claim classes and optionally queues recomputation tasks.
    """
    result = await impact_service.analyze_impact(
        evidence_id=request.evidence_id,
        entity_id=request.entity_id,
        entity_id_type=request.entity_id_type,
        date_range_start=request.date_range_start,
        date_range_end=request.date_range_end,
        queue_tasks=request.queue_tasks,
        priority=request.priority,
    )
    
    logger.info(
        "Impact analysis completed",
        analysis_id=result.analysis_id,
        total_impacted=result.total_impacted,
        total_queued=result.total_queued,
    )
    
    return result


# -----------------------------------------------------------------------------
# Utility Endpoints
# -----------------------------------------------------------------------------


@router.get("/truth/version")
async def get_service_version() -> dict[str, str]:
    """Get service version information."""
    return {
        "service": "truth-versioning-service",
        "version": TRUTH_VERSION_SERVICE_VERSION,
    }


@router.get("/truth/claim-class-key")
async def compute_claim_class_key(
    entity_id: Annotated[str, Query(..., description="Entity ID")],
    entity_id_type: Annotated[str, Query(..., description="Entity ID type")],
    jurisdiction: Annotated[str, Query(..., description="Jurisdiction")],
    horizon_months: Annotated[int, Query(..., ge=3, le=120)],
    as_of_date: Annotated[date, Query(...)],
    scenario_name: str = Query("baseline"),
    scenario_shocks_hash: str = Query("0" * 64),
) -> dict[str, Any]:
    """
    Compute the claim class key for given components.
    
    Useful for understanding how claim classes are grouped.
    """
    claim_class_key = ClaimClassKey.from_components(
        entity_id=entity_id,
        entity_id_type=entity_id_type,
        jurisdiction=jurisdiction,
        scenario_name=scenario_name,
        scenario_shocks_hash=scenario_shocks_hash,
        horizon_months=horizon_months,
        as_of_date=as_of_date,
    )
    
    return {
        "key": claim_class_key.key,
        "components": {
            "entity_id": claim_class_key.entity_id,
            "entity_id_type": claim_class_key.entity_id_type,
            "jurisdiction": claim_class_key.jurisdiction,
            "scenario_name": claim_class_key.scenario_name,
            "scenario_shocks_hash": claim_class_key.scenario_shocks_hash[:16] + "...",
            "horizon_bucket": claim_class_key.horizon_bucket,
            "as_of_date_bucket": claim_class_key.as_of_date_bucket.isoformat(),
        },
        "bucketing": {
            "original_horizon": horizon_months,
            "bucketed_horizon": claim_class_key.horizon_bucket,
            "original_as_of_date": as_of_date.isoformat(),
            "bucketed_as_of_date": claim_class_key.as_of_date_bucket.isoformat(),
        },
    }
