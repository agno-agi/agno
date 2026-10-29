"""Regression tests for member content events in route-mode team streams.

In route mode (``respond_directly``) the delegate tool sets ``show_result`` so the
member's reply also becomes the team's reply. The model layer then emits a
synthetic ``ModelResponse`` for the member's content event. The sync path also
forwarded the original member event, while the async path dropped it, so
``team.arun`` and AgentOS SSE lost the agent-identified ``RunContent`` delta.

These tests run fully offline with scripted models.
"""

import json
from collections import Counter
from typing import Any, AsyncIterator, Dict, Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.run.agent import RunContentEvent as AgentRunContentEvent
from agno.run.agent import RunErrorEvent as AgentRunErrorEvent
from agno.run.agent import RunEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import TeamRunEvent
from agno.team import Team
from agno.team.mode import TeamMode
from agno.tools import tool

INPUT = "tell me the secret"
MEMBER_TEXT = "MEMBER_SECRET_42"
MEMBER_ID = "member-1"
TEAM_ID = "route-team"


class ScriptedLeaderModel(Model):
    """Calls one tool, then answers (route mode never asks the leader again)."""

    def __init__(
        self,
        tool_name: str = "delegate_task_to_member",
        arguments: Optional[Dict[str, Any]] = None,
        final: Optional[str] = "leader final",
    ) -> None:
        super().__init__(id="leader-model", name="leader-model", provider="test")
        self.calls = 0
        self.tool_name = tool_name
        self.arguments = arguments if arguments is not None else {"member_id": MEMBER_ID, "task": "say the secret"}
        self.final = final

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": self.tool_name,
                            "arguments": json.dumps(self.arguments),
                        },
                    }
                ],
            )
        return ModelResponse(role="assistant", content=self.final)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class ScriptedMemberModel(Model):
    """Returns one fixed content chunk."""

    def __init__(self, body: str = MEMBER_TEXT) -> None:
        super().__init__(id="member-model", name="member-model", provider="test")
        self.body = body

    def _answer(self) -> ModelResponse:
        return ModelResponse(role="assistant", content=self.body)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._answer()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._answer()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._answer()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._answer()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class ScriptedConfirmationMemberModel(Model):
    """Calls a confirmation-gated tool, then answers once resumed."""

    def __init__(self) -> None:
        super().__init__(id="confirm-member-model", name="confirm-member-model", provider="test")
        self.calls = 0

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call-confirm",
                        "type": "function",
                        "function": {"name": "confirming_tool", "arguments": json.dumps({"city": "Tokyo"})},
                    }
                ],
            )
        return ModelResponse(role="assistant", content=MEMBER_TEXT)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _agui_run_input(thread_id: str, run_id: str) -> Any:
    from ag_ui.core import RunAgentInput, types

    return RunAgentInput(
        thread_id=thread_id,
        run_id=run_id,
        state={},
        messages=[types.UserMessage(id="user-1", content=INPUT)],
        tools=[],
        context=[],
        forwarded_props={},
    )


def _sse_frames(text: str) -> list[Dict[str, Any]]:
    return [json.loads(line[len("data:") :]) for line in text.splitlines() if line.startswith("data:")]


def _route_team(**kwargs: Any) -> Team:
    member = Agent(id=MEMBER_ID, name="Member One", model=ScriptedMemberModel())
    return Team(
        id=TEAM_ID,
        name="Route Team",
        mode=TeamMode.route,
        members=[member],
        model=ScriptedLeaderModel(),
        telemetry=False,
        **kwargs,
    )


def _team_run_id(events: list[Any]) -> str:
    for event in events:
        if getattr(event, "team_id", None) == TEAM_ID and getattr(event, "run_id", None):
            return event.run_id
    raise AssertionError("No team run id found in the event stream")


