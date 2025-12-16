"""
Extraction Service
==================

Deterministic fact extraction from financial evidence.
All extractions are versioned and traceable.

Key Components:
- ExtractionService: Main service for fact extraction
- XBRLExtractor: XBRL parsing pipeline (HIGH confidence)
- TableExtractor: Table parsing pipeline (MEDIUM confidence)
- TextExtractor: Text pattern extraction (LOW confidence)
- MacroExtractor: Macroeconomic data extraction (HIGH confidence)
- FactStore: Fact storage with deduplication and indexing
- PassageStore: Passage storage with deduplication
"""

from services.extraction_service.app import create_app, app, get_service, reset_service
from services.extraction_service.service_impl import (
    ExtractionService,
    XBRLExtractor,
    TableExtractor,
    TextExtractor,
    MacroExtractor,
    FactStore,
    PassageStore,
    ExtractionPipeline,
)
from services.extraction_service.schemas import (
    # Enums
    ExtractionMethod,
    ExtractionJobStatus,
    ExtractionRefusalCode,
    FactConfidence,
    FactUnit,
    # Location Models
    XBRLLocation,
    TableLocation,
    TextLocation,
    MacroLocation,
    # Core Models
    FactProvenance,
    FinancialFact,
    EvidencePassage,
    ExtractionJob,
    ExtractionJobRequest,
    ExtractionJobResult,
    # Constants
    XBRL_FACT_MAPPINGS,
    EXTRACTION_METHOD_CONFIDENCE,
    FACT_CATEGORY_MAPPING,
    SUPPORTED_FACT_TYPES,
    DEFAULT_MIN_CONFIDENCE,
)

__all__ = [
    # App
    "create_app",
    "app",
    "get_service",
    "reset_service",
    # Service & Pipelines
    "ExtractionService",
    "ExtractionPipeline",
    "XBRLExtractor",
    "TableExtractor",
    "TextExtractor",
    "MacroExtractor",
    # Stores
    "FactStore",
    "PassageStore",
    # Enums
    "ExtractionMethod",
    "ExtractionJobStatus",
    "ExtractionRefusalCode",
    "FactConfidence",
    "FactUnit",
    # Location Models
    "XBRLLocation",
    "TableLocation",
    "TextLocation",
    "MacroLocation",
    # Core Models
    "FactProvenance",
    "FinancialFact",
    "EvidencePassage",
    "ExtractionJob",
    "ExtractionJobRequest",
    "ExtractionJobResult",
    # Constants
    "XBRL_FACT_MAPPINGS",
    "EXTRACTION_METHOD_CONFIDENCE",
    "FACT_CATEGORY_MAPPING",
    "SUPPORTED_FACT_TYPES",
    "DEFAULT_MIN_CONFIDENCE",
]

