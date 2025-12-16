"""
Reasoning Engine - Pure Functional Implementation
===================================================

CRITICAL: This entire module MUST remain purely functional.
- No I/O operations
- No database access
- No network calls
- No mutable global state
- No side effects of any kind

All reasoning functions take immutable inputs and return outputs
without modifying any external state.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional, Protocol

from shared.hashing import deterministic_hash
from shared.schemas import TruthStatus, ConfidenceLevel


class EvidenceStrength(str, Enum):
    """Strength classification of evidence."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    IRRELEVANT = "irrelevant"


@dataclass(frozen=True)
class EvidenceItem:
    """
    Immutable evidence item for reasoning.

    This is the input representation of evidence, containing
    only the data needed for reasoning (no references to external state).
    """

    id: str
    content_hash: str
    source_type: str
    extracted_data: dict[str, Any]
    is_supporting: Optional[bool] = None
    strength: EvidenceStrength = EvidenceStrength.MODERATE


@dataclass(frozen=True)
class ClaimData:
    """
    Immutable claim data for reasoning.

    Contains all claim information needed for reasoning.
    """

    id: str
    content: str
    content_hash: str
    metadata: tuple[tuple[str, Any], ...] = ()  # Immutable dict alternative


@dataclass(frozen=True)
class ReasoningInput:
    """
    Complete immutable input for reasoning.

    This contains all data needed to reason about a claim.
    It is completely self-contained with no external dependencies.
    """

    claim: ClaimData
    evidence: tuple[EvidenceItem, ...]  # Immutable sequence
    context: tuple[tuple[str, Any], ...] = ()  # Immutable dict alternative
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def get_input_hash(self) -> str:
        """Compute deterministic hash of all input."""
        return deterministic_hash(
            self.claim.content_hash,
            tuple(e.content_hash for e in self.evidence),
            self.context,
        )


@dataclass(frozen=True)
class ReasoningStep:
    """An individual step in the reasoning process."""

    step_number: int
    description: str
    evidence_ids: tuple[str, ...]
    conclusion: str
    confidence: float


@dataclass(frozen=True)
class ReasoningOutput:
    """
    Complete immutable output from reasoning.

    Contains the truth determination and complete audit trail.
    """

    input_hash: str
    output_hash: str
    conclusion: TruthStatus
    confidence: ConfidenceLevel
    confidence_score: float  # 0.0 to 1.0
    supporting_evidence: tuple[str, ...]
    contradicting_evidence: tuple[str, ...]
    reasoning_steps: tuple[ReasoningStep, ...]
    explanation: str
    timestamp: datetime

    def verify_determinism(self, input: ReasoningInput) -> bool:
        """Verify that output hash matches input."""
        return self.input_hash == input.get_input_hash()


class ReasoningRule(Protocol):
    """
    Protocol for reasoning rules.

    EXTENSION_POINT: A1+ will implement concrete reasoning rules.
    Each rule must be a pure function.
    """

    def evaluate(
        self,
        claim: ClaimData,
        evidence: tuple[EvidenceItem, ...],
    ) -> tuple[TruthStatus, float, str]:
        """
        Evaluate claim against evidence.

        Args:
            claim: The claim to evaluate
            evidence: Available evidence

        Returns:
            Tuple of (conclusion, confidence_score, explanation)
        """
        ...


def _classify_confidence(score: float) -> ConfidenceLevel:
    """Convert numeric confidence to level. Pure function."""
    if score >= 0.8:
        return ConfidenceLevel.HIGH
    elif score >= 0.5:
        return ConfidenceLevel.MEDIUM
    elif score > 0.0:
        return ConfidenceLevel.LOW
    else:
        return ConfidenceLevel.UNKNOWN


def _partition_evidence(
    evidence: tuple[EvidenceItem, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Partition evidence into supporting and contradicting. Pure function."""
    supporting = tuple(e.id for e in evidence if e.is_supporting is True)
    contradicting = tuple(e.id for e in evidence if e.is_supporting is False)
    return supporting, contradicting


def reason_about_claim(input: ReasoningInput) -> ReasoningOutput:
    """
    The core pure reasoning function.

    CRITICAL: This function MUST be pure - no side effects.
    Given the same input, it MUST produce the same output.

    Args:
        input: Complete immutable reasoning input

    Returns:
        Complete immutable reasoning output

    EXTENSION_POINT: A1+ will implement actual reasoning logic.
    This A0 version provides the structure but no real logic.
    """
    # Compute input hash for auditability
    input_hash = input.get_input_hash()

    # Partition evidence
    supporting, contradicting = _partition_evidence(input.evidence)

    # EXTENSION_POINT: A1+ will implement real reasoning rules
    # For A0, we just return a placeholder result
    reasoning_steps = (
        ReasoningStep(
            step_number=1,
            description="EXTENSION_POINT: Real reasoning implemented in A1+",
            evidence_ids=tuple(e.id for e in input.evidence),
            conclusion="pending",
            confidence=0.0,
        ),
    )

    conclusion = TruthStatus.PENDING
    confidence_score = 0.0
    explanation = (
        "A0 Foundation: Reasoning logic will be implemented in A1+. "
        f"Input contains {len(input.evidence)} evidence items."
    )

    # Compute output hash
    output_data = (
        conclusion.value,
        confidence_score,
        supporting,
        contradicting,
        reasoning_steps,
    )
    output_hash = deterministic_hash(input_hash, output_data)

    timestamp = datetime.now(timezone.utc)

    return ReasoningOutput(
        input_hash=input_hash,
        output_hash=output_hash,
        conclusion=conclusion,
        confidence=_classify_confidence(confidence_score),
        confidence_score=confidence_score,
        supporting_evidence=supporting,
        contradicting_evidence=contradicting,
        reasoning_steps=reasoning_steps,
        explanation=explanation,
        timestamp=timestamp,
    )


class ReasoningEngine:
    """
    Reasoning Engine coordinator.

    Note: While this class has state (registered rules), the actual
    reasoning operations are pure functions. The class merely
    coordinates which rules to apply.

    EXTENSION_POINT: A1+ will register actual reasoning rules.
    """

    def __init__(self) -> None:
        self._rules: list[ReasoningRule] = []
        self._version = "0.1.0"

    @property
    def version(self) -> str:
        """Engine version for audit trails."""
        return self._version

    def register_rule(self, rule: ReasoningRule) -> None:
        """Register a reasoning rule."""
        self._rules.append(rule)

    def reason(self, input: ReasoningInput) -> ReasoningOutput:
        """
        Execute reasoning on input.

        This delegates to the pure reason_about_claim function.
        """
        return reason_about_claim(input)

    def verify_output(self, input: ReasoningInput, output: ReasoningOutput) -> bool:
        """
        Verify that an output is valid for the given input.

        This enables replay verification for auditing.
        """
        expected = self.reason(input)
        return expected.output_hash == output.output_hash


# Factory function for creating configured engines
def create_reasoning_engine() -> ReasoningEngine:
    """
    Create a configured reasoning engine.

    EXTENSION_POINT: A1+ will register real reasoning rules here.
    """
    engine = ReasoningEngine()
    # EXTENSION_POINT: Register rules in A1+
    # engine.register_rule(FinancialRatioRule())
    # engine.register_rule(BalanceSheetRule())
    return engine
