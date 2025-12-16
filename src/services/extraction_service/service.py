"""
Extraction Service Implementation
==================================

Handles data extraction from evidence with versioned extractors.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import hash_content


class ExtractionType(str, Enum):
    """Types of data extraction."""

    FINANCIAL_STATEMENT = "financial_statement"
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    RATIO_ANALYSIS = "ratio_analysis"
    TEXT_CONTENT = "text_content"
    METADATA = "metadata"
    CUSTOM = "custom"


@dataclass
class Extraction:
    """Internal extraction representation."""

    id: str
    evidence_id: str
    extraction_type: ExtractionType
    content_hash: str
    extracted_data: dict[str, Any]
    extractor_version: str
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ExtractDataInput(BaseModel):
    """Input for extracting data from evidence."""

    evidence_id: str
    extraction_type: ExtractionType
    content: bytes
    options: dict = {}


class ExtractorInterface(ABC):
    """
    Abstract interface for data extractors.

    EXTENSION_POINT: A1+ will implement concrete extractors.
    Each extractor must be deterministic - same input yields same output.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of this extractor."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Version of this extractor."""
        pass

    @property
    @abstractmethod
    def extraction_type(self) -> ExtractionType:
        """Type of extraction this extractor performs."""
        pass

    @abstractmethod
    async def extract(
        self,
        content: bytes,
        options: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Extract structured data from content.

        This method MUST be deterministic - the same content and options
        must always produce the same extracted data.

        Args:
            content: Raw content to extract from
            options: Optional extraction options

        Returns:
            Extracted structured data
        """
        pass

    @abstractmethod
    async def validate(self, content: bytes) -> bool:
        """Validate that content can be processed by this extractor."""
        pass


class ExtractionServiceInterface(ABC):
    """
    Abstract interface for Extraction Service.

    EXTENSION_POINT: A1+ will implement full extraction logic.
    """

    @abstractmethod
    async def extract(self, input: ExtractDataInput) -> Extraction:
        """Extract data from evidence content."""
        pass

    @abstractmethod
    async def get(self, extraction_id: str) -> Optional[Extraction]:
        """Get extraction by ID."""
        pass

    @abstractmethod
    async def list_for_evidence(
        self,
        evidence_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Extraction], int]:
        """List all extractions for an evidence item."""
        pass

    @abstractmethod
    def register_extractor(self, extractor: ExtractorInterface) -> None:
        """Register an extractor."""
        pass


class ExtractionService(ExtractionServiceInterface):
    """
    Extraction Service implementation.

    EXTENSION_POINT: This provides the interface structure.
    A1+ will add concrete extractors for financial documents.
    """

    EXTRACTOR_VERSION = "0.1.0"

    def __init__(self) -> None:
        self._extractions: dict[str, Extraction] = {}
        self._extractors: dict[ExtractionType, ExtractorInterface] = {}

    def register_extractor(self, extractor: ExtractorInterface) -> None:
        """Register an extractor."""
        self._extractors[extractor.extraction_type] = extractor

    async def extract(self, input: ExtractDataInput) -> Extraction:
        """Extract data from evidence content."""
        # EXTENSION_POINT: A1+ will implement real extraction
        extraction_id = str(generate_canonical_id(EntityType.EXTRACTION))

        # For A0, create a placeholder extraction
        extracted_data: dict[str, Any] = {
            "extraction_type": input.extraction_type.value,
            "status": "pending",
            "message": "EXTENSION_POINT: Real extraction implemented in A1+",
        }

        content_hash = str(hash_content(input.content))

        extraction = Extraction(
            id=extraction_id,
            evidence_id=input.evidence_id,
            extraction_type=input.extraction_type,
            content_hash=content_hash,
            extracted_data=extracted_data,
            extractor_version=self.EXTRACTOR_VERSION,
        )

        self._extractions[extraction_id] = extraction
        return extraction

    async def get(self, extraction_id: str) -> Optional[Extraction]:
        """Get extraction by ID."""
        return self._extractions.get(extraction_id)

    async def list_for_evidence(
        self,
        evidence_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Extraction], int]:
        """List all extractions for an evidence item."""
        filtered = [e for e in self._extractions.values() if e.evidence_id == evidence_id]
        total = len(filtered)
        return filtered[offset : offset + limit], total