def _assert_route_content_events(events: list[Any]) -> None:
    """A route-mode stream carries both the team aggregate and the member delta."""
    team_run_id = _team_run_id(events)

    member_events = [event for event in events if event.event == RunEvent.run_content.value]
    assert len(member_events) == 1
    member_event = member_events[0]
    assert member_event.agent_id == MEMBER_ID
    assert member_event.agent_name == "Member One"
    assert member_event.content == MEMBER_TEXT
    assert member_event.run_id != team_run_id
    assert member_event.parent_run_id == team_run_id
    assert getattr(member_event, "team_id", None) is None

    team_events = [event for event in events if event.event == TeamRunEvent.run_content.value]
    assert len(team_events) == 1
    team_event = team_events[0]
    assert team_event.team_id == TEAM_ID
    assert team_event.team_name == "Route Team"
    assert team_event.run_id == team_run_id
    assert team_event.content == MEMBER_TEXT
    # The team-level event stays a team event: no member identity on it.
    assert not hasattr(team_event, "agent_id")
    assert "agent_id" not in team_event.to_dict()

    completed = [event for event in events if event.event == TeamRunEvent.run_completed.value]
    assert len(completed) == 1
    assert completed[0].content == MEMBER_TEXT
    assert [response.agent_id for response in completed[0].member_responses] == [MEMBER_ID]


def _content_signature(events: list[Any]) -> Counter:
    return Counter(
        (
            event.event,
            getattr(event, "agent_id", None),
            getattr(event, "team_id", None),
            event.content,
        )
        for event in events
        if event.event in {RunEvent.run_content.value, TeamRunEvent.run_content.value}
    )


def test_route_sync_stream_emits_member_content_event() -> None:
    events = list(_route_team().run(INPUT, stream=True, stream_events=True))
    _assert_route_content_events(events)


@pytest.mark.asyncio
async def test_route_async_stream_emits_member_content_event() -> None:
    events = [event async for event in _route_team().arun(INPUT, stream=True, stream_events=True)]
    _assert_route_content_events(events)


@pytest.mark.asyncio
async def test_route_sync_and_async_streams_carry_the_same_content_events() -> None:
    sync_events = list(_route_team().run(INPUT, stream=True, stream_events=True))
    async_events = [event async for event in _route_team().arun(INPUT, stream=True, stream_events=True)]

    assert _content_signature(async_events) == _content_signature(sync_events)


@pytest.mark.asyncio
async def test_route_async_stream_without_member_events_keeps_team_content() -> None:
    team = _route_team(stream_member_events=False)
    events = [event async for event in team.arun(INPUT, stream=True, stream_events=True)]

    assert not [event for event in events if event.event == RunEvent.run_content.value]
    team_events = [event for event in events if event.event == TeamRunEvent.run_content.value]
    assert len(team_events) == 1
    assert getattr(team_events[0], "team_id", None) == TEAM_ID
    assert team_events[0].content == MEMBER_TEXT


def test_agent_os_sse_exposes_member_content_event() -> None:
    team = _route_team()
    client = TestClient(AgentOS(teams=[team], telemetry=False).get_app())

    frames: list[tuple[str, dict[str, Any]]] = []
    with client.stream(
        "POST",
        f"/teams/{TEAM_ID}/runs",
        data={"message": INPUT, "stream": "true"},
    ) as response:
        assert response.status_code == 200
        event_name = ""
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                frames.append((event_name, json.loads(line[len("data:") :])))

    team_run_id = next(
        payload["run_id"]
        for name, payload in frames
        if name == TeamRunEvent.run_started.value and payload.get("run_id")
    )

    member_frames = [(name, payload) for name, payload in frames if name == RunEvent.run_content.value]
    assert len(member_frames) == 1
    _, member_payload = member_frames[0]
    assert member_payload["agent_id"] == MEMBER_ID
    assert member_payload["agent_name"] == "Member One"
    assert member_payload["content"] == MEMBER_TEXT
    assert member_payload["parent_run_id"] == team_run_id
    assert member_payload["run_id"] != team_run_id
    assert member_payload.get("team_id") is None

    team_frames = [(name, payload) for name, payload in frames if name == TeamRunEvent.run_content.value]
    assert len(team_frames) == 1
    _, team_payload = team_frames[0]
    assert team_payload["team_id"] == TEAM_ID
    assert team_payload["run_id"] == team_run_id
    assert team_payload["content"] == MEMBER_TEXT
    assert "agent_id" not in team_payload

    # Other team tool events are untouched by the fix.
    tool_started = [name for name, _ in frames if name == TeamRunEvent.tool_call_started.value]
    tool_completed = [name for name, _ in frames if name == TeamRunEvent.tool_call_completed.value]
    assert tool_started == [TeamRunEvent.tool_call_started.value]
    assert tool_completed == [TeamRunEvent.tool_call_completed.value]

    completed = next(payload for name, payload in frames if name == TeamRunEvent.run_completed.value)
    assert completed["content"] == MEMBER_TEXT
    assert [response["agent_id"] for response in completed["member_responses"]] == [MEMBER_ID]


