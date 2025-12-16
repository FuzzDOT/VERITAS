"""
Vector Store Interface
======================

Provides an abstraction for vector similarity search.
Used for semantic similarity matching of claims and evidence.

EXTENSION_POINT: A3+ will implement concrete vector store (Qdrant, etc.)
Note: This interface is defined but NOT connected to any LLM/AI.
      Vectors will be provided by external embedding services.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class VectorDocument:
    """A document with its vector embedding."""

    id: str
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None


@dataclass
class SearchResult:
    """Result of a vector similarity search."""

    id: str
    score: float
    payload: dict[str, Any]


@dataclass
class VectorSearchQuery:
    """Query parameters for vector search."""

    vector: list[float]
    limit: int = 10
    score_threshold: float = 0.0
    filter: Optional[dict[str, Any]] = None


class VectorStoreInterface(ABC):
    """
    Abstract interface for vector store operations.

    EXTENSION_POINT: A3+ will implement concrete vector store.
    
    Important: This system does NOT include LLM/AI integration.
    Embeddings are assumed to be provided by external services
    and passed into these methods.
    """

    @abstractmethod
    async def upsert(self, documents: list[VectorDocument]) -> list[str]:
        """
        Insert or update vector documents.

        Args:
            documents: Documents with vectors to store

        Returns:
            List of document IDs that were upserted
        """
        pass

    @abstractmethod
    async def search(self, query: VectorSearchQuery) -> list[SearchResult]:
        """
        Search for similar vectors.

        Args:
            query: Search parameters including query vector

        Returns:
            Ranked list of similar documents
        """
        pass

    @abstractmethod
    async def get(self, doc_id: str) -> Optional[VectorDocument]:
        """
        Retrieve a document by ID.

        Args:
            doc_id: Document ID

        Returns:
            The document or None if not found
        """
        pass

    @abstractmethod
    async def delete(self, doc_ids: list[str]) -> int:
        """
        Delete documents by ID.

        Args:
            doc_ids: List of document IDs to delete

        Returns:
            Number of documents deleted
        """
        pass

    @abstractmethod
    async def count(self, filter: Optional[dict[str, Any]] = None) -> int:
        """
        Count documents, optionally filtered.

        Args:
            filter: Optional filter criteria

        Returns:
            Document count
        """
        pass


class NullVectorStore(VectorStoreInterface):
    """
    Null implementation of vector store.

    EXTENSION_POINT: This is replaced with real vector store in A3+.
    """

    def __init__(self) -> None:
        self._documents: dict[str, VectorDocument] = {}

    async def upsert(self, documents: list[VectorDocument]) -> list[str]:
        ids = []
        for doc in documents:
            self._documents[doc.id] = doc
            ids.append(doc.id)
        return ids

    async def search(self, query: VectorSearchQuery) -> list[SearchResult]:
        # EXTENSION_POINT: Real similarity search in A3+
        # This is a placeholder that returns empty results
        results: list[SearchResult] = []

        # Simple cosine similarity placeholder
        def cosine_similarity(a: list[float], b: list[float]) -> float:
            if len(a) != len(b) or len(a) == 0:
                return 0.0
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(x * x for x in b) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)

        for doc in self._documents.values():
            score = cosine_similarity(query.vector, doc.vector)
            if score >= query.score_threshold:
                results.append(SearchResult(
                    id=doc.id,
                    score=score,
                    payload=doc.payload,
                ))

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:query.limit]

    async def get(self, doc_id: str) -> Optional[VectorDocument]:
        return self._documents.get(doc_id)

    async def delete(self, doc_ids: list[str]) -> int:
        count = 0
        for doc_id in doc_ids:
            if doc_id in self._documents:
                del self._documents[doc_id]
                count += 1
        return count

    async def count(self, filter: Optional[dict[str, Any]] = None) -> int:
        # EXTENSION_POINT: Real filtering in A3+
        return len(self._documents)
