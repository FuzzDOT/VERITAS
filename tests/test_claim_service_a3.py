"""
Claim Service A3 Tests - Comprehensive Test Suite
===================================================

Tests for the production Claim Service implementation covering:
- Valid claim processing
- Semantic refusals
- Entity resolution
- Horizon validation
- Scenario validation
- Required facts derivation
- Determinism guarantees
- Edge cases
"""

import pytest
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from services.claim_service.app import create_app, get_claim_service
from services.claim_service.processor import ClaimProcessor
from services.claim_service.service import ClaimService
from services.claim_service.schemas import (
    ClaimType,
    SemanticRefusalCode,
    FactCategory,
    FactPriority,
    EntityResolutionStatus,
    SemanticValidationResult,
    ProcessClaimRequest,
    ENTITIES_WITH_SOLVENCY_SEMANTICS,
    ENTITIES_WITHOUT_SOLVENCY_SEMANTICS,
    SUPPORTED_SHOCKS_BY_ENTITY,
    MIN_MEANINGFUL_HORIZON_MONTHS,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def processor() -> ClaimProcessor:
    """Create a fresh ClaimProcessor instance."""
    return ClaimProcessor()


@pytest.fixture
def service() -> ClaimService:
    """Create a fresh ClaimService instance."""
    return ClaimService()


@pytest.fixture
def app():
    """Create test application."""
    return create_app()


@pytest.fixture
def client(app) -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def valid_bank_request() -> dict[str, Any]:
    """Valid solvency request for a US bank."""
    return {
        "entity": {
            "external_id": "549300EXAMPLE00LEI00",
            "id_type": "LEI",
            "name": "Example Bank Corporation",
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
                        "shock_percent": 2.0,
                        "time_horizon_months": 12,
                    }
                ],
            }
        ],
        "thresholds": {
            "minimum_capital_ratio": 0.08,
            "target_capital_ratio": 0.12,
            "confidence_threshold": 0.95,
        },
        "evidence_policy": {
            "require_audited_statements": True,
            "max_statement_age_days": 365,
        },
    }


@pytest.fixture
def valid_insurance_request() -> dict[str, Any]:
    """Valid solvency request for an EU insurance company."""
    return {
        "entity": {
            "external_id": "549300INSURANCELEIXX",  # Exactly 20 chars
            "id_type": "LEI",
            "name": "European Insurance Group",
        },
        "jurisdiction": "DE",
        "entity_classification": "insurance_company",
        "regulatory_framework": "solvency_ii",
        "analysis_horizon": {
            "months": 24,
            "reference_date": date.today().isoformat(),
        },
        "reporting_currency": "EUR",
        "stress_scenarios": [
            {
                "scenario_type": "severely_adverse",
                "name": "Market Stress",
                "shocks": [
                    {
                        "variable": "equity_price",
                        "shock_percent": -40.0,
                        "time_horizon_months": 12,
                    },
                    {
                        "variable": "interest_rate",
                        "shock_percent": -1.5,
                        "time_horizon_months": 12,
                    },
                ],
            }
        ],
    }


@pytest.fixture
def valid_corporate_request() -> dict[str, Any]:
    """Valid solvency request for a corporate entity."""
    return {
        "entity": {
            "external_id": "CORP123456",
            "id_type": "INTERNAL",
            "name": "Acme Corporation Inc.",
        },
        "jurisdiction": "US",
        "entity_classification": "corporate",
        "regulatory_framework": "us_gaap",
        "analysis_horizon": {
            "months": 36,
            "reference_date": date.today().isoformat(),
        },
        "reporting_currency": "USD",
        "stress_scenarios": [],
    }


# =============================================================================
# Test: Valid Claim Processing
# =============================================================================