@pytest.mark.asyncio
async def test_route_agui_emits_member_response_text_only_once() -> None:
    pytest.importorskip("ag_ui.core")
    from ag_ui.core import TextMessageContentEvent

    from agno.os.interfaces.agui.router import run_entity

    events = [
        event async for event in run_entity(_route_team(), _agui_run_input("thread-route-agui", "run-route-agui"))
    ]

    text_deltas = [event.delta for event in events if isinstance(event, TextMessageContentEvent)]
    assert text_deltas == [MEMBER_TEXT]


@pytest.mark.asyncio
async def test_route_agui_sub_team_reply_is_emitted_once() -> None:
    pytest.importorskip("ag_ui.core")
    from ag_ui.core import TextMessageContentEvent

    from agno.os.interfaces.agui.router import run_entity

    inner = Agent(id="inner-1", name="Inner One", model=ScriptedMemberModel("INNER_TEXT"))
    sub_team = Team(
        id="sub-team",
        name="Sub Team",
        mode=TeamMode.coordinate,
        members=[inner],
        model=ScriptedLeaderModel(arguments={"member_id": "inner-1", "task": "go"}, final="SUB_TEAM_FINAL"),
        telemetry=False,
    )
    team = Team(
        id=TEAM_ID,
        name="Route Team",
        mode=TeamMode.route,
        members=[sub_team],
        model=ScriptedLeaderModel(arguments={"member_id": "sub-team", "task": "go"}, final="PARENT_FINAL"),
        telemetry=False,
    )

    events = [event async for event in run_entity(team, _agui_run_input("thread-route-sub-team", "run-route-sub-team"))]

    text_deltas = [event.delta for event in events if isinstance(event, TextMessageContentEvent)]
    assert text_deltas == ["INNER_TEXT", "SUB_TEAM_FINAL"]


