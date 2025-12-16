"""
Extraction Service Implementation
==================================

Production-grade implementation of deterministic fact extraction:
- XBRL-first extraction for SEC filings
- Deterministic table/text fallback with low confidence flags
- Macroeconomic data extraction
- Fact and passage storage with deduplication
- Job orchestration

Design Principles:
- All extraction is deterministic and reproducible
- No LLM integration, no probabilistic guessing
- Every fact is traceable to evidence
- Idempotent extraction (same evidence → same facts)
"""

import hashlib
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional
import json

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import hash_content, deterministic_hash

from .schemas import (
    # Constants
    XBRL_FACT_MAPPINGS,
    EXTRACTION_METHOD_CONFIDENCE,
    FACT_CATEGORY_MAPPING,
    SUPPORTED_FACT_TYPES,
    DEFAULT_MIN_CONFIDENCE,
    # Enums
    ExtractionMethod,
    FactConfidence,
    ExtractionJobStatus,
    ExtractionRefusalCode,
    FactUnit,
    # Models
    XBRLLocation,
    TableLocation,
    TextLocation,
    MacroLocation,
    FactProvenance,
    FinancialFact,
    EvidencePassage,
    ExtractionJobRequest,
    ExtractionJobResult,
    ExtractionJob,
    ExtractionRefusal,
)


# =============================================================================
# Constants
# =============================================================================

EXTRACTOR_VERSION = "1.0.0"

# XBRL namespaces
XBRL_NAMESPACES = {
    "xbrli": "http://www.xbrl.org/2003/instance",
    "us-gaap": "http://fasb.org/us-gaap/2023",
    "dei": "http://xbrl.sec.gov/dei/2023",
    "link": "http://www.xbrl.org/2003/linkbase",
}

# Number patterns for table/text extraction
NUMBER_PATTERN = re.compile(
    r"[-−]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?",
    re.IGNORECASE
)

# Scale factors
SCALE_FACTORS = {
    "billion": 9,
    "millions": 6,
    "million": 6,
    "thousands": 3,
    "thousand": 3,
}


# =============================================================================
# Extraction Result Types
# =============================================================================


@dataclass
class RawExtractedFact:
    """Raw fact before ID assignment."""
    
    fact_type: str
    value: Decimal
    unit: FactUnit
    currency: Optional[str]
    scale: int
    as_of_date: date
    period_start: Optional[date]
    period_end: Optional[date]
    fiscal_year: Optional[int]
    fiscal_quarter: Optional[int]
    extraction_method: ExtractionMethod
    confidence: Decimal
    xbrl_location: Optional[XBRLLocation] = None
    table_location: Optional[TableLocation] = None
    text_location: Optional[TextLocation] = None
    macro_location: Optional[MacroLocation] = None
    
    def compute_content_hash(self) -> str:
        """Compute deterministic hash of fact content."""
        content = f"{self.fact_type}|{self.value}|{self.unit.value}|"
        content += f"{self.currency or ''}|{self.scale}|{self.as_of_date.isoformat()}|"
        content += f"{self.period_start.isoformat() if self.period_start else ''}|"
        content += f"{self.period_end.isoformat() if self.period_end else ''}"
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class RawExtractedPassage:
    """Raw passage before ID assignment."""
    
    text_content: str
    passage_type: str
    page_number: Optional[int]
    section_title: Optional[str]
    xbrl_tag: Optional[str]
    
    def compute_content_hash(self) -> str:
        """Compute deterministic hash of passage content."""
        return hashlib.sha256(self.text_content.encode()).hexdigest()


@dataclass
class ExtractionOutput:
    """Complete output from an extraction pipeline."""
    
    facts: list[RawExtractedFact] = field(default_factory=list)
    passages: list[RawExtractedPassage] = field(default_factory=list)
    extraction_method: ExtractionMethod = ExtractionMethod.XBRL
    success: bool = True
    refusal_code: Optional[ExtractionRefusalCode] = None
    error_message: Optional[str] = None


# =============================================================================
# Extraction Pipelines (Abstract Base)
# =============================================================================


class ExtractionPipeline(ABC):
    """
    Abstract base class for extraction pipelines.
    
    Each pipeline is responsible for extracting facts from a specific
    type of evidence using a deterministic method.
    """
    
    @property
    @abstractmethod
    def extraction_method(self) -> ExtractionMethod:
        """The extraction method this pipeline uses."""
        pass
    
    @property
    @abstractmethod
    def supported_source_types(self) -> frozenset[str]:
        """Source types this pipeline can handle."""
        pass
    
    @abstractmethod
    async def extract(
        self,
        content: bytes,
        evidence_id: str,
        evidence_hash: str,
        metadata: dict[str, Any],
    ) -> ExtractionOutput:
        """
        Extract facts from evidence content.
        
        This method MUST be deterministic - same content yields same facts.
        """
        pass
    
    @abstractmethod
    async def can_extract(self, content: bytes, metadata: dict[str, Any]) -> bool:
        """Check if this pipeline can extract from the given content."""
        pass


# =============================================================================
# XBRL Extractor (Primary for SEC Filings)
# =============================================================================


