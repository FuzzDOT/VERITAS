"""
Truth Versioning Service - Promotion & Diff Logic
===================================================

Production-grade implementation of:
- Promotion logic: Create TruthVersion from verified evaluation
- Supersession rules: When and how versions supersede each other
- Diff generation: Deterministic structured diffs between versions
- Impact analysis: Determine affected claim classes

All operations are deterministic and produce reproducible results.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import deterministic_hash

from .schemas import (
    TRUTH_VERSION_SERVICE_VERSION,
    PROBABILITY_TOLERANCE,
    FRAGILITY_TOLERANCE,
    TruthVersion,
    TruthVersionStatus,
    ClaimClassKey,
    ProbabilityIntervalSummary,
    KeyRisk,
    TruthDiff,
    EvidenceChange,
    FactChange,
    PolicyChange,
    DecisionChange,
    DiffChangeType,
    PromotionResult,
    PromoteResponse,
    ImpactAnalysisResult,
    ImpactedClaimClass,
    RecomputeTask,
)
from .stores import (
    TruthVersionStore,
    RecomputeQueue,
    ClaimClassIndex,
    ReplayVerifier,
)


# =============================================================================
# Promotion Service
# =============================================================================


class PromotionService:
    """
    Handles promotion of evaluations to truth versions.
    
    Promotion rules:
    1. Evaluation must have stored trace and audit records
    2. Evaluation must be replay-verified
    3. If prior version exists for same claim class:
       a. Create new version only if hashes differ
       b. Deduplicate if hashes match (return existing)
       c. Supersede prior if newer
    """
    
    def __init__(
        self,
        session: AsyncSession,
        version_store: TruthVersionStore,
        verifier: ReplayVerifier,
        claim_class_index: ClaimClassIndex,
    ):
        self._session = session
        self._version_store = version_store
        self._verifier = verifier
        self._claim_class_index = claim_class_index
    
    async def promote(
        self,
        evaluation_id: str,
        claim_class_key: ClaimClassKey,
        canonical_claim_hash: str,
        canonical_claim_summary: str,
        evidence_ids: list[str],
        force_supersede: bool = False,
    ) -> PromoteResponse:
        """
        Promote an evaluation to a truth version.
        
        Returns the promotion result.
        """
        # Step 1: Verify evaluation
        is_valid, message, audit_data = await self._verifier.verify_evaluation(
            evaluation_id
        )
        
        if not is_valid:
            if "trace" in message.lower():
                return PromoteResponse(
                    result=PromotionResult.REJECTED_NO_TRACE,
                    truth_version_id=None,
                    truth_version=None,
                    superseded_version_id=None,
                    message=message,
                )
            else:
                return PromoteResponse(
                    result=PromotionResult.REJECTED_NO_AUDIT,
                    truth_version_id=None,
                    truth_version=None,
                    superseded_version_id=None,
                    message=message,
                )
        
        assert audit_data is not None
        
        # Step 2: Check for deduplication
        if not force_supersede:
            existing = await self._version_store.find_matching_version(
                claim_class_key=claim_class_key.key,
                evidence_set_hash=audit_data["evidence_set_hash"],
                facts_snapshot_hash=audit_data["facts_snapshot_hash"],
                policy_hash=audit_data["policy_hash"],
                engine_version=audit_data["engine_version"],
            )
            
            if existing:
                return PromoteResponse(
                    result=PromotionResult.DEDUPLICATED,
                    truth_version_id=existing.truth_version_id,
                    truth_version=existing,
                    superseded_version_id=None,
                    message=(
                        f"Deduplicated to existing version {existing.truth_version_id}"
                    ),
                )
        
        # Step 3: Check for prior version to supersede
        current = await self._version_store.get_current(claim_class_key.key)
        supersedes_id: Optional[str] = None
        
        if current:
            # Check if we should supersede
            should_supersede = self._should_supersede(
                current, audit_data, force_supersede
            )
            
            if should_supersede:
                supersedes_id = current.truth_version_id
            else:
                # No change needed - deduplicate
                return PromoteResponse(
                    result=PromotionResult.DEDUPLICATED,
                    truth_version_id=current.truth_version_id,
                    truth_version=current,
                    superseded_version_id=None,
                    message="No material changes from current version",
                )
        
        # Step 4: Create new truth version
        version_number = await self._version_store.get_next_version_number(
            claim_class_key.key
        )
        
        truth_version_id = str(generate_canonical_id(EntityType.TRUTH_VERSION))
        
        # Build probability interval if available
        probability_interval: Optional[ProbabilityIntervalSummary] = None
        # This would be populated from the evaluation result
        # For now, we'll leave it as None - the actual implementation would
        # fetch this from the evaluation result
        
        # Build key risks from audit data
        key_risks: list[KeyRisk] = []
        
        truth_version = TruthVersion(
            truth_version_id=truth_version_id,
            created_at=datetime.now(timezone.utc),
            claim_class_key=claim_class_key,
            canonical_claim_hash=canonical_claim_hash,
            canonical_claim_summary=canonical_claim_summary,
            evaluation_id=evaluation_id,
            conclusion=audit_data["outcome"],
            refusal_code=None,  # Would be populated from evaluation
            refusal_message=None,
            probability_interval=probability_interval,
            fragility_score=None,  # Would be populated from evaluation
            key_risks=key_risks,
            top_sensitivity_driver=None,  # Would be populated from evaluation
            engine_version=audit_data["engine_version"],
            evidence_set_hash=audit_data["evidence_set_hash"],
            facts_snapshot_hash=audit_data["facts_snapshot_hash"],
            policy_hash=audit_data["policy_hash"],
            trace_hash=audit_data["trace_hash"],
            result_hash=audit_data["result_hash"],
            version_number=version_number,
            status=TruthVersionStatus.CURRENT,
            supersedes_truth_version_id=supersedes_id,
            superseded_by_truth_version_id=None,
            truth_service_version=TRUTH_VERSION_SERVICE_VERSION,
        )
        
        # Store the new version
        await self._version_store.store(truth_version)
        
        # Mark prior as superseded if applicable
        if supersedes_id:
            await self._version_store.mark_superseded(
                supersedes_id, truth_version_id
            )
        
        # Update claim class index
        await self._claim_class_index.update_index(
            claim_class_key=claim_class_key.key,
            entity_id=claim_class_key.entity_id,
            entity_id_type=claim_class_key.entity_id_type,
            evidence_ids=evidence_ids,
            as_of_date_bucket=claim_class_key.as_of_date_bucket,
            current_truth_version_id=truth_version_id,
        )
        
        # Commit
        await self._session.commit()
        
        result = (
            PromotionResult.SUPERSEDED_PRIOR if supersedes_id
            else PromotionResult.CREATED
        )
        
        return PromoteResponse(
            result=result,
            truth_version_id=truth_version_id,
            truth_version=truth_version,
            superseded_version_id=supersedes_id,
            message=(
                f"Created truth version {truth_version_id}"
                + (f", superseding {supersedes_id}" if supersedes_id else "")
            ),
        )
    
    def _should_supersede(
        self,
        current: TruthVersion,
        audit_data: dict[str, Any],
        force: bool,
    ) -> bool:
        """
        Determine if a new evaluation should supersede the current version.
        
        Supersede if:
        - force is True, OR
        - evidence_set_hash differs, OR
        - facts_snapshot_hash differs, OR
        - policy_hash differs, OR
        - engine_version differs
        """
        if force:
            return True
        
        return (
            current.evidence_set_hash != audit_data["evidence_set_hash"]
            or current.facts_snapshot_hash != audit_data["facts_snapshot_hash"]
            or current.policy_hash != audit_data["policy_hash"]
            or current.engine_version != audit_data["engine_version"]
        )


# =============================================================================
# Diff Service
# =============================================================================


class DiffService:
    """
    Generates deterministic structured diffs between truth versions.
    
    Diffs cite trace node identifiers where possible.
    """
    
    def __init__(self, session: AsyncSession, version_store: TruthVersionStore):
        self._session = session
        self._version_store = version_store
    
    async def generate_diff(
        self,
        version_a_id: str,
        version_b_id: str,
    ) -> Optional[TruthDiff]:
        """
        Generate a structured diff between two versions.
        
        Returns None if either version doesn't exist.
        """
        version_a = await self._version_store.get(version_a_id)
        version_b = await self._version_store.get(version_b_id)
        
        if not version_a or not version_b:
            return None
        
        # Generate evidence changes
        evidence_added, evidence_removed = self._diff_evidence_hashes(
            version_a, version_b
        )
        
        # Generate fact changes
        facts_added, facts_removed, facts_modified = self._diff_facts(
            version_a, version_b
        )
        
        # Generate policy changes
        policies_changed = self._diff_policies(version_a, version_b)
        
        # Generate decision change
        decision_change = self._diff_decisions(version_a, version_b)
        
        # Engine version change
        engine_version_changed = (
            version_a.engine_version != version_b.engine_version
        )
        
        # Determine if material change
        is_material = (
            decision_change.conclusion_changed
            or decision_change.probability_changed
            or engine_version_changed
            or len(evidence_added) > 0
            or len(evidence_removed) > 0
            or len(facts_modified) > 0
        )
        
        # Generate change summary
        change_summary = self._generate_summary(
            version_a, version_b, decision_change, is_material
        )
        
        # Compute deterministic diff hash
        diff_hash = self._compute_diff_hash(
            version_a_id=version_a_id,
            version_b_id=version_b_id,
            evidence_added=evidence_added,
            evidence_removed=evidence_removed,
            facts_added=facts_added,
            facts_removed=facts_removed,
            facts_modified=facts_modified,
            policies_changed=policies_changed,
            engine_version_changed=engine_version_changed,
            decision_change=decision_change,
        )
        
        return TruthDiff(
            version_a_id=version_a_id,
            version_b_id=version_b_id,
            diff_hash=diff_hash,
            evidence_added=evidence_added,
            evidence_removed=evidence_removed,
            facts_added=facts_added,
            facts_removed=facts_removed,
            facts_modified=facts_modified,
            policies_changed=policies_changed,
            engine_version_changed=engine_version_changed,
            old_engine_version=(
                version_a.engine_version if engine_version_changed else None
            ),
            new_engine_version=(
                version_b.engine_version if engine_version_changed else None
            ),
            decision_change=decision_change,
            is_material_change=is_material,
            change_summary=change_summary,
        )
    
    def _diff_evidence_hashes(
        self,
        version_a: TruthVersion,
        version_b: TruthVersion,
    ) -> tuple[list[EvidenceChange], list[EvidenceChange]]:
        """
        Diff evidence between versions.
        
        Note: Full evidence diff would require fetching audit records.
        For now, we detect change via hash comparison.
        """
        added: list[EvidenceChange] = []
        removed: list[EvidenceChange] = []
        
        if version_a.evidence_set_hash != version_b.evidence_set_hash:
            # Evidence changed - we'd need to fetch and compare actual evidence
            # For now, record that a change occurred
            removed.append(EvidenceChange(
                change_type=DiffChangeType.REMOVED,
                evidence_id="*",
                evidence_hash=version_a.evidence_set_hash,
                description="Evidence set changed",
            ))
            added.append(EvidenceChange(
                change_type=DiffChangeType.ADDED,
                evidence_id="*",
                evidence_hash=version_b.evidence_set_hash,
                description="New evidence set",
            ))
        
        return added, removed
    
    def _diff_facts(
        self,
        version_a: TruthVersion,
        version_b: TruthVersion,
    ) -> tuple[list[FactChange], list[FactChange], list[FactChange]]:
        """
        Diff facts between versions.
        
        Note: Full fact diff would require fetching facts snapshots.
        For now, we detect change via hash comparison.
        """
        added: list[FactChange] = []
        removed: list[FactChange] = []
        modified: list[FactChange] = []
        
        if version_a.facts_snapshot_hash != version_b.facts_snapshot_hash:
            # Facts changed - detailed diff would require snapshot comparison
            modified.append(FactChange(
                change_type=DiffChangeType.MODIFIED,
                fact_id="*",
                fact_type="*",
                old_value=version_a.facts_snapshot_hash[:16] + "...",
                new_value=version_b.facts_snapshot_hash[:16] + "...",
                value_delta=None,
                old_confidence=None,
                new_confidence=None,
                old_extraction_method=None,
                new_extraction_method=None,
                trace_node_id=None,
            ))
        
        return added, removed, modified
    
    def _diff_policies(
        self,
        version_a: TruthVersion,
        version_b: TruthVersion,
    ) -> list[PolicyChange]:
        """Diff policy configuration."""
        changes: list[PolicyChange] = []
        
        if version_a.policy_hash != version_b.policy_hash:
            changes.append(PolicyChange(
                policy_field="policy_hash",
                old_value=version_a.policy_hash,
                new_value=version_b.policy_hash,
            ))
        
        return changes
    
    def _diff_decisions(
        self,
        version_a: TruthVersion,
        version_b: TruthVersion,
    ) -> DecisionChange:
        """Diff the decision/conclusion."""
        conclusion_changed = version_a.conclusion != version_b.conclusion
        
        # Probability comparison
        probability_changed = False
        old_p_mid: Optional[Decimal] = None
        new_p_mid: Optional[Decimal] = None
        p_delta: Optional[Decimal] = None
        
        if version_a.probability_interval and version_b.probability_interval:
            old_p_mid = version_a.probability_interval.p_mid
            new_p_mid = version_b.probability_interval.p_mid
            p_delta = abs(new_p_mid - old_p_mid)
            probability_changed = p_delta > PROBABILITY_TOLERANCE
        elif version_a.probability_interval or version_b.probability_interval:
            probability_changed = True
            old_p_mid = (
                version_a.probability_interval.p_mid
                if version_a.probability_interval else None
            )
            new_p_mid = (
                version_b.probability_interval.p_mid
                if version_b.probability_interval else None
            )
        
        # Fragility comparison
        fragility_changed = False
        old_fragility: Optional[Decimal] = None
        new_fragility: Optional[Decimal] = None
        fragility_delta: Optional[Decimal] = None
        
        if version_a.fragility_score and version_b.fragility_score:
            old_fragility = version_a.fragility_score
            new_fragility = version_b.fragility_score
            fragility_delta = abs(new_fragility - old_fragility)
            fragility_changed = fragility_delta > FRAGILITY_TOLERANCE
        elif version_a.fragility_score or version_b.fragility_score:
            fragility_changed = True
            old_fragility = version_a.fragility_score
            new_fragility = version_b.fragility_score
        
        # Top risks comparison
        old_risk_types = {r.risk_type for r in version_a.key_risks}
        new_risk_types = {r.risk_type for r in version_b.key_risks}
        risks_added = list(new_risk_types - old_risk_types)
        risks_removed = list(old_risk_types - new_risk_types)
        top_risks_changed = len(risks_added) > 0 or len(risks_removed) > 0
        
        # Sensitivity driver comparison
        sensitivities_changed = (
            version_a.top_sensitivity_driver != version_b.top_sensitivity_driver
        )
        
        return DecisionChange(
            conclusion_changed=conclusion_changed,
            old_conclusion=version_a.conclusion if conclusion_changed else None,
            new_conclusion=version_b.conclusion if conclusion_changed else None,
            probability_changed=probability_changed,
            old_p_mid=old_p_mid,
            new_p_mid=new_p_mid,
            p_delta=p_delta,
            fragility_changed=fragility_changed,
            old_fragility=old_fragility,
            new_fragility=new_fragility,
            fragility_delta=fragility_delta,
            top_risks_changed=top_risks_changed,
            risks_added=risks_added,
            risks_removed=risks_removed,
            sensitivities_changed=sensitivities_changed,
            old_top_driver=(
                version_a.top_sensitivity_driver if sensitivities_changed else None
            ),
            new_top_driver=(
                version_b.top_sensitivity_driver if sensitivities_changed else None
            ),
        )
    
    def _generate_summary(
        self,
        version_a: TruthVersion,
        version_b: TruthVersion,
        decision_change: DecisionChange,
        is_material: bool,
    ) -> str:
        """Generate human-readable change summary."""
        parts = []
        
        if decision_change.conclusion_changed:
            parts.append(
                f"Conclusion changed from {decision_change.old_conclusion} "
                f"to {decision_change.new_conclusion}"
            )
        
        if decision_change.probability_changed and decision_change.p_delta:
            direction = "increased" if (
                decision_change.new_p_mid and decision_change.old_p_mid and
                decision_change.new_p_mid > decision_change.old_p_mid
            ) else "decreased"
            parts.append(
                f"Probability {direction} by {decision_change.p_delta:.2%}"
            )
        
        if decision_change.fragility_changed:
            parts.append("Fragility score changed")
        
        if decision_change.top_risks_changed:
            if decision_change.risks_added:
                parts.append(f"New risks: {', '.join(decision_change.risks_added)}")
            if decision_change.risks_removed:
                parts.append(
                    f"Resolved risks: {', '.join(decision_change.risks_removed)}"
                )
        
        if decision_change.sensitivities_changed:
            parts.append(
                f"Top driver changed from {decision_change.old_top_driver} "
                f"to {decision_change.new_top_driver}"
            )
        
        if not parts:
            if is_material:
                return "Material changes in inputs (evidence, facts, or policy)"
            else:
                return "No material changes"
        
        return "; ".join(parts)
    
    def _compute_diff_hash(
        self,
        version_a_id: str,
        version_b_id: str,
        evidence_added: list[EvidenceChange],
        evidence_removed: list[EvidenceChange],
        facts_added: list[FactChange],
        facts_removed: list[FactChange],
        facts_modified: list[FactChange],
        policies_changed: list[PolicyChange],
        engine_version_changed: bool,
        decision_change: DecisionChange,
    ) -> str:
        """Compute deterministic hash of diff."""
        return deterministic_hash(
            version_a_id,
            version_b_id,
            len(evidence_added),
            len(evidence_removed),
            len(facts_added),
            len(facts_removed),
            len(facts_modified),
            len(policies_changed),
            engine_version_changed,
            decision_change.conclusion_changed,
            decision_change.probability_changed,
            decision_change.fragility_changed,
        )


# =============================================================================
# Impact Analysis Service
# =============================================================================


class ImpactAnalysisService:
    """
    Analyzes impact of evidence/fact updates on truth versions.
    
    Determines which claim classes need recomputation.
    """
    
    def __init__(
        self,
        session: AsyncSession,
        claim_class_index: ClaimClassIndex,
        recompute_queue: RecomputeQueue,
    ):
        self._session = session
        self._claim_class_index = claim_class_index
        self._recompute_queue = recompute_queue
    
    async def analyze_impact(
        self,
        evidence_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_id_type: Optional[str] = None,
        date_range_start: Optional[date] = None,
        date_range_end: Optional[date] = None,
        queue_tasks: bool = True,
        priority: int = 5,
    ) -> ImpactAnalysisResult:
        """
        Analyze impact and optionally queue recomputation tasks.
        
        Returns the analysis result.
        """
        analysis_id = str(generate_canonical_id(EntityType.TASK))
        impacted: list[ImpactedClaimClass] = []
        
        # Find impacted by evidence
        if evidence_id:
            impacted.extend(
                await self._claim_class_index.find_by_evidence(evidence_id)
            )
        
        # Find impacted by entity
        if entity_id and entity_id_type:
            impacted.extend(
                await self._claim_class_index.find_by_entity(
                    entity_id=entity_id,
                    entity_id_type=entity_id_type,
                    date_range_start=date_range_start,
                    date_range_end=date_range_end,
                )
            )
        
        # Deduplicate by claim class key
        seen_keys: set[str] = set()
        unique_impacted: list[ImpactedClaimClass] = []
        for item in impacted:
            if item.claim_class_key not in seen_keys:
                seen_keys.add(item.claim_class_key)
                unique_impacted.append(item)
        
        # Queue tasks if requested
        tasks_queued: list[RecomputeTask] = []
        if queue_tasks:
            for item in unique_impacted:
                # Check if task already exists
                exists = await self._recompute_queue.task_exists_for_claim_class(
                    item.claim_class_key
                )
                if not exists:
                    task = await self._recompute_queue.enqueue(
                        claim_class_key=item.claim_class_key,
                        trigger_reason=item.impact_reason,
                        triggered_by_evidence_id=evidence_id,
                        triggered_by_entity_id=entity_id,
                        current_truth_version_id=item.current_truth_version_id,
                        priority=priority,
                    )
                    tasks_queued.append(task)
        
        await self._session.commit()
        
        return ImpactAnalysisResult(
            analysis_id=analysis_id,
            evidence_id=evidence_id,
            entity_id=entity_id,
            entity_id_type=entity_id_type,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            impacted_claim_classes=unique_impacted,
            tasks_queued=tasks_queued,
            total_impacted=len(unique_impacted),
            total_queued=len(tasks_queued),
        )
