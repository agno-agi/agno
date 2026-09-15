import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import EventType, RunAgentInput
from ag_ui.core.types import Context, UserMessage
from ag_ui.core.types import Tool as AGUITool
from ag_ui.core.types import ToolMessage as AGUIToolMessage

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.db.in_memory import InMemoryDb
from agno.os.interfaces.agui import router
from agno.os.interfaces.agui.router import run_entity
from agno.run.base import RunContext
from agno.team.remote import RemoteTeam
from agno.tools import tool

from .agui_stream_invariants import ScriptedModel


class FakeRunInput:
    def __init__(self, *, context=None, state=None, tools=None, messages=None):
        self.messages = messages if messages is not None else [MagicMock(role="user", content="test")]
        self.thread_id = "test-thread"
        self.run_id = "test-run"
        self.forwarded_props = None
        self.state = state
        self.context = context
        self.tools = tools


class CaptureKwargsEntity:
    def __init__(self):
        self.captured_kwargs = {}
        self.dependencies = None
        self.arun_called = False
        self.acontinue_run_called = False

    async def arun(self, **kwargs):
        self.captured_kwargs = kwargs
        self.arun_called = True
        return
        yield


def capturing_wire_stream(captured: dict):
    """Stand-in for the AgentOS client's stream methods: records the wire kwargs."""

    async def stream(**kwargs):
        captured.update(kwargs)
        return
        yield

    return stream


@pytest.mark.asyncio
async def test_run_entity_passes_stream_events():
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput()

    events = []
    async for event in run_entity(fake_entity, run_input):
        events.append(event)

    assert fake_entity.captured_kwargs.get("stream") is True
    assert fake_entity.captured_kwargs.get("stream_events") is True
    assert "stream_steps" not in fake_entity.captured_kwargs


@pytest.mark.asyncio
async def test_run_entity_no_context_omits_add_dependencies_flag():
    """No context means no add_dependencies_to_context passed."""
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput(context=None)

    async for _ in run_entity(fake_entity, run_input):
        pass

    assert "add_dependencies_to_context" not in fake_entity.captured_kwargs


@pytest.mark.asyncio
async def test_run_entity_with_context_passes_run_context_with_dependencies():
    """Context items are passed via run_context.dependencies with add_dependencies_to_context=True."""
    fake_entity = CaptureKwargsEntity()
    context = [MagicMock(description="user_name", value="Alice")]
    run_input = FakeRunInput(context=context)

    async for _ in run_entity(fake_entity, run_input):
        pass

    assert fake_entity.captured_kwargs.get("add_dependencies_to_context") is True
    run_context = fake_entity.captured_kwargs.get("run_context")
    assert run_context is not None
    assert run_context.dependencies == {"user_name": "Alice"}


@pytest.mark.asyncio
async def test_run_entity_passes_client_tools_in_run_context():
    fake_entity = CaptureKwargsEntity()
    agui_tools = [
        AGUITool(name="change_background", description="Change page background color"),
        AGUITool(name="show_modal", description="Show a modal dialog"),
    ]
    run_input = FakeRunInput(tools=agui_tools)

    async for _ in run_entity(fake_entity, run_input):
        pass

    run_context = fake_entity.captured_kwargs.get("run_context")
    assert run_context is not None
    assert run_context.client_tools is not None
    assert len(run_context.client_tools) == 2

    tool_names = [t.name for t in run_context.client_tools]
    assert "change_background" in tool_names
    assert "show_modal" in tool_names

    for client_tool in run_context.client_tools:
        assert client_tool.external_execution is True
        assert client_tool.external_execution_silent is True


@pytest.mark.asyncio
async def test_run_entity_no_client_tools_when_tools_none():
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput(tools=None)

    async for _ in run_entity(fake_entity, run_input):
        pass

    run_context = fake_entity.captured_kwargs.get("run_context")
    assert run_context is not None
    assert run_context.client_tools is None


@pytest.mark.asyncio
async def test_run_entity_no_client_tools_when_tools_empty():
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput(tools=[])

    async for _ in run_entity(fake_entity, run_input):
        pass

    run_context = fake_entity.captured_kwargs.get("run_context")
    assert run_context is not None
    assert run_context.client_tools is None


@pytest.mark.asyncio
async def test_run_entity_passes_user_id_to_arun():
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput()

    async for _ in run_entity(fake_entity, run_input, user_id="test-user-123"):
        pass

    assert fake_entity.captured_kwargs.get("user_id") == "test-user-123"
    run_context = fake_entity.captured_kwargs.get("run_context")
    assert run_context.user_id == "test-user-123"


@pytest.mark.asyncio
async def test_run_entity_fresh_run_calls_arun():
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput()

    async for _ in run_entity(fake_entity, run_input):
        pass

    assert fake_entity.arun_called is True


@pytest.mark.asyncio
async def test_run_entity_remote_agent_sends_wire_fields_instead_of_run_context():
    """A RunContext cannot cross the wire: the remote proxy would post it as a stringified form field."""
    remote_agent = RemoteAgent(base_url="http://fake-host", agent_id="remote-agent")
    captured: dict = {}
    remote_agent.agentos_client = MagicMock(run_agent_stream=capturing_wire_stream(captured))
    context = [MagicMock(description="user_name", value="Alice")]
    run_input = FakeRunInput(context=context, state={"counter": 1})

    events = [event async for event in run_entity(remote_agent, run_input, user_id="test-user-123")]

    assert "run_context" not in captured
    assert captured["session_state"] == {"counter": 1}
    assert captured["dependencies"] == {"user_name": "Alice"}
    assert captured["add_dependencies_to_context"] is True
    assert captured["session_id"] == "test-thread"
    assert captured["user_id"] == "test-user-123"
    assert captured["run_id"] == "test-run"
    assert events[-1].type == EventType.RUN_FINISHED


