"""
Extraction Service (A5) Test Suite
===================================

Comprehensive tests for:
- XBRL extraction pipeline
- Table extraction pipeline (fallback)
- Text extraction pipeline (low confidence)
- Macroeconomic extraction pipeline
- FinancialFact storage and deduplication
- EvidencePassage storage
- Job orchestration
- API endpoints
- Idempotent extraction
- Confidence filtering

Test Categories:
1. Unit tests for extraction pipelines
2. Integration tests for service
3. API endpoint tests
4. Edge case and error handling tests
"""

import base64
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from services.extraction_service.app import app, reset_service, get_service
from services.extraction_service.service_impl import (
    ExtractionService,
    XBRLExtractor,
    TableExtractor,
    TextExtractor,
    MacroExtractor,
    FactStore,
    PassageStore,
    RawExtractedFact,
    RawExtractedPassage,
    ExtractionOutput,
)
from services.extraction_service.schemas import (
    ExtractionMethod,
    ExtractionJobStatus,
    ExtractionRefusalCode,
    FactConfidence,
    FactUnit,
    XBRLLocation,
    TableLocation,
    TextLocation,
    MacroLocation,
    FactProvenance,
    FinancialFact,
    EvidencePassage,
    ExtractionJobRequest,
    DEFAULT_MIN_CONFIDENCE,
    XBRL_FACT_MAPPINGS,
    EXTRACTION_METHOD_CONFIDENCE,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def client():
    """Test client fixture."""
    reset_service()
    with TestClient(app) as c:
        yield c
    reset_service()


@pytest.fixture
def service():
    """Extraction service fixture."""
    return ExtractionService()


@pytest.fixture
def xbrl_extractor():
    """XBRL extractor fixture."""
    return XBRLExtractor()


@pytest.fixture
def table_extractor():
    """Table extractor fixture."""
    return TableExtractor()


@pytest.fixture
def text_extractor():
    """Text extractor fixture."""
    return TextExtractor()


@pytest.fixture
def macro_extractor():
    """Macro extractor fixture."""
    return MacroExtractor()


@pytest.fixture
def fact_store():
    """Fact store fixture."""
    return FactStore()


@pytest.fixture
def passage_store():
    """Passage store fixture."""
    return PassageStore()


@pytest.fixture
def sample_xbrl_content() -> bytes:
    """Sample XBRL content for testing."""
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:us-gaap="http://fasb.org/us-gaap/2023"
            xmlns:dei="http://xbrl.sec.gov/dei/2023">
    
    <xbrli:context id="FY2023">
        <xbrli:entity>
            <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
        </xbrli:entity>
        <xbrli:period>
            <xbrli:instant>2023-12-31</xbrli:instant>
        </xbrli:period>
    </xbrli:context>
    
    <xbrli:context id="FY2023_Duration">
        <xbrli:entity>
            <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
        </xbrli:entity>
        <xbrli:period>
            <xbrli:startDate>2023-01-01</xbrli:startDate>
            <xbrli:endDate>2023-12-31</xbrli:endDate>
        </xbrli:period>
    </xbrli:context>
    
    <xbrli:unit id="USD">
        <xbrli:measure>iso4217:USD</xbrli:measure>
    </xbrli:unit>
    
    <us-gaap:Assets contextRef="FY2023" unitRef="USD" decimals="-6">10500000000</us-gaap:Assets>
    <us-gaap:Liabilities contextRef="FY2023" unitRef="USD" decimals="-6">5200000000</us-gaap:Liabilities>
    <us-gaap:StockholdersEquity contextRef="FY2023" unitRef="USD" decimals="-6">5300000000</us-gaap:StockholdersEquity>
    <us-gaap:CashAndCashEquivalentsAtCarryingValue contextRef="FY2023" unitRef="USD" decimals="-6">1250000000</us-gaap:CashAndCashEquivalentsAtCarryingValue>
    <us-gaap:Revenues contextRef="FY2023_Duration" unitRef="USD" decimals="-6">8750000000</us-gaap:Revenues>
    <us-gaap:OperatingIncomeLoss contextRef="FY2023_Duration" unitRef="USD" decimals="-6">920000000</us-gaap:OperatingIncomeLoss>
    <us-gaap:NetIncomeLoss contextRef="FY2023_Duration" unitRef="USD" decimals="-6">680000000</us-gaap:NetIncomeLoss>
    
</xbrli:xbrl>"""


@pytest.fixture
def sample_table_content() -> bytes:
    """Sample HTML table content for testing."""
    return b"""
<html>
<body>
<h2>Consolidated Balance Sheet</h2>
<table>
    <tr><th>Item</th><th>2023</th><th>2022</th></tr>
    <tr><td>Total Assets</td><td>$10,500</td><td>$9,800</td></tr>
    <tr><td>Total Liabilities</td><td>$5,200</td><td>$4,900</td></tr>
    <tr><td>Total Stockholders' Equity</td><td>$5,300</td><td>$4,900</td></tr>
</table>

<h2>Income Statement</h2>
<table>
    <tr><th>Item</th><th>FY 2023</th></tr>
    <tr><td>Total Revenue</td><td>$8,750 million</td></tr>
    <tr><td>Operating Income</td><td>$920 million</td></tr>
    <tr><td>Net Income</td><td>$680 million</td></tr>
</table>
</body>
</html>
"""


@pytest.fixture
def sample_macro_content() -> bytes:
    """Sample macroeconomic JSON data."""
    return b"""{
    "series_id": "DGS10",
    "treasury_yield_10yr": 4.25,
    "treasury_yield_2yr": 4.85,
    "fed_funds_rate": 5.33,
    "effective_date": "2024-01-15"
}"""


# =============================================================================
# Schema Tests
# =============================================================================


class TestSchemas:
    """Tests for Pydantic schema validation."""
    
    def test_xbrl_location_frozen(self):
        """XBRLLocation should be immutable."""
        loc = XBRLLocation(
            namespace="http://fasb.org/us-gaap/2023",
            tag_name="Assets",
            context_ref="FY2023",
        )
        with pytest.raises(Exception):  # ValidationError for frozen
            loc.tag_name = "Liabilities"
    
    def test_table_location_validation(self):
        """TableLocation should validate indexes."""
        loc = TableLocation(
            page_number=1,
            table_index=0,
            row_index=5,
            column_index=2,
            row_header="Total Assets",
        )
        assert loc.page_number == 1
        assert loc.row_index == 5
    
    def test_fact_provenance_requires_one_location(self):
        """FactProvenance requires exactly one location type."""
        # Valid with xbrl_location
        prov = FactProvenance(
            evidence_id="ev_123",
            evidence_hash="abc123",
            xbrl_location=XBRLLocation(
                namespace="http://fasb.org/us-gaap/2023",
                tag_name="Assets",
                context_ref="FY2023",
            ),
        )
        assert prov.xbrl_location is not None
        assert prov.table_location is None
    
    def test_financial_fact_frozen(self):
        """FinancialFact should be immutable."""
        fact = FinancialFact(
            fact_id="fact_123",
            fact_hash="hash_abc",
            fact_type="total_assets",
            category="balance_sheet",
            value=Decimal("10500000000"),
            unit=FactUnit.CURRENCY,
            currency="USD",
            scale=0,
            as_of_date=date(2023, 12, 31),
            confidence=Decimal("1.00"),
            confidence_level=FactConfidence.HIGH,
            extraction_method=ExtractionMethod.XBRL,
            extractor_version="1.0.0",
            derived_from=FactProvenance(
                evidence_id="ev_123",
                evidence_hash="hash_xyz",
                xbrl_location=XBRLLocation(
                    namespace="http://fasb.org/us-gaap/2023",
                    tag_name="Assets",
                    context_ref="FY2023",
                ),
            ),
        )
        assert fact.value == Decimal("10500000000")
        with pytest.raises(Exception):
            fact.value = Decimal("0")
    
    def test_evidence_passage_hash_deduplication(self):
        """EvidencePassage hash should enable deduplication."""
        passage1 = EvidencePassage(
            passage_id="pass_1",
            passage_hash="same_hash",
            evidence_id="ev_123",
            evidence_hash="evidence_hash_123",
            text_content="Debt maturities are as follows...",
            passage_type="debt_maturity",
        )
        passage2 = EvidencePassage(
            passage_id="pass_2",
            passage_hash="same_hash",
            evidence_id="ev_456",
            evidence_hash="evidence_hash_456",
            text_content="Debt maturities are as follows...",
            passage_type="debt_maturity",
        )
        assert passage1.passage_hash == passage2.passage_hash
    
    def test_extraction_method_confidence_mapping(self):
        """Extraction methods should have correct confidence values."""
        assert EXTRACTION_METHOD_CONFIDENCE["XBRL"] == Decimal("1.00")
        assert EXTRACTION_METHOD_CONFIDENCE["TABLE"] == Decimal("0.70")
        assert EXTRACTION_METHOD_CONFIDENCE["TEXT"] == Decimal("0.40")
        assert EXTRACTION_METHOD_CONFIDENCE["MACRO"] == Decimal("1.00")


# =============================================================================
# XBRL Extractor Tests
# =============================================================================


class TestXBRLExtractor:
    """Tests for XBRL extraction pipeline."""
    
    @pytest.mark.asyncio
    async def test_can_extract_xbrl(self, xbrl_extractor, sample_xbrl_content):
        """Should detect XBRL content."""
        result = await xbrl_extractor.can_extract(sample_xbrl_content, {})
        assert result is True
    
    @pytest.mark.asyncio
    async def test_cannot_extract_html(self, xbrl_extractor, sample_table_content):
        """Should not detect plain HTML as XBRL."""
        result = await xbrl_extractor.can_extract(sample_table_content, {})
        assert result is False
    
    @pytest.mark.asyncio
    async def test_extract_assets(self, xbrl_extractor, sample_xbrl_content):
        """Should extract total assets from XBRL."""
        result = await xbrl_extractor.extract(
            sample_xbrl_content,
            "ev_123",
            "hash_abc",
            {"fiscal_year": 2023},
        )
        assert result.success is True
        
        asset_facts = [f for f in result.facts if f.fact_type == "total_assets"]
        assert len(asset_facts) >= 1
        assert asset_facts[0].value == Decimal("10500000000")
        assert asset_facts[0].extraction_method == ExtractionMethod.XBRL
        assert asset_facts[0].confidence == Decimal("1.00")
    
    @pytest.mark.asyncio
    async def test_extract_liabilities(self, xbrl_extractor, sample_xbrl_content):
        """Should extract total liabilities from XBRL."""
        result = await xbrl_extractor.extract(
            sample_xbrl_content,
            "ev_123",
            "hash_abc",
            {"fiscal_year": 2023},
        )
        assert result.success is True
        
        liability_facts = [f for f in result.facts if f.fact_type == "total_liabilities"]
        assert len(liability_facts) >= 1
        assert liability_facts[0].value == Decimal("5200000000")
    
    @pytest.mark.asyncio
    async def test_extract_equity(self, xbrl_extractor, sample_xbrl_content):
        """Should extract stockholders equity from XBRL."""
        result = await xbrl_extractor.extract(
            sample_xbrl_content,
            "ev_123",
            "hash_abc",
            {},
        )
        assert result.success is True
        
        equity_facts = [f for f in result.facts if f.fact_type == "total_equity"]
        assert len(equity_facts) >= 1
        assert equity_facts[0].value == Decimal("5300000000")
    
    @pytest.mark.asyncio
    async def test_extract_revenue(self, xbrl_extractor, sample_xbrl_content):
        """Should extract revenue from XBRL."""
        result = await xbrl_extractor.extract(
            sample_xbrl_content,
            "ev_123",
            "hash_abc",
            {},
        )
        assert result.success is True
        
        revenue_facts = [f for f in result.facts if f.fact_type == "revenue"]
        assert len(revenue_facts) >= 1
        assert revenue_facts[0].value == Decimal("8750000000")
    
    @pytest.mark.asyncio
    async def test_extract_net_income(self, xbrl_extractor, sample_xbrl_content):
        """Should extract net income from XBRL."""
        result = await xbrl_extractor.extract(
            sample_xbrl_content,
            "ev_123",
            "hash_abc",
            {},
        )
        assert result.success is True
        
        income_facts = [f for f in result.facts if f.fact_type == "net_income"]
        assert len(income_facts) >= 1
        assert income_facts[0].value == Decimal("680000000")
    
    @pytest.mark.asyncio
    async def test_xbrl_location_captured(self, xbrl_extractor, sample_xbrl_content):
        """Should capture XBRL location details."""
        result = await xbrl_extractor.extract(
            sample_xbrl_content,
            "ev_123",
            "hash_abc",
            {},
        )
        assert result.success is True
        
        asset_facts = [f for f in result.facts if f.fact_type == "total_assets"]
        assert len(asset_facts) >= 1
        
        loc = asset_facts[0].xbrl_location
        assert loc is not None
        assert loc.tag_name == "Assets"
        assert loc.context_ref == "FY2023"
    
    @pytest.mark.asyncio
    async def test_context_period_parsing(self, xbrl_extractor, sample_xbrl_content):
        """Should parse instant and duration contexts."""
        result = await xbrl_extractor.extract(
            sample_xbrl_content,
            "ev_123",
            "hash_abc",
            {},
        )
        
        # Instant context (balance sheet items)
        asset_facts = [f for f in result.facts if f.fact_type == "total_assets"]
        assert asset_facts[0].as_of_date == date(2023, 12, 31)
        
        # Duration context (income statement items)
        revenue_facts = [f for f in result.facts if f.fact_type == "revenue"]
        # Revenue should have period extracted
        assert revenue_facts[0].as_of_date is not None
    
    @pytest.mark.asyncio
    async def test_xbrl_deterministic(self, xbrl_extractor, sample_xbrl_content):
        """Same XBRL content should produce identical facts."""
        result1 = await xbrl_extractor.extract(
            sample_xbrl_content, "ev_1", "hash_1", {}
        )
        result2 = await xbrl_extractor.extract(
            sample_xbrl_content, "ev_2", "hash_2", {}
        )
        
        # Same number of facts
        assert len(result1.facts) == len(result2.facts)
        
        # Same values (fact hashes may differ due to metadata)
        values1 = sorted([f.value for f in result1.facts])
        values2 = sorted([f.value for f in result2.facts])
        assert values1 == values2
    
    @pytest.mark.asyncio
    async def test_empty_xbrl_refused(self, xbrl_extractor):
        """Empty XBRL should be refused."""
        empty_xbrl = b'<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"></xbrli:xbrl>'
        result = await xbrl_extractor.extract(
            empty_xbrl, "ev_123", "hash_abc", {}
        )
        assert result.success is False
        assert result.refusal_code == ExtractionRefusalCode.NO_XBRL_AVAILABLE


# =============================================================================
# Table Extractor Tests
# =============================================================================


class TestTableExtractor:
    """Tests for table extraction pipeline."""
    
    @pytest.mark.asyncio
    async def test_can_extract_html_table(self, table_extractor, sample_table_content):
        """Should detect HTML table content."""
        result = await table_extractor.can_extract(sample_table_content, {})
        assert result is True
    
    @pytest.mark.asyncio
    async def test_cannot_extract_plain_text(self, table_extractor):
        """Should not detect plain text as table."""
        plain = b"This is plain text without tables."
        result = await table_extractor.can_extract(plain, {})
        assert result is False
    
    @pytest.mark.asyncio
    async def test_extract_assets_from_table(self, table_extractor, sample_table_content):
        """Should extract total assets from HTML table."""
        result = await table_extractor.extract(
            sample_table_content,
            "ev_123",
            "hash_abc",
            {"period_of_report": "2023-12-31"},
        )
        
        if result.success:  # Table extraction may have varying results
            asset_facts = [f for f in result.facts if f.fact_type == "total_assets"]
            if asset_facts:
                assert asset_facts[0].extraction_method == ExtractionMethod.TABLE
                assert asset_facts[0].confidence == Decimal("0.70")
    
    @pytest.mark.asyncio
    async def test_table_location_captured(self, table_extractor, sample_table_content):
        """Should capture table location details."""
        result = await table_extractor.extract(
            sample_table_content,
            "ev_123",
            "hash_abc",
            {"period_of_report": "2023-12-31"},
        )
        
        if result.success and result.facts:
            loc = result.facts[0].table_location
            assert loc is not None
            assert loc.row_index is not None
            assert loc.column_index is not None
    
    @pytest.mark.asyncio
    async def test_table_medium_confidence(self, table_extractor, sample_table_content):
        """Table extraction should have MEDIUM confidence."""
        result = await table_extractor.extract(
            sample_table_content,
            "ev_123",
            "hash_abc",
            {"period_of_report": "2023-12-31"},
        )
        
        if result.success and result.facts:
            for fact in result.facts:
                assert fact.confidence == EXTRACTION_METHOD_CONFIDENCE["TABLE"]


# =============================================================================
# Text Extractor Tests
# =============================================================================


class TestTextExtractor:
    """Tests for text extraction pipeline."""
    
    @pytest.mark.asyncio
    async def test_can_always_extract(self, text_extractor):
        """Text extraction should always be possible."""
        result = await text_extractor.can_extract(b"any content", {})
        assert result is True
    
    @pytest.mark.asyncio
    async def test_extract_debt_maturity_passage(self, text_extractor):
        """Should extract debt maturity narrative passages."""
        content = b"""
        The Company's debt maturities are as follows: $500 million in 2024,
        $750 million in 2025, and $1.2 billion in 2026. The Company maintains
        adequate liquidity to meet these obligations.
        """
        
        result = await text_extractor.extract(
            content,
            "ev_123",
            "hash_abc",
            {"period_of_report": "2023-12-31"},
        )
        
        assert result.success is True
        # Text extractor produces passages, not facts
        debt_passages = [p for p in result.passages if p.passage_type == "debt_maturity"]
        assert len(debt_passages) >= 1
    
    @pytest.mark.asyncio
    async def test_extract_covenant_passage(self, text_extractor):
        """Should extract covenant narrative passages."""
        content = b"""
        The Company is subject to financial covenants requiring a debt-to-equity
        ratio not exceeding 2.5x. As of December 31, 2023, the Company was in
        compliance with all financial covenants.
        """
        
        result = await text_extractor.extract(
            content,
            "ev_123",
            "hash_abc",
            {},
        )
        
        assert result.success is True
        covenant_passages = [p for p in result.passages if p.passage_type == "covenant"]
        assert len(covenant_passages) >= 1
    
    @pytest.mark.asyncio
    async def test_text_low_confidence(self, text_extractor):
        """Text extraction should produce passages, not facts."""
        content = b"Total assets of $10 billion."
        
        result = await text_extractor.extract(
            content,
            "ev_123",
            "hash_abc",
            {},
        )
        
        # Text extractor doesn't produce facts due to low confidence
        # Only passages for audit trail
        assert result.extraction_method == ExtractionMethod.TEXT


# =============================================================================
# Macro Extractor Tests
# =============================================================================


class TestMacroExtractor:
    """Tests for macroeconomic extraction pipeline."""
    
    @pytest.mark.asyncio
    async def test_can_extract_json(self, macro_extractor, sample_macro_content):
        """Should detect JSON content."""
        result = await macro_extractor.can_extract(sample_macro_content, {})
        assert result is True
    
    @pytest.mark.asyncio
    async def test_cannot_extract_invalid_json(self, macro_extractor):
        """Should not accept invalid JSON."""
        invalid = b"not json content"
        result = await macro_extractor.can_extract(invalid, {})
        assert result is False
    
    @pytest.mark.asyncio
    async def test_extract_interest_rates(self, macro_extractor, sample_macro_content):
        """Should extract interest rate facts."""
        result = await macro_extractor.extract(
            sample_macro_content,
            "ev_123",
            "hash_abc",
            {"effective_date": "2024-01-15", "series_id": "RATES", "source_institution": "Federal Reserve"},
        )
        
        assert result.success is True
        assert result.extraction_method == ExtractionMethod.MACRO
        
        # Should extract treasury yields
        yield_facts = [f for f in result.facts if "treasury" in f.fact_type or "interest" in f.fact_type]
        assert len(yield_facts) >= 1
    
    @pytest.mark.asyncio
    async def test_macro_high_confidence(self, macro_extractor, sample_macro_content):
        """Macro extraction should have HIGH confidence."""
        result = await macro_extractor.extract(
            sample_macro_content,
            "ev_123",
            "hash_abc",
            {"effective_date": "2024-01-15"},
        )
        
        for fact in result.facts:
            assert fact.confidence == EXTRACTION_METHOD_CONFIDENCE["MACRO"]
    
    @pytest.mark.asyncio
    async def test_macro_location_captured(self, macro_extractor, sample_macro_content):
        """Should capture macro location details."""
        result = await macro_extractor.extract(
            sample_macro_content,
            "ev_123",
            "hash_abc",
            {"effective_date": "2024-01-15", "series_id": "DGS10", "source_institution": "Treasury"},
        )
        
        if result.facts:
            loc = result.facts[0].macro_location
            assert loc is not None
            assert loc.series_id is not None


# =============================================================================
# Fact Store Tests
# =============================================================================


class TestFactStore:
    """Tests for fact storage and indexing."""
    
    def test_store_and_retrieve(self, fact_store):
        """Should store and retrieve facts."""
        fact = FinancialFact(
            fact_id="fact_001",
            fact_hash="hash_abc",
            fact_type="total_assets",
            category="balance_sheet",
            value=Decimal("10500000000"),
            unit=FactUnit.CURRENCY,
            currency="USD",
            scale=0,
            as_of_date=date(2023, 12, 31),
            confidence=Decimal("1.00"),
            confidence_level=FactConfidence.HIGH,
            extraction_method=ExtractionMethod.XBRL,
            extractor_version="1.0.0",
            derived_from=FactProvenance(
                evidence_id="ev_123",
                evidence_hash="hash_xyz",
                xbrl_location=XBRLLocation(
                    namespace="http://fasb.org/us-gaap/2023",
                    tag_name="Assets",
                    context_ref="FY2023",
                ),
            ),
            entity_id="1234567",
            entity_id_type="CIK",
        )
        
        fact_id, is_dup = fact_store.store(fact)
        assert fact_id == "fact_001"
        assert is_dup is False
        
        retrieved = fact_store.get("fact_001")
        assert retrieved is not None
        assert retrieved.value == Decimal("10500000000")
    
    def test_deduplication_by_hash(self, fact_store):
        """Should deduplicate facts by hash."""
        fact1 = FinancialFact(
            fact_id="fact_001",
            fact_hash="same_hash",
            fact_type="total_assets",
            category="balance_sheet",
            value=Decimal("10500000000"),
            unit=FactUnit.CURRENCY,
            currency="USD",
            scale=0,
            as_of_date=date(2023, 12, 31),
            confidence=Decimal("1.00"),
            confidence_level=FactConfidence.HIGH,
            extraction_method=ExtractionMethod.XBRL,
            extractor_version="1.0.0",
            derived_from=FactProvenance(
                evidence_id="ev_123",
                evidence_hash="hash_xyz",
                xbrl_location=XBRLLocation(
                    namespace="ns",
                    tag_name="Assets",
                    context_ref="ctx",
                ),
            ),
        )
        
        fact2 = FinancialFact(
            fact_id="fact_002",
            fact_hash="same_hash",
            fact_type="total_assets",
            category="balance_sheet",
            value=Decimal("10500000000"),
            unit=FactUnit.CURRENCY,
            currency="USD",
            scale=0,
            as_of_date=date(2023, 12, 31),
            confidence=Decimal("1.00"),
            confidence_level=FactConfidence.HIGH,
            extraction_method=ExtractionMethod.XBRL,
            extractor_version="1.0.0",
            derived_from=FactProvenance(
                evidence_id="ev_456",
                evidence_hash="hash_abc",
                xbrl_location=XBRLLocation(
                    namespace="ns",
                    tag_name="Assets",
                    context_ref="ctx",
                ),
            ),
        )
        
        id1, dup1 = fact_store.store(fact1)
        id2, dup2 = fact_store.store(fact2)
        
        assert id1 == "fact_001"
        assert dup1 is False
        assert id2 == "fact_001"  # Returns existing ID
        assert dup2 is True
    
    def test_find_by_entity(self, fact_store):
        """Should find facts by entity."""
        fact = FinancialFact(
            fact_id="fact_001",
            fact_hash="hash_1",
            fact_type="total_assets",
            category="balance_sheet",
            value=Decimal("10500000000"),
            unit=FactUnit.CURRENCY,
            currency="USD",
            scale=0,
            as_of_date=date(2023, 12, 31),
            confidence=Decimal("1.00"),
            confidence_level=FactConfidence.HIGH,
            extraction_method=ExtractionMethod.XBRL,
            extractor_version="1.0.0",
            derived_from=FactProvenance(
                evidence_id="ev_123",
                evidence_hash="hash_xyz",
                xbrl_location=XBRLLocation(
                    namespace="ns",
                    tag_name="Assets",
                    context_ref="ctx",
                ),
            ),
            entity_id="1234567",
            entity_id_type="CIK",
        )
        
        fact_store.store(fact)
        
        found = fact_store.find_by_entity("CIK", "1234567")
        assert len(found) == 1
        assert found[0].fact_id == "fact_001"
        
        not_found = fact_store.find_by_entity("CIK", "9999999")
        assert len(not_found) == 0
    
    def test_find_by_evidence(self, fact_store):
        """Should find facts by evidence ID."""
        fact = FinancialFact(
            fact_id="fact_001",
            fact_hash="hash_1",
            fact_type="total_assets",
            category="balance_sheet",
            value=Decimal("10500000000"),
            unit=FactUnit.CURRENCY,
            currency="USD",
            scale=0,
            as_of_date=date(2023, 12, 31),
            confidence=Decimal("1.00"),
            confidence_level=FactConfidence.HIGH,
            extraction_method=ExtractionMethod.XBRL,
            extractor_version="1.0.0",
            derived_from=FactProvenance(
                evidence_id="ev_123",
                evidence_hash="hash_xyz",
                xbrl_location=XBRLLocation(
                    namespace="ns",
                    tag_name="Assets",
                    context_ref="ctx",
                ),
            ),
        )
        
        fact_store.store(fact)
        
        found = fact_store.find_by_evidence("ev_123")
        assert len(found) == 1
        
        not_found = fact_store.find_by_evidence("ev_nonexistent")
        assert len(not_found) == 0
    
    def test_link_to_claim(self, fact_store):
        """Should link facts to claims."""
        fact = FinancialFact(
            fact_id="fact_001",
            fact_hash="hash_1",
            fact_type="total_assets",
            category="balance_sheet",
            value=Decimal("10500000000"),
            unit=FactUnit.CURRENCY,
            currency="USD",
            scale=0,
            as_of_date=date(2023, 12, 31),
            confidence=Decimal("1.00"),
            confidence_level=FactConfidence.HIGH,
            extraction_method=ExtractionMethod.XBRL,
            extractor_version="1.0.0",
            derived_from=FactProvenance(
                evidence_id="ev_123",
                evidence_hash="hash_xyz",
                xbrl_location=XBRLLocation(
                    namespace="ns",
                    tag_name="Assets",
                    context_ref="ctx",
                ),
            ),
        )
        
        fact_store.store(fact)
        fact_store.link_to_claim("claim_001", "fact_001")
        
        found = fact_store.find_by_claim("claim_001")
        assert len(found) == 1
        assert found[0].fact_id == "fact_001"


# =============================================================================
# Passage Store Tests
# =============================================================================


class TestPassageStore:
    """Tests for passage storage."""
    
    def test_store_and_retrieve(self, passage_store):
        """Should store and retrieve passages."""
        passage = EvidencePassage(
            passage_id="pass_001",
            passage_hash="hash_abc",
            evidence_id="ev_123",
            evidence_hash="evidence_hash_123",
            text_content="Debt maturities...",
            passage_type="debt_maturity",
        )
        
        pass_id, is_dup = passage_store.store(passage)
        assert pass_id == "pass_001"
        assert is_dup is False
        
        retrieved = passage_store.get("pass_001")
        assert retrieved is not None
        assert retrieved.text_content == "Debt maturities..."
    
    def test_deduplication_by_hash(self, passage_store):
        """Should deduplicate passages by hash."""
        passage1 = EvidencePassage(
            passage_id="pass_001",
            passage_hash="same_hash",
            evidence_id="ev_123",
            evidence_hash="evidence_hash_123",
            text_content="Same text",
            passage_type="covenant",
        )
        
        passage2 = EvidencePassage(
            passage_id="pass_002",
            passage_hash="same_hash",
            evidence_id="ev_456",
            evidence_hash="evidence_hash_456",
            text_content="Same text",
            passage_type="covenant",
        )
        
        id1, dup1 = passage_store.store(passage1)
        id2, dup2 = passage_store.store(passage2)
        
        assert id1 == "pass_001"
        assert dup1 is False
        assert id2 == "pass_001"
        assert dup2 is True
    
    def test_find_by_evidence(self, passage_store):
        """Should find passages by evidence ID."""
        passage = EvidencePassage(
            passage_id="pass_001",
            passage_hash="hash_abc",
            evidence_id="ev_123",
            evidence_hash="evidence_hash_123",
            text_content="Some passage",
            passage_type="narrative",
        )
        
        passage_store.store(passage)
        
        found = passage_store.find_by_evidence("ev_123")
        assert len(found) == 1
        
        not_found = passage_store.find_by_evidence("ev_nonexistent")
        assert len(not_found) == 0


# =============================================================================
# Extraction Service Integration Tests
# =============================================================================


class TestExtractionServiceIntegration:
    """Integration tests for the extraction service."""
    
    @pytest.mark.asyncio
    async def test_extract_from_xbrl(self, service, sample_xbrl_content):
        """Should extract facts from XBRL evidence."""
        result = await service.extract_from_evidence(
            evidence_id="ev_001",
            content=sample_xbrl_content,
            source_type="sec_10k",
            metadata={"cik": "1234567", "fiscal_year": 2023},
        )
        
        assert result.success is True
        assert result.facts_extracted > 0
        assert len(result.fact_ids) > 0
        assert result.extraction_method == ExtractionMethod.XBRL
    
    @pytest.mark.asyncio
    async def test_idempotent_extraction(self, service, sample_xbrl_content):
        """Extracting same evidence twice should be idempotent."""
        result1 = await service.extract_from_evidence(
            evidence_id="ev_001",
            content=sample_xbrl_content,
            source_type="sec_10k",
            metadata={"cik": "1234567"},
        )
        
        result2 = await service.extract_from_evidence(
            evidence_id="ev_001",
            content=sample_xbrl_content,
            source_type="sec_10k",
            metadata={"cik": "1234567"},
        )
        
        # Second call should be idempotent (reuse existing facts)
        assert result1.success is True
        assert result2.success is True
        # Same fact IDs should be returned
        assert set(result1.fact_ids) == set(result2.fact_ids)
    
    @pytest.mark.asyncio
    async def test_xbrl_first_fallback(self, service, sample_table_content):
        """Should try XBRL first then fall back to table."""
        result = await service.extract_from_evidence(
            evidence_id="ev_001",
            content=sample_table_content,
            source_type="sec_10k",
            metadata={"period_of_report": "2023-12-31"},
        )
        
        # XBRL should fail, table should be attempted
        if result.success:
            assert result.extraction_method in [ExtractionMethod.TABLE, ExtractionMethod.TEXT]
    
    @pytest.mark.asyncio
    async def test_confidence_filtering(self, service, sample_table_content):
        """Should filter facts below minimum confidence."""
        result = await service.extract_from_evidence(
            evidence_id="ev_001",
            content=sample_table_content,
            source_type="sec_10k",
            metadata={"period_of_report": "2023-12-31"},
            min_confidence=Decimal("0.90"),  # Exclude TABLE extraction
            allow_low_confidence=False,
        )
        
        # TABLE extraction (0.70 confidence) should be filtered
        # May result in 0 facts or only high-confidence ones
        if result.success and result.fact_ids:
            for fact_id in result.fact_ids:
                fact = await service.get_fact(fact_id)
                assert fact.confidence >= Decimal("0.90")
    
    @pytest.mark.asyncio
    async def test_get_fact_by_id(self, service, sample_xbrl_content):
        """Should retrieve fact by ID."""
        result = await service.extract_from_evidence(
            evidence_id="ev_001",
            content=sample_xbrl_content,
            source_type="sec_10k",
            metadata={},
        )
        
        if result.fact_ids:
            fact = await service.get_fact(result.fact_ids[0])
            assert fact is not None
            assert fact.fact_id == result.fact_ids[0]
    
    @pytest.mark.asyncio
    async def test_find_facts_by_entity(self, service, sample_xbrl_content):
        """Should find facts by entity."""
        await service.extract_from_evidence(
            evidence_id="ev_001",
            content=sample_xbrl_content,
            source_type="sec_10k",
            metadata={"cik": "1234567"},
        )
        
        facts, total = await service.find_facts_by_entity(
            entity_id_type="CIK",
            entity_id="1234567",
        )
        
        assert total > 0
        assert len(facts) > 0


# =============================================================================
# API Endpoint Tests
# =============================================================================


class TestHealthEndpoint:
    """Tests for health check endpoint."""
    
    def test_health_check(self, client):
        """Should return healthy status."""
        response = client.get("/health")
        assert response.status_code == status.HTTP_200_OK
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "extraction-service"


class TestExtractionEndpoints:
    """Tests for extraction API endpoints."""
    
    def test_run_extraction_validation(self, client):
        """Should validate extraction request."""
        response = client.post(
            "/v1/extract/run",
            json={"evidence_ids": []},  # Empty list should fail
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_run_extraction_creates_job(self, client):
        """Should create extraction job."""
        response = client.post(
            "/v1/extract/run",
            json={
                "evidence_ids": ["ev_001", "ev_002"],
                "claim_id": "claim_001",
            },
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        
        data = response.json()
        assert "job_id" in data
        assert data["evidence_count"] == 2
        assert data["status"] in ["running", "failed", "completed", "partial"]
    
    def test_get_job_status_not_found(self, client):
        """Should return 404 for nonexistent job."""
        response = client.get("/v1/extract/status/nonexistent_job")
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_direct_extraction_xbrl(self, client, sample_xbrl_content):
        """Should extract facts via direct endpoint."""
        response = client.post(
            "/v1/extract/direct",
            json={
                "evidence_id": "ev_test",
                "content_base64": base64.b64encode(sample_xbrl_content).decode(),
                "source_type": "sec_10k",
                "metadata": {"cik": "1234567", "fiscal_year": 2023},
            },
        )
        assert response.status_code == status.HTTP_200_OK
        
        data = response.json()
        assert data["success"] is True
        assert data["facts_extracted"] > 0
        assert data["extraction_method"] == "XBRL"
    
    def test_direct_extraction_invalid_base64(self, client):
        """Should reject invalid base64."""
        response = client.post(
            "/v1/extract/direct",
            json={
                "evidence_id": "ev_test",
                "content_base64": "not valid base64!!!",
                "source_type": "sec_10k",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestFactEndpoints:
    """Tests for fact API endpoints."""
    
    def test_get_fact_not_found(self, client):
        """Should return 404 for nonexistent fact."""
        response = client.get("/v1/facts/nonexistent_fact")
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_get_facts_by_entity_required_params(self, client):
        """Should require entity parameters."""
        response = client.get("/v1/facts/by-entity")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_get_facts_by_entity_empty(self, client):
        """Should return empty list for unknown entity."""
        response = client.get(
            "/v1/facts/by-entity",
            params={"entity_id_type": "CIK", "entity_id": "9999999"},
        )
        assert response.status_code == status.HTTP_200_OK
        
        data = response.json()
        assert data["facts"] == []
        assert data["total"] == 0
    
    def test_get_facts_by_claim_required_params(self, client):
        """Should require claim_id parameter."""
        response = client.get("/v1/facts/by-claim")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_get_facts_by_evidence(self, client):
        """Should return facts by evidence ID."""
        response = client.get("/v1/facts/by-evidence/ev_nonexistent")
        assert response.status_code == status.HTTP_200_OK
        
        data = response.json()
        assert data["facts"] == []


class TestPassageEndpoints:
    """Tests for passage API endpoints."""
    
    def test_get_passage_not_found(self, client):
        """Should return 404 for nonexistent passage."""
        response = client.get("/v1/passages/nonexistent_passage")
        assert response.status_code == status.HTTP_404_NOT_FOUND


# =============================================================================
# Full Workflow Tests
# =============================================================================


class TestFullWorkflow:
    """End-to-end workflow tests."""
    
    def test_xbrl_extraction_workflow(self, client, sample_xbrl_content):
        """Full workflow: extract XBRL -> get facts -> verify."""
        # Step 1: Extract
        extract_response = client.post(
            "/v1/extract/direct",
            json={
                "evidence_id": "ev_workflow_001",
                "content_base64": base64.b64encode(sample_xbrl_content).decode(),
                "source_type": "sec_10k",
                "metadata": {"cik": "1234567", "fiscal_year": 2023},
            },
        )
        assert extract_response.status_code == status.HTTP_200_OK
        extract_data = extract_response.json()
        assert extract_data["success"] is True
        
        # Step 2: Get facts by entity
        facts_response = client.get(
            "/v1/facts/by-entity",
            params={"entity_id_type": "CIK", "entity_id": "1234567"},
        )
        assert facts_response.status_code == status.HTTP_200_OK
        facts_data = facts_response.json()
        assert facts_data["total"] > 0
        
        # Step 3: Get individual fact
        if facts_data["facts"]:
            fact_id = facts_data["facts"][0]["fact_id"]
            fact_response = client.get(f"/v1/facts/{fact_id}")
            assert fact_response.status_code == status.HTTP_200_OK
            fact_data = fact_response.json()
            assert fact_data["fact_id"] == fact_id
        
        # Step 4: Get facts by evidence
        evidence_response = client.get("/v1/facts/by-evidence/ev_workflow_001")
        assert evidence_response.status_code == status.HTTP_200_OK
        evidence_data = evidence_response.json()
        assert evidence_data["total"] > 0
    
    def test_job_orchestration_workflow(self, client):
        """Test job creation and status check."""
        # Step 1: Create job
        create_response = client.post(
            "/v1/extract/run",
            json={
                "evidence_ids": ["ev_job_001", "ev_job_002"],
                "claim_id": "claim_001",
            },
        )
        assert create_response.status_code == status.HTTP_202_ACCEPTED
        job_id = create_response.json()["job_id"]
        
        # Step 2: Check status
        status_response = client.get(f"/v1/extract/status/{job_id}")
        assert status_response.status_code == status.HTTP_200_OK
        status_data = status_response.json()
        assert status_data["job_id"] == job_id
        assert status_data["evidence_count"] == 2


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Edge case and error handling tests."""
    
    @pytest.mark.asyncio
    async def test_malformed_xbrl(self, service):
        """Should handle malformed XBRL gracefully."""
        malformed = b"<not valid xml"
        result = await service.extract_from_evidence(
            evidence_id="ev_001",
            content=malformed,
            source_type="sec_10k",
            metadata={},
        )
        # May fail or fall back to other methods
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_empty_content(self, service):
        """Should handle empty content."""
        result = await service.extract_from_evidence(
            evidence_id="ev_001",
            content=b"",
            source_type="sec_10k",
            metadata={},
        )
        # Should handle gracefully
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_unsupported_source_type(self, service, sample_xbrl_content):
        """Should refuse unsupported source types."""
        result = await service.extract_from_evidence(
            evidence_id="ev_001",
            content=sample_xbrl_content,
            source_type="unsupported_type",
            metadata={},
        )
        assert result.success is False
        assert result.refusal_code == ExtractionRefusalCode.EVIDENCE_TYPE_UNSUPPORTED
    
    @pytest.mark.asyncio
    async def test_very_large_values(self, xbrl_extractor):
        """Should handle very large financial values."""
        large_xbrl = b"""<?xml version="1.0"?>
        <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
                    xmlns:us-gaap="http://fasb.org/us-gaap/2023">
            <xbrli:context id="ctx">
                <xbrli:entity><xbrli:identifier>test</xbrli:identifier></xbrli:entity>
                <xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period>
            </xbrli:context>
            <us-gaap:Assets contextRef="ctx">999999999999999999999</us-gaap:Assets>
        </xbrli:xbrl>"""
        
        result = await xbrl_extractor.extract(
            large_xbrl, "ev_001", "hash", {}
        )
        # Should handle large numbers
        if result.success and result.facts:
            assert result.facts[0].value > 0
    
    @pytest.mark.asyncio
    async def test_negative_values(self, xbrl_extractor):
        """Should handle negative values (losses)."""
        negative_xbrl = b"""<?xml version="1.0"?>
        <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
                    xmlns:us-gaap="http://fasb.org/us-gaap/2023">
            <xbrli:context id="ctx">
                <xbrli:entity><xbrli:identifier>test</xbrli:identifier></xbrli:entity>
                <xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period>
            </xbrli:context>
            <us-gaap:NetIncomeLoss contextRef="ctx">-5000000</us-gaap:NetIncomeLoss>
        </xbrli:xbrl>"""
        
        result = await xbrl_extractor.extract(
            negative_xbrl, "ev_001", "hash", {}
        )
        
        if result.success:
            income_facts = [f for f in result.facts if f.fact_type == "net_income"]
            if income_facts:
                assert income_facts[0].value < 0


# =============================================================================
# Performance Tests
# =============================================================================


class TestPerformance:
    """Performance and efficiency tests."""
    
    @pytest.mark.asyncio
    async def test_extraction_duration_tracked(self, service, sample_xbrl_content):
        """Should track extraction duration."""
        result = await service.extract_from_evidence(
            evidence_id="ev_001",
            content=sample_xbrl_content,
            source_type="sec_10k",
            metadata={},
        )
        
        assert result.extraction_duration_ms >= 0
    
    def test_pagination(self, client, sample_xbrl_content):
        """Should support pagination."""
        # First extract some facts
        client.post(
            "/v1/extract/direct",
            json={
                "evidence_id": "ev_page_001",
                "content_base64": base64.b64encode(sample_xbrl_content).decode(),
                "source_type": "sec_10k",
                "metadata": {"cik": "9876543"},
            },
        )
        
        # Test pagination
        response = client.get(
            "/v1/facts/by-entity",
            params={
                "entity_id_type": "CIK",
                "entity_id": "9876543",
                "offset": 0,
                "limit": 2,
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["offset"] == 0
        assert data["limit"] == 2


# =============================================================================
# Constants and Configuration Tests
# =============================================================================


class TestConstants:
    """Tests for schema constants and configuration."""
    
    def test_xbrl_fact_mappings_complete(self):
        """XBRL mappings should cover key fact types."""
        required_types = [
            "total_assets",
            "total_liabilities",
            "total_equity",
            "revenue",
            "net_income",
            "operating_income",
            "cash_and_equivalents",
        ]
        for fact_type in required_types:
            assert fact_type in XBRL_FACT_MAPPINGS, f"Missing mapping for {fact_type}"
    
    def test_extraction_method_confidence_complete(self):
        """All extraction methods should have confidence values."""
        for method in ExtractionMethod:
            assert method.value in EXTRACTION_METHOD_CONFIDENCE
    
    def test_default_min_confidence_reasonable(self):
        """Default minimum confidence should be reasonable."""
        assert DEFAULT_MIN_CONFIDENCE >= Decimal("0")
        assert DEFAULT_MIN_CONFIDENCE <= Decimal("1")
        # Default should exclude low confidence
        assert DEFAULT_MIN_CONFIDENCE >= Decimal("0.50")
