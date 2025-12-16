"""
Claim Processor - Production-Grade Claim Analysis
===================================================

Implements the core claim processing logic:
1. Entity resolution and normalization (CIK/LEI/ticker rules)
2. Jurisdiction confirmation
3. Time-horizon interpretation
4. Scenario structure validation
5. Required-facts contract derivation
6. Semantic refusal detection

Design Principles:
- All operations are deterministic and side-effect-free
- Semantic refusals are first-class outputs, not exceptions
- Required facts form a closed set contract for downstream services
- Processing is fully reproducible given the same input
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from typing import Any, Optional

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import hash_content, deterministic_hash

from .schemas import (
    # Constants
    MIN_MEANINGFUL_HORIZON_MONTHS,
    REPORTING_GRANULARITY_MIN_HORIZON,
    ENTITIES_WITH_SOLVENCY_SEMANTICS,
    ENTITIES_WITHOUT_SOLVENCY_SEMANTICS,
    SUPPORTED_SHOCKS_BY_ENTITY,
    ENTITY_ID_RULES,
    JURISDICTION_FILING_REQUIREMENTS,
    # Enums
    ClaimType,
    SemanticRefusalCode,
    FactCategory,
    FactPriority,
    EntityResolutionStatus,
    # Models
    ResolvedEntityIdentifier,
    NormalizedHorizon,
    ValidatedScenario,
    RequiredFact,
    RequiredFactsContract,
    SemanticRefusal,
    SemanticValidationResult,
    CanonicalSolvencyClaim,
    ClaimProcessingResult,
)


# =============================================================================
# Required Facts Definitions
# =============================================================================

# Core solvency facts required for all entity types
CORE_SOLVENCY_FACTS: list[dict[str, Any]] = [
    {
        "fact_name": "total_assets",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.REQUIRED,
        "description": "Total assets as reported on balance sheet",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "total_liabilities",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.REQUIRED,
        "description": "Total liabilities as reported on balance sheet",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "total_equity",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.REQUIRED,
        "description": "Total shareholders' equity",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "cash_and_equivalents",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.REQUIRED,
        "description": "Cash and cash equivalents",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "total_debt",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.REQUIRED,
        "description": "Total interest-bearing debt",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "current_assets",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.REQUIRED,
        "description": "Current assets (due within 1 year)",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "current_liabilities",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.REQUIRED,
        "description": "Current liabilities (due within 1 year)",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
]

# Income statement facts for cash flow analysis
INCOME_STATEMENT_FACTS: list[dict[str, Any]] = [
    {
        "fact_name": "operating_income",
        "category": FactCategory.INCOME_STATEMENT,
        "priority": FactPriority.REQUIRED,
        "description": "Operating income (EBIT)",
        "period_type": "period",
        "period_months": 12,
        "expected_unit": "currency",
    },
    {
        "fact_name": "interest_expense",
        "category": FactCategory.INCOME_STATEMENT,
        "priority": FactPriority.REQUIRED,
        "description": "Interest expense on debt",
        "period_type": "period",
        "period_months": 12,
        "expected_unit": "currency",
    },
    {
        "fact_name": "net_income",
        "category": FactCategory.INCOME_STATEMENT,
        "priority": FactPriority.MATERIAL,
        "description": "Net income attributable to shareholders",
        "period_type": "period",
        "period_months": 12,
        "expected_unit": "currency",
    },
    {
        "fact_name": "revenue",
        "category": FactCategory.INCOME_STATEMENT,
        "priority": FactPriority.MATERIAL,
        "description": "Total revenue",
        "period_type": "period",
        "period_months": 12,
        "expected_unit": "currency",
    },
]

# Cash flow facts
CASH_FLOW_FACTS: list[dict[str, Any]] = [
    {
        "fact_name": "operating_cash_flow",
        "category": FactCategory.CASH_FLOW,
        "priority": FactPriority.REQUIRED,
        "description": "Cash flow from operating activities",
        "period_type": "period",
        "period_months": 12,
        "expected_unit": "currency",
    },
    {
        "fact_name": "capital_expenditures",
        "category": FactCategory.CASH_FLOW,
        "priority": FactPriority.MATERIAL,
        "description": "Capital expenditures",
        "period_type": "period",
        "period_months": 12,
        "expected_unit": "currency",
    },
    {
        "fact_name": "free_cash_flow",
        "category": FactCategory.CASH_FLOW,
        "priority": FactPriority.MATERIAL,
        "description": "Free cash flow (OCF - CapEx)",
        "period_type": "period",
        "period_months": 12,
        "expected_unit": "currency",
        "derivation_rule": "operating_cash_flow - capital_expenditures",
        "components": ["operating_cash_flow", "capital_expenditures"],
    },
]

# Debt schedule facts (for horizons > 12 months)
DEBT_SCHEDULE_FACTS: list[dict[str, Any]] = [
    {
        "fact_name": "debt_maturity_schedule",
        "category": FactCategory.DEBT_SCHEDULE,
        "priority": FactPriority.REQUIRED,
        "description": "Schedule of debt maturities by year",
        "period_type": "point_in_time",
        "expected_unit": "schedule",
    },
    {
        "fact_name": "debt_by_type",
        "category": FactCategory.DEBT_SCHEDULE,
        "priority": FactPriority.MATERIAL,
        "description": "Debt breakdown by type (term loans, bonds, etc.)",
        "period_type": "point_in_time",
        "expected_unit": "schedule",
    },
    {
        "fact_name": "weighted_average_interest_rate",
        "category": FactCategory.DEBT_SCHEDULE,
        "priority": FactPriority.MATERIAL,
        "description": "Weighted average interest rate on debt",
        "period_type": "point_in_time",
        "expected_unit": "percent",
    },
]

# Bank-specific regulatory capital facts
BANK_REGULATORY_FACTS: list[dict[str, Any]] = [
    {
        "fact_name": "tier1_capital",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Tier 1 regulatory capital",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "tier2_capital",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Tier 2 regulatory capital",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "risk_weighted_assets",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Total risk-weighted assets",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "cet1_ratio",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Common Equity Tier 1 ratio",
        "period_type": "point_in_time",
        "expected_unit": "ratio",
        "derivation_rule": "cet1_capital / risk_weighted_assets",
    },
    {
        "fact_name": "liquidity_coverage_ratio",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Liquidity Coverage Ratio (LCR)",
        "period_type": "point_in_time",
        "expected_unit": "ratio",
    },
]

# Insurance-specific facts
INSURANCE_REGULATORY_FACTS: list[dict[str, Any]] = [
    {
        "fact_name": "solvency_capital_requirement",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Solvency Capital Requirement (SCR)",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "minimum_capital_requirement",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Minimum Capital Requirement (MCR)",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "own_funds",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Eligible own funds",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "solvency_ratio",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Solvency II ratio (Own Funds / SCR)",
        "period_type": "point_in_time",
        "expected_unit": "ratio",
        "derivation_rule": "own_funds / solvency_capital_requirement",
    },
    {
        "fact_name": "technical_provisions",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.REQUIRED,
        "description": "Technical provisions (insurance liabilities)",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
]

# Broker-dealer specific facts
BROKER_DEALER_FACTS: list[dict[str, Any]] = [
    {
        "fact_name": "net_capital",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Net capital under SEC Rule 15c3-1",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "minimum_net_capital_requirement",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Minimum net capital requirement",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "aggregate_indebtedness",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.REQUIRED,
        "description": "Aggregate indebtedness",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
    {
        "fact_name": "customer_reserve_requirement",
        "category": FactCategory.REGULATORY_CAPITAL,
        "priority": FactPriority.REQUIRED,
        "description": "Customer reserve requirement",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
]

# Covenant facts (when covenants are likely)
COVENANT_FACTS: list[dict[str, Any]] = [
    {
        "fact_name": "debt_covenants",
        "category": FactCategory.COVENANT,
        "priority": FactPriority.MATERIAL,
        "description": "List of financial covenants and current status",
        "period_type": "point_in_time",
        "expected_unit": "schedule",
    },
    {
        "fact_name": "covenant_headroom",
        "category": FactCategory.COVENANT,
        "priority": FactPriority.MATERIAL,
        "description": "Headroom to covenant thresholds",
        "period_type": "point_in_time",
        "expected_unit": "schedule",
    },
]

# Scenario-specific facts
INTEREST_RATE_SCENARIO_FACTS: list[dict[str, Any]] = [
    {
        "fact_name": "interest_rate_sensitivity",
        "category": FactCategory.DERIVATIVE,
        "priority": FactPriority.MATERIAL,
        "description": "Sensitivity of net interest income to rate changes",
        "period_type": "point_in_time",
        "expected_unit": "currency_per_bp",
    },
    {
        "fact_name": "duration_gap",
        "category": FactCategory.DERIVATIVE,
        "priority": FactPriority.MATERIAL,
        "description": "Duration gap between assets and liabilities",
        "period_type": "point_in_time",
        "expected_unit": "years",
    },
    {
        "fact_name": "fixed_vs_floating_debt_mix",
        "category": FactCategory.DEBT_SCHEDULE,
        "priority": FactPriority.MATERIAL,
        "description": "Proportion of fixed vs floating rate debt",
        "period_type": "point_in_time",
        "expected_unit": "ratio",
    },
]

FX_SCENARIO_FACTS: list[dict[str, Any]] = [
    {
        "fact_name": "foreign_currency_exposure",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.MATERIAL,
        "description": "Net foreign currency exposure by currency",
        "period_type": "point_in_time",
        "expected_unit": "schedule",
    },
    {
        "fact_name": "fx_hedging_positions",
        "category": FactCategory.DERIVATIVE,
        "priority": FactPriority.SUPPLEMENTARY,
        "description": "FX hedging derivative positions",
        "period_type": "point_in_time",
        "expected_unit": "schedule",
    },
]

CREDIT_SCENARIO_FACTS: list[dict[str, Any]] = [
    {
        "fact_name": "credit_exposure_by_rating",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.MATERIAL,
        "description": "Credit exposure breakdown by counterparty rating",
        "period_type": "point_in_time",
        "expected_unit": "schedule",
    },
    {
        "fact_name": "allowance_for_credit_losses",
        "category": FactCategory.BALANCE_SHEET,
        "priority": FactPriority.MATERIAL,
        "description": "Allowance for credit losses (loan loss reserve)",
        "period_type": "point_in_time",
        "expected_unit": "currency",
    },
]


# =============================================================================
# Claim Processor
# =============================================================================


class ClaimProcessor:
    """
    Production-grade claim processor.
    
    Performs semantic analysis and validation of solvency claims, then
    derives the complete required-facts contract for downstream services.
    
    All operations are:
    - Deterministic: same input always produces same output
    - Side-effect-free: no database writes, no external calls
    - Traceable: all decisions are logged in the result
    """
    
    def __init__(self) -> None:
        """Initialize the claim processor."""
        # No state - processor is stateless
        pass
    
    def process(
        self,
        api_request: dict[str, Any],
        request_hash: str,
        trace_id: str,
    ) -> ClaimProcessingResult:
        """
        Process a solvency evaluation request into a canonical claim.
        
        Args:
            api_request: The validated SolvencyEvaluationRequest as dict
            request_hash: Hash of the API request (for idempotency)
            trace_id: Trace ID for correlation
            
        Returns:
            ClaimProcessingResult with either:
            - Canonical claim + required facts contract (success)
            - Semantic refusals (failure)
        """
        start_time = datetime.now(timezone.utc)
        warnings: list[str] = []
        
        # Step 1: Validate claim type (only SOLVENCY supported)
        claim_type_result = self._validate_claim_type(api_request)
        if not claim_type_result.is_valid:
            return self._create_failure_result(
                claim_type_result.refusals,
                warnings,
                start_time,
                trace_id,
            )
        
        # Step 2: Validate entity has solvency semantics
        entity_classification = api_request.get("entity_classification", "")
        entity_result = self._validate_entity_semantics(entity_classification)
        if not entity_result.is_valid:
            return self._create_failure_result(
                entity_result.refusals,
                entity_result.warnings,
                start_time,
                trace_id,
            )
        warnings.extend(entity_result.warnings)
        
        # Step 3: Resolve and normalize entity identifier
        entity_data = api_request.get("entity", {})
        resolved_entity, entity_warnings = self._resolve_entity(
            entity_data, trace_id
        )
        warnings.extend(entity_warnings)
        
        if resolved_entity.resolution_status == EntityResolutionStatus.INVALID:
            return self._create_failure_result(
                [SemanticRefusal(
                    code=SemanticRefusalCode.ENTITY_ID_INVALID_FORMAT,
                    message=f"Entity ID format is invalid: {resolved_entity.resolution_notes}",
                    field_path="entity.external_id",
                    details={"id_type": entity_data.get("id_type")},
                    suggestion=None,
                )],
                warnings,
                start_time,
                trace_id,
            )
        
        # Step 4: Validate and normalize horizon
        horizon_data = api_request.get("analysis_horizon", {})
        horizon_result = self._validate_and_normalize_horizon(
            horizon_data, entity_classification
        )
        if not horizon_result["is_valid"]:
            return self._create_failure_result(
                horizon_result["refusals"],
                warnings,
                start_time,
                trace_id,
            )
        normalized_horizon = horizon_result["horizon"]
        warnings.extend(horizon_result.get("warnings", []))
        
        # Step 5: Validate scenarios against entity type
        scenarios_data = api_request.get("stress_scenarios", [])
        validated_scenarios, scenario_warnings, scenario_refusals = self._validate_scenarios(
            scenarios_data,
            entity_classification,
            normalized_horizon.months,
            trace_id,
        )
        warnings.extend(scenario_warnings)
        
        if scenario_refusals:
            return self._create_failure_result(
                scenario_refusals,
                warnings,
                start_time,
                trace_id,
            )
        
        # Step 6: Create baseline scenario
        baseline_scenario = self._create_baseline_scenario(trace_id)
        
        # Step 7: Derive required facts contract
        required_facts_contract = self._derive_required_facts(
            entity_classification=entity_classification,
            regulatory_framework=api_request.get("regulatory_framework", ""),
            horizon=normalized_horizon,
            scenarios=[baseline_scenario] + validated_scenarios,
            jurisdiction=api_request.get("jurisdiction", ""),
            trace_id=trace_id,
        )
        
        # Step 8: Build canonical claim
        claim_id = str(generate_canonical_id(EntityType.CLAIM))
        
        # Build thresholds dict
        thresholds_data = api_request.get("thresholds", {})
        thresholds = {}
        if thresholds_data.get("minimum_capital_ratio") is not None:
            thresholds["minimum_capital_ratio"] = Decimal(str(thresholds_data["minimum_capital_ratio"]))
        if thresholds_data.get("target_capital_ratio") is not None:
            thresholds["target_capital_ratio"] = Decimal(str(thresholds_data["target_capital_ratio"]))
        if thresholds_data.get("liquidity_coverage_ratio") is not None:
            thresholds["liquidity_coverage_ratio"] = Decimal(str(thresholds_data["liquidity_coverage_ratio"]))
        if thresholds_data.get("confidence_threshold") is not None:
            thresholds["confidence_threshold"] = Decimal(str(thresholds_data["confidence_threshold"]))
        
        # Evidence policy
        evidence_policy = api_request.get("evidence_policy", {})
        
        # Compute claim hash
        claim_hash = self._compute_claim_hash(
            claim_id=claim_id,
            entity=resolved_entity,
            entity_classification=entity_classification,
            jurisdiction=api_request.get("jurisdiction", ""),
            regulatory_framework=api_request.get("regulatory_framework", ""),
            horizon=normalized_horizon,
            scenarios=[baseline_scenario] + validated_scenarios,
            thresholds=thresholds,
        )
        
        canonical_claim = CanonicalSolvencyClaim(
            claim_id=claim_id,
            claim_type=ClaimType.SOLVENCY,
            version=1,
            entity=resolved_entity,
            entity_classification=entity_classification,
            jurisdiction=api_request.get("jurisdiction", "").upper(),
            regulatory_framework=api_request.get("regulatory_framework", ""),
            analysis_horizon=normalized_horizon,
            baseline_scenario=baseline_scenario,
            stress_scenarios=validated_scenarios,
            reporting_currency=api_request.get("reporting_currency", "").upper(),
            thresholds=thresholds,
            require_audited_statements=evidence_policy.get("require_audited_statements", True),
            max_statement_age_days=evidence_policy.get("max_statement_age_days", 365),
            claim_hash=claim_hash,
            source_request_hash=request_hash,
            trace_id=trace_id,
            processing_warnings=warnings,
        )
        
        # Calculate processing time
        end_time = datetime.now(timezone.utc)
        processing_time_ms = int((end_time - start_time).total_seconds() * 1000)
        
        return ClaimProcessingResult(
            success=True,
            canonical_claim=canonical_claim,
            required_facts_contract=required_facts_contract,
            warnings=warnings,
            processing_time_ms=processing_time_ms,
            trace_id=trace_id,
        )
    
    def _validate_claim_type(self, api_request: dict[str, Any]) -> SemanticValidationResult:
        """Validate that we can process this claim type."""
        # For A3, we only process solvency claims
        # The API Gateway should only send solvency requests, but we validate anyway
        result = SemanticValidationResult(is_valid=True, refusals=[], warnings=[])
        
        # Check if this looks like a solvency request
        required_fields = ["entity", "analysis_horizon", "regulatory_framework"]
        missing = [f for f in required_fields if f not in api_request or not api_request[f]]
        
        if missing:
            return result.add_refusal(
                code=SemanticRefusalCode.CLAIM_UNDERSPECIFIED,
                message=f"Claim is underspecified. Missing required fields: {missing}",
                details={"missing_fields": missing},
                suggestion="Ensure all required fields are provided",
            )
        
        return result
    
    def _validate_entity_semantics(self, entity_classification: str) -> SemanticValidationResult:
        """Validate that the entity type has solvency semantics."""
        result = SemanticValidationResult(is_valid=True, refusals=[], warnings=[])
        
        classification_lower = entity_classification.lower()
        
        if classification_lower in ENTITIES_WITHOUT_SOLVENCY_SEMANTICS:
            reasons = {
                "sovereign": "Sovereign entities can print their own currency; traditional solvency metrics do not apply",
                "municipal": "Municipal solvency depends on complex jurisdictional factors not modeled in A3",
                "spv": "SPV solvency depends on underlying asset structure requiring specialized analysis",
            }
            return result.add_refusal(
                code=SemanticRefusalCode.ENTITY_TYPE_NO_SOLVENCY_SEMANTICS,
                message=f"Entity type '{entity_classification}' does not have standard solvency semantics",
                field_path="entity_classification",
                details={
                    "entity_classification": entity_classification,
                    "reason": reasons.get(classification_lower, "Not supported"),
                },
                suggestion="Use a supported entity classification: " + 
                          ", ".join(sorted(ENTITIES_WITH_SOLVENCY_SEMANTICS)),
            )
        
        if classification_lower not in ENTITIES_WITH_SOLVENCY_SEMANTICS:
            return result.add_refusal(
                code=SemanticRefusalCode.ENTITY_TYPE_NO_SOLVENCY_SEMANTICS,
                message=f"Unknown entity classification: {entity_classification}",
                field_path="entity_classification",
                suggestion="Use a supported entity classification: " +
                          ", ".join(sorted(ENTITIES_WITH_SOLVENCY_SEMANTICS)),
            )
        
        return result
    
    def _resolve_entity(
        self,
        entity_data: dict[str, Any],
        trace_id: str,
    ) -> tuple[ResolvedEntityIdentifier, list[str]]:
        """
        Resolve and normalize entity identifier.
        
        Applies ID-type-specific validation rules (LEI length, CIK padding, etc.)
        """
        warnings: list[str] = []
        
        external_id = str(entity_data.get("external_id", "")).strip().upper()
        id_type = str(entity_data.get("id_type", "")).strip().upper()
        name = str(entity_data.get("name", "")).strip()
        # Normalize whitespace in name
        name = " ".join(name.split())
        
        resolution_notes: list[str] = []
        resolution_status = EntityResolutionStatus.NORMALIZED
        alternative_ids: dict[str, str] = {}
        
        # Apply ID-type-specific rules
        rules = ENTITY_ID_RULES.get(id_type, ENTITY_ID_RULES["INTERNAL"])
        
        if id_type == "LEI":
            if len(external_id) != 20:
                resolution_status = EntityResolutionStatus.INVALID
                resolution_notes.append(f"LEI must be exactly 20 characters, got {len(external_id)}")
            elif not re.match(r"^[A-Z0-9]{20}$", external_id):
                resolution_status = EntityResolutionStatus.INVALID
                resolution_notes.append("LEI must contain only uppercase letters and digits")
        
        elif id_type == "CIK":
            # CIK should be 10 digits, left-padded with zeros
            digits_only = re.sub(r"[^0-9]", "", external_id)
            if len(digits_only) > 10:
                resolution_status = EntityResolutionStatus.INVALID
                resolution_notes.append(f"CIK cannot exceed 10 digits, got {len(digits_only)}")
            else:
                # Normalize: pad to 10 digits
                normalized_cik = digits_only.zfill(10)
                if normalized_cik != external_id:
                    warnings.append(f"CIK normalized from '{external_id}' to '{normalized_cik}'")
                    external_id = normalized_cik
                resolution_notes.append("CIK normalized to 10-digit format")
        
        elif id_type == "CUSIP":
            if len(external_id) != 9:
                resolution_status = EntityResolutionStatus.INVALID
                resolution_notes.append(f"CUSIP must be exactly 9 characters, got {len(external_id)}")
        
        elif id_type == "ISIN":
            if len(external_id) != 12:
                resolution_status = EntityResolutionStatus.INVALID
                resolution_notes.append(f"ISIN must be exactly 12 characters, got {len(external_id)}")
            elif not re.match(r"^[A-Z]{2}[A-Z0-9]{10}$", external_id):
                resolution_status = EntityResolutionStatus.INVALID
                resolution_notes.append("ISIN must start with 2-letter country code")
        
        elif id_type == "TICKER":
            # Ticker requires exchange context (not implemented in A3)
            if not entity_data.get("exchange"):
                warnings.append(
                    "Ticker identifier provided without exchange context; "
                    "resolution may be ambiguous"
                )
            if not re.match(r"^[A-Z]{1,10}$", external_id):
                resolution_status = EntityResolutionStatus.INVALID
                resolution_notes.append("Ticker must be 1-10 uppercase letters")
        
        # Generate canonical ID
        canonical_id = str(generate_canonical_id(EntityType.CLAIM))
        
        return (
            ResolvedEntityIdentifier(
                external_id=external_id,
                id_type=id_type,
                canonical_id=canonical_id,
                name=name,
                resolution_status=resolution_status,
                resolution_notes=resolution_notes,
                alternative_ids=alternative_ids,
            ),
            warnings,
        )
    
    def _validate_and_normalize_horizon(
        self,
        horizon_data: dict[str, Any],
        entity_classification: str,
    ) -> dict[str, Any]:
        """Validate horizon against reporting granularity and normalize."""
        refusals: list[SemanticRefusal] = []
        warnings: list[str] = []
        
        months = int(horizon_data.get("months", 12))
        reference_date_raw = horizon_data.get("reference_date")
        
        # Parse reference date
        if isinstance(reference_date_raw, str):
            reference_date = date.fromisoformat(reference_date_raw)
        elif isinstance(reference_date_raw, date):
            reference_date = reference_date_raw
        else:
            reference_date = date.today()
        
        # Determine reporting granularity based on entity type
        # Banks and insurance: typically quarterly
        # Corporates: typically quarterly (US) or semi-annual (EU)
        if entity_classification.lower() in ("bank", "insurance_company", "broker_dealer"):
            reporting_granularity = "quarterly"
        elif entity_classification.lower() in ("pension_fund", "hedge_fund", "asset_manager"):
            reporting_granularity = "quarterly"
        else:
            reporting_granularity = "quarterly"  # Default to quarterly
        
        min_horizon = REPORTING_GRANULARITY_MIN_HORIZON.get(reporting_granularity, 3)
        
        # Check if horizon is below reporting granularity
        if months < min_horizon:
            refusals.append(SemanticRefusal(
                code=SemanticRefusalCode.HORIZON_BELOW_REPORTING_GRANULARITY,
                message=f"Analysis horizon of {months} months is below the minimum "
                       f"reporting granularity of {min_horizon} months for {reporting_granularity} reporting",
                field_path="analysis_horizon.months",
                details={
                    "requested_months": months,
                    "minimum_months": min_horizon,
                    "reporting_granularity": reporting_granularity,
                },
                suggestion=f"Set horizon to at least {min_horizon} months",
            ))
            return {"is_valid": False, "refusals": refusals}
        
        # Check for meaningful analysis threshold
        if months < MIN_MEANINGFUL_HORIZON_MONTHS:
            refusals.append(SemanticRefusal(
                code=SemanticRefusalCode.HORIZON_TOO_SHORT_FOR_MEANINGFUL_ANALYSIS,
                message=f"Horizon of {months} months is too short for meaningful solvency analysis",
                field_path="analysis_horizon.months",
                details={"minimum_meaningful_months": MIN_MEANINGFUL_HORIZON_MONTHS},
                suggestion=f"Set horizon to at least {MIN_MEANINGFUL_HORIZON_MONTHS} months",
            ))
            return {"is_valid": False, "refusals": refusals}
        
        # Compute end date and reporting periods
        end_date = reference_date + relativedelta(months=months)
        
        if reporting_granularity == "quarterly":
            reporting_periods = (months + 2) // 3  # Round up
        elif reporting_granularity == "semi_annual":
            reporting_periods = (months + 5) // 6
        else:
            reporting_periods = (months + 11) // 12
        
        normalized_horizon = NormalizedHorizon(
            months=months,
            reference_date=reference_date,
            end_date=end_date,
            reporting_periods=reporting_periods,
            reporting_granularity=reporting_granularity,
        )
        
        return {
            "is_valid": True,
            "horizon": normalized_horizon,
            "warnings": warnings,
            "refusals": [],
        }
    
    def _validate_scenarios(
        self,
        scenarios_data: list[dict[str, Any]],
        entity_classification: str,
        analysis_horizon_months: int,
        trace_id: str,
    ) -> tuple[list[ValidatedScenario], list[str], list[SemanticRefusal]]:
        """Validate scenarios against entity type and horizon."""
        validated_scenarios: list[ValidatedScenario] = []
        warnings: list[str] = []
        refusals: list[SemanticRefusal] = []
        
        classification_lower = entity_classification.lower()
        supported_shocks = SUPPORTED_SHOCKS_BY_ENTITY.get(
            classification_lower,
            frozenset()  # Empty set if unknown
        )
        
        for idx, scenario in enumerate(scenarios_data):
            scenario_type = scenario.get("scenario_type", "custom")
            scenario_name = scenario.get("name", f"Scenario_{idx + 1}")
            shocks = scenario.get("shocks", [])
            
            validated_shocks: list[dict[str, Any]] = []
            unsupported_removed: list[str] = []
            scenario_refusals: list[SemanticRefusal] = []
            
            for shock in shocks:
                shock_variable = shock.get("variable", "")
                shock_horizon = shock.get("time_horizon_months", 12)
                shock_percent = shock.get("shock_percent", 0)
                
                # Check if shock variable is supported for this entity type
                if shock_variable.lower() not in {s.lower() for s in supported_shocks}:
                    unsupported_removed.append(shock_variable)
                    warnings.append(
                        f"Shock variable '{shock_variable}' is not supported for "
                        f"entity type '{entity_classification}' and was removed from "
                        f"scenario '{scenario_name}'"
                    )
                    continue
                
                # Check if shock horizon exceeds analysis horizon
                if shock_horizon > analysis_horizon_months:
                    refusals.append(SemanticRefusal(
                        code=SemanticRefusalCode.SHOCK_HORIZON_EXCEEDS_ANALYSIS_HORIZON,
                        message=f"Shock horizon of {shock_horizon} months exceeds "
                               f"analysis horizon of {analysis_horizon_months} months",
                        field_path=f"stress_scenarios[{idx}].shocks",
                        details={
                            "scenario_name": scenario_name,
                            "shock_variable": shock_variable,
                            "shock_horizon_months": shock_horizon,
                            "analysis_horizon_months": analysis_horizon_months,
                        },
                        suggestion="Reduce shock horizon to be within analysis horizon",
                    ))
                    continue
                
                # Check for economically meaningless scenarios
                if self._is_shock_economically_meaningless(shock_variable, shock_percent):
                    refusals.append(SemanticRefusal(
                        code=SemanticRefusalCode.SCENARIO_ECONOMICALLY_MEANINGLESS,
                        message=f"Shock of {shock_percent}% to {shock_variable} is economically meaningless",
                        field_path=f"stress_scenarios[{idx}].shocks",
                        details={
                            "shock_variable": shock_variable,
                            "shock_percent": float(shock_percent),
                        },
                        suggestion="Use a shock magnitude of at least 0.01%",
                    ))
                    continue
                
                validated_shocks.append({
                    "variable": shock_variable,
                    "shock_percent": float(shock_percent) if isinstance(shock_percent, Decimal) else shock_percent,
                    "time_horizon_months": shock_horizon,
                })
            
            # After removing unsupported shocks, check if custom scenario has any shocks left
            if scenario_type.lower() == "custom" and len(validated_shocks) == 0:
                if len(shocks) > 0:
                    # Had shocks but all were removed
                    refusals.append(SemanticRefusal(
                        code=SemanticRefusalCode.SHOCK_UNSUPPORTED_FOR_ENTITY_TYPE,
                        message=f"All shocks in scenario '{scenario_name}' are unsupported "
                               f"for entity type '{entity_classification}'",
                        field_path=f"stress_scenarios[{idx}]",
                        details={
                            "entity_classification": entity_classification,
                            "unsupported_shocks": unsupported_removed,
                            "supported_shocks": list(supported_shocks),
                        },
                        suggestion=f"Use supported shocks: {', '.join(sorted(supported_shocks))}",
                    ))
                    continue
            
            # Generate scenario ID
            scenario_id = f"SCN_{trace_id}_{idx + 1}"
            
            validated_scenarios.append(ValidatedScenario(
                scenario_id=scenario_id,
                scenario_type=scenario_type,
                name=scenario_name,
                validated_shocks=validated_shocks,
                unsupported_shocks_removed=unsupported_removed,
                is_valid=True,
            ))
        
        return validated_scenarios, warnings, refusals
    
    def _is_shock_economically_meaningless(
        self,
        shock_variable: str,
        shock_percent: Any,
    ) -> bool:
        """Check if a shock is economically meaningless."""
        percent = float(shock_percent) if not isinstance(shock_percent, float) else shock_percent
        
        # Some variables have direction constraints
        if shock_variable.lower() == "recovery_rate":
            # Recovery rate can't go above 100% or below 0%
            if percent > 100 or percent < -100:
                return True
        
        if shock_variable.lower() == "default_rate":
            # Default rate shock of +500% on a 0.1% base rate = 0.6%, still valid
            # But default rate can't go negative
            pass
        
        # Very tiny shocks are meaningless
        if abs(percent) < 0.01:  # Less than 0.01% shock
            return True
        
        return False
    
    def _create_baseline_scenario(self, trace_id: str) -> ValidatedScenario:
        """Create the baseline (no-shock) scenario."""
        return ValidatedScenario(
            scenario_id=f"SCN_{trace_id}_BASELINE",
            scenario_type="baseline",
            name="Baseline",
            validated_shocks=[],
            unsupported_shocks_removed=[],
            is_valid=True,
        )
    
    def _derive_required_facts(
        self,
        entity_classification: str,
        regulatory_framework: str,
        horizon: NormalizedHorizon,
        scenarios: list[ValidatedScenario],
        jurisdiction: str,
        trace_id: str,
    ) -> RequiredFactsContract:
        """
        Derive the complete set of required facts for this claim.
        
        This is the core contract that downstream services rely on.
        """
        required_facts: list[RequiredFact] = []
        material_facts: list[RequiredFact] = []
        supplementary_facts: list[RequiredFact] = []
        
        classification_lower = entity_classification.lower()
        fact_counter = 0
        
        def add_fact(fact_def: dict[str, Any], applies_to: Optional[list[str]] = None) -> None:
            nonlocal fact_counter
            fact_counter += 1
            
            priority = fact_def.get("priority", FactPriority.SUPPLEMENTARY)
            
            fact = RequiredFact(
                fact_id=f"FACT_{trace_id}_{fact_counter:04d}",
                fact_name=fact_def["fact_name"],
                category=fact_def["category"],
                priority=priority,
                description=fact_def["description"],
                as_of_date=horizon.reference_date,
                period_type=fact_def.get("period_type", "point_in_time"),
                period_months=fact_def.get("period_months"),
                expected_unit=fact_def.get("expected_unit"),
                acceptable_sources=self._get_acceptable_sources(
                    jurisdiction, classification_lower, fact_def["category"]
                ),
                applies_to_scenarios=applies_to or [],
                derivation_rule=fact_def.get("derivation_rule"),
                components=fact_def.get("components", []),
            )
            
            if priority == FactPriority.REQUIRED:
                required_facts.append(fact)
            elif priority == FactPriority.MATERIAL:
                material_facts.append(fact)
            else:
                supplementary_facts.append(fact)
        
        # Add core solvency facts (always required)
        for fact_def in CORE_SOLVENCY_FACTS:
            add_fact(fact_def)
        
        # Add income statement facts
        for fact_def in INCOME_STATEMENT_FACTS:
            add_fact(fact_def)
        
        # Add cash flow facts
        for fact_def in CASH_FLOW_FACTS:
            add_fact(fact_def)
        
        # Add debt schedule facts for longer horizons
        if horizon.months > 12:
            for fact_def in DEBT_SCHEDULE_FACTS:
                add_fact(fact_def)
        
        # Add entity-specific regulatory facts
        if classification_lower == "bank":
            for fact_def in BANK_REGULATORY_FACTS:
                add_fact(fact_def)
        elif classification_lower == "insurance_company":
            for fact_def in INSURANCE_REGULATORY_FACTS:
                add_fact(fact_def)
        elif classification_lower == "broker_dealer":
            for fact_def in BROKER_DEALER_FACTS:
                add_fact(fact_def)
        
        # Add covenant facts for corporates with debt
        if classification_lower == "corporate" and horizon.months > 6:
            for fact_def in COVENANT_FACTS:
                add_fact(fact_def)
        
        # Add scenario-specific facts
        all_shock_variables = set()
        for scenario in scenarios:
            for shock in scenario.validated_shocks:
                all_shock_variables.add(shock.get("variable", "").lower())
        
        if "interest_rate" in all_shock_variables:
            scenario_ids = [s.scenario_id for s in scenarios 
                          if any(sh.get("variable", "").lower() == "interest_rate" 
                                for sh in s.validated_shocks)]
            for fact_def in INTEREST_RATE_SCENARIO_FACTS:
                add_fact(fact_def, scenario_ids)
        
        if "fx_rate" in all_shock_variables:
            scenario_ids = [s.scenario_id for s in scenarios 
                          if any(sh.get("variable", "").lower() == "fx_rate" 
                                for sh in s.validated_shocks)]
            for fact_def in FX_SCENARIO_FACTS:
                add_fact(fact_def, scenario_ids)
        
        if "credit_spread" in all_shock_variables or "default_rate" in all_shock_variables:
            scenario_ids = [s.scenario_id for s in scenarios 
                          if any(sh.get("variable", "").lower() in ("credit_spread", "default_rate")
                                for sh in s.validated_shocks)]
            for fact_def in CREDIT_SCENARIO_FACTS:
                add_fact(fact_def, scenario_ids)
        
        # Collect all categories
        all_facts = required_facts + material_facts + supplementary_facts
        categories_covered = list(set(f.category for f in all_facts))
        
        # Compute contract hash for determinism verification
        contract_hash = self._compute_contract_hash(
            required_facts, material_facts, supplementary_facts
        )
        
        contract_id = f"RFC_{trace_id}"
        claim_id = f"CLM_{trace_id}"  # Will be updated after claim creation
        
        return RequiredFactsContract(
            contract_id=contract_id,
            claim_id=claim_id,
            version=1,
            required_facts=required_facts,
            material_facts=material_facts,
            supplementary_facts=supplementary_facts,
            total_facts=len(all_facts),
            categories_covered=categories_covered,
            contract_hash=contract_hash,
        )
    
    def _get_acceptable_sources(
        self,
        jurisdiction: str,
        entity_classification: str,
        category: FactCategory,
    ) -> list[str]:
        """Get acceptable evidence sources for a fact."""
        jurisdiction_upper = jurisdiction.upper()
        
        # Get jurisdiction-specific filing requirements
        filings = JURISDICTION_FILING_REQUIREMENTS.get(
            jurisdiction_upper,
            JURISDICTION_FILING_REQUIREMENTS["_default"]
        )
        
        entity_filings = filings.get(
            entity_classification,
            filings.get("corporate", ["Annual Report"])
        )
        
        # Add category-specific sources
        sources = list(entity_filings)
        
        if category == FactCategory.REGULATORY_CAPITAL:
            if entity_classification == "bank":
                sources.extend(["Pillar 3 Disclosure", "Call Report"])
            elif entity_classification == "insurance_company":
                sources.extend(["SFCR", "Statutory Filing"])
        
        return sources
    
    def _compute_claim_hash(
        self,
        claim_id: str,
        entity: ResolvedEntityIdentifier,
        entity_classification: str,
        jurisdiction: str,
        regulatory_framework: str,
        horizon: NormalizedHorizon,
        scenarios: list[ValidatedScenario],
        thresholds: dict[str, Decimal],
    ) -> str:
        """Compute deterministic hash of the canonical claim."""
        # Build deterministic representation
        claim_data = {
            "entity_id": entity.external_id,
            "entity_id_type": entity.id_type,
            "entity_name": entity.name,
            "entity_classification": entity_classification,
            "jurisdiction": jurisdiction,
            "regulatory_framework": regulatory_framework,
            "horizon_months": horizon.months,
            "horizon_reference_date": horizon.reference_date.isoformat(),
            "scenarios": [
                {
                    "type": s.scenario_type,
                    "name": s.name,
                    "shocks": sorted(s.validated_shocks, key=lambda x: x.get("variable", "")),
                }
                for s in sorted(scenarios, key=lambda x: x.scenario_id)
            ],
            "thresholds": {k: str(v) for k, v in sorted(thresholds.items())},
        }
        
        return str(hash_content(claim_data))
    
    def _compute_contract_hash(
        self,
        required_facts: list[RequiredFact],
        material_facts: list[RequiredFact],
        supplementary_facts: list[RequiredFact],
    ) -> str:
        """Compute deterministic hash of the required facts contract."""
        def fact_to_dict(f: RequiredFact) -> dict:
            return {
                "name": f.fact_name,
                "category": f.category.value,
                "priority": f.priority.value,
            }
        
        contract_data = {
            "required": [fact_to_dict(f) for f in sorted(required_facts, key=lambda x: x.fact_name)],
            "material": [fact_to_dict(f) for f in sorted(material_facts, key=lambda x: x.fact_name)],
            "supplementary": [fact_to_dict(f) for f in sorted(supplementary_facts, key=lambda x: x.fact_name)],
        }
        
        return str(hash_content(contract_data))
    
    def _create_failure_result(
        self,
        refusals: list[SemanticRefusal],
        warnings: list[str],
        start_time: datetime,
        trace_id: str,
    ) -> ClaimProcessingResult:
        """Create a failure result from semantic refusals."""
        end_time = datetime.now(timezone.utc)
        processing_time_ms = int((end_time - start_time).total_seconds() * 1000)
        
        return ClaimProcessingResult(
            success=False,
            canonical_claim=None,
            required_facts_contract=None,
            semantic_refusals=refusals,
            warnings=warnings,
            processing_time_ms=processing_time_ms,
            trace_id=trace_id,
        )
