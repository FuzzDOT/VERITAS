"""
API Gateway Service
===================

Production-grade API Gateway for the Financial Solvency Truth Engine.

This module provides:
- Single external endpoint: POST /v1/claims/solvency:evaluate
- Health and readiness endpoints
- Exhaustive input validation
- Deterministic request normalization
- Idempotency via request hashing
- Structured refusal responses
"""

from services.api_gateway.app import create_app, app
from services.api_gateway.routes import router
from services.api_gateway.schemas import (
    SolvencyEvaluationRequest,
    SolvencyEvaluationAccepted,
    RefusalResponse,
    CanonicalSolvencyRequest,
    HealthResponse,
    ReadinessResponse,
)
from services.api_gateway.validation import (
    SolvencyRequestValidator,
    IdempotencyManager,
    ValidationResult,
    create_validator,
    create_idempotency_manager,
)

__all__ = [
    "create_app",
    "app",
    "router",
    "SolvencyEvaluationRequest",
    "SolvencyEvaluationAccepted",
    "RefusalResponse",
    "CanonicalSolvencyRequest",
    "HealthResponse",
    "ReadinessResponse",
    "SolvencyRequestValidator",
    "IdempotencyManager",
    "ValidationResult",
    "create_validator",
    "create_idempotency_manager",
]
