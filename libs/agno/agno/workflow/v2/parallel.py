from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Iterator, List, Optional, Union

from agno.run.response import RunResponseEvent
from agno.run.team import TeamRunResponseEvent
from agno.run.v2.workflow import WorkflowRunResponse, WorkflowRunResponseEvent
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
class Parallel:
    """A list of steps that execute in parallel"""

    steps: WorkflowSteps

    name: Optional[str] = None
    description: Optional[str] = None

    def execute(
        self,
        step_input: StepInput,
        workflow_run_response: WorkflowRunResponse,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[StepOutput]:
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
        self,
        step_input: StepInput,
        workflow_run_response: WorkflowRunResponse,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[StepOutput]:
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