class XBRLExtractor(ExtractionPipeline):
    """
    Deterministic XBRL extraction for SEC filings.
    
    This is the primary extraction method for 10-K and 10-Q filings.
    XBRL extraction has HIGH confidence (1.00) as it uses authoritative tags.
    """
    
    @property
    def extraction_method(self) -> ExtractionMethod:
        return ExtractionMethod.XBRL
    
    @property
    def supported_source_types(self) -> frozenset[str]:
        return frozenset({"sec_10k", "sec_10q", "sec_8k"})
    
    async def can_extract(self, content: bytes, metadata: dict[str, Any]) -> bool:
        """Check if content contains valid XBRL."""
        try:
            # Check for XBRL markers
            content_str = content.decode("utf-8", errors="ignore")
            return (
                "xbrl" in content_str.lower()
                or "xmlns:us-gaap" in content_str
                or "<xbrli:" in content_str
            )
        except Exception:
            return False
    
    async def extract(
        self,
        content: bytes,
        evidence_id: str,
        evidence_hash: str,
        metadata: dict[str, Any],
    ) -> ExtractionOutput:
        """Extract facts from XBRL content."""
        try:
            content_str = content.decode("utf-8", errors="replace")
        except Exception as e:
            return ExtractionOutput(
                success=False,
                refusal_code=ExtractionRefusalCode.EVIDENCE_MALFORMED,
                error_message=f"Failed to decode content: {e}",
            )
        
        # Parse XBRL
        try:
            facts = self._parse_xbrl(content_str, metadata)
        except Exception as e:
            return ExtractionOutput(
                success=False,
                refusal_code=ExtractionRefusalCode.XBRL_PARSE_ERROR,
                error_message=f"XBRL parse error: {e}",
            )
        
        if not facts:
            return ExtractionOutput(
                success=False,
                refusal_code=ExtractionRefusalCode.NO_XBRL_AVAILABLE,
                error_message="No XBRL facts found in content",
            )
        
        return ExtractionOutput(
            facts=facts,
            passages=[],  # XBRL doesn't produce passages
            extraction_method=ExtractionMethod.XBRL,
            success=True,
        )
    
    def _parse_xbrl(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> list[RawExtractedFact]:
        """Parse XBRL content and extract facts."""
        facts: list[RawExtractedFact] = []
        
        # Extract fiscal period info from metadata
        fiscal_year = metadata.get("fiscal_year")
        fiscal_quarter = metadata.get("fiscal_quarter")
        period_end = metadata.get("period_of_report")
        if isinstance(period_end, str):
            period_end = date.fromisoformat(period_end)
        
        # Find XBRL facts using regex patterns for standard tags
        for fact_type, xbrl_tags in XBRL_FACT_MAPPINGS.items():
            for tag in xbrl_tags:
                # Extract namespace prefix and local name
                if ":" in tag:
                    prefix, local_name = tag.split(":", 1)
                else:
                    local_name = tag
                    prefix = "us-gaap"
                
                # Find all occurrences of this tag
                pattern = rf"<{prefix}:{local_name}[^>]*>([^<]+)</{prefix}:{local_name}>"
                matches = re.finditer(pattern, content, re.IGNORECASE)
                
                for match in matches:
                    value_str = match.group(1).strip()
                    
                    # Parse value
                    try:
                        value = self._parse_xbrl_value(value_str)
                    except (ValueError, InvalidOperation):
                        continue
                    
                    # Extract context and unit refs from tag attributes
                    tag_content = match.group(0)
                    context_ref = self._extract_attribute(tag_content, "contextRef")
                    unit_ref = self._extract_attribute(tag_content, "unitRef")
                    decimals = self._extract_attribute(tag_content, "decimals")
                    
                    # Determine unit
                    unit = self._determine_unit(unit_ref, fact_type)
                    currency = self._extract_currency(unit_ref) if unit == FactUnit.CURRENCY else None
                    
                    # Determine period from context
                    as_of_date, period_start, period_end_ctx = self._parse_context_period(
                        content, context_ref, period_end
                    )
                    
                    fact = RawExtractedFact(
                        fact_type=fact_type,
                        value=value,
                        unit=unit,
                        currency=currency or "USD",
                        scale=0,  # XBRL values are at scale
                        as_of_date=as_of_date or period_end or date.today(),
                        period_start=period_start,
                        period_end=period_end_ctx,
                        fiscal_year=fiscal_year,
                        fiscal_quarter=fiscal_quarter,
                        extraction_method=ExtractionMethod.XBRL,
                        confidence=EXTRACTION_METHOD_CONFIDENCE["XBRL"],
                        xbrl_location=XBRLLocation(
                            namespace=XBRL_NAMESPACES.get(prefix, f"http://fasb.org/{prefix}"),
                            tag_name=local_name,
                            context_ref=context_ref or "unknown",
                            unit_ref=unit_ref,
                            decimals=int(decimals) if decimals and decimals.lstrip("-").isdigit() else None,
                        ),
                    )
                    facts.append(fact)
                    break  # Take first match for each tag set
        
        return facts
    
    def _parse_xbrl_value(self, value_str: str) -> Decimal:
        """Parse XBRL numeric value."""
        # Remove whitespace and commas
        cleaned = value_str.strip().replace(",", "").replace(" ", "")
        # Handle negative values
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = "-" + cleaned[1:-1]
        return Decimal(cleaned)
    
    def _extract_attribute(self, tag: str, attr_name: str) -> Optional[str]:
        """Extract attribute value from XML tag."""
        pattern = rf'{attr_name}="([^"]*)"'
        match = re.search(pattern, tag)
        return match.group(1) if match else None
    
    def _determine_unit(self, unit_ref: Optional[str], fact_type: str) -> FactUnit:
        """Determine fact unit from unit reference."""
        if not unit_ref:
            # Default based on fact type
            if any(r in fact_type for r in ["ratio", "tier"]):
                return FactUnit.RATIO
            return FactUnit.CURRENCY
        
        unit_lower = unit_ref.lower()
        if "usd" in unit_lower or "eur" in unit_lower or "gbp" in unit_lower:
            return FactUnit.CURRENCY
        if "shares" in unit_lower:
            return FactUnit.SHARES
        if "percent" in unit_lower or "pure" in unit_lower:
            return FactUnit.RATIO
        
        return FactUnit.CURRENCY
    
    def _extract_currency(self, unit_ref: Optional[str]) -> Optional[str]:
        """Extract currency code from unit reference."""
        if not unit_ref:
            return "USD"
        
        unit_upper = unit_ref.upper()
        for currency in ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD"]:
            if currency in unit_upper:
                return currency
        
        return "USD"
    
    def _parse_context_period(
        self,
        content: str,
        context_ref: Optional[str],
        default_date: Optional[date],
    ) -> tuple[Optional[date], Optional[date], Optional[date]]:
        """Parse period from XBRL context."""
        if not context_ref:
            return default_date, None, None
        
        # Find context element
        pattern = rf'<xbrli:context[^>]*id="{context_ref}"[^>]*>.*?</xbrli:context>'
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        
        if not match:
            return default_date, None, None
        
        context = match.group(0)
        
        # Check for instant (point in time)
        instant_match = re.search(r"<xbrli:instant>([^<]+)</xbrli:instant>", context)
        if instant_match:
            try:
                instant_date = date.fromisoformat(instant_match.group(1).strip())
                return instant_date, None, None
            except ValueError:
                pass
        
        # Check for period (start/end)
        start_match = re.search(r"<xbrli:startDate>([^<]+)</xbrli:startDate>", context)
        end_match = re.search(r"<xbrli:endDate>([^<]+)</xbrli:endDate>", context)
        
        period_start = None
        period_end = None
        
        if start_match:
            try:
                period_start = date.fromisoformat(start_match.group(1).strip())
            except ValueError:
                pass
        
        if end_match:
            try:
                period_end = date.fromisoformat(end_match.group(1).strip())
            except ValueError:
                pass
        
        return period_end or default_date, period_start, period_end


# =============================================================================
# Table Extractor (Fallback for SEC Filings)
# =============================================================================


class TableExtractor(ExtractionPipeline):
    """
    Deterministic table extraction for financial statements.
    
    This is a fallback when XBRL is not available. Table extraction
    has MEDIUM confidence (0.70) as it relies on layout patterns.
    """
    
    @property
    def extraction_method(self) -> ExtractionMethod:
        return ExtractionMethod.TABLE
    
    @property
    def supported_source_types(self) -> frozenset[str]:
        return frozenset({"sec_10k", "sec_10q", "audited_financial_statement", "audited_annual_report"})
    
    async def can_extract(self, content: bytes, metadata: dict[str, Any]) -> bool:
        """Check if content contains extractable tables."""
        try:
            content_str = content.decode("utf-8", errors="ignore")
            # Look for HTML table markers
            return "<table" in content_str.lower() or "<tr" in content_str.lower()
        except Exception:
            return False
    
    async def extract(
        self,
        content: bytes,
        evidence_id: str,
        evidence_hash: str,
        metadata: dict[str, Any],
    ) -> ExtractionOutput:
        """Extract facts from table content."""
        try:
            content_str = content.decode("utf-8", errors="replace")
        except Exception as e:
            return ExtractionOutput(
                success=False,
                refusal_code=ExtractionRefusalCode.EVIDENCE_MALFORMED,
                error_message=f"Failed to decode content: {e}",
            )
        
        facts: list[RawExtractedFact] = []
        passages: list[RawExtractedPassage] = []
        
        # Get period info from metadata
        fiscal_year = metadata.get("fiscal_year")
        period_end = metadata.get("period_of_report") or metadata.get("period_end")
        if isinstance(period_end, str):
            period_end = date.fromisoformat(period_end)
        as_of_date = period_end or date.today()
        
        # Find tables and extract facts
        table_facts = self._extract_from_tables(
            content_str, as_of_date, fiscal_year
        )
        facts.extend(table_facts)
        
        if not facts:
            return ExtractionOutput(
                success=False,
                refusal_code=ExtractionRefusalCode.TABLE_PARSE_ERROR,
                error_message="No facts extracted from tables",
            )
        
        return ExtractionOutput(
            facts=facts,
            passages=passages,
            extraction_method=ExtractionMethod.TABLE,
            success=True,
        )
    
    def _extract_from_tables(
        self,
        content: str,
        as_of_date: date,
        fiscal_year: Optional[int],
    ) -> list[RawExtractedFact]:
        """Extract facts from HTML tables."""
        facts: list[RawExtractedFact] = []
        
        # Regex patterns for common financial line items
        patterns: dict[str, list[str]] = {
            "total_assets": [
                r"total\s+assets",
                r"assets,?\s+total",
            ],
            "total_liabilities": [
                r"total\s+liabilities",
                r"liabilities,?\s+total",
            ],
            "total_equity": [
                r"total\s+(?:stockholders['']?|shareholders['']?)\s+equity",
                r"total\s+equity",
            ],
            "cash_and_equivalents": [
                r"cash\s+and\s+cash\s+equivalents",
                r"cash\s+and\s+equivalents",
            ],
            "revenue": [
                r"total\s+revenue",
                r"net\s+revenue",
                r"revenues?,?\s+net",
            ],
            "net_income": [
                r"net\s+income",
                r"net\s+(?:loss|income)\s+attributable",
            ],
            "operating_income": [
                r"operating\s+income",
                r"income\s+from\s+operations",
            ],
        }
        
        # Simple table row extraction
        row_pattern = r"<tr[^>]*>(.*?)</tr>"
        cell_pattern = r"<t[dh][^>]*>(.*?)</t[dh]>"
        
        rows = re.findall(row_pattern, content, re.DOTALL | re.IGNORECASE)
        
        for row_idx, row in enumerate(rows):
            cells = re.findall(cell_pattern, row, re.DOTALL | re.IGNORECASE)
            if len(cells) < 2:
                continue
            
            # First cell is usually the label
            label = self._clean_html(cells[0]).lower()
            
            # Check if label matches any fact type
            for fact_type, fact_patterns in patterns.items():
                if any(re.search(p, label) for p in fact_patterns):
                    # Try to extract value from subsequent cells
                    for col_idx, cell in enumerate(cells[1:], 1):
                        value = self._extract_numeric_value(cell)
                        if value is not None:
                            fact = RawExtractedFact(
                                fact_type=fact_type,
                                value=value,
                                unit=FactUnit.CURRENCY,
                                currency="USD",
                                scale=0,
                                as_of_date=as_of_date,
                                period_start=None,
                                period_end=as_of_date if fact_type in {
                                    "revenue", "net_income", "operating_income"
                                } else None,
                                fiscal_year=fiscal_year,
                                fiscal_quarter=None,
                                extraction_method=ExtractionMethod.TABLE,
                                confidence=EXTRACTION_METHOD_CONFIDENCE["TABLE"],
                                table_location=TableLocation(
                                    page_number=1,  # Would need PDF processing for actual page
                                    table_index=0,
                                    row_index=row_idx,
                                    column_index=col_idx,
                                    row_header=self._clean_html(cells[0])[:100],
                                    column_header=None,
                                ),
                            )
                            facts.append(fact)
                            break  # Take first numeric value
                    break  # Don't match same row to multiple fact types
        
        return facts
    
    def _clean_html(self, text: str) -> str:
        """Remove HTML tags and normalize whitespace."""
        # Remove tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)
        return text.strip()
    
    def _extract_numeric_value(self, cell: str) -> Optional[Decimal]:
        """Extract numeric value from table cell."""
        text = self._clean_html(cell)
        
        # Remove currency symbols
        text = re.sub(r"[$€£¥]", "", text)
        
        # Find number pattern
        match = re.search(r"[-−(]?\s*([\d,]+(?:\.\d+)?)\s*[)]?", text)
        if not match:
            return None
        
        try:
            value_str = match.group(1).replace(",", "")
            value = Decimal(value_str)
            
            # Check for negative indicators
            if "(" in text or "−" in text or text.strip().startswith("-"):
                value = -value
            
            # Check for scale indicators
            text_lower = text.lower()
            for scale_word, scale_exp in SCALE_FACTORS.items():
                if scale_word in text_lower:
                    value = value * (Decimal(10) ** scale_exp)
                    break
            
            return value
        except (ValueError, InvalidOperation):
            return None


# =============================================================================
# Text Extractor (Low Confidence Fallback)
# =============================================================================


class TextExtractor(ExtractionPipeline):
    """
    Deterministic text pattern extraction.
    
    This is a last-resort fallback with LOW confidence (0.40).
    Policy should typically exclude LOW confidence facts.
    """
    
    @property
    def extraction_method(self) -> ExtractionMethod:
        return ExtractionMethod.TEXT
    
    @property
    def supported_source_types(self) -> frozenset[str]:
        return frozenset({"sec_10k", "sec_10q", "sec_8k", "audited_financial_statement"})
    
    async def can_extract(self, content: bytes, metadata: dict[str, Any]) -> bool:
        """Text extraction can always be attempted."""
        return len(content) > 0
    
    async def extract(
        self,
        content: bytes,
        evidence_id: str,
        evidence_hash: str,
        metadata: dict[str, Any],
    ) -> ExtractionOutput:
        """Extract facts from text patterns."""
        try:
            content_str = content.decode("utf-8", errors="replace")
        except Exception as e:
            return ExtractionOutput(
                success=False,
                refusal_code=ExtractionRefusalCode.EVIDENCE_MALFORMED,
                error_message=f"Failed to decode content: {e}",
            )
        
        # Text extraction produces passages for audit trail
        passages: list[RawExtractedPassage] = []
        facts: list[RawExtractedFact] = []
        
        # Get period info
        period_end = metadata.get("period_of_report") or metadata.get("period_end")
        if isinstance(period_end, str):
            period_end = date.fromisoformat(period_end)
        as_of_date = period_end or date.today()
        
        # Extract key narrative passages (debt maturity, covenants)
        narrative_passages = self._extract_narrative_passages(content_str)
        passages.extend(narrative_passages)
        
        return ExtractionOutput(
            facts=facts,
            passages=passages,
            extraction_method=ExtractionMethod.TEXT,
            success=True,
        )
    
    def _extract_narrative_passages(self, content: str) -> list[RawExtractedPassage]:
        """Extract key narrative passages for audit trail."""
        passages: list[RawExtractedPassage] = []
        
        # Debt maturity narrative patterns
        debt_patterns = [
            r"(debt\s+maturi(?:ty|ties)[^.]*\.(?:[^.]*\.){0,2})",
            r"(maturit(?:y|ies)\s+of\s+(?:long-term\s+)?debt[^.]*\.(?:[^.]*\.){0,2})",
        ]
        
        for pattern in debt_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                text = self._normalize_passage(match.group(1))
                if len(text) > 50:  # Only include meaningful passages
                    passages.append(RawExtractedPassage(
                        text_content=text[:2000],  # Limit length
                        passage_type="debt_maturity",
                        page_number=None,
                        section_title="Debt Maturities",
                        xbrl_tag=None,
                    ))
        
        # Covenant language patterns
        covenant_patterns = [
            r"((?:financial\s+)?covenant[^.]*\.(?:[^.]*\.){0,3})",
            r"(debt[-\s]to[-\s](?:equity|ebitda|capital)[^.]*\.(?:[^.]*\.){0,2})",
        ]
        
        for pattern in covenant_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                text = self._normalize_passage(match.group(1))
                if len(text) > 50:
                    passages.append(RawExtractedPassage(
                        text_content=text[:2000],
                        passage_type="covenant",
                        page_number=None,
                        section_title="Covenants",
                        xbrl_tag=None,
                    ))
        
        return passages[:10]  # Limit number of passages
    
    def _normalize_passage(self, text: str) -> str:
        """Normalize passage text."""
        # Remove excessive whitespace
        text = re.sub(r"\s+", " ", text)
        return text.strip()


# =============================================================================
# Macroeconomic Extractor
# =============================================================================


class MacroExtractor(ExtractionPipeline):
    """
    Extractor for macroeconomic data (yield curves, rates).
    
    Macroeconomic data has HIGH confidence (1.00) as it comes
    from authoritative sources like Treasury, Fed.
    """
    
    @property
    def extraction_method(self) -> ExtractionMethod:
        return ExtractionMethod.MACRO
    
    @property
    def supported_source_types(self) -> frozenset[str]:
        return frozenset({
            "interest_rate_curve",
            "treasury_yield_curve",
            "economic_indicators",
            "central_bank_rates",
        })
    
    async def can_extract(self, content: bytes, metadata: dict[str, Any]) -> bool:
        """Check if content is valid macroeconomic data."""
        try:
            # Try to parse as JSON
            content_str = content.decode("utf-8")
            json.loads(content_str)
            return True
        except Exception:
            return False
    
    async def extract(
        self,
        content: bytes,
        evidence_id: str,
        evidence_hash: str,
        metadata: dict[str, Any],
    ) -> ExtractionOutput:
        """Extract facts from macroeconomic data."""
        try:
            content_str = content.decode("utf-8")
            data = json.loads(content_str)
        except Exception as e:
            return ExtractionOutput(
                success=False,
                refusal_code=ExtractionRefusalCode.EVIDENCE_MALFORMED,
                error_message=f"Invalid JSON: {e}",
            )
        
        facts: list[RawExtractedFact] = []
        
        # Get metadata
        source_type = metadata.get("source_type", "economic_indicators")
        effective_date = metadata.get("effective_date")
        if isinstance(effective_date, str):
            effective_date = date.fromisoformat(effective_date)
        as_of_date = effective_date or date.today()
        
        series_id = metadata.get("series_id", source_type)
        data_source = metadata.get("source_institution", "Unknown")
        
        # Extract facts from data
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (int, float)):
                    fact_type = self._map_to_fact_type(key, source_type)
                    if fact_type:
                        facts.append(RawExtractedFact(
                            fact_type=fact_type,
                            value=Decimal(str(value)),
                            unit=FactUnit.PERCENT if "rate" in key.lower() or "yield" in key.lower() else FactUnit.DECIMAL,
                            currency=None,
                            scale=0,
                            as_of_date=as_of_date,
                            period_start=None,
                            period_end=None,
                            fiscal_year=as_of_date.year,
                            fiscal_quarter=None,
                            extraction_method=ExtractionMethod.MACRO,
                            confidence=EXTRACTION_METHOD_CONFIDENCE["MACRO"],
                            macro_location=MacroLocation(
                                series_id=series_id,
                                data_source=data_source,
                                observation_date=as_of_date,
                            ),
                        ))
        
        return ExtractionOutput(
            facts=facts,
            passages=[],
            extraction_method=ExtractionMethod.MACRO,
            success=True,
        )
    
    def _map_to_fact_type(self, key: str, source_type: str) -> Optional[str]:
        """Map data key to canonical fact type."""
        key_lower = key.lower()
        
        if "treasury" in key_lower or "yield" in key_lower:
            return "treasury_yield"
        if "interest" in key_lower or "rate" in key_lower:
            return "interest_rate"
        if "inflation" in key_lower:
            return "inflation_rate"
        if "gdp" in key_lower:
            return "gdp_growth_rate"
        if "unemployment" in key_lower:
            return "unemployment_rate"
        
        return None


