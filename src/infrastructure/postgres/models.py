"""
PostgreSQL Database Models
==========================

SQLAlchemy models for the Truth Engine database.
These are the core persistent entities of the system.

Note: A0 defines the schema structure. Domain logic will be added in A1+.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class TimestampMixin:
    """Mixin for models with timestamp tracking."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Claim(TimestampMixin, Base):
    """
    A claim is a statement that can be verified or refuted.

    This is the central entity in the Truth Engine. Claims flow through
    the system, accumulating evidence and reasoning until a truth
    determination is made.
    """

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    confidence: Mapped[str] = mapped_column(String(20), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    organization_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)

    # Relationships
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="claim", lazy="selectin")
    versions: Mapped[list["TruthVersion"]] = relationship(back_populates="claim", lazy="selectin")

    __table_args__ = (
        Index("ix_claims_status_org", "status", "organization_id"),
    )


class Evidence(TimestampMixin, Base):
    """
    Evidence supporting or refuting a claim.

    Evidence is immutable once created. Each piece of evidence
    has a content hash for deduplication and integrity verification.
    """

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    object_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    is_supporting: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Relationships
    claim: Mapped["Claim"] = relationship(back_populates="evidence")

    __table_args__ = (
        UniqueConstraint("claim_id", "content_hash", name="uq_evidence_claim_hash"),
    )


class Extraction(TimestampMixin, Base):
    """
    Extracted data from evidence documents.

    Extractions are the structured data pulled from raw evidence.
    Each extraction is linked to its source evidence.
    """

    __tablename__ = "extractions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extraction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    extracted_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(50), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


class ReasoningTrace(TimestampMixin, Base):
    """
    A complete trace of a reasoning operation.

    Reasoning traces are immutable records of the reasoning process,
    enabling full auditability and reproducibility.
    """

    __tablename__ = "reasoning_traces"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    input_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    conclusion: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    reasoning_steps: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    engine_version: Mapped[str] = mapped_column(String(50), nullable=False)


class TruthVersion(TimestampMixin, Base):
    """
    A versioned snapshot of a claim's truth state.

    Truth versions provide a complete history of how a claim's
    status has evolved over time, with full audit trails.
    """

    __tablename__ = "truth_versions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=True)
    reasoning_trace_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("reasoning_traces.id"), nullable=True
    )
    state_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_version_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    # Relationships
    claim: Mapped["Claim"] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("claim_id", "version_number", name="uq_truth_version_claim_num"),
        Index("ix_truth_versions_claim_version", "claim_id", "version_number"),
    )


class AuditEntry(TimestampMixin, Base):
    """
    An immutable audit log entry.

    Every significant operation in the system creates an audit entry,
    enabling complete reconstruction of system history.
    """

    __tablename__ = "audit_entries"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    span_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    operation: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    before_state: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_timestamp", "created_at"),
    )


class Workflow(TimestampMixin, Base):
    """
    A workflow orchestrating the processing of a claim.

    Workflows track the progress of claims through the system,
    ensuring deterministic execution order.
    """

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    current_step: Mapped[str] = mapped_column(String(100), nullable=False)
    steps_completed: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    steps_remaining: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Report(TimestampMixin, Base):
    """
    A generated report for a claim or set of claims.

    Reports are the output artifacts of the Truth Engine,
    containing formatted truth determinations.
    """

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    claim_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True
    )
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="json")
    content_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    object_key: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
