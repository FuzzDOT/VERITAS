"""
API Gateway Validation - Exhaustive Input Validation
======================================================

Implements deterministic validation and normalization of all incoming requests.
Validation failures produce structured refusal responses with precise reasons.

Design Principles:
- All validation is deterministic and reproducible
- Validation errors are accumulated, not short-circuited
- Refusals include actionable information for clients
- Policy enforcement is explicit and auditable
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from pydantic import ValidationError

from shared.canonical_id import generate_canonical_id, EntityType
from shared.hashing import hash_content, deterministic_hash
from shared.errors import (
    ValidationRefusalError,
    PreconditionNotMetError,
    RefusalCategory,
)
from shared.logging import get_logger

from services.api_gateway.schemas import (
    SolvencyEvaluationRequest,
    CanonicalSolvencyRequest,
    SUPPORTED_JURISDICTIONS,
    SUPPORTED_CURRENCIES,
    MIN_HORIZON_MONTHS,
    MAX_HORIZON_MONTHS,
    MIN_SHOCK_PERCENT,
    MAX_SHOCK_PERCENT,
    ScenarioType,
)


logger = get_logger(__name__)


# =============================================================================
# Validation Result Types
# =============================================================================


@dataclass(frozen=True)
class FieldError:
    """A single field-level validation error."""
    
    field: str
    message: str
    value: Any = None
    constraint: Optional[str] = None


@dataclass
class ValidationResult:
    """
    Result of validation, containing all errors and warnings.
    
    Accumulates all validation issues rather than failing fast,
    providing comprehensive feedback to clients.
    """
    
    is_valid: bool = True
    errors: list[FieldError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)
    normalized_request: Optional[SolvencyEvaluationRequest] = None
    
    def add_error(
        self,
        field_name: str,
        message: str,
        value: Any = None,
        constraint: Optional[str] = None,
    ) -> None:
        """Add a validation error."""
        self.errors.append(FieldError(
            field=field_name,
            message=message,
            value=value,
            constraint=constraint,
        ))
        self.is_valid = False
    
    def add_warning(self, message: str) -> None:
        """Add a validation warning (does not fail validation)."""
        self.warnings.append(message)
    
    def add_policy_violation(self, policy: str) -> None:
        """Add a policy violation."""
        self.policy_violations.append(policy)
        self.is_valid = False
    
    def to_error_dict(self) -> dict[str, Any]:
        """Convert to error response dictionary."""
        return {
            "field_errors": [
                {
                    "field": e.field,
                    "message": e.message,
                    "value": str(e.value) if e.value is not None else None,
                    "constraint": e.constraint,
                }
                for e in self.errors
            ],
            "warnings": self.warnings,
            "policy_violations": self.policy_violations,
        }


# =============================================================================
# Request Validator
# =============================================================================


class SolvencyRequestValidator:
    """
    Validates and normalizes solvency evaluation requests.
    
    Performs:
    1. Schema validation (via Pydantic)
    2. Business rule validation
    3. Policy enforcement
    4. Deterministic normalization
    5. Request hash computation
    """
    
    def __init__(self) -> None:
        self._logger = get_logger(__name__)
    
    def validate_and_normalize(
        self,
        raw_data: dict[str, Any],
        trace_id: str,
    ) -> tuple[ValidationResult, Optional[CanonicalSolvencyRequest]]:
        """
        Validate and normalize a raw request into a canonical request.
        
        Args:
            raw_data: Raw JSON request body
            trace_id: Request trace ID
        
        Returns:
            Tuple of (ValidationResult, CanonicalSolvencyRequest or None)
        """
        result = ValidationResult()
        received_at = datetime.now(timezone.utc)
        
        # Phase 1: Pydantic schema validation
        try:
            request = SolvencyEvaluationRequest.model_validate(raw_data)
        except ValidationError as e:
            self._extract_pydantic_errors(e, result)
            self._logger.warning(
                "Schema validation failed",
                trace_id=trace_id,
                error_count=len(result.errors),
            )
            return result, None
        
        # Phase 2: Business rule validation
        self._validate_business_rules(request, result)
        
        # Phase 3: Policy enforcement
        self._enforce_policies(request, result)
        
        if not result.is_valid:
            self._logger.warning(
                "Business validation failed",
                trace_id=trace_id,
                error_count=len(result.errors),
                policy_violations=result.policy_violations,
            )
            return result, None
        
        # Phase 4: Create canonical request
        result.normalized_request = request
        canonical = self._create_canonical_request(request, trace_id, received_at)
        
        self._logger.info(
            "Request validated and normalized",
            trace_id=trace_id,
            claim_id=canonical.claim_id,
            request_hash=canonical.request_hash,
            entity_id=request.entity.external_id,
            jurisdiction=request.jurisdiction,
        )
        
        return result, canonical
    
    def _extract_pydantic_errors(
        self,
        error: ValidationError,
        result: ValidationResult,
    ) -> None:
        """Extract field errors from Pydantic ValidationError."""
        for err in error.errors():
            field_path = ".".join(str(loc) for loc in err["loc"])
            result.add_error(
                field_name=field_path,
                message=err["msg"],
                value=err.get("input"),
                constraint=err.get("type"),
            )
    
    def _validate_business_rules(
        self,
        request: SolvencyEvaluationRequest,
        result: ValidationResult,
    ) -> None:
        """Validate business rules beyond schema constraints."""
        
        # Rule 1: Stress scenario consistency
        self._validate_scenario_consistency(request, result)
        
        # Rule 2: Horizon/scenario alignment
        self._validate_horizon_scenario_alignment(request, result)
        
        # Rule 3: Threshold coherence
        self._validate_threshold_coherence(request, result)
        
        # Rule 4: Entity classification coherence
        self._validate_entity_coherence(request, result)
    
    def _validate_scenario_consistency(
        self,
        request: SolvencyEvaluationRequest,
        result: ValidationResult,
    ) -> None:
        """Validate stress scenario internal consistency."""
        scenario_names = set()
        
        for i, scenario in enumerate(request.stress_scenarios):
            # Check for duplicate scenario names
            if scenario.name.lower() in scenario_names:
                result.add_error(
                    field_name=f"stress_scenarios[{i}].name",
                    message=f"Duplicate scenario name: '{scenario.name}'",
                    value=scenario.name,
                    constraint="unique_scenario_names",
                )
            scenario_names.add(scenario.name.lower())
            
            # Validate shock magnitudes are realistic for the type
            for j, shock in enumerate(scenario.shocks):
                if scenario.scenario_type == ScenarioType.BASELINE:
                    if abs(shock.shock_percent) > Decimal("10"):
                        result.add_warning(
                            f"Baseline scenario '{scenario.name}' has shock "
                            f">{10}% which is unusual for baseline"
                        )
                
                if scenario.scenario_type == ScenarioType.SEVERELY_ADVERSE:
                    if abs(shock.shock_percent) < Decimal("10"):
                        result.add_warning(
                            f"Severely adverse scenario '{scenario.name}' has shock "
                            f"<{10}% which may be too mild"
                        )
    
    def _validate_horizon_scenario_alignment(
        self,
        request: SolvencyEvaluationRequest,
        result: ValidationResult,
    ) -> None:
        """Validate analysis horizon and scenario horizons are aligned."""
        analysis_months = request.analysis_horizon.months
        
        for i, scenario in enumerate(request.stress_scenarios):
            for j, shock in enumerate(scenario.shocks):
                if shock.time_horizon_months > analysis_months:
                    result.add_error(
                        field_name=f"stress_scenarios[{i}].shocks[{j}].time_horizon_months",
                        message=(
                            f"Shock horizon ({shock.time_horizon_months} months) "
                            f"exceeds analysis horizon ({analysis_months} months)"
                        ),
                        value=shock.time_horizon_months,
                        constraint="shock_horizon_within_analysis",
                    )
    
    def _validate_threshold_coherence(
        self,
        request: SolvencyEvaluationRequest,
        result: ValidationResult,
    ) -> None:
        """Validate threshold configuration is coherent."""
        thresholds = request.thresholds
        
        # If both min and target are set, target must be >= min
        # (Already validated in schema, but double-check)
        if (thresholds.minimum_capital_ratio is not None and 
            thresholds.target_capital_ratio is not None):
            if thresholds.target_capital_ratio < thresholds.minimum_capital_ratio:
                result.add_error(
                    field_name="thresholds.target_capital_ratio",
                    message="Target ratio must be >= minimum ratio",
                    value=float(thresholds.target_capital_ratio),
                    constraint="target_gte_minimum",
                )
    
    def _validate_entity_coherence(
        self,
        request: SolvencyEvaluationRequest,
        result: ValidationResult,
    ) -> None:
        """Validate entity identification is coherent."""
        entity = request.entity
        
        # LEI must be 20 characters
        if entity.id_type == "LEI" and len(entity.external_id) != 20:
            result.add_error(
                field_name="entity.external_id",
                message="LEI must be exactly 20 characters",
                value=entity.external_id,
                constraint="lei_length",
            )
        
        # CUSIP must be 9 characters
        if entity.id_type == "CUSIP" and len(entity.external_id) != 9:
            result.add_error(
                field_name="entity.external_id",
                message="CUSIP must be exactly 9 characters",
                value=entity.external_id,
                constraint="cusip_length",
            )
        
        # ISIN must be 12 characters
        if entity.id_type == "ISIN" and len(entity.external_id) != 12:
            result.add_error(
                field_name="entity.external_id",
                message="ISIN must be exactly 12 characters",
                value=entity.external_id,
                constraint="isin_length",
            )
    
    def _enforce_policies(
        self,
        request: SolvencyEvaluationRequest,
        result: ValidationResult,
    ) -> None:
        """Enforce business and regulatory policies."""
        
        # Policy 1: Certain jurisdictions require specific frameworks
        self._enforce_jurisdiction_framework_policy(request, result)
        
        # Policy 2: Evidence policy constraints
        self._enforce_evidence_policy(request, result)
        
        # Policy 3: Output policy constraints
        self._enforce_output_policy(request, result)
    
    def _enforce_jurisdiction_framework_policy(
        self,
        request: SolvencyEvaluationRequest,
        result: ValidationResult,
    ) -> None:
        """Enforce jurisdiction-specific framework requirements."""
        from services.api_gateway.schemas import (
            RegulatoryFramework,
            EntityClassification,
        )
        
        # EU Insurance companies must use Solvency II or IFRS 17
        eu_jurisdictions = {
            "DE", "FR", "IT", "ES", "NL", "BE", "AT", "IE", "LU",
            "PL", "SE", "DK", "FI", "PT", "GR", "CZ", "RO", "HU",
        }
        eu_insurance_frameworks = {
            RegulatoryFramework.SOLVENCY_II,
            RegulatoryFramework.IFRS_17,
            RegulatoryFramework.CUSTOM,
        }
        
        if (request.jurisdiction in eu_jurisdictions and
            request.entity_classification == EntityClassification.INSURANCE_COMPANY and
            request.regulatory_framework not in eu_insurance_frameworks):
            result.add_policy_violation(
                f"EU insurance companies must use Solvency II, IFRS 17, or custom framework. "
                f"'{request.regulatory_framework.value}' is not permitted."
            )
    
    def _enforce_evidence_policy(
        self,
        request: SolvencyEvaluationRequest,
        result: ValidationResult,
    ) -> None:
        """Enforce evidence policy constraints."""
        evidence_policy = request.evidence_policy
        
        # High-priority requests require audited statements
        if request.priority.value in ("high", "critical"):
            if not evidence_policy.require_audited_statements:
                result.add_warning(
                    "High-priority requests typically require audited statements; "
                    "proceeding with provisional data may reduce confidence"
                )
    
    def _enforce_output_policy(
        self,
        request: SolvencyEvaluationRequest,
        result: ValidationResult,
    ) -> None:
        """Enforce output policy constraints."""
        output_policy = request.output_policy
        
        # Sensitivity analysis requires sufficient scenarios
        if output_policy.include_sensitivity_analysis:
            if len(request.stress_scenarios) < 2:
                result.add_error(
                    field_name="output_policy.include_sensitivity_analysis",
                    message="Sensitivity analysis requires at least 2 stress scenarios",
                    value=True,
                    constraint="sensitivity_requires_scenarios",
                )
    
    def _create_canonical_request(
        self,
        request: SolvencyEvaluationRequest,
        trace_id: str,
        received_at: datetime,
    ) -> CanonicalSolvencyRequest:
        """Create a canonical request with computed fields."""
        
        # Generate claim ID
        claim_id = generate_canonical_id(EntityType.CLAIM)
        
        # Compute deterministic request hash
        request_hash = self._compute_request_hash(request)
        
        now = datetime.now(timezone.utc)
        
        return CanonicalSolvencyRequest(
            claim_id=str(claim_id),
            request=request,
            request_hash=request_hash,
            trace_id=trace_id,
            received_at=received_at,
            normalized_at=now,
            api_version="v1",
        )
    
    def _compute_request_hash(self, request: SolvencyEvaluationRequest) -> str:
        """
        Compute a deterministic hash of the request for idempotency.
        
        The hash includes all fields that affect the evaluation result,
        excluding metadata and timestamps.
        """
        # Extract canonical fields for hashing
        hash_input = {
            "entity": {
                "external_id": request.entity.external_id,
                "id_type": request.entity.id_type,
                "name": request.entity.name,
            },
            "jurisdiction": request.jurisdiction,
            "entity_classification": request.entity_classification.value,
            "regulatory_framework": request.regulatory_framework.value,
            "analysis_horizon": {
                "months": request.analysis_horizon.months,
                "reference_date": request.analysis_horizon.reference_date.isoformat(),
            },
            "reporting_currency": request.reporting_currency,
            "stress_scenarios": [
                {
                    "scenario_type": s.scenario_type.value,
                    "name": s.name,
                    "shocks": [
                        {
                            "variable": shock.variable.value,
                            "shock_percent": str(shock.shock_percent),
                            "time_horizon_months": shock.time_horizon_months,
                        }
                        for shock in s.shocks
                    ],
                }
                for s in request.stress_scenarios
            ],
            "thresholds": {
                "minimum_capital_ratio": str(request.thresholds.minimum_capital_ratio) 
                    if request.thresholds.minimum_capital_ratio else None,
                "target_capital_ratio": str(request.thresholds.target_capital_ratio)
                    if request.thresholds.target_capital_ratio else None,
                "liquidity_coverage_ratio": str(request.thresholds.liquidity_coverage_ratio)
                    if request.thresholds.liquidity_coverage_ratio else None,
                "confidence_threshold": str(request.thresholds.confidence_threshold),
            },
            "evidence_policy": {
                "require_audited_statements": request.evidence_policy.require_audited_statements,
                "max_statement_age_days": request.evidence_policy.max_statement_age_days,
                "minimum_evidence_sources": request.evidence_policy.minimum_evidence_sources,
                "accept_provisional_data": request.evidence_policy.accept_provisional_data,
            },
        }
        
        content_hash = hash_content(hash_input)
        return str(content_hash)


# =============================================================================
# Idempotency Manager
# =============================================================================


class IdempotencyManager:
    """
    Manages request idempotency via hash-based deduplication.
    
    Uses the request hash to detect duplicate requests and return
    cached responses when appropriate.
    """
    
    def __init__(self) -> None:
        # In-memory cache for development; production uses persistent store
        self._cache: dict[str, tuple[str, datetime]] = {}
        self._logger = get_logger(__name__)
    
    def check_duplicate(
        self,
        request_hash: str,
        client_request_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Check if this request is a duplicate.
        
        Args:
            request_hash: Computed hash of the request
            client_request_id: Client-provided request ID
        
        Returns:
            Existing claim_id if duplicate, None otherwise
        """
        # Check by request hash
        if request_hash in self._cache:
            existing_claim_id, cached_at = self._cache[request_hash]
            self._logger.info(
                "Duplicate request detected by hash",
                request_hash=request_hash,
                existing_claim_id=existing_claim_id,
                cached_at=cached_at.isoformat(),
            )
            return existing_claim_id
        
        # Check by client request ID if provided
        if client_request_id:
            client_key = f"client:{client_request_id}"
            if client_key in self._cache:
                existing_claim_id, cached_at = self._cache[client_key]
                self._logger.info(
                    "Duplicate request detected by client_request_id",
                    client_request_id=client_request_id,
                    existing_claim_id=existing_claim_id,
                )
                return existing_claim_id
        
        return None
    
    def record_request(
        self,
        request_hash: str,
        claim_id: str,
        client_request_id: Optional[str] = None,
    ) -> None:
        """
        Record a new request for idempotency checking.
        
        Args:
            request_hash: Computed hash of the request
            claim_id: Assigned claim ID
            client_request_id: Client-provided request ID
        """
        now = datetime.now(timezone.utc)
        self._cache[request_hash] = (claim_id, now)
        
        if client_request_id:
            self._cache[f"client:{client_request_id}"] = (claim_id, now)
        
        self._logger.debug(
            "Request recorded for idempotency",
            request_hash=request_hash,
            claim_id=claim_id,
        )


# =============================================================================
# Factory Functions
# =============================================================================


def create_validator() -> SolvencyRequestValidator:
    """Create a new request validator instance."""
    return SolvencyRequestValidator()


def create_idempotency_manager() -> IdempotencyManager:
    """Create a new idempotency manager instance."""
    return IdempotencyManager()
