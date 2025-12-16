"""
Workflow Orchestration
======================

Provides deterministic workflow execution for processing claims.
All workflow state transitions are logged for auditability.

Design Principles:
- Deterministic execution order
- Resumable from any checkpoint
- Complete audit trail of all transitions
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar

from shared.canonical_id import CanonicalId, EntityType, generate_canonical_id
from shared.hashing import deterministic_hash


class WorkflowStatus(str, Enum):
    """Status of a workflow execution."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Status of a workflow step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowStep:
    """A single step in a workflow."""

    id: str
    name: str
    handler: str  # Reference to handler function
    status: StepStatus = StepStatus.PENDING
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 3


@dataclass
class WorkflowContext:
    """
    Context passed through workflow execution.

    Contains all state needed for deterministic execution.
    """

    workflow_id: str
    claim_id: str
    trace_id: str
    current_step: str
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def get_state_hash(self) -> str:
        """Compute deterministic hash of current state."""
        return deterministic_hash(
            self.workflow_id,
            self.claim_id,
            self.current_step,
            self.data,
        )


@dataclass
class WorkflowDefinition:
    """
    Definition of a workflow with its steps.

    Workflows are defined declaratively and executed deterministically.
    """

    id: str
    name: str
    version: str
    steps: list[WorkflowStep]
    initial_step: str
    final_steps: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowExecution:
    """
    A running instance of a workflow.

    Tracks the complete execution state for resumability.
    """

    id: str
    definition_id: str
    claim_id: str
    status: WorkflowStatus
    current_step: str
    context: WorkflowContext
    steps: list[WorkflowStep]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class StepResult:
    """Result of executing a workflow step."""

    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    next_step: Optional[str] = None
    error: Optional[str] = None


# Type variable for step handlers
T = TypeVar("T")


class StepHandler(ABC, Generic[T]):
    """
    Abstract base for workflow step handlers.

    EXTENSION_POINT: A1+ will implement concrete step handlers.
    All handlers must be deterministic given the same input.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of this handler."""
        pass

    @abstractmethod
    async def execute(self, context: WorkflowContext) -> StepResult:
        """
        Execute the step with given context.

        Args:
            context: The workflow context

        Returns:
            Result of step execution

        Note:
            This method must be deterministic. Given the same context,
            it must produce the same result.
        """
        pass

    @abstractmethod
    async def validate_input(self, context: WorkflowContext) -> bool:
        """Validate that context contains required inputs."""
        pass

    @abstractmethod
    async def rollback(self, context: WorkflowContext) -> bool:
        """Rollback any changes made by this step."""
        pass


class WorkflowEngine(ABC):
    """
    Abstract workflow execution engine.

    EXTENSION_POINT: A1+ will implement concrete engine with persistence.
    """

    @abstractmethod
    async def create_workflow(
        self,
        definition: WorkflowDefinition,
        claim_id: str,
        initial_data: Optional[dict[str, Any]] = None,
    ) -> WorkflowExecution:
        """Create a new workflow execution."""
        pass

    @abstractmethod
    async def execute_step(
        self,
        execution_id: str,
    ) -> StepResult:
        """Execute the current step of a workflow."""
        pass

    @abstractmethod
    async def advance_workflow(
        self,
        execution_id: str,
        next_step: str,
    ) -> WorkflowExecution:
        """Advance workflow to the next step."""
        pass

    @abstractmethod
    async def pause_workflow(
        self,
        execution_id: str,
        reason: str,
    ) -> WorkflowExecution:
        """Pause a running workflow."""
        pass

    @abstractmethod
    async def resume_workflow(
        self,
        execution_id: str,
    ) -> WorkflowExecution:
        """Resume a paused workflow."""
        pass

    @abstractmethod
    async def cancel_workflow(
        self,
        execution_id: str,
        reason: str,
    ) -> WorkflowExecution:
        """Cancel a workflow."""
        pass

    @abstractmethod
    async def get_execution(
        self,
        execution_id: str,
    ) -> Optional[WorkflowExecution]:
        """Get a workflow execution by ID."""
        pass

    @abstractmethod
    async def list_executions(
        self,
        claim_id: Optional[str] = None,
        status: Optional[WorkflowStatus] = None,
        limit: int = 100,
    ) -> list[WorkflowExecution]:
        """List workflow executions with optional filters."""
        pass


