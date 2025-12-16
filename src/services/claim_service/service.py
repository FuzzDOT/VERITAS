"""
Claim Service Implementation
=============================

Handles claim lifecycle management with full audit trails.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import hash_content
from shared.schemas import TruthStatus, ConfidenceLevel


@dataclass
class Claim:
    """Internal claim representation."""

    id: str
    content: str
    content_hash: str
    status: TruthStatus
    confidence: Optional[ConfidenceLevel] = None
    source: Optional[str] = None
    organization_id: Optional[str] = None
    current_version: int = 1
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CreateClaimInput(BaseModel):
    """Input for creating a claim."""

    content: str
    source: Optional[str] = None
    organization_id: Optional[str] = None
    metadata: dict = {}


class UpdateClaimInput(BaseModel):
    """Input for updating a claim."""

    status: Optional[TruthStatus] = None
    confidence: Optional[ConfidenceLevel] = None
    metadata: Optional[dict] = None


class ClaimServiceInterface(ABC):
    """
    Abstract interface for Claim Service.

    EXTENSION_POINT: A1+ will implement full claim management logic.
    """

    @abstractmethod
    async def create(self, input: CreateClaimInput) -> Claim:
        """Create a new claim."""
        pass

    @abstractmethod
    async def get(self, claim_id: str) -> Optional[Claim]:
        """Get a claim by ID."""
        pass

    @abstractmethod
    async def update(self, claim_id: str, input: UpdateClaimInput) -> Optional[Claim]:
        """Update a claim."""
        pass

    @abstractmethod
    async def list(
        self,
        status: Optional[TruthStatus] = None,
        organization_id: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Claim], int]:
        """List claims with pagination."""
        pass

    @abstractmethod
    async def get_by_content_hash(self, content_hash: str) -> Optional[Claim]:
        """Get a claim by its content hash (for deduplication)."""
        pass


class ClaimService(ClaimServiceInterface):
    """
    Claim Service implementation.

    EXTENSION_POINT: This provides the interface structure.
    A1+ will add database persistence and full business logic.
    """

    def __init__(self) -> None:
        # EXTENSION_POINT: A1+ will inject database session
        self._claims: dict[str, Claim] = {}

    async def create(self, input: CreateClaimInput) -> Claim:
        """Create a new claim."""
        # EXTENSION_POINT: A1+ will implement full creation logic with validation
        claim_id = str(generate_canonical_id(EntityType.CLAIM))
        content_hash = str(hash_content(input.content))

        claim = Claim(
            id=claim_id,
            content=input.content,
            content_hash=content_hash,
            status=TruthStatus.PENDING,
            source=input.source,
            organization_id=input.organization_id,
            metadata=input.metadata,
        )

        self._claims[claim_id] = claim
        return claim

    async def get(self, claim_id: str) -> Optional[Claim]:
        """Get a claim by ID."""
        # EXTENSION_POINT: A1+ will query database
        return self._claims.get(claim_id)

    async def update(self, claim_id: str, input: UpdateClaimInput) -> Optional[Claim]:
        """Update a claim."""
        # EXTENSION_POINT: A1+ will implement proper update with versioning
        claim = self._claims.get(claim_id)
        if not claim:
            return None

        if input.status is not None:
            claim.status = input.status
        if input.confidence is not None:
            claim.confidence = input.confidence
        if input.metadata is not None:
            claim.metadata.update(input.metadata)

        claim.updated_at = datetime.now(timezone.utc)
        return claim

    async def list(
        self,
        status: Optional[TruthStatus] = None,
        organization_id: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Claim], int]:
        """List claims with pagination."""
        # EXTENSION_POINT: A1+ will implement database query
        filtered = list(self._claims.values())

        if status:
            filtered = [c for c in filtered if c.status == status]
        if organization_id:
            filtered = [c for c in filtered if c.organization_id == organization_id]

        total = len(filtered)
        return filtered[offset : offset + limit], total

    async def get_by_content_hash(self, content_hash: str) -> Optional[Claim]:
        """Get a claim by its content hash."""
        # EXTENSION_POINT: A1+ will implement hash-based lookup
        for claim in self._claims.values():
            if claim.content_hash == content_hash:
                return claim
        return None
