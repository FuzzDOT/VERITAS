"""
Truth Orchestrator Service
==========================

Coordinates the workflow for processing claims through the truth verification pipeline.
Ensures deterministic execution order and maintains workflow state.
"""

from services.truth_orchestrator.app import create_app
from services.truth_orchestrator.service import TruthOrchestratorService

__all__ = ["create_app", "TruthOrchestratorService"]
