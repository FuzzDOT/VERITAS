"""
PostgreSQL Database Infrastructure
===================================

Provides database connection, session management, and migrations.
"""

from infrastructure.postgres.models import (
    Base,
    Claim,
    Evidence,
    Extraction,
    ReasoningTrace,
    TruthVersion,
    AuditEntry,
    Workflow,
    Report,
)
from infrastructure.postgres.session import (
    get_engine,
    get_session,
    get_session_factory,
    init_database,
)

__all__ = [
    "Base",
    "Claim",
    "Evidence",
    "Extraction",
    "ReasoningTrace",
    "TruthVersion",
    "AuditEntry",
    "Workflow",
    "Report",
    "get_engine",
    "get_session",
    "get_session_factory",
    "init_database",
]
