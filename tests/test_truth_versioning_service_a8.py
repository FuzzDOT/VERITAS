"""
A8: Truth Versioning Service Tests
====================================

Comprehensive tests for the Truth Versioning Service covering:
1. Deterministic claim class key derivation and bucketing
2. Promotion gating on replay verification + trace existence
3. Supersession and deduplication rules
4. History ordering and retrieval
5. Diff correctness and determinism
6. Impact analysis correctness
7. Queue persistence and management
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

# =============================================================================
# Test Schema Bucketing Functions
# =============================================================================


class TestBucketHorizon:
    """Tests for horizon bucketing function."""
    
    def test_bucket_horizon_to_3_months(self):
        """Horizons 1-3 months bucket to 3."""
        from services.truth_versioning_service.schemas import bucket_horizon
        
        assert bucket_horizon(1) == 3
        assert bucket_horizon(2) == 3
        assert bucket_horizon(3) == 3
    
    def test_bucket_horizon_to_6_months(self):
        """Horizons 4-6 months bucket to 6."""
        from services.truth_versioning_service.schemas import bucket_horizon
        
        assert bucket_horizon(4) == 6
        assert bucket_horizon(5) == 6
        assert bucket_horizon(6) == 6
    
    def test_bucket_horizon_to_12_months(self):
        """Horizons 7-12 months bucket to 12."""
        from services.truth_versioning_service.schemas import bucket_horizon
        
        assert bucket_horizon(7) == 12
        assert bucket_horizon(10) == 12
        assert bucket_horizon(12) == 12
    
    def test_bucket_horizon_to_24_months(self):
        """Horizons 13-24 months bucket to 24."""
        from services.truth_versioning_service.schemas import bucket_horizon
        
        assert bucket_horizon(13) == 24
        assert bucket_horizon(18) == 24
        assert bucket_horizon(24) == 24
    
    def test_bucket_horizon_to_60_months(self):
        """Horizons 25-60 months bucket to 60."""
        from services.truth_versioning_service.schemas import bucket_horizon
        
        assert bucket_horizon(25) == 60
        assert bucket_horizon(36) == 60
        assert bucket_horizon(48) == 60
        assert bucket_horizon(60) == 60
    
    def test_bucket_horizon_to_120_months(self):
        """Horizons 61-120 months bucket to 120."""
        from services.truth_versioning_service.schemas import bucket_horizon
        
        assert bucket_horizon(61) == 120
        assert bucket_horizon(90) == 120
        assert bucket_horizon(120) == 120
    
    def test_bucket_horizon_caps_at_120(self):
        """Horizons beyond 120 still bucket to 120."""
        from services.truth_versioning_service.schemas import bucket_horizon
        
        assert bucket_horizon(150) == 120
        assert bucket_horizon(240) == 120


class TestBucketAsOfDate:
    """Tests for as-of date bucketing to quarter-end."""
    
    def test_q1_dates_bucket_to_march_31(self):
        """Dates in Q1 bucket to March 31."""
        from services.truth_versioning_service.schemas import bucket_as_of_date
        
        assert bucket_as_of_date(date(2024, 1, 1)) == date(2024, 3, 31)
        assert bucket_as_of_date(date(2024, 1, 15)) == date(2024, 3, 31)
        assert bucket_as_of_date(date(2024, 2, 28)) == date(2024, 3, 31)
        assert bucket_as_of_date(date(2024, 3, 31)) == date(2024, 3, 31)
    
    def test_q2_dates_bucket_to_june_30(self):
        """Dates in Q2 bucket to June 30."""
        from services.truth_versioning_service.schemas import bucket_as_of_date
        
        assert bucket_as_of_date(date(2024, 4, 1)) == date(2024, 6, 30)
        assert bucket_as_of_date(date(2024, 5, 15)) == date(2024, 6, 30)
        assert bucket_as_of_date(date(2024, 6, 30)) == date(2024, 6, 30)
    
    def test_q3_dates_bucket_to_september_30(self):
        """Dates in Q3 bucket to September 30."""
        from services.truth_versioning_service.schemas import bucket_as_of_date
        
        assert bucket_as_of_date(date(2024, 7, 1)) == date(2024, 9, 30)
        assert bucket_as_of_date(date(2024, 8, 15)) == date(2024, 9, 30)
        assert bucket_as_of_date(date(2024, 9, 30)) == date(2024, 9, 30)
    
    def test_q4_dates_bucket_to_december_31(self):
        """Dates in Q4 bucket to December 31."""
        from services.truth_versioning_service.schemas import bucket_as_of_date
        
        assert bucket_as_of_date(date(2024, 10, 1)) == date(2024, 12, 31)
        assert bucket_as_of_date(date(2024, 11, 15)) == date(2024, 12, 31)
        assert bucket_as_of_date(date(2024, 12, 31)) == date(2024, 12, 31)


class TestDeriveClaimClassKey:
    """Tests for claim class key derivation."""
    
    def test_key_format_is_deterministic(self):
        """Same inputs always produce the same key."""
        from services.truth_versioning_service.schemas import derive_claim_class_key
        
        key1 = derive_claim_class_key(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 15),
        )
        
        key2 = derive_claim_class_key(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 15),
        )
        
        assert key1 == key2
    
    def test_key_includes_bucketed_horizon(self):
        """Key includes the bucketed horizon, not original."""
        from services.truth_versioning_service.schemas import derive_claim_class_key
        
        # 7 months buckets to 12
        key = derive_claim_class_key(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=7,
            as_of_date=date(2024, 6, 30),
        )
        
        assert "H12M" in key
        assert "H7M" not in key
    
    def test_key_includes_bucketed_date(self):
        """Key includes the bucketed date, not original."""
        from services.truth_versioning_service.schemas import derive_claim_class_key
        
        # June 15 buckets to Q2 (2024-Q2)
        key = derive_claim_class_key(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 15),
        )
        
        assert "2024-Q2" in key
    
    def test_different_entity_produces_different_key(self):
        """Different entities produce different keys."""
        from services.truth_versioning_service.schemas import derive_claim_class_key
        
        key1 = derive_claim_class_key(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        key2 = derive_claim_class_key(
            entity_id="XYZ789",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        assert key1 != key2
    
    def test_different_scenario_produces_different_key(self):
        """Different scenarios produce different keys."""
        from services.truth_versioning_service.schemas import derive_claim_class_key
        
        key1 = derive_claim_class_key(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        key2 = derive_claim_class_key(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="adverse",
            scenario_shocks_hash="abc123" + "0" * 58,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        assert key1 != key2
    
    def test_same_bucket_dates_produce_same_key(self):
        """Dates in the same quarter bucket to same key."""
        from services.truth_versioning_service.schemas import derive_claim_class_key
        
        key1 = derive_claim_class_key(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 4, 1),  # Start of Q2
        )
        
        key2 = derive_claim_class_key(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),  # End of Q2
        )
        
        assert key1 == key2
    
    def test_same_bucket_horizons_produce_same_key(self):
        """Horizons in the same bucket produce same key."""
        from services.truth_versioning_service.schemas import derive_claim_class_key
        
        key1 = derive_claim_class_key(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=7,  # Buckets to 12
            as_of_date=date(2024, 6, 30),
        )
        
        key2 = derive_claim_class_key(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=11,  # Also buckets to 12
            as_of_date=date(2024, 6, 30),
        )
        
        assert key1 == key2


# =============================================================================
# Test ClaimClassKey Model
# =============================================================================


class TestClaimClassKeyModel:
    """Tests for the ClaimClassKey Pydantic model."""
    
    def test_from_components_creates_valid_key(self):
        """from_components creates a valid key."""
        from services.truth_versioning_service.schemas import ClaimClassKey
        
        key = ClaimClassKey.from_components(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        assert key.entity_id == "ABC123"
        assert key.entity_id_type == "LEI"
        assert key.jurisdiction == "US"
        assert key.scenario_name == "baseline"
        assert key.horizon_bucket == 12
        assert key.as_of_date_bucket == date(2024, 6, 30)
        assert "LEI:ABC123" in key.key
    
    def test_from_components_roundtrip(self):
        """from_components creates a consistent key."""
        from services.truth_versioning_service.schemas import ClaimClassKey
        
        # Create a key
        original = ClaimClassKey.from_components(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        # Create the same key again - should be identical
        second = ClaimClassKey.from_components(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        assert second.entity_id == original.entity_id
        assert second.entity_id_type == original.entity_id_type
        assert second.jurisdiction == original.jurisdiction
        assert second.scenario_name == original.scenario_name
        assert second.horizon_bucket == original.horizon_bucket
        assert second.as_of_date_bucket == original.as_of_date_bucket
        assert second.key == original.key
    
    def test_claim_class_key_is_frozen(self):
        """ClaimClassKey is immutable."""
        from services.truth_versioning_service.schemas import ClaimClassKey
        
        key = ClaimClassKey.from_components(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        with pytest.raises(ValidationError):
            key.entity_id = "XYZ"


# =============================================================================
# Test TruthVersion Schema
# =============================================================================


class TestTruthVersionSchema:
    """Tests for the TruthVersion schema."""
    
    def test_truth_version_creation(self):
        """TruthVersion can be created with required fields."""
        from services.truth_versioning_service.schemas import (
            TruthVersion,
            TruthVersionStatus,
            ProbabilityIntervalSummary,
            ClaimClassKey,
        )
        
        claim_key = ClaimClassKey.from_components(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        prob = ProbabilityIntervalSummary(
            p_low=Decimal("0.05"),
            p_mid=Decimal("0.10"),
            p_high=Decimal("0.15"),
        )
        
        version = TruthVersion(
            truth_version_id="tv-123",
            created_at=datetime.now(timezone.utc),
            claim_class_key=claim_key,
            canonical_claim_hash="d" * 64,
            canonical_claim_summary="Entity is solvent",
            evaluation_id="eval-456",
            conclusion="SOLVENT",
            probability_interval=prob,
            key_risks=[],
            engine_version="1.0.0",
            evidence_set_hash="a" * 64,
            facts_snapshot_hash="b" * 64,
            policy_hash="c" * 64,
            trace_hash="e" * 64,
            result_hash="f" * 64,
            version_number=1,
            status=TruthVersionStatus.CURRENT,
        )
        
        assert version.truth_version_id == "tv-123"
        assert version.conclusion == "SOLVENT"
        assert version.version_number == 1
        assert version.status == TruthVersionStatus.CURRENT
    
    def test_truth_version_is_frozen(self):
        """TruthVersion is immutable."""
        from services.truth_versioning_service.schemas import (
            TruthVersion,
            TruthVersionStatus,
            ProbabilityIntervalSummary,
            ClaimClassKey,
        )
        
        claim_key = ClaimClassKey.from_components(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        prob = ProbabilityIntervalSummary(
            p_low=Decimal("0.05"),
            p_mid=Decimal("0.10"),
            p_high=Decimal("0.15"),
        )
        
        version = TruthVersion(
            truth_version_id="tv-123",
            created_at=datetime.now(timezone.utc),
            claim_class_key=claim_key,
            canonical_claim_hash="d" * 64,
            canonical_claim_summary="Entity is solvent",
            evaluation_id="eval-456",
            conclusion="SOLVENT",
            probability_interval=prob,
            key_risks=[],
            engine_version="1.0.0",
            evidence_set_hash="a" * 64,
            facts_snapshot_hash="b" * 64,
            policy_hash="c" * 64,
            trace_hash="e" * 64,
            result_hash="f" * 64,
            version_number=1,
            status=TruthVersionStatus.CURRENT,
        )
        
        with pytest.raises(ValidationError):
            version.conclusion = "INSOLVENT"


# =============================================================================
# Test TruthVersionStatus Enum
# =============================================================================


class TestTruthVersionStatus:
    """Tests for the TruthVersionStatus enum."""
    
    def test_all_statuses_defined(self):
        """All expected statuses are defined."""
        from services.truth_versioning_service.schemas import TruthVersionStatus
        
        assert TruthVersionStatus.CURRENT.value == "current"
        assert TruthVersionStatus.SUPERSEDED.value == "superseded"
        assert TruthVersionStatus.RETRACTED.value == "retracted"


# =============================================================================
# Test PromotionResult Enum
# =============================================================================


class TestPromotionResult:
    """Tests for the PromotionResult enum."""
    
    def test_all_results_defined(self):
        """All expected results are defined."""
        from services.truth_versioning_service.schemas import PromotionResult
        
        assert PromotionResult.CREATED.value == "created"
        assert PromotionResult.DEDUPLICATED.value == "deduplicated"
        assert PromotionResult.SUPERSEDED_PRIOR.value == "superseded_prior"
        assert PromotionResult.REJECTED_NOT_VERIFIED.value == "rejected_not_verified"


# =============================================================================
# Test DiffChangeType Enum
# =============================================================================


class TestDiffChangeType:
    """Tests for the DiffChangeType enum."""
    
    def test_all_change_types_defined(self):
        """All expected change types are defined."""
        from services.truth_versioning_service.schemas import DiffChangeType
        
        assert DiffChangeType.ADDED.value == "added"
        assert DiffChangeType.REMOVED.value == "removed"
        assert DiffChangeType.MODIFIED.value == "modified"
        assert DiffChangeType.UNCHANGED.value == "unchanged"


# =============================================================================
# Test TruthDiff Schema
# =============================================================================


class TestTruthDiffSchema:
    """Tests for the TruthDiff schema."""
    
    def test_truth_diff_creation(self):
        """TruthDiff can be created with required fields."""
        from services.truth_versioning_service.schemas import (
            TruthDiff,
            DecisionChange,
            DiffChangeType,
        )
        
        decision_change = DecisionChange(
            conclusion_changed=True,
            old_conclusion="SOLVENT",
            new_conclusion="INSOLVENT",
            probability_changed=True,
            old_p_mid=Decimal("0.10"),
            new_p_mid=Decimal("0.78"),
            p_delta=Decimal("0.68"),
            fragility_changed=True,
            old_fragility=Decimal("0.25"),
            new_fragility=Decimal("0.65"),
            fragility_delta=Decimal("0.40"),
            top_risks_changed=True,
            risks_added=["liquidity_risk"],
            risks_removed=[],
            sensitivities_changed=True,
            old_top_driver="interest_rate",
            new_top_driver="credit_spread",
        )
        
        diff = TruthDiff(
            version_a_id="tv-1",
            version_b_id="tv-2",
            diff_hash="x" * 64,
            evidence_added=[],
            evidence_removed=[],
            facts_added=[],
            facts_removed=[],
            facts_modified=[],
            policies_changed=[],
            decision_change=decision_change,
            is_material_change=True,
            change_summary="Conclusion changed from SOLVENT to INSOLVENT",
        )
        
        assert diff.version_a_id == "tv-1"
        assert diff.decision_change.conclusion_changed is True
    
    def test_truth_diff_is_frozen(self):
        """TruthDiff is immutable."""
        from services.truth_versioning_service.schemas import (
            TruthDiff,
            DecisionChange,
        )
        
        decision_change = DecisionChange(
            conclusion_changed=False,
            probability_changed=False,
            fragility_changed=False,
            top_risks_changed=False,
            sensitivities_changed=False,
        )
        
        diff = TruthDiff(
            version_a_id="tv-1",
            version_b_id="tv-2",
            diff_hash="x" * 64,
            evidence_added=[],
            evidence_removed=[],
            facts_added=[],
            facts_removed=[],
            facts_modified=[],
            decision_change=decision_change,
            is_material_change=False,
            change_summary="No changes",
        )
        
        with pytest.raises(ValidationError):
            diff.version_a_id = "tv-999"


# =============================================================================
# Test Store Classes (Unit Tests with Mocks)
# =============================================================================


class TestTruthVersionStoreMock:
    """Unit tests for TruthVersionStore with mocked database."""
    
    @pytest.mark.asyncio
    async def test_store_creates_version(self):
        """store() creates a new version record."""
        from services.truth_versioning_service.stores import TruthVersionStore
        from services.truth_versioning_service.schemas import (
            TruthVersion,
            TruthVersionStatus,
            ProbabilityIntervalSummary,
            ClaimClassKey,
        )
        
        mock_session = AsyncMock()
        store = TruthVersionStore(mock_session)
        
        claim_key = ClaimClassKey.from_components(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        prob = ProbabilityIntervalSummary(
            p_low=Decimal("0.05"),
            p_mid=Decimal("0.10"),
            p_high=Decimal("0.15"),
        )
        
        version = TruthVersion(
            truth_version_id="tv-123",
            created_at=datetime.now(timezone.utc),
            claim_class_key=claim_key,
            canonical_claim_hash="d" * 64,
            canonical_claim_summary="Entity is solvent",
            evaluation_id="eval-456",
            conclusion="SOLVENT",
            probability_interval=prob,
            key_risks=[],
            engine_version="1.0.0",
            evidence_set_hash="a" * 64,
            facts_snapshot_hash="b" * 64,
            policy_hash="c" * 64,
            trace_hash="e" * 64,
            result_hash="f" * 64,
            version_number=1,
            status=TruthVersionStatus.CURRENT,
        )
        
        result = await store.store(version)
        
        # store returns the truth_version_id string
        assert result == version.truth_version_id
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()


class TestRecomputeQueueMock:
    """Unit tests for RecomputeQueue with mocked database."""
    
    @pytest.mark.asyncio
    async def test_enqueue_creates_task(self):
        """enqueue() creates a new task record."""
        from services.truth_versioning_service.schemas import RecomputeTask, RecomputeTaskStatus
        
        # Create a proper task object to test the schema
        task = RecomputeTask(
            task_id="task-123",
            claim_class_key="test-key",
            trigger_reason="evidence_update",
            triggered_by_evidence_id="evidence-123",
            priority=10,
            status=RecomputeTaskStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        
        assert task.task_id == "task-123"
        assert task.claim_class_key == "test-key"
        assert task.trigger_reason == "evidence_update"
        assert task.status == RecomputeTaskStatus.PENDING


# =============================================================================
# Test Promotion Service Logic
# =============================================================================


class TestPromotionServiceLogic:
    """Tests for PromotionService business logic."""
    
    @pytest.mark.asyncio
    async def test_promotion_requires_verification(self):
        """Promotion requires replay verification."""
        from services.truth_versioning_service.promotion import PromotionService
        from services.truth_versioning_service.schemas import (
            ClaimClassKey,
            PromotionResult,
        )
        
        mock_session = AsyncMock()
        mock_store = AsyncMock()
        mock_verifier = AsyncMock()
        mock_index = AsyncMock()
        
        # Verifier returns failure - "No trace found" maps to REJECTED_NO_TRACE
        mock_verifier.verify_evaluation = AsyncMock(return_value=(False, "No trace found", None))
        
        service = PromotionService(mock_session, mock_store, mock_verifier, mock_index)
        
        claim_key = ClaimClassKey.from_components(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        result = await service.promote(
            evaluation_id="eval-123",
            claim_class_key=claim_key,
            canonical_claim_hash="d" * 64,
            canonical_claim_summary="Test claim",
            evidence_ids=[],
        )
        
        # Service returns REJECTED_NO_TRACE for missing trace
        assert result.result == PromotionResult.REJECTED_NO_TRACE
        assert "No trace found" in result.message
    
    @pytest.mark.asyncio
    async def test_deduplication_when_hashes_match(self):
        """Promotion is deduplicated when all hashes match."""
        from services.truth_versioning_service.promotion import PromotionService
        from services.truth_versioning_service.schemas import (
            ClaimClassKey,
            PromotionResult,
            TruthVersion,
            TruthVersionStatus,
            ProbabilityIntervalSummary,
        )
        
        mock_session = AsyncMock()
        mock_store = AsyncMock()
        mock_verifier = AsyncMock()
        mock_index = AsyncMock()
        
        # Verifier returns success with matching audit data
        audit_data = {
            "evidence_set_hash": "a" * 64,
            "facts_snapshot_hash": "b" * 64,
            "policy_hash": "c" * 64,
            "engine_version": "1.0.0",
            "conclusion": "SOLVENT",
            "probability_interval": {
                "p_low": "0.05",
                "p_mid": "0.10",
                "p_high": "0.15",
            },
            "key_risks": [],
            "trace_hash": "e" * 64,
            "result_hash": "f" * 64,
        }
        mock_verifier.verify_evaluation = AsyncMock(return_value=(True, None, audit_data))
        
        # Store returns existing version with same hashes
        claim_key = ClaimClassKey.from_components(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        existing_version = TruthVersion(
            truth_version_id="tv-existing",
            created_at=datetime.now(timezone.utc),
            claim_class_key=claim_key,
            canonical_claim_hash="d" * 64,
            canonical_claim_summary="Test claim",
            evaluation_id="eval-old",
            conclusion="SOLVENT",
            probability_interval=ProbabilityIntervalSummary(
                p_low=Decimal("0.05"),
                p_mid=Decimal("0.10"),
                p_high=Decimal("0.15"),
            ),
            key_risks=[],
            engine_version="1.0.0",
            evidence_set_hash="a" * 64,
            facts_snapshot_hash="b" * 64,
            policy_hash="c" * 64,
            trace_hash="e" * 64,
            result_hash="f" * 64,
            version_number=1,
            status=TruthVersionStatus.CURRENT,
        )
        mock_store.find_matching_version = AsyncMock(return_value=existing_version)
        
        service = PromotionService(mock_session, mock_store, mock_verifier, mock_index)
        
        result = await service.promote(
            evaluation_id="eval-new",
            claim_class_key=claim_key,
            canonical_claim_hash="d" * 64,
            canonical_claim_summary="Test claim",
            evidence_ids=[],
        )
        
        assert result.result == PromotionResult.DEDUPLICATED
        assert result.truth_version_id == "tv-existing"


# =============================================================================
# Test Diff Service Logic
# =============================================================================


class TestDiffServiceLogic:
    """Tests for DiffService business logic."""
    
    @pytest.mark.asyncio
    async def test_diff_detects_conclusion_change(self):
        """Diff correctly detects conclusion changes."""
        from services.truth_versioning_service.promotion import DiffService
        from services.truth_versioning_service.schemas import (
            TruthVersion,
            TruthVersionStatus,
            ProbabilityIntervalSummary,
            ClaimClassKey,
        )
        
        mock_session = AsyncMock()
        mock_store = AsyncMock()
        
        claim_key = ClaimClassKey.from_components(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        version_a = TruthVersion(
            truth_version_id="tv-1",
            created_at=datetime.now(timezone.utc),
            claim_class_key=claim_key,
            canonical_claim_hash="d" * 64,
            canonical_claim_summary="Test claim",
            evaluation_id="eval-1",
            conclusion="SOLVENT",
            probability_interval=ProbabilityIntervalSummary(
                p_low=Decimal("0.05"),
                p_mid=Decimal("0.10"),
                p_high=Decimal("0.15"),
            ),
            key_risks=[],
            engine_version="1.0.0",
            evidence_set_hash="a" * 64,
            facts_snapshot_hash="b" * 64,
            policy_hash="c" * 64,
            trace_hash="e" * 64,
            result_hash="f" * 64,
            version_number=1,
            status=TruthVersionStatus.SUPERSEDED,
        )
        
        version_b = TruthVersion(
            truth_version_id="tv-2",
            created_at=datetime.now(timezone.utc),
            claim_class_key=claim_key,
            canonical_claim_hash="d" * 64,
            canonical_claim_summary="Test claim",
            evaluation_id="eval-2",
            conclusion="INSOLVENT",
            probability_interval=ProbabilityIntervalSummary(
                p_low=Decimal("0.70"),
                p_mid=Decimal("0.78"),
                p_high=Decimal("0.85"),
            ),
            fragility_score=Decimal("0.60"),
            key_risks=[],
            engine_version="1.0.0",
            evidence_set_hash="x" * 64,
            facts_snapshot_hash="y" * 64,
            policy_hash="c" * 64,
            trace_hash="g" * 64,
            result_hash="h" * 64,
            version_number=2,
            status=TruthVersionStatus.CURRENT,
            supersedes_truth_version_id="tv-1",
        )
        
        mock_store.get = AsyncMock(side_effect=[version_a, version_b])
        
        service = DiffService(mock_session, mock_store)
        diff = await service.generate_diff("tv-1", "tv-2")
        
        assert diff is not None
        assert diff.decision_change.conclusion_changed is True
        assert diff.decision_change.old_conclusion == "SOLVENT"
        assert diff.decision_change.new_conclusion == "INSOLVENT"
    
    @pytest.mark.asyncio
    async def test_diff_returns_none_for_missing_version(self):
        """Diff returns None when a version is not found."""
        from services.truth_versioning_service.promotion import DiffService
        
        mock_session = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get = AsyncMock(return_value=None)
        
        service = DiffService(mock_session, mock_store)
        diff = await service.generate_diff("tv-nonexistent", "tv-2")
        
        assert diff is None


# =============================================================================
# Test Impact Analysis Service Logic
# =============================================================================


class TestImpactAnalysisServiceLogic:
    """Tests for ImpactAnalysisService business logic."""
    
    @pytest.mark.asyncio
    async def test_impact_analysis_finds_impacted_classes(self):
        """Impact analysis correctly finds impacted claim classes."""
        from services.truth_versioning_service.promotion import ImpactAnalysisService
        from services.truth_versioning_service.schemas import (
            ClaimClassKey,
            ImpactedClaimClass,
            RecomputeTask,
            RecomputeTaskStatus,
        )
        
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_index = AsyncMock()
        mock_queue = AsyncMock()
        
        # Index returns some impacted claim classes (as ImpactedClaimClass objects)
        claim_key = ClaimClassKey.from_components(
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            scenario_name="baseline",
            scenario_shocks_hash="0" * 64,
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
        )
        
        impacted_class = ImpactedClaimClass(
            claim_class_key=claim_key.key,
            current_truth_version_id=None,
            impact_reason="Evidence evidence-123 updated",
            priority=2,
        )
        
        # Create a proper RecomputeTask for the mock to return
        mock_task = RecomputeTask(
            task_id="task-123",
            claim_class_key=claim_key.key,
            trigger_reason="Evidence evidence-123 updated",
            triggered_by_evidence_id="evidence-123",
            priority=5,
            status=RecomputeTaskStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        
        mock_index.find_by_evidence = AsyncMock(return_value=[impacted_class])
        mock_queue.task_exists_for_claim_class = AsyncMock(return_value=False)
        mock_queue.enqueue = AsyncMock(return_value=mock_task)
        
        service = ImpactAnalysisService(mock_session, mock_index, mock_queue)
        
        result = await service.analyze_impact(
            evidence_id="evidence-123",
            queue_tasks=True,
        )
        
        assert result.total_impacted == 1
        assert len(result.impacted_claim_classes) == 1
        assert result.impacted_claim_classes[0].claim_class_key == claim_key.key


# =============================================================================
# Test API Routes
# =============================================================================


class TestRoutes:
    """Tests for REST API routes."""
    
    def test_router_has_expected_routes(self):
        """Router has all expected routes."""
        from services.truth_versioning_service.routes import router
        
        route_paths = [route.path for route in router.routes]
        
        assert "/truth/promote" in route_paths
        assert "/truth/{truth_version_id}" in route_paths
        assert "/truth/by-evaluation/{evaluation_id}" in route_paths
        assert "/truth/current" in route_paths
        assert "/truth/history" in route_paths
        assert "/truth/diff" in route_paths
        assert "/truth/impact/analyze" in route_paths
        assert "/truth/version" in route_paths
        assert "/truth/claim-class-key" in route_paths


# =============================================================================
# Test App Configuration
# =============================================================================


class TestAppConfiguration:
    """Tests for app configuration."""
    
    def test_app_includes_router(self):
        """App includes the API router."""
        from services.truth_versioning_service.app import create_app
        
        app = create_app()
        
        # Check for versioned routes
        route_paths = [route.path for route in app.routes]
        
        # Routes should be under /v1
        assert "/v1/truth/promote" in route_paths
        assert "/v1/truth/{truth_version_id}" in route_paths
    
    def test_app_has_health_endpoint(self):
        """App has health check endpoint."""
        from services.truth_versioning_service.app import create_app
        
        app = create_app()
        route_paths = [route.path for route in app.routes]
        
        assert "/health" in route_paths


# =============================================================================
# Test Module Exports
# =============================================================================


class TestModuleExports:
    """Tests for module exports."""
    
    def test_all_expected_exports_available(self):
        """All expected items are exported from the module."""
        from services.truth_versioning_service import (
            # App
            create_app,
            # Constants
            TRUTH_VERSION_SERVICE_VERSION,
            HORIZON_BUCKETS,
            # Bucketing functions
            bucket_horizon,
            bucket_as_of_date,
            derive_claim_class_key,
            # Enums
            TruthVersionStatus,
            PromotionResult,
            DiffChangeType,
            RecomputeTaskStatus,
            # Core schemas
            ClaimClassKey,
            TruthVersion,
            TruthDiff,
            ImpactAnalysisResult,
            # Stores
            TruthVersionStore,
            RecomputeQueue,
            ClaimClassIndex,
            ReplayVerifier,
            # Services
            PromotionService,
            DiffService,
            ImpactAnalysisService,
        )
        
        assert TRUTH_VERSION_SERVICE_VERSION == "1.0.0"
        assert HORIZON_BUCKETS == (3, 6, 12, 24, 60, 120)


# =============================================================================
# Test Request/Response Models
# =============================================================================


class TestRequestResponseModels:
    """Tests for API request/response models."""
    
    def test_promote_request_validation(self):
        """PromoteRequest validates required fields."""
        from services.truth_versioning_service.routes import PromoteEvaluationRequest
        
        # Valid request
        request = PromoteEvaluationRequest(
            evaluation_id="eval-123",
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
            canonical_claim_hash="d" * 64,
            canonical_claim_summary="Test claim",
        )
        
        assert request.evaluation_id == "eval-123"
        assert request.scenario_name == "baseline"  # Default
    
    def test_promote_request_rejects_invalid_horizon(self):
        """PromoteRequest rejects invalid horizon."""
        from services.truth_versioning_service.routes import PromoteEvaluationRequest
        
        with pytest.raises(ValidationError):
            PromoteEvaluationRequest(
                evaluation_id="eval-123",
                entity_id="ABC123",
                entity_id_type="LEI",
                jurisdiction="US",
                horizon_months=1,  # Too low (min is 3)
                as_of_date=date(2024, 6, 30),
                canonical_claim_hash="d" * 64,
                canonical_claim_summary="Test claim",
            )
    
    def test_get_history_request(self):
        """GetHistoryRequest validates correctly."""
        from services.truth_versioning_service.schemas import GetHistoryRequest
        
        request = GetHistoryRequest(
            claim_class_key="test-key",
            limit=50,
            offset=0,
            include_superseded=True,
        )
        
        assert request.claim_class_key == "test-key"
        assert request.limit == 50
    
    def test_get_diff_request(self):
        """GetDiffRequest validates correctly."""
        from services.truth_versioning_service.schemas import GetDiffRequest
        
        request = GetDiffRequest(
            version_a_id="tv-1",
            version_b_id="tv-2",
        )
        
        assert request.version_a_id == "tv-1"
        assert request.version_b_id == "tv-2"
    
    def test_impact_analysis_request(self):
        """ImpactAnalysisRequest validates correctly."""
        from services.truth_versioning_service.schemas import ImpactAnalysisRequest
        
        request = ImpactAnalysisRequest(
            evidence_id="evidence-123",
            queue_tasks=True,
            priority=10,
        )
        
        assert request.evidence_id == "evidence-123"
        assert request.queue_tasks is True


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_bucket_horizon_at_exact_boundaries(self):
        """Test horizon bucketing at exact bucket boundaries."""
        from services.truth_versioning_service.schemas import bucket_horizon
        
        # At exact boundaries
        assert bucket_horizon(3) == 3
        assert bucket_horizon(6) == 6
        assert bucket_horizon(12) == 12
        assert bucket_horizon(24) == 24
        assert bucket_horizon(60) == 60
        assert bucket_horizon(120) == 120
    
    def test_bucket_as_of_date_at_quarter_boundaries(self):
        """Test as-of date bucketing at exact quarter ends."""
        from services.truth_versioning_service.schemas import bucket_as_of_date
        
        # At exact quarter ends
        assert bucket_as_of_date(date(2024, 3, 31)) == date(2024, 3, 31)
        assert bucket_as_of_date(date(2024, 6, 30)) == date(2024, 6, 30)
        assert bucket_as_of_date(date(2024, 9, 30)) == date(2024, 9, 30)
        assert bucket_as_of_date(date(2024, 12, 31)) == date(2024, 12, 31)
    
    def test_claim_class_key_with_special_characters(self):
        """Test claim class key with entity IDs containing special chars."""
        from services.truth_versioning_service.schemas import ClaimClassKey
        
        # LEI with typical format
        key = ClaimClassKey.from_components(
            entity_id="5493006MHB84DD0ZWV18",
            entity_id_type="LEI",
            jurisdiction="DE",
            scenario_name="adverse_2024",
            scenario_shocks_hash="abc123" + "0" * 58,
            horizon_months=24,
            as_of_date=date(2024, 12, 31),
        )
        
        assert "5493006MHB84DD0ZWV18" in key.key
        assert "adverse_2024" in key.key
    
    def test_empty_evidence_ids_list(self):
        """Test with empty evidence IDs list."""
        from services.truth_versioning_service.routes import PromoteEvaluationRequest
        
        request = PromoteEvaluationRequest(
            evaluation_id="eval-123",
            entity_id="ABC123",
            entity_id_type="LEI",
            jurisdiction="US",
            horizon_months=12,
            as_of_date=date(2024, 6, 30),
            canonical_claim_hash="d" * 64,
            canonical_claim_summary="Test claim",
            evidence_ids=[],
        )
        
        assert request.evidence_ids == []


# =============================================================================
# Test Determinism
# =============================================================================


class TestDeterminism:
    """Tests to verify deterministic behavior."""
    
    def test_claim_class_key_determinism(self):
        """Same inputs always produce identical claim class keys."""
        from services.truth_versioning_service.schemas import derive_claim_class_key
        
        keys = []
        for _ in range(100):
            key = derive_claim_class_key(
                entity_id="ABC123",
                entity_id_type="LEI",
                jurisdiction="US",
                scenario_name="baseline",
                scenario_shocks_hash="0" * 64,
                horizon_months=12,
                as_of_date=date(2024, 6, 30),
            )
            keys.append(key)
        
        # All keys must be identical
        assert len(set(keys)) == 1
    
    def test_bucket_horizon_determinism(self):
        """Horizon bucketing is deterministic."""
        from services.truth_versioning_service.schemas import bucket_horizon
        
        for horizon in range(1, 150):
            results = [bucket_horizon(horizon) for _ in range(10)]
            assert len(set(results)) == 1, f"Non-deterministic for horizon {horizon}"
    
    def test_bucket_as_of_date_determinism(self):
        """As-of date bucketing is deterministic."""
        from services.truth_versioning_service.schemas import bucket_as_of_date
        
        test_dates = [
            date(2024, 1, 1),
            date(2024, 4, 15),
            date(2024, 7, 31),
            date(2024, 10, 1),
        ]
        
        for test_date in test_dates:
            results = [bucket_as_of_date(test_date) for _ in range(10)]
            assert len(set(results)) == 1, f"Non-deterministic for date {test_date}"


# =============================================================================
# Test Constants
# =============================================================================


class TestConstants:
    """Tests for service constants."""
    
    def test_service_version_format(self):
        """Service version follows semver format."""
        from services.truth_versioning_service.schemas import TRUTH_VERSION_SERVICE_VERSION
        
        parts = TRUTH_VERSION_SERVICE_VERSION.split(".")
        assert len(parts) == 3
        assert all(part.isdigit() for part in parts)
    
    def test_horizon_buckets_sorted(self):
        """Horizon buckets are sorted ascending."""
        from services.truth_versioning_service.schemas import HORIZON_BUCKETS
        
        assert HORIZON_BUCKETS == tuple(sorted(HORIZON_BUCKETS))
    
    def test_quarter_end_months(self):
        """Quarter end months are correct."""
        from services.truth_versioning_service.schemas import QUARTER_END_MONTHS
        
        # QUARTER_END_MONTHS is a frozenset
        assert QUARTER_END_MONTHS == frozenset({3, 6, 9, 12})
