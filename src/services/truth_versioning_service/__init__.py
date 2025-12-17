"""
Truth Versioning Service
========================

Manages immutable versioned truth states for canonical solvency claim classes.

Key Features:
- Deterministic claim class key derivation with bucketing
- Promotion of evaluations to truth versions (gated on replay verification)
- Supersession rules based on hash differences
- Deterministic structured diffs between versions
- Impact analysis and recomputation queue management
"""

from services.truth_versioning_service.app import create_app
from services.truth_versioning_service.schemas import (
    TRUTH_VERSION_SERVICE_VERSION,
    HORIZON_BUCKETS,
    bucket_horizon,
    bucket_as_of_date,
    derive_claim_class_key,
    TruthVersionStatus,
    PromotionResult,
    DiffChangeType,
    RecomputeTaskStatus,
    ClaimClassKey,
    TruthVersion,
    TruthDiff,
    ImpactAnalysisResult,
    PromoteRequest,
    PromoteResponse,
    GetHistoryRequest,
    GetHistoryResponse,
    GetDiffRequest,
    ImpactAnalysisRequest,
)
from services.truth_versioning_service.stores import (
    TruthVersionStore,
    RecomputeQueue,
    ClaimClassIndex,
    ReplayVerifier,
)
from services.truth_versioning_service.promotion import (
    PromotionService,
    DiffService,
    ImpactAnalysisService,
)

__all__ = [
    # App
    "create_app",
    # Constants
    "TRUTH_VERSION_SERVICE_VERSION",
    "HORIZON_BUCKETS",
    # Bucketing functions
    "bucket_horizon",
    "bucket_as_of_date",
    "derive_claim_class_key",
    # Enums
    "TruthVersionStatus",
    "PromotionResult",
    "DiffChangeType",
    "RecomputeTaskStatus",
    # Core schemas
    "ClaimClassKey",
    "TruthVersion",
    "TruthDiff",
    "ImpactAnalysisResult",
    # API schemas
    "PromoteRequest",
    "PromoteResponse",
    "GetHistoryRequest",
    "GetHistoryResponse",
    "GetDiffRequest",
    "ImpactAnalysisRequest",
    # Stores
    "TruthVersionStore",
    "RecomputeQueue",
    "ClaimClassIndex",
    "ReplayVerifier",
    # Services
    "PromotionService",
    "DiffService",
    "ImpactAnalysisService",
]