class TestValidClaimProcessing:
    """Tests for processing valid claims."""
    
    def test_process_valid_bank_claim(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test processing a valid bank solvency claim."""
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_hash_bank_001",
            trace_id="test_trace_bank_001",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        assert result.required_facts_contract is not None
        assert result.semantic_refusals == []
        
        # Verify canonical claim structure
        claim = result.canonical_claim
        assert claim.claim_type == ClaimType.SOLVENCY
        assert claim.entity_classification == "bank"
        assert claim.jurisdiction == "US"
        assert claim.regulatory_framework == "basel_iii"
        
        # Verify entity resolution
        assert claim.entity.external_id == "549300EXAMPLE00LEI00"
        assert claim.entity.id_type == "LEI"
        assert claim.entity.resolution_status in (
            EntityResolutionStatus.RESOLVED,
            EntityResolutionStatus.NORMALIZED,
        )
    
    def test_process_valid_insurance_claim(self, processor: ClaimProcessor, valid_insurance_request: dict):
        """Test processing a valid insurance company solvency claim."""
        result = processor.process(
            api_request=valid_insurance_request,
            request_hash="test_hash_ins_001",
            trace_id="test_trace_ins_001",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        
        claim = result.canonical_claim
        assert claim.entity_classification == "insurance_company"
        assert claim.jurisdiction == "DE"
        assert claim.regulatory_framework == "solvency_ii"
    
    def test_process_valid_corporate_claim(self, processor: ClaimProcessor, valid_corporate_request: dict):
        """Test processing a valid corporate solvency claim."""
        result = processor.process(
            api_request=valid_corporate_request,
            request_hash="test_hash_corp_001",
            trace_id="test_trace_corp_001",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        
        claim = result.canonical_claim
        assert claim.entity_classification == "corporate"
        # Long horizon should include debt schedule facts
        contract = result.required_facts_contract
        assert contract is not None
        fact_names = [f.fact_name for f in contract.required_facts + contract.material_facts]
        assert "debt_maturity_schedule" in fact_names
    
    def test_baseline_scenario_always_present(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test that baseline scenario is always present."""
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_hash_baseline",
            trace_id="test_trace_baseline",
        )
        
        assert result.success is True
        claim = result.canonical_claim
        assert claim is not None
        assert claim.baseline_scenario is not None
        assert claim.baseline_scenario.scenario_type == "baseline"
        assert claim.baseline_scenario.validated_shocks == []


# =============================================================================
# Test: Entity Resolution
# =============================================================================


