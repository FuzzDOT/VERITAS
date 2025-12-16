"""
Truth Versioning Service Implementation
=========================================

Manages immutable truth version snapshots.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import deterministic_hash
from shared.schemas import TruthStatus, ConfidenceLevel


@dataclass
class TruthVersion:
    """Internal truth version representation."""

    id: str
    claim_id: str
    version_number: int
    status: TruthStatus
    confidence: Optional[ConfidenceLevel]
    reasoning_trace_id: Optional[str]
    state_hash: str
    previous_version_id: Optional[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CreateVersionInput(BaseModel):
    """Input for creating a truth version."""

    claim_id: str
    status: TruthStatus
    confidence: Optional[ConfidenceLevel] = None
    reasoning_trace_id: Optional[str] = None
    metadata: dict[str, Any] = {}


class TruthVersioningServiceInterface(ABC):
    """
    Abstract interface for Truth Versioning Service.

    EXTENSION_POINT: A1+ will implement full versioning logic.
    """

    @abstractmethod
    async def create_version(self, input: CreateVersionInput) -> TruthVersion:
        """Create a new truth version."""
        pass

    @abstractmethod
    async def get_version(self, version_id: str) -> Optional[TruthVersion]:
        """Get a specific version."""
        pass

    @abstractmethod
    async def get_latest(self, claim_id: str) -> Optional[TruthVersion]:
        """Get the latest version for a claim."""
        pass

    @abstractmethod
    async def get_at_version(
        self,
        claim_id: str,
        version_number: int,
    ) -> Optional[TruthVersion]:
        """Get a specific version number for a claim."""
        pass

    @abstractmethod
    async def get_history(
        self,
        claim_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TruthVersion], int]:
        """Get version history for a claim."""
        pass

    @abstractmethod
    async def compare_versions(
        self,
        version_id_a: str,
        version_id_b: str,
    ) -> dict[str, Any]:
        """Compare two versions."""
        pass


class TruthVersioningService(TruthVersioningServiceInterface):
    """
    Truth Versioning Service implementation.

    EXTENSION_POINT: This provides the interface structure.
    A1+ will add database persistence and diff logic.
    """

    def __init__(self) -> None:
        self._versions: dict[str, TruthVersion] = {}
        self._claim_versions: dict[str, list[str]] = {}  # claim_id -> version_ids

    def _compute_state_hash(
        self,
        claim_id: str,
        status: TruthStatus,
        confidence: Optional[ConfidenceLevel],
        version_number: int,
    ) -> str:
        """Compute deterministic state hash."""
        return deterministic_hash(
            claim_id,
            status.value,
            confidence.value if confidence else None,
            version_number,
        )

    async def create_version(self, input: CreateVersionInput) -> TruthVersion:
        """Create a new truth version."""
        version_id = str(generate_canonical_id(EntityType.TRUTH_VERSION))

        # Get previous version info
        claim_versions = self._claim_versions.get(input.claim_id, [])
        version_number = len(claim_versions) + 1
        previous_version_id = claim_versions[-1] if claim_versions else None

        # Compute state hash
        state_hash = self._compute_state_hash(
            input.claim_id,
            input.status,
            input.confidence,
            version_number,
        )

        version = TruthVersion(
            id=version_id,
            claim_id=input.claim_id,
            version_number=version_number,
            status=input.status,
            confidence=input.confidence,
            reasoning_trace_id=input.reasoning_trace_id,
            state_hash=state_hash,
            previous_version_id=previous_version_id,
            metadata=input.metadata,
        )

        self._versions[version_id] = version

        if input.claim_id not in self._claim_versions:
            self._claim_versions[input.claim_id] = []
        self._claim_versions[input.claim_id].append(version_id)

        return version

    async def get_version(self, version_id: str) -> Optional[TruthVersion]:
        """Get a specific version."""
        return self._versions.get(version_id)

    async def get_latest(self, claim_id: str) -> Optional[TruthVersion]:
        """Get the latest version for a claim."""
        version_ids = self._claim_versions.get(claim_id, [])
        if not version_ids:
            return None
        return self._versions.get(version_ids[-1])

    async def get_at_version(
        self,
        claim_id: str,
        version_number: int,
    ) -> Optional[TruthVersion]:
        """Get a specific version number for a claim."""
        version_ids = self._claim_versions.get(claim_id, [])
        if version_number < 1 or version_number > len(version_ids):
            return None
        return self._versions.get(version_ids[version_number - 1])

    async def get_history(
        self,
        claim_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TruthVersion], int]:
        """Get version history for a claim."""
        version_ids = self._claim_versions.get(claim_id, [])
        total = len(version_ids)

        # Return in reverse chronological order
        version_ids = list(reversed(version_ids))
        selected_ids = version_ids[offset : offset + limit]

        versions = [self._versions[vid] for vid in selected_ids if vid in self._versions]
        return versions, total

    async def compare_versions(
        self,
        version_id_a: str,
        version_id_b: str,
    ) -> dict[str, Any]:
        """Compare two versions."""
        # EXTENSION_POINT: A1+ will implement proper diff logic
        version_a = self._versions.get(version_id_a)
        version_b = self._versions.get(version_id_b)

        if not version_a or not version_b:
            return {"error": "Version not found"}

        return {
            "version_a": {
                "id": version_a.id,
                "version_number": version_a.version_number,
                "status": version_a.status.value,
                "confidence": version_a.confidence.value if version_a.confidence else None,
            },
            "version_b": {
                "id": version_b.id,
                "version_number": version_b.version_number,
                "status": version_b.status.value,
                "confidence": version_b.confidence.value if version_b.confidence else None,
            },
            "changes": {
                "status_changed": version_a.status != version_b.status,
                "confidence_changed": version_a.confidence != version_b.confidence,
            },
        }
