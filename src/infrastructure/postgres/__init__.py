"""
PostgreSQL Database Infrastructure
===================================

Provides database connection, session management, and migrations.

Includes:
- Core domain models (Claim, Evidence, etc.)
- Financial fact persistence (FinancialFactRecord, EvidencePassageRecord)
- Fact/Passage stores for extraction service integration
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
    FinancialFactRecord,
    EvidencePassageRecord,
    FactClaimLink,
)
from infrastructure.postgres.session import (
    get_engine,
    get_session,
    get_session_factory,
    init_database,
)
from infrastructure.postgres.fact_store import (
    PostgresFactStore,
    PostgresPassageStore,
)

__all__ = [
    # Base
    "Base",
    # Domain models
    "Claim",
    "Evidence",
    "Extraction",
    "ReasoningTrace",
    "TruthVersion",
    "AuditEntry",
    "Workflow",
    "Report",
    # Fact persistence models
    "FinancialFactRecord",
    "EvidencePassageRecord",
    "FactClaimLink",
    # Session management
    "get_engine",
    "get_session",
    "get_session_factory",
    "init_database",
    # Fact stores
    "PostgresFactStore",
    "PostgresPassageStore",
]
