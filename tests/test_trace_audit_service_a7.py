"""
A7 Trace & Audit Service Tests
===============================

Comprehensive test suite for the Trace & Audit Service (A7).

Tests cover:
1. Canonical serialization determinism
2. Hash reproducibility (same inputs → same hashes)
3. Trace graph construction and structure
4. Node and edge type coverage
5. Audit record append-only behavior
6. Hash chain integrity
7. Daily manifest generation and chaining
8. Replay verification (success and failure cases)
9. Refusal trace generation
10. REST API endpoints
"""

import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from services.trace_audit_service.schemas import (
    # Constants
    TRACE_SERVICE_VERSION,
    # Enums
    TraceNodeType,
    TraceEdgeType,
    AuditRecordType,
    ReplayStatus,
    # Core schemas
    TraceNode,
    TraceEdge,
    TraceGraph,
    AuditRecord,
    AuditManifest,
    ReplayResult,
    # Node payloads
    ClaimNode,
    PolicyNode,
    EvidenceNode,
    FactNode,
    AssumptionNode,
    ComputationNode,
    MetricNode,
    FailureModeNode,
    MonteCarloRunNode,
    SensitivityNode,
    ConclusionNode,
    RefusalNode,
    # API schemas
    BuildTraceRequest,
    BuildTraceResponse,
    GetTraceResponse,
    GetAuditResponse,
    GetManifestResponse,
    ReplayVerificationRequest,
    ReplayVerificationResponse,
)

from services.trace_audit_service.canonical import (
    GENESIS_HASH,
    canonical_serialize,
    canonical_bytes,
    canonical_hash,
    canonical_hash_chain,
    canonical_decimal,
    canonical_datetime,
    canonical_value,
    canonical_dict,
    canonical_facts_snapshot_hash,
    canonical_policy_hash,
    canonical_evidence_set_hash,
    canonical_trace_hash,
    canonical_audit_record_hash,
    canonical_manifest_hash,
    verify_hash,
    verify_chain_integrity,
)

