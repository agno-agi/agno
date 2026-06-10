from unittest.mock import MagicMock

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from agno.os.interfaces.agui.router import run_agent, run_team


class FakeRunInput:
    def __init__(self, forwarded_props=None):
        self.messages = [MagicMock(role="user", content="test")]
        self.thread_id = "test-thread"
        self.run_id = "test-run"
        self.forwarded_props = forwarded_props
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


@pytest.mark.asyncio
async def test_run_agent_forwards_full_forwarded_props_as_metadata():
    fake_agent = CaptureKwargsAgent()
    forwarded_props = {"user_id": "user-1", "tenant_id": "acme", "trace_id": "abc-123"}
    run_input = FakeRunInput(forwarded_props=forwarded_props)

    async for _ in run_agent(fake_agent, run_input):
        pass

    # user_id is still extracted into its own argument
    assert fake_agent.captured_kwargs.get("user_id") == "user-1"
    # the full payload (incl. non-user_id fields) is preserved via metadata
    assert fake_agent.captured_kwargs.get("metadata") == {"forwarded_props": forwarded_props}


@pytest.mark.asyncio
async def test_run_team_forwards_full_forwarded_props_as_metadata():
    fake_team = CaptureKwargsTeam()
    forwarded_props = {"user_id": "user-2", "locale": "fr-FR", "feature_flags": {"beta": True}}
    run_input = FakeRunInput(forwarded_props=forwarded_props)

    async for _ in run_team(fake_team, run_input):
        pass

    assert fake_team.captured_kwargs.get("user_id") == "user-2"
    assert fake_team.captured_kwargs.get("metadata") == {"forwarded_props": forwarded_props}


@pytest.mark.asyncio
async def test_run_agent_no_forwarded_props_sends_no_metadata():
    fake_agent = CaptureKwargsAgent()
    run_input = FakeRunInput(forwarded_props=None)

    async for _ in run_agent(fake_agent, run_input):
        pass

    assert fake_agent.captured_kwargs.get("user_id") is None
    assert fake_agent.captured_kwargs.get("metadata") is None


@pytest.mark.asyncio
async def test_run_agent_ignores_non_dict_forwarded_props():
    fake_agent = CaptureKwargsAgent()
    run_input = FakeRunInput(forwarded_props="not-a-dict")

    async for _ in run_agent(fake_agent, run_input):
        pass

    assert fake_agent.captured_kwargs.get("user_id") is None
    assert fake_agent.captured_kwargs.get("metadata") is None
