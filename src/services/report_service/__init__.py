"""
Report Service
==============

Generates formatted reports of truth determinations.
All reports are content-addressed and versioned.

A9 Implementation:
- Deterministic HTML/PDF report generation from TruthVersions
- Canonical formatting with stable ordering
- Content-addressed artifact storage
- Idempotent generation
"""

from services.report_service.app import create_app
from services.report_service.schemas import (
    REPORT_SERVICE_VERSION,
    HTML_RENDERER_VERSION,
    PDF_RENDERER_VERSION,
    ReportStatus,
    ReportType,
    ReportMetadata,
    ReportContent,
    EvidenceProvenance,
    FactProvenance,
    GenerateReportRequest,
    GenerateReportResponse,
)
from services.report_service.stores import ReportStore, ArtifactStore
from services.report_service.generator import (
    ReportGenerator,
    ReportContentBuilder,
    HTMLRenderer,
    PDFRenderer,
)
from services.report_service.routes import router, generate_report_internal

__all__ = [
    # App
    "create_app",
    # Constants
    "REPORT_SERVICE_VERSION",
    "HTML_RENDERER_VERSION",
    "PDF_RENDERER_VERSION",
    # Enums
    "ReportStatus",
    "ReportType",
    # Schemas
    "ReportMetadata",
    "ReportContent",
    "EvidenceProvenance",
    "FactProvenance",
    "GenerateReportRequest",
    "GenerateReportResponse",
    # Stores
    "ReportStore",
    "ArtifactStore",
    # Generator
    "ReportGenerator",
    "ReportContentBuilder",
    "HTMLRenderer",
    "PDFRenderer",
    # Routes
    "router",
    "generate_report_internal",
]