@pytest.mark.asyncio
async def test_run_entity_remote_team_sends_wire_fields_instead_of_run_context():
    remote_team = RemoteTeam(base_url="http://fake-host", team_id="remote-team")
    captured: dict = {}
    remote_team.agentos_client = MagicMock(run_team_stream=capturing_wire_stream(captured))
    run_input = FakeRunInput(state={"counter": 1})

    events = [event async for event in run_entity(remote_team, run_input)]

    assert "run_context" not in captured
    assert captured["session_state"] == {"counter": 1}
    assert captured["session_id"] == "test-thread"
    assert captured["run_id"] == "test-run"
    assert events[-1].type == EventType.RUN_FINISHED


@pytest.mark.asyncio
async def test_run_entity_remote_agent_warns_and_drops_client_tools(caplog):
    """Client tools resolve against this process's session, so a remote run proceeds without them."""
    remote_agent = RemoteAgent(base_url="http://fake-host", agent_id="remote-agent")
    captured: dict = {}
    remote_agent.agentos_client = MagicMock(run_agent_stream=capturing_wire_stream(captured))
    run_input = FakeRunInput(tools=[AGUITool(name="change_background", description="Change page background color")])

    with caplog.at_level(logging.WARNING, logger="agno"):
        events = [event async for event in run_entity(remote_agent, run_input)]

    assert "run_context" not in captured
    assert any("client tools are not forwarded" in record.message for record in caplog.records)
    assert events[-1].type == EventType.RUN_FINISHED


# --- Options a resumed run must not be handed ---------------------------------


DEPENDENCIES_THE_TOOL_SAW: list = []


@tool(requires_confirmation=True)
def send_email(to: str, run_context: RunContext) -> str:
    DEPENDENCIES_THE_TOOL_SAW.append(dict(run_context.dependencies or {}))
    return f"Email sent to {to}"


def _request(*, context=None, trailing=None):
    """The request the route reads, carrying a prompt and optionally an answer."""
    messages = [UserMessage(id="m1", role="user", content="email ops@example.com")]
    messages.extend(trailing or [])
    return RunAgentInput(
        thread_id="deps-session",
        run_id=str(uuid4()),
        state={},
        messages=messages,
        tools=[],
        context=context or [],
        forwarded_props={},
    )


def _confirmation(tool_call_id: str):
    return AGUIToolMessage(
        id="answer-1",
        role="tool",
        content=json.dumps({"accepted": True}),
        tool_call_id=tool_call_id,
    )


@pytest.mark.asyncio
async def test_resumed_run_is_not_handed_the_fresh_run_dependency_option():
    """``add_dependencies_to_context`` is a fresh-run option, and a resume must not carry it.

    The continue entry point does not declare it, so it lands in that call's
    catch-all keywords and is splatted into the run's post-hook arguments, where
    a hook taking ``**kwargs`` is handed an option on turn two that turn one
    never handed it. Nothing on the continue path reads it as an option: it is
    read while a user message is built, and a continue replays the paused run's
    stored messages rather than building one. The request's context still
    reaches the resumed run, through the run context, which is the other half
    pinned here.
    """
    DEPENDENCIES_THE_TOOL_SAW.clear()
    hook_arguments: list = []

    def record_hook_arguments(**kwargs):
        hook_arguments.append(dict(kwargs))

    agent = Agent(
        id="dependency-agent",
        model=ScriptedModel(
            "m",
            [("tool", "send_email", {"to": "ops@example.com"}, "tc-1"), ("content", "Sent.")],
        ),
        db=InMemoryDb(),
        tools=[send_email],
        post_hooks=[record_hook_arguments],
        telemetry=False,
    )
    context = [Context(description="user_name", value="Alice")]

    async for _ in run_entity(agent, _request(context=context)):
        pass

    request = _request(context=context, trailing=[_confirmation("tc-1")])
    resumed = [event async for event in run_entity(agent, request)]

    assert [event.message for event in resumed if event.type == EventType.RUN_ERROR] == []
    assert hook_arguments, "the resumed run ran no post hook, so it pins nothing"
    handed = [sorted(args) for args in hook_arguments if "add_dependencies_to_context" in args]
    assert handed == [], f"a resumed run's post hook was handed a fresh-run option: {handed}"
    assert DEPENDENCIES_THE_TOOL_SAW == [{"user_name": "Alice"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel, extra_input",
    [
        ("resume_paused_run_from_entries", {"resume": [SimpleNamespace(interrupt_id="i-1")]}),
        ("resume_paused_run", {"messages": [MagicMock(role="user", content="go"), MagicMock(role="tool")]}),
    ],
    ids=["resume-array", "tool-messages"],
)
async def test_neither_resume_channel_is_handed_the_fresh_run_dependency_option(channel, extra_input, monkeypatch):
    """Both channels resume through the same continue entry point, which takes no such option."""
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs["run_kwargs"])

        async def nothing():
            return
            yield

        return nothing()

    monkeypatch.setattr(router, channel, capture)
    run_input = FakeRunInput(context=[MagicMock(description="user_name", value="Alice")])
    for name, value in extra_input.items():
        setattr(run_input, name, value)

    async for _ in run_entity(MagicMock(), run_input):
        pass

    assert "add_dependencies_to_context" not in captured
