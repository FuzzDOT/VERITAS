"""
Trace & Audit Service Implementation
======================================

Handles immutable audit logging with tamper detection.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import deterministic_hash


class AuditAction(str, Enum):
    """Types of auditable actions."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    READ = "read"
    SUBMIT = "submit"
    PROCESS = "process"
    VERIFY = "verify"
    APPROVE = "approve"
    REJECT = "reject"
    EXPORT = "export"


@dataclass
class AuditEntry:
    """Internal audit entry representation."""

    id: str
    trace_id: str
    span_id: Optional[str]
    operation: str
    entity_type: str
    entity_id: str
    action: AuditAction
    actor_id: Optional[str]
    organization_id: Optional[str]
    before_state: Optional[dict[str, Any]]
    after_state: Optional[dict[str, Any]]
    metadata: dict[str, Any]
    entry_hash: str  # Hash of entry for tamper detection
    previous_hash: Optional[str]  # Chain link for integrity
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CreateAuditEntryInput(BaseModel):
    """Input for creating an audit entry."""

    trace_id: str
    span_id: Optional[str] = None
    operation: str
    entity_type: str
    entity_id: str
    action: AuditAction
    actor_id: Optional[str] = None
    organization_id: Optional[str] = None
    before_state: Optional[dict[str, Any]] = None
    after_state: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = {}


class AuditQuery(BaseModel):
    """Query parameters for audit log search."""

    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    trace_id: Optional[str] = None
    actor_id: Optional[str] = None
    organization_id: Optional[str] = None
    action: Optional[AuditAction] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class TraceAuditServiceInterface(ABC):
    """
    Abstract interface for Trace & Audit Service.

    EXTENSION_POINT: A1+ will implement full audit logic.
    """

    @abstractmethod
    async def record(self, input: CreateAuditEntryInput) -> AuditEntry:
        """Record an audit entry."""
        pass

    @abstractmethod
    async def get(self, entry_id: str) -> Optional[AuditEntry]:
        """Get an audit entry by ID."""
        pass

    @abstractmethod
    async def query(
        self,
        query: AuditQuery,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[AuditEntry], int]:
        """Query audit entries."""
        pass

    @abstractmethod
    async def get_entity_trail(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[AuditEntry]:
        """Get complete audit trail for an entity."""
        pass

    @abstractmethod
    async def verify_integrity(
        self,
        start_id: Optional[str] = None,
        end_id: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Verify hash chain integrity.

        Returns:
            Tuple of (is_valid, first_invalid_entry_id)
        """
        pass


class TraceAuditService(TraceAuditServiceInterface):
    """
    Trace & Audit Service implementation.

    EXTENSION_POINT: This provides the interface structure.
    A1+ will add database persistence and chain verification.
    """

    def __init__(self) -> None:
        self._entries: dict[str, AuditEntry] = {}
        self._chain: list[str] = []  # Ordered entry IDs for chain
        self._last_hash: Optional[str] = None

    def _compute_entry_hash(
        self,
        entry_data: dict[str, Any],
        previous_hash: Optional[str],
    ) -> str:
        """Compute hash for an entry including chain link."""
        return deterministic_hash(entry_data, previous_hash or "genesis")

    async def record(self, input: CreateAuditEntryInput) -> AuditEntry:
        """Record an audit entry."""
        entry_id = str(generate_canonical_id(EntityType.AUDIT_ENTRY))

        # Prepare entry data for hashing
        entry_data = {
            "id": entry_id,
            "trace_id": input.trace_id,
            "operation": input.operation,
            "entity_type": input.entity_type,
            "entity_id": input.entity_id,
            "action": input.action.value,
            "before_state": input.before_state,
            "after_state": input.after_state,
        }

        # Compute hash with chain link
        entry_hash = self._compute_entry_hash(entry_data, self._last_hash)

        entry = AuditEntry(
            id=entry_id,
            trace_id=input.trace_id,
            span_id=input.span_id,
            operation=input.operation,
            entity_type=input.entity_type,
            entity_id=input.entity_id,
            action=input.action,
            actor_id=input.actor_id,
            organization_id=input.organization_id,
            before_state=input.before_state,
            after_state=input.after_state,
            metadata=input.metadata,
            entry_hash=entry_hash,
            previous_hash=self._last_hash,
        )

        self._entries[entry_id] = entry
        self._chain.append(entry_id)
        self._last_hash = entry_hash

        return entry

    async def get(self, entry_id: str) -> Optional[AuditEntry]:
        """Get an audit entry by ID."""
        return self._entries.get(entry_id)

    async def query(
        self,
        query: AuditQuery,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[AuditEntry], int]:
        """Query audit entries."""
        # EXTENSION_POINT: A1+ will implement efficient querying
        filtered = list(self._entries.values())

        if query.entity_type:
            filtered = [e for e in filtered if e.entity_type == query.entity_type]
        if query.entity_id:
            filtered = [e for e in filtered if e.entity_id == query.entity_id]
        if query.trace_id:
            filtered = [e for e in filtered if e.trace_id == query.trace_id]
        if query.actor_id:
            filtered = [e for e in filtered if e.actor_id == query.actor_id]
        if query.action:
            filtered = [e for e in filtered if e.action == query.action]
        if query.start_time:
            filtered = [e for e in filtered if e.created_at >= query.start_time]
        if query.end_time:
            filtered = [e for e in filtered if e.created_at <= query.end_time]

        # Sort by creation time
        filtered.sort(key=lambda e: e.created_at, reverse=True)

        total = len(filtered)
        return filtered[offset : offset + limit], total

    async def get_entity_trail(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[AuditEntry]:
        """Get complete audit trail for an entity."""
        trail = [
            e for e in self._entries.values()
            if e.entity_type == entity_type and e.entity_id == entity_id
        ]
        trail.sort(key=lambda e: e.created_at)
        return trail

    async def verify_integrity(
        self,
        start_id: Optional[str] = None,
        end_id: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """Verify hash chain integrity."""
        # EXTENSION_POINT: A1+ will implement full chain verification
        previous_hash: Optional[str] = None

        for entry_id in self._chain:
            entry = self._entries[entry_id]

            # Verify chain link
            if entry.previous_hash != previous_hash:
                return False, entry_id

            # Verify entry hash
            entry_data = {
                "id": entry.id,
                "trace_id": entry.trace_id,
                "operation": entry.operation,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "action": entry.action.value,
                "before_state": entry.before_state,
                "after_state": entry.after_state,
            }
            expected_hash = self._compute_entry_hash(entry_data, previous_hash)

            if entry.entry_hash != expected_hash:
                return False, entry_id

            previous_hash = entry.entry_hash

        return True, None
