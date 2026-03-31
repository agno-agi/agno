import pytest

from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.team import Team
from agno.workflow import Step
from agno.workflow.types import StepInput, StepOutput


def build_error_only_team() -> Team:
    team = Team(name="error-only-team", members=[])

    def run(*args, **kwargs):
        yield TeamRunErrorEvent(content="team failed before producing a final output")

    async def arun(*args, **kwargs):
        yield TeamRunErrorEvent(content="team failed before producing a final output")

    team.run = run  # type: ignore[method-assign]
    team.arun = arun  # type: ignore[method-assign]
    return team


def test_execute_stream_skips_storing_missing_team_run_output():
    step = Step(name="team_step", team=build_error_only_team(), on_error="fail")

    events = list(
        step.execute_stream(
            StepInput(input="hello"),
            stream_events=True,
            store_executor_outputs=False,
        )
    )

    assert isinstance(events[0], TeamRunErrorEvent)
    assert isinstance(events[-1], StepOutput)
    assert events[-1].content == ""


@pytest.mark.asyncio
async def test_aexecute_stream_skips_storing_missing_team_run_output():
    step = Step(name="team_step", team=build_error_only_team(), on_error="fail")

    events = []
    async for event in step.aexecute_stream(
        StepInput(input="hello"),
        stream_events=True,
        store_executor_outputs=False,
    ):
        events.append(event)

    assert isinstance(events[0], TeamRunErrorEvent)
    assert isinstance(events[-1], StepOutput)
    assert events[-1].content == ""
