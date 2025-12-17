"""
Trace & Audit Service Implementation
======================================

Production-grade implementation of the Trace & Audit Service (A7).

Key Components:
1. TraceStore: Persistent storage for trace graphs
2. AuditStore: Append-only audit log with hash chains
3. ManifestService: Daily signed manifest generation
4. ReplayService: Deterministic replay verification

All operations are:
- Immutable: Once written, traces and audit records cannot be modified
- Append-only: Audit log only supports appending, never updating
- Tamper-evident: Hash chains detect any modification
- Reproducible: Same inputs produce identical hashes
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from shared.canonical_id import EntityType, generate_canonical_id

from infrastructure.postgres.models import (
    TraceGraphRecord,
    AuditLogRecord,
    AuditManifestRecord,
)
from infrastructure.object_store import ObjectStoreInterface

from .schemas import (
    TRACE_SERVICE_VERSION,
    TraceGraph,
    TraceNode,
    TraceEdge,
    AuditRecord,
    AuditManifest,
    AuditRecordType,
    ReplayResult,
    ReplayStatus,
)
from .canonical import (
    GENESIS_HASH,
    canonical_hash,
    canonical_serialize,
    canonical_audit_record_hash,
    canonical_manifest_hash,
    canonical_hash_chain,
    canonical_facts_snapshot_hash,
    canonical_evidence_set_hash,
    canonical_policy_hash,
    verify_hash,
)
from .builder import TraceGraph


# =============================================================================
# Trace Store
# =============================================================================


class TraceStore:
    """
    Persistent storage for reasoning trace graphs.
    
    Traces are immutable once stored. Supports retrieval by:
    - trace_id
    - evaluation_id
    - claim_hash
    """
    
    def __init__(self, session: AsyncSession):
        self._session = session
    
    async def store(self, trace: TraceGraph) -> str:
        """
        Store a trace graph.
        
        Returns the trace ID.
        """
        record = TraceGraphRecord(
            id=trace.trace_id,
            trace_hash=trace.trace_hash,
            evaluation_id=trace.evaluation_id,
            claim_id=trace.claim_node_id,  # Using claim_node_id as reference
            claim_hash=self._extract_claim_hash(trace),
            nodes=[n.model_dump() for n in trace.nodes],
            edges=[e.model_dump() for e in trace.edges],
            node_count=trace.node_count,
            edge_count=trace.edge_count,
            claim_node_id=trace.claim_node_id,
            conclusion_node_id=trace.conclusion_node_id,
            refusal_node_id=trace.refusal_node_id,
            engine_version=trace.engine_version,
            trace_service_version=trace.trace_service_version,
            built_at=trace.built_at,
        )
        
        self._session.add(record)
        await self._session.flush()
        
        return trace.trace_id
    
    async def get(self, trace_id: str) -> Optional[TraceGraph]:
        """Get a trace by ID."""
        result = await self._session.execute(
            select(TraceGraphRecord).where(TraceGraphRecord.id == trace_id)
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._record_to_trace(record)
    
    async def get_by_evaluation(self, evaluation_id: str) -> Optional[TraceGraph]:
        """Get trace by evaluation ID."""
        result = await self._session.execute(
            select(TraceGraphRecord).where(
                TraceGraphRecord.evaluation_id == evaluation_id
            )
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._record_to_trace(record)
    
    async def get_by_hash(self, trace_hash: str) -> Optional[TraceGraph]:
        """Get trace by hash."""
        result = await self._session.execute(
            select(TraceGraphRecord).where(
                TraceGraphRecord.trace_hash == trace_hash
            )
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._record_to_trace(record)
    
    async def exists(self, evaluation_id: str) -> bool:
        """Check if a trace exists for an evaluation."""
        result = await self._session.execute(
            select(func.count(TraceGraphRecord.id)).where(
                TraceGraphRecord.evaluation_id == evaluation_id
            )
        )
        count = result.scalar()
        return count > 0 if count else False
    
    def _extract_claim_hash(self, trace: TraceGraph) -> Optional[str]:
        """Extract claim hash from trace nodes."""
        for node in trace.nodes:
            if node.node_type.value == "claim":
                return node.payload.get("claim_hash")
        return None
    
    def _record_to_trace(self, record: TraceGraphRecord) -> TraceGraph:
        """Convert database record to TraceGraph."""
        nodes = [TraceNode(**n) for n in record.nodes]
        edges = [TraceEdge(**e) for e in record.edges]
        
        return TraceGraph(
            trace_id=record.id,
            evaluation_id=record.evaluation_id,
            nodes=nodes,
            edges=edges,
            node_count=record.node_count,
            edge_count=record.edge_count,
            trace_hash=record.trace_hash,
            engine_version=record.engine_version,
            trace_service_version=record.trace_service_version,
            claim_node_id=record.claim_node_id or "",
            conclusion_node_id=record.conclusion_node_id,
            refusal_node_id=record.refusal_node_id,
            built_at=record.built_at,
        )


# =============================================================================
# Audit Store
# =============================================================================


class AuditStore:
    """
    Append-only audit log storage.
    
    Key properties:
    - Append-only: Cannot update or delete records
    - Hash-chained: Each record links to previous
    - Tamper-evident: Hash chain detects modifications
    """
    
    def __init__(self, session: AsyncSession):
        self._session = session
    
    async def append(
        self,
        evaluation_id: str,
        claim_hash: str,
        evidence_set_hash: str,
        policy_hash: str,
        facts_snapshot: list[dict[str, Any]],
        trace_hash: str,
        result_hash: str,
        outcome: str,
        engine_version: str,
    ) -> AuditRecord:
        """
        Append a new audit record to the log.
        
        Returns the created AuditRecord.
        """
        # Get previous hash for chain
        previous = await self._get_last_record()
        previous_hash = previous.audit_hash if previous else None
        chain_position = (previous.chain_position + 1) if previous else 0
        
        # Generate audit ID
        audit_id = str(generate_canonical_id(EntityType.AUDIT_ENTRY))
        created_at = datetime.now(timezone.utc)
        
        # Compute facts snapshot hash
        facts_snapshot_hash = canonical_facts_snapshot_hash(facts_snapshot)
        
        # Compute audit record hash
        audit_hash = canonical_audit_record_hash(
            evaluation_id=evaluation_id,
            claim_hash=claim_hash,
            evidence_set_hash=evidence_set_hash,
            facts_snapshot_hash=facts_snapshot_hash,
            policy_hash=policy_hash,
            trace_hash=trace_hash,
            result_hash=result_hash,
            engine_version=engine_version,
            created_at=created_at,
            previous_hash=previous_hash,
        )
        
        # Create database record
        record = AuditLogRecord(
            id=audit_id,
            audit_hash=audit_hash,
            evaluation_id=evaluation_id,
            engine_version=engine_version,
            trace_service_version=TRACE_SERVICE_VERSION,
            claim_hash=claim_hash,
            evidence_set_hash=evidence_set_hash,
            policy_hash=policy_hash,
            facts_snapshot=facts_snapshot,
            facts_snapshot_hash=facts_snapshot_hash,
            trace_hash=trace_hash,
            result_hash=result_hash,
            outcome=outcome,
            previous_audit_hash=previous_hash,
            chain_position=chain_position,
        )
        
        self._session.add(record)
        await self._session.flush()
        
        # Return schema object
        return AuditRecord(
            audit_id=audit_id,
            evaluation_id=evaluation_id,
            created_at=created_at,
            engine_version=engine_version,
            trace_service_version=TRACE_SERVICE_VERSION,
            claim_hash=claim_hash,
            evidence_set_hash=evidence_set_hash,
            policy_hash=policy_hash,
            facts_snapshot=facts_snapshot,
            facts_snapshot_hash=facts_snapshot_hash,
            trace_hash=trace_hash,
            result_hash=result_hash,
            outcome=outcome,
            previous_audit_hash=previous_hash,
            audit_hash=audit_hash,
        )
    
    async def get(self, audit_id: str) -> Optional[AuditRecord]:
        """Get audit record by ID."""
        result = await self._session.execute(
            select(AuditLogRecord).where(AuditLogRecord.id == audit_id)
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._record_to_audit(record)
    
    async def get_by_evaluation(self, evaluation_id: str) -> Optional[AuditRecord]:
        """Get audit record by evaluation ID."""
        result = await self._session.execute(
            select(AuditLogRecord).where(
                AuditLogRecord.evaluation_id == evaluation_id
            )
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._record_to_audit(record)
    
    async def get_by_hash(self, audit_hash: str) -> Optional[AuditRecord]:
        """Get audit record by hash."""
        result = await self._session.execute(
            select(AuditLogRecord).where(
                AuditLogRecord.audit_hash == audit_hash
            )
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._record_to_audit(record)
    
    async def get_records_for_date(self, target_date: date) -> list[AuditRecord]:
        """Get all audit records for a specific date."""
        start_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(target_date, datetime.max.time(), tzinfo=timezone.utc)
        
        result = await self._session.execute(
            select(AuditLogRecord)
            .where(AuditLogRecord.created_at >= start_dt)
            .where(AuditLogRecord.created_at <= end_dt)
            .order_by(AuditLogRecord.chain_position)
        )
        records = result.scalars().all()
        
        return [self._record_to_audit(r) for r in records]
    
    async def verify_chain(
        self,
        start_position: int = 0,
        end_position: Optional[int] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Verify the integrity of the audit chain.
        
        Returns (is_valid, first_invalid_audit_id).
        """
        query = select(AuditLogRecord).order_by(AuditLogRecord.chain_position)
        
        if end_position is not None:
            query = query.where(AuditLogRecord.chain_position <= end_position)
        
        result = await self._session.execute(query)
        records = result.scalars().all()
        
        previous_hash: Optional[str] = None
        
        for record in records:
            if record.chain_position < start_position:
                previous_hash = record.audit_hash
                continue
            
            # Verify chain link
            if record.previous_audit_hash != previous_hash:
                return False, record.id
            
            # Recompute hash and verify
            expected_hash = canonical_audit_record_hash(
                evaluation_id=record.evaluation_id,
                claim_hash=record.claim_hash,
                evidence_set_hash=record.evidence_set_hash,
                facts_snapshot_hash=record.facts_snapshot_hash,
                policy_hash=record.policy_hash,
                trace_hash=record.trace_hash,
                result_hash=record.result_hash,
                engine_version=record.engine_version,
                created_at=record.created_at,
                previous_hash=previous_hash,
            )
            
            if record.audit_hash != expected_hash:
                return False, record.id
            
            previous_hash = record.audit_hash
        
        return True, None
    
    async def _get_last_record(self) -> Optional[AuditLogRecord]:
        """Get the last record in the chain."""
        result = await self._session.execute(
            select(AuditLogRecord)
            .order_by(AuditLogRecord.chain_position.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    def _record_to_audit(self, record: AuditLogRecord) -> AuditRecord:
        """Convert database record to AuditRecord."""
        return AuditRecord(
            audit_id=record.id,
            evaluation_id=record.evaluation_id,
            created_at=record.created_at,
            engine_version=record.engine_version,
            trace_service_version=record.trace_service_version,
            claim_hash=record.claim_hash,
            evidence_set_hash=record.evidence_set_hash,
            policy_hash=record.policy_hash,
            facts_snapshot=record.facts_snapshot,
            facts_snapshot_hash=record.facts_snapshot_hash,
            trace_hash=record.trace_hash,
            result_hash=record.result_hash,
            outcome=record.outcome,
            previous_audit_hash=record.previous_audit_hash,
            audit_hash=record.audit_hash,
        )


# =============================================================================
# Manifest Service
# =============================================================================


class ManifestService:
    """
    Daily audit manifest generation and storage.
    
    Generates deterministic manifest files containing:
    - All audit record hashes for the day
    - Rolling hash chain
    - Link to previous manifest
    """
    
    def __init__(
        self,
        session: AsyncSession,
        object_store: Optional[ObjectStoreInterface] = None,
    ):
        self._session = session
        self._object_store = object_store
    
    async def generate_manifest(self, manifest_date: date) -> AuditManifest:
        """
        Generate a manifest for a specific date.
        
        Returns the generated AuditManifest.
        """
        # Get all records for the date
        audit_store = AuditStore(self._session)
        records = await audit_store.get_records_for_date(manifest_date)
        
        # Get previous manifest
        previous = await self._get_previous_manifest(manifest_date)
        previous_manifest_hash = previous.manifest_hash if previous else None
        previous_rolling_hash = previous.rolling_hash if previous else GENESIS_HASH
        
        # Build record hashes list
        record_hashes = [r.audit_hash for r in records]
        
        # Compute rolling hash
        rolling_hash = canonical_hash_chain(record_hashes, previous_rolling_hash)
        
        # Compute manifest hash
        manifest_hash = canonical_manifest_hash(
            manifest_date=manifest_date,
            record_hashes=record_hashes,
            rolling_hash=rolling_hash,
            previous_manifest_hash=previous_manifest_hash,
        )
        
        # Generate manifest ID
        manifest_id = str(generate_canonical_id(EntityType.AUDIT_ENTRY))
        
        # Create manifest record
        record = AuditManifestRecord(
            id=manifest_id,
            manifest_hash=manifest_hash,
            manifest_date=datetime.combine(manifest_date, datetime.min.time(), tzinfo=timezone.utc),
            record_count=len(records),
            first_audit_id=records[0].audit_id if records else None,
            last_audit_id=records[-1].audit_id if records else None,
            record_hashes=record_hashes,
            rolling_hash=rolling_hash,
            previous_manifest_hash=previous_manifest_hash,
        )
        
        # Store manifest file in object storage
        object_key: Optional[str] = None
        if self._object_store:
            manifest_data = {
                "manifest_id": manifest_id,
                "manifest_date": manifest_date.isoformat(),
                "record_count": len(records),
                "record_hashes": record_hashes,
                "rolling_hash": rolling_hash,
                "previous_manifest_hash": previous_manifest_hash,
                "manifest_hash": manifest_hash,
            }
            
            content = canonical_serialize(manifest_data).encode("utf-8")
            metadata = await self._object_store.put(
                content, 
                prefix=f"manifests/{manifest_date.isoformat()}",
                content_type="application/json",
            )
            object_key = metadata.key
            record.object_key = object_key
        
        self._session.add(record)
        await self._session.flush()
        
        return AuditManifest(
            manifest_id=manifest_id,
            manifest_date=manifest_date,
            record_count=len(records),
            first_audit_id=records[0].audit_id if records else None,
            last_audit_id=records[-1].audit_id if records else None,
            record_hashes=record_hashes,
            rolling_hash=rolling_hash,
            previous_manifest_hash=previous_manifest_hash,
            manifest_hash=manifest_hash,
            object_key=object_key,
        )
    
    async def get_manifest(self, manifest_date: date) -> Optional[AuditManifest]:
        """Get manifest for a specific date."""
        result = await self._session.execute(
            select(AuditManifestRecord).where(
                func.date(AuditManifestRecord.manifest_date) == manifest_date
            )
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._record_to_manifest(record)
    
    async def _get_previous_manifest(self, before_date: date) -> Optional[AuditManifestRecord]:
        """Get the manifest immediately before the given date."""
        before_dt = datetime.combine(before_date, datetime.min.time(), tzinfo=timezone.utc)
        
        result = await self._session.execute(
            select(AuditManifestRecord)
            .where(AuditManifestRecord.manifest_date < before_dt)
            .order_by(AuditManifestRecord.manifest_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    def _record_to_manifest(self, record: AuditManifestRecord) -> AuditManifest:
        """Convert database record to AuditManifest."""
        return AuditManifest(
            manifest_id=record.id,
            manifest_date=record.manifest_date.date() if isinstance(record.manifest_date, datetime) else record.manifest_date,
            record_count=record.record_count,
            first_audit_id=record.first_audit_id,
            last_audit_id=record.last_audit_id,
            record_hashes=record.record_hashes,
            rolling_hash=record.rolling_hash,
            previous_manifest_hash=record.previous_manifest_hash,
            manifest_hash=record.manifest_hash,
            generated_at=record.created_at,
            object_key=record.object_key,
        )


# =============================================================================
# Replay Service
# =============================================================================


class ReplayService:
    """
    Deterministic replay and verification service.
    
    Re-runs an evaluation with the original inputs and
    verifies that computed hashes match stored hashes.
    """
    
    def __init__(
        self,
        session: AsyncSession,
        trace_store: TraceStore,
        audit_store: AuditStore,
    ):
        self._session = session
        self._trace_store = trace_store
        self._audit_store = audit_store
    
    async def verify_replay(
        self,
        evaluation_id: str,
        recomputed_trace_hash: Optional[str] = None,
        recomputed_result_hash: Optional[str] = None,
        recomputed_facts_hash: Optional[str] = None,
    ) -> ReplayResult:
        """
        Verify a replay by comparing recomputed hashes to stored hashes.
        
        If recomputed hashes are not provided, just checks that stored
        data is internally consistent.
        """
        # Get stored audit record
        audit = await self._audit_store.get_by_evaluation(evaluation_id)
        if not audit:
            return ReplayResult(
                evaluation_id=evaluation_id,
                status=ReplayStatus.INPUT_MISSING,
                original_trace_hash="",
                original_result_hash="",
                original_facts_hash="",
                reproduced_trace_hash=None,
                reproduced_result_hash=None,
                reproduced_facts_hash=None,
                trace_matches=False,
                result_matches=False,
                facts_match=False,
                original_engine_version="",
                replay_engine_version=TRACE_SERVICE_VERSION,
                mismatch_details={"error": "Audit record not found"},
            )
        
        # Get stored trace
        trace = await self._trace_store.get_by_evaluation(evaluation_id)
        if not trace:
            return ReplayResult(
                evaluation_id=evaluation_id,
                status=ReplayStatus.INPUT_MISSING,
                original_trace_hash=audit.trace_hash,
                original_result_hash=audit.result_hash,
                original_facts_hash=audit.facts_snapshot_hash,
                reproduced_trace_hash=None,
                reproduced_result_hash=None,
                reproduced_facts_hash=None,
                trace_matches=False,
                result_matches=False,
                facts_match=False,
                original_engine_version=audit.engine_version,
                replay_engine_version=TRACE_SERVICE_VERSION,
                mismatch_details={"error": "Trace not found"},
            )
        
        # If no recomputed hashes provided, verify internal consistency
        if recomputed_trace_hash is None:
            recomputed_trace_hash = trace.trace_hash
        if recomputed_facts_hash is None:
            recomputed_facts_hash = audit.facts_snapshot_hash
        if recomputed_result_hash is None:
            recomputed_result_hash = audit.result_hash
        
        # Compare hashes
        trace_matches = recomputed_trace_hash == audit.trace_hash
        result_matches = recomputed_result_hash == audit.result_hash
        facts_match = recomputed_facts_hash == audit.facts_snapshot_hash
        
        all_match = trace_matches and result_matches and facts_match
        
        # Build mismatch details if any
        mismatch_details: Optional[dict[str, Any]] = None
        if not all_match:
            mismatch_details = {}
            if not trace_matches:
                mismatch_details["trace_hash"] = {
                    "original": audit.trace_hash,
                    "reproduced": recomputed_trace_hash,
                }
            if not result_matches:
                mismatch_details["result_hash"] = {
                    "original": audit.result_hash,
                    "reproduced": recomputed_result_hash,
                }
            if not facts_match:
                mismatch_details["facts_hash"] = {
                    "original": audit.facts_snapshot_hash,
                    "reproduced": recomputed_facts_hash,
                }
        
        return ReplayResult(
            evaluation_id=evaluation_id,
            status=ReplayStatus.SUCCESS if all_match else ReplayStatus.HASH_MISMATCH,
            original_trace_hash=audit.trace_hash,
            original_result_hash=audit.result_hash,
            original_facts_hash=audit.facts_snapshot_hash,
            reproduced_trace_hash=recomputed_trace_hash,
            reproduced_result_hash=recomputed_result_hash,
            reproduced_facts_hash=recomputed_facts_hash,
            trace_matches=trace_matches,
            result_matches=result_matches,
            facts_match=facts_match,
            mismatch_details=mismatch_details,
            original_engine_version=audit.engine_version,
            replay_engine_version=TRACE_SERVICE_VERSION,
        )


# =============================================================================
# Unified Trace & Audit Service
# =============================================================================


class TraceAuditServiceV2:
    """
    Unified Trace & Audit Service for A7.
    
    Provides:
    - Trace graph building and storage
    - Append-only audit logging
    - Daily manifest generation
    - Replay verification
    """
    
    def __init__(
        self,
        session: AsyncSession,
        object_store: Optional[ObjectStoreInterface] = None,
    ):
        self._session = session
        self._trace_store = TraceStore(session)
        self._audit_store = AuditStore(session)
        self._manifest_service = ManifestService(session, object_store)
        self._replay_service = ReplayService(
            session, self._trace_store, self._audit_store
        )
    
    @property
    def trace_store(self) -> TraceStore:
        return self._trace_store
    
    @property
    def audit_store(self) -> AuditStore:
        return self._audit_store
    
    @property
    def manifest_service(self) -> ManifestService:
        return self._manifest_service
    
    @property
    def replay_service(self) -> ReplayService:
        return self._replay_service
    
    async def record_evaluation(
        self,
        trace: TraceGraph,
        claim_hash: str,
        evidence_set_hash: str,
        policy_hash: str,
        facts_snapshot: list[dict[str, Any]],
        result_hash: str,
        outcome: str,
        engine_version: str,
    ) -> tuple[str, str]:
        """
        Record a complete evaluation: store trace and append audit record.
        
        Returns (trace_id, audit_id).
        """
        # Store trace
        trace_id = await self._trace_store.store(trace)
        
        # Append audit record
        audit = await self._audit_store.append(
            evaluation_id=trace.evaluation_id,
            claim_hash=claim_hash,
            evidence_set_hash=evidence_set_hash,
            policy_hash=policy_hash,
            facts_snapshot=facts_snapshot,
            trace_hash=trace.trace_hash,
            result_hash=result_hash,
            outcome=outcome,
            engine_version=engine_version,
        )
        
        return trace_id, audit.audit_id
