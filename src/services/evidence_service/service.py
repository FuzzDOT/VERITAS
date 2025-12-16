"""
Evidence Service Implementation
================================

Handles evidence lifecycle with content-addressable storage.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import hash_content
from infrastructure.object_store import ObjectStoreInterface, ObjectMetadata


@dataclass
class Evidence:
    """Internal evidence representation."""

    id: str
    claim_id: str
    content_hash: str
    source_type: str
    source_uri: Optional[str] = None
    object_key: Optional[str] = None
    is_supporting: Optional[bool] = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SubmitEvidenceInput(BaseModel):
    """Input for submitting evidence."""

    claim_id: str
    source_type: str
    content: Optional[bytes] = None
    source_uri: Optional[str] = None
    metadata: dict = {}


class EvidenceServiceInterface(ABC):
    """
    Abstract interface for Evidence Service.

    EXTENSION_POINT: A1+ will implement full evidence management logic.
    """

    @abstractmethod
    async def submit(self, input: SubmitEvidenceInput) -> Evidence:
        """Submit new evidence for a claim."""
        pass

    @abstractmethod
    async def get(self, evidence_id: str) -> Optional[Evidence]:
        """Get evidence by ID."""
        pass

    @abstractmethod
    async def get_content(self, evidence_id: str) -> Optional[bytes]:
        """Get the raw content of evidence."""
        pass

    @abstractmethod
    async def list_for_claim(
        self,
        claim_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Evidence], int]:
        """List all evidence for a claim."""
        pass

    @abstractmethod
    async def exists_by_hash(self, claim_id: str, content_hash: str) -> bool:
        """Check if evidence with given hash exists for a claim."""
        pass


class EvidenceService(EvidenceServiceInterface):
    """
    Evidence Service implementation.

    EXTENSION_POINT: This provides the interface structure.
    A1+ will add object storage integration and full logic.
    """

    def __init__(self, object_store: Optional[ObjectStoreInterface] = None) -> None:
        # EXTENSION_POINT: A1+ will use real object store
        self._object_store = object_store
        self._evidence: dict[str, Evidence] = {}
        self._content: dict[str, bytes] = {}

    async def submit(self, input: SubmitEvidenceInput) -> Evidence:
        """Submit new evidence for a claim."""
        # EXTENSION_POINT: A1+ will implement full submission logic
        evidence_id = str(generate_canonical_id(EntityType.EVIDENCE))

        content = input.content or b""
        content_hash = str(hash_content(content))

        # Store content if object store is available
        object_key = None
        if self._object_store and content:
            obj_meta = await self._object_store.put(
                content,
                prefix=f"evidence/{input.claim_id}",
            )
            object_key = obj_meta.key

        evidence = Evidence(
            id=evidence_id,
            claim_id=input.claim_id,
            content_hash=content_hash,
            source_type=input.source_type,
            source_uri=input.source_uri,
            object_key=object_key,
            metadata=input.metadata,
        )

        self._evidence[evidence_id] = evidence
        self._content[evidence_id] = content
        return evidence

    async def get(self, evidence_id: str) -> Optional[Evidence]:
        """Get evidence by ID."""
        # EXTENSION_POINT: A1+ will query database
        return self._evidence.get(evidence_id)

    async def get_content(self, evidence_id: str) -> Optional[bytes]:
        """Get the raw content of evidence."""
        # EXTENSION_POINT: A1+ will fetch from object store
        evidence = self._evidence.get(evidence_id)
        if not evidence:
            return None

        if self._object_store and evidence.object_key:
            obj = await self._object_store.get(evidence.object_key)
            return obj.content if obj else None

        return self._content.get(evidence_id)

    async def list_for_claim(
        self,
        claim_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Evidence], int]:
        """List all evidence for a claim."""
        # EXTENSION_POINT: A1+ will implement database query
        filtered = [e for e in self._evidence.values() if e.claim_id == claim_id]
        total = len(filtered)
        return filtered[offset : offset + limit], total

    async def exists_by_hash(self, claim_id: str, content_hash: str) -> bool:
        """Check if evidence with given hash exists for a claim."""
        # EXTENSION_POINT: A1+ will implement hash-based lookup
        for evidence in self._evidence.values():
            if evidence.claim_id == claim_id and evidence.content_hash == content_hash:
                return True
        return False
