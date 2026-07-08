import pytest

from agno.agent import Agent
from agno.run.agent import RunErrorEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.workflow import WorkflowRunOutput
from agno.team import Team
from agno.workflow import Step
from agno.workflow.types import StepInput


class ErrorStreamingAgent(Agent):
    def __init__(self):
        super().__init__(id="error-agent", name="Error Agent", telemetry=False)

    def run(self, *args, **kwargs):
        yield RunErrorEvent(content="executor failed", error_type="RuntimeError")

    async def arun(self, *args, **kwargs):
        yield RunErrorEvent(content="executor failed", error_type="RuntimeError")


class ErrorStreamingTeam(Team):
    def __init__(self):
        super().__init__(id="error-team", name="Error Team", members=[])

    def run(self, *args, **kwargs):
        yield TeamRunErrorEvent(content="team failed", error_type="RuntimeError")

    async def arun(self, *args, **kwargs):
        yield TeamRunErrorEvent(content="team failed", error_type="RuntimeError")


def _workflow_run_response() -> WorkflowRunOutput:
    return WorkflowRunOutput(
        run_id="workflow-run",
        workflow_id="workflow",
        workflow_name="Workflow",
        session_id="session",
    )


def test_execute_stream_raises_executor_error_event():
    step = Step(name="error step", agent=ErrorStreamingAgent(), max_retries=0)

    with pytest.raises(RuntimeError, match="executor failed"):
        list(
            step.execute_stream(
                StepInput(input="run"),
                workflow_run_response=_workflow_run_response(),
                stream_executor_events=False,
            )
        )


def test_execute_stream_raises_team_executor_error_event():
    step = Step(name="error step", team=ErrorStreamingTeam(), max_retries=0)

    with pytest.raises(RuntimeError, match="team failed"):
        list(
            step.execute_stream(
                StepInput(input="run"),
                workflow_run_response=_workflow_run_response(),
                stream_executor_events=False,
            )
        )


@pytest.mark.asyncio
async def test_aexecute_stream_raises_executor_error_event():
    step = Step(name="error step", agent=ErrorStreamingAgent(), max_retries=0)

    with pytest.raises(RuntimeError, match="executor failed"):
        async for _ in step.aexecute_stream(
            StepInput(input="run"),
            workflow_run_response=_workflow_run_response(),
            stream_executor_events=False,
        ):
            pass


@pytest.mark.asyncio
async def test_aexecute_stream_raises_team_executor_error_event():
    step = Step(name="error step", team=ErrorStreamingTeam(), max_retries=0)

    with pytest.raises(RuntimeError, match="team failed"):
        async for _ in step.aexecute_stream(
            StepInput(input="run"),
            workflow_run_response=_workflow_run_response(),
            stream_executor_events=False,
        ):
            pass
