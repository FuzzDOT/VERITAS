"""
Reasoning Engine
================

Pure, side-effect-free reasoning functions for truth determination.
This engine evaluates claims against evidence to produce truth judgments.

CRITICAL DESIGN PRINCIPLE:
All functions in this module must be PURE - no side effects, no I/O,
no database access, no network calls. Given the same inputs, they
must always produce the same outputs.
"""

from services.reasoning_engine.engine import (
    ReasoningEngine,
    ReasoningInput,
    ReasoningOutput,
    ClaimData,
    EvidenceItem,
    EvidenceStrength,
    ReasoningStep,
    reason_about_claim,
)

__all__ = [
    "ReasoningEngine",
    "ReasoningInput",
    "ReasoningOutput",
    "ClaimData",
    "EvidenceItem",
    "EvidenceStrength",
    "ReasoningStep",
    "reason_about_claim",
]
