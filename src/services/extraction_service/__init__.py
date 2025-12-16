"""
Extraction Service
==================

Extracts structured data from evidence documents.
All extractions are deterministic and versioned.
"""

from services.extraction_service.app import create_app
from services.extraction_service.service import ExtractionService

__all__ = ["create_app", "ExtractionService"]
