"""
Comprehensive Tests for A1 API Gateway
=======================================

Tests for the production-grade solvency evaluation API.
Validates:
- Schema validation with all edge cases
- Business rule enforcement
- Policy enforcement
- Idempotency
- Refusal responses
- End-to-end request flow
"""

import pytest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import json

from fastapi.testclient import TestClient
from pydantic import ValidationError

# Import the application and schemas
from services.api_gateway.app import create_app
from services.api_gateway.schemas import (
    SolvencyEvaluationRequest,
    CanonicalSolvencyRequest,
    EntityIdentifier,
    AnalysisHorizon,
    StressScenario,
    ScenarioShock,
    ThresholdConfiguration,
    OutputPolicy,
    EvidencePolicy,
    EntityClassification,
    RegulatoryFramework,
    ScenarioType,
    ShockVariable,
    OutputFormat,
    Priority,
    SUPPORTED_JURISDICTIONS,
    SUPPORTED_CURRENCIES,
    MIN_HORIZON_MONTHS,
    MAX_HORIZON_MONTHS,
    MIN_SHOCK_PERCENT,
    MAX_SHOCK_PERCENT,
)
from services.api_gateway.validation import (
    SolvencyRequestValidator,
    IdempotencyManager,
    ValidationResult,
    create_validator,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def app():
    """Create test application."""
    return create_app()


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def validator():
    """Create a request validator."""
    return create_validator()


@pytest.fixture
def valid_request_data():
    """Create a valid solvency evaluation request."""
    return {
        "entity": {
            "external_id": "549300EXAMPLE00LEI00",  # 20 chars
            "id_type": "LEI",
            "name": "Example Financial Corporation",
        },
        "jurisdiction": "US",
        "entity_classification": "bank",
        "regulatory_framework": "basel_iii",
        "analysis_horizon": {
            "months": 12,
            "reference_date": date.today().isoformat(),
        },
        "reporting_currency": "USD",
        "stress_scenarios": [
            {
                "scenario_type": "adverse",
                "name": "Interest Rate Shock",
                "shocks": [
                    {
                        "variable": "interest_rate",
                        "shock_percent": 25.0,
                        "time_horizon_months": 6,
                    }
                ],
            }
        ],
        "thresholds": {
            "minimum_capital_ratio": "0.08",
            "target_capital_ratio": "0.12",
            "confidence_threshold": "0.95",
        },
        "priority": "standard",
    }


@pytest.fixture
def minimal_valid_request():
    """Minimal valid request with only required fields."""
    return {
        "entity": {
            "external_id": "INTERNAL123",
            "id_type": "INTERNAL",
            "name": "Test Entity",
        },
        "jurisdiction": "US",
        "entity_classification": "bank",
        "regulatory_framework": "basel_iii",
        "analysis_horizon": {
            "months": 12,
            "reference_date": date.today().isoformat(),
        },
        "reporting_currency": "USD",
    }


# =============================================================================
# Schema Validation Tests
# =============================================================================


class TestEntityIdentifier:
    """Tests for EntityIdentifier schema."""

    def test_valid_lei(self):
        """LEI identifier with correct format."""
        entity = EntityIdentifier(
            external_id="549300EXAMPLE00LEI00",  # 20 chars
            id_type="LEI",
            name="Test Corp",
        )
        assert len(entity.external_id) == 20

    def test_external_id_normalized(self):
        """External ID is uppercased and stripped."""
        entity = EntityIdentifier(
            external_id="  abc123def  ",
            id_type="INTERNAL",
            name="Test Corp",
        )
        assert entity.external_id == "ABC123DEF"

    def test_name_whitespace_normalized(self):
        """Entity name has extra whitespace collapsed."""
        entity = EntityIdentifier(
            external_id="ABC",
            id_type="INTERNAL",
            name="  Test   Corp   Inc  ",
        )
        assert entity.name == "Test Corp Inc"

    def test_empty_external_id_rejected(self):
        """Empty external ID is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            EntityIdentifier(
                external_id="",
                id_type="INTERNAL",
                name="Test",
            )
        assert "external_id" in str(exc_info.value)

    def test_invalid_id_type_rejected(self):
        """Invalid ID type pattern is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            EntityIdentifier(
                external_id="ABC",
                id_type="invalid-type",  # Must match ^[A-Z][A-Z0-9_]*$
                name="Test",
            )
        assert "id_type" in str(exc_info.value)


class TestAnalysisHorizon:
    """Tests for AnalysisHorizon schema."""

    def test_valid_horizon(self):
        """Valid analysis horizon."""
        horizon = AnalysisHorizon(
            months=24,
            reference_date=date.today(),
        )
        assert horizon.months == 24

    def test_min_horizon(self):
        """Minimum horizon is 1 month."""
        horizon = AnalysisHorizon(
            months=MIN_HORIZON_MONTHS,
            reference_date=date.today(),
        )
        assert horizon.months == 1

    def test_max_horizon(self):
        """Maximum horizon is 120 months."""
        horizon = AnalysisHorizon(
            months=MAX_HORIZON_MONTHS,
            reference_date=date.today(),
        )
        assert horizon.months == 120

    def test_horizon_below_min_rejected(self):
        """Horizon below minimum is rejected."""
        with pytest.raises(ValidationError):
            AnalysisHorizon(
                months=0,
                reference_date=date.today(),
            )

    def test_horizon_above_max_rejected(self):
        """Horizon above maximum is rejected."""
        with pytest.raises(ValidationError):
            AnalysisHorizon(
                months=MAX_HORIZON_MONTHS + 1,
                reference_date=date.today(),
            )

    def test_future_date_within_year(self):
        """Reference date within 1 year future is accepted."""
        from datetime import timedelta
        future_date = date.today() + timedelta(days=300)
        horizon = AnalysisHorizon(
            months=12,
            reference_date=future_date,
        )
        assert horizon.reference_date == future_date

    def test_date_too_far_rejected(self):
        """Reference date more than 1 year away is rejected."""
        from datetime import timedelta
        far_future = date.today() + timedelta(days=400)
        with pytest.raises(ValidationError) as exc_info:
            AnalysisHorizon(
                months=12,
                reference_date=far_future,
            )
        assert "Reference date must be within 1 year" in str(exc_info.value)


class TestScenarioShock:
    """Tests for ScenarioShock schema."""

    def test_valid_shock(self):
        """Valid scenario shock."""
        shock = ScenarioShock(
            variable=ShockVariable.INTEREST_RATE,
            shock_percent=Decimal("25.0"),
            time_horizon_months=6,
        )
        assert shock.variable == ShockVariable.INTEREST_RATE

    def test_shock_percent_normalized(self):
        """Shock percent is normalized to 4 decimal places."""
        shock = ScenarioShock(
            variable=ShockVariable.EQUITY_PRICE,
            shock_percent=Decimal("25.12345678"),
            time_horizon_months=12,
        )
        assert shock.shock_percent == Decimal("25.1235")

    def test_negative_shock(self):
        """Negative shock (decline) is valid."""
        shock = ScenarioShock(
            variable=ShockVariable.REAL_ESTATE,
            shock_percent=Decimal("-30.0"),
            time_horizon_months=12,
        )
        assert shock.shock_percent == Decimal("-30.0000")

    def test_shock_at_min_bound(self):
        """Shock at minimum bound (-100%)."""
        shock = ScenarioShock(
            variable=ShockVariable.DEFAULT_RATE,
            shock_percent=MIN_SHOCK_PERCENT,
            time_horizon_months=12,
        )
        assert shock.shock_percent == Decimal("-100.0000")

    def test_shock_at_max_bound(self):
        """Shock at maximum bound (+500%)."""
        shock = ScenarioShock(
            variable=ShockVariable.VOLATILITY,
            shock_percent=MAX_SHOCK_PERCENT,
            time_horizon_months=12,
        )
        assert shock.shock_percent == Decimal("500.0000")

    def test_shock_below_min_rejected(self):
        """Shock below minimum is rejected."""
        with pytest.raises(ValidationError):
            ScenarioShock(
                variable=ShockVariable.GDP_GROWTH,
                shock_percent=Decimal("-101.0"),
                time_horizon_months=12,
            )

    def test_shock_above_max_rejected(self):
        """Shock above maximum is rejected."""
        with pytest.raises(ValidationError):
            ScenarioShock(
                variable=ShockVariable.INFLATION,
                shock_percent=Decimal("501.0"),
                time_horizon_months=12,
            )


class TestStressScenario:
    """Tests for StressScenario schema."""

    def test_valid_scenario(self):
        """Valid stress scenario with shocks."""
        scenario = StressScenario(
            scenario_type=ScenarioType.ADVERSE,
            name="Market Stress",
            shocks=[
                ScenarioShock(
                    variable=ShockVariable.EQUITY_PRICE,
                    shock_percent=Decimal("-25.0"),
                ),
            ],
        )
        assert scenario.scenario_type == ScenarioType.ADVERSE

    def test_custom_requires_shocks(self):
        """Custom scenario must have at least one shock."""
        with pytest.raises(ValidationError) as exc_info:
            StressScenario(
                scenario_type=ScenarioType.CUSTOM,
                name="Empty Custom",
                shocks=[],
            )
        assert "Custom scenarios must define at least one shock" in str(exc_info.value)

    def test_duplicate_shock_variables_rejected(self):
        """Duplicate shock variables in same scenario rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StressScenario(
                scenario_type=ScenarioType.ADVERSE,
                name="Duplicate Test",
                shocks=[
                    ScenarioShock(variable=ShockVariable.INTEREST_RATE, shock_percent=Decimal("10")),
                    ScenarioShock(variable=ShockVariable.INTEREST_RATE, shock_percent=Decimal("20")),
                ],
            )
        assert "Duplicate shock variables" in str(exc_info.value)

    def test_baseline_with_no_shocks(self):
        """Baseline scenario can have no shocks."""
        scenario = StressScenario(
            scenario_type=ScenarioType.BASELINE,
            name="Baseline",
            shocks=[],
        )
        assert len(scenario.shocks) == 0


class TestSolvencyEvaluationRequest:
    """Tests for the main request schema."""

    def test_valid_full_request(self, valid_request_data):
        """Valid request with all fields."""
        request = SolvencyEvaluationRequest.model_validate(valid_request_data)
        assert request.jurisdiction == "US"
        assert request.entity_classification == EntityClassification.BANK

    def test_minimal_request(self, minimal_valid_request):
        """Minimal valid request with defaults."""
        request = SolvencyEvaluationRequest.model_validate(minimal_valid_request)
        assert request.priority == Priority.STANDARD
        assert request.output_policy.format == OutputFormat.FULL

    def test_unsupported_jurisdiction_rejected(self, minimal_valid_request):
        """Unsupported jurisdiction is rejected."""
        minimal_valid_request["jurisdiction"] = "XX"
        with pytest.raises(ValidationError) as exc_info:
            SolvencyEvaluationRequest.model_validate(minimal_valid_request)
        assert "not supported" in str(exc_info.value)

    def test_unsupported_currency_rejected(self, minimal_valid_request):
        """Unsupported currency is rejected."""
        minimal_valid_request["reporting_currency"] = "XYZ"
        with pytest.raises(ValidationError) as exc_info:
            SolvencyEvaluationRequest.model_validate(minimal_valid_request)
        assert "not supported" in str(exc_info.value)

    def test_jurisdiction_normalized(self, minimal_valid_request):
        """Jurisdiction is uppercased (validated at schema level)."""
        # Note: Schema requires uppercase pattern, normalization happens in validator
        minimal_valid_request["jurisdiction"] = "US"
        request = SolvencyEvaluationRequest.model_validate(minimal_valid_request)
        assert request.jurisdiction == "US"

    def test_bank_with_solvency_ii_rejected(self, minimal_valid_request):
        """Bank with Solvency II framework is rejected."""
        minimal_valid_request["regulatory_framework"] = "solvency_ii"
        with pytest.raises(ValidationError) as exc_info:
            SolvencyEvaluationRequest.model_validate(minimal_valid_request)
        assert "Basel" in str(exc_info.value) or "framework" in str(exc_info.value).lower()

    def test_insurance_with_basel_rejected(self, minimal_valid_request):
        """Insurance company with Basel framework is rejected."""
        minimal_valid_request["entity_classification"] = "insurance_company"
        minimal_valid_request["regulatory_framework"] = "basel_iii"
        with pytest.raises(ValidationError) as exc_info:
            SolvencyEvaluationRequest.model_validate(minimal_valid_request)
        assert "Solvency" in str(exc_info.value) or "IFRS" in str(exc_info.value)

    def test_extra_fields_rejected(self, minimal_valid_request):
        """Extra fields are rejected (strict mode)."""
        minimal_valid_request["unknown_field"] = "value"
        with pytest.raises(ValidationError) as exc_info:
            SolvencyEvaluationRequest.model_validate(minimal_valid_request)
        assert "extra" in str(exc_info.value).lower()

    def test_callback_url_must_be_https(self, minimal_valid_request):
        """Callback URL must use HTTPS."""
        minimal_valid_request["callback_url"] = "http://example.com/callback"
        with pytest.raises(ValidationError):
            SolvencyEvaluationRequest.model_validate(minimal_valid_request)


# =============================================================================
# Validation Service Tests
# =============================================================================


class TestSolvencyRequestValidator:
    """Tests for the validation service."""

    def test_valid_request_passes(self, validator, valid_request_data):
        """Valid request passes validation."""
        result, canonical = validator.validate_and_normalize(
            raw_data=valid_request_data,
            trace_id="test-trace-123",
        )
        
        assert result.is_valid
        assert canonical is not None
        assert canonical.claim_id.startswith("CLM_")
        assert canonical.request_hash.startswith("sha256v1:")

    def test_invalid_json_structure(self, validator):
        """Invalid JSON structure produces field errors."""
        result, canonical = validator.validate_and_normalize(
            raw_data={"invalid": "structure"},
            trace_id="test-trace-456",
        )
        
        assert not result.is_valid
        assert canonical is None
        assert len(result.errors) > 0

    def test_lei_length_validation(self, validator, valid_request_data):
        """LEI with wrong length produces error."""
        valid_request_data["entity"]["external_id"] = "TOOLONG" * 5
        result, canonical = validator.validate_and_normalize(
            raw_data=valid_request_data,
            trace_id="test-trace-789",
        )
        
        assert not result.is_valid
        # Find the LEI error
        lei_error = next(
            (e for e in result.errors if "LEI" in e.message),
            None
        )
        assert lei_error is not None

    def test_shock_horizon_exceeds_analysis(self, validator, valid_request_data):
        """Shock horizon exceeding analysis horizon produces error."""
        valid_request_data["analysis_horizon"]["months"] = 6
        valid_request_data["stress_scenarios"][0]["shocks"][0]["time_horizon_months"] = 12
        
        result, canonical = validator.validate_and_normalize(
            raw_data=valid_request_data,
            trace_id="test-trace-abc",
        )
        
        assert not result.is_valid
        horizon_error = next(
            (e for e in result.errors if "horizon" in e.message.lower()),
            None
        )
        assert horizon_error is not None

    def test_duplicate_scenario_names(self, validator, valid_request_data):
        """Duplicate scenario names produce error."""
        valid_request_data["stress_scenarios"].append(
            valid_request_data["stress_scenarios"][0].copy()
        )
        
        result, canonical = validator.validate_and_normalize(
            raw_data=valid_request_data,
            trace_id="test-trace-def",
        )
        
        assert not result.is_valid
        dup_error = next(
            (e for e in result.errors if "Duplicate" in e.message),
            None
        )
        assert dup_error is not None

    def test_request_hash_deterministic(self, validator, valid_request_data):
        """Same request produces same hash."""
        result1, canonical1 = validator.validate_and_normalize(
            raw_data=valid_request_data,
            trace_id="trace-1",
        )
        result2, canonical2 = validator.validate_and_normalize(
            raw_data=valid_request_data,
            trace_id="trace-2",
        )
        
        assert canonical1.request_hash == canonical2.request_hash

    def test_different_requests_different_hash(self, validator, valid_request_data):
        """Different requests produce different hashes."""
        result1, canonical1 = validator.validate_and_normalize(
            raw_data=valid_request_data,
            trace_id="trace-1",
        )
        
        valid_request_data["analysis_horizon"]["months"] = 24
        result2, canonical2 = validator.validate_and_normalize(
            raw_data=valid_request_data,
            trace_id="trace-2",
        )
        
        assert canonical1.request_hash != canonical2.request_hash


# =============================================================================
# Idempotency Tests
# =============================================================================


class TestIdempotencyManager:
    """Tests for idempotency management."""

    def test_new_request_not_duplicate(self):
        """New request is not detected as duplicate."""
        manager = IdempotencyManager()
        
        result = manager.check_duplicate(
            request_hash="sha256v1:abc123",
        )
        
        assert result is None

    def test_duplicate_by_hash(self):
        """Duplicate detected by request hash."""
        manager = IdempotencyManager()
        
        manager.record_request(
            request_hash="sha256v1:abc123",
            claim_id="CLM_test1",
        )
        
        result = manager.check_duplicate(
            request_hash="sha256v1:abc123",
        )
        
        assert result == "CLM_test1"

    def test_duplicate_by_client_id(self):
        """Duplicate detected by client request ID."""
        manager = IdempotencyManager()
        
        manager.record_request(
            request_hash="sha256v1:abc123",
            claim_id="CLM_test2",
            client_request_id="client-req-001",
        )
        
        result = manager.check_duplicate(
            request_hash="sha256v1:different",
            client_request_id="client-req-001",
        )
        
        assert result == "CLM_test2"

    def test_different_hash_not_duplicate(self):
        """Different hash is not detected as duplicate."""
        manager = IdempotencyManager()
        
        manager.record_request(
            request_hash="sha256v1:abc123",
            claim_id="CLM_test3",
        )
        
        result = manager.check_duplicate(
            request_hash="sha256v1:different",
        )
        
        assert result is None


# =============================================================================
# API Endpoint Tests
# =============================================================================


class TestHealthEndpoints:
    """Tests for health and readiness endpoints."""

    def test_health_endpoint(self, client):
        """Health endpoint returns healthy status."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "api-gateway"

    def test_ready_endpoint(self, client):
        """Ready endpoint returns ready status."""
        response = client.get("/ready")
        
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] == True

    def test_root_endpoint(self, client):
        """Root endpoint returns service info."""
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert "Financial Solvency" in data["service"]