# =============================================================================
# Fact Store
# =============================================================================


class FactStore:
    """
    In-memory fact store with indexing and deduplication.
    
    Provides:
    - Deduplication by fact hash
    - Indexing by entity, fact_type, as_of_date, evidence_id
    - Idempotent storage
    """
    
    def __init__(self) -> None:
        self._facts: dict[str, FinancialFact] = {}
        self._by_hash: dict[str, str] = {}  # hash -> fact_id
        self._by_entity: dict[str, set[str]] = {}  # entity_id -> fact_ids
        self._by_fact_type: dict[str, set[str]] = {}  # fact_type -> fact_ids
        self._by_evidence: dict[str, set[str]] = {}  # evidence_id -> fact_ids
        self._by_claim: dict[str, set[str]] = {}  # claim_id -> fact_ids
    
    def store(self, fact: FinancialFact) -> tuple[str, bool]:
        """
        Store a fact, returning (fact_id, is_duplicate).
        
        If fact with same hash exists, returns existing ID.
        """
        # Check for duplicate by hash
        if fact.fact_hash in self._by_hash:
            return self._by_hash[fact.fact_hash], True
        
        # Store fact
        self._facts[fact.fact_id] = fact
        self._by_hash[fact.fact_hash] = fact.fact_id
        
        # Index by entity
        if fact.entity_id:
            key = f"{fact.entity_id_type}:{fact.entity_id}"
            if key not in self._by_entity:
                self._by_entity[key] = set()
            self._by_entity[key].add(fact.fact_id)
        
        # Index by fact type
        if fact.fact_type not in self._by_fact_type:
            self._by_fact_type[fact.fact_type] = set()
        self._by_fact_type[fact.fact_type].add(fact.fact_id)
        
        # Index by evidence
        evidence_id = fact.derived_from.evidence_id
        if evidence_id not in self._by_evidence:
            self._by_evidence[evidence_id] = set()
        self._by_evidence[evidence_id].add(fact.fact_id)
        
        return fact.fact_id, False
    
    def get(self, fact_id: str) -> Optional[FinancialFact]:
        """Get fact by ID."""
        return self._facts.get(fact_id)
    
    def get_by_hash(self, fact_hash: str) -> Optional[FinancialFact]:
        """Get fact by content hash."""
        fact_id = self._by_hash.get(fact_hash)
        return self._facts.get(fact_id) if fact_id else None
    
    def find_by_entity(
        self,
        entity_id_type: str,
        entity_id: str,
        fact_types: Optional[list[str]] = None,
    ) -> list[FinancialFact]:
        """Find facts by entity identifier."""
        key = f"{entity_id_type}:{entity_id}"
        fact_ids = self._by_entity.get(key, set())
        
        facts = [self._facts[fid] for fid in fact_ids if fid in self._facts]
        
        if fact_types:
            facts = [f for f in facts if f.fact_type in fact_types]
        
        return sorted(facts, key=lambda f: f.as_of_date, reverse=True)
    
    def find_by_evidence(self, evidence_id: str) -> list[FinancialFact]:
        """Find all facts extracted from an evidence item."""
        fact_ids = self._by_evidence.get(evidence_id, set())
        return [self._facts[fid] for fid in fact_ids if fid in self._facts]
    
    def link_to_claim(self, claim_id: str, fact_id: str) -> None:
        """Link a fact to a claim."""
        if claim_id not in self._by_claim:
            self._by_claim[claim_id] = set()
        self._by_claim[claim_id].add(fact_id)
    
    def find_by_claim(self, claim_id: str) -> list[FinancialFact]:
        """Find facts linked to a claim."""
        fact_ids = self._by_claim.get(claim_id, set())
        return [self._facts[fid] for fid in fact_ids if fid in self._facts]
    
    def has_extraction(self, evidence_hash: str) -> bool:
        """Check if evidence has already been extracted."""
        # Check if any fact references this evidence hash
        for fact in self._facts.values():
            if fact.derived_from.evidence_hash == evidence_hash:
                return True
        return False


