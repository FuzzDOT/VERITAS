"""
Canonical ID Generation
=======================

Provides deterministic, globally unique identifiers for all entities in the system.
Uses ULID (Universally Unique Lexicographically Sortable Identifier) for time-ordered,
sortable IDs that are URL-safe and database-friendly.

Design Principles:
- IDs are deterministic given the same timestamp and randomness source
- IDs are lexicographically sortable by creation time
- IDs encode the entity type for runtime type safety
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from ulid import ULID


class EntityType(str, Enum):
    """
    Enumeration of all entity types in the Truth Engine.
    Used as a prefix in canonical IDs for type safety.
    """

    CLAIM = "CLM"
    EVIDENCE = "EVD"
    EXTRACTION = "EXT"
    REASONING_TRACE = "RSN"
    TRUTH_VERSION = "TRV"
    AUDIT_ENTRY = "AUD"
    REPORT = "RPT"
    WORKFLOW = "WFL"
    TASK = "TSK"
    USER = "USR"
    ORGANIZATION = "ORG"
    DOCUMENT = "DOC"


@dataclass(frozen=True)
class CanonicalId:
    """
    A canonical identifier that combines entity type with ULID.

    Attributes:
        entity_type: The type of entity this ID represents
        ulid: The underlying ULID value
    """

    entity_type: EntityType
    ulid: ULID

    def __str__(self) -> str:
        """Return the string representation: {TYPE}_{ULID}"""
        return f"{self.entity_type.value}_{self.ulid}"

    def __repr__(self) -> str:
        return f"CanonicalId({self.entity_type.value}_{self.ulid})"

    @property
    def timestamp(self) -> datetime:
        """Extract the creation timestamp from the ULID."""
        return self.ulid.datetime

    @classmethod
    def parse(cls, id_string: str) -> "CanonicalId":
        """
        Parse a canonical ID string back into a CanonicalId object.

        Args:
            id_string: String in format {TYPE}_{ULID}

        Returns:
            Parsed CanonicalId

        Raises:
            ValueError: If the string format is invalid
        """
        parts = id_string.split("_", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid canonical ID format: {id_string}")

        type_str, ulid_str = parts
        try:
            entity_type = EntityType(type_str)
        except ValueError:
            raise ValueError(f"Unknown entity type: {type_str}")

        try:
            ulid = ULID.from_str(ulid_str)
        except Exception as e:
            raise ValueError(f"Invalid ULID: {ulid_str}") from e

        return cls(entity_type=entity_type, ulid=ulid)


def generate_canonical_id(
    entity_type: EntityType,
    timestamp: Optional[datetime] = None,
) -> CanonicalId:
    """
    Generate a new canonical ID for the given entity type.

    Args:
        entity_type: The type of entity to generate an ID for
        timestamp: Optional timestamp to use (defaults to now)

    Returns:
        A new CanonicalId

    Note:
        For deterministic replay, provide the same timestamp and ensure
        the ULID randomness source is seeded consistently.
    """
    # EXTENSION_POINT: In A1+, this will accept a deterministic randomness source
    # for fully reproducible ID generation during replay scenarios.
    if timestamp is not None:
        ulid = ULID.from_datetime(timestamp)
    else:
        ulid = ULID()

    return CanonicalId(entity_type=entity_type, ulid=ulid)
