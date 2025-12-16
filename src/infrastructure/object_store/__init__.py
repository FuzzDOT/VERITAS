"""
Object Storage Interface
========================

Provides an abstraction over S3-compatible object storage.
All objects are content-addressed using their hash for deduplication.

Design Principles:
- Content-addressable storage for deduplication
- Immutable objects (no overwrites)
- Deterministic object keys
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Optional

from shared.hashing import ContentHash, hash_content


@dataclass(frozen=True)
class ObjectMetadata:
    """Metadata about a stored object."""

    key: str
    content_hash: str
    size_bytes: int
    content_type: str
    created_at: datetime
    metadata: dict[str, str]


@dataclass(frozen=True)
class StoredObject:
    """A retrieved object from storage."""

    key: str
    content: bytes
    metadata: ObjectMetadata


class ObjectStoreInterface(ABC):
    """
    Abstract interface for object storage.

    EXTENSION_POINT: A1+ will implement concrete S3 client.
    This interface defines the contract for object storage operations.
    """

    @abstractmethod
    async def put(
        self,
        content: bytes,
        *,
        prefix: str = "",
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None,
    ) -> ObjectMetadata:
        """
        Store an object with content-addressed key.

        Args:
            content: The content to store
            prefix: Optional key prefix for organization
            content_type: MIME type of the content
            metadata: Optional key-value metadata

        Returns:
            Metadata about the stored object
        """
        pass

    @abstractmethod
    async def get(self, key: str) -> Optional[StoredObject]:
        """
        Retrieve an object by key.

        Args:
            key: The object key

        Returns:
            The stored object or None if not found
        """
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """
        Check if an object exists.

        Args:
            key: The object key

        Returns:
            True if the object exists
        """
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """
        Delete an object.

        Args:
            key: The object key

        Returns:
            True if the object was deleted
        """
        pass

    @abstractmethod
    async def list_objects(
        self,
        prefix: str = "",
        max_keys: int = 1000,
    ) -> AsyncIterator[ObjectMetadata]:
        """
        List objects with optional prefix filter.

        Args:
            prefix: Optional key prefix filter
            max_keys: Maximum number of keys to return

        Yields:
            Object metadata for matching objects
        """
        pass

    @abstractmethod
    async def get_presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
    ) -> Optional[str]:
        """
        Generate a presigned URL for direct access.

        Args:
            key: The object key
            expires_in: URL expiration time in seconds

        Returns:
            The presigned URL or None if object doesn't exist
        """
        pass


def generate_object_key(content: bytes, prefix: str = "") -> str:
    """
    Generate a content-addressed object key.

    Args:
        content: The content to hash
        prefix: Optional key prefix

    Returns:
        A deterministic object key based on content hash
    """
    content_hash = hash_content(content)
    if prefix:
        return f"{prefix.rstrip('/')}/{content_hash.digest}"
    return content_hash.digest


class NullObjectStore(ObjectStoreInterface):
    """
    Null implementation of object storage.

    EXTENSION_POINT: This is replaced with real S3 client in A1+.
    Used for testing and development without actual storage.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[bytes, ObjectMetadata]] = {}

    async def put(
        self,
        content: bytes,
        *,
        prefix: str = "",
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None,
    ) -> ObjectMetadata:
        key = generate_object_key(content, prefix)
        content_hash = hash_content(content)

        obj_metadata = ObjectMetadata(
            key=key,
            content_hash=str(content_hash),
            size_bytes=len(content),
            content_type=content_type,
            created_at=datetime.utcnow(),
            metadata=metadata or {},
        )

        self._store[key] = (content, obj_metadata)
        return obj_metadata

    async def get(self, key: str) -> Optional[StoredObject]:
        if key not in self._store:
            return None
        content, metadata = self._store[key]
        return StoredObject(key=key, content=content, metadata=metadata)

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    async def list_objects(
        self,
        prefix: str = "",
        max_keys: int = 1000,
    ) -> AsyncIterator[ObjectMetadata]:
        count = 0
        for key, (_, metadata) in self._store.items():
            if prefix and not key.startswith(prefix):
                continue
            if count >= max_keys:
                break
            yield metadata
            count += 1

    async def get_presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
    ) -> Optional[str]:
        # EXTENSION_POINT: Real presigned URLs in A1+
        if key in self._store:
            return f"http://localhost:9000/truth-engine/{key}?presigned=true"
        return None