@pytest.mark.parametrize(
    ("leader_final", "expected"),
    [
        # The leader's continue turn can be empty; the member reply is the answer.
        (None, [MEMBER_TEXT]),
        # The leader repeats the member; the duplicate is dropped.
        (MEMBER_TEXT, [MEMBER_TEXT]),
        # A different team reply keeps both texts in their original order.
        ("leader final", [MEMBER_TEXT, "leader final"]),
    ],
)
def test_route_agui_resume_dedupes_only_the_same_answer(
    tmp_path: Any, leader_final: Optional[str], expected: list[str]
) -> None:
    pytest.importorskip("ag_ui.core")
    from agno.os.interfaces.agui import AGUI

    @tool(requires_confirmation=True)
    def confirming_tool(city: str) -> str:
        """Do something that needs confirmation."""
        return f"weather in {city}"

    member = Agent(id=MEMBER_ID, name="Member One", model=ScriptedConfirmationMemberModel(), tools=[confirming_tool])
    team = Team(
        id=TEAM_ID,
        name="Route Team",
        mode=TeamMode.route,
        members=[member],
        model=ScriptedLeaderModel(final=leader_final),
        db=SqliteDb(db_file=str(tmp_path / "route-resume.db")),
        telemetry=False,
    )
    client = TestClient(AgentOS(teams=[team], interfaces=[AGUI(team=team)], telemetry=False).get_app())

    user = {"id": "user-1", "role": "user", "content": INPUT}
    body = {
        "threadId": "thread-route-resume",
        "runId": "run-1",
        "state": {},
        "messages": [user],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    paused = client.post("/agui", json=body)
    assert paused.status_code == 200
    call = next(
        frame
        for frame in _sse_frames(paused.text)
        if frame["type"] == "TOOL_CALL_START" and frame.get("toolCallName") == "confirming_tool"
    )

    assistant = {
        "id": "assistant-1",
        "role": "assistant",
        "toolCalls": [
            {
                "id": call["toolCallId"],
                "type": "function",
                "function": {"name": "confirming_tool", "arguments": json.dumps({"city": "Tokyo"})},
            }
        ],
    }
    tool_message = {
        "id": "tool-1",
        "role": "tool",
        "toolCallId": call["toolCallId"],
        "content": json.dumps({"accepted": True}),
    }
    resumed = client.post("/agui", json={**body, "runId": "run-2", "messages": [user, assistant, tool_message]})

    assert resumed.status_code == 200
    text_deltas = [frame["delta"] for frame in _sse_frames(resumed.text) if frame["type"] == "TEXT_MESSAGE_CONTENT"]
    assert text_deltas == expected


def test_route_agui_flushes_distinct_alternate_content_at_completion() -> None:
    pytest.importorskip("ag_ui.core")
    from ag_ui.core import TextMessageContentEvent

    from agno.os.interfaces.agui.handlers import on_run_completed, on_run_content
    from agno.os.interfaces.agui.state import StreamState
    from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent

    state = StreamState(suppress_member_run_content=True)
    member = AgentRunContentEvent(content="member answer", parent_run_id="team-run")
    team = TeamRunContentEvent(content="different team answer")

    first_events = on_run_content(member, state)
    second_events = on_run_content(team, state)
    terminal_events = on_run_completed(TeamRunCompletedEvent(), state)

    assert [event.delta for event in first_events if isinstance(event, TextMessageContentEvent)] == ["member answer"]
    assert not [event for event in second_events if isinstance(event, TextMessageContentEvent)]
    assert [event.delta for event in terminal_events if isinstance(event, TextMessageContentEvent)] == [
        "different team answer"
    ]


def test_route_agui_does_not_interleave_alternate_stream_chunks() -> None:
    pytest.importorskip("ag_ui.core")
    from ag_ui.core import TextMessageContentEvent

    from agno.os.interfaces.agui.handlers import on_run_completed, on_run_content
    from agno.os.interfaces.agui.state import StreamState
    from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent

    state = StreamState(suppress_member_run_content=True)
    events = []
    events.extend(on_run_content(AgentRunContentEvent(content="A", parent_run_id="team-run"), state))
    events.extend(on_run_content(TeamRunContentEvent(content="X", run_id="team-run"), state))
    events.extend(on_run_content(AgentRunContentEvent(content="B", parent_run_id="team-run"), state))
    events.extend(on_run_content(TeamRunContentEvent(content="Y", run_id="team-run"), state))
    events.extend(on_run_completed(TeamRunCompletedEvent(), state))

    assert [event.delta for event in events if isinstance(event, TextMessageContentEvent)] == ["A", "B", "XY"]


def test_route_agui_flushes_ambiguous_content_on_pause_and_error() -> None:
    pytest.importorskip("ag_ui.core")
    from ag_ui.core import EventType, TextMessageContentEvent

    from agno.os.interfaces.agui.handlers import on_run_completed, on_run_content, on_run_error
    from agno.os.interfaces.agui.state import StreamState
    from agno.run.team import RunPausedEvent as TeamRunPausedEvent

    for terminal_handler, terminal in (
        (on_run_completed, TeamRunPausedEvent()),
        (on_run_error, AgentRunErrorEvent(content="member failed")),
    ):
        state = StreamState(suppress_member_run_content=True)
        team = TeamRunContentEvent(content="member answer", run_id="team-run")
        member = AgentRunContentEvent(content="member", parent_run_id="team-run")

        on_run_content(team, state)
        on_run_content(member, state)
        terminal_events = terminal_handler(terminal, state)

        deltas = [event.delta for event in terminal_events if isinstance(event, TextMessageContentEvent)]
        assert deltas == ["member"]
        if terminal_handler is on_run_error:
            assert terminal_events[-1].type == EventType.RUN_ERROR
