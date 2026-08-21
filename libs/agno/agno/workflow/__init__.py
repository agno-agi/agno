from typing import TYPE_CHECKING, Any

from agno.workflow.agent import WorkflowAgent
from agno.workflow.cel import CEL_AVAILABLE, validate_cel_expression
from agno.workflow.condition import Condition
from agno.workflow.decorators import pause
from agno.workflow.factory import WorkflowFactory
from agno.workflow.loop import Loop
from agno.workflow.parallel import Parallel
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import HumanReview, OnError, OnReject, OnTimeout, StepInput, StepOutput, WorkflowExecutionInput
from agno.workflow.workflow import Workflow, get_workflow_by_id, get_workflows

if TYPE_CHECKING:
    from agno.workflow.remote import RemoteWorkflow

__all__ = [
    "Workflow",
    "WorkflowAgent",
    "WorkflowFactory",
    "RemoteWorkflow",
    "Steps",
    "Step",
    "Loop",
    "Parallel",
    "Condition",
    "Router",
    "WorkflowExecutionInput",
    "StepInput",
    "StepOutput",
    "OnReject",
    "OnError",
    "OnTimeout",
    "HumanReview",
    "get_workflow_by_id",
    "get_workflows",
    # CEL utilities
    "CEL_AVAILABLE",
    "validate_cel_expression",
    # Decorators
    "pause",
]


def __getattr__(name: str) -> Any:
    # Resolving RemoteWorkflow on first access keeps the remote-client stack
    # off the import path of everything that does not use it.
    if name == "RemoteWorkflow":
        from agno.workflow.remote import RemoteWorkflow

        return RemoteWorkflow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list:
    return sorted(set(globals()) | set(__all__))
