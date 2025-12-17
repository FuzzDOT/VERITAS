"""
Postgres-Backed Fact Store
===========================

Persistent implementation of FactStore and PassageStore using PostgreSQL.

This module provides durable storage for extracted facts, enabling:
- Fact retrieval by entity, fact_type, evidence
- Claim linkage
- Audit trail preservation

Design:
- Implements same interface as in-memory stores in service_impl.py
- Uses SQLAlchemy async for database access
- Maintains same deduplication semantics (by hash)
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from infrastructure.postgres.models import (
    FinancialFactRecord,
    EvidencePassageRecord,
    FactClaimLink,
)
from infrastructure.postgres.session import get_session

from services.extraction_service.schemas import (
    FinancialFact,
    EvidencePassage,
    FactProvenance,
    FactUnit,
    FactConfidence,
    ExtractionMethod,
    XBRLLocation,
    TableLocation,
    TextLocation,
    MacroLocation,
)


# =============================================================================
# Conversion Helpers
# =============================================================================


def fact_to_record(fact: FinancialFact) -> dict[str, Any]:
    """Convert FinancialFact to database record dict."""
    # Convert as_of_date to datetime if it's a date
    as_of_dt = fact.as_of_date
    if isinstance(as_of_dt, date) and not isinstance(as_of_dt, datetime):
        as_of_dt = datetime.combine(as_of_dt, datetime.min.time(), tzinfo=timezone.utc)
    
    period_start_dt = None
    if fact.period_start:
        if isinstance(fact.period_start, date) and not isinstance(fact.period_start, datetime):
            period_start_dt = datetime.combine(fact.period_start, datetime.min.time(), tzinfo=timezone.utc)
        else:
            period_start_dt = fact.period_start
    
    period_end_dt = None
    if fact.period_end:
        if isinstance(fact.period_end, date) and not isinstance(fact.period_end, datetime):
            period_end_dt = datetime.combine(fact.period_end, datetime.min.time(), tzinfo=timezone.utc)
        else:
            period_end_dt = fact.period_end
    
    return {
        "id": fact.fact_id,
        "fact_hash": fact.fact_hash,
        "fact_type": fact.fact_type,
        "category": fact.category,
        "value": str(fact.value),
        "unit": fact.unit.value,
        "currency": fact.currency,
        "scale": fact.scale,
        "as_of_date": as_of_dt,
        "period_start": period_start_dt,
        "period_end": period_end_dt,
        "fiscal_year": fact.fiscal_year,
        "fiscal_quarter": fact.fiscal_quarter,
        "confidence": str(fact.confidence),
        "confidence_level": fact.confidence_level.value,
        "extraction_method": fact.extraction_method.value,
        "extractor_version": fact.extractor_version,
        "evidence_id": fact.derived_from.evidence_id,
        "evidence_hash": fact.derived_from.evidence_hash,
        "provenance": fact.derived_from.model_dump(mode="json"),
        "entity_id": fact.entity_id,
        "entity_id_type": fact.entity_id_type,
    }


def record_to_fact(record: FinancialFactRecord) -> FinancialFact:
    """Convert database record to FinancialFact."""
    # Reconstruct provenance
    prov_data = record.provenance
    
    xbrl_loc = None
    if prov_data.get("xbrl_location"):
        xbrl_loc = XBRLLocation(**prov_data["xbrl_location"])
    
    table_loc = None
    if prov_data.get("table_location"):
        table_loc = TableLocation(**prov_data["table_location"])
    
    text_loc = None
    if prov_data.get("text_location"):
        text_loc = TextLocation(**prov_data["text_location"])
    
    macro_loc = None
    if prov_data.get("macro_location"):
        macro_loc = MacroLocation(**prov_data["macro_location"])
    
    provenance = FactProvenance(
        evidence_id=record.evidence_id,
        evidence_hash=record.evidence_hash,
        passage_id=prov_data.get("passage_id"),
        xbrl_location=xbrl_loc,
        table_location=table_loc,
        text_location=text_loc,
        macro_location=macro_loc,
    )
    
    # Convert datetime to date for as_of_date
    as_of = record.as_of_date.date() if isinstance(record.as_of_date, datetime) else record.as_of_date
    period_start = record.period_start.date() if record.period_start else None
    period_end = record.period_end.date() if record.period_end else None
    
    return FinancialFact(
        fact_id=record.id,
        fact_hash=record.fact_hash,
        fact_type=record.fact_type,
        category=record.category,
        value=Decimal(record.value),
        unit=FactUnit(record.unit),
        currency=record.currency,
        scale=record.scale,
        as_of_date=as_of,
        period_start=period_start,
        period_end=period_end,
        fiscal_year=record.fiscal_year,
        fiscal_quarter=record.fiscal_quarter,
        confidence=Decimal(record.confidence),
        confidence_level=FactConfidence(record.confidence_level),
        extraction_method=ExtractionMethod(record.extraction_method),
        extractor_version=record.extractor_version,
        derived_from=provenance,
        entity_id=record.entity_id,
        entity_id_type=record.entity_id_type,
        extracted_at=record.created_at,
    )


def passage_to_record(passage: EvidencePassage) -> dict[str, Any]:
    """Convert EvidencePassage to database record dict."""
    return {
        "id": passage.passage_id,
        "passage_hash": passage.passage_hash,
        "evidence_id": passage.evidence_id,
        "evidence_hash": passage.evidence_hash,
        "page_number": passage.page_number,
        "section_title": passage.section_title,
        "xbrl_tag": passage.xbrl_tag,
        "text_content": passage.text_content,
        "passage_type": passage.passage_type,
        "linked_fact_ids": list(passage.linked_fact_ids),
    }


def record_to_passage(record: EvidencePassageRecord) -> EvidencePassage:
    """Convert database record to EvidencePassage."""
    return EvidencePassage(
        passage_id=record.id,
        passage_hash=record.passage_hash,
        evidence_id=record.evidence_id,
        evidence_hash=record.evidence_hash,
        page_number=record.page_number,
        section_title=record.section_title,
        xbrl_tag=record.xbrl_tag,
        text_content=record.text_content,
        passage_type=record.passage_type,
        linked_fact_ids=list(record.linked_fact_ids or []),
    )


# =============================================================================
# Postgres Fact Store
# =============================================================================


class PostgresFactStore:
    """
    Postgres-backed fact store with same interface as in-memory store.
    
    Provides:
    - Deduplication by fact hash
    - Indexing by entity, fact_type, as_of_date, evidence_id
    - Idempotent storage
    - Claim linkage
    """
    
    async def store(self, fact: FinancialFact) -> tuple[str, bool]:
        """
        Store a fact, returning (fact_id, is_duplicate).
        
        Uses upsert with ON CONFLICT to handle duplicates.
        """
        async with get_session() as session:
            # Check for existing by hash
            result = await session.execute(
                select(FinancialFactRecord.id)
                .where(FinancialFactRecord.fact_hash == fact.fact_hash)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                return existing, True
            
            # Insert new fact
            record_data = fact_to_record(fact)
            record = FinancialFactRecord(**record_data)
            session.add(record)
            await session.flush()
            
            return fact.fact_id, False
    
    async def get(self, fact_id: str) -> Optional[FinancialFact]:
        """Get fact by ID."""
        async with get_session() as session:
            result = await session.execute(
                select(FinancialFactRecord)
                .where(FinancialFactRecord.id == fact_id)
            )
            record = result.scalar_one_or_none()
            
            if record:
                return record_to_fact(record)
            return None
    
    async def get_by_hash(self, fact_hash: str) -> Optional[FinancialFact]:
        """Get fact by content hash."""
        async with get_session() as session:
            result = await session.execute(
                select(FinancialFactRecord)
                .where(FinancialFactRecord.fact_hash == fact_hash)
            )
            record = result.scalar_one_or_none()
            
            if record:
                return record_to_fact(record)
            return None
    
    async def find_by_entity(
        self,
        entity_id_type: str,
        entity_id: str,
        fact_types: Optional[list[str]] = None,
        min_confidence: Optional[Decimal] = None,
        as_of_start: Optional[date] = None,
        as_of_end: Optional[date] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[FinancialFact], int]:
        """Find facts by entity identifier."""
        async with get_session() as session:
            # Build query
            conditions = [
                FinancialFactRecord.entity_id_type == entity_id_type,
                FinancialFactRecord.entity_id == entity_id,
            ]
            
            if fact_types:
                conditions.append(FinancialFactRecord.fact_type.in_(fact_types))
            
            if as_of_start:
                start_dt = datetime.combine(as_of_start, datetime.min.time(), tzinfo=timezone.utc)
                conditions.append(FinancialFactRecord.as_of_date >= start_dt)
            
            if as_of_end:
                end_dt = datetime.combine(as_of_end, datetime.max.time(), tzinfo=timezone.utc)
                conditions.append(FinancialFactRecord.as_of_date <= end_dt)
            
            # Get count
            count_result = await session.execute(
                select(FinancialFactRecord.id)
                .where(and_(*conditions))
            )
            total = len(count_result.all())
            
            # Get paginated results
            result = await session.execute(
                select(FinancialFactRecord)
                .where(and_(*conditions))
                .order_by(FinancialFactRecord.as_of_date.desc())
                .offset(offset)
                .limit(limit)
            )
            records = result.scalars().all()
            
            facts = [record_to_fact(r) for r in records]
            
            # Filter by confidence in Python (stored as string)
            if min_confidence:
                facts = [f for f in facts if f.confidence >= min_confidence]
            
            return facts, total
    
    async def find_by_evidence(self, evidence_id: str) -> list[FinancialFact]:
        """Find all facts extracted from an evidence item."""
        async with get_session() as session:
            result = await session.execute(
                select(FinancialFactRecord)
                .where(FinancialFactRecord.evidence_id == evidence_id)
            )
            records = result.scalars().all()
            
            return [record_to_fact(r) for r in records]
    
    async def link_to_claim(self, claim_id: str, fact_id: str) -> None:
        """Link a fact to a claim."""
        async with get_session() as session:
            # Upsert link
            link_id = f"{fact_id}_{claim_id}"
            
            stmt = pg_insert(FactClaimLink).values(
                id=link_id,
                fact_id=fact_id,
                claim_id=claim_id,
            ).on_conflict_do_nothing()
            
            await session.execute(stmt)
    
    async def find_by_claim(
        self,
        claim_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[FinancialFact], int]:
        """Find facts linked to a claim."""
        async with get_session() as session:
            # Get linked fact IDs
            link_result = await session.execute(
                select(FactClaimLink.fact_id)
                .where(FactClaimLink.claim_id == claim_id)
            )
            fact_ids = [r[0] for r in link_result.all()]
            
            if not fact_ids:
                return [], 0
            
            total = len(fact_ids)
            
            # Get facts
            result = await session.execute(
                select(FinancialFactRecord)
                .where(FinancialFactRecord.id.in_(fact_ids))
                .offset(offset)
                .limit(limit)
            )
            records = result.scalars().all()
            
            return [record_to_fact(r) for r in records], total
    
    async def has_extraction(self, evidence_hash: str) -> bool:
        """Check if evidence has already been extracted."""
        async with get_session() as session:
            result = await session.execute(
                select(FinancialFactRecord.id)
                .where(FinancialFactRecord.evidence_hash == evidence_hash)
                .limit(1)
            )
            return result.scalar_one_or_none() is not None


# =============================================================================
# Postgres Passage Store
# =============================================================================


class PostgresPassageStore:
    """Postgres-backed passage store with deduplication."""
    
    async def store(self, passage: EvidencePassage) -> tuple[str, bool]:
        """Store a passage, returning (passage_id, is_duplicate)."""
        async with get_session() as session:
            # Check for existing by hash
            result = await session.execute(
                select(EvidencePassageRecord.id)
                .where(EvidencePassageRecord.passage_hash == passage.passage_hash)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                return existing, True
            
            # Insert new passage
            record_data = passage_to_record(passage)
            record = EvidencePassageRecord(**record_data)
            session.add(record)
            await session.flush()
            
            return passage.passage_id, False
    
    async def get(self, passage_id: str) -> Optional[EvidencePassage]:
        """Get passage by ID."""
        async with get_session() as session:
            result = await session.execute(
                select(EvidencePassageRecord)
                .where(EvidencePassageRecord.id == passage_id)
            )
            record = result.scalar_one_or_none()
            
            if record:
                return record_to_passage(record)
            return None
    
    async def find_by_evidence(self, evidence_id: str) -> list[EvidencePassage]:
        """Find passages by evidence ID."""
        async with get_session() as session:
            result = await session.execute(
                select(EvidencePassageRecord)
                .where(EvidencePassageRecord.evidence_id == evidence_id)
            )
            records = result.scalars().all()
            
            return [record_to_passage(r) for r in records]
