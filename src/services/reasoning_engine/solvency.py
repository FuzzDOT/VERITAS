"""
Solvency Reasoning Engine - Pure Computation Module
=====================================================

Production-grade deterministic solvency evaluation engine.

CRITICAL: This module is PURE - no I/O, no database access, no side effects.
All functions take immutable inputs and return outputs deterministically.

Key Components:
1. Fact Selection: Deterministic selection from candidate facts
2. Metric Computation: Financial ratios and coverage metrics
3. Scenario Shocks: Deterministic stress application
4. Monte Carlo: Uncertainty quantification with deterministic RNG
5. Failure Modes: Rule-based insolvency detection
6. Sensitivity Analysis: One-at-a-time perturbation ranking

Design Principles:
- Same inputs + same seed => identical outputs
- Refusals are first-class outputs, not exceptions
- Probability is an interval [p_low, p_high]
- No LLM, no probabilistic guessing
"""

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional, Sequence

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import deterministic_hash

from .schemas import (
    # Constants
    ENGINE_VERSION,
    DEFAULT_SAMPLE_COUNT,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MAX_STALENESS_DAYS,
    CONFIDENCE_TO_UNCERTAINTY,
    REQUIRED_SOLVENCY_FACTS,
    MATERIAL_SOLVENCY_FACTS,
    SUPPORTED_SHOCK_TYPES,
    # Enums
    EvaluationStatus,
    SolvencyOutcome,
    RefusalCode,
    FailureMode,
    SensitivityDriver,
    # Models
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


# =============================================================================
# Constants for Computation
# =============================================================================

# Threshold values for failure mode detection
LIQUIDITY_THRESHOLD: Decimal = Decimal("1.0")  # Current ratio < 1 is danger
INTEREST_COVERAGE_THRESHOLD: Decimal = Decimal("1.5")  # ICR < 1.5 is danger
DEBT_SERVICE_THRESHOLD: Decimal = Decimal("1.2")  # DSCR < 1.2 is danger
CASH_RUNWAY_MONTHS_THRESHOLD: int = 6  # Less than 6 months runway is danger

# Perturbation percentage for sensitivity analysis
SENSITIVITY_PERTURBATION_PCT: Decimal = Decimal("10")

# Model uncertainty band (conservative)
MODEL_UNCERTAINTY_BAND: Decimal = Decimal("0.05")


# =============================================================================
# Immutable Input Types
# =============================================================================


@dataclass(frozen=True)
class FactCandidate:
    """A candidate fact for selection."""
    
    fact_id: str
    fact_type: str
    value: Decimal
    currency: Optional[str]
    scale: int
    as_of_date: date
    period_end: Optional[date]
    confidence: Decimal
    evidence_id: str
    evidence_hash: str
    fact_hash: str
    
    def scaled_value(self) -> Decimal:
        """Get value at actual scale."""
        return self.value * (Decimal(10) ** self.scale)


@dataclass(frozen=True)
class ClaimContext:
    """Context from the canonical claim."""
    
    claim_id: str
    claim_hash: str
    entity_id: str
    entity_id_type: str
    entity_classification: str
    reference_date: date
    horizon_months: int
    currency: str


@dataclass(frozen=True)
class EvaluationInput:
    """Complete input for solvency evaluation."""
    
    claim_context: ClaimContext
    fact_candidates: tuple[FactCandidate, ...]
    scenarios: tuple[Scenario, ...]
    policy: FactSelectionPolicy
    sample_count: int
    seed: int
    trace_id: str
    
    def compute_input_hash(self) -> str:
        """Compute deterministic hash of all inputs."""
        components = (
            self.claim_context.claim_hash,
            tuple(f.fact_hash for f in self.fact_candidates),
            tuple(s.scenario_id for s in self.scenarios),
            str(self.policy.min_confidence),
            str(self.policy.max_staleness_days),
            self.sample_count,
            ENGINE_VERSION,
        )
        return deterministic_hash(*components)


# =============================================================================
# Seed Generation
# =============================================================================


def derive_seed(
    claim_hash: str,
    evidence_set_hash: str,
    engine_version: str = ENGINE_VERSION,
) -> int:
    """
    Derive deterministic RNG seed from input hashes.
    
    This ensures reproducibility: same inputs => same seed => same results.
    """
    combined = f"{claim_hash}|{evidence_set_hash}|{engine_version}"
    hash_bytes = hashlib.sha256(combined.encode()).digest()
    # Use first 8 bytes as seed (64-bit integer)
    seed = int.from_bytes(hash_bytes[:8], byteorder="big")
    # Ensure positive and within Python's random range
    return seed % (2**31 - 1)


def compute_evidence_set_hash(facts: Sequence[FactCandidate]) -> str:
    """Compute hash of evidence set from facts."""
    if not facts:
        return hashlib.sha256(b"empty").hexdigest()
    
    # Sort by fact_hash for determinism
    sorted_hashes = tuple(sorted(f.fact_hash for f in facts))
    return deterministic_hash(*sorted_hashes)


# =============================================================================
# Fact Selection
# =============================================================================


def select_facts(
    candidates: Sequence[FactCandidate],
    required_types: frozenset[str],
    reference_date: date,
    policy: FactSelectionPolicy,
) -> tuple[list[SelectedFact], list[MissingFact]]:
    """
    Select facts according to policy with deterministic tie-breaking.
    
    Selection Rules:
    1. Filter by confidence >= min_confidence
    2. Filter by staleness <= max_staleness_days
    3. For each fact_type, choose closest period_end <= reference_date
    4. Break ties by: higher confidence > newer published_at > stable hash order
    
    Returns:
        Tuple of (selected_facts, missing_facts)
    """
    selected: list[SelectedFact] = []
    missing: list[MissingFact] = []
    
    # Group candidates by fact_type
    by_type: dict[str, list[FactCandidate]] = {}
    for fact in candidates:
        if fact.fact_type not in by_type:
            by_type[fact.fact_type] = []
        by_type[fact.fact_type].append(fact)
    
    # Process each required type
    for fact_type in required_types:
        type_candidates = by_type.get(fact_type, [])
        
        if not type_candidates:
            priority = "required" if fact_type in REQUIRED_SOLVENCY_FACTS else "material"
            missing.append(MissingFact(
                fact_type=fact_type,
                priority=priority,
                reason=f"No facts of type '{fact_type}' available",
                impact=_get_fact_impact(fact_type),
            ))
            continue
        
        # Filter by policy
        filtered = _filter_by_policy(
            type_candidates, reference_date, policy
        )
        
        if not filtered:
            priority = "required" if fact_type in REQUIRED_SOLVENCY_FACTS else "material"
            missing.append(MissingFact(
                fact_type=fact_type,
                priority=priority,
                reason=f"All {len(type_candidates)} candidates excluded by policy",
                impact=_get_fact_impact(fact_type),
            ))
            continue
        
        # Select best candidate with deterministic tie-breaking
        best = _select_best_candidate(filtered, reference_date, policy)
        
        selected.append(SelectedFact(
            fact_id=best.fact_id,
            fact_type=best.fact_type,
            value=best.scaled_value(),
            currency=best.currency,
            scale=best.scale,
            as_of_date=best.as_of_date,
            confidence=best.confidence,
            evidence_id=best.evidence_id,
            selection_rank=1,
            candidates_considered=len(filtered),
        ))
    
    return selected, missing


def _filter_by_policy(
    candidates: list[FactCandidate],
    reference_date: date,
    policy: FactSelectionPolicy,
) -> list[FactCandidate]:
    """Filter candidates by confidence and staleness policy."""
    filtered = []
    for fact in candidates:
        # Confidence check
        if fact.confidence < policy.min_confidence:
            continue
        
        # Staleness check
        staleness_days = (reference_date - fact.as_of_date).days
        if staleness_days > policy.max_staleness_days:
            continue
        
        # Must be as-of date <= reference date
        if fact.as_of_date > reference_date:
            continue
        
        filtered.append(fact)
    
    return filtered


def _select_best_candidate(
    candidates: list[FactCandidate],
    reference_date: date,
    policy: FactSelectionPolicy,
) -> FactCandidate:
    """
    Select best candidate with deterministic tie-breaking.
    
    Ranking (in order):
    1. Closest as_of_date to reference_date (within allowed window)
    2. Higher confidence (if prefer_higher_confidence)
    3. Newer as_of_date (if prefer_newer_date)
    4. Stable hash order (deterministic fallback)
    """
    def sort_key(fact: FactCandidate) -> tuple:
        # Days from reference (lower is better, but must be >= 0)
        days_before = (reference_date - fact.as_of_date).days
        
        # Confidence (higher is better, so negate for ascending sort)
        conf_rank = -float(fact.confidence) if policy.prefer_higher_confidence else 0
        
        # Freshness (newer is better, so negate)
        date_rank = -fact.as_of_date.toordinal() if policy.prefer_newer_date else 0
        
        # Hash for stable tie-breaking
        hash_rank = fact.fact_hash
        
        return (days_before, conf_rank, date_rank, hash_rank)
    
    sorted_candidates = sorted(candidates, key=sort_key)
    return sorted_candidates[0]


def _get_fact_impact(fact_type: str) -> str:
    """Get impact description for missing fact."""
    impacts = {
        "total_assets": "Cannot compute leverage or asset-based ratios",
        "total_liabilities": "Cannot compute solvency or leverage ratios",
        "cash_and_equivalents": "Cannot assess liquidity position",
        "total_debt": "Cannot compute debt-related metrics",
        "operating_income": "Cannot compute interest coverage ratio",
        "interest_expense": "Cannot compute interest coverage ratio",
        "operating_cash_flow": "Cannot compute debt service coverage",
        "current_assets": "Cannot compute current ratio",
        "current_liabilities": "Cannot compute current ratio",
    }
    return impacts.get(fact_type, f"May reduce analysis quality for {fact_type}")


# =============================================================================
# Metric Computation
# =============================================================================


def compute_metrics(facts: dict[str, Decimal]) -> ComputedMetrics:
    """
    Compute financial metrics from selected facts.
    
    All computations are deterministic with explicit formulas.
    """
    # Extract values with defaults
    total_assets = facts.get("total_assets")
    total_liabilities = facts.get("total_liabilities")
    total_equity = facts.get("total_equity")
    cash = facts.get("cash_and_equivalents")
    total_debt = facts.get("total_debt")
    current_assets = facts.get("current_assets")
    current_liabilities = facts.get("current_liabilities")
    operating_income = facts.get("operating_income")
    interest_expense = facts.get("interest_expense")
    operating_cash_flow = facts.get("operating_cash_flow")
    capital_expenditures = facts.get("capital_expenditures")
    
    # Compute liquidity metrics
    current_ratio = _safe_divide(current_assets, current_liabilities)
    cash_ratio = _safe_divide(cash, current_liabilities)
    
    # Compute leverage metrics
    debt_to_equity = _safe_divide(total_debt, total_equity)
    debt_to_assets = _safe_divide(total_debt, total_assets)
    
    # Compute coverage metrics
    interest_coverage = _safe_divide(operating_income, interest_expense)
    
    # Compute cash flow metrics
    free_cash_flow = None
    if operating_cash_flow is not None and capital_expenditures is not None:
        free_cash_flow = operating_cash_flow - abs(capital_expenditures)
    
    # Cash burn calculation (simplified)
    cash_burn_months = None
    if cash is not None and operating_cash_flow is not None:
        if operating_cash_flow < 0:
            monthly_burn = abs(operating_cash_flow) / Decimal(12)
            if monthly_burn > 0:
                cash_burn_months = cash / monthly_burn
    
    return ComputedMetrics(
        current_ratio=current_ratio,
        quick_ratio=current_ratio,  # Simplified - same as current for now
        cash_ratio=cash_ratio,
        debt_to_equity=debt_to_equity,
        debt_to_assets=debt_to_assets,
        interest_coverage=interest_coverage,
        debt_service_coverage=None,  # Requires debt service schedule
        free_cash_flow=free_cash_flow,
        cash_burn_months=cash_burn_months,
    )


def _safe_divide(
    numerator: Optional[Decimal],
    denominator: Optional[Decimal],
) -> Optional[Decimal]:
    """Safe division returning None if invalid."""
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return (numerator / denominator).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# =============================================================================
# Scenario Shock Application
# =============================================================================


def apply_scenario_shocks(
    base_facts: dict[str, Decimal],
    scenario: Scenario,
) -> dict[str, Decimal]:
    """
    Apply scenario shocks to base facts deterministically.
    
    Shock Application Rules:
    - interest_rate: Increases interest_expense proportionally
    - credit_spread: Increases interest_expense
    - refinancing_spread: Increases interest_expense on debt
    - revenue_decline: Decreases revenue and operating_income
    - cost_increase: Decreases operating_income
    - asset_impairment: Decreases total_assets and total_equity
    """
    shocked = dict(base_facts)
    
    for shock in scenario.shocks:
        magnitude = Decimal(shock.magnitude_bps) / Decimal(10000)
        if shock.direction == "down":
            magnitude = -magnitude
        
        _apply_single_shock(shocked, shock.shock_type, magnitude)
    
    return shocked


def _apply_single_shock(
    facts: dict[str, Decimal],
    shock_type: str,
    magnitude: Decimal,
) -> None:
    """Apply a single shock in-place."""
    
    if shock_type == "interest_rate":
        # Interest expense increases with rate
        if "interest_expense" in facts and facts["interest_expense"]:
            # Assume 1:1 pass-through for simplicity
            facts["interest_expense"] = facts["interest_expense"] * (1 + magnitude)
    
    elif shock_type == "credit_spread":
        # Similar to interest rate
        if "interest_expense" in facts and facts["interest_expense"]:
            facts["interest_expense"] = facts["interest_expense"] * (1 + magnitude)
    
    elif shock_type == "refinancing_spread":
        # Affects interest expense on refinanced debt
        if "interest_expense" in facts and facts["interest_expense"]:
            # Assume 50% of debt refinances in horizon
            facts["interest_expense"] = facts["interest_expense"] * (1 + magnitude * Decimal("0.5"))
    
    elif shock_type == "revenue_decline":
        # Decreases revenue and operating income
        if "revenue" in facts and facts["revenue"]:
            facts["revenue"] = facts["revenue"] * (1 - abs(magnitude))
        if "operating_income" in facts and facts["operating_income"]:
            # Operating leverage: income drops more than revenue
            facts["operating_income"] = facts["operating_income"] * (1 - abs(magnitude) * Decimal("1.5"))
    
    elif shock_type == "cost_increase":
        # Decreases operating income
        if "operating_income" in facts and facts["operating_income"]:
            facts["operating_income"] = facts["operating_income"] * (1 - abs(magnitude))
    
    elif shock_type == "asset_impairment":
        # Decreases total assets and equity
        if "total_assets" in facts and facts["total_assets"]:
            impairment = facts["total_assets"] * abs(magnitude)
            facts["total_assets"] = facts["total_assets"] - impairment
            if "total_equity" in facts and facts["total_equity"]:
                facts["total_equity"] = facts["total_equity"] - impairment


# =============================================================================
# Failure Mode Detection
# =============================================================================


def detect_failure_modes(
    metrics: ComputedMetrics,
    facts: dict[str, Decimal],
) -> list[tuple[FailureMode, Decimal, Decimal]]:
    """
    Detect triggered failure modes based on metrics and thresholds.
    
    Returns list of (mode, threshold, actual_value) tuples.
    """
    failures: list[tuple[FailureMode, Decimal, Decimal]] = []
    
    # Liquidity shortfall
    if metrics.current_ratio is not None:
        if metrics.current_ratio < LIQUIDITY_THRESHOLD:
            failures.append((
                FailureMode.LIQUIDITY_SHORTFALL,
                LIQUIDITY_THRESHOLD,
                metrics.current_ratio,
            ))
    
    # Interest coverage breach
    if metrics.interest_coverage is not None:
        if metrics.interest_coverage < INTEREST_COVERAGE_THRESHOLD:
            failures.append((
                FailureMode.INTEREST_COVERAGE_BREACH,
                INTEREST_COVERAGE_THRESHOLD,
                metrics.interest_coverage,
            ))
    
    # Debt service failure (if we have DSCR)
    if metrics.debt_service_coverage is not None:
        if metrics.debt_service_coverage < DEBT_SERVICE_THRESHOLD:
            failures.append((
                FailureMode.DEBT_SERVICE_FAILURE,
                DEBT_SERVICE_THRESHOLD,
                metrics.debt_service_coverage,
            ))
    
    # Cash runway stress
    if metrics.cash_burn_months is not None:
        threshold = Decimal(CASH_RUNWAY_MONTHS_THRESHOLD)
        if metrics.cash_burn_months < threshold:
            failures.append((
                FailureMode.MATURITY_REFINANCING_STRESS,
                threshold,
                metrics.cash_burn_months,
            ))
    
    # Negative equity
    total_equity = facts.get("total_equity")
    if total_equity is not None and total_equity <= 0:
        failures.append((
            FailureMode.NEGATIVE_EQUITY,
            Decimal("0"),
            total_equity,
        ))
    
    return failures


def is_insolvent(
    metrics: ComputedMetrics,
    facts: dict[str, Decimal],
) -> bool:
    """
    Determine if entity is insolvent based on failure modes.
    
    An entity is considered insolvent if:
    - Interest coverage < 1.0 (cannot cover interest)
    - Current ratio < 0.5 (severe liquidity crisis)
    - Negative equity
    """
    # Check interest coverage
    if metrics.interest_coverage is not None:
        if metrics.interest_coverage < Decimal("1.0"):
            return True
    
    # Check severe liquidity
    if metrics.current_ratio is not None:
        if metrics.current_ratio < Decimal("0.5"):
            return True
    
    # Check negative equity
    if facts.get("total_equity") is not None:
        if facts["total_equity"] <= 0:
            return True
    
    return False


# =============================================================================
# Monte Carlo Simulation
# =============================================================================


def confidence_to_std_dev(confidence: Decimal) -> Decimal:
    """
    Map confidence score to uncertainty (standard deviation multiplier).
    
    Higher confidence => lower uncertainty => narrower distribution.
    """
    # Find closest confidence level in mapping
    conf_str = str(confidence.quantize(Decimal("0.05"), rounding=ROUND_HALF_UP))
    
    # Interpolate or use closest
    if conf_str in CONFIDENCE_TO_UNCERTAINTY:
        return CONFIDENCE_TO_UNCERTAINTY[conf_str]
    
    # Linear interpolation for values between breakpoints
    conf_float = float(confidence)
    if conf_float >= 0.90:
        return Decimal("0.05")
    elif conf_float >= 0.70:
        return Decimal("0.15")
    elif conf_float >= 0.60:
        return Decimal("0.20")
    else:
        return Decimal("0.40")


def run_monte_carlo(
    base_facts: dict[str, Decimal],
    fact_confidences: dict[str, Decimal],
    scenarios: Sequence[Scenario],
    sample_count: int,
    seed: int,
) -> tuple[int, int, list[TriggeredFailureMode]]:
    """
    Run Monte Carlo simulation with deterministic RNG.
    
    For each sample:
    1. Perturb facts based on confidence (lower conf = wider distribution)
    2. Apply scenario shocks
    3. Compute metrics
    4. Check for insolvency
    
    Returns:
        Tuple of (insolvent_count, total_samples, failure_modes_with_freq)
    """
    rng = random.Random(seed)
    
    insolvent_count = 0
    failure_counts: dict[FailureMode, int] = {}
    failure_values: dict[FailureMode, list[Decimal]] = {}
    
    for _ in range(sample_count):
        # Perturb facts based on confidence
        perturbed = _perturb_facts(base_facts, fact_confidences, rng)
        
        # Find worst scenario (most stressed)
        worst_metrics = None
        worst_facts = None
        
        for scenario in scenarios:
            shocked_facts = apply_scenario_shocks(perturbed, scenario)
            metrics = compute_metrics(shocked_facts)
            
            if worst_metrics is None or _is_worse(metrics, worst_metrics):
                worst_metrics = metrics
                worst_facts = shocked_facts
        
        # If no scenarios, use baseline
        if worst_metrics is None:
            worst_metrics = compute_metrics(perturbed)
            worst_facts = perturbed
        
        # At this point worst_facts is guaranteed to be set
        assert worst_facts is not None
        
        # Check for insolvency
        if is_insolvent(worst_metrics, worst_facts):
            insolvent_count += 1
        
        # Track failure modes
        failures = detect_failure_modes(worst_metrics, worst_facts)
        for mode, threshold, actual in failures:
            if mode not in failure_counts:
                failure_counts[mode] = 0
                failure_values[mode] = []
            failure_counts[mode] += 1
            failure_values[mode].append(actual)
    
    # Convert to TriggeredFailureMode objects
    triggered = []
    for mode, count in sorted(failure_counts.items(), key=lambda x: -x[1]):
        freq = Decimal(count) / Decimal(sample_count)
        
        # Compute contribution to insolvency
        contribution = Decimal(count) / Decimal(max(insolvent_count, 1))
        contribution = min(contribution, Decimal("1.0"))
        
        # Get threshold for this mode
        threshold = _get_threshold_for_mode(mode)
        
        # Median actual value
        values = failure_values[mode]
        median_val = sorted(values)[len(values) // 2] if values else Decimal("0")
        
        triggered.append(TriggeredFailureMode(
            mode=mode,
            trigger_threshold=threshold,
            actual_value=median_val,
            frequency=freq,
            contribution_to_insolvency=contribution,
        ))
    
    return insolvent_count, sample_count, triggered


def _perturb_facts(
    base_facts: dict[str, Decimal],
    confidences: dict[str, Decimal],
    rng: random.Random,
) -> dict[str, Decimal]:
    """Perturb facts based on confidence levels."""
    perturbed = {}
    
    for fact_type, value in base_facts.items():
        confidence = confidences.get(fact_type, Decimal("1.0"))
        std_dev = confidence_to_std_dev(confidence)
        
        if std_dev > 0 and value != 0:
            # Normal perturbation scaled by value and std_dev
            perturbation = Decimal(str(rng.gauss(0, float(std_dev))))
            perturbed[fact_type] = value * (1 + perturbation)
        else:
            perturbed[fact_type] = value
    
    return perturbed


def _is_worse(a: ComputedMetrics, b: ComputedMetrics) -> bool:
    """Compare two metrics, return True if a is worse than b."""
    # Lower interest coverage is worse
    if a.interest_coverage is not None and b.interest_coverage is not None:
        if a.interest_coverage < b.interest_coverage:
            return True
    
    # Lower current ratio is worse
    if a.current_ratio is not None and b.current_ratio is not None:
        if a.current_ratio < b.current_ratio:
            return True
    
    return False


def _get_threshold_for_mode(mode: FailureMode) -> Decimal:
    """Get threshold value for a failure mode."""
    thresholds = {
        FailureMode.LIQUIDITY_SHORTFALL: LIQUIDITY_THRESHOLD,
        FailureMode.INTEREST_COVERAGE_BREACH: INTEREST_COVERAGE_THRESHOLD,
        FailureMode.DEBT_SERVICE_FAILURE: DEBT_SERVICE_THRESHOLD,
        FailureMode.MATURITY_REFINANCING_STRESS: Decimal(CASH_RUNWAY_MONTHS_THRESHOLD),
        FailureMode.NEGATIVE_EQUITY: Decimal("0"),
        FailureMode.COVENANT_BREACH: Decimal("0"),
        FailureMode.REGULATORY_CAPITAL_BREACH: Decimal("0"),
    }
    return thresholds.get(mode, Decimal("0"))


# =============================================================================
# Probability Interval Computation
# =============================================================================


def compute_probability_interval(
    insolvent_count: int,
    total_samples: int,
    fact_avg_confidence: Decimal,
) -> ProbabilityInterval:
    """
    Compute probability interval from Monte Carlo results.
    
    The interval accounts for:
    1. Sampling uncertainty (based on sample count)
    2. Model uncertainty (conservative band)
    """
    if total_samples == 0:
        return ProbabilityInterval(
            p_low=Decimal("0"),
            p_mid=Decimal("0.5"),
            p_high=Decimal("1"),
            sampling_uncertainty=Decimal("0.5"),
            model_uncertainty=MODEL_UNCERTAINTY_BAND,
        )
    
    # Point estimate (probability of insolvency)
    p_insolvency = Decimal(insolvent_count) / Decimal(total_samples)
    
    # Solvency probability is complement
    p_solvency = Decimal("1") - p_insolvency
    
    # Sampling uncertainty (approximation of standard error)
    # SE = sqrt(p(1-p)/n) ≈ 1/(2*sqrt(n)) for worst case
    import math
    se = Decimal(str(1 / (2 * math.sqrt(total_samples))))
    
    # 95% confidence interval: approximately ±2*SE
    sampling_uncertainty = se * Decimal("2")
    
    # Model uncertainty adds conservative buffer
    total_uncertainty = sampling_uncertainty + MODEL_UNCERTAINTY_BAND
    
    # Compute interval with bounds
    p_low = max(Decimal("0"), p_solvency - total_uncertainty)
    p_high = min(Decimal("1"), p_solvency + total_uncertainty)
    
    # Ensure ordering
    p_mid = p_solvency.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    p_low = p_low.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    p_high = p_high.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    
    return ProbabilityInterval(
        p_low=p_low,
        p_mid=p_mid,
        p_high=p_high,
        sampling_uncertainty=sampling_uncertainty.quantize(Decimal("0.0001")),
        model_uncertainty=MODEL_UNCERTAINTY_BAND,
    )


# =============================================================================
# Sensitivity Analysis
# =============================================================================


def compute_sensitivity(
    base_facts: dict[str, Decimal],
    fact_confidences: dict[str, Decimal],
    scenarios: Sequence[Scenario],
    base_p_insolvency: Decimal,
    sample_count: int,
    seed: int,
) -> SensitivityAnalysis:
    """
    Compute sensitivity analysis using one-at-a-time perturbation.
    
    For each input driver, perturb by SENSITIVITY_PERTURBATION_PCT
    and measure change in insolvency probability.
    """
    results: list[dict[str, Any]] = []
    
    # Map fact types to drivers
    fact_to_driver = {
        "cash_and_equivalents": SensitivityDriver.CASH_POSITION,
        "interest_expense": SensitivityDriver.INTEREST_EXPENSE,
        "operating_cash_flow": SensitivityDriver.OPERATING_CASH_FLOW,
        "revenue": SensitivityDriver.REVENUE,
        "total_debt": SensitivityDriver.DEBT_LEVEL,
        "current_assets": SensitivityDriver.CURRENT_RATIO,
        "current_liabilities": SensitivityDriver.CURRENT_RATIO,
    }
    
    for fact_type, driver in fact_to_driver.items():
        if fact_type not in base_facts:
            continue
        
        base_value = base_facts[fact_type]
        if base_value == 0:
            continue
        
        # Perturb by 10% adversely
        perturbed_facts = dict(base_facts)
        perturbation = SENSITIVITY_PERTURBATION_PCT / Decimal(100)
        
        # Adverse perturbation direction depends on fact type
        if fact_type in {"cash_and_equivalents", "operating_cash_flow", "revenue", "current_assets"}:
            # Lower is worse
            perturbed_facts[fact_type] = base_value * (1 - perturbation)
        else:
            # Higher is worse (debt, interest, liabilities)
            perturbed_facts[fact_type] = base_value * (1 + perturbation)
        
        # Run mini Monte Carlo with perturbation
        mini_samples = min(1000, sample_count // 10)
        perturbed_seed = seed + hash(fact_type) % 1000
        
        insol_count, total, _ = run_monte_carlo(
            perturbed_facts,
            fact_confidences,
            scenarios,
            mini_samples,
            perturbed_seed,
        )
        
        p_perturbed = Decimal(insol_count) / Decimal(max(total, 1))
        delta = p_perturbed - base_p_insolvency
        
        # Store intermediate data for ranking later
        results.append({
            "driver": driver,
            "fact_type": fact_type,
            "base_value": base_value,
            "perturbation_pct": SENSITIVITY_PERTURBATION_PCT,
            "p_insolvency_base": base_p_insolvency,
            "p_insolvency_perturbed": p_perturbed,
            "delta_p": delta,
        })
    
    # Rank by absolute delta
    sorted_results = sorted(results, key=lambda r: abs(r["delta_p"]), reverse=True)
    
    # Assign ranks and normalized contributions
    total_delta = sum(abs(r["delta_p"]) for r in sorted_results)
    ranked_results = []
    for i, r in enumerate(sorted_results, 1):
        norm_contrib = abs(r["delta_p"]) / total_delta if total_delta > 0 else Decimal("0")
        ranked_results.append(SensitivityResult(
            driver=r["driver"],
            fact_type=r["fact_type"],
            base_value=r["base_value"],
            perturbation_pct=r["perturbation_pct"],
            p_insolvency_base=r["p_insolvency_base"],
            p_insolvency_perturbed=r["p_insolvency_perturbed"],
            delta_p=r["delta_p"],
            rank=i,
            normalized_contribution=norm_contrib.quantize(Decimal("0.0001")),
        ))
    
    # Compute fragility score (average sensitivity)
    fragility = Decimal("0")
    if ranked_results:
        fragility = sum(abs(r.delta_p) for r in ranked_results) / Decimal(len(ranked_results))
        fragility = min(fragility * Decimal("10"), Decimal("1"))  # Scale to 0-1
    
    return SensitivityAnalysis(
        drivers=ranked_results,
        top_driver=ranked_results[0].driver if ranked_results else None,
        fragility_score=fragility.quantize(Decimal("0.0001")),
        perturbation_method="one_at_a_time",
    )


# =============================================================================
# Main Evaluation Function
# =============================================================================


def evaluate_solvency(
    evaluation_input: EvaluationInput,
) -> tuple[SolvencyEvaluationResult, ReasoningArtifact]:
    """
    Main pure function for solvency evaluation.
    
    This is the core deterministic computation:
    1. Select facts according to policy
    2. Check for required fact coverage
    3. Compute baseline metrics
    4. Run Monte Carlo simulation
    5. Compute probability interval
    6. Analyze sensitivity
    7. Produce result and artifact
    
    CRITICAL: This function is PURE - no side effects.
    """
    start_time = datetime.now(timezone.utc)
    
    ctx = evaluation_input.claim_context
    evaluation_id = str(generate_canonical_id(EntityType.EXTRACTION))
    artifact_id = str(generate_canonical_id(EntityType.EXTRACTION))
    
    # Compute evidence set hash for artifact
    evidence_set_hash = compute_evidence_set_hash(evaluation_input.fact_candidates)
    
    # Step 1: Select facts
    all_required = REQUIRED_SOLVENCY_FACTS | MATERIAL_SOLVENCY_FACTS
    selected_facts, missing_facts = select_facts(
        evaluation_input.fact_candidates,
        all_required,
        ctx.reference_date,
        evaluation_input.policy,
    )
    
    # Step 2: Check required fact coverage
    missing_required = [
        m for m in missing_facts
        if m.fact_type in REQUIRED_SOLVENCY_FACTS
    ]
    
    if missing_required:
        # Create refusal
        refusal = ReasoningRefusal(
            code=RefusalCode.REQUIRED_FACTS_MISSING,
            message=f"Cannot evaluate: {len(missing_required)} required facts missing",
            missing_facts=missing_required,
            excluded_facts=[],
            remediation="Ensure all required facts are extracted from evidence",
            trace_id=evaluation_input.trace_id,
        )
        
        result = _create_refused_result(
            evaluation_id, ctx.claim_id, refusal,
            evaluation_input.seed, evaluation_input.trace_id, start_time,
        )
        
        artifact = _create_artifact(
            artifact_id, evaluation_id, ctx, evidence_set_hash,
            evaluation_input.seed, evaluation_input.sample_count,
            selected_facts, None, [], None, start_time,
        )
        
        return result, artifact
    
    # Step 3: Build fact dictionaries
    fact_values: dict[str, Decimal] = {}
    fact_confidences: dict[str, Decimal] = {}
    
    for sf in selected_facts:
        fact_values[sf.fact_type] = sf.value
        fact_confidences[sf.fact_type] = sf.confidence
    
    # Step 4: Compute baseline metrics
    baseline_metrics = compute_metrics(fact_values)
    
    # Step 5: Run Monte Carlo
    insolvent_count, total_samples, triggered_failures = run_monte_carlo(
        fact_values,
        fact_confidences,
        evaluation_input.scenarios,
        evaluation_input.sample_count,
        evaluation_input.seed,
    )
    
    # Step 6: Compute probability interval
    avg_confidence = sum(fact_confidences.values()) / Decimal(max(len(fact_confidences), 1))
    prob_interval = compute_probability_interval(
        insolvent_count, total_samples, avg_confidence
    )
    
    # Step 7: Determine outcome
    p_insolvency = Decimal(insolvent_count) / Decimal(max(total_samples, 1))
    
    if p_insolvency < Decimal("0.05"):
        outcome = SolvencyOutcome.SOLVENT
    elif p_insolvency < Decimal("0.25"):
        outcome = SolvencyOutcome.DISTRESSED
    elif p_insolvency < Decimal("0.75"):
        outcome = SolvencyOutcome.INDETERMINATE
    else:
        outcome = SolvencyOutcome.INSOLVENT
    
    # Step 8: Sensitivity analysis
    sensitivity = compute_sensitivity(
        fact_values,
        fact_confidences,
        evaluation_input.scenarios,
        p_insolvency,
        evaluation_input.sample_count,
        evaluation_input.seed,
    )
    
    # Create result
    end_time = datetime.now(timezone.utc)
    computation_ms = int((end_time - start_time).total_seconds() * 1000)
    
    output_hash = deterministic_hash(
        evaluation_id,
        outcome.value,
        str(prob_interval.p_mid),
        str(evaluation_input.seed),
        ENGINE_VERSION,
    )
    
    result = SolvencyEvaluationResult(
        evaluation_id=evaluation_id,
        claim_id=ctx.claim_id,
        status=EvaluationStatus.COMPLETED,
        outcome=outcome,
        solvency_probability=prob_interval,
        key_metrics=baseline_metrics,
        triggered_failure_modes=triggered_failures,
        sensitivity_analysis=sensitivity,
        refusal=None,
        facts_used_count=len(selected_facts),
        facts_excluded_count=len(missing_facts),
        artifact_id=artifact_id,
        seed=evaluation_input.seed,
        engine_version=ENGINE_VERSION,
        output_hash=output_hash,
        started_at=start_time,
        completed_at=end_time,
        computation_time_ms=computation_ms,
        trace_id=evaluation_input.trace_id,
    )
    
    # Create artifact
    artifact = _create_artifact(
        artifact_id, evaluation_id, ctx, evidence_set_hash,
        evaluation_input.seed, evaluation_input.sample_count,
        selected_facts, baseline_metrics, triggered_failures,
        sensitivity, start_time, end_time, computation_ms,
    )
    
    return result, artifact


def _create_refused_result(
    evaluation_id: str,
    claim_id: str,
    refusal: ReasoningRefusal,
    seed: int,
    trace_id: str,
    started_at: datetime,
) -> SolvencyEvaluationResult:
    """Create a refused evaluation result."""
    output_hash = deterministic_hash(
        evaluation_id,
        refusal.code.value,
        str(seed),
        ENGINE_VERSION,
    )
    
    return SolvencyEvaluationResult(
        evaluation_id=evaluation_id,
        claim_id=claim_id,
        status=EvaluationStatus.REFUSED,
        outcome=None,
        solvency_probability=None,
        key_metrics=None,
        triggered_failure_modes=[],
        sensitivity_analysis=None,
        refusal=refusal,
        facts_used_count=0,
        facts_excluded_count=0,
        artifact_id=None,
        seed=seed,
        engine_version=ENGINE_VERSION,
        output_hash=output_hash,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        computation_time_ms=0,
        trace_id=trace_id,
    )


def _create_artifact(
    artifact_id: str,
    evaluation_id: str,
    ctx: ClaimContext,
    evidence_set_hash: str,
    seed: int,
    sample_count: int,
    selected_facts: list[SelectedFact],
    baseline_metrics: Optional[ComputedMetrics],
    triggered_failures: list[TriggeredFailureMode],
    sensitivity: Optional[SensitivityAnalysis],
    started_at: datetime,
    completed_at: Optional[datetime] = None,
    computation_time_ms: int = 0,
) -> ReasoningArtifact:
    """Create reasoning artifact."""
    return ReasoningArtifact(
        artifact_id=artifact_id,
        evaluation_id=evaluation_id,
        claim_id=ctx.claim_id,
        claim_hash=ctx.claim_hash,
        fact_ids_used=[f.fact_id for f in selected_facts],
        evidence_set_hash=evidence_set_hash,
        seed=seed,
        engine_version=ENGINE_VERSION,
        sample_count=sample_count,
        selected_facts=selected_facts,
        baseline_metrics=baseline_metrics,
        stressed_metrics=[],  # TODO: Populate if needed
        triggered_failure_modes=triggered_failures,
        sensitivity_analysis=sensitivity,
        started_at=started_at,
        completed_at=completed_at,
        computation_time_ms=computation_time_ms,
    )
