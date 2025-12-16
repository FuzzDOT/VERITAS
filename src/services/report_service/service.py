"""
Report Service Implementation
===============================

Handles report generation and storage.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import hash_content
from infrastructure.object_store import ObjectStoreInterface


class ReportType(str, Enum):
    """Types of reports."""

    SUMMARY = "summary"
    DETAILED = "detailed"
    AUDIT_TRAIL = "audit_trail"
    EVIDENCE_SUMMARY = "evidence_summary"
    COMPARISON = "comparison"


class ReportFormat(str, Enum):
    """Output formats for reports."""

    JSON = "json"
    HTML = "html"
    PDF = "pdf"
    CSV = "csv"


class ReportStatus(str, Enum):
    """Status of report generation."""

    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Report:
    """Internal report representation."""

    id: str
    claim_id: Optional[str]
    report_type: ReportType
    format: ReportFormat
    status: ReportStatus
    content_hash: Optional[str] = None
    object_key: Optional[str] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


class GenerateReportInput(BaseModel):
    """Input for generating a report."""

    claim_id: Optional[str] = None
    report_type: ReportType = ReportType.SUMMARY
    format: ReportFormat = ReportFormat.JSON
    options: dict[str, Any] = {}


class ReportGeneratorInterface(ABC):
    """
    Abstract interface for report generators.

    EXTENSION_POINT: A1+ will implement concrete generators.
    """

    @property
    @abstractmethod
    def report_type(self) -> ReportType:
        """Type of report this generator creates."""
        pass

    @property
    @abstractmethod
    def supported_formats(self) -> list[ReportFormat]:
        """Formats this generator supports."""
        pass

    @abstractmethod
    async def generate(
        self,
        claim_id: str,
        format: ReportFormat,
        options: Optional[dict[str, Any]] = None,
    ) -> bytes:
        """Generate report content."""
        pass


class ReportServiceInterface(ABC):
    """
    Abstract interface for Report Service.

    EXTENSION_POINT: A1+ will implement full report logic.
    """

    @abstractmethod
    async def generate(self, input: GenerateReportInput) -> Report:
        """Generate a report."""
        pass

    @abstractmethod
    async def get(self, report_id: str) -> Optional[Report]:
        """Get report metadata."""
        pass

    @abstractmethod
    async def get_content(self, report_id: str) -> Optional[bytes]:
        """Get report content."""
        pass

    @abstractmethod
    async def list_for_claim(
        self,
        claim_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Report], int]:
        """List reports for a claim."""
        pass

    @abstractmethod
    async def get_download_url(
        self,
        report_id: str,
        expires_in: int = 3600,
    ) -> Optional[str]:
        """Get a download URL for a report."""
        pass


class ReportService(ReportServiceInterface):
    """
    Report Service implementation.

    EXTENSION_POINT: This provides the interface structure.
    A1+ will add real report generation and storage.
    """

    def __init__(self, object_store: Optional[ObjectStoreInterface] = None) -> None:
        self._object_store = object_store
        self._reports: dict[str, Report] = {}
        self._content: dict[str, bytes] = {}
        self._generators: dict[ReportType, ReportGeneratorInterface] = {}

    def register_generator(self, generator: ReportGeneratorInterface) -> None:
        """Register a report generator."""
        self._generators[generator.report_type] = generator

    async def generate(self, input: GenerateReportInput) -> Report:
        """Generate a report."""
        report_id = str(generate_canonical_id(EntityType.REPORT))

        # EXTENSION_POINT: A1+ will implement real report generation
        report = Report(
            id=report_id,
            claim_id=input.claim_id,
            report_type=input.report_type,
            format=input.format,
            status=ReportStatus.PENDING,
            metadata=input.options,
        )

        # For A0, create a placeholder report
        placeholder_content = {
            "report_id": report_id,
            "claim_id": input.claim_id,
            "report_type": input.report_type.value,
            "format": input.format.value,
            "message": "EXTENSION_POINT: Real report generation implemented in A1+",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        import json
        content = json.dumps(placeholder_content, indent=2).encode("utf-8")
        content_hash = str(hash_content(content))

        # Store content
        object_key = None
        if self._object_store:
            obj_meta = await self._object_store.put(
                content,
                prefix=f"reports/{input.claim_id or 'general'}",
                content_type="application/json",
            )
            object_key = obj_meta.key

        report.content_hash = content_hash
        report.object_key = object_key
        report.status = ReportStatus.COMPLETED
        report.completed_at = datetime.now(timezone.utc)

        self._reports[report_id] = report
        self._content[report_id] = content

        return report

    async def get(self, report_id: str) -> Optional[Report]:
        """Get report metadata."""
        return self._reports.get(report_id)

    async def get_content(self, report_id: str) -> Optional[bytes]:
        """Get report content."""
        report = self._reports.get(report_id)
        if not report:
            return None

        if self._object_store and report.object_key:
            obj = await self._object_store.get(report.object_key)
            return obj.content if obj else None

        return self._content.get(report_id)

    async def list_for_claim(
        self,
        claim_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Report], int]:
        """List reports for a claim."""
        filtered = [r for r in self._reports.values() if r.claim_id == claim_id]
        filtered.sort(key=lambda r: r.created_at, reverse=True)
        total = len(filtered)
        return filtered[offset : offset + limit], total

    async def get_download_url(
        self,
        report_id: str,
        expires_in: int = 3600,
    ) -> Optional[str]:
        """Get a download URL for a report."""
        report = self._reports.get(report_id)
        if not report or not report.object_key:
            return None

        if self._object_store:
            return await self._object_store.get_presigned_url(report.object_key, expires_in)

        return None