# =============================================================================
# Passage Store
# =============================================================================


class PassageStore:
    """
    In-memory passage store with deduplication.
    """
    
    def __init__(self) -> None:
        self._passages: dict[str, EvidencePassage] = {}
        self._by_hash: dict[str, str] = {}  # hash -> passage_id
        self._by_evidence: dict[str, set[str]] = {}  # evidence_id -> passage_ids
    
    def store(self, passage: EvidencePassage) -> tuple[str, bool]:
        """Store a passage, returning (passage_id, is_duplicate)."""
        # Check for duplicate by hash
        if passage.passage_hash in self._by_hash:
            return self._by_hash[passage.passage_hash], True
        
        self._passages[passage.passage_id] = passage
        self._by_hash[passage.passage_hash] = passage.passage_id
        
        # Index by evidence
        if passage.evidence_id not in self._by_evidence:
            self._by_evidence[passage.evidence_id] = set()
        self._by_evidence[passage.evidence_id].add(passage.passage_id)
        
        return passage.passage_id, False
    
    def get(self, passage_id: str) -> Optional[EvidencePassage]:
        """Get passage by ID."""
        return self._passages.get(passage_id)
    
    def find_by_evidence(self, evidence_id: str) -> list[EvidencePassage]:
        """Find passages by evidence ID."""
        passage_ids = self._by_evidence.get(evidence_id, set())
        return [self._passages[pid] for pid in passage_ids if pid in self._passages]


