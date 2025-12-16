"""
Common Pydantic Schemas
=======================

Shared data models and schemas used across all services.
These provide the contract for inter-service communication.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


# Type variable for generic responses
T = TypeVar("T")


class TimestampMixin(BaseModel):
    """Mixin for models that track creation and modification times."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ServiceInfo(BaseModel):
    """Information about a service for health checks and discovery."""

    name: str
    version: str
    status: str = "healthy"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = Field(default_factory=dict)


class HealthStatus(str, Enum):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthCheck(BaseModel):
    """Standard health check response."""

    status: HealthStatus = HealthStatus.HEALTHY
    service: str
    version: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    checks: dict[str, HealthStatus] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standard error response schema."""

    error: str
    category: str
    operation: str
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SuccessResponse(BaseModel, Generic[T]):
    """Generic success response wrapper."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool = True
    data: T
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: Optional[str] = None


class PaginationParams(BaseModel):
    """Standard pagination parameters."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=1000)
    
    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


class AuditContext(BaseModel):
    """Context information for audit logging."""

    user_id: Optional[str] = None
    organization_id: Optional[str] = None
    trace_id: str
    span_id: Optional[str] = None
    operation: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class TruthStatus(str, Enum):
    """Status of a truth claim."""

    PENDING = "pending"
    PROCESSING = "processing"
    VERIFIED = "verified"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    NEEDS_REVIEW = "needs_review"


class ConfidenceLevel(str, Enum):
    """Confidence levels for truth determinations."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class ClaimSummary(BaseModel):
    """Summary information about a claim."""

    id: str
    status: TruthStatus
    confidence: ConfidenceLevel
    created_at: datetime
    updated_at: datetime
    version: int


class EvidenceSummary(BaseModel):
    """Summary information about evidence."""

    id: str
    claim_id: str
    source_type: str
    created_at: datetime
    hash: str


class ReasoningResult(BaseModel):
    """Result of a reasoning operation."""

    claim_id: str
    conclusion: TruthStatus
    confidence: ConfidenceLevel
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    reasoning_trace_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