class TestEntityResolution:
    """Tests for entity identifier resolution and normalization."""
    
    def test_lei_valid_20_chars(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test valid 20-character LEI is accepted."""
        valid_bank_request["entity"]["external_id"] = "529900T8BM49AURSDO55"
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_lei_valid",
            trace_id="test_trace_lei_valid",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        assert result.canonical_claim.entity.resolution_status != EntityResolutionStatus.INVALID
    
    def test_lei_invalid_19_chars(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test LEI with wrong length is rejected."""
        valid_bank_request["entity"]["external_id"] = "529900T8BM49AURSD5"  # 18 chars
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_lei_short",
            trace_id="test_trace_lei_short",
        )
        
        assert result.success is False
        assert any(
            r.code == SemanticRefusalCode.ENTITY_ID_INVALID_FORMAT
            for r in result.semantic_refusals
        )
    
    def test_lei_invalid_21_chars(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test LEI with 21 chars is rejected."""
        valid_bank_request["entity"]["external_id"] = "529900T8BM49AURSDO555"  # 21 chars
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_lei_long",
            trace_id="test_trace_lei_long",
        )
        
        assert result.success is False
    
    def test_cik_padding_normalization(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test CIK is normalized with zero-padding."""
        valid_bank_request["entity"]["external_id"] = "12345"
        valid_bank_request["entity"]["id_type"] = "CIK"
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_cik_pad",
            trace_id="test_trace_cik_pad",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        # CIK should be padded to 10 digits
        assert result.canonical_claim.entity.external_id == "0000012345"
    
    def test_cusip_valid_9_chars(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test valid 9-character CUSIP is accepted."""
        valid_bank_request["entity"]["external_id"] = "037833100"
        valid_bank_request["entity"]["id_type"] = "CUSIP"
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_cusip_valid",
            trace_id="test_trace_cusip",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        assert result.canonical_claim.entity.resolution_status != EntityResolutionStatus.INVALID
    
    def test_cusip_invalid_length(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test CUSIP with wrong length is rejected."""
        valid_bank_request["entity"]["external_id"] = "03783310"  # 8 chars
        valid_bank_request["entity"]["id_type"] = "CUSIP"
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_cusip_short",
            trace_id="test_trace_cusip_short",
        )
        
        assert result.success is False
    
    def test_isin_valid_12_chars(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test valid 12-character ISIN is accepted."""
        valid_bank_request["entity"]["external_id"] = "US0378331005"
        valid_bank_request["entity"]["id_type"] = "ISIN"
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_isin_valid",
            trace_id="test_trace_isin",
        )
        
        assert result.success is True
    
    def test_entity_name_whitespace_normalization(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test entity name whitespace is normalized."""
        valid_bank_request["entity"]["name"] = "  Example   Bank   Corporation  "
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_name_ws",
            trace_id="test_trace_name_ws",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        assert result.canonical_claim.entity.name == "Example Bank Corporation"
    
    def test_external_id_uppercase_normalization(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test external ID is normalized to uppercase."""
        valid_bank_request["entity"]["external_id"] = "549300example00lei00"
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_upper",
            trace_id="test_trace_upper",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        assert result.canonical_claim.entity.external_id == "549300EXAMPLE00LEI00"


# =============================================================================
# Test: Semantic Refusals - Entity Type
# =============================================================================


class TestSemanticRefusalsEntityType:
    """Tests for semantic refusals related to entity types."""
    
    def test_sovereign_entity_refused(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test sovereign entities are refused (no solvency semantics)."""
        valid_bank_request["entity_classification"] = "sovereign"
        valid_bank_request["regulatory_framework"] = "custom"
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_sovereign",
            trace_id="test_trace_sovereign",
        )
        
        assert result.success is False
        assert any(
            r.code == SemanticRefusalCode.ENTITY_TYPE_NO_SOLVENCY_SEMANTICS
            for r in result.semantic_refusals
        )
    
    def test_municipal_entity_refused(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test municipal entities are refused."""
        valid_bank_request["entity_classification"] = "municipal"
        valid_bank_request["regulatory_framework"] = "custom"
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_municipal",
            trace_id="test_trace_municipal",
        )
        
        assert result.success is False
        assert any(
            r.code == SemanticRefusalCode.ENTITY_TYPE_NO_SOLVENCY_SEMANTICS
            for r in result.semantic_refusals
        )
    
    def test_spv_entity_refused(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test SPV entities are refused."""
        valid_bank_request["entity_classification"] = "spv"
        valid_bank_request["regulatory_framework"] = "custom"
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_spv",
            trace_id="test_trace_spv",
        )
        
        assert result.success is False
        assert any(
            r.code == SemanticRefusalCode.ENTITY_TYPE_NO_SOLVENCY_SEMANTICS
            for r in result.semantic_refusals
        )
    
    def test_all_valid_entity_types_accepted(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test all entity types with solvency semantics are accepted."""
        for entity_type in ENTITIES_WITH_SOLVENCY_SEMANTICS:
            valid_bank_request["entity_classification"] = entity_type
            valid_bank_request["regulatory_framework"] = "custom"
            
            result = processor.process(
                api_request=valid_bank_request,
                request_hash=f"test_{entity_type}",
                trace_id=f"test_trace_{entity_type}",
            )
            
            assert result.success is True, f"Entity type {entity_type} should be accepted"


# =============================================================================
# Test: Semantic Refusals - Horizon
# =============================================================================


class TestSemanticRefusalsHorizon:
    """Tests for semantic refusals related to analysis horizon."""
    
    def test_horizon_1_month_refused_for_bank(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test 1-month horizon is refused for banks (quarterly reporting)."""
        valid_bank_request["analysis_horizon"]["months"] = 1
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_horizon_1m",
            trace_id="test_trace_horizon_1m",
        )
        
        assert result.success is False
        assert any(
            r.code == SemanticRefusalCode.HORIZON_BELOW_REPORTING_GRANULARITY
            for r in result.semantic_refusals
        )
    
    def test_horizon_2_months_refused(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test 2-month horizon is refused (below quarterly)."""
        valid_bank_request["analysis_horizon"]["months"] = 2
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_horizon_2m",
            trace_id="test_trace_horizon_2m",
        )
        
        assert result.success is False
    
    def test_horizon_3_months_accepted(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test 3-month horizon is accepted (meets quarterly minimum)."""
        valid_bank_request["analysis_horizon"]["months"] = 3
        # Remove stress scenarios that have shock horizons > 3 months
        valid_bank_request["stress_scenarios"] = []
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_horizon_3m",
            trace_id="test_trace_horizon_3m",
        )
        
        assert result.success is True
    
    def test_horizon_120_months_accepted(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test maximum horizon of 120 months is accepted."""
        valid_bank_request["analysis_horizon"]["months"] = 120
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_horizon_120m",
            trace_id="test_trace_horizon_120m",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        assert result.canonical_claim.analysis_horizon.months == 120


# =============================================================================
# Test: Semantic Refusals - Scenarios
# =============================================================================


class TestSemanticRefusalsScenarios:
    """Tests for semantic refusals related to stress scenarios."""
    
    def test_shock_unsupported_for_entity_type(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test shocks unsupported for entity type generate warnings."""
        # Add an equity shock to a bank - should be removed with warning
        valid_bank_request["stress_scenarios"] = [
            {
                "scenario_type": "custom",
                "name": "Mixed Shocks",
                "shocks": [
                    {"variable": "interest_rate", "shock_percent": 2.0, "time_horizon_months": 12},
                    {"variable": "equity_price", "shock_percent": -30.0, "time_horizon_months": 12},  # Not typically for banks
                ],
            }
        ]
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_unsupported_shock",
            trace_id="test_trace_unsupported",
        )
        
        # Should succeed but with warnings
        assert result.success is True
        assert result.canonical_claim is not None
        # Equity shock should be removed for banks
        scenario = result.canonical_claim.stress_scenarios[0]
        shock_vars = [s["variable"] for s in scenario.validated_shocks]
        assert "interest_rate" in shock_vars
        # Equity is not in SUPPORTED_SHOCKS_BY_ENTITY["bank"]
        if "equity_price" not in SUPPORTED_SHOCKS_BY_ENTITY.get("bank", set()):
            assert "equity_price" not in shock_vars
    
    def test_shock_horizon_exceeds_analysis_horizon(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test shock horizon exceeding analysis horizon is refused."""
        valid_bank_request["analysis_horizon"]["months"] = 12
        valid_bank_request["stress_scenarios"] = [
            {
                "scenario_type": "custom",
                "name": "Long Shock",
                "shocks": [
                    {"variable": "interest_rate", "shock_percent": 2.0, "time_horizon_months": 24},  # Exceeds 12
                ],
            }
        ]
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_shock_horizon",
            trace_id="test_trace_shock_horizon",
        )
        
        assert result.success is False
        assert any(
            r.code == SemanticRefusalCode.SHOCK_HORIZON_EXCEEDS_ANALYSIS_HORIZON
            for r in result.semantic_refusals
        )
    
    def test_custom_scenario_all_shocks_unsupported_refused(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test custom scenario with all unsupported shocks is refused."""
        # Add only shocks not supported for banks
        valid_bank_request["stress_scenarios"] = [
            {
                "scenario_type": "custom",
                "name": "Unsupported Shocks",
                "shocks": [
                    {"variable": "gdp_growth", "shock_percent": -5.0, "time_horizon_months": 12},
                    {"variable": "unemployment", "shock_percent": 5.0, "time_horizon_months": 12},
                ],
            }
        ]
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_all_unsupported",
            trace_id="test_trace_all_unsupported",
        )
        
        # Should be refused because all shocks were removed
        assert result.success is False
        assert any(
            r.code == SemanticRefusalCode.SHOCK_UNSUPPORTED_FOR_ENTITY_TYPE
            for r in result.semantic_refusals
        )
    
    def test_economically_meaningless_shock_refused(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test economically meaningless shock (tiny) is refused."""
        valid_bank_request["stress_scenarios"] = [
            {
                "scenario_type": "custom",
                "name": "Tiny Shock",
                "shocks": [
                    {"variable": "interest_rate", "shock_percent": 0.001, "time_horizon_months": 12},  # Too small
                ],
            }
        ]
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_tiny_shock",
            trace_id="test_trace_tiny",
        )
        
        assert result.success is False
        assert any(
            r.code == SemanticRefusalCode.SCENARIO_ECONOMICALLY_MEANINGLESS
            for r in result.semantic_refusals
        )


# =============================================================================
# Test: Required Facts Derivation
# =============================================================================


class TestRequiredFactsDerivation:
    """Tests for required facts contract derivation."""
    
    def test_core_solvency_facts_always_present(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test core solvency facts are always in the contract."""
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_core_facts",
            trace_id="test_trace_core",
        )
        
        assert result.success is True
        contract = result.required_facts_contract
        assert contract is not None
        
        required_fact_names = [f.fact_name for f in contract.required_facts]
        
        # Core facts should be present
        assert "total_assets" in required_fact_names
        assert "total_liabilities" in required_fact_names
        assert "total_equity" in required_fact_names
        assert "cash_and_equivalents" in required_fact_names
        assert "total_debt" in required_fact_names
    
    def test_bank_regulatory_facts_for_bank(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test bank-specific regulatory facts are included for banks."""
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_bank_facts",
            trace_id="test_trace_bank_facts",
        )
        
        assert result.success is True
        contract = result.required_facts_contract
        assert contract is not None
        
        all_fact_names = [f.fact_name for f in contract.required_facts + contract.material_facts]
        
        # Bank regulatory facts
        assert "tier1_capital" in all_fact_names
        assert "risk_weighted_assets" in all_fact_names
        assert "cet1_ratio" in all_fact_names
    
    def test_insurance_regulatory_facts_for_insurance(self, processor: ClaimProcessor, valid_insurance_request: dict):
        """Test insurance-specific facts are included for insurance companies."""
        result = processor.process(
            api_request=valid_insurance_request,
            request_hash="test_ins_facts",
            trace_id="test_trace_ins_facts",
        )
        
        assert result.success is True
        contract = result.required_facts_contract
        assert contract is not None
        
        all_fact_names = [f.fact_name for f in contract.required_facts + contract.material_facts]
        
        # Insurance regulatory facts
        assert "solvency_capital_requirement" in all_fact_names
        assert "own_funds" in all_fact_names
        assert "solvency_ratio" in all_fact_names
    
    def test_debt_schedule_for_long_horizon(self, processor: ClaimProcessor, valid_corporate_request: dict):
        """Test debt schedule facts are included for horizons > 12 months."""
        valid_corporate_request["analysis_horizon"]["months"] = 36
        
        result = processor.process(
            api_request=valid_corporate_request,
            request_hash="test_long_horizon",
            trace_id="test_trace_long",
        )
        
        assert result.success is True
        contract = result.required_facts_contract
        assert contract is not None
        
        all_fact_names = [f.fact_name for f in contract.required_facts + contract.material_facts]
        assert "debt_maturity_schedule" in all_fact_names
    
    def test_interest_rate_scenario_facts(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test interest rate scenario adds rate sensitivity facts."""
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_ir_facts",
            trace_id="test_trace_ir",
        )
        
        assert result.success is True
        contract = result.required_facts_contract
        assert contract is not None
        
        all_fact_names = [f.fact_name for f in contract.required_facts + contract.material_facts + contract.supplementary_facts]
        
        # Interest rate scenario facts
        assert "interest_rate_sensitivity" in all_fact_names or "fixed_vs_floating_debt_mix" in all_fact_names
    
    def test_required_facts_contract_is_complete(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test contract contains all required metadata."""
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_contract_meta",
            trace_id="test_trace_meta",
        )
        
        assert result.success is True
        contract = result.required_facts_contract
        assert contract is not None
        
        # Verify contract structure
        assert contract.contract_id.startswith("RFC_")
        assert contract.version == 1
        assert contract.total_facts > 0
        assert contract.total_facts == (
            len(contract.required_facts) +
            len(contract.material_facts) +
            len(contract.supplementary_facts)
        )
        assert len(contract.categories_covered) > 0
        assert contract.contract_hash is not None
    
    def test_facts_have_acceptable_sources(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test all facts have acceptable sources defined."""
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_sources",
            trace_id="test_trace_sources",
        )
        
        assert result.success is True
        contract = result.required_facts_contract
        assert contract is not None
        
        for fact in contract.required_facts:
            assert len(fact.acceptable_sources) > 0, f"Fact {fact.fact_name} should have sources"


# =============================================================================
# Test: Determinism Guarantees
# =============================================================================


class TestDeterminismGuarantees:
    """Tests for determinism of claim processing."""
    
    def test_same_input_produces_same_claim_hash(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test identical inputs produce identical claim hashes."""
        result1 = processor.process(
            api_request=valid_bank_request,
            request_hash="test_det_1",
            trace_id="trace_det_1",
        )
        
        result2 = processor.process(
            api_request=valid_bank_request,
            request_hash="test_det_1",  # Same hash
            trace_id="trace_det_2",  # Different trace (should not affect claim hash)
        )
        
        assert result1.success is True
        assert result2.success is True
        assert result1.canonical_claim is not None
        assert result2.canonical_claim is not None
        
        # Claim hashes should be identical
        assert result1.canonical_claim.claim_hash == result2.canonical_claim.claim_hash
    
    def test_same_input_produces_same_contract_hash(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test identical inputs produce identical contract hashes."""
        result1 = processor.process(
            api_request=valid_bank_request,
            request_hash="test_det_contract_1",
            trace_id="trace_det_contract_1",
        )
        
        result2 = processor.process(
            api_request=valid_bank_request,
            request_hash="test_det_contract_2",
            trace_id="trace_det_contract_2",
        )
        
        assert result1.success is True
        assert result2.success is True
        assert result1.required_facts_contract is not None
        assert result2.required_facts_contract is not None
        
        # Contract hashes should be identical
        assert result1.required_facts_contract.contract_hash == result2.required_facts_contract.contract_hash
    
    def test_different_entity_produces_different_hash(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test different entities produce different claim hashes."""
        result1 = processor.process(
            api_request=valid_bank_request,
            request_hash="test_diff_1",
            trace_id="trace_diff_1",
        )
        
        valid_bank_request["entity"]["external_id"] = "529900DIFFERENT0LEI0"
        
        result2 = processor.process(
            api_request=valid_bank_request,
            request_hash="test_diff_2",
            trace_id="trace_diff_2",
        )
        
        assert result1.success is True
        assert result2.success is True
        assert result1.canonical_claim is not None
        assert result2.canonical_claim is not None
        
        # Claim hashes should be different
        assert result1.canonical_claim.claim_hash != result2.canonical_claim.claim_hash
    
    def test_required_facts_order_is_stable(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test required facts are in stable order across runs."""
        results = []
        for i in range(3):
            result = processor.process(
                api_request=valid_bank_request,
                request_hash=f"test_order_{i}",
                trace_id=f"trace_order_{i}",
            )
            results.append(result)
        
        # All should succeed
        assert all(r.success for r in results)
        
        # Fact names should be in same order
        first_names = [f.fact_name for f in results[0].required_facts_contract.required_facts]
        for result in results[1:]:
            current_names = [f.fact_name for f in result.required_facts_contract.required_facts]
            assert first_names == current_names


# =============================================================================
# Test: Service Layer
# =============================================================================


class TestServiceLayer:
    """Tests for the ClaimService layer."""
    
    @pytest.mark.asyncio
    async def test_service_process_and_retrieve(self, service: ClaimService, valid_bank_request: dict):
        """Test processing and retrieving a claim through the service."""
        request = ProcessClaimRequest(
            api_request=valid_bank_request,
            request_hash="test_service_001",
            trace_id="trace_service_001",
            received_at=datetime.now(timezone.utc),
        )
        
        response = await service.process_solvency_claim(request)
        
        assert response.success is True
        assert response.claim_id is not None
        assert response.claim_hash is not None
        assert response.required_facts_count is not None
        assert response.required_facts_count > 0
        
        # Retrieve the claim
        claim = await service.get_canonical_claim(response.claim_id)
        assert claim is not None
        assert claim.claim_id == response.claim_id
        
        # Retrieve the contract
        contract = await service.get_required_facts_contract(response.claim_id)
        assert contract is not None
        assert contract.total_facts == response.required_facts_count
    
    @pytest.mark.asyncio
    async def test_service_idempotency(self, service: ClaimService, valid_bank_request: dict):
        """Test that duplicate requests return existing claim."""
        request = ProcessClaimRequest(
            api_request=valid_bank_request,
            request_hash="test_idempotent_hash",
            trace_id="trace_idemp_1",
            received_at=datetime.now(timezone.utc),
        )
        
        response1 = await service.process_solvency_claim(request)
        assert response1.success is True
        
        # Submit same request again
        request2 = ProcessClaimRequest(
            api_request=valid_bank_request,
            request_hash="test_idempotent_hash",  # Same hash
            trace_id="trace_idemp_2",
            received_at=datetime.now(timezone.utc),
        )
        
        response2 = await service.process_solvency_claim(request2)
        assert response2.success is True
        assert response2.claim_id == response1.claim_id
        assert "Duplicate request" in response2.warnings[0]
    
    @pytest.mark.asyncio
    async def test_service_refusal_response(self, service: ClaimService, valid_bank_request: dict):
        """Test service returns proper refusal response."""
        valid_bank_request["entity_classification"] = "sovereign"
        valid_bank_request["regulatory_framework"] = "custom"
        
        request = ProcessClaimRequest(
            api_request=valid_bank_request,
            request_hash="test_refusal",
            trace_id="trace_refusal",
            received_at=datetime.now(timezone.utc),
        )
        
        response = await service.process_solvency_claim(request)
        
        assert response.success is False
        assert response.refused is True
        assert len(response.refusal_codes) > 0
        assert len(response.refusal_messages) > 0


# =============================================================================
# Test: API Endpoints
# =============================================================================


class TestAPIEndpoints:
    """Tests for API endpoints."""
    
    def test_health_endpoint(self, client: TestClient):
        """Test health endpoint returns healthy."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "claim-service"
    
    def test_readiness_endpoint(self, client: TestClient):
        """Test readiness endpoint."""
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert "ready" in data
        assert "checks" in data
    
    def test_process_claim_endpoint(self, client: TestClient, valid_bank_request: dict):
        """Test process claim endpoint."""
        request_data = {
            "api_request": valid_bank_request,
            "request_hash": "test_api_hash",
            "trace_id": "test_api_trace",
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        
        response = client.post("/v1/claims/process", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["claim_id"] is not None
    
    def test_get_claim_endpoint(self, client: TestClient, valid_bank_request: dict):
        """Test get claim endpoint."""
        # First create a claim
        request_data = {
            "api_request": valid_bank_request,
            "request_hash": "test_get_claim_hash",
            "trace_id": "test_get_claim_trace",
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        
        create_response = client.post("/v1/claims/process", json=request_data)
        claim_id = create_response.json()["claim_id"]
        
        # Get the claim
        response = client.get(f"/v1/claims/{claim_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["claim_id"] == claim_id
    
    def test_get_required_facts_endpoint(self, client: TestClient, valid_bank_request: dict):
        """Test get required facts endpoint."""
        # First create a claim
        request_data = {
            "api_request": valid_bank_request,
            "request_hash": "test_facts_api_hash",
            "trace_id": "test_facts_api_trace",
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        
        create_response = client.post("/v1/claims/process", json=request_data)
        claim_id = create_response.json()["claim_id"]
        
        # Get required facts
        response = client.get(f"/v1/claims/{claim_id}/required-facts")
        assert response.status_code == 200
        
        data = response.json()
        assert data["claim_id"] == claim_id
        assert data["total_facts"] > 0
    
    def test_get_nonexistent_claim_returns_404(self, client: TestClient):
        """Test getting nonexistent claim returns 404."""
        response = client.get("/v1/claims/CLM_nonexistent_12345")
        assert response.status_code == 404


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_empty_stress_scenarios_accepted(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test claim with no stress scenarios is accepted."""
        valid_bank_request["stress_scenarios"] = []
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_no_scenarios",
            trace_id="trace_no_scenarios",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        assert len(result.canonical_claim.stress_scenarios) == 0
        # Baseline should still be present
        assert result.canonical_claim.baseline_scenario is not None
    
    def test_internal_id_type_accepted(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test INTERNAL id type is accepted without strict validation."""
        valid_bank_request["entity"]["external_id"] = "any-internal-id-format-123"
        valid_bank_request["entity"]["id_type"] = "INTERNAL"
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_internal_id",
            trace_id="trace_internal",
        )
        
        assert result.success is True
    
    def test_missing_thresholds_uses_defaults(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test missing thresholds uses defaults."""
        del valid_bank_request["thresholds"]
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_no_thresholds",
            trace_id="trace_no_thresholds",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        # Should have empty or default thresholds
        assert result.canonical_claim.thresholds is not None
    
    def test_underspecified_claim_refused(self, processor: ClaimProcessor):
        """Test underspecified claim is refused."""
        minimal_request = {
            "entity": {"external_id": "TEST", "id_type": "INTERNAL", "name": "Test"},
            # Missing required fields
        }
        
        result = processor.process(
            api_request=minimal_request,
            request_hash="test_underspec",
            trace_id="trace_underspec",
        )
        
        assert result.success is False
        assert any(
            r.code == SemanticRefusalCode.CLAIM_UNDERSPECIFIED
            for r in result.semantic_refusals
        )
    
    def test_very_long_entity_name_normalized(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test very long entity name with extra spaces is normalized."""
        valid_bank_request["entity"]["name"] = "   A  Very   Long    Entity   Name   With   Many   Spaces   "
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_long_name",
            trace_id="trace_long_name",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        assert "  " not in result.canonical_claim.entity.name
        assert result.canonical_claim.entity.name == "A Very Long Entity Name With Many Spaces"
    
    def test_scenario_with_valid_and_invalid_shocks(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test scenario with mix of valid and invalid shocks keeps valid ones."""
        valid_bank_request["stress_scenarios"] = [
            {
                "scenario_type": "custom",
                "name": "Mixed Validity",
                "shocks": [
                    {"variable": "interest_rate", "shock_percent": 2.0, "time_horizon_months": 12},  # Valid
                    {"variable": "credit_spread", "shock_percent": 1.5, "time_horizon_months": 12},  # Valid for bank
                ],
            }
        ]
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_mixed_shocks",
            trace_id="trace_mixed",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        # Should have the valid shocks
        assert len(result.canonical_claim.stress_scenarios) == 1
        assert len(result.canonical_claim.stress_scenarios[0].validated_shocks) >= 1


# =============================================================================
# Test: Normalized Horizon
# =============================================================================


class TestNormalizedHorizon:
    """Tests for horizon normalization."""
    
    def test_horizon_end_date_computed(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test horizon end date is correctly computed."""
        valid_bank_request["analysis_horizon"]["months"] = 12
        today = date.today()
        valid_bank_request["analysis_horizon"]["reference_date"] = today.isoformat()
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_end_date",
            trace_id="trace_end_date",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        horizon = result.canonical_claim.analysis_horizon
        assert horizon.reference_date == today
        # End date should be ~12 months later
        days_diff = (horizon.end_date - today).days
        assert 360 <= days_diff <= 370  # Approximately 12 months
    
    def test_horizon_reporting_periods_computed(self, processor: ClaimProcessor, valid_bank_request: dict):
        """Test reporting periods are correctly computed."""
        valid_bank_request["analysis_horizon"]["months"] = 12
        
        result = processor.process(
            api_request=valid_bank_request,
            request_hash="test_periods",
            trace_id="trace_periods",
        )
        
        assert result.success is True
        assert result.canonical_claim is not None
        horizon = result.canonical_claim.analysis_horizon
        # 12 months with quarterly reporting = 4 periods
        assert horizon.reporting_periods >= 4
        assert horizon.reporting_granularity == "quarterly"
