import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import RunAgentInput
from ag_ui.core.types import UserMessage

from agno.os.interfaces.agui.router import run_agent, run_team


def _build_run_input() -> RunAgentInput:
    """Build a minimal real RunAgentInput for router-level kwargs tests.

    Mirrors the canonical fixture pattern at
    ``tests/unit/app/test_agui_app.py:1672-1680``.
    """
    return RunAgentInput(
        thread_id="t1",
        run_id="r1",
        state={},
        messages=[UserMessage(id="u1", content="hello")],
        tools=[],
        context=[],
        forwarded_props=None,
    )


class CaptureKwargsTeam:
    def __init__(self):
        self.captured_kwargs = {}
        self.tools = []
        self.db = None

    async def arun(self, **kwargs):
        self.captured_kwargs = kwargs
        return
        yield


class CaptureKwargsAgent:
    def __init__(self):
        self.captured_kwargs = {}
        self.tools = []
        self.db = None

    async def arun(self, **kwargs):
        self.captured_kwargs = kwargs
        return
        yield


@pytest.mark.asyncio
async def test_run_team_passes_stream_events_not_stream_steps():
    fake_team = CaptureKwargsTeam()
    run_input = _build_run_input()

    events = []
    async for event in run_team(fake_team, run_input):
        events.append(event)

    assert fake_team.captured_kwargs.get("stream") is True
    assert fake_team.captured_kwargs.get("stream_events") is True
    assert "stream_steps" not in fake_team.captured_kwargs


@pytest.mark.asyncio
async def test_run_agent_passes_stream_events():
    fake_agent = CaptureKwargsAgent()
    run_input = _build_run_input()

    events = []
    async for event in run_agent(fake_agent, run_input):
        events.append(event)

    assert fake_agent.captured_kwargs.get("stream") is True
    assert fake_agent.captured_kwargs.get("stream_events") is True
    assert "stream_steps" not in fake_agent.captured_kwargs
