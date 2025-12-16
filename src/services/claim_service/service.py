"""
Claim Service Implementation - Production A3
==============================================

Production-grade service layer for claim processing.
Provides the interface between the API and the ClaimProcessor.

Design Principles:
- Service is stateless and side-effect-free
- All claim storage is in-memory (A3 scope)
- Operations are fully deterministic
- Complete audit trail for all operations
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel

from shared.canonical_id import EntityType, generate_canonical_id
from shared.hashing import hash_content
from shared.schemas import TruthStatus, ConfidenceLevel

from .processor import ClaimProcessor
from .schemas import (
    ClaimType,
    CanonicalSolvencyClaim,
    RequiredFactsContract,
    ClaimProcessingResult,
    ProcessClaimRequest,
    ProcessClaimResponse,
    SemanticRefusalCode,
)


# =============================================================================
# Legacy Dataclass (for backward compatibility)
# =============================================================================


@dataclass
class Claim:
    """
    Internal claim representation.
    
    Note: This is the legacy A0 structure. A3 uses CanonicalSolvencyClaim
    for solvency claims, but this is kept for interface compatibility.
    """

    id: str
    content: str
    content_hash: str
    status: TruthStatus
    confidence: Optional[ConfidenceLevel] = None
    source: Optional[str] = None
    organization_id: Optional[str] = None
    current_version: int = 1
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # A3 additions
    claim_type: Optional[ClaimType] = None
    canonical_claim: Optional[CanonicalSolvencyClaim] = None
    required_facts_contract: Optional[RequiredFactsContract] = None


class CreateClaimInput(BaseModel):
    """Input for creating a claim."""

    content: str
    source: Optional[str] = None
    organization_id: Optional[str] = None
    metadata: dict = {}


class UpdateClaimInput(BaseModel):
    """Input for updating a claim."""

    status: Optional[TruthStatus] = None
    confidence: Optional[ConfidenceLevel] = None
    metadata: Optional[dict] = None


class ClaimServiceInterface(ABC):
    """
    Abstract interface for Claim Service.
    
    A3 adds the process_solvency_claim method for production claim processing.
    """

    @abstractmethod
    async def create(self, input: CreateClaimInput) -> Claim:
        """Create a new claim (legacy interface)."""
        pass

    @abstractmethod
    async def get(self, claim_id: str) -> Optional[Claim]:
        """Get a claim by ID."""
        pass

    @abstractmethod
    async def update(self, claim_id: str, input: UpdateClaimInput) -> Optional[Claim]:
        """Update a claim."""
        pass

    @abstractmethod
    async def list(
        self,
        status: Optional[TruthStatus] = None,
        organization_id: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Claim], int]:
        """List claims with pagination."""
        pass

    @abstractmethod
    async def get_by_content_hash(self, content_hash: str) -> Optional[Claim]:
        """Get a claim by its content hash (for deduplication)."""
        pass
    
    @abstractmethod
    async def process_solvency_claim(
        self,
        request: ProcessClaimRequest,
    ) -> ProcessClaimResponse:
        """
        Process a solvency evaluation request into a canonical claim.
        
        This is the A3 production interface for claim processing.
        """
        pass
    
    @abstractmethod
    async def get_canonical_claim(
        self,
        claim_id: str,
    ) -> Optional[CanonicalSolvencyClaim]:
        """Get a canonical solvency claim by ID."""
        pass
    
    @abstractmethod
    async def get_required_facts_contract(
        self,
        claim_id: str,
    ) -> Optional[RequiredFactsContract]:
        """Get the required facts contract for a claim."""
        pass


class ClaimService(ClaimServiceInterface):
    """
    Claim Service implementation - Production A3.
    
    Provides claim processing with:
    - Semantic validation and refusals
    - Entity resolution and normalization
    - Required facts derivation
    - Deterministic processing guarantees
    """

    def __init__(self) -> None:
        """Initialize the claim service."""
        # In-memory storage (A3 scope - no database)
        self._claims: dict[str, Claim] = {}
        self._canonical_claims: dict[str, CanonicalSolvencyClaim] = {}
        self._required_facts_contracts: dict[str, RequiredFactsContract] = {}
        self._claim_hash_index: dict[str, str] = {}  # request_hash -> claim_id
        
        # Processor instance (stateless)
        self._processor = ClaimProcessor()

    async def create(self, input: CreateClaimInput) -> Claim:
        """Create a new claim (legacy interface for backward compatibility)."""
        claim_id = str(generate_canonical_id(EntityType.CLAIM))
        content_hash = str(hash_content(input.content))

        claim = Claim(
            id=claim_id,
            content=input.content,
            content_hash=content_hash,
            status=TruthStatus.PENDING,
            source=input.source,
            organization_id=input.organization_id,
            metadata=input.metadata,
        )

        self._claims[claim_id] = claim
        return claim

    async def get(self, claim_id: str) -> Optional[Claim]:
        """Get a claim by ID."""
        return self._claims.get(claim_id)

    async def update(self, claim_id: str, input: UpdateClaimInput) -> Optional[Claim]:
        """Update a claim."""
        claim = self._claims.get(claim_id)
        if not claim:
            return None

        if input.status is not None:
            claim.status = input.status
        if input.confidence is not None:
            claim.confidence = input.confidence
        if input.metadata is not None:
            claim.metadata.update(input.metadata)

        claim.updated_at = datetime.now(timezone.utc)
        return claim

    async def list(
        self,
        status: Optional[TruthStatus] = None,
        organization_id: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Claim], int]:
        """List claims with pagination."""
        filtered = list(self._claims.values())

        if status:
            filtered = [c for c in filtered if c.status == status]
        if organization_id:
            filtered = [c for c in filtered if c.organization_id == organization_id]

        total = len(filtered)
        return filtered[offset : offset + limit], total

    async def get_by_content_hash(self, content_hash: str) -> Optional[Claim]:
        """Get a claim by its content hash."""
        for claim in self._claims.values():
            if claim.content_hash == content_hash:
                return claim
        return None
    
    async def process_solvency_claim(
        self,
        request: ProcessClaimRequest,
    ) -> ProcessClaimResponse:
        """
        Process a solvency evaluation request into a canonical claim.
        
        This is the main A3 interface. It:
        1. Validates the claim semantically
        2. Resolves and normalizes entity identifiers
        3. Validates scenarios against entity type
        4. Derives the required facts contract
        5. Creates the canonical claim
        
        Returns a ProcessClaimResponse with either success or refusal information.
        """
        # Check for duplicate by request hash (idempotency)
        if request.request_hash in self._claim_hash_index:
            existing_claim_id = self._claim_hash_index[request.request_hash]
            existing_claim = self._canonical_claims.get(existing_claim_id)
            existing_contract = self._required_facts_contracts.get(existing_claim_id)
            
            if existing_claim and existing_contract:
                return ProcessClaimResponse(
                    success=True,
                    claim_id=existing_claim_id,
                    claim_hash=existing_claim.claim_hash,
                    required_facts_count=existing_contract.total_facts,
                    contract_id=existing_contract.contract_id,
                    warnings=["Duplicate request - returning existing claim"],
                    processing_time_ms=0,
                    trace_id=request.trace_id,
                )
        
        # Process the claim
        result = self._processor.process(
            api_request=request.api_request,
            request_hash=request.request_hash,
            trace_id=request.trace_id,
        )
        
        if not result.success:
            return ProcessClaimResponse(
                success=False,
                refused=True,
                refusal_codes=[r.code.value for r in result.semantic_refusals],
                refusal_messages=[r.message for r in result.semantic_refusals],
                warnings=result.warnings,
                processing_time_ms=result.processing_time_ms,
                trace_id=request.trace_id,
            )
        
        # Store the canonical claim and contract
        canonical_claim = result.canonical_claim
        contract = result.required_facts_contract
        
        if canonical_claim and contract:
            claim_id = canonical_claim.claim_id
            
            # Update contract with actual claim ID
            contract = RequiredFactsContract(
                contract_id=contract.contract_id,
                claim_id=claim_id,
                version=contract.version,
                required_facts=contract.required_facts,
                material_facts=contract.material_facts,
                supplementary_facts=contract.supplementary_facts,
                total_facts=contract.total_facts,
                categories_covered=contract.categories_covered,
                contract_hash=contract.contract_hash,
                generated_at=contract.generated_at,
            )
            
            self._canonical_claims[claim_id] = canonical_claim
            self._required_facts_contracts[claim_id] = contract
            self._claim_hash_index[request.request_hash] = claim_id
            
            # Also store in legacy format for backward compatibility
            legacy_claim = Claim(
                id=claim_id,
                content=f"Solvency evaluation for {canonical_claim.entity.name}",
                content_hash=canonical_claim.claim_hash,
                status=TruthStatus.PENDING,
                claim_type=ClaimType.SOLVENCY,
                canonical_claim=canonical_claim,
                required_facts_contract=contract,
                metadata={
                    "entity_classification": canonical_claim.entity_classification,
                    "jurisdiction": canonical_claim.jurisdiction,
                    "regulatory_framework": canonical_claim.regulatory_framework,
                },
            )
            self._claims[claim_id] = legacy_claim
            
            return ProcessClaimResponse(
                success=True,
                claim_id=claim_id,
                claim_hash=canonical_claim.claim_hash,
                required_facts_count=contract.total_facts,
                contract_id=contract.contract_id,
                warnings=result.warnings,
                processing_time_ms=result.processing_time_ms,
                trace_id=request.trace_id,
            )
        
        # Should not reach here
        return ProcessClaimResponse(
            success=False,
            refused=True,
            refusal_codes=["internal_error"],
            refusal_messages=["Failed to create canonical claim"],
            trace_id=request.trace_id,
        )
    
    async def get_canonical_claim(
        self,
        claim_id: str,
    ) -> Optional[CanonicalSolvencyClaim]:
        """Get a canonical solvency claim by ID."""
        return self._canonical_claims.get(claim_id)
    
    async def get_required_facts_contract(
        self,
        claim_id: str,
    ) -> Optional[RequiredFactsContract]:
        """Get the required facts contract for a claim."""
        return self._required_facts_contracts.get(claim_id)
    
    async def get_by_claim_hash(
        self,
        claim_hash: str,
    ) -> Optional[CanonicalSolvencyClaim]:
        """Get a canonical claim by its claim hash."""
        for claim in self._canonical_claims.values():
            if claim.claim_hash == claim_hash:
                return claim
        return None
