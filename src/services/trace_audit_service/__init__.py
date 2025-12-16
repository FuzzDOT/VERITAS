"""
Trace & Audit Service
=====================

Provides comprehensive audit logging for all system operations.
All audit entries are immutable and tamper-evident.
"""

from services.trace_audit_service.app import create_app
from services.trace_audit_service.service import TraceAuditService

__all__ = ["create_app", "TraceAuditService"]