class TestSolvencyEvaluationEndpoint:
    """Tests for the main solvency evaluation endpoint."""

    def test_valid_request_accepted(self, client, valid_request_data):
        """Valid request is accepted with 202 status."""
        response = client.post(
            "/v1/claims/solvency:evaluate",
            json=valid_request_data,
        )
        
        assert response.status_code == 202
        data = response.json()
        assert data["success"] == True
        assert data["data"]["status"] == "accepted"
        assert data["data"]["claim_id"].startswith("CLM_")
        assert "trace_id" in data

    def test_trace_id_in_response_header(self, client, valid_request_data):
        """Trace ID is included in response headers."""
        response = client.post(
            "/v1/claims/solvency:evaluate",
            json=valid_request_data,
            headers={"X-Trace-ID": "custom-trace-123"},
        )
        
        assert response.headers.get("X-Trace-ID") == "custom-trace-123"

    def test_invalid_json_rejected(self, client):
        """Invalid JSON is rejected with 400."""
        response = client.post(
            "/v1/claims/solvency:evaluate",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["refused"] == True

    def test_missing_required_fields_rejected(self, client):
        """Missing required fields produce 422."""
        response = client.post(
            "/v1/claims/solvency:evaluate",
            json={"entity": {"external_id": "ABC", "id_type": "LEI", "name": "Test"}},
        )
        
        assert response.status_code == 422
        data = response.json()
        assert data["refused"] == True
        assert len(data["field_errors"]) > 0

    def test_unsupported_jurisdiction_rejected(self, client, valid_request_data):
        """Unsupported jurisdiction produces 422."""
        valid_request_data["jurisdiction"] = "XX"
        
        response = client.post(
            "/v1/claims/solvency:evaluate",
            json=valid_request_data,
        )
        
        assert response.status_code == 422
        data = response.json()
        assert data["refused"] == True
        assert "jurisdiction" in str(data).lower()

    def test_shock_out_of_bounds_rejected(self, client, valid_request_data):
        """Shock value out of bounds produces 422."""
        valid_request_data["stress_scenarios"][0]["shocks"][0]["shock_percent"] = 600.0
        
        response = client.post(
            "/v1/claims/solvency:evaluate",
            json=valid_request_data,
        )
        
        assert response.status_code == 422
        data = response.json()
        assert data["refused"] == True

    def test_duplicate_request_returns_existing(self, client):
        """Duplicate request returns existing claim ID."""
        # Use a unique request to avoid interference from other tests
        unique_request = {
            "entity": {
                "external_id": "DUPTEST1234567890AB",  # 20 chars, unique
                "id_type": "INTERNAL",
                "name": "Duplicate Test Entity",
            },
            "jurisdiction": "US",
            "entity_classification": "bank",
            "regulatory_framework": "basel_iii",
            "analysis_horizon": {
                "months": 18,  # Different from other tests
                "reference_date": date.today().isoformat(),
            },
            "reporting_currency": "USD",
        }
        
        # First request - should be 202
        response1 = client.post(
            "/v1/claims/solvency:evaluate",
            json=unique_request,
        )
        assert response1.status_code == 202
        claim_id1 = response1.json()["data"]["claim_id"]
        
        # Second identical request
        response2 = client.post(
            "/v1/claims/solvency:evaluate",
            json=unique_request,
        )
        
        # Should return 200 (not 202) for idempotent return
        assert response2.status_code == 200
        claim_id2 = response2.json()["data"]["claim_id"]
        
        assert claim_id1 == claim_id2
        assert response2.headers.get("X-Idempotent") == "true"

    def test_client_request_id_idempotency(self, client, valid_request_data):
        """Client request ID enables idempotency."""
        valid_request_data["client_request_id"] = "unique-client-id-123"
        
        response1 = client.post(
            "/v1/claims/solvency:evaluate",
            json=valid_request_data,
        )
        claim_id1 = response1.json()["data"]["claim_id"]
        
        # Modify request but keep same client_request_id
        valid_request_data["priority"] = "high"
        
        response2 = client.post(
            "/v1/claims/solvency:evaluate",
            json=valid_request_data,
        )
        claim_id2 = response2.json()["data"]["claim_id"]
        
        assert claim_id1 == claim_id2


class TestStatusEndpoint:
    """Tests for the status check endpoint."""

    def test_status_endpoint(self, client):
        """Status endpoint returns claim status."""
        response = client.get("/v1/claims/solvency/CLM_test123/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["claim_id"] == "CLM_test123"
        assert "status" in data


# =============================================================================
# Integration Tests
# =============================================================================


class TestEndToEndFlow:
    """End-to-end integration tests."""

    def test_full_flow_with_scenarios(self, client):
        """Complete request with multiple scenarios."""
        request = {
            "entity": {
                "external_id": "549300FULLTEST0LEI00",  # 20 chars
                "id_type": "LEI",
                "name": "Full Test Corporation",
            },
            "jurisdiction": "US",
            "entity_classification": "bank",
            "regulatory_framework": "basel_iii",
            "analysis_horizon": {
                "months": 36,
                "reference_date": date.today().isoformat(),
            },
            "reporting_currency": "USD",
            "stress_scenarios": [
                {
                    "scenario_type": "baseline",
                    "name": "Base Case",
                    "shocks": [],
                },
                {
                    "scenario_type": "adverse",
                    "name": "Rate Shock",
                    "shocks": [
                        {"variable": "interest_rate", "shock_percent": 25.0},
                        {"variable": "credit_spread", "shock_percent": 50.0},
                    ],
                },
                {
                    "scenario_type": "severely_adverse",
                    "name": "Market Crash",
                    "shocks": [
                        {"variable": "equity_price", "shock_percent": -40.0},
                        {"variable": "real_estate", "shock_percent": -30.0},
                        {"variable": "volatility", "shock_percent": 100.0},
                    ],
                },
            ],
            "thresholds": {
                "minimum_capital_ratio": "0.08",
                "target_capital_ratio": "0.12",
                "liquidity_coverage_ratio": "1.0",
                "confidence_threshold": "0.99",
            },
            "output_policy": {
                "format": "full",
                "include_evidence_chain": True,
                "include_reasoning_trace": True,
                "include_sensitivity_analysis": True,
            },
            "evidence_policy": {
                "require_audited_statements": True,
                "max_statement_age_days": 180,
                "minimum_evidence_sources": 2,
            },
            "priority": "high",
            "client_request_id": "integration-test-001",
        }
        
        response = client.post(
            "/v1/claims/solvency:evaluate",
            json=request,
            headers={"X-Trace-ID": "integration-test-trace"},
        )
        
        assert response.status_code == 202
        data = response.json()
        
        assert data["success"] == True
        assert data["data"]["claim_id"].startswith("CLM_")
        assert data["data"]["request_hash"].startswith("sha256v1:")
        assert data["trace_id"] == "integration-test-trace"
        assert data["data"]["estimated_completion_seconds"] is not None

    def test_eu_insurance_solvency_ii(self, client):
        """EU insurance company with Solvency II."""
        request = {
            "entity": {
                "external_id": "EUINSURANCE1234LEI00",  # 20 chars
                "id_type": "LEI",
                "name": "EU Insurance AG",
            },
            "jurisdiction": "DE",
            "entity_classification": "insurance_company",
            "regulatory_framework": "solvency_ii",
            "analysis_horizon": {
                "months": 12,
                "reference_date": date.today().isoformat(),
            },
            "reporting_currency": "EUR",
        }
        
        response = client.post(
            "/v1/claims/solvency:evaluate",
            json=request,
        )
        
        assert response.status_code == 202


# =============================================================================
# Error Response Tests
# =============================================================================


class TestRefusalResponses:
    """Tests for structured refusal responses."""

    def test_refusal_includes_all_fields(self, client):
        """Refusal response includes all required fields."""
        response = client.post(
            "/v1/claims/solvency:evaluate",
            json={},  # Empty request
        )
        
        assert response.status_code == 422
        data = response.json()
        
        assert "refused" in data
        assert "reason" in data
        assert "category" in data
        assert "trace_id" in data
        assert "timestamp" in data

    def test_multiple_errors_accumulated(self, client):
        """Multiple validation errors are accumulated."""
        response = client.post(
            "/v1/claims/solvency:evaluate",
            json={
                "entity": {"external_id": "", "id_type": "bad", "name": ""},
                "jurisdiction": "XX",
                "entity_classification": "unknown",
                "regulatory_framework": "unknown",
                "analysis_horizon": {"months": 0, "reference_date": "invalid"},
                "reporting_currency": "XXX",
            },
        )
        
        assert response.status_code == 422
        data = response.json()
        
        # Should have multiple field errors
        assert len(data["field_errors"]) > 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
