"""
Refusal and Error Types
=======================

Implements the refusal-first error handling paradigm. The system explicitly
refuses to proceed when preconditions are not met, rather than attempting
to handle invalid states.

Design Principles:
- All refusals are explicit and well-documented
- Refusals carry complete context for debugging
- Refusals are auditable and traceable
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class RefusalCategory(str, Enum):
    """Categories of system refusals."""

    PRECONDITION_NOT_MET = "precondition_not_met"
    VALIDATION_FAILED = "validation_failed"
    INVARIANT_VIOLATED = "invariant_violated"
    AUTHORIZATION_DENIED = "authorization_denied"
    RESOURCE_NOT_FOUND = "resource_not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class RefusalContext:
    """
    Complete context for a refusal, enabling debugging and auditing.

    Attributes:
        operation: The operation that was attempted
        reason: Human-readable explanation of why it was refused
        details: Additional structured details
        timestamp: When the refusal occurred
        trace_id: Optional trace ID for correlation
    """

    operation: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "operation": self.operation,
            "reason": self.reason,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "trace_id": self.trace_id,
        }


class RefusalError(Exception):
    """
    Base class for all refusal errors in the Truth Engine.

    Refusals are explicit rejections of operations that cannot proceed
    due to unmet preconditions, validation failures, or invariant violations.
    """

    category: RefusalCategory = RefusalCategory.INTERNAL_ERROR

    def __init__(
        self,
        message: str,
        *,
        operation: str = "unknown",
        details: Optional[dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.context = RefusalContext(
            operation=operation,
            reason=message,
            details=details or {},
            trace_id=trace_id,
        )

    @property
    def operation(self) -> str:
        return self.context.operation

    @property
    def reason(self) -> str:
        return self.context.reason

    @property
    def details(self) -> dict[str, Any]:
        return self.context.details


class PreconditionNotMetError(RefusalError):
    """
    Raised when a required precondition for an operation is not met.

    This indicates that the system state does not satisfy the requirements
    for the requested operation to proceed.
    """

    category = RefusalCategory.PRECONDITION_NOT_MET


class ValidationRefusalError(RefusalError):
    """
    Raised when input validation fails.

    This indicates that the provided input does not conform to the
    expected schema or business rules.
    """

    category = RefusalCategory.VALIDATION_FAILED


class InvariantViolationError(RefusalError):
    """
    Raised when a system invariant would be violated.

    This is a serious error indicating that the operation would put
    the system into an invalid state.
    """

    category = RefusalCategory.INVARIANT_VIOLATED


class AuthorizationDeniedError(RefusalError):
    """Raised when the caller is not authorized to perform the operation."""

    category = RefusalCategory.AUTHORIZATION_DENIED


class ResourceNotFoundError(RefusalError):
    """Raised when a required resource does not exist."""

    category = RefusalCategory.RESOURCE_NOT_FOUND


class ConflictError(RefusalError):
    """Raised when the operation conflicts with existing state."""

    category = RefusalCategory.CONFLICT


class ServiceUnavailableError(RefusalError):
    """Raised when a required service is unavailable."""

    category = RefusalCategory.SERVICE_UNAVAILABLE


def refuse(
    message: str,
    *,
    category: RefusalCategory = RefusalCategory.PRECONDITION_NOT_MET,
    operation: str = "unknown",
    details: Optional[dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> RefusalError:
    """
    Factory function to create the appropriate RefusalError subclass.

    Args:
        message: Human-readable refusal message
        category: The category of refusal
        operation: The operation being refused
        details: Additional context
        trace_id: Correlation ID for tracing

    Returns:
        An appropriate RefusalError subclass
    """
    error_classes = {
        RefusalCategory.PRECONDITION_NOT_MET: PreconditionNotMetError,
        RefusalCategory.VALIDATION_FAILED: ValidationRefusalError,
        RefusalCategory.INVARIANT_VIOLATED: InvariantViolationError,
        RefusalCategory.AUTHORIZATION_DENIED: AuthorizationDeniedError,
        RefusalCategory.RESOURCE_NOT_FOUND: ResourceNotFoundError,
        RefusalCategory.CONFLICT: ConflictError,
        RefusalCategory.SERVICE_UNAVAILABLE: ServiceUnavailableError,
    }

    error_class = error_classes.get(category, RefusalError)
    return error_class(
        message,
        operation=operation,
        details=details,
        trace_id=trace_id,
    )
