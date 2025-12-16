"""
Evidence Service Implementation - Production-Grade Evidence Management
=======================================================================

Implements complete evidence lifecycle management:
1. Ingestion with validation and deduplication
2. Content-addressable storage
3. Policy-based retrieval for claims
4. Conflict detection
5. Missing evidence identification

Design Principles:
- All operations are deterministic
- Evidence is immutable once ingested
- Deduplication by content hash
- Policy enforcement is explicit and auditable
- Never extracts facts or infers meaning from content
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import hash_content, deterministic_hash
from shared.logging import get_logger
from infrastructure.object_store import (
    ObjectStoreInterface,
    ObjectMetadata,
    NullObjectStore,
    generate_object_key,
)

from .schemas import (
    # Constants
    SUPPORTED_SOURCE_TYPES,
    ENTITY_LINKED_SOURCES,
    MACROECONOMIC_SOURCES,
    SOURCE_RELIABILITY_TIER,
    DEFAULT_MAX_STATEMENT_AGE_DAYS,
    MIN_RELIABILITY_SCORE,
    # Enums
    EvidenceStatus,
    EvidenceSourceType,
    RejectionCode,
    ConflictType,
    MissingEvidenceReason,
    # Models
    EvidenceEntityIdentifier,
    EvidenceProvenance,
    EvidenceReliability,
    EvidenceDocument,
    IngestEvidenceRequest,
    IngestEvidenceResponse,
    EvidenceRejection,
    EvidencePolicy,
    MissingEvidence,
    EvidenceConflict,
    EvidenceSet,
    LookupByClaimRequest,
    LookupByEntityRequest,
    LookupByEntityResponse,
    SECFilingMetadata,
    AuditedStatementMetadata,
    MacroeconomicDataMetadata,
)


logger = get_logger(__name__)


# =============================================================================
# Ingestion Pipelines
# =============================================================================


class IngestionPipeline(ABC):
    """Base class for evidence ingestion pipelines."""
    
    @abstractmethod
    def validate(self, request: IngestEvidenceRequest) -> list[EvidenceRejection]:
        """Validate the ingestion request. Returns list of rejections."""
        pass
    
    @abstractmethod
    def extract_provenance(
        self, request: IngestEvidenceRequest, content_hash: str
    ) -> EvidenceProvenance:
        """Extract provenance from the request."""
        pass
    
    @abstractmethod
    def compute_reliability(
        self, request: IngestEvidenceRequest, provenance: EvidenceProvenance
    ) -> EvidenceReliability:
        """Compute reliability assessment."""
        pass


class SECFilingPipeline(IngestionPipeline):
    """Pipeline for SEC filing ingestion (10-K, 10-Q, 8-K)."""
    
    SUPPORTED_TYPES = frozenset({
        EvidenceSourceType.SEC_10K,
        EvidenceSourceType.SEC_10Q,
        EvidenceSourceType.SEC_8K,
    })
    
    def validate(self, request: IngestEvidenceRequest) -> list[EvidenceRejection]:
        """Validate SEC filing request."""
        rejections: list[EvidenceRejection] = []
        
        # Must have SEC metadata
        if not request.sec_metadata:
            rejections.append(EvidenceRejection(
                code=RejectionCode.UNVERIFIABLE_SOURCE,
                message="SEC filing requires SEC metadata",
                field_path="sec_metadata",
                suggestion="Provide accession_number, cik, filing_date",
            ))
            return rejections
        
        meta = request.sec_metadata
        
        # Validate CIK format (10 digits, zero-padded)
        if not meta.cik or len(meta.cik) != 10:
            normalized_cik = meta.cik.zfill(10) if meta.cik else ""
            if not normalized_cik.isdigit():
                rejections.append(EvidenceRejection(
                    code=RejectionCode.INVALID_ENTITY_IDENTIFIER,
                    message=f"Invalid CIK format: {meta.cik}",
                    field_path="sec_metadata.cik",
                    suggestion="CIK must be a 10-digit number",
                ))
        
        # Validate accession number format (XXXXXXXXXX-XX-XXXXXX)
        if meta.accession_number:
            parts = meta.accession_number.replace("-", "")
            if not parts.isdigit() or len(parts) != 18:
                rejections.append(EvidenceRejection(
                    code=RejectionCode.UNVERIFIABLE_SOURCE,
                    message=f"Invalid accession number format: {meta.accession_number}",
                    field_path="sec_metadata.accession_number",
                    suggestion="Accession number format: XXXXXXXXXX-XX-XXXXXX",
                ))
        
        # Filing date cannot be in the future
        if meta.filing_date > date.today():
            rejections.append(EvidenceRejection(
                code=RejectionCode.FUTURE_DATED_DOCUMENT,
                message=f"Filing date {meta.filing_date} is in the future",
                field_path="sec_metadata.filing_date",
            ))
        
        # Must have entity identifier with CIK
        has_cik = any(
            eid.id_type == "CIK" for eid in request.entity_identifiers
        )
        if not has_cik:
            # Add CIK from metadata
            pass  # Will be added during processing
        
        return rejections
    
    def extract_provenance(
        self, request: IngestEvidenceRequest, content_hash: str
    ) -> EvidenceProvenance:
        """Extract provenance from SEC filing."""
        meta = request.sec_metadata
        assert meta is not None
        
        # Determine if audited based on form type
        is_audited = request.source_type == EvidenceSourceType.SEC_10K
        
        # Determine period from metadata
        period_end = meta.period_of_report
        period_start = None
        fiscal_year = None
        fiscal_quarter = None
        
        if request.source_type == EvidenceSourceType.SEC_10K:
            # Annual report - full year
            fiscal_year = period_end.year
            # Approximate period start
            period_start = date(period_end.year - 1, period_end.month, period_end.day)
        elif request.source_type == EvidenceSourceType.SEC_10Q:
            # Quarterly report
            fiscal_quarter = request.fiscal_quarter or ((period_end.month - 1) // 3 + 1)
            fiscal_year = period_end.year
        
        return EvidenceProvenance(
            source_type=request.source_type,
            source_uri=request.source_uri,
            source_name=f"SEC EDGAR - {meta.form_type}",
            published_at=datetime.combine(meta.filing_date, datetime.min.time()).replace(
                tzinfo=timezone.utc
            ),
            retrieved_at=datetime.now(timezone.utc),
            period_start=period_start or request.period_start,
            period_end=period_end,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            reliability_tier=SOURCE_RELIABILITY_TIER.get(request.source_type.value, 2),
            is_audited=is_audited,
            auditor_name=None,  # Not typically in SEC filing header
            accession_number=meta.accession_number,
            filing_date=meta.filing_date,
            jurisdiction="US",
        )
    
    def compute_reliability(
        self, request: IngestEvidenceRequest, provenance: EvidenceProvenance
    ) -> EvidenceReliability:
        """Compute reliability for SEC filing."""
        now = datetime.now(timezone.utc)
        age_days = (now - provenance.published_at).days
        
        # SEC filings are high reliability
        base_score = Decimal("0.95") if provenance.is_audited else Decimal("0.90")
        
        # Adjust for age
        if age_days > 365:
            age_penalty = min(Decimal("0.10"), Decimal(age_days - 365) / Decimal("1000"))
            base_score -= age_penalty
        
        return EvidenceReliability(
            overall_score=max(Decimal("0.50"), base_score),
            source_tier=provenance.reliability_tier,
            is_primary_source=True,
            is_audited=provenance.is_audited,
            age_days=age_days,
            is_stale=age_days > 365,
            staleness_threshold_days=365,
        )


class AuditedStatementPipeline(IngestionPipeline):
    """Pipeline for audited financial statement ingestion."""
    
    SUPPORTED_TYPES = frozenset({
        EvidenceSourceType.AUDITED_FINANCIAL_STATEMENT,
        EvidenceSourceType.AUDITED_ANNUAL_REPORT,
        EvidenceSourceType.AUDITOR_OPINION,
    })
    
    def validate(self, request: IngestEvidenceRequest) -> list[EvidenceRejection]:
        """Validate audited statement request."""
        rejections: list[EvidenceRejection] = []
        
        # Must have audited statement metadata
        if not request.audited_statement_metadata:
            rejections.append(EvidenceRejection(
                code=RejectionCode.UNVERIFIABLE_SOURCE,
                message="Audited statement requires statement metadata",
                field_path="audited_statement_metadata",
                suggestion="Provide auditor_name, audit_opinion, opinion_date",
            ))
            return rejections
        
        meta = request.audited_statement_metadata
        
        # Validate auditor name is not empty
        if not meta.auditor_name or not meta.auditor_name.strip():
            rejections.append(EvidenceRejection(
                code=RejectionCode.UNVERIFIABLE_SOURCE,
                message="Auditor name is required",
                field_path="audited_statement_metadata.auditor_name",
            ))
        
        # Validate audit opinion is known type
        valid_opinions = {"unqualified", "qualified", "adverse", "disclaimer"}
        if meta.audit_opinion.lower() not in valid_opinions:
            rejections.append(EvidenceRejection(
                code=RejectionCode.UNVERIFIABLE_SOURCE,
                message=f"Unknown audit opinion type: {meta.audit_opinion}",
                field_path="audited_statement_metadata.audit_opinion",
                details={"valid_opinions": list(valid_opinions)},
            ))
        
        # Opinion date cannot be before period end
        if meta.opinion_date < meta.period_end:
            rejections.append(EvidenceRejection(
                code=RejectionCode.UNVERIFIABLE_SOURCE,
                message="Audit opinion date cannot be before period end",
                field_path="audited_statement_metadata.opinion_date",
            ))
        
        # Must have entity identifier
        if not request.entity_identifiers:
            rejections.append(EvidenceRejection(
                code=RejectionCode.MISSING_ENTITY_IDENTIFIER,
                message="Entity identifier required for audited statement",
                field_path="entity_identifiers",
            ))
        
        return rejections
    
    def extract_provenance(
        self, request: IngestEvidenceRequest, content_hash: str
    ) -> EvidenceProvenance:
        """Extract provenance from audited statement."""
        meta = request.audited_statement_metadata
        assert meta is not None
        
        return EvidenceProvenance(
            source_type=request.source_type,
            source_uri=request.source_uri,
            source_name=f"Audited Statement - {meta.auditor_name}",
            published_at=datetime.combine(meta.opinion_date, datetime.min.time()).replace(
                tzinfo=timezone.utc
            ),
            retrieved_at=datetime.now(timezone.utc),
            period_start=meta.period_start,
            period_end=meta.period_end,
            fiscal_year=meta.fiscal_year,
            fiscal_quarter=None,
            reliability_tier=SOURCE_RELIABILITY_TIER.get(request.source_type.value, 1),
            is_audited=True,
            auditor_name=meta.auditor_name,
            accession_number=None,
            filing_date=None,
            jurisdiction=meta.entity_jurisdiction,
        )
    
    def compute_reliability(
        self, request: IngestEvidenceRequest, provenance: EvidenceProvenance
    ) -> EvidenceReliability:
        """Compute reliability for audited statement."""
        now = datetime.now(timezone.utc)
        age_days = (now - provenance.published_at).days
        
        # Audited statements are high reliability
        base_score = Decimal("0.95")
        
        # Adjust for age
        if age_days > 365:
            age_penalty = min(Decimal("0.15"), Decimal(age_days - 365) / Decimal("1000"))
            base_score -= age_penalty
        
        return EvidenceReliability(
            overall_score=max(Decimal("0.50"), base_score),
            source_tier=provenance.reliability_tier,
            is_primary_source=True,
            is_audited=True,
            age_days=age_days,
            is_stale=age_days > 365,
            staleness_threshold_days=365,
        )


class MacroeconomicDataPipeline(IngestionPipeline):
    """Pipeline for macroeconomic reference data ingestion."""
    
    SUPPORTED_TYPES = frozenset({
        EvidenceSourceType.INTEREST_RATE_CURVE,
        EvidenceSourceType.TREASURY_YIELD_CURVE,
        EvidenceSourceType.ECONOMIC_INDICATORS,
        EvidenceSourceType.CENTRAL_BANK_RATES,
    })
    
    def validate(self, request: IngestEvidenceRequest) -> list[EvidenceRejection]:
        """Validate macroeconomic data request."""
        rejections: list[EvidenceRejection] = []
        
        # Must have macroeconomic metadata
        if not request.macroeconomic_metadata:
            rejections.append(EvidenceRejection(
                code=RejectionCode.UNVERIFIABLE_SOURCE,
                message="Macroeconomic data requires macroeconomic metadata",
                field_path="macroeconomic_metadata",
                suggestion="Provide source_institution, publication_date, effective_date",
            ))
            return rejections
        
        meta = request.macroeconomic_metadata
        
        # Validate source institution is recognized
        recognized_institutions = {
            "federal reserve", "fed", "ecb", "bank of england", "boe",
            "treasury", "us treasury", "bls", "census", "imf", "world bank",
        }
        if meta.source_institution.lower() not in recognized_institutions:
            # Not a rejection, but a warning - we accept other institutions
            pass
        
        # Effective date cannot be in the far future (more than 30 days)
        if meta.effective_date > date.today():
            # Allow up to 30 days in future for forward-looking data
            days_ahead = (meta.effective_date - date.today()).days
            if days_ahead > 30:
                rejections.append(EvidenceRejection(
                    code=RejectionCode.FUTURE_DATED_DOCUMENT,
                    message=f"Effective date {meta.effective_date} is too far in the future",
                    field_path="macroeconomic_metadata.effective_date",
                ))
        
        # Entity identifiers should NOT be present for macro data
        if request.entity_identifiers:
            rejections.append(EvidenceRejection(
                code=RejectionCode.ENTITY_MISMATCH,
                message="Macroeconomic data should not have entity identifiers",
                field_path="entity_identifiers",
                suggestion="Remove entity identifiers for macroeconomic data",
            ))
        
        return rejections
    
    def extract_provenance(
        self, request: IngestEvidenceRequest, content_hash: str
    ) -> EvidenceProvenance:
        """Extract provenance from macroeconomic data."""
        meta = request.macroeconomic_metadata
        assert meta is not None
        
        return EvidenceProvenance(
            source_type=request.source_type,
            source_uri=request.source_uri,
            source_name=f"{meta.source_institution} - {meta.data_type}",
            published_at=datetime.combine(meta.publication_date, datetime.min.time()).replace(
                tzinfo=timezone.utc
            ),
            retrieved_at=datetime.now(timezone.utc),
            period_start=None,
            period_end=meta.effective_date,
            fiscal_year=None,
            fiscal_quarter=None,
            reliability_tier=SOURCE_RELIABILITY_TIER.get(request.source_type.value, 1),
            is_audited=False,  # Macro data is not audited
            auditor_name=None,
            accession_number=None,
            filing_date=None,
            jurisdiction=meta.region,
        )
    
    def compute_reliability(
        self, request: IngestEvidenceRequest, provenance: EvidenceProvenance
    ) -> EvidenceReliability:
        """Compute reliability for macroeconomic data."""
        now = datetime.now(timezone.utc)
        age_days = (now - provenance.published_at).days
        
        # Macro data from official sources is high reliability
        base_score = Decimal("0.95")
        
        # Macro data becomes stale faster (30 days for rates)
        staleness_threshold = 30 if "rate" in request.source_type.value.lower() else 90
        
        if age_days > staleness_threshold:
            age_penalty = min(Decimal("0.30"), Decimal(age_days - staleness_threshold) / Decimal("100"))
            base_score -= age_penalty
        
        return EvidenceReliability(
            overall_score=max(Decimal("0.50"), base_score),
            source_tier=provenance.reliability_tier,
            is_primary_source=True,
            is_audited=False,
            age_days=age_days,
            is_stale=age_days > staleness_threshold,
            staleness_threshold_days=staleness_threshold,
        )


# =============================================================================
# Evidence Storage
# =============================================================================


@dataclass
class EvidenceRecord:
    """Internal storage record for evidence."""
    
    evidence_id: str
    content_hash: str
    status: EvidenceStatus
    entity_identifiers: list[EvidenceEntityIdentifier]
    provenance: EvidenceProvenance
    reliability: EvidenceReliability
    object_key: str
    content_type: str
    size_bytes: int
    metadata: dict[str, Any]
    ingested_at: datetime
    supersedes_evidence_id: Optional[str] = None
    superseded_by_evidence_id: Optional[str] = None


class EvidenceStore:
    """In-memory evidence storage with indexing."""
    
    def __init__(self) -> None:
        # Primary storage by evidence_id
        self._records: dict[str, EvidenceRecord] = {}
        
        # Index by content_hash for deduplication
        self._by_hash: dict[str, str] = {}  # hash -> evidence_id
        
        # Index by entity identifier
        self._by_entity: dict[str, set[str]] = {}  # "type:value" -> evidence_ids
        
        # Index by claim (for claim-based retrieval)
        self._by_claim: dict[str, set[str]] = {}  # claim_id -> evidence_ids
        
        # Index by source type
        self._by_source_type: dict[str, set[str]] = {}  # source_type -> evidence_ids
    
    def store(self, record: EvidenceRecord) -> None:
        """Store an evidence record with indexing."""
        self._records[record.evidence_id] = record
        
        # Index by hash
        self._by_hash[record.content_hash] = record.evidence_id
        
        # Index by entity identifiers
        for eid in record.entity_identifiers:
            key = f"{eid.id_type}:{eid.id_value}"
            if eid.exchange:
                key = f"{key}:{eid.exchange}"
            if key not in self._by_entity:
                self._by_entity[key] = set()
            self._by_entity[key].add(record.evidence_id)
        
        # Index by source type
        source_type = record.provenance.source_type.value
        if source_type not in self._by_source_type:
            self._by_source_type[source_type] = set()
        self._by_source_type[source_type].add(record.evidence_id)
    
    def get(self, evidence_id: str) -> Optional[EvidenceRecord]:
        """Get evidence by ID."""
        return self._records.get(evidence_id)
    
    def get_by_hash(self, content_hash: str) -> Optional[EvidenceRecord]:
        """Get evidence by content hash."""
        evidence_id = self._by_hash.get(content_hash)
        if evidence_id:
            return self._records.get(evidence_id)
        return None
    
    def find_by_entity(
        self,
        id_type: str,
        id_value: str,
        exchange: Optional[str] = None,
    ) -> list[EvidenceRecord]:
        """Find evidence by entity identifier."""
        key = f"{id_type}:{id_value}"
        if exchange:
            key = f"{key}:{exchange}"
        
        evidence_ids = self._by_entity.get(key, set())
        return [self._records[eid] for eid in evidence_ids if eid in self._records]
    
    def find_by_source_type(
        self, source_type: str
    ) -> list[EvidenceRecord]:
        """Find evidence by source type."""
        evidence_ids = self._by_source_type.get(source_type, set())
        return [self._records[eid] for eid in evidence_ids if eid in self._records]
    
    def link_to_claim(self, claim_id: str, evidence_id: str) -> None:
        """Link evidence to a claim."""
        if claim_id not in self._by_claim:
            self._by_claim[claim_id] = set()
        self._by_claim[claim_id].add(evidence_id)
    
    def find_by_claim(self, claim_id: str) -> list[EvidenceRecord]:
        """Find evidence linked to a claim."""
        evidence_ids = self._by_claim.get(claim_id, set())
        return [self._records[eid] for eid in evidence_ids if eid in self._records]
    
    def update_supersession(
        self, evidence_id: str, superseded_by: str
    ) -> None:
        """Mark evidence as superseded."""
        record = self._records.get(evidence_id)
        if record:
            # Create new record with updated supersession
            new_record = EvidenceRecord(
                evidence_id=record.evidence_id,
                content_hash=record.content_hash,
                status=EvidenceStatus.SUPERSEDED,
                entity_identifiers=record.entity_identifiers,
                provenance=record.provenance,
                reliability=record.reliability,
                object_key=record.object_key,
                content_type=record.content_type,
                size_bytes=record.size_bytes,
                metadata=record.metadata,
                ingested_at=record.ingested_at,
                supersedes_evidence_id=record.supersedes_evidence_id,
                superseded_by_evidence_id=superseded_by,
            )
            self._records[evidence_id] = new_record


# =============================================================================
# Policy Enforcement
# =============================================================================


class PolicyEnforcer:
    """Enforces evidence admissibility policies."""
    
    def __init__(self, policy: EvidencePolicy) -> None:
        self._policy = policy
    
    def check_admissibility(
        self, evidence: EvidenceRecord
    ) -> tuple[bool, Optional[EvidenceRejection]]:
        """Check if evidence is admissible under policy."""
        
        # Check source type
        if evidence.provenance.source_type not in self._policy.allowed_source_types:
            return False, EvidenceRejection(
                code=RejectionCode.SOURCE_TYPE_NOT_ALLOWED,
                message=f"Source type {evidence.provenance.source_type.value} not allowed by policy",
                details={"allowed": [st.value for st in self._policy.allowed_source_types]},
            )
        
        # Check audited requirement
        if self._policy.require_audited_statements:
            # Only apply to entity-linked sources that should be audited
            if (
                evidence.provenance.source_type.value in ENTITY_LINKED_SOURCES
                and not evidence.provenance.is_audited
            ):
                # For 10-Q, we don't require audit
                if evidence.provenance.source_type not in {
                    EvidenceSourceType.SEC_10Q,
                    EvidenceSourceType.SEC_8K,
                }:
                    return False, EvidenceRejection(
                        code=RejectionCode.SOURCE_NOT_AUTHORITATIVE,
                        message="Policy requires audited statements",
                    )
        
        # Check document age
        if evidence.reliability.is_stale:
            age_days = evidence.reliability.age_days
            if age_days > self._policy.max_document_age_days:
                return False, EvidenceRejection(
                    code=RejectionCode.DOCUMENT_EXPIRED,
                    message=f"Document is {age_days} days old, exceeds max {self._policy.max_document_age_days}",
                    details={
                        "age_days": age_days,
                        "max_allowed": self._policy.max_document_age_days,
                    },
                )
        
        # Check reliability score
        if evidence.reliability.overall_score < self._policy.minimum_reliability_score:
            return False, EvidenceRejection(
                code=RejectionCode.RELIABILITY_BELOW_THRESHOLD,
                message=f"Reliability score {evidence.reliability.overall_score} below threshold {self._policy.minimum_reliability_score}",
            )
        
        # Check jurisdiction
        if self._policy.allowed_jurisdictions:
            if (
                evidence.provenance.jurisdiction
                and evidence.provenance.jurisdiction not in self._policy.allowed_jurisdictions
            ):
                return False, EvidenceRejection(
                    code=RejectionCode.JURISDICTION_NOT_ALLOWED,
                    message=f"Jurisdiction {evidence.provenance.jurisdiction} not allowed",
                    details={"allowed": list(self._policy.allowed_jurisdictions)},
                )
        
        # Check primary source requirement
        if self._policy.require_primary_sources:
            if not evidence.reliability.is_primary_source:
                return False, EvidenceRejection(
                    code=RejectionCode.SOURCE_NOT_AUTHORITATIVE,
                    message="Policy requires primary sources",
                )
        
        # Check entity linkage requirement
        if self._policy.require_entity_linkage:
            if evidence.provenance.source_type.value in ENTITY_LINKED_SOURCES:
                if not evidence.entity_identifiers:
                    return False, EvidenceRejection(
                        code=RejectionCode.MISSING_ENTITY_IDENTIFIER,
                        message="Policy requires entity linkage for this source type",
                    )
        
        return True, None


# =============================================================================
# Conflict Detection
# =============================================================================


class ConflictDetector:
    """Detects conflicts between evidence documents."""
    
    def detect_conflicts(
        self, evidence_list: list[EvidenceRecord]
    ) -> list[EvidenceConflict]:
        """Detect conflicts in a set of evidence."""
        conflicts: list[EvidenceConflict] = []
        
        # Group evidence by entity + source type + period
        grouped: dict[str, list[EvidenceRecord]] = {}
        
        for evidence in evidence_list:
            if evidence.status == EvidenceStatus.SUPERSEDED:
                continue
            
            # Create grouping key
            entity_key = self._get_entity_key(evidence)
            source_type = evidence.provenance.source_type.value
            period_key = self._get_period_key(evidence)
            
            key = f"{entity_key}|{source_type}|{period_key}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(evidence)
        
        # Check for duplicates within each group
        for key, group in grouped.items():
            if len(group) > 1:
                # Multiple documents for same entity/type/period
                conflict = self._analyze_group_conflict(key, group)
                if conflict:
                    conflicts.append(conflict)
        
        return conflicts
    
    def _get_entity_key(self, evidence: EvidenceRecord) -> str:
        """Get normalized entity key."""
        if not evidence.entity_identifiers:
            return "NO_ENTITY"
        
        # Use primary identifier or first one
        primary = next(
            (eid for eid in evidence.entity_identifiers if eid.is_primary),
            evidence.entity_identifiers[0]
        )
        return f"{primary.id_type}:{primary.id_value}"
    
    def _get_period_key(self, evidence: EvidenceRecord) -> str:
        """Get normalized period key."""
        prov = evidence.provenance
        
        if prov.fiscal_year:
            if prov.fiscal_quarter:
                return f"FY{prov.fiscal_year}Q{prov.fiscal_quarter}"
            return f"FY{prov.fiscal_year}"
        
        if prov.period_end:
            return prov.period_end.isoformat()
        
        return "NO_PERIOD"
    
    def _analyze_group_conflict(
        self, key: str, group: list[EvidenceRecord]
    ) -> Optional[EvidenceConflict]:
        """Analyze a group of potentially conflicting evidence."""
        # Sort by ingestion time
        sorted_group = sorted(group, key=lambda e: e.ingested_at)
        
        # Check if they have different content hashes
        hashes = {e.content_hash for e in sorted_group}
        
        if len(hashes) > 1:
            # Different content for same entity/period
            return EvidenceConflict(
                conflict_type=ConflictType.DUPLICATE_PERIOD_FILING,
                evidence_ids=[e.evidence_id for e in sorted_group],
                affected_facts=[],  # Would need fact mapping
                description=f"Multiple documents with different content for {key}",
                resolution_suggestion="Use the most recent document or manually review",
            )
        else:
            # Same content - true duplicate, not a conflict
            return None


# =============================================================================
# Evidence Service
# =============================================================================


class EvidenceService:
    """
    Production-grade Evidence Service.
    
    Handles evidence ingestion, storage, retrieval, and policy enforcement.
    Never extracts facts or infers meaning - only manages document-level truth.
    """
    
    def __init__(
        self,
        object_store: Optional[ObjectStoreInterface] = None,
    ) -> None:
        self._object_store = object_store or NullObjectStore()
        self._store = EvidenceStore()
        self._conflict_detector = ConflictDetector()
        
        # Initialize pipelines
        self._pipelines: dict[EvidenceSourceType, IngestionPipeline] = {}
        self._register_pipelines()
    
    def _register_pipelines(self) -> None:
        """Register ingestion pipelines for each source type."""
        sec_pipeline = SECFilingPipeline()
        for source_type in SECFilingPipeline.SUPPORTED_TYPES:
            self._pipelines[source_type] = sec_pipeline
        
        audited_pipeline = AuditedStatementPipeline()
        for source_type in AuditedStatementPipeline.SUPPORTED_TYPES:
            self._pipelines[source_type] = audited_pipeline
        
        macro_pipeline = MacroeconomicDataPipeline()
        for source_type in MacroeconomicDataPipeline.SUPPORTED_TYPES:
            self._pipelines[source_type] = macro_pipeline
    
    async def ingest(
        self, request: IngestEvidenceRequest
    ) -> IngestEvidenceResponse:
        """
        Ingest new evidence into the system.
        
        Performs:
        - Source type validation
        - Pipeline-specific validation
        - Content hashing and deduplication
        - Object storage
        - Provenance recording
        """
        logger.info(
            "Ingesting evidence",
            source_type=request.source_type.value,
            trace_id=request.trace_id,
        )
        
        # Check source type is supported
        if request.source_type.value not in SUPPORTED_SOURCE_TYPES:
            return IngestEvidenceResponse(
                success=False,
                rejected=True,
                rejection_code=RejectionCode.UNSUPPORTED_SOURCE_TYPE,
                rejection_message=f"Source type {request.source_type.value} is not supported",
                trace_id=request.trace_id,
            )
        
        # Get appropriate pipeline
        pipeline = self._pipelines.get(request.source_type)
        if not pipeline:
            return IngestEvidenceResponse(
                success=False,
                rejected=True,
                rejection_code=RejectionCode.UNSUPPORTED_SOURCE_TYPE,
                rejection_message=f"No pipeline registered for {request.source_type.value}",
                trace_id=request.trace_id,
            )
        
        # Run pipeline validation
        rejections = pipeline.validate(request)
        if rejections:
            first_rejection = rejections[0]
            return IngestEvidenceResponse(
                success=False,
                rejected=True,
                rejection_code=first_rejection.code,
                rejection_message=first_rejection.message,
                trace_id=request.trace_id,
            )
        
        # Get content
        content = request.content
        if not content and request.content_reference:
            # EXTENSION_POINT: Fetch from reference
            return IngestEvidenceResponse(
                success=False,
                rejected=True,
                rejection_code=RejectionCode.INVALID_DOCUMENT_FORMAT,
                rejection_message="Content reference fetching not yet implemented",
                trace_id=request.trace_id,
            )
        
        if not content:
            return IngestEvidenceResponse(
                success=False,
                rejected=True,
                rejection_code=RejectionCode.INVALID_DOCUMENT_FORMAT,
                rejection_message="No content provided",
                trace_id=request.trace_id,
            )
        
        # Compute content hash
        content_hash = hashlib.sha256(content).hexdigest()
        
        # Verify expected hash if provided
        if request.expected_hash and request.expected_hash != content_hash:
            return IngestEvidenceResponse(
                success=False,
                rejected=True,
                rejection_code=RejectionCode.HASH_MISMATCH,
                rejection_message=f"Content hash mismatch: expected {request.expected_hash}, got {content_hash}",
                trace_id=request.trace_id,
            )
        
        # Check for duplicate
        existing = self._store.get_by_hash(content_hash)
        if existing:
            logger.info(
                "Duplicate evidence detected",
                existing_id=existing.evidence_id,
                content_hash=content_hash,
                trace_id=request.trace_id,
            )
            return IngestEvidenceResponse(
                success=True,
                evidence_id=existing.evidence_id,
                content_hash=content_hash,
                is_duplicate=True,
                duplicate_evidence_id=existing.evidence_id,
                trace_id=request.trace_id,
            )
        
        # Generate stable evidence ID
        evidence_id = str(generate_canonical_id(EntityType.EVIDENCE))
        
        # Store in object store
        object_key = f"evidence/{content_hash[:2]}/{content_hash}"
        try:
            obj_meta = await self._object_store.put(
                content,
                prefix="evidence",
                content_type=self._infer_content_type(request),
                metadata={
                    "evidence_id": evidence_id,
                    "source_type": request.source_type.value,
                    "trace_id": request.trace_id,
                },
            )
            object_key = obj_meta.key
        except Exception as e:
            logger.error(
                "Failed to store evidence content",
                error=str(e),
                trace_id=request.trace_id,
            )
            return IngestEvidenceResponse(
                success=False,
                rejected=True,
                rejection_code=RejectionCode.DOCUMENT_CORRUPTED,
                rejection_message=f"Failed to store content: {e}",
                trace_id=request.trace_id,
            )
        
        # Extract provenance and compute reliability
        provenance = pipeline.extract_provenance(request, content_hash)
        reliability = pipeline.compute_reliability(request, provenance)
        
        # Normalize entity identifiers
        entity_identifiers = list(request.entity_identifiers)
        
        # For SEC filings, add CIK from metadata if not present
        if request.sec_metadata:
            cik = request.sec_metadata.cik.zfill(10)
            has_cik = any(eid.id_type == "CIK" for eid in entity_identifiers)
            if not has_cik:
                entity_identifiers.append(EvidenceEntityIdentifier(
                    id_type="CIK",
                    id_value=cik,
                    is_primary=True,
                ))
        
        # Create evidence record
        record = EvidenceRecord(
            evidence_id=evidence_id,
            content_hash=content_hash,
            status=EvidenceStatus.VALIDATED,
            entity_identifiers=entity_identifiers,
            provenance=provenance,
            reliability=reliability,
            object_key=object_key,
            content_type=self._infer_content_type(request),
            size_bytes=len(content),
            metadata=request.metadata,
            ingested_at=datetime.now(timezone.utc),
        )
        
        # Store record
        self._store.store(record)
        
        logger.info(
            "Evidence ingested successfully",
            evidence_id=evidence_id,
            content_hash=content_hash,
            source_type=request.source_type.value,
            trace_id=request.trace_id,
        )
        
        return IngestEvidenceResponse(
            success=True,
            evidence_id=evidence_id,
            content_hash=content_hash,
            is_duplicate=False,
            trace_id=request.trace_id,
        )
    
    def _infer_content_type(self, request: IngestEvidenceRequest) -> str:
        """Infer content type from request."""
        # EXTENSION_POINT: More sophisticated content type detection
        source_type = request.source_type.value
        
        if "sec" in source_type:
            return "application/xml"  # SEC filings are typically XML
        elif "rate" in source_type or "economic" in source_type:
            return "application/json"  # Macro data is typically JSON
        elif "audited" in source_type:
            return "application/pdf"  # Audited statements are typically PDF
        
        return "application/octet-stream"
    
    async def get(self, evidence_id: str) -> Optional[EvidenceDocument]:
        """Get evidence by ID."""
        record = self._store.get(evidence_id)
        if not record:
            return None
        
        return self._record_to_document(record)
    
    async def get_content(self, evidence_id: str) -> Optional[bytes]:
        """Get raw content of evidence."""
        record = self._store.get(evidence_id)
        if not record:
            return None
        
        obj = await self._object_store.get(record.object_key)
        return obj.content if obj else None
    
    async def find_by_entity(
        self,
        request: LookupByEntityRequest,
    ) -> LookupByEntityResponse:
        """Find evidence by entity identifier."""
        records = self._store.find_by_entity(
            id_type=request.entity_id_type.upper(),
            id_value=request.entity_id_value.upper(),
            exchange=request.exchange,
        )
        
        # Apply filters
        filtered = records
        
        if request.source_types:
            allowed = {st.value for st in request.source_types}
            filtered = [r for r in filtered if r.provenance.source_type.value in allowed]
        
        if request.published_after:
            filtered = [
                r for r in filtered
                if r.provenance.published_at >= request.published_after
            ]
        
        if request.published_before:
            filtered = [
                r for r in filtered
                if r.provenance.published_at <= request.published_before
            ]
        
        if request.status:
            filtered = [r for r in filtered if r.status == request.status]
        
        total = len(filtered)
        
        # Apply pagination
        paginated = filtered[request.offset : request.offset + request.limit]
        
        return LookupByEntityResponse(
            evidence=[self._record_to_document(r) for r in paginated],
            total_count=total,
            offset=request.offset,
            limit=request.limit,
            trace_id=request.trace_id,
        )
    
    async def get_evidence_for_claim(
        self,
        claim: Any,  # CanonicalSolvencyClaim
        contract: Any,  # RequiredFactsContract
        trace_id: str,
    ) -> EvidenceSet:
        """
        Get evidence set for a claim and its required facts.
        
        Performs:
        - Policy derivation from claim
        - Entity-based evidence lookup
        - Policy enforcement filtering
        - Missing evidence identification
        - Conflict detection
        """
        # Derive policy from claim
        policy = EvidencePolicy.from_canonical_claim(claim)
        enforcer = PolicyEnforcer(policy)
        
        # Find all evidence for the claim's entity
        entity = claim.entity
        all_records: list[EvidenceRecord] = []
        
        # Search by entity ID
        id_type = entity.id_type
        id_value = entity.external_id
        all_records = self._store.find_by_entity(id_type, id_value)
        
        # Also get macroeconomic data (no entity filter)
        for source_type in MACROECONOMIC_SOURCES:
            macro_records = self._store.find_by_source_type(source_type)
            all_records.extend(macro_records)
        
        # Apply policy enforcement
        admissible: list[EvidenceRecord] = []
        excluded: list[tuple[EvidenceRecord, EvidenceRejection]] = []
        
        for record in all_records:
            is_admissible, rejection = enforcer.check_admissibility(record)
            if is_admissible:
                admissible.append(record)
            else:
                assert rejection is not None
                excluded.append((record, rejection))
        
        # Detect conflicts
        conflicts = self._conflict_detector.detect_conflicts(admissible)
        
        # Analyze fact coverage
        facts_coverage = self._analyze_fact_coverage(contract, admissible, policy)
        
        # Calculate completeness
        total_required = len(contract.required_facts)
        covered = len(facts_coverage["fully_covered"])
        completeness_ratio = (
            Decimal(covered) / Decimal(total_required)
            if total_required > 0
            else Decimal("1")
        )
        
        # Generate evidence set hash
        evidence_set_hash = self._compute_evidence_set_hash(
            claim.claim_id, contract.contract_id, admissible
        )
        
        evidence_set_id = str(generate_canonical_id(EntityType.DOCUMENT))
        
        return EvidenceSet(
            evidence_set_id=evidence_set_id,
            claim_id=claim.claim_id,
            contract_id=contract.contract_id,
            admissible_evidence=[self._record_to_document(r) for r in admissible],
            excluded_evidence=[
                (self._record_to_document(r), rej) for r, rej in excluded
            ],
            missing_evidence=facts_coverage["missing"],
            conflicts=conflicts,
            facts_fully_covered=facts_coverage["fully_covered"],
            facts_partially_covered=facts_coverage["partially_covered"],
            facts_not_covered=facts_coverage["not_covered"],
            policy_applied=policy,
            is_complete=(len(facts_coverage["not_covered"]) == 0),
            completeness_ratio=completeness_ratio,
            evidence_set_hash=evidence_set_hash,
        )
    
    def _analyze_fact_coverage(
        self,
        contract: Any,
        admissible: list[EvidenceRecord],
        policy: EvidencePolicy,
    ) -> dict[str, Any]:
        """Analyze which facts are covered by available evidence."""
        # This is a simplified implementation
        # In production, this would have more sophisticated fact-to-source mapping
        
        fully_covered: list[str] = []
        partially_covered: list[str] = []
        not_covered: list[str] = []
        missing: list[MissingEvidence] = []
        
        # Map source types to fact categories
        source_to_facts = {
            "sec_10k": ["total_assets", "total_liabilities", "total_equity", "revenue", "net_income"],
            "sec_10q": ["total_assets", "total_liabilities", "revenue"],
            "audited_financial_statement": ["total_assets", "total_liabilities", "total_equity"],
            "interest_rate_curve": ["interest_rate_sensitivity"],
            "treasury_yield_curve": ["interest_rate_sensitivity"],
        }
        
        # Get available source types
        available_sources = {r.provenance.source_type.value for r in admissible}
        
        # Determine covered facts
        covered_facts: set[str] = set()
        for source_type in available_sources:
            facts = source_to_facts.get(source_type, [])
            covered_facts.update(facts)
        
        # Check each required fact
        for fact in contract.required_facts:
            fact_name = fact.fact_name
            if fact_name in covered_facts:
                fully_covered.append(fact.fact_id)
            else:
                not_covered.append(fact.fact_id)
                # Determine acceptable sources for this fact
                acceptable = []
                for source_type, facts in source_to_facts.items():
                    if fact_name in facts:
                        try:
                            acceptable.append(EvidenceSourceType(source_type))
                        except ValueError:
                            pass
                
                missing.append(MissingEvidence(
                    fact_id=fact.fact_id,
                    fact_name=fact_name,
                    reason=MissingEvidenceReason.NO_MATCHING_DOCUMENTS,
                    acceptable_source_types=acceptable or [
                        EvidenceSourceType.SEC_10K,
                        EvidenceSourceType.AUDITED_FINANCIAL_STATEMENT,
                    ],
                    required_period=None,
                    message=f"No evidence found for fact: {fact_name}",
                ))
        
        return {
            "fully_covered": fully_covered,
            "partially_covered": partially_covered,
            "not_covered": not_covered,
            "missing": missing,
        }
    
    def _compute_evidence_set_hash(
        self,
        claim_id: str,
        contract_id: str,
        evidence: list[EvidenceRecord],
    ) -> str:
        """Compute deterministic hash of evidence set."""
        evidence_hashes = sorted([e.content_hash for e in evidence])
        return deterministic_hash(
            claim_id,
            contract_id,
            evidence_hashes,
        )
    
    def _record_to_document(self, record: EvidenceRecord) -> EvidenceDocument:
        """Convert internal record to API document."""
        return EvidenceDocument(
            evidence_id=record.evidence_id,
            content_hash=record.content_hash,
            status=record.status,
            entity_identifiers=record.entity_identifiers,
            provenance=record.provenance,
            reliability=record.reliability,
            object_key=record.object_key,
            content_type=record.content_type,
            size_bytes=record.size_bytes,
            metadata=record.metadata,
            ingested_at=record.ingested_at,
            supersedes_evidence_id=record.supersedes_evidence_id,
            superseded_by_evidence_id=record.superseded_by_evidence_id,
        )
    
    async def link_evidence_to_claim(
        self, claim_id: str, evidence_id: str
    ) -> bool:
        """Link evidence to a claim."""
        record = self._store.get(evidence_id)
        if not record:
            return False
        
        self._store.link_to_claim(claim_id, evidence_id)
        return True
    
    async def list_for_claim(
        self, claim_id: str, offset: int = 0, limit: int = 50
    ) -> tuple[list[EvidenceDocument], int]:
        """List evidence linked to a claim."""
        records = self._store.find_by_claim(claim_id)
        total = len(records)
        
        paginated = records[offset : offset + limit]
        documents = [self._record_to_document(r) for r in paginated]
        
        return documents, total