# Standard workflow definitions for the Truth Engine

CLAIM_PROCESSING_WORKFLOW = WorkflowDefinition(
    id="claim_processing_v1",
    name="Claim Processing Workflow",
    version="1.0.0",
    steps=[
        WorkflowStep(id="validate", name="Validate Claim", handler="validate_claim"),
        WorkflowStep(id="collect", name="Collect Evidence", handler="collect_evidence"),
        WorkflowStep(id="extract", name="Extract Data", handler="extract_data"),
        WorkflowStep(id="reason", name="Reason About Claim", handler="reason_claim"),
        WorkflowStep(id="version", name="Version Truth State", handler="version_truth"),
        WorkflowStep(id="audit", name="Create Audit Trail", handler="create_audit"),
    ],
    initial_step="validate",
    final_steps=["audit"],
    metadata={"description": "Standard workflow for processing financial solvency claims"},
)


class NullWorkflowEngine(WorkflowEngine):
    """
    Null implementation of workflow engine.

    EXTENSION_POINT: This is replaced with real engine in A1+.
    """

    def __init__(self) -> None:
        self._executions: dict[str, WorkflowExecution] = {}
        self._handlers: dict[str, StepHandler] = {}

    def register_handler(self, handler: StepHandler) -> None:
        """Register a step handler."""
        self._handlers[handler.name] = handler

    async def create_workflow(
        self,
        definition: WorkflowDefinition,
        claim_id: str,
        initial_data: Optional[dict[str, Any]] = None,
    ) -> WorkflowExecution:
        workflow_id = str(generate_canonical_id(EntityType.WORKFLOW))
        now = datetime.now(timezone.utc)

        context = WorkflowContext(
            workflow_id=workflow_id,
            claim_id=claim_id,
            trace_id=workflow_id,
            current_step=definition.initial_step,
            data=initial_data or {},
        )

        execution = WorkflowExecution(
            id=workflow_id,
            definition_id=definition.id,
            claim_id=claim_id,
            status=WorkflowStatus.PENDING,
            current_step=definition.initial_step,
            context=context,
            steps=definition.steps.copy(),
            created_at=now,
            updated_at=now,
        )

        self._executions[workflow_id] = execution
        return execution

    async def execute_step(self, execution_id: str) -> StepResult:
        execution = self._executions.get(execution_id)
        if not execution:
            return StepResult(success=False, error="Execution not found")

        # EXTENSION_POINT: Real step execution in A1+
        return StepResult(success=True, output={})

    async def advance_workflow(
        self,
        execution_id: str,
        next_step: str,
    ) -> WorkflowExecution:
        execution = self._executions.get(execution_id)
        if execution:
            execution.current_step = next_step
            execution.context.current_step = next_step
            execution.updated_at = datetime.now(timezone.utc)
        return execution  # type: ignore

    async def pause_workflow(
        self,
        execution_id: str,
        reason: str,
    ) -> WorkflowExecution:
        execution = self._executions.get(execution_id)
        if execution:
            execution.status = WorkflowStatus.PAUSED
            execution.updated_at = datetime.now(timezone.utc)
        return execution  # type: ignore

    async def resume_workflow(self, execution_id: str) -> WorkflowExecution:
        execution = self._executions.get(execution_id)
        if execution:
            execution.status = WorkflowStatus.RUNNING
            execution.updated_at = datetime.now(timezone.utc)
        return execution  # type: ignore

    async def cancel_workflow(
        self,
        execution_id: str,
        reason: str,
    ) -> WorkflowExecution:
        execution = self._executions.get(execution_id)
        if execution:
            execution.status = WorkflowStatus.CANCELLED
            execution.error = reason
            execution.updated_at = datetime.now(timezone.utc)
        return execution  # type: ignore

    async def get_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        return self._executions.get(execution_id)

    async def list_executions(
        self,
        claim_id: Optional[str] = None,
        status: Optional[WorkflowStatus] = None,
        limit: int = 100,
    ) -> list[WorkflowExecution]:
        results = []
        for execution in self._executions.values():
            if claim_id and execution.claim_id != claim_id:
                continue
            if status and execution.status != status:
                continue
            results.append(execution)
            if len(results) >= limit:
                break
        return results
