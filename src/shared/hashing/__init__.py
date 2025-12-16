"""
Deterministic Hashing
=====================

Provides cryptographically secure, deterministic hashing functions for content
integrity verification and deduplication.

Design Principles:
- All hashing operations are deterministic (same input = same output)
- Content is canonicalized before hashing to ensure consistency
- Hash algorithms are explicitly versioned for future upgrades
"""

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Union


class HashAlgorithm(str, Enum):
    """Supported hash algorithms with version tracking."""

    SHA256_V1 = "sha256v1"
    SHA384_V1 = "sha384v1"
    SHA512_V1 = "sha512v1"


@dataclass(frozen=True)
class ContentHash:
    """
    A verified content hash with algorithm metadata.

    Attributes:
        algorithm: The hash algorithm used
        digest: The hex-encoded hash digest
    """

    algorithm: HashAlgorithm
    digest: str

    def __str__(self) -> str:
        """Return the prefixed hash string: {algorithm}:{digest}"""
        return f"{self.algorithm.value}:{self.digest}"

    @classmethod
    def parse(cls, hash_string: str) -> "ContentHash":
        """Parse a hash string back into a ContentHash object."""
        parts = hash_string.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid hash format: {hash_string}")

        alg_str, digest = parts
        try:
            algorithm = HashAlgorithm(alg_str)
        except ValueError:
            raise ValueError(f"Unknown hash algorithm: {alg_str}")

        return cls(algorithm=algorithm, digest=digest)

    def verify(self, content: bytes) -> bool:
        """Verify that content matches this hash."""
        computed = hash_content(content, self.algorithm)
        return computed.digest == self.digest


def _canonicalize_json(obj: Any) -> bytes:
    """
    Canonicalize a JSON-serializable object to deterministic bytes.

    Uses sorted keys and no whitespace to ensure consistent output.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")


def hash_content(
    content: Union[bytes, str, dict, list],
    algorithm: HashAlgorithm = HashAlgorithm.SHA256_V1,
) -> ContentHash:
    """
    Compute a deterministic hash of the given content.

    Args:
        content: The content to hash (bytes, string, or JSON-serializable object)
        algorithm: The hash algorithm to use

    Returns:
        A ContentHash with the computed digest
    """
    # Normalize content to bytes
    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    elif isinstance(content, (dict, list)):
        content_bytes = _canonicalize_json(content)
    else:
        content_bytes = content

    # Select hash function
    if algorithm == HashAlgorithm.SHA256_V1:
        hasher = hashlib.sha256()
    elif algorithm == HashAlgorithm.SHA384_V1:
        hasher = hashlib.sha384()
    elif algorithm == HashAlgorithm.SHA512_V1:
        hasher = hashlib.sha512()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    hasher.update(content_bytes)
    digest = hasher.hexdigest()

    return ContentHash(algorithm=algorithm, digest=digest)


def deterministic_hash(*args: Any, algorithm: HashAlgorithm = HashAlgorithm.SHA256_V1) -> str:
    """
    Compute a deterministic hash of multiple arguments.

    This is useful for creating cache keys or deduplication identifiers
    from multiple values.

    Args:
        *args: Values to include in the hash (will be JSON-canonicalized)
        algorithm: The hash algorithm to use

    Returns:
        The hex-encoded hash digest
    """
    # Create a deterministic representation of all arguments
    canonical = _canonicalize_json(list(args))
    return hash_content(canonical, algorithm).digest
