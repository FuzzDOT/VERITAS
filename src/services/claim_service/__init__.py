"""
Claim Service - Production A3
==============================

Production-grade claim processing for the Financial Solvency Truth Engine.

Provides:
- Semantic validation of solvency claims
- Entity resolution and normalization (CIK/LEI/ticker)
- Required facts contract derivation
- Deterministic claim canonicalization
"""

from services.claim_service.app import create_app
from services.claim_service.service import ClaimService
from services.claim_service.processor import ClaimProcessor
from services.claim_service.schemas import (
    # Enums
    ClaimType,
    SemanticRefusalCode,
    FactCategory,
    FactPriority,
    EntityResolutionStatus,
    # Core models
    CanonicalSolvencyClaim,
    RequiredFact,
    RequiredFactsContract,
    SemanticRefusal,
    SemanticValidationResult,
    ClaimProcessingResult,
    # Sub-models
    ResolvedEntityIdentifier,
    NormalizedHorizon,
    ValidatedScenario,
    # API models
    ProcessClaimRequest,
    ProcessClaimResponse,
)

__all__ = [
    # App
    "create_app",
    # Service
    "ClaimService",
    "ClaimProcessor",
    # Enums
    "ClaimType",
    "SemanticRefusalCode",
    "FactCategory",
    "FactPriority",
    "EntityResolutionStatus",
    # Core models
    "CanonicalSolvencyClaim",
    "RequiredFact",
    "RequiredFactsContract",
    "SemanticRefusal",
    "SemanticValidationResult",
    "ClaimProcessingResult",
    # Sub-models
    "ResolvedEntityIdentifier",
    "NormalizedHorizon",
    "ValidatedScenario",
    # API models
    "ProcessClaimRequest",
    "ProcessClaimResponse",
]
