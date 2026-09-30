import json
import logging
from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import EventType, RunAgentInput
from ag_ui.core.types import Tool as AGUITool

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.os.interfaces.agui.router import run_entity
from agno.team.remote import RemoteTeam


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

    for tool in run_context.client_tools:
        assert tool.external_execution is True
        assert tool.external_execution_silent is True


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


# =============================================================================
# Routing a trailing tool result: resume versus fresh turn
# =============================================================================

CLICK_TOOL_NAME = "log_a2ui_event"
CLICK_RESULT = (
    'User performed action "bookHotel" on surface "luxury-hotels" '
    '(component: hotel-card). Context: {"hotelName":"The Ritz-Carlton"}'
)
STALE_USER_TURN = "Show me three luxury hotels as cards, each with a Book button."


class ScriptedModel(Model):
    """Offline model that records the messages each turn was handed.

    Script entries are one turn each: ``("tool", name, args, call_id)`` or
    ``("content", text)``. The recorded turns are where an input the interface
    built for the model can be read back.
    """

    def __init__(self, script: List[tuple]):
        super().__init__(id="m-scripted", name="m-scripted", provider="test")
        self._script = list(script)
        self._i = 0
        self.turns: List[List[Any]] = []

    def _next(self, kwargs: dict) -> ModelResponse:
        self.turns.append(list(kwargs.get("messages") or []))
        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tool":
            _, name, args, call_id = turn
            response = ModelResponse(role="assistant")
            response.tool_calls = [
                {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            ]
            return response
        response = ModelResponse(content=turn[1], role="assistant")
        response.event = ModelResponseEvent.assistant_response.value
        return response

    def invoke(self, *args: Any, **kwargs: Any):
        return self._next(kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any):
        return self._next(kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any):
        yield self._next(kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any):
        yield self._next(kwargs)

    def parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


def surface_action_input(session_id: str, tool_call_id: str = "767065f4-7cc3-42d4") -> Any:
    """The request an A2UI surface-action click sends.

    Shape taken from a captured click: no new user message, and a trailing tool
    result for a tool call the client minted, which the backend never emitted
    and was never offered in ``tools``.
    """
    return RunAgentInput.model_validate(
        {
            "threadId": session_id,
            "runId": "click-run",
            "state": None,
            "messages": [
                {"id": "u1", "role": "user", "content": STALE_USER_TURN},
                {"id": "a1", "role": "assistant", "content": "Here are three luxury hotel options."},
                {
                    "id": "a2",
                    "role": "assistant",
                    "toolCalls": [
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {"name": CLICK_TOOL_NAME, "arguments": json.dumps({"name": "bookHotel"})},
                        }
                    ],
                },
                {"id": "t1", "role": "tool", "toolCallId": tool_call_id, "content": CLICK_RESULT},
            ],
            "tools": [
                {
                    "name": "render_a2ui",
                    "description": "Render an A2UI surface.",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
            "context": [],
            "forwardedProps": {"a2uiAction": {"userAction": {"name": "bookHotel"}}},
        }
    )


def user_turn_input(session_id: str, content: str) -> Any:
    return RunAgentInput.model_validate(
        {
            "threadId": session_id,
            "runId": "turn-run",
            "state": None,
            "messages": [{"id": "u1", "role": "user", "content": content}],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
    )


def echoed_confirmation_input(session_id: str, tool_call_id: str) -> Any:
    """A HITL answer: the client echoes back the tool call id the backend paused on."""
    return RunAgentInput.model_validate(
        {
            "threadId": session_id,
            "runId": "resume-run",
            "state": None,
            "messages": [
                {"id": "u1", "role": "user", "content": "Email a@example.com"},
                {
                    "id": "a1",
                    "role": "assistant",
                    "toolCalls": [
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {"name": "send_email", "arguments": "{}"},
                        }
                    ],
                },
                {
                    "id": "t1",
                    "role": "tool",
                    "toolCallId": tool_call_id,
                    "content": json.dumps({"accepted": True}),
                },
            ],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
    )


def build_agent(tmp_path: Any, script: List[tuple], tools: Optional[List[Any]] = None) -> Any:
    db = SqliteDb(db_file=str(tmp_path / "agui_routing.db"))
    return Agent(
        id="routing-agent",
        name="Routing Agent",
        model=ScriptedModel(script),
        db=db,
        tools=tools,
        telemetry=False,
    )


def turn_text(model: ScriptedModel) -> str:
    """Everything the model was given on its last turn, flattened."""
    return "\n".join(f"{getattr(m, 'role', '')}: {getattr(m, 'content', '') or ''}" for m in model.turns[-1])


@pytest.mark.asyncio
async def test_a_tool_result_nothing_paused_on_runs_a_fresh_turn(tmp_path):
    """A surface-action click is not a resume, and must not be routed as one."""
    agent = build_agent(tmp_path, [("content", "Booked.")])
    session_id = "s-click"

    async for _ in run_entity(agent, user_turn_input(session_id, STALE_USER_TURN)):
        pass

    events = [event async for event in run_entity(agent, surface_action_input(session_id))]
    types = [event.type for event in events]

    assert EventType.RUN_ERROR not in types, [event.message for event in events if event.type == EventType.RUN_ERROR]
    assert types[-1] == EventType.RUN_FINISHED


@pytest.mark.asyncio
async def test_a_tool_result_nothing_paused_on_reaches_the_model(tmp_path):
    """The click is what is new in the turn, so the stale user message must not stand in for it."""
    agent = build_agent(tmp_path, [("content", "Booked.")])
    session_id = "s-click-input"

    async for _ in run_entity(agent, user_turn_input(session_id, STALE_USER_TURN)):
        pass
    async for _ in run_entity(agent, surface_action_input(session_id)):
        pass

    text = turn_text(agent.model)
    assert "bookHotel" in text
    assert "The Ritz-Carlton" in text
    # The stale turn is already answered and belongs to history, not to this input.
    assert f"user: {STALE_USER_TURN}" not in text


@pytest.mark.asyncio
async def test_an_echoed_pause_still_resumes_the_paused_run(tmp_path):
    """HITL echoes an id the backend paused on, so a paused run does match and is continued."""
    from agno.run.base import RunStatus
    from agno.tools import tool as tool_decorator

    @tool_decorator(requires_confirmation=True)
    def send_email(to: str) -> str:
        return f"Email sent to {to}"

    agent = build_agent(
        tmp_path,
        [("tool", "send_email", {"to": "a@example.com"}, "tc-send"), ("content", "Email sent.")],
        tools=[send_email],
    )
    session_id = "s-hitl"

    async for _ in run_entity(agent, user_turn_input(session_id, "Email a@example.com")):
        pass

    session = agent.db.get_session(session_id=session_id, session_type="agent")
    paused = [run for run in (session.runs or []) if run.status == RunStatus.paused]
    assert len(paused) == 1, "expected the send_email confirmation to pause the run"
    paused_run_id = paused[0].run_id

    events = [event async for event in run_entity(agent, echoed_confirmation_input(session_id, "tc-send"))]
    types = [event.type for event in events]

    assert EventType.RUN_ERROR not in types, [event.message for event in events if event.type == EventType.RUN_ERROR]
    session = agent.db.get_session(session_id=session_id, session_type="agent")
    resumed = next(run for run in (session.runs or []) if run.run_id == paused_run_id)
    assert resumed.status == RunStatus.completed
    # A resume continues the paused run; it never fabricates a turn out of the answer.
    assert "Result of the send_email tool call" not in turn_text(agent.model)
