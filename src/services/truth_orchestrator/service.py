"""
Truth Orchestrator Service Implementation
==========================================

The orchestrator coordinates the entire truth verification workflow.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from shared.canonical_id import CanonicalId
from shared.schemas import TruthStatus, ConfidenceLevel
from infrastructure.workflow import (
    WorkflowEngine,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowStatus,
    CLAIM_PROCESSING_WORKFLOW,
)


@dataclass
class OrchestrationRequest:
    """Request to orchestrate claim processing."""

    claim_id: str
    priority: int = 0
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class OrchestrationResult:
    """Result of an orchestration operation."""

    workflow_id: str
    claim_id: str
    status: WorkflowStatus
    current_step: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    final_status: Optional[TruthStatus] = None
    final_confidence: Optional[ConfidenceLevel] = None


class TruthOrchestratorInterface(ABC):
    """
    Abstract interface for the Truth Orchestrator.

    EXTENSION_POINT: A1+ will implement the full orchestration logic.
    """

    @abstractmethod
    async def start_processing(self, request: OrchestrationRequest) -> OrchestrationResult:
        """
        Start processing a claim through the truth verification workflow.

        Args:
            request: The orchestration request

        Returns:
            Initial orchestration result with workflow ID
        """
        pass

    @abstractmethod
    async def get_status(self, workflow_id: str) -> Optional[OrchestrationResult]:
        """
        Get the current status of an orchestration.

        Args:
            workflow_id: The workflow ID

        Returns:
            Current orchestration result or None if not found
        """
        pass

    @abstractmethod
    async def pause_processing(self, workflow_id: str, reason: str) -> OrchestrationResult:
        """Pause a running workflow."""
        pass

    @abstractmethod
    async def resume_processing(self, workflow_id: str) -> OrchestrationResult:
        """Resume a paused workflow."""
        pass

    @abstractmethod
    async def cancel_processing(self, workflow_id: str, reason: str) -> OrchestrationResult:
        """Cancel a workflow."""
        pass


class TruthOrchestratorService(TruthOrchestratorInterface):
    """
    Truth Orchestrator Service implementation.

    EXTENSION_POINT: This implementation provides the interface structure.
    A1+ will add real workflow coordination logic.
    """

    def __init__(self, workflow_engine: WorkflowEngine) -> None:
        self._engine = workflow_engine
        self._workflow_definition = CLAIM_PROCESSING_WORKFLOW

    async def start_processing(self, request: OrchestrationRequest) -> OrchestrationResult:
        """Start processing a claim."""
        # EXTENSION_POINT: A1+ will implement full workflow initiation
        execution = await self._engine.create_workflow(
            definition=self._workflow_definition,
            claim_id=request.claim_id,
            initial_data=request.metadata,
        )

        return OrchestrationResult(
            workflow_id=execution.id,
            claim_id=execution.claim_id,
            status=execution.status,
            current_step=execution.current_step,
            started_at=execution.created_at,
        )

    async def get_status(self, workflow_id: str) -> Optional[OrchestrationResult]:
        """Get workflow status."""
        execution = await self._engine.get_execution(workflow_id)
        if not execution:
            return None

        return OrchestrationResult(
            workflow_id=execution.id,
            claim_id=execution.claim_id,
            status=execution.status,
            current_step=execution.current_step,
            started_at=execution.created_at,
            completed_at=execution.completed_at,
        )

    async def pause_processing(self, workflow_id: str, reason: str) -> OrchestrationResult:
        """Pause workflow."""
        execution = await self._engine.pause_workflow(workflow_id, reason)
        return OrchestrationResult(
            workflow_id=execution.id,
            claim_id=execution.claim_id,
            status=execution.status,
            current_step=execution.current_step,
            started_at=execution.created_at,
        )

    async def resume_processing(self, workflow_id: str) -> OrchestrationResult:
        """Resume workflow."""
        execution = await self._engine.resume_workflow(workflow_id)
        return OrchestrationResult(
            workflow_id=execution.id,
            claim_id=execution.claim_id,
            status=execution.status,
            current_step=execution.current_step,
            started_at=execution.created_at,
        )

    async def cancel_processing(self, workflow_id: str, reason: str) -> OrchestrationResult:
        """Cancel workflow."""
        execution = await self._engine.cancel_workflow(workflow_id, reason)
        return OrchestrationResult(
            workflow_id=execution.id,
            claim_id=execution.claim_id,
            status=execution.status,
            current_step=execution.current_step,
            started_at=execution.created_at,
        )
