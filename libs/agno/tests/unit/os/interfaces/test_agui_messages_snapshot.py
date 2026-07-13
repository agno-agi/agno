import json
from typing import Any, AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import EventType, RunAgentInput
from ag_ui.core.types import AssistantMessage as AGUIAssistantMessage
from ag_ui.core.types import ToolMessage as AGUIToolMessage
from ag_ui.core.types import UserMessage as AGUIUserMessage

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.agui.history import asession_history_snapshot, session_history_snapshot
from agno.os.interfaces.agui.router import run_entity
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team import Team


class _TextModel(Model):
    def __init__(self, content: str):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.content = content

    def _response(self) -> ModelResponse:
        response = ModelResponse(role="assistant", content=self.content)
        response.event = ModelResponseEvent.assistant_response.value
        return response

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._response()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._response()

    def parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


def _run_input(messages=None, run_id: str = "run-2") -> RunAgentInput:
    return RunAgentInput(
        threadId="thread-1",
        runId=run_id,
        state=None,
        messages=messages or [AGUIUserMessage(id="current-user", content="current question")],
        tools=[],
        context=[],
        forwardedProps={},
    )


def _agent_with_history(user_id: str = "user-1") -> Agent:
    db = InMemoryDb()
    agent = Agent(id="history-agent", db=db, model=_TextModel("current answer"), telemetry=False)
    db.upsert_session(
        AgentSession(
            session_id="thread-1",
            user_id=user_id,
            agent_id=agent.id,
            runs=[
                RunOutput(
                    run_id="run-1",
                    agent_id=agent.id,
                    status=RunStatus.completed,
                    messages=[
                        Message(id="history-user", role="user", content="previous question"),
                        Message(id="history-assistant", role="assistant", content="previous answer"),
                    ],
                )
            ],
        )
    )
    return agent


def _team_with_history() -> Team:
    db = InMemoryDb()
    member = Agent(id="member", model=_TextModel("member answer"), telemetry=False)
    team = Team(id="history-team", members=[member], db=db, model=_TextModel("team answer"), telemetry=False)
    db.upsert_session(
        TeamSession(
            session_id="thread-1",
            user_id="user-1",
            team_id=team.id,
            runs=[
                TeamRunOutput(
                    run_id="run-1",
                    team_id=team.id,
                    status=RunStatus.completed,
                    messages=[
                        Message(id="team-user", role="user", content="team question"),
                        Message(id="team-assistant", role="assistant", content="team answer"),
                    ],
                )
            ],
        )
    )
    return team


def test_session_history_snapshot_maps_agent_history_and_current_input():
    snapshot = session_history_snapshot(_agent_with_history(), _run_input(), [], user_id="user-1")

    assert snapshot is not None
    assert [(message.role, message.content) for message in snapshot.messages] == [
        ("user", "previous question"),
        ("assistant", "previous answer"),
        ("user", "current question"),
    ]
    assert snapshot.messages[0].id == "history-user"
    assert snapshot.messages[1].id == "history-assistant"
    assert snapshot.messages[-1].id != "current-user"


@pytest.mark.asyncio
async def test_asession_history_snapshot_maps_team_history():
    snapshot = await asession_history_snapshot(_team_with_history(), _run_input(), [], user_id="user-1")

    assert snapshot is not None
    assert [(message.role, message.content) for message in snapshot.messages] == [
        ("user", "team question"),
        ("assistant", "team answer"),
        ("user", "current question"),
    ]


def test_session_history_snapshot_respects_user_id():
    snapshot = session_history_snapshot(_agent_with_history(user_id="owner"), _run_input(), [], user_id="other")

    assert snapshot is None


@pytest.mark.parametrize(
    "messages,tool_messages",
    [
        (
            [
                AGUIUserMessage(id="prior-user", content="previous question"),
                AGUIAssistantMessage(id="prior-assistant", content="previous answer"),
                AGUIUserMessage(id="current-user", content="current question"),
            ],
            [],
        ),
        (
            [AGUIUserMessage(id="current-user", content="current question")],
            [AGUIToolMessage(id="tool-message", tool_call_id="tool-call", content="tool result")],
        ),
    ],
)
def test_session_history_snapshot_skips_stateful_and_resume_payloads(messages, tool_messages):
    snapshot = session_history_snapshot(_agent_with_history(), _run_input(messages=messages), tool_messages)

    assert snapshot is None


@pytest.mark.asyncio
async def test_run_entity_emits_one_snapshot_before_live_messages():
    events = [
        event
        async for event in run_entity(
            _agent_with_history(),
            _run_input(),
            user_id="user-1",
            emit_messages_snapshot=True,
        )
    ]
    event_types = [event.type for event in events]
    snapshots = [event for event in events if event.type == EventType.MESSAGES_SNAPSHOT]

    assert len(snapshots) == 1
    assert event_types.index(EventType.MESSAGES_SNAPSHOT) < event_types.index(EventType.TEXT_MESSAGE_START)
    assert [message.content for message in snapshots[0].messages] == [
        "previous question",
        "previous answer",
        "current question",
    ]
    assert "current answer" not in [message.content for message in snapshots[0].messages]


@pytest.mark.asyncio
async def test_run_entity_preserves_existing_behavior_when_disabled_or_empty():
    disabled_events = [event async for event in run_entity(_agent_with_history(), _run_input(), user_id="user-1")]
    empty_agent = Agent(id="empty-agent", db=InMemoryDb(), model=_TextModel("answer"), telemetry=False)
    empty_events = [
        event
        async for event in run_entity(
            empty_agent,
            _run_input(),
            user_id="user-1",
            emit_messages_snapshot=True,
        )
    ]

    assert EventType.MESSAGES_SNAPSHOT not in [event.type for event in disabled_events]
    assert EventType.MESSAGES_SNAPSHOT not in [event.type for event in empty_events]
    assert EventType.RUN_FINISHED in [event.type for event in empty_events]


@pytest.mark.asyncio
async def test_run_entity_continues_when_session_read_fails(monkeypatch):
    agent = _agent_with_history()

    async def fail_session_read(*args: Any, **kwargs: Any):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(agent, "aget_session", fail_session_read)
    events = [
        event
        async for event in run_entity(
            agent,
            _run_input(),
            user_id="user-1",
            emit_messages_snapshot=True,
        )
    ]

    assert EventType.MESSAGES_SNAPSHOT not in [event.type for event in events]
    assert EventType.RUN_FINISHED in [event.type for event in events]
    assert EventType.RUN_ERROR not in [event.type for event in events]


def test_agui_http_route_emits_snapshot_when_enabled():
    agent = _agent_with_history()
    app = AgentOS(agents=[agent], interfaces=[AGUI(agent=agent, emit_messages_snapshot=True)]).get_app()
    response = TestClient(app).post(
        "/agui",
        json={
            "threadId": "thread-1",
            "runId": "run-2",
            "state": None,
            "messages": [{"id": "current-user", "role": "user", "content": "current question"}],
            "tools": [],
            "context": [],
            "forwardedProps": {"user_id": "user-1"},
        },
    )

    assert response.status_code == 200
    payloads = [
        json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    snapshots = [payload for payload in payloads if payload["type"] == EventType.MESSAGES_SNAPSHOT]
    assert len(snapshots) == 1
    assert [message["content"] for message in snapshots[0]["messages"]] == [
        "previous question",
        "previous answer",
        "current question",
    ]
