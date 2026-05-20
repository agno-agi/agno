from unittest.mock import MagicMock

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from agno.os.interfaces.agui.router import run_agent, run_team


class FakeRunInput:
    def __init__(self):
        self.messages = [MagicMock(role="user", content="test")]
        self.thread_id = "test-thread"
        self.run_id = "test-run"
        self.forwarded_props = None
        self.state = None


class CaptureKwargsTeam:
    def __init__(self):
        self.captured_kwargs = {}

    async def arun(self, **kwargs):
        self.captured_kwargs = kwargs
        return
        yield


class CaptureKwargsAgent:
    def __init__(self):
        self.captured_kwargs = {}

    async def arun(self, **kwargs):
        self.captured_kwargs = kwargs
        return
        yield


@pytest.mark.asyncio
async def test_run_team_passes_stream_events_not_stream_steps():
    fake_team = CaptureKwargsTeam()
    run_input = FakeRunInput()

    events = []
    async for event in run_team(fake_team, run_input):
        events.append(event)

    assert fake_team.captured_kwargs.get("stream") is True
    assert fake_team.captured_kwargs.get("stream_events") is True
    assert "stream_steps" not in fake_team.captured_kwargs


@pytest.mark.asyncio
async def test_run_agent_passes_stream_events():
    fake_agent = CaptureKwargsAgent()
    run_input = FakeRunInput()

    events = []
    async for event in run_agent(fake_agent, run_input):
        events.append(event)

    assert fake_agent.captured_kwargs.get("stream") is True
    assert fake_agent.captured_kwargs.get("stream_events") is True
    assert "stream_steps" not in fake_agent.captured_kwargs
