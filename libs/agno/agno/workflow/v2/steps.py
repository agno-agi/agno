from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Iterator, List, Optional, Union

from agno.run.response import RunResponseEvent
from agno.run.team import TeamRunResponseEvent
from agno.run.v2.workflow import (
    WorkflowRunResponse,
    WorkflowRunResponseEvent,
)
from agno.workflow.v2.step import Step
from agno.workflow.v2.types import StepInput, StepOutput

WorkflowSteps = List[
    Union[
        Callable[
            [StepInput], Union[StepOutput, Awaitable[StepOutput], Iterator[StepOutput], AsyncIterator[StepOutput]]
        ],
        Step,
        "Steps",
        "Loop",
        "Parallel",
        "Condition",
    ]
]


@dataclass
class Steps:
    """A pipeline of steps that execute in order"""

    # Steps to execute
    steps: WorkflowSteps

    # Pipeline_name identification
    name: Optional[str] = None
    description: Optional[str] = None

    def __init__(
        self, name: Optional[str] = None, description: Optional[str] = None, steps: Optional[List[Step]] = None
    ):
        self.name = name
        self.description = description
        self.steps = steps if steps else []

    def execute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> StepOutput:
        pass

    def execute_stream(
        self,
        step_input: StepInput,
        workflow_run_response: WorkflowRunResponse,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
    ) -> Iterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent]]:
        pass

    async def aexecute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> StepOutput:
        pass

    async def aexecute_stream(
        self,
        step_input: StepInput,
        workflow_run_response: WorkflowRunResponse,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
    ) -> AsyncIterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent]]:
        pass
