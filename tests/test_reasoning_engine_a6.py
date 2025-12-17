"""
A6 Reasoning Engine Tests
=========================

Comprehensive test suite for the Reasoning Engine (A6).

Tests cover:
1. Schema validation and serialization
2. Deterministic seeding (same inputs → same results)
3. Fact selection with tie-breakers and policies
4. Missing-fact refusals
5. Stale/low-confidence fact filtering
6. Scenario shock application
7. Solvency computation on synthetic cases
8. Monte Carlo simulation determinism
9. Sensitivity analysis ordering
10. REST API endpoints
"""

import hashlib
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.reasoning_engine.schemas import (
    # Constants
    ENGINE_VERSION,
    DEFAULT_SAMPLE_COUNT,
    REQUIRED_SOLVENCY_FACTS,
    MATERIAL_SOLVENCY_FACTS,
    CONFIDENCE_TO_UNCERTAINTY,
    # Enums
    EvaluationStatus,
    SolvencyOutcome,
    RefusalCode,
    FailureMode,
    SensitivityDriver,
    # Core schemas
    ScenarioShock,
    Scenario,
    FactSelectionPolicy,
    SelectedFact,
    MissingFact,
    ComputedMetrics,
    StressedMetrics,
    TriggeredFailureMode,
    ProbabilityInterval,
    SensitivityResult,
    SensitivityAnalysis,
    ReasoningRefusal,
    ReasoningArtifact,
    SolvencyEvaluationRequest,
    SolvencyEvaluationResult,
)
from services.reasoning_engine.solvency import (
    # Constants
    LIQUIDITY_THRESHOLD,
    INTEREST_COVERAGE_THRESHOLD,
    DEBT_SERVICE_THRESHOLD,
    CASH_RUNWAY_MONTHS_THRESHOLD,
    # Types
    FactCandidate,
    ClaimContext,
    EvaluationInput,
    # Pure functions
    derive_seed,
    select_facts,
    compute_metrics,
    apply_scenario_shocks,
    detect_failure_modes,
    is_insolvent,
    run_monte_carlo,
    compute_probability_interval,
    compute_sensitivity,
    evaluate_solvency,
)
from services.reasoning_engine.app import create_app


# =============================================================================
# Test Helpers
# =============================================================================


