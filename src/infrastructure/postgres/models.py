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


# =============================================================================
# A6: Financial Fact Storage
# =============================================================================


class FinancialFactRecord(TimestampMixin, Base):
    """
    Persistent storage for extracted financial facts.
    
    Facts are the core data extracted from evidence by A5.
    They are immutable once created and indexed for efficient
    retrieval by entity, fact_type, and evidence.
    """
    
    __tablename__ = "financial_facts"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    fact_hash: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    
    # Type
    fact_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Value (stored as string for precision)
    value: Mapped[str] = mapped_column(String(100), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    scale: Mapped[int] = mapped_column(Integer, default=0)
    
    # Temporal
    as_of_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fiscal_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fiscal_quarter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Extraction metadata
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence_level: Mapped[str] = mapped_column(String(20), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(20), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Provenance
    evidence_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    evidence_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    # Entity linkage
    entity_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    entity_id_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    __table_args__ = (
        Index("ix_facts_entity", "entity_id_type", "entity_id"),
        Index("ix_facts_type_date", "fact_type", "as_of_date"),
        Index("ix_facts_evidence", "evidence_id"),
    )


class EvidencePassageRecord(TimestampMixin, Base):
    """
    Persistent storage for extracted evidence passages.
    
    Passages provide human-readable provenance for facts
    and capture key narrative items.
    """
    
    __tablename__ = "evidence_passages"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    passage_hash: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    
    # Source
    evidence_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    evidence_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Location
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    xbrl_tag: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    
    # Content
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    passage_type: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Linkage
    linked_fact_ids: Mapped[list] = mapped_column(JSONB, default=list)


class FactClaimLink(TimestampMixin, Base):
    """
    Many-to-many link between facts and claims.
    
    Tracks which facts are used for which claims,
    enabling audit trails.
    """
    
    __tablename__ = "fact_claim_links"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    fact_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    claim_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    
    __table_args__ = (
        UniqueConstraint("fact_id", "claim_id", name="uq_fact_claim"),
        Index("ix_fact_claim_fact", "fact_id"),
        Index("ix_fact_claim_claim", "claim_id"),
    )


# =============================================================================
# A7: Trace & Audit Storage
# =============================================================================


class TraceGraphRecord(TimestampMixin, Base):
    """
    Persistent storage for reasoning trace graphs.
    
    Traces are immutable once created. They capture the complete
    reasoning chain for a solvency evaluation.
    """
    
    __tablename__ = "trace_graphs"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    trace_hash: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    
    # Links
    evaluation_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    claim_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    claim_hash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Graph structure (stored as JSONB)
    nodes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    edges: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Root node references
    claim_node_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    conclusion_node_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    refusal_node_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Versioning
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)
    trace_service_version: Mapped[str] = mapped_column(String(20), nullable=False)
    
    # Timestamp
    built_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    
    __table_args__ = (
        Index("ix_trace_evaluation", "evaluation_id"),
        Index("ix_trace_claim", "claim_id"),
        Index("ix_trace_hash", "trace_hash"),
    )


class AuditLogRecord(TimestampMixin, Base):
    """
    Append-only audit log for evaluations.
    
    Each evaluation writes exactly one audit record. Records are
    chained by hash for tamper detection.
    """
    
    __tablename__ = "audit_log"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    audit_hash: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    
    # Links
    evaluation_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    
    # Engine metadata
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)
    trace_service_version: Mapped[str] = mapped_column(String(20), nullable=False)
    
    # Input hashes
    claim_hash: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    evidence_set_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Facts snapshot (JSONB for efficient storage)
    facts_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    facts_snapshot_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Trace reference
    trace_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Result hash
    result_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Outcome
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # completed, refused, failed
    
    # Chain link
    previous_audit_hash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    chain_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    __table_args__ = (
        Index("ix_audit_evaluation", "evaluation_id"),
        Index("ix_audit_claim", "claim_hash"),
        Index("ix_audit_hash", "audit_hash"),
        Index("ix_audit_chain", "chain_position"),
    )


class AuditManifestRecord(TimestampMixin, Base):
    """
    Daily audit manifest for batch verification.
    
    Contains rolling hash of all audit records for a given date.
    """
    
    __tablename__ = "audit_manifests"
    
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    manifest_hash: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    
    # Date coverage
    manifest_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, unique=True)
    
    # Record summary
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_audit_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_audit_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Hash chain (JSONB list of record hashes)
    record_hashes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    rolling_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Manifest chain
    previous_manifest_hash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Object storage reference
    object_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    __table_args__ = (
        Index("ix_manifest_date", "manifest_date"),
        Index("ix_manifest_hash", "manifest_hash"),
    )
