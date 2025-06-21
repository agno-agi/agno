from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Iterator, List, Optional, Union

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
class Condition:
    """A condition that executes a step (or list of steps) if the condition is met"""

    # Evaluator can be a async or sync function, or a boolean
    # If it is a function, it has to return the step/steps to execute
    # If it is a boolean, it will be used to determine if all the provided steps should be executed
    evaluator: Union[Callable[[Any], Union[bool, Step, List[Step], Awaitable[Step], Awaitable[List[Step]]]]]
    steps: WorkflowSteps

    name: Optional[str] = None
    description: Optional[str] = None

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