# =============================================================================
# Job Store
# =============================================================================


class JobStore:
    """In-memory job store for extraction job tracking."""
    
    def __init__(self) -> None:
        self._jobs: dict[str, ExtractionJob] = {}
    
    def store(self, job: ExtractionJob) -> None:
        """Store or update a job."""
        self._jobs[job.job_id] = job
    
    def get(self, job_id: str) -> Optional[ExtractionJob]:
        """Get job by ID."""
        return self._jobs.get(job_id)


# =============================================================================
# Extraction Service
# =============================================================================


class ExtractionService:
    """
    Production-grade Extraction Service.
    
    Provides:
    - Deterministic fact extraction from evidence
    - XBRL-first with fallback to table/text
    - Fact and passage storage with deduplication
    - Job orchestration
    - Idempotent extraction
    """
    
    def __init__(self) -> None:
        self._fact_store = FactStore()
        self._passage_store = PassageStore()
        self._job_store = JobStore()
        
        # Initialize pipelines
        self._pipelines: dict[str, list[ExtractionPipeline]] = {}
        self._register_pipelines()
    
    def _register_pipelines(self) -> None:
        """Register extraction pipelines in priority order."""
        xbrl = XBRLExtractor()
        table = TableExtractor()
        text = TextExtractor()
        macro = MacroExtractor()
        
        # SEC filings: XBRL first, then table, then text
        for source_type in ["sec_10k", "sec_10q", "sec_8k"]:
            self._pipelines[source_type] = [xbrl, table, text]
        
        # Audited statements: table first, then text
        for source_type in ["audited_financial_statement", "audited_annual_report"]:
            self._pipelines[source_type] = [table, text]
        
        # Macroeconomic data
        for source_type in ["interest_rate_curve", "treasury_yield_curve", "economic_indicators", "central_bank_rates"]:
            self._pipelines[source_type] = [macro]
    
    async def run_extraction(
        self,
        request: ExtractionJobRequest,
    ) -> ExtractionJob:
        """
        Run extraction job for given evidence.
        
        Returns immediately with job status; extraction happens synchronously
        in this implementation (could be made async with task queue).
        """
        job_id = str(generate_canonical_id(EntityType.EXTRACTION))
        
        job = ExtractionJob(
            job_id=job_id,
            status=ExtractionJobStatus.RUNNING,
            evidence_count=len(request.evidence_ids),
            claim_id=request.claim_id,
            trace_id=request.trace_id or "",
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            results=[],
            error_message=None,
        )
        self._job_store.store(job)
        
        results: list[ExtractionJobResult] = []
        total_facts = 0
        total_passages = 0
        failed_count = 0
        
        for evidence_id in request.evidence_ids:
            result = await self._extract_single(
                evidence_id=evidence_id,
                min_confidence=request.min_confidence,
                allow_low_confidence=request.allow_low_confidence,
                force_reextract=request.force_reextract,
            )
            results.append(result)
            
            if result.success:
                total_facts += result.facts_extracted
                total_passages += result.passages_extracted
                
                # Link facts to claim if specified
                if request.claim_id:
                    for fact_id in result.fact_ids:
                        self._fact_store.link_to_claim(request.claim_id, fact_id)
            else:
                failed_count += 1
        
        # Determine final status
        if failed_count == len(request.evidence_ids):
            status = ExtractionJobStatus.FAILED
        elif failed_count > 0:
            status = ExtractionJobStatus.PARTIAL
        else:
            status = ExtractionJobStatus.COMPLETED
        
        # Update job
        final_job = ExtractionJob(
            job_id=job_id,
            status=status,
            evidence_count=len(request.evidence_ids),
            claim_id=request.claim_id,
            trace_id=request.trace_id or "",
            completed_count=len(request.evidence_ids) - failed_count,
            failed_count=failed_count,
            results=results,
            total_facts=total_facts,
            total_passages=total_passages,
            started_at=job.started_at,
            completed_at=datetime.now(timezone.utc),
            error_message=None,
        )
        self._job_store.store(final_job)
        
        return final_job
    
    async def _extract_single(
        self,
        evidence_id: str,
        min_confidence: Decimal,
        allow_low_confidence: bool,
        force_reextract: bool,
        content: Optional[bytes] = None,
        evidence_hash: Optional[str] = None,
        source_type: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> ExtractionJobResult:
        """Extract facts from a single evidence item."""
        start_time = datetime.now(timezone.utc)
        
        # In production, would fetch from evidence service
        # For now, use provided data or mock
        if content is None:
            # Would call evidence service here
            return ExtractionJobResult(
                evidence_id=evidence_id,
                evidence_hash=evidence_hash or "",
                success=False,
                refusal_code=ExtractionRefusalCode.EVIDENCE_NOT_FOUND,
                error_message="Evidence not found (mock implementation)",
                extraction_method=None,
            )
        
        if evidence_hash is None:
            evidence_hash = hashlib.sha256(content).hexdigest()
        
        # Check if already extracted (idempotency)
        if not force_reextract and self._fact_store.has_extraction(evidence_hash):
            existing_facts = [
                f for f in self._fact_store._facts.values()
                if f.derived_from.evidence_hash == evidence_hash
            ]
            return ExtractionJobResult(
                evidence_id=evidence_id,
                evidence_hash=evidence_hash,
                success=True,
                facts_extracted=len(existing_facts),
                fact_ids=[f.fact_id for f in existing_facts],
                extraction_duration_ms=0,
                refusal_code=None,
                error_message=None,
                extraction_method=ExtractionMethod.XBRL,  # Assume XBRL for cached results
            )
        
        if source_type is None:
            source_type = "sec_10k"  # Default
        
        if metadata is None:
            metadata = {}
        
        # Get pipelines for source type
        pipelines = self._pipelines.get(source_type, [])
        if not pipelines:
            return ExtractionJobResult(
                evidence_id=evidence_id,
                evidence_hash=evidence_hash,
                success=False,
                refusal_code=ExtractionRefusalCode.EVIDENCE_TYPE_UNSUPPORTED,
                error_message=f"No extraction pipeline for source type: {source_type}",
                extraction_method=None,
            )
        
        # Try pipelines in order
        extraction_output: Optional[ExtractionOutput] = None
        for pipeline in pipelines:
            if await pipeline.can_extract(content, metadata):
                extraction_output = await pipeline.extract(
                    content, evidence_id, evidence_hash, metadata
                )
                if extraction_output.success and extraction_output.facts:
                    break
        
        if not extraction_output or not extraction_output.success:
            return ExtractionJobResult(
                evidence_id=evidence_id,
                evidence_hash=evidence_hash,
                success=False,
                refusal_code=extraction_output.refusal_code if extraction_output else ExtractionRefusalCode.EVIDENCE_MALFORMED,
                error_message=extraction_output.error_message if extraction_output else "No pipeline could extract",
                extraction_method=extraction_output.extraction_method if extraction_output else None,
            )
        
        # Convert raw facts to FinancialFacts and store
        fact_ids: list[str] = []
        facts_stored = 0
        
        for raw_fact in extraction_output.facts:
            # Apply confidence filter
            if not allow_low_confidence and raw_fact.confidence < min_confidence:
                continue
            
            # Create FinancialFact
            fact = self._create_fact(raw_fact, evidence_id, evidence_hash, metadata)
            
            # Store (handles deduplication)
            fact_id, is_dup = self._fact_store.store(fact)
            fact_ids.append(fact_id)
            if not is_dup:
                facts_stored += 1
        
        # Store passages
        passage_ids: list[str] = []
        passages_stored = 0
        
        for raw_passage in extraction_output.passages:
            passage = self._create_passage(raw_passage, evidence_id, evidence_hash)
            passage_id, is_dup = self._passage_store.store(passage)
            passage_ids.append(passage_id)
            if not is_dup:
                passages_stored += 1
        
        duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        
        return ExtractionJobResult(
            evidence_id=evidence_id,
            evidence_hash=evidence_hash,
            success=True,
            facts_extracted=facts_stored,
            passages_extracted=passages_stored,
            fact_ids=fact_ids,
            passage_ids=passage_ids,
            extraction_method=extraction_output.extraction_method,
            extraction_duration_ms=duration_ms,
            refusal_code=None,
            error_message=None,
        )
    
    def _create_fact(
        self,
        raw: RawExtractedFact,
        evidence_id: str,
        evidence_hash: str,
        metadata: dict[str, Any],
    ) -> FinancialFact:
        """Create FinancialFact from raw extraction."""
        fact_id = str(generate_canonical_id(EntityType.EXTRACTION))
        fact_hash = raw.compute_content_hash()
        
        # Determine confidence level
        if raw.confidence >= Decimal("0.90"):
            confidence_level = FactConfidence.HIGH
        elif raw.confidence >= Decimal("0.60"):
            confidence_level = FactConfidence.MEDIUM
        else:
            confidence_level = FactConfidence.LOW
        
        # Get category from mapping
        category = FACT_CATEGORY_MAPPING.get(raw.fact_type, "unknown")
        
        # Extract entity info from metadata
        entity_id = metadata.get("cik") or metadata.get("entity_id")
        entity_id_type = "CIK" if metadata.get("cik") else metadata.get("entity_id_type")
        
        # Build provenance
        provenance = FactProvenance(
            evidence_id=evidence_id,
            evidence_hash=evidence_hash,
            passage_id=None,
            xbrl_location=raw.xbrl_location,
            table_location=raw.table_location,
            text_location=raw.text_location,
            macro_location=raw.macro_location,
        )
        
        return FinancialFact(
            fact_id=fact_id,
            fact_hash=fact_hash,
            fact_type=raw.fact_type,
            category=category,
            value=raw.value,
            unit=raw.unit,
            currency=raw.currency,
            scale=raw.scale,
            as_of_date=raw.as_of_date,
            period_start=raw.period_start,
            period_end=raw.period_end,
            fiscal_year=raw.fiscal_year,
            fiscal_quarter=raw.fiscal_quarter,
            confidence=raw.confidence,
            confidence_level=confidence_level,
            extraction_method=raw.extraction_method,
            extractor_version=EXTRACTOR_VERSION,
            derived_from=provenance,
            entity_id=entity_id,
            entity_id_type=entity_id_type,
        )
    
    def _create_passage(
        self,
        raw: RawExtractedPassage,
        evidence_id: str,
        evidence_hash: str,
    ) -> EvidencePassage:
        """Create EvidencePassage from raw extraction."""
        passage_id = str(generate_canonical_id(EntityType.EXTRACTION))
        passage_hash = raw.compute_content_hash()
        
        return EvidencePassage(
            passage_id=passage_id,
            passage_hash=passage_hash,
            evidence_id=evidence_id,
            evidence_hash=evidence_hash,
            page_number=raw.page_number,
            section_title=raw.section_title,
            xbrl_tag=raw.xbrl_tag,
            text_content=raw.text_content,
            passage_type=raw.passage_type,
        )
    
    # =========================================================================
    # Public API Methods
    # =========================================================================
    
    async def extract_from_evidence(
        self,
        evidence_id: str,
        content: bytes,
        source_type: str,
        metadata: dict[str, Any],
        min_confidence: Decimal = DEFAULT_MIN_CONFIDENCE,
        allow_low_confidence: bool = False,
        force_reextract: bool = False,
    ) -> ExtractionJobResult:
        """
        Extract facts from a single evidence item.
        
        This is the main entry point for extraction.
        """
        evidence_hash = hashlib.sha256(content).hexdigest()
        
        return await self._extract_single(
            evidence_id=evidence_id,
            content=content,
            evidence_hash=evidence_hash,
            source_type=source_type,
            metadata=metadata,
            min_confidence=min_confidence,
            allow_low_confidence=allow_low_confidence,
            force_reextract=force_reextract,
        )
    
    async def get_job(self, job_id: str) -> Optional[ExtractionJob]:
        """Get extraction job by ID."""
        return self._job_store.get(job_id)
    
    async def get_fact(self, fact_id: str) -> Optional[FinancialFact]:
        """Get fact by ID."""
        return self._fact_store.get(fact_id)
    
    async def get_passage(self, passage_id: str) -> Optional[EvidencePassage]:
        """Get passage by ID."""
        return self._passage_store.get(passage_id)
    
    async def find_facts_by_entity(
        self,
        entity_id_type: str,
        entity_id: str,
        fact_types: Optional[list[str]] = None,
        min_confidence: Optional[Decimal] = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[FinancialFact], int]:
        """Find facts by entity."""
        facts = self._fact_store.find_by_entity(entity_id_type, entity_id, fact_types)
        
        if min_confidence:
            facts = [f for f in facts if f.confidence >= min_confidence]
        
        total = len(facts)
        return facts[offset:offset + limit], total
    
    async def find_facts_by_claim(
        self,
        claim_id: str,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[FinancialFact], int]:
        """Find facts linked to a claim."""
        facts = self._fact_store.find_by_claim(claim_id)
        total = len(facts)
        return facts[offset:offset + limit], total
    
    async def find_facts_by_evidence(
        self,
        evidence_id: str,
    ) -> list[FinancialFact]:
        """Find all facts extracted from an evidence item."""
        return self._fact_store.find_by_evidence(evidence_id)
