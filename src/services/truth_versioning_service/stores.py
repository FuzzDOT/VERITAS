"""
Truth Versioning Service - Storage Layer
==========================================

Production-grade implementation of truth version storage:
- TruthVersionStore: CRUD for truth versions
- RecomputeQueue: Persistent task queue
- ClaimClassIndex: Impact analysis index

All operations are deterministic and maintain referential integrity.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import select, func, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import deterministic_hash

from infrastructure.postgres.models import (
    TruthVersionRecord,
    RecomputeTaskRecord,
    ClaimClassIndexRecord,
    TraceGraphRecord,
    AuditLogRecord,
)

from .schemas import (
    TRUTH_VERSION_SERVICE_VERSION,
    TruthVersion,
    TruthVersionStatus,
    ClaimClassKey,
    ProbabilityIntervalSummary,
    KeyRisk,
    RecomputeTask,
    RecomputeTaskStatus,
    ImpactedClaimClass,
    bucket_horizon,
    bucket_as_of_date,
)


# =============================================================================
# Truth Version Store
# =============================================================================


class TruthVersionStore:
    """
    Persistent storage for truth versions.
    
    Truth versions are immutable once created. Updates create new versions
    with supersession links.
    """
    
    def __init__(self, session: AsyncSession):
        self._session = session
    
    async def store(self, version: TruthVersion) -> str:
        """
        Store a truth version.
        
        Returns the truth version ID.
        """
        record = TruthVersionRecord(
            id=version.truth_version_id,
            claim_class_key=version.claim_class_key.key,
            claim_class_components=version.claim_class_key.model_dump(mode="json"),
            canonical_claim_hash=version.canonical_claim_hash,
            canonical_claim_summary=version.canonical_claim_summary,
            evaluation_id=version.evaluation_id,
            conclusion=version.conclusion,
            refusal_code=version.refusal_code,
            refusal_message=version.refusal_message,
            probability_interval=(
                version.probability_interval.model_dump(mode="json")
                if version.probability_interval else None
            ),
            fragility_score=(
                str(version.fragility_score) if version.fragility_score else None
            ),
            key_risks=[r.model_dump(mode="json") for r in version.key_risks],
            top_sensitivity_driver=version.top_sensitivity_driver,
            engine_version=version.engine_version,
            evidence_set_hash=version.evidence_set_hash,
            facts_snapshot_hash=version.facts_snapshot_hash,
            policy_hash=version.policy_hash,
            trace_hash=version.trace_hash,
            result_hash=version.result_hash,
            version_number=version.version_number,
            status=version.status.value,
            supersedes_truth_version_id=version.supersedes_truth_version_id,
            superseded_by_truth_version_id=version.superseded_by_truth_version_id,
            truth_service_version=version.truth_service_version,
        )
        
        self._session.add(record)
        await self._session.flush()
        
        return version.truth_version_id
    
    async def get(self, truth_version_id: str) -> Optional[TruthVersion]:
        """Get a truth version by ID."""
        result = await self._session.execute(
            select(TruthVersionRecord).where(
                TruthVersionRecord.id == truth_version_id
            )
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._record_to_version(record)
    
    async def get_by_evaluation(self, evaluation_id: str) -> Optional[TruthVersion]:
        """Get truth version by evaluation ID."""
        result = await self._session.execute(
            select(TruthVersionRecord).where(
                TruthVersionRecord.evaluation_id == evaluation_id
            )
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._record_to_version(record)
    
    async def get_current(self, claim_class_key: str) -> Optional[TruthVersion]:
        """Get the current (latest non-superseded) version for a claim class."""
        result = await self._session.execute(
            select(TruthVersionRecord)
            .where(TruthVersionRecord.claim_class_key == claim_class_key)
            .where(TruthVersionRecord.status == TruthVersionStatus.CURRENT.value)
            .order_by(TruthVersionRecord.version_number.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._record_to_version(record)
    
    async def get_history(
        self,
        claim_class_key: str,
        offset: int = 0,
        limit: int = 50,
        include_superseded: bool = True,
    ) -> tuple[list[TruthVersion], int]:
        """Get version history for a claim class."""
        query = select(TruthVersionRecord).where(
            TruthVersionRecord.claim_class_key == claim_class_key
        )
        
        if not include_superseded:
            query = query.where(
                TruthVersionRecord.status == TruthVersionStatus.CURRENT.value
            )
        
        # Get total count
        count_query = select(func.count(TruthVersionRecord.id)).where(
            TruthVersionRecord.claim_class_key == claim_class_key
        )
        if not include_superseded:
            count_query = count_query.where(
                TruthVersionRecord.status == TruthVersionStatus.CURRENT.value
            )
        count_result = await self._session.execute(count_query)
        total = count_result.scalar() or 0
        
        # Get paginated results
        query = query.order_by(
            TruthVersionRecord.version_number.desc()
        ).offset(offset).limit(limit)
        
        result = await self._session.execute(query)
        records = result.scalars().all()
        
        return [self._record_to_version(r) for r in records], total
    
    async def get_next_version_number(self, claim_class_key: str) -> int:
        """Get the next version number for a claim class."""
        result = await self._session.execute(
            select(func.max(TruthVersionRecord.version_number)).where(
                TruthVersionRecord.claim_class_key == claim_class_key
            )
        )
        max_version = result.scalar()
        return (max_version or 0) + 1
    
    async def mark_superseded(
        self,
        truth_version_id: str,
        superseded_by_id: str,
    ) -> None:
        """Mark a version as superseded by another."""
        await self._session.execute(
            update(TruthVersionRecord)
            .where(TruthVersionRecord.id == truth_version_id)
            .values(
                status=TruthVersionStatus.SUPERSEDED.value,
                superseded_by_truth_version_id=superseded_by_id,
            )
        )
        await self._session.flush()
    
    async def find_matching_version(
        self,
        claim_class_key: str,
        evidence_set_hash: str,
        facts_snapshot_hash: str,
        policy_hash: str,
        engine_version: str,
    ) -> Optional[TruthVersion]:
        """
        Find an existing version with matching hashes (for deduplication).
        """
        result = await self._session.execute(
            select(TruthVersionRecord)
            .where(TruthVersionRecord.claim_class_key == claim_class_key)
            .where(TruthVersionRecord.evidence_set_hash == evidence_set_hash)
            .where(TruthVersionRecord.facts_snapshot_hash == facts_snapshot_hash)
            .where(TruthVersionRecord.policy_hash == policy_hash)
            .where(TruthVersionRecord.engine_version == engine_version)
            .order_by(TruthVersionRecord.created_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return None
        
        return self._record_to_version(record)
    
    def _record_to_version(self, record: TruthVersionRecord) -> TruthVersion:
        """Convert database record to TruthVersion."""
        # Parse claim class components
        components = record.claim_class_components
        claim_class_key = ClaimClassKey(
            entity_id=components["entity_id"],
            entity_id_type=components["entity_id_type"],
            jurisdiction=components["jurisdiction"],
            scenario_name=components["scenario_name"],
            scenario_shocks_hash=components["scenario_shocks_hash"],
            horizon_bucket=components["horizon_bucket"],
            as_of_date_bucket=date.fromisoformat(components["as_of_date_bucket"]),
            key=record.claim_class_key,
        )
        
        # Parse probability interval
        probability_interval = None
        if record.probability_interval:
            probability_interval = ProbabilityIntervalSummary(
                p_low=Decimal(str(record.probability_interval["p_low"])),
                p_mid=Decimal(str(record.probability_interval["p_mid"])),
                p_high=Decimal(str(record.probability_interval["p_high"])),
            )
        
        # Parse key risks
        key_risks = [KeyRisk(**r) for r in record.key_risks]
        
        return TruthVersion(
            truth_version_id=record.id,
            created_at=record.created_at,
            claim_class_key=claim_class_key,
            canonical_claim_hash=record.canonical_claim_hash,
            canonical_claim_summary=record.canonical_claim_summary,
            evaluation_id=record.evaluation_id,
            conclusion=record.conclusion,
            refusal_code=record.refusal_code,
            refusal_message=record.refusal_message,
            probability_interval=probability_interval,
            fragility_score=(
                Decimal(record.fragility_score) if record.fragility_score else None
            ),
            key_risks=key_risks,
            top_sensitivity_driver=record.top_sensitivity_driver,
            engine_version=record.engine_version,
            evidence_set_hash=record.evidence_set_hash,
            facts_snapshot_hash=record.facts_snapshot_hash,
            policy_hash=record.policy_hash,
            trace_hash=record.trace_hash,
            result_hash=record.result_hash,
            version_number=record.version_number,
            status=TruthVersionStatus(record.status),
            supersedes_truth_version_id=record.supersedes_truth_version_id,
            superseded_by_truth_version_id=record.superseded_by_truth_version_id,
            truth_service_version=record.truth_service_version,
        )


# =============================================================================
# Recompute Queue
# =============================================================================


class RecomputeQueue:
    """
    Persistent queue for recomputation tasks.
    
    Tasks are created when evidence or facts change and need to
    trigger re-evaluation of affected claim classes.
    """
    
    def __init__(self, session: AsyncSession):
        self._session = session
    
    async def enqueue(
        self,
        claim_class_key: str,
        trigger_reason: str,
        triggered_by_evidence_id: Optional[str] = None,
        triggered_by_entity_id: Optional[str] = None,
        current_truth_version_id: Optional[str] = None,
        priority: int = 5,
    ) -> RecomputeTask:
        """
        Enqueue a recomputation task.
        
        Returns the created task.
        """
        task_id = str(generate_canonical_id(EntityType.TASK))
        
        record = RecomputeTaskRecord(
            id=task_id,
            claim_class_key=claim_class_key,
            current_truth_version_id=current_truth_version_id,
            triggered_by_evidence_id=triggered_by_evidence_id,
            triggered_by_entity_id=triggered_by_entity_id,
            trigger_reason=trigger_reason,
            status=RecomputeTaskStatus.PENDING.value,
            priority=priority,
        )
        
        self._session.add(record)
        await self._session.flush()
        
        return RecomputeTask(
            task_id=task_id,
            claim_class_key=claim_class_key,
            current_truth_version_id=current_truth_version_id,
            triggered_by_evidence_id=triggered_by_evidence_id,
            triggered_by_entity_id=triggered_by_entity_id,
            trigger_reason=trigger_reason,
            status=RecomputeTaskStatus.PENDING,
            created_at=record.created_at,
            priority=priority,
        )
    
    async def get_pending_tasks(
        self,
        limit: int = 100,
    ) -> list[RecomputeTask]:
        """Get pending tasks ordered by priority and creation time."""
        result = await self._session.execute(
            select(RecomputeTaskRecord)
            .where(RecomputeTaskRecord.status == RecomputeTaskStatus.PENDING.value)
            .order_by(
                RecomputeTaskRecord.priority.asc(),
                RecomputeTaskRecord.created_at.asc(),
            )
            .limit(limit)
        )
        records = result.scalars().all()
        
        return [self._record_to_task(r) for r in records]
    
    async def mark_in_progress(self, task_id: str) -> None:
        """Mark a task as in progress."""
        await self._session.execute(
            update(RecomputeTaskRecord)
            .where(RecomputeTaskRecord.id == task_id)
            .values(
                status=RecomputeTaskStatus.IN_PROGRESS.value,
                started_at=datetime.now(timezone.utc),
            )
        )
        await self._session.flush()
    
    async def mark_completed(
        self,
        task_id: str,
        result_evaluation_id: Optional[str] = None,
    ) -> None:
        """Mark a task as completed."""
        await self._session.execute(
            update(RecomputeTaskRecord)
            .where(RecomputeTaskRecord.id == task_id)
            .values(
                status=RecomputeTaskStatus.COMPLETED.value,
                completed_at=datetime.now(timezone.utc),
                result_evaluation_id=result_evaluation_id,
            )
        )
        await self._session.flush()
    
    async def mark_failed(
        self,
        task_id: str,
        error_message: str,
    ) -> None:
        """Mark a task as failed."""
        await self._session.execute(
            update(RecomputeTaskRecord)
            .where(RecomputeTaskRecord.id == task_id)
            .values(
                status=RecomputeTaskStatus.FAILED.value,
                completed_at=datetime.now(timezone.utc),
                error_message=error_message,
            )
        )
        await self._session.flush()
    
    async def task_exists_for_claim_class(
        self,
        claim_class_key: str,
        statuses: Optional[Sequence[RecomputeTaskStatus]] = None,
    ) -> bool:
        """Check if a task already exists for a claim class."""
        if statuses is None:
            statuses = [RecomputeTaskStatus.PENDING, RecomputeTaskStatus.IN_PROGRESS]
        
        result = await self._session.execute(
            select(func.count(RecomputeTaskRecord.id))
            .where(RecomputeTaskRecord.claim_class_key == claim_class_key)
            .where(RecomputeTaskRecord.status.in_([s.value for s in statuses]))
        )
        count = result.scalar()
        return count > 0 if count else False
    
    def _record_to_task(self, record: RecomputeTaskRecord) -> RecomputeTask:
        """Convert database record to RecomputeTask."""
        return RecomputeTask(
            task_id=record.id,
            claim_class_key=record.claim_class_key,
            current_truth_version_id=record.current_truth_version_id,
            triggered_by_evidence_id=record.triggered_by_evidence_id,
            triggered_by_entity_id=record.triggered_by_entity_id,
            trigger_reason=record.trigger_reason,
            status=RecomputeTaskStatus(record.status),
            created_at=record.created_at,
            priority=record.priority,
        )


# =============================================================================
# Claim Class Index
# =============================================================================


class ClaimClassIndex:
    """
    Index for fast impact analysis.
    
    Maps entities and evidence to their associated claim classes.
    """
    
    def __init__(self, session: AsyncSession):
        self._session = session
    
    async def update_index(
        self,
        claim_class_key: str,
        entity_id: str,
        entity_id_type: str,
        evidence_ids: list[str],
        as_of_date_bucket: date,
        current_truth_version_id: Optional[str] = None,
    ) -> None:
        """
        Update or insert index entry for a claim class.
        """
        # Check if exists
        result = await self._session.execute(
            select(ClaimClassIndexRecord).where(
                ClaimClassIndexRecord.claim_class_key == claim_class_key
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing
            await self._session.execute(
                update(ClaimClassIndexRecord)
                .where(ClaimClassIndexRecord.claim_class_key == claim_class_key)
                .values(
                    evidence_ids=evidence_ids,
                    current_truth_version_id=current_truth_version_id,
                )
            )
        else:
            # Insert new
            record = ClaimClassIndexRecord(
                id=str(generate_canonical_id(EntityType.TASK)),
                claim_class_key=claim_class_key,
                entity_id=entity_id,
                entity_id_type=entity_id_type,
                evidence_ids=evidence_ids,
                as_of_date_bucket=datetime.combine(
                    as_of_date_bucket, datetime.min.time(), tzinfo=timezone.utc
                ),
                current_truth_version_id=current_truth_version_id,
            )
            self._session.add(record)
        
        await self._session.flush()
    
    async def find_by_entity(
        self,
        entity_id: str,
        entity_id_type: str,
        date_range_start: Optional[date] = None,
        date_range_end: Optional[date] = None,
    ) -> list[ImpactedClaimClass]:
        """Find claim classes by entity."""
        query = (
            select(ClaimClassIndexRecord)
            .where(ClaimClassIndexRecord.entity_id == entity_id.upper())
            .where(ClaimClassIndexRecord.entity_id_type == entity_id_type.upper())
        )
        
        if date_range_start:
            start_dt = datetime.combine(
                date_range_start, datetime.min.time(), tzinfo=timezone.utc
            )
            query = query.where(ClaimClassIndexRecord.as_of_date_bucket >= start_dt)
        
        if date_range_end:
            end_dt = datetime.combine(
                date_range_end, datetime.max.time(), tzinfo=timezone.utc
            )
            query = query.where(ClaimClassIndexRecord.as_of_date_bucket <= end_dt)
        
        result = await self._session.execute(query)
        records = result.scalars().all()
        
        return [
            ImpactedClaimClass(
                claim_class_key=r.claim_class_key,
                current_truth_version_id=r.current_truth_version_id,
                impact_reason=f"Entity {entity_id_type}:{entity_id} updated",
                priority=3,
            )
            for r in records
        ]
    
    async def find_by_evidence(
        self,
        evidence_id: str,
    ) -> list[ImpactedClaimClass]:
        """Find claim classes that used a specific evidence ID."""
        # Use JSONB contains operator
        result = await self._session.execute(
            select(ClaimClassIndexRecord).where(
                ClaimClassIndexRecord.evidence_ids.contains([evidence_id])
            )
        )
        records = result.scalars().all()
        
        return [
            ImpactedClaimClass(
                claim_class_key=r.claim_class_key,
                current_truth_version_id=r.current_truth_version_id,
                impact_reason=f"Evidence {evidence_id} updated",
                priority=2,
            )
            for r in records
        ]


# =============================================================================
# Verification Helpers
# =============================================================================


class ReplayVerifier:
    """
    Verifies that an evaluation has trace and audit records
    and is replay-verified.
    """
    
    def __init__(self, session: AsyncSession):
        self._session = session
    
    async def verify_evaluation(
        self,
        evaluation_id: str,
    ) -> tuple[bool, str, Optional[dict[str, Any]]]:
        """
        Verify an evaluation is suitable for promotion.
        
        Returns (is_valid, message, audit_data).
        """
        # Check trace exists
        trace_result = await self._session.execute(
            select(TraceGraphRecord).where(
                TraceGraphRecord.evaluation_id == evaluation_id
            )
        )
        trace = trace_result.scalar_one_or_none()
        
        if not trace:
            return False, "No trace record found for evaluation", None
        
        # Check audit exists
        audit_result = await self._session.execute(
            select(AuditLogRecord).where(
                AuditLogRecord.evaluation_id == evaluation_id
            )
        )
        audit = audit_result.scalar_one_or_none()
        
        if not audit:
            return False, "No audit record found for evaluation", None
        
        # Verify trace hash matches audit reference
        if trace.trace_hash != audit.trace_hash:
            return False, "Trace hash mismatch with audit record", None
        
        # Build audit data for promotion
        audit_data = {
            "evaluation_id": evaluation_id,
            "claim_hash": audit.claim_hash,
            "evidence_set_hash": audit.evidence_set_hash,
            "policy_hash": audit.policy_hash,
            "facts_snapshot": audit.facts_snapshot,
            "facts_snapshot_hash": audit.facts_snapshot_hash,
            "trace_hash": audit.trace_hash,
            "result_hash": audit.result_hash,
            "outcome": audit.outcome,
            "engine_version": audit.engine_version,
        }
        
        return True, "Evaluation verified", audit_data
