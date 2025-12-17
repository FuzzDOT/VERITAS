"""
Report Service - Storage Layer
================================

Provides storage operations for reports:
- ReportStore: Postgres CRUD for report metadata
- ArtifactStore: Object storage for HTML/PDF artifacts

All operations are designed for deterministic, reproducible behavior.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.canonical_id import EntityType, generate_canonical_id
from infrastructure.object_store import ObjectStoreInterface, ObjectMetadata
from infrastructure.postgres.models import ReportRecord

from .schemas import (
    ReportMetadata,
    ReportStatus,
    REPORT_SERVICE_VERSION,
)


# =============================================================================
# Report Store
# =============================================================================


class ReportStore:
    """
    Storage operations for report metadata in Postgres.
    
    Handles idempotency through unique constraint on truth_version_id + renderer_version.
    """
    
    def __init__(self, session: AsyncSession):
        self._session = session
    
    async def store(self, metadata: ReportMetadata) -> str:
        """
        Store report metadata.
        
        Returns the report_id.
        """
        record = ReportRecord(
            id=metadata.report_id,
            truth_version_id=metadata.truth_version_id,
            html_hash=metadata.html_hash,
            pdf_hash=metadata.pdf_hash,
            html_uri=metadata.html_uri,
            pdf_uri=metadata.pdf_uri,
            renderer_version=metadata.renderer_version,
            pdf_renderer_version=metadata.pdf_renderer_version,
            report_service_version=metadata.report_service_version,
            status=metadata.status.value,
        )
        
        self._session.add(record)
        await self._session.flush()
        
        return metadata.report_id
    
    async def get(self, report_id: str) -> Optional[ReportMetadata]:
        """Get report metadata by ID."""
        stmt = select(ReportRecord).where(ReportRecord.id == report_id)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._to_metadata(record)
    
    async def get_by_truth_version(
        self,
        truth_version_id: str,
        renderer_version: Optional[str] = None,
    ) -> Optional[ReportMetadata]:
        """
        Get report for a truth version.
        
        If renderer_version is provided, looks for exact match (for idempotency).
        Otherwise returns the most recent report.
        """
        if renderer_version:
            stmt = select(ReportRecord).where(
                ReportRecord.truth_version_id == truth_version_id,
                ReportRecord.renderer_version == renderer_version,
            )
        else:
            stmt = (
                select(ReportRecord)
                .where(ReportRecord.truth_version_id == truth_version_id)
                .order_by(ReportRecord.created_at.desc())
                .limit(1)
            )
        
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._to_metadata(record)
    
    async def list_for_truth_version(
        self,
        truth_version_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ReportMetadata], int]:
        """List all reports for a truth version."""
        # Count total
        count_stmt = select(ReportRecord).where(
            ReportRecord.truth_version_id == truth_version_id
        )
        count_result = await self._session.execute(count_stmt)
        total = len(count_result.all())
        
        # Fetch page
        stmt = (
            select(ReportRecord)
            .where(ReportRecord.truth_version_id == truth_version_id)
            .order_by(ReportRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        records = result.scalars().all()
        
        return [self._to_metadata(r) for r in records], total
    
    async def find_existing(
        self,
        truth_version_id: str,
        renderer_version: str,
    ) -> Optional[ReportMetadata]:
        """
        Find existing report for idempotency check.
        
        If a report exists for the same truth_version_id and renderer_version,
        return it instead of generating a new one.
        """
        stmt = select(ReportRecord).where(
            ReportRecord.truth_version_id == truth_version_id,
            ReportRecord.renderer_version == renderer_version,
            ReportRecord.status == "completed",
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._to_metadata(record)
    
    def _to_metadata(self, record: ReportRecord) -> ReportMetadata:
        """Convert database record to schema."""
        return ReportMetadata(
            report_id=record.id,
            truth_version_id=record.truth_version_id,
            created_at=record.created_at,
            html_hash=record.html_hash,
            pdf_hash=record.pdf_hash,
            html_uri=record.html_uri,
            pdf_uri=record.pdf_uri,
            renderer_version=record.renderer_version,
            pdf_renderer_version=record.pdf_renderer_version,
            report_service_version=record.report_service_version,
            status=ReportStatus(record.status),
        )


# =============================================================================
# Artifact Store
# =============================================================================


class ArtifactStore:
    """
    Storage operations for report artifacts (HTML, PDF) in object storage.
    
    Uses content-addressable storage for deduplication and integrity.
    """
    
    def __init__(self, object_store: ObjectStoreInterface):
        self._object_store = object_store
    
    async def store_html(
        self,
        report_id: str,
        truth_version_id: str,
        html_content: bytes,
    ) -> tuple[str, str]:
        """
        Store HTML artifact.
        
        Returns (uri, content_hash).
        """
        metadata = await self._object_store.put(
            html_content,
            prefix=f"reports/{truth_version_id}",
            content_type="text/html; charset=utf-8",
            metadata={
                "report_id": report_id,
                "truth_version_id": truth_version_id,
                "artifact_type": "html",
            },
        )
        
        return self._to_uri(metadata.key), metadata.content_hash
    
    async def store_pdf(
        self,
        report_id: str,
        truth_version_id: str,
        pdf_content: bytes,
    ) -> tuple[str, str]:
        """
        Store PDF artifact.
        
        Returns (uri, content_hash).
        """
        metadata = await self._object_store.put(
            pdf_content,
            prefix=f"reports/{truth_version_id}",
            content_type="application/pdf",
            metadata={
                "report_id": report_id,
                "truth_version_id": truth_version_id,
                "artifact_type": "pdf",
            },
        )
        
        return self._to_uri(metadata.key), metadata.content_hash
    
    async def get_html(self, html_uri: str) -> Optional[bytes]:
        """Retrieve HTML content."""
        key = self._from_uri(html_uri)
        obj = await self._object_store.get(key)
        return obj.content if obj else None
    
    async def get_pdf(self, pdf_uri: str) -> Optional[bytes]:
        """Retrieve PDF content."""
        key = self._from_uri(pdf_uri)
        obj = await self._object_store.get(key)
        return obj.content if obj else None
    
    async def get_presigned_url(
        self,
        uri: str,
        expires_in: int = 3600,
    ) -> Optional[str]:
        """Get a presigned download URL."""
        key = self._from_uri(uri)
        return await self._object_store.get_presigned_url(key, expires_in)
    
    def _to_uri(self, key: str) -> str:
        """Convert object key to URI."""
        return f"s3://reports/{key}"
    
    def _from_uri(self, uri: str) -> str:
        """Extract object key from URI."""
        if uri.startswith("s3://reports/"):
            return uri[len("s3://reports/"):]
        return uri


# =============================================================================
# Factory Functions
# =============================================================================


def create_report_store(session: AsyncSession) -> ReportStore:
    """Create a ReportStore instance."""
    return ReportStore(session)


def create_artifact_store(object_store: ObjectStoreInterface) -> ArtifactStore:
    """Create an ArtifactStore instance."""
    return ArtifactStore(object_store)