def make_fact_candidate(
    fact_id: str,
    fact_type: str,
    value: Decimal,
    confidence: Decimal = Decimal("0.90"),
    as_of_date: date | None = None,
    period_end: date | None = None,
    currency: str = "USD",
    scale: int = 0,
    evidence_id: str = "ev_001",
    evidence_hash: str = "evhash_001",
    fact_hash: str | None = None,
) -> FactCandidate:
    """Helper to create a FactCandidate with defaults."""
    if as_of_date is None:
        as_of_date = date(2024, 12, 31)
    if fact_hash is None:
        fact_hash = hashlib.sha256(f"{fact_type}_{fact_id}".encode()).hexdigest()[:32]
    return FactCandidate(
        fact_id=fact_id,
        fact_type=fact_type,
        value=value,
        currency=currency,
        scale=scale,
        as_of_date=as_of_date,
        period_end=period_end,
        confidence=confidence,
        evidence_id=evidence_id,
        evidence_hash=evidence_hash,
        fact_hash=fact_hash,
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def reference_date() -> date:
    """Fixed reference date for tests."""
    return date(2024, 12, 31)


@pytest.fixture
def default_policy() -> FactSelectionPolicy:
    """Default fact selection policy."""
    return FactSelectionPolicy(
        min_confidence=Decimal("0.70"),
        max_staleness_days=365,
    )


@pytest.fixture
def entity_id() -> str:
    """Test entity identifier."""
    return "TEST_CORP_001"


@pytest.fixture
def entity_id_type() -> str:
    """Test entity identifier type."""
    return "lei"


@pytest.fixture
def claim_hash() -> str:
    """Test claim hash."""
    return hashlib.sha256(b"test_claim").hexdigest()[:32]


@pytest.fixture
def evidence_set_hash() -> str:
    """Test evidence set hash."""
    return hashlib.sha256(b"test_evidence").hexdigest()[:32]


@pytest.fixture
def solvent_facts() -> dict[str, FactCandidate]:
    """Facts representing a solvent entity."""
    ref_date = date(2024, 12, 31)
    return {
        "total_assets": make_fact_candidate(
            "fact_001", "total_assets", Decimal("1000000"),
            confidence=Decimal("0.95"), as_of_date=ref_date,
        ),
        "total_liabilities": make_fact_candidate(
            "fact_002", "total_liabilities", Decimal("400000"),
            confidence=Decimal("0.95"), as_of_date=ref_date,
        ),
        "current_assets": make_fact_candidate(
            "fact_003", "current_assets", Decimal("300000"),
            confidence=Decimal("0.90"), as_of_date=ref_date,
        ),
        "current_liabilities": make_fact_candidate(
            "fact_004", "current_liabilities", Decimal("150000"),
            confidence=Decimal("0.90"), as_of_date=ref_date,
        ),
        "cash_and_equivalents": make_fact_candidate(
            "fact_005", "cash_and_equivalents", Decimal("200000"),
            confidence=Decimal("0.95"), as_of_date=ref_date,
        ),
        "total_debt": make_fact_candidate(
            "fact_006", "total_debt", Decimal("300000"),
            confidence=Decimal("0.90"), as_of_date=ref_date,
        ),
        "interest_expense": make_fact_candidate(
            "fact_008", "interest_expense", Decimal("20000"),
            confidence=Decimal("0.90"), as_of_date=ref_date,
        ),
        "operating_income": make_fact_candidate(
            "fact_009", "operating_income", Decimal("100000"),
            confidence=Decimal("0.85"), as_of_date=ref_date,
        ),
        "operating_cash_flow": make_fact_candidate(
            "fact_010", "operating_cash_flow", Decimal("80000"),
            confidence=Decimal("0.85"), as_of_date=ref_date,
        ),
        "total_equity": make_fact_candidate(
            "fact_012", "total_equity", Decimal("600000"),
            confidence=Decimal("0.95"), as_of_date=ref_date,
        ),
    }


@pytest.fixture
def insolvent_facts() -> dict[str, FactCandidate]:
    """Facts representing an insolvent entity."""
    ref_date = date(2024, 12, 31)
    return {
        "total_assets": make_fact_candidate(
            "bad_001", "total_assets", Decimal("300000"),
            confidence=Decimal("0.95"), as_of_date=ref_date,
        ),
        "total_liabilities": make_fact_candidate(
            "bad_002", "total_liabilities", Decimal("500000"),
            confidence=Decimal("0.95"), as_of_date=ref_date,
        ),
        "current_assets": make_fact_candidate(
            "bad_003", "current_assets", Decimal("50000"),
            confidence=Decimal("0.90"), as_of_date=ref_date,
        ),
        "current_liabilities": make_fact_candidate(
            "bad_004", "current_liabilities", Decimal("200000"),
            confidence=Decimal("0.90"), as_of_date=ref_date,
        ),
        "cash_and_equivalents": make_fact_candidate(
            "bad_005", "cash_and_equivalents", Decimal("10000"),
            confidence=Decimal("0.95"), as_of_date=ref_date,
        ),
        "total_debt": make_fact_candidate(
            "bad_006", "total_debt", Decimal("400000"),
            confidence=Decimal("0.90"), as_of_date=ref_date,
        ),
        "interest_expense": make_fact_candidate(
            "bad_008", "interest_expense", Decimal("50000"),
            confidence=Decimal("0.90"), as_of_date=ref_date,
        ),
        "operating_income": make_fact_candidate(
            "bad_009", "operating_income", Decimal("40000"),
            confidence=Decimal("0.85"), as_of_date=ref_date,
        ),
        "operating_cash_flow": make_fact_candidate(
            "bad_010", "operating_cash_flow", Decimal("10000"),
            confidence=Decimal("0.85"), as_of_date=ref_date,
        ),
        "total_equity": make_fact_candidate(
            "bad_012", "total_equity", Decimal("-200000"),  # Negative equity!
            confidence=Decimal("0.95"), as_of_date=ref_date,
        ),
    }


@pytest.fixture
def base_scenario() -> Scenario:
    """Default baseline scenario."""
    return Scenario(
        scenario_id="base",
        name="Baseline",
        shocks=[],
        is_baseline=True,
    )


@pytest.fixture
def stress_scenario() -> Scenario:
    """Stress scenario with interest rate shock."""
    return Scenario(
        scenario_id="stress",
        name="Rate Shock",
        shocks=[
            ScenarioShock(
                shock_type="interest_rate",
                magnitude_bps=100,  # 100 basis points = 1%
            )
        ],
    )


@pytest.fixture
def severe_scenario() -> Scenario:
    """Severe stress scenario."""
    return Scenario(
        scenario_id="severe",
        name="Severe Stress",
        shocks=[
            ScenarioShock(
                shock_type="interest_rate",
                magnitude_bps=200,
            ),
            ScenarioShock(
                shock_type="revenue_decline",
                magnitude_bps=2000,  # 20%
            ),
            ScenarioShock(
                shock_type="asset_impairment",
                magnitude_bps=1000,  # 10%
            ),
        ],
    )


@pytest.fixture
def test_client() -> TestClient:
    """FastAPI test client."""
    app = create_app()
    return TestClient(app)


# =============================================================================
# Schema Tests
# =============================================================================


class TestSchemas:
    """Test schema validation and serialization."""
    
    def test_scenario_shock_validation(self) -> None:
        """Test ScenarioShock field validation."""
        shock = ScenarioShock(
            shock_type="interest_rate",
            magnitude_bps=100,
        )
        assert shock.shock_type == "interest_rate"
        assert shock.magnitude_bps == 100
        assert shock.direction == "up"  # Default
    
    def test_scenario_shock_is_frozen(self) -> None:
        """Test ScenarioShock is immutable."""
        shock = ScenarioShock(
            shock_type="interest_rate",
            magnitude_bps=100,
        )
        with pytest.raises(Exception):  # ValidationError for frozen
            shock.magnitude_bps = 200  # type: ignore
    
    def test_fact_selection_policy_defaults(self) -> None:
        """Test FactSelectionPolicy default values."""
        policy = FactSelectionPolicy()
        assert policy.min_confidence == Decimal("0.60")  # DEFAULT_MIN_CONFIDENCE
        assert policy.max_staleness_days == 365
        assert policy.prefer_higher_confidence is True
    
    def test_probability_interval_bounds(self) -> None:
        """Test ProbabilityInterval probability bounds."""
        interval = ProbabilityInterval(
            p_low=Decimal("0.05"),
            p_mid=Decimal("0.10"),
            p_high=Decimal("0.15"),
            sampling_uncertainty=Decimal("0.02"),
            model_uncertainty=Decimal("0.05"),
        )
        assert Decimal("0") <= interval.p_low <= Decimal("1")
        assert Decimal("0") <= interval.p_mid <= Decimal("1")
        assert Decimal("0") <= interval.p_high <= Decimal("1")
        assert interval.p_low <= interval.p_mid <= interval.p_high
    
    def test_computed_metrics_basic(self) -> None:
        """Test ComputedMetrics creation."""
        metrics = ComputedMetrics(
            current_ratio=Decimal("2.0"),
            quick_ratio=Decimal("1.5"),
            cash_ratio=Decimal("1.0"),
            debt_to_equity=Decimal("0.5"),
            debt_to_assets=Decimal("0.3"),
            interest_coverage=Decimal("5.0"),
            debt_service_coverage=Decimal("3.0"),
            free_cash_flow=Decimal("100000"),
            cash_burn_months=Decimal("24"),
        )
        assert metrics.current_ratio == Decimal("2.0")
        assert metrics.cash_burn_months == Decimal("24")
    
    def test_refusal_code_enum(self) -> None:
        """Test RefusalCode enumeration values."""
        assert RefusalCode.REQUIRED_FACTS_MISSING.value == "required_facts_missing"
        assert RefusalCode.FACTS_STALE.value == "facts_stale"
        assert RefusalCode.FACTS_LOW_CONFIDENCE.value == "facts_low_confidence"
    
    def test_evaluation_status_enum(self) -> None:
        """Test EvaluationStatus enumeration values."""
        assert EvaluationStatus.PENDING.value == "pending"
        assert EvaluationStatus.RUNNING.value == "running"
        assert EvaluationStatus.COMPLETED.value == "completed"
        assert EvaluationStatus.REFUSED.value == "refused"
    
    def test_solvency_outcome_enum(self) -> None:
        """Test SolvencyOutcome enumeration values."""
        assert SolvencyOutcome.SOLVENT.value == "solvent"
        assert SolvencyOutcome.INSOLVENT.value == "insolvent"
        assert SolvencyOutcome.INDETERMINATE.value == "indeterminate"


# =============================================================================
# Deterministic Seeding Tests
# =============================================================================


class TestDeterministicSeeding:
    """Test that seeding produces deterministic results."""
    
    def test_derive_seed_same_inputs(
        self,
        claim_hash: str,
        evidence_set_hash: str,
    ) -> None:
        """Same inputs produce same seed."""
        seed1 = derive_seed(claim_hash, evidence_set_hash, ENGINE_VERSION)
        seed2 = derive_seed(claim_hash, evidence_set_hash, ENGINE_VERSION)
        assert seed1 == seed2
    
    def test_derive_seed_different_claim(
        self,
        claim_hash: str,
        evidence_set_hash: str,
    ) -> None:
        """Different claim hash produces different seed."""
        seed1 = derive_seed(claim_hash, evidence_set_hash, ENGINE_VERSION)
        other_hash = hashlib.sha256(b"other_claim").hexdigest()[:32]
        seed2 = derive_seed(other_hash, evidence_set_hash, ENGINE_VERSION)
        assert seed1 != seed2
    
    def test_derive_seed_different_evidence(
        self,
        claim_hash: str,
        evidence_set_hash: str,
    ) -> None:
        """Different evidence set hash produces different seed."""
        seed1 = derive_seed(claim_hash, evidence_set_hash, ENGINE_VERSION)
        other_hash = hashlib.sha256(b"other_evidence").hexdigest()[:32]
        seed2 = derive_seed(claim_hash, other_hash, ENGINE_VERSION)
        assert seed1 != seed2
    
    def test_derive_seed_different_version(
        self,
        claim_hash: str,
        evidence_set_hash: str,
    ) -> None:
        """Different engine version produces different seed."""
        seed1 = derive_seed(claim_hash, evidence_set_hash, ENGINE_VERSION)
        seed2 = derive_seed(claim_hash, evidence_set_hash, "2.0.0")
        assert seed1 != seed2
    
    def test_seed_is_valid_integer(
        self,
        claim_hash: str,
        evidence_set_hash: str,
    ) -> None:
        """Seed is a valid positive integer within range."""
        seed = derive_seed(claim_hash, evidence_set_hash, ENGINE_VERSION)
        assert isinstance(seed, int)
        assert 0 <= seed < 2**31 - 1


# =============================================================================
# Fact Selection Tests
# =============================================================================


class TestFactSelection:
    """Test fact selection with policies and tie-breakers."""
    
    def test_select_all_required_facts(
        self,
        solvent_facts: dict[str, FactCandidate],
        reference_date: date,
        default_policy: FactSelectionPolicy,
    ) -> None:
        """Select facts when all required are present."""
        candidates = list(solvent_facts.values())
        required = frozenset({"total_assets", "total_liabilities"})
        
        selected, missing = select_facts(
            candidates, required, reference_date, default_policy
        )
        
        assert len(missing) == 0
        selected_types = {f.fact_type for f in selected}
        assert required.issubset(selected_types)
    
    def test_missing_required_facts(
        self,
        solvent_facts: dict[str, FactCandidate],
        reference_date: date,
        default_policy: FactSelectionPolicy,
    ) -> None:
        """Detect missing required facts."""
        # Remove a required fact
        candidates = [f for f in solvent_facts.values() if f.fact_type != "total_assets"]
        required = frozenset({"total_assets", "total_liabilities"})
        
        selected, missing = select_facts(
            candidates, required, reference_date, default_policy
        )
        
        assert len(missing) == 1
        assert missing[0].fact_type == "total_assets"
    
    def test_stale_fact_rejection(
        self,
        reference_date: date,
        default_policy: FactSelectionPolicy,
    ) -> None:
        """Stale facts beyond max_staleness_days are rejected."""
        old_date = reference_date - timedelta(days=400)  # Beyond 365-day limit
        
        candidates = [
            make_fact_candidate(
                "stale_001", "total_assets", Decimal("1000000"),
                confidence=Decimal("0.95"), as_of_date=old_date,
            )
        ]
        required = frozenset({"total_assets"})
        
        selected, missing = select_facts(
            candidates, required, reference_date, default_policy
        )
        
        assert len(selected) == 0
        assert len(missing) == 1
    
    def test_low_confidence_rejection(
        self,
        reference_date: date,
        default_policy: FactSelectionPolicy,
    ) -> None:
        """Facts below min_confidence are rejected."""
        candidates = [
            make_fact_candidate(
                "low_conf_001", "total_assets", Decimal("1000000"),
                confidence=Decimal("0.50"), as_of_date=reference_date,  # Below 0.70 threshold
            )
        ]
        required = frozenset({"total_assets"})
        
        selected, missing = select_facts(
            candidates, required, reference_date, default_policy
        )
        
        assert len(selected) == 0
        assert len(missing) == 1
    
    def test_tie_breaker_fresher_date(
        self,
        reference_date: date,
        default_policy: FactSelectionPolicy,
    ) -> None:
        """When confidence is equal, prefer fresher date."""
        candidates = [
            make_fact_candidate(
                "old_001", "total_assets", Decimal("900000"),
                confidence=Decimal("0.90"),
                as_of_date=reference_date - timedelta(days=30),
            ),
            make_fact_candidate(
                "new_001", "total_assets", Decimal("1000000"),
                confidence=Decimal("0.90"),  # Same confidence
                as_of_date=reference_date - timedelta(days=10),  # Fresher
            ),
        ]
        required = frozenset({"total_assets"})
        
        selected, missing = select_facts(
            candidates, required, reference_date, default_policy
        )
        
        assert len(selected) == 1
        assert selected[0].fact_id == "new_001"
    
    def test_tie_breaker_higher_confidence(
        self,
        reference_date: date,
        default_policy: FactSelectionPolicy,
    ) -> None:
        """When date is same, prefer higher confidence."""
        same_date = reference_date - timedelta(days=10)
        candidates = [
            make_fact_candidate(
                "low_001", "total_assets", Decimal("900000"),
                confidence=Decimal("0.80"),
                as_of_date=same_date,
            ),
            make_fact_candidate(
                "high_001", "total_assets", Decimal("1000000"),
                confidence=Decimal("0.95"),  # Higher confidence
                as_of_date=same_date,
            ),
        ]
        required = frozenset({"total_assets"})
        
        selected, missing = select_facts(
            candidates, required, reference_date, default_policy
        )
        
        assert len(selected) == 1
        assert selected[0].fact_id == "high_001"
    
    def test_tie_breaker_hash_stable(
        self,
        reference_date: date,
        default_policy: FactSelectionPolicy,
    ) -> None:
        """When all else equal, use hash for stable ordering."""
        same_date = reference_date
        candidates = [
            make_fact_candidate(
                "a_001", "total_assets", Decimal("1000000"),
                confidence=Decimal("0.90"),
                as_of_date=same_date,
                fact_hash="aaaaaa",  # Lexicographically first
            ),
            make_fact_candidate(
                "z_001", "total_assets", Decimal("1000000"),
                confidence=Decimal("0.90"),
                as_of_date=same_date,
                fact_hash="zzzzzz",  # Lexicographically last
            ),
        ]
        required = frozenset({"total_assets"})
        
        selected1, _ = select_facts(candidates, required, reference_date, default_policy)
        selected2, _ = select_facts(candidates, required, reference_date, default_policy)
        
        # Result should be deterministic
        assert selected1[0].fact_id == selected2[0].fact_id


# =============================================================================
# Metrics Computation Tests
# =============================================================================


class TestMetricsComputation:
    """Test financial metrics computation."""
    
    def test_compute_solvent_metrics(
        self,
        solvent_facts: dict[str, FactCandidate],
    ) -> None:
        """Compute metrics for solvent entity."""
        facts = {f.fact_type: f.value for f in solvent_facts.values()}
        metrics = compute_metrics(facts)
        
        # Current ratio = current_assets / current_liabilities = 300000 / 150000 = 2.0
        assert metrics.current_ratio == Decimal("2.0")
        
        # Interest coverage = operating_income / interest_expense = 100000 / 20000 = 5.0
        assert metrics.interest_coverage == Decimal("5.0")
    
    def test_compute_insolvent_metrics(
        self,
        insolvent_facts: dict[str, FactCandidate],
    ) -> None:
        """Compute metrics for insolvent entity."""
        facts = {f.fact_type: f.value for f in insolvent_facts.values()}
        metrics = compute_metrics(facts)
        
        # Current ratio = 50000 / 200000 = 0.25 (below threshold)
        assert metrics.current_ratio == Decimal("0.25")
    
    def test_metrics_handle_zero_divisor(self) -> None:
        """Metrics handle zero values gracefully."""
        facts = {
            "total_assets": Decimal("1000000"),
            "total_liabilities": Decimal("400000"),
            "current_assets": Decimal("300000"),
            "current_liabilities": Decimal("0"),  # Zero!
            "total_debt": Decimal("300000"),
            "total_equity": Decimal("0"),  # Zero!
            "interest_expense": Decimal("0"),  # Zero!
            "operating_income": Decimal("100000"),
        }
        metrics = compute_metrics(facts)
        
        # Should return None for undefined ratios
        assert metrics.current_ratio is None  # Division by zero
        assert metrics.debt_to_equity is None  # Division by zero


# =============================================================================
# Scenario Shocks Tests
# =============================================================================


class TestScenarioShocks:
    """Test scenario shock application."""
    
    def test_apply_interest_rate_shock(self) -> None:
        """Interest rate shock increases interest expense."""
        base_facts = {
            "interest_expense": Decimal("20000"),
            "total_debt": Decimal("300000"),
        }
        scenario = Scenario(
            scenario_id="rate_shock",
            name="Rate Shock",
            shocks=[
                ScenarioShock(
                    shock_type="interest_rate",
                    magnitude_bps=100,  # 1% increase
                )
            ],
        )
        
        shocked = apply_scenario_shocks(base_facts, scenario)
        
        # Interest expense increases proportionally
        assert shocked["interest_expense"] > base_facts["interest_expense"]
    
    def test_apply_revenue_decline_shock(self) -> None:
        """Revenue decline shock reduces operating income."""
        base_facts = {
            "operating_income": Decimal("100000"),
            "operating_cash_flow": Decimal("80000"),
        }
        scenario = Scenario(
            scenario_id="revenue_decline",
            name="Revenue Decline",
            shocks=[
                ScenarioShock(
                    shock_type="revenue_decline",
                    magnitude_bps=2000,  # 20% decline
                )
            ],
        )
        
        shocked = apply_scenario_shocks(base_facts, scenario)
        
        # Operating income reduced by 30% due to 1.5x operating leverage
        # 20% revenue decline * 1.5 = 30% operating income decline
        # 100000 * (1 - 0.20 * 1.5) = 100000 * 0.70 = 70000
        assert shocked["operating_income"] == Decimal("70000.00")
    
    def test_apply_asset_impairment_shock(self) -> None:
        """Asset impairment shock reduces asset values."""
        base_facts = {
            "total_assets": Decimal("1000000"),
            "current_assets": Decimal("300000"),
        }
        scenario = Scenario(
            scenario_id="asset_impair",
            name="Asset Impairment",
            shocks=[
                ScenarioShock(
                    shock_type="asset_impairment",
                    magnitude_bps=1000,  # 10% impairment
                )
            ],
        )
        
        shocked = apply_scenario_shocks(base_facts, scenario)
        
        assert shocked["total_assets"] == Decimal("900000")
        # Note: current_assets is NOT affected by asset_impairment in the implementation
        assert shocked["current_assets"] == Decimal("300000")
    
    def test_apply_multiple_shocks(
        self,
        severe_scenario: Scenario,
    ) -> None:
        """Apply multiple shocks simultaneously."""
        base_facts = {
            "interest_expense": Decimal("20000"),
            "total_debt": Decimal("300000"),
            "operating_income": Decimal("100000"),
            "total_assets": Decimal("1000000"),
        }
        
        shocked = apply_scenario_shocks(base_facts, severe_scenario)
        
        # All affected metrics should change
        assert shocked["operating_income"] < base_facts["operating_income"]
        assert shocked["total_assets"] < base_facts["total_assets"]


# =============================================================================
# Failure Mode Detection Tests
# =============================================================================


class TestFailureModeDetection:
    """Test failure mode detection."""
    
    def test_detect_liquidity_failure(self) -> None:
        """Detect liquidity failure mode."""
        metrics = ComputedMetrics(
            current_ratio=Decimal("0.5"),  # Below 1.0 threshold
            quick_ratio=Decimal("0.3"),
            cash_ratio=Decimal("0.2"),
            debt_to_equity=Decimal("0.5"),
            debt_to_assets=Decimal("0.3"),
            interest_coverage=Decimal("5.0"),
            debt_service_coverage=Decimal("3.0"),
            free_cash_flow=Decimal("100000"),
            cash_burn_months=Decimal("24"),
        )
        facts: dict[str, Decimal] = {}
        
        failures = detect_failure_modes(metrics, facts)
        
        assert any(f[0] == FailureMode.LIQUIDITY_SHORTFALL for f in failures)
    
    def test_detect_interest_coverage_failure(self) -> None:
        """Detect interest coverage failure mode."""
        metrics = ComputedMetrics(
            current_ratio=Decimal("2.0"),
            quick_ratio=Decimal("1.5"),
            cash_ratio=Decimal("1.0"),
            debt_to_equity=Decimal("0.5"),
            debt_to_assets=Decimal("0.3"),
            interest_coverage=Decimal("1.0"),  # Below 1.5 threshold
            debt_service_coverage=Decimal("3.0"),
            free_cash_flow=Decimal("100000"),
            cash_burn_months=Decimal("24"),
        )
        facts: dict[str, Decimal] = {}
        
        failures = detect_failure_modes(metrics, facts)
        
        assert any(f[0] == FailureMode.INTEREST_COVERAGE_BREACH for f in failures)
    
    def test_is_insolvent_with_failures(self) -> None:
        """Entity is insolvent if any failure mode triggered."""
        metrics = ComputedMetrics(
            current_ratio=Decimal("0.3"),  # Below 0.5 severe threshold
            quick_ratio=Decimal("0.2"),
            cash_ratio=Decimal("0.1"),
            debt_to_equity=Decimal("0.5"),
            debt_to_assets=Decimal("0.3"),
            interest_coverage=Decimal("0.5"),  # Below 1.0 threshold
            debt_service_coverage=Decimal("3.0"),
            free_cash_flow=Decimal("100000"),
            cash_burn_months=Decimal("24"),
        )
        # is_insolvent checks: interest_coverage < 1.0, current_ratio < 0.5, total_equity <= 0
        facts: dict[str, Decimal] = {"total_equity": Decimal("-100000")}
        
        result = is_insolvent(metrics, facts)
        
        assert result is True
    
    def test_is_solvent_no_failures(
        self,
        solvent_facts: dict[str, FactCandidate],
    ) -> None:
        """Entity is solvent if no failure modes triggered."""
        facts = {f.fact_type: f.value for f in solvent_facts.values()}
        metrics = compute_metrics(facts)
        
        result = is_insolvent(metrics, facts)
        
        assert result is False


# =============================================================================
# Monte Carlo Tests
# =============================================================================


class TestMonteCarlo:
    """Test Monte Carlo simulation."""
    
    def test_monte_carlo_deterministic(
        self,
        solvent_facts: dict[str, FactCandidate],
        base_scenario: Scenario,
    ) -> None:
        """Monte Carlo produces deterministic results with same seed."""
        base = {f.fact_type: f.value for f in solvent_facts.values()}
        confidences = {f.fact_type: f.confidence for f in solvent_facts.values()}
        scenarios = [base_scenario]
        
        result1 = run_monte_carlo(base, confidences, scenarios, 1000, 42)
        result2 = run_monte_carlo(base, confidences, scenarios, 1000, 42)
        
        assert result1[0] == result2[0]  # Same insolvent count
        assert result1[1] == result2[1]  # Same total count
    
    def test_monte_carlo_different_seeds(
        self,
        solvent_facts: dict[str, FactCandidate],
        base_scenario: Scenario,
    ) -> None:
        """Monte Carlo with different seeds may differ."""
        base = {f.fact_type: f.value for f in solvent_facts.values()}
        confidences = {f.fact_type: f.confidence for f in solvent_facts.values()}
        scenarios = [base_scenario]
        
        result1 = run_monte_carlo(base, confidences, scenarios, 1000, 42)
        result2 = run_monte_carlo(base, confidences, scenarios, 1000, 99)
        
        # Results may or may not differ, but process should complete
        assert result1[1] == result2[1]  # Same total count
    
    def test_monte_carlo_solvent_low_probability(
        self,
        solvent_facts: dict[str, FactCandidate],
        base_scenario: Scenario,
    ) -> None:
        """Solvent entity has low insolvency probability."""
        base = {f.fact_type: f.value for f in solvent_facts.values()}
        confidences = {f.fact_type: f.confidence for f in solvent_facts.values()}
        scenarios = [base_scenario]
        
        insolvent_count, total, failures = run_monte_carlo(
            base, confidences, scenarios, 1000, 42
        )
        
        probability = Decimal(str(insolvent_count)) / Decimal(str(total))
        assert probability < Decimal("0.50")  # Less than 50% insolvent
    
    def test_monte_carlo_insolvent_high_probability(
        self,
        insolvent_facts: dict[str, FactCandidate],
        base_scenario: Scenario,
    ) -> None:
        """Insolvent entity has high insolvency probability."""
        base = {f.fact_type: f.value for f in insolvent_facts.values()}
        confidences = {f.fact_type: f.confidence for f in insolvent_facts.values()}
        scenarios = [base_scenario]
        
        insolvent_count, total, failures = run_monte_carlo(
            base, confidences, scenarios, 1000, 42
        )
        
        probability = Decimal(str(insolvent_count)) / Decimal(str(total))
        assert probability > Decimal("0.50")  # More than 50% insolvent


# =============================================================================
# Probability Interval Tests
# =============================================================================


class TestProbabilityInterval:
    """Test probability interval computation."""
    
    def test_probability_interval_bounds(self) -> None:
        """Probability interval respects bounds."""
        interval = compute_probability_interval(100, 1000, Decimal("0.90"))
        
        assert interval.p_low >= Decimal("0")
        assert interval.p_high <= Decimal("1")
        assert interval.p_low <= interval.p_mid <= interval.p_high
    
    def test_probability_mid_equals_raw(self) -> None:
        """p_mid equals raw survival probability (not insolvency rate)."""
        interval = compute_probability_interval(200, 1000, Decimal("0.95"))
        
        # Note: compute_probability_interval returns SURVIVAL probability
        # p_mid = (total - insolvent) / total = (1000 - 200) / 1000 = 0.8
        expected_mid = Decimal("0.8")  # Survival, not insolvency
        assert interval.p_mid == expected_mid.quantize(Decimal("0.0001"))
    
    def test_uncertainty_increases_with_low_confidence(self) -> None:
        """Lower confidence leads to wider interval through model uncertainty."""
        high_conf = compute_probability_interval(100, 1000, Decimal("0.95"))
        low_conf = compute_probability_interval(100, 1000, Decimal("0.70"))
        
        # Model uncertainty should be higher for lower confidence
        assert low_conf.model_uncertainty >= high_conf.model_uncertainty
    
    def test_uncertainty_decreases_with_more_samples(self) -> None:
        """More samples lead to narrower interval."""
        few_samples = compute_probability_interval(10, 100, Decimal("0.90"))
        many_samples = compute_probability_interval(1000, 10000, Decimal("0.90"))
        
        few_width = few_samples.p_high - few_samples.p_low
        many_width = many_samples.p_high - many_samples.p_low
        
        assert many_width < few_width


# =============================================================================
# Sensitivity Analysis Tests
# =============================================================================


class TestSensitivityAnalysis:
    """Test sensitivity analysis."""
    
    def test_sensitivity_identifies_drivers(
        self,
        solvent_facts: dict[str, FactCandidate],
        base_scenario: Scenario,
    ) -> None:
        """Sensitivity analysis identifies key drivers."""
        base = {f.fact_type: f.value for f in solvent_facts.values()}
        confidences = {f.fact_type: f.confidence for f in solvent_facts.values()}
        scenarios = [base_scenario]
        
        analysis = compute_sensitivity(
            base, confidences, scenarios, Decimal("0.10"), 100, 42
        )
        
        # Analysis should complete without error
        assert analysis is not None
    
    def test_sensitivity_deterministic(
        self,
        solvent_facts: dict[str, FactCandidate],
        base_scenario: Scenario,
    ) -> None:
        """Sensitivity analysis is deterministic."""
        base = {f.fact_type: f.value for f in solvent_facts.values()}
        confidences = {f.fact_type: f.confidence for f in solvent_facts.values()}
        scenarios = [base_scenario]
        
        analysis1 = compute_sensitivity(base, confidences, scenarios, Decimal("0.10"), 100, 42)
        analysis2 = compute_sensitivity(base, confidences, scenarios, Decimal("0.10"), 100, 42)
        
        assert analysis1.fragility_score == analysis2.fragility_score


# =============================================================================
# REST API Tests
# =============================================================================


class TestRestAPI:
    """Test REST API endpoints."""
    
    def test_health_check(self, test_client: TestClient) -> None:
        """Health check endpoint returns OK."""
        response = test_client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "reasoning-engine"
    
    def test_get_result_not_found(
        self,
        test_client: TestClient,
    ) -> None:
        """Get result returns 404 for unknown ID."""
        response = test_client.get("/v1/reasoning/result/nonexistent_id")
        
        assert response.status_code == 404
    
    def test_get_metrics_not_found(
        self,
        test_client: TestClient,
    ) -> None:
        """Get metrics returns 404 for unknown ID."""
        response = test_client.get("/v1/reasoning/metrics/nonexistent_id")
        
        assert response.status_code == 404


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Test module constants are properly defined."""
    
    def test_engine_version_format(self) -> None:
        """Engine version follows semver."""
        parts = ENGINE_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)
    
    def test_default_sample_count(self) -> None:
        """Default sample count is reasonable."""
        assert DEFAULT_SAMPLE_COUNT >= 1000
        assert DEFAULT_SAMPLE_COUNT <= 100000
    
    def test_required_facts_not_empty(self) -> None:
        """Required facts list is not empty."""
        assert len(REQUIRED_SOLVENCY_FACTS) > 0
    
    def test_thresholds_positive(self) -> None:
        """Thresholds are positive values."""
        assert LIQUIDITY_THRESHOLD > 0
        assert INTEREST_COVERAGE_THRESHOLD > 0
        assert DEBT_SERVICE_THRESHOLD > 0
        assert CASH_RUNWAY_MONTHS_THRESHOLD > 0
    
    def test_confidence_uncertainty_mapping(self) -> None:
        """Confidence mapping is complete."""
        assert "1.00" in CONFIDENCE_TO_UNCERTAINTY
        assert "0.90" in CONFIDENCE_TO_UNCERTAINTY
        assert "0.70" in CONFIDENCE_TO_UNCERTAINTY
        
        # Higher confidence = lower uncertainty
        assert CONFIDENCE_TO_UNCERTAINTY["1.00"] < CONFIDENCE_TO_UNCERTAINTY["0.70"]
