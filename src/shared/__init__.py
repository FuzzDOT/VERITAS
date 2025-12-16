"""
Shared Libraries
================

Common utilities and abstractions used across all services.
"""

from shared.canonical_id import CanonicalId, generate_canonical_id
from shared.hashing import deterministic_hash, hash_content
from shared.errors import (
    RefusalError,
    PreconditionNotMetError,
    ValidationRefusalError,
    InvariantViolationError,
)
from shared.config import Settings, get_settings

__all__ = [
    "CanonicalId",
    "generate_canonical_id",
    "deterministic_hash",
    "hash_content",
    "RefusalError",
    "PreconditionNotMetError",
    "ValidationRefusalError",
    "InvariantViolationError",
    "Settings",
    "get_settings",
]
