"""
Structured Logging
==================

Provides structured, JSON-formatted logging for all services.
Uses structlog for context-rich, machine-parseable logs.

Design Principles:
- All logs are structured JSON for easy parsing
- Logs include trace correlation IDs
- Sensitive data is never logged
"""

import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from structlog.types import EventDict, Processor

from shared.config import get_settings


# Context variable for trace correlation
trace_id_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
span_id_var: ContextVar[Optional[str]] = ContextVar("span_id", default=None)


def add_trace_context(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add trace correlation IDs to log events."""
    trace_id = trace_id_var.get()
    span_id = span_id_var.get()

    if trace_id:
        event_dict["trace_id"] = trace_id
    if span_id:
        event_dict["span_id"] = span_id

    return event_dict


def add_timestamp(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add ISO-format timestamp to log events."""
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def add_service_context(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add service identification to log events."""
    settings = get_settings()
    event_dict["service"] = settings.service_name
    event_dict["version"] = settings.service_version
    event_dict["environment"] = settings.environment
    return event_dict


def drop_sensitive_keys(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Remove sensitive keys from log events."""
    sensitive_keys = {"password", "secret", "token", "api_key", "authorization"}
    
    for key in list(event_dict.keys()):
        if any(s in key.lower() for s in sensitive_keys):
            event_dict[key] = "[REDACTED]"
    
    return event_dict


def configure_logging(
    service_name: str,
    log_level: str = "INFO",
    json_output: bool = True,
) -> None:
    """
    Configure structured logging for a service.
    
    Args:
        service_name: Name of the service for log identification
        log_level: Minimum log level to output
        json_output: Whether to output JSON (True) or human-readable (False)
    """
    # Set up the processor chain
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        add_timestamp,
        add_trace_context,
        add_service_context,
        drop_sensitive_keys,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """
    Get a configured logger instance.
    
    Args:
        name: Optional logger name (defaults to calling module)
    
    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


def bind_trace_context(trace_id: str, span_id: Optional[str] = None) -> None:
    """
    Bind trace context for the current async context.
    
    Args:
        trace_id: The trace correlation ID
        span_id: Optional span ID within the trace
    """
    trace_id_var.set(trace_id)
    if span_id:
        span_id_var.set(span_id)


def get_trace_context() -> tuple[Optional[str], Optional[str]]:
    """Get the current trace context."""
    return trace_id_var.get(), span_id_var.get()


class LogContext:
    """Context manager for scoped logging context."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.token: Optional[Any] = None

    def __enter__(self) -> "LogContext":
        self.token = structlog.contextvars.bind_contextvars(**self.kwargs)
        return self

    def __exit__(self, *args: Any) -> None:
        if self.token:
            structlog.contextvars.unbind_contextvars(*self.kwargs.keys())
