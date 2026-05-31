import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from agno.os.interfaces.agui.router import run_agent, run_team


class FakeRunInput:
    def __init__(self, context=None):
        self.messages = [MagicMock(role="user", content="test")]
        self.thread_id = "test-thread"
        self.run_id = "test-run"
        self.forwarded_props = None
        self.state = None
        self.context = context


class CaptureKwargsTeam:
    def __init__(self, dependencies=None):
        self.dependencies = dependencies
        self.captured_kwargs = {}

    async def arun(self, **kwargs):
        self.captured_kwargs = kwargs
        return
        yield


class CaptureKwargsAgent:
    def __init__(self, dependencies=None):
        self.dependencies = dependencies
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
    assert "dependencies" not in fake_team.captured_kwargs
    assert "add_dependencies_to_context" not in fake_team.captured_kwargs


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
    assert "dependencies" not in fake_agent.captured_kwargs
    assert "add_dependencies_to_context" not in fake_agent.captured_kwargs


@pytest.mark.asyncio
async def test_run_agent_adds_agui_context_to_input():
    fake_agent = CaptureKwargsAgent(dependencies={"robot_name": "Anna"})
    context = [
        MagicMock(description="Visible movies", value='{"count": 2, "movies": ["Apex", "Hoppers"]}'),
        MagicMock(description="Search query", value="family movies"),
        MagicMock(description="Search query", value="new releases"),
    ]
    run_input = FakeRunInput(context=context)

    events = []
    async for event in run_agent(fake_agent, run_input):
        events.append(event)

    assert "dependencies" not in fake_agent.captured_kwargs
    assert "add_dependencies_to_context" not in fake_agent.captured_kwargs
    assert fake_agent.captured_kwargs["input"] == "test"
    context_message = fake_agent.captured_kwargs["additional_input"][0]
    context_json = context_message.content.removeprefix("<additional context>\n").removesuffix(
        "\n</additional context>"
    )
    assert context_message.role == "user"
    assert context_message.add_to_agent_memory is False
    assert context_message.temporary is False
    assert json.loads(context_json) == {
        "agui_context": [
            {"description": "Visible movies", "value": {"count": 2, "movies": ["Apex", "Hoppers"]}},
            {"description": "Search query", "value": "family movies"},
            {"description": "Search query", "value": "new releases"},
        ],
    }


@pytest.mark.asyncio
async def test_run_team_adds_agui_context_to_input():
    fake_team = CaptureKwargsTeam(dependencies={"team_mode": "route"})
    context = [MagicMock(description="Visible movies", value='{"count": 1, "movies": ["Apex"]}')]
    run_input = FakeRunInput(context=context)

    events = []
    async for event in run_team(fake_team, run_input):
        events.append(event)

    assert "dependencies" not in fake_team.captured_kwargs
    assert "add_dependencies_to_context" not in fake_team.captured_kwargs
    assert fake_team.captured_kwargs["input"] == "test"
    context_message = fake_team.captured_kwargs["additional_input"][0]
    context_json = context_message.content.removeprefix("<additional context>\n").removesuffix(
        "\n</additional context>"
    )
    assert context_message.role == "user"
    assert context_message.add_to_agent_memory is False
    assert context_message.temporary is False
    assert json.loads(context_json) == {
        "agui_context": [{"description": "Visible movies", "value": {"count": 1, "movies": ["Apex"]}}],
    }