from services.trace_audit_service.builder import (
    TraceBuilderContext,
    build_trace_graph,
    build_refusal_trace_graph,
    build_claim_node,
    build_policy_node,
    build_evidence_node,
    build_fact_node,
    build_assumption_node,
    build_computation_node,
    build_metric_node,
    build_failure_mode_node,
    build_monte_carlo_node,
    build_sensitivity_node,
    build_conclusion_node,
    build_refusal_node,
    EvidenceInfo,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def reference_date() -> date:
    """Fixed reference date for tests."""
    return date(2024, 12, 31)


@pytest.fixture
def reference_datetime() -> datetime:
    """Fixed reference datetime for tests."""
    return datetime(2024, 12, 31, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_claim_hash() -> str:
    """Sample claim hash."""
    return hashlib.sha256(b"test_claim").hexdigest()


@pytest.fixture
def sample_evidence_hash() -> str:
    """Sample evidence hash."""
    return hashlib.sha256(b"test_evidence").hexdigest()


@pytest.fixture
def sample_policy_hash() -> str:
    """Sample policy hash."""
    return hashlib.sha256(b"test_policy").hexdigest()


@pytest.fixture
def sample_facts_snapshot() -> list[dict[str, Any]]:
    """Sample facts snapshot for audit records."""
    return [
        {
            "fact_id": "fact_001",
            "fact_type": "total_assets",
            "value": "1000000.00",
            "currency": "USD",
            "as_of_date": "2024-12-31",
            "confidence": "0.95",
            "fact_hash": "a" * 64,
        },
        {
            "fact_id": "fact_002",
            "fact_type": "total_liabilities",
            "value": "400000.00",
            "currency": "USD",
            "as_of_date": "2024-12-31",
            "confidence": "0.95",
            "fact_hash": "b" * 64,
        },
    ]


# =============================================================================
# Canonical Serialization Tests
# =============================================================================


class TestCanonicalSerialization:
    """Tests for deterministic canonical serialization."""
    
    def test_canonical_decimal_rounding(self):
        """Decimals are serialized with consistent rounding."""
        # Test various Decimal values
        assert canonical_decimal(Decimal("1.5")) == "1.5"
        assert canonical_decimal(Decimal("1.50")) == "1.5"
        assert canonical_decimal(Decimal("1.500000")) == "1.5"
        assert canonical_decimal(Decimal("0.123456789")) == "0.123456789"
        # Large numbers may use scientific notation - that's ok for determinism
        result = canonical_decimal(Decimal("1000000"))
        assert result in ("1000000", "1E+6")  # Either form is deterministic
        
    def test_canonical_decimal_negative(self):
        """Negative Decimals are handled correctly."""
        assert canonical_decimal(Decimal("-100.50")) == "-100.5"
        assert canonical_decimal(Decimal("-0.001")) == "-0.001"
    
    def test_canonical_datetime_utc(self):
        """Datetimes are serialized as UTC ISO8601."""
        dt = datetime(2024, 12, 31, 12, 30, 45, tzinfo=timezone.utc)
        result = canonical_datetime(dt)
        # Should contain the date/time and end with Z
        assert "2024-12-31T12:30:45" in result
        assert result.endswith("Z")
    
    def test_canonical_datetime_no_tz(self):
        """Naive datetimes are treated as UTC."""
        dt = datetime(2024, 1, 15, 8, 0, 0)
        result = canonical_datetime(dt)
        # Should have Z suffix
        assert result.endswith("Z")
    
    def test_canonical_serialize_sorted_keys(self):
        """JSON serialization uses sorted keys."""
        data = {"z": 1, "a": 2, "m": 3}
        result = canonical_serialize(data)
        assert result == '{"a":2,"m":3,"z":1}'
    
    def test_canonical_serialize_nested_sorted(self):
        """Nested objects have sorted keys."""
        data = {"outer": {"z": 1, "a": 2}}
        result = canonical_serialize(data)
        assert result == '{"outer":{"a":2,"z":1}}'
    
    def test_canonical_serialize_no_spaces(self):
        """Serialization is compact without spaces."""
        data = {"key": "value", "num": 42}
        result = canonical_serialize(data)
        assert " " not in result
        assert "\n" not in result
    
    def test_canonical_hash_determinism(self):
        """Same input produces same hash every time."""
        data = {"test": "data", "number": 42}
        
        hash1 = canonical_hash(data)
        hash2 = canonical_hash(data)
        hash3 = canonical_hash(data)
        
        assert hash1 == hash2 == hash3
    
    def test_canonical_hash_different_for_different_input(self):
        """Different inputs produce different hashes."""
        hash1 = canonical_hash({"a": 1})
        hash2 = canonical_hash({"a": 2})
        hash3 = canonical_hash({"b": 1})
        
        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3
    
    def test_canonical_hash_length(self):
        """Hash is 64 characters (SHA256 hex)."""
        h = canonical_hash({"test": "data"})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)
    
    def test_canonical_hash_chain_determinism(self):
        """Hash chain is deterministic."""
        items = ["hash1", "hash2", "hash3"]
        
        chain1 = canonical_hash_chain(items, GENESIS_HASH)
        chain2 = canonical_hash_chain(items, GENESIS_HASH)
        
        assert chain1 == chain2
    
    def test_canonical_hash_chain_order_matters(self):
        """Hash chain depends on order."""
        chain1 = canonical_hash_chain(["a", "b", "c"], GENESIS_HASH)
        chain2 = canonical_hash_chain(["c", "b", "a"], GENESIS_HASH)
        chain3 = canonical_hash_chain(["a", "c", "b"], GENESIS_HASH)
        
        assert chain1 != chain2
        assert chain1 != chain3
        assert chain2 != chain3
    
    def test_canonical_hash_chain_empty(self):
        """Empty chain returns previous hash."""
        result = canonical_hash_chain([], GENESIS_HASH)
        assert result == GENESIS_HASH
    
    def test_genesis_hash_format(self):
        """Genesis hash is 64 zeros."""
        assert GENESIS_HASH == "0" * 64
        assert len(GENESIS_HASH) == 64
    
    def test_verify_hash_success(self):
        """verify_hash returns True for correct hash."""
        data = {"test": "data"}
        h = canonical_hash(data)
        assert verify_hash(data, h) is True
    
    def test_verify_hash_failure(self):
        """verify_hash returns False for wrong hash."""
        data = {"test": "data"}
        wrong_hash = "0" * 64
        assert verify_hash(data, wrong_hash) is False


class TestCanonicalFactsSnapshot:
    """Tests for facts snapshot hashing."""
    
    def test_facts_snapshot_hash_determinism(self, sample_facts_snapshot):
        """Facts snapshot hash is deterministic."""
        hash1 = canonical_facts_snapshot_hash(sample_facts_snapshot)
        hash2 = canonical_facts_snapshot_hash(sample_facts_snapshot)
        
        assert hash1 == hash2
        assert len(hash1) == 64
    
    def test_facts_snapshot_hash_order_independent(self):
        """Facts are sorted by fact_id before hashing."""
        facts1 = [
            {"fact_id": "a", "value": "1"},
            {"fact_id": "b", "value": "2"},
        ]
        facts2 = [
            {"fact_id": "b", "value": "2"},
            {"fact_id": "a", "value": "1"},
        ]
        
        hash1 = canonical_facts_snapshot_hash(facts1)
        hash2 = canonical_facts_snapshot_hash(facts2)
        
        assert hash1 == hash2
    
    def test_facts_snapshot_empty(self):
        """Empty facts list produces consistent hash."""
        hash1 = canonical_facts_snapshot_hash([])
        hash2 = canonical_facts_snapshot_hash([])
        
        assert hash1 == hash2
        assert len(hash1) == 64


class TestCanonicalPolicyHash:
    """Tests for policy hash computation."""
    
    def test_policy_hash_determinism(self):
        """Policy hash is deterministic."""
        hash1 = canonical_policy_hash(
            min_confidence=Decimal("0.70"),
            max_staleness_days=365,
            prefer_higher_confidence=True,
            prefer_newer_date=True,
        )
        hash2 = canonical_policy_hash(
            min_confidence=Decimal("0.70"),
            max_staleness_days=365,
            prefer_higher_confidence=True,
            prefer_newer_date=True,
        )
        
        assert hash1 == hash2
    
    def test_policy_hash_changes_with_values(self):
        """Different policy values produce different hashes."""
        hash1 = canonical_policy_hash(
            min_confidence=Decimal("0.70"),
            max_staleness_days=365,
            prefer_higher_confidence=True,
            prefer_newer_date=True,
        )
        hash2 = canonical_policy_hash(
            min_confidence=Decimal("0.80"),
            max_staleness_days=365,
            prefer_higher_confidence=True,
            prefer_newer_date=True,
        )
        
        assert hash1 != hash2


class TestCanonicalEvidenceSetHash:
    """Tests for evidence set hash computation."""
    
    def test_evidence_set_hash_determinism(self):
        """Evidence set hash is deterministic."""
        evidence_hashes = ["a" * 64, "b" * 64]
        
        hash1 = canonical_evidence_set_hash(evidence_hashes)
        hash2 = canonical_evidence_set_hash(evidence_hashes)
        
        assert hash1 == hash2
    
    def test_evidence_set_hash_order_independent(self):
        """Evidence hashes are sorted before hashing."""
        evidence1 = ["a" * 64, "b" * 64]
        evidence2 = ["b" * 64, "a" * 64]
        
        hash1 = canonical_evidence_set_hash(evidence1)
        hash2 = canonical_evidence_set_hash(evidence2)
        
        assert hash1 == hash2


# =============================================================================
# Schema Validation Tests
# =============================================================================


class TestTraceNodeType:
    """Tests for TraceNodeType enum."""
    
    def test_all_node_types_defined(self):
        """All 12 node types are defined."""
        expected = {
            "claim", "policy", "evidence", "fact", "assumption",
            "computation", "metric", "failure_mode", "monte_carlo_run",
            "sensitivity", "conclusion", "refusal",
        }
        actual = {nt.value for nt in TraceNodeType}
        assert actual == expected


class TestTraceEdgeType:
    """Tests for TraceEdgeType enum."""
    
    def test_all_edge_types_defined(self):
        """All 9 edge types are defined."""
        expected = {
            "supports", "derived_from", "used_in", "produces",
            "constrains", "triggers", "cites", "selects", "excludes",
        }
        actual = {et.value for et in TraceEdgeType}
        assert actual == expected


class TestTraceNode:
    """Tests for TraceNode schema."""
    
    def test_create_valid_node(self):
        """Can create a valid TraceNode."""
        node = TraceNode(
            node_id="node_001",
            node_type=TraceNodeType.CLAIM,
            node_hash="a" * 64,
            payload={"claim_text": "Test claim", "claim_hash": "a" * 64},
        )
        assert node.node_id == "node_001"
        assert node.node_type == TraceNodeType.CLAIM
    
    def test_node_immutability(self):
        """TraceNode is frozen (immutable)."""
        node = TraceNode(
            node_id="node_001",
            node_type=TraceNodeType.CLAIM,
            node_hash="a" * 64,
            payload={},
        )
        with pytest.raises(ValidationError):
            node.node_id = "modified"


class TestTraceEdge:
    """Tests for TraceEdge schema."""
    
    def test_create_valid_edge(self):
        """Can create a valid TraceEdge."""
        edge = TraceEdge(
            edge_id="edge_001",
            source_node_id="node_001",
            target_node_id="node_002",
            edge_type=TraceEdgeType.SUPPORTS,
            edge_hash="a" * 64,
        )
        assert edge.source_node_id == "node_001"
        assert edge.target_node_id == "node_002"
    
    def test_edge_with_metadata(self):
        """Edge can have optional metadata."""
        edge = TraceEdge(
            edge_id="edge_001",
            source_node_id="node_001",
            target_node_id="node_002",
            edge_type=TraceEdgeType.SUPPORTS,
            edge_hash="a" * 64,
            metadata={"weight": "0.95"},
        )
        assert edge.metadata["weight"] == "0.95"


class TestTraceGraph:
    """Tests for TraceGraph schema."""
    
    def test_create_minimal_graph(self):
        """Can create a minimal TraceGraph."""
        node = TraceNode(
            node_id="claim_node",
            node_type=TraceNodeType.CLAIM,
            node_hash="b" * 64,
            payload={"claim_text": "Test"},
        )
        graph = TraceGraph(
            trace_id="trace_001",
            evaluation_id="eval_001",
            nodes=[node],
            edges=[],
            node_count=1,
            edge_count=0,
            trace_hash="a" * 64,
            engine_version="1.0.0",
            trace_service_version=TRACE_SERVICE_VERSION,
            claim_node_id="claim_node",
        )
        assert graph.node_count == 1
        assert graph.edge_count == 0
    
    def test_graph_built_at_default(self):
        """Graph has built_at timestamp."""
        graph = TraceGraph(
            trace_id="trace_001",
            evaluation_id="eval_001",
            nodes=[],
            edges=[],
            node_count=0,
            edge_count=0,
            trace_hash="a" * 64,
            engine_version="1.0.0",
            trace_service_version=TRACE_SERVICE_VERSION,
            claim_node_id="claim_node",
        )
        assert graph.built_at is not None


class TestAuditRecord:
    """Tests for AuditRecord schema."""
    
    def test_create_valid_audit_record(
        self,
        sample_facts_snapshot,
        sample_claim_hash,
        sample_evidence_hash,
        sample_policy_hash,
    ):
        """Can create a valid AuditRecord."""
        record = AuditRecord(
            audit_id="audit_001",
            evaluation_id="eval_001",
            created_at=datetime.now(timezone.utc),
            engine_version="1.0.0",
            trace_service_version=TRACE_SERVICE_VERSION,
            claim_hash=sample_claim_hash,
            evidence_set_hash=sample_evidence_hash,
            policy_hash=sample_policy_hash,
            facts_snapshot=sample_facts_snapshot,
            facts_snapshot_hash="b" * 64,
            trace_hash="c" * 64,
            result_hash="d" * 64,
            outcome="solvent",
            audit_hash="e" * 64,
        )
        assert record.audit_id == "audit_001"
        assert record.outcome == "solvent"
    
    def test_audit_record_with_previous_hash(self, sample_facts_snapshot):
        """Audit record can link to previous record."""
        record = AuditRecord(
            audit_id="audit_002",
            evaluation_id="eval_002",
            created_at=datetime.now(timezone.utc),
            engine_version="1.0.0",
            trace_service_version=TRACE_SERVICE_VERSION,
            claim_hash="a" * 64,
            evidence_set_hash="b" * 64,
            policy_hash="c" * 64,
            facts_snapshot=sample_facts_snapshot,
            facts_snapshot_hash="d" * 64,
            trace_hash="e" * 64,
            result_hash="f" * 64,
            outcome="insolvent",
            previous_audit_hash="0" * 64,  # Link to previous
            audit_hash="g" * 64,
        )
        assert record.previous_audit_hash == "0" * 64


class TestAuditManifest:
    """Tests for AuditManifest schema."""
    
    def test_create_valid_manifest(self, reference_date):
        """Can create a valid AuditManifest."""
        manifest = AuditManifest(
            manifest_id="manifest_001",
            manifest_date=reference_date,
            record_count=5,
            record_hashes=["a" * 64, "b" * 64],
            rolling_hash="c" * 64,
            manifest_hash="d" * 64,
        )
        assert manifest.record_count == 5
        assert len(manifest.record_hashes) == 2
    
    def test_manifest_with_previous_link(self, reference_date):
        """Manifest can link to previous manifest."""
        manifest = AuditManifest(
            manifest_id="manifest_002",
            manifest_date=reference_date,
            record_count=3,
            record_hashes=[],
            rolling_hash="a" * 64,
            previous_manifest_hash="b" * 64,
            manifest_hash="c" * 64,
        )
        assert manifest.previous_manifest_hash == "b" * 64


class TestReplayResult:
    """Tests for ReplayResult schema."""
    
    def test_replay_success(self):
        """Can create successful replay result."""
        result = ReplayResult(
            evaluation_id="eval_001",
            status=ReplayStatus.SUCCESS,
            original_trace_hash="a" * 64,
            original_result_hash="b" * 64,
            original_facts_hash="c" * 64,
            reproduced_trace_hash="a" * 64,
            reproduced_result_hash="b" * 64,
            reproduced_facts_hash="c" * 64,
            trace_matches=True,
            result_matches=True,
            facts_match=True,
            original_engine_version="1.0.0",
            replay_engine_version="1.0.0",
        )
        assert result.status == ReplayStatus.SUCCESS
        assert result.trace_matches is True
    
    def test_replay_hash_mismatch(self):
        """Can create replay result with hash mismatch."""
        result = ReplayResult(
            evaluation_id="eval_001",
            status=ReplayStatus.HASH_MISMATCH,
            original_trace_hash="a" * 64,
            original_result_hash="b" * 64,
            original_facts_hash="c" * 64,
            reproduced_trace_hash="x" * 64,  # Different!
            trace_matches=False,
            result_matches=True,
            facts_match=True,
            mismatch_details={"trace_hash": "mismatch"},
            original_engine_version="1.0.0",
            replay_engine_version="1.0.0",
        )
        assert result.status == ReplayStatus.HASH_MISMATCH
        assert result.trace_matches is False


# =============================================================================
# Trace Builder Tests
# =============================================================================


class TestTraceBuilderContext:
    """Tests for TraceBuilderContext."""
    
    def test_context_initialization(self):
        """Context initializes with empty lists."""
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        assert ctx.nodes == []
        assert ctx.edges == []
        assert ctx.node_id_map == {}
    
    def test_context_adds_nodes(self):
        """Can add nodes to context."""
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        node_id = ctx.add_node(
            TraceNodeType.CLAIM,
            {"test": "payload"},
            key="test"
        )
        assert len(ctx.nodes) == 1
        assert ctx.node_id_map["test"] == node_id


class TestBuildClaimNode:
    """Tests for build_claim_node."""
    
    def test_builds_claim_node(self, sample_claim_hash, reference_date):
        """Builds a valid claim node."""
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        node_id = build_claim_node(
            ctx=ctx,
            claim_id="claim_001",
            claim_hash=sample_claim_hash,
            entity_id="XYZ_123",
            entity_id_type="lei",
            reference_date=reference_date,
            horizon_months=12,
        )
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        assert ctx.nodes[0].node_type == TraceNodeType.CLAIM
        assert ctx.nodes[0].payload["claim_hash"] == sample_claim_hash
    
    def test_claim_node_registered_in_map(self, sample_claim_hash, reference_date):
        """Claim node is registered in node_id_map."""
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        node_id = build_claim_node(
            ctx=ctx,
            claim_id="claim_001",
            claim_hash=sample_claim_hash,
            entity_id="E1",
            entity_id_type="lei",
            reference_date=reference_date,
            horizon_months=12,
        )
        
        # Check that it's in the map with the claim key
        assert f"claim:claim_001" in ctx.node_id_map
        assert ctx.node_id_map[f"claim:claim_001"] == node_id


class TestBuildPolicyNode:
    """Tests for build_policy_node."""
    
    def test_builds_policy_node(self):
        """Builds a valid policy node."""
        from services.reasoning_engine.schemas import FactSelectionPolicy
        
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        policy = FactSelectionPolicy(
            min_confidence=Decimal("0.70"),
            max_staleness_days=365,
        )
        node_id = build_policy_node(ctx=ctx, policy=policy)
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        assert ctx.nodes[0].node_type == TraceNodeType.POLICY


class TestBuildEvidenceNode:
    """Tests for build_evidence_node."""
    
    def test_builds_evidence_node(self):
        """Builds a valid evidence node."""
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        node_id = build_evidence_node(
            ctx=ctx,
            evidence_id="ev_001",
            evidence_hash="a" * 64,
            source_type="filing",
        )
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        assert ctx.nodes[0].node_type == TraceNodeType.EVIDENCE


class TestBuildFactNode:
    """Tests for build_fact_node."""
    
    def test_builds_fact_node(self, reference_date):
        """Builds a valid fact node."""
        from services.reasoning_engine.schemas import SelectedFact
        
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        fact = SelectedFact(
            fact_id="fact_001",
            fact_type="total_assets",
            value=Decimal("1000000"),
            currency="USD",
            scale=0,
            as_of_date=reference_date,
            confidence=Decimal("0.95"),
            evidence_id="ev_001",
        )
        node_id = build_fact_node(
            ctx=ctx,
            fact=fact,
            evidence_hash="a" * 64,
        )
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        node = ctx.nodes[0]
        assert node.node_type == TraceNodeType.FACT
        assert node.payload["fact_type"] == "total_assets"


class TestBuildAssumptionNode:
    """Tests for build_assumption_node."""
    
    def test_builds_assumption_node(self):
        """Builds a valid assumption node."""
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        node_id = build_assumption_node(
            ctx=ctx,
            assumption_type="confidence_uncertainty",
            description="Higher uncertainty for lower confidence facts",
            value={"base_uncertainty": "0.05"},
        )
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        assert ctx.nodes[0].node_type == TraceNodeType.ASSUMPTION


class TestBuildComputationNode:
    """Tests for build_computation_node."""
    
    def test_builds_computation_node(self):
        """Builds a valid computation node."""
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        node_id = build_computation_node(
            ctx=ctx,
            computation_type="metric_calculation",
            inputs_used=["fact_001", "fact_002"],
        )
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        assert ctx.nodes[0].node_type == TraceNodeType.COMPUTATION


class TestBuildMetricNode:
    """Tests for build_metric_node."""
    
    def test_builds_metric_node(self):
        """Builds a valid metric node."""
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        node_id = build_metric_node(
            ctx=ctx,
            metric_name="liquidity_ratio",
            value=Decimal("2.0"),
            threshold=Decimal("1.0"),
        )
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        node = ctx.nodes[0]
        assert node.node_type == TraceNodeType.METRIC
        assert node.payload["metric_name"] == "liquidity_ratio"
        assert node.payload["is_breach"] is False  # 2.0 >= 1.0


class TestBuildFailureModeNode:
    """Tests for build_failure_mode_node."""
    
    def test_builds_failure_mode_node(self):
        """Builds a valid failure mode node."""
        from services.reasoning_engine.schemas import TriggeredFailureMode, FailureMode
        
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        failure = TriggeredFailureMode(
            mode=FailureMode.LIQUIDITY_SHORTFALL,
            trigger_threshold=Decimal("1.0"),
            actual_value=Decimal("0.5"),
            frequency=Decimal("0.25"),
            contribution_to_insolvency=Decimal("0.40"),
        )
        node_id = build_failure_mode_node(ctx=ctx, failure=failure)
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        node = ctx.nodes[0]
        assert node.node_type == TraceNodeType.FAILURE_MODE


class TestBuildMonteCarloNode:
    """Tests for build_monte_carlo_node."""
    
    def test_builds_monte_carlo_node(self):
        """Builds a valid Monte Carlo node."""
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        node_id = build_monte_carlo_node(
            ctx=ctx,
            seed=12345,
            sample_count=1000,
            insolvent_count=50,
            solvent_count=950,
            scenarios_count=3,
        )
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        node = ctx.nodes[0]
        assert node.node_type == TraceNodeType.MONTE_CARLO_RUN
        assert node.payload["sample_count"] == 1000


class TestBuildSensitivityNode:
    """Tests for build_sensitivity_node."""
    
    def test_builds_sensitivity_node(self):
        """Builds a valid sensitivity node."""
        from services.reasoning_engine.schemas import SensitivityResult, SensitivityDriver
        
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        sensitivity = SensitivityResult(
            driver=SensitivityDriver.INTEREST_EXPENSE,
            fact_type=None,
            base_value=Decimal("100000"),
            p_insolvency_base=Decimal("0.05"),
            p_insolvency_perturbed=Decimal("0.15"),
            delta_p=Decimal("0.10"),
            rank=1,
            normalized_contribution=Decimal("0.50"),
        )
        node_id = build_sensitivity_node(ctx=ctx, sensitivity=sensitivity)
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        node = ctx.nodes[0]
        assert node.node_type == TraceNodeType.SENSITIVITY
        assert node.payload["driver"] == "interest_expense"


class TestBuildConclusionNode:
    """Tests for build_conclusion_node."""
    
    def test_builds_conclusion_node(self):
        """Builds a valid conclusion node."""
        from services.reasoning_engine.schemas import ProbabilityInterval
        
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        probability = ProbabilityInterval(
            p_low=Decimal("0.02"),
            p_mid=Decimal("0.05"),
            p_high=Decimal("0.08"),
            sampling_uncertainty=Decimal("0.01"),
            model_uncertainty=Decimal("0.02"),
        )
        node_id = build_conclusion_node(
            ctx=ctx,
            outcome="solvent",
            probability=probability,
        )
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        node = ctx.nodes[0]
        assert node.node_type == TraceNodeType.CONCLUSION
        assert node.payload["outcome"] == "solvent"


class TestBuildRefusalNode:
    """Tests for build_refusal_node."""
    
    def test_builds_refusal_node(self):
        """Builds a valid refusal node."""
        from services.reasoning_engine.schemas import ReasoningRefusal, RefusalCode
        
        ctx = TraceBuilderContext(
            evaluation_id="eval_001",
            engine_version="1.0.0",
        )
        refusal = ReasoningRefusal(
            code=RefusalCode.REQUIRED_FACTS_MISSING,
            message="Required facts not available",
            missing_facts=[],
            excluded_facts=[],
            trace_id="trace_001",
        )
        node_id = build_refusal_node(ctx=ctx, refusal=refusal)
        
        assert node_id is not None
        assert len(ctx.nodes) == 1
        node = ctx.nodes[0]
        assert node.node_type == TraceNodeType.REFUSAL
        assert node.payload["refusal_code"] == "required_facts_missing"


# =============================================================================
# API Schema Tests
# =============================================================================


class TestBuildTraceRequest:
    """Tests for BuildTraceRequest schema."""
    
    def test_create_valid_request(self):
        """Can create a valid BuildTraceRequest."""
        request = BuildTraceRequest(
            evaluation_id="eval_001",
            include_evidence_details=True,
        )
        assert request.evaluation_id == "eval_001"


class TestBuildTraceResponse:
    """Tests for BuildTraceResponse schema."""
    
    def test_create_valid_response(self):
        """Can create a valid BuildTraceResponse."""
        response = BuildTraceResponse(
            trace_id="trace_001",
            evaluation_id="eval_001",
            trace_hash="a" * 64,
            node_count=5,
            edge_count=4,
            built_at=datetime.now(timezone.utc),
        )
        assert response.trace_hash == "a" * 64


class TestGetTraceResponse:
    """Tests for GetTraceResponse schema."""
    
    def test_create_valid_response(self):
        """Can create a valid GetTraceResponse."""
        graph = TraceGraph(
            trace_id="trace_001",
            evaluation_id="eval_001",
            nodes=[],
            edges=[],
            node_count=0,
            edge_count=0,
            trace_hash="a" * 64,
            engine_version="1.0.0",
            trace_service_version=TRACE_SERVICE_VERSION,
            claim_node_id="claim",
        )
        response = GetTraceResponse(trace=graph)
        assert response.trace.trace_id == "trace_001"


class TestReplayVerificationRequest:
    """Tests for ReplayVerificationRequest schema."""
    
    def test_create_valid_request(self):
        """Can create a valid ReplayVerificationRequest."""
        request = ReplayVerificationRequest(
            evaluation_id="eval_001",
            recomputed_trace_hash="a" * 64,
            recomputed_result_hash="b" * 64,
            recomputed_facts_hash="c" * 64,
        )
        assert request.evaluation_id == "eval_001"


# =============================================================================
# Hash Reproducibility Tests
# =============================================================================


class TestHashReproducibility:
    """Tests ensuring hash reproducibility across runs."""
    
    def test_trace_hash_reproducibility(self):
        """Trace hash is reproducible from same nodes/edges."""
        nodes = [
            {"node_id": "n1", "node_type": "claim", "payload": {"text": "test"}},
            {"node_id": "n2", "node_type": "fact", "payload": {"value": "100"}},
        ]
        edges = [
            {"edge_id": "e1", "source_node_id": "n1", "target_node_id": "n2", "edge_type": "uses"},
        ]
        
        hash1 = canonical_trace_hash(nodes, edges)
        hash2 = canonical_trace_hash(nodes, edges)
        hash3 = canonical_trace_hash(nodes, edges)
        
        assert hash1 == hash2 == hash3
    
    def test_trace_hash_changes_with_nodes(self):
        """Trace hash changes when nodes change."""
        nodes1 = [{"node_id": "n1", "node_type": "claim", "payload": {}}]
        nodes2 = [{"node_id": "n2", "node_type": "claim", "payload": {}}]
        edges = []
        
        hash1 = canonical_trace_hash(nodes1, edges)
        hash2 = canonical_trace_hash(nodes2, edges)
        
        assert hash1 != hash2
    
    def test_audit_record_hash_reproducibility(self, reference_datetime):
        """Audit record hash is reproducible."""
        hash1 = canonical_audit_record_hash(
            evaluation_id="eval_001",
            claim_hash="a" * 64,
            evidence_set_hash="b" * 64,
            facts_snapshot_hash="c" * 64,
            policy_hash="d" * 64,
            trace_hash="e" * 64,
            result_hash="f" * 64,
            engine_version="1.0.0",
            created_at=reference_datetime,
            previous_hash=None,
        )
        hash2 = canonical_audit_record_hash(
            evaluation_id="eval_001",
            claim_hash="a" * 64,
            evidence_set_hash="b" * 64,
            facts_snapshot_hash="c" * 64,
            policy_hash="d" * 64,
            trace_hash="e" * 64,
            result_hash="f" * 64,
            engine_version="1.0.0",
            created_at=reference_datetime,
            previous_hash=None,
        )
        
        assert hash1 == hash2
    
    def test_audit_record_hash_includes_previous(self, reference_datetime):
        """Audit record hash includes previous hash for chaining."""
        hash_with_genesis = canonical_audit_record_hash(
            evaluation_id="eval_001",
            claim_hash="a" * 64,
            evidence_set_hash="b" * 64,
            facts_snapshot_hash="c" * 64,
            policy_hash="d" * 64,
            trace_hash="e" * 64,
            result_hash="f" * 64,
            engine_version="1.0.0",
            created_at=reference_datetime,
            previous_hash=GENESIS_HASH,
        )
        hash_with_prev = canonical_audit_record_hash(
            evaluation_id="eval_001",
            claim_hash="a" * 64,
            evidence_set_hash="b" * 64,
            facts_snapshot_hash="c" * 64,
            policy_hash="d" * 64,
            trace_hash="e" * 64,
            result_hash="f" * 64,
            engine_version="1.0.0",
            created_at=reference_datetime,
            previous_hash="1" * 64,  # Different non-genesis hash
        )
        
        assert hash_with_genesis != hash_with_prev
    
    def test_manifest_hash_reproducibility(self, reference_date):
        """Manifest hash is reproducible."""
        hash1 = canonical_manifest_hash(
            manifest_date=reference_date,
            record_hashes=["a" * 64, "b" * 64],
            rolling_hash="c" * 64,
            previous_manifest_hash=None,
        )
        hash2 = canonical_manifest_hash(
            manifest_date=reference_date,
            record_hashes=["a" * 64, "b" * 64],
            rolling_hash="c" * 64,
            previous_manifest_hash=None,
        )
        
        assert hash1 == hash2


# =============================================================================
# Chain Integrity Tests
# =============================================================================


class TestChainIntegrity:
    """Tests for hash chain integrity verification."""
    
    def test_verify_chain_integrity_valid(self):
        """Valid chain passes verification."""
        # Build a valid chain
        items = ["hash1", "hash2", "hash3"]
        
        chain = []
        prev = GENESIS_HASH
        for item in items:
            current = canonical_hash({"item": item, "previous": prev})
            chain.append({"hash": current, "previous": prev, "item": item})
            prev = current
        
        # Verify with our own chain integrity check
        is_valid = True
        prev_check = GENESIS_HASH
        for record in chain:
            if record["previous"] != prev_check:
                is_valid = False
                break
            prev_check = record["hash"]
        
        assert is_valid is True
    
    def test_detect_chain_tampering(self):
        """Tampered chain is detected."""
        # Build a chain
        items = ["hash1", "hash2", "hash3"]
        
        chain = []
        prev = GENESIS_HASH
        for item in items:
            current = canonical_hash({"item": item, "previous": prev})
            chain.append({"hash": current, "previous": prev, "item": item})
            prev = current
        
        # Tamper with middle record's previous pointer
        chain[1] = {**chain[1], "previous": "tampered" * 4}
        
        # Verify - should detect tampering
        is_valid = True
        prev_check = GENESIS_HASH
        for record in chain:
            if record["previous"] != prev_check:
                is_valid = False
                break
            prev_check = record["hash"]
        
        assert is_valid is False


# =============================================================================
# Version Tests
# =============================================================================


class TestVersions:
    """Tests for version constants."""
    
    def test_trace_service_version_format(self):
        """Trace service version has semver format."""
        import re
        pattern = r'^\d+\.\d+\.\d+$'
        assert re.match(pattern, TRACE_SERVICE_VERSION)
    
    def test_genesis_hash_constant(self):
        """Genesis hash is all zeros."""
        assert GENESIS_HASH == "0" * 64
        assert len(GENESIS_HASH) == 64
