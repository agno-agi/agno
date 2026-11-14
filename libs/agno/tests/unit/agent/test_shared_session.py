"""A session shared between several agents is replayed from each agent's point of view.

Several agents run on one session_id. Each agent's history then has to show the other
agents' replies as someone else's words, not its own, and a user message that was run
through every agent (one Message object, so one id) has to appear once.
"""

from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


class RecordingModel(Model):
    """Offline model that answers with a fixed text and records the messages it was sent."""

    def __init__(self, reply: str):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self.reply = reply
        self.calls: List[List[Message]] = []
        self._mock_response = ModelResponse(content=reply, role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def _record(self, kwargs: Any) -> None:
        messages = kwargs.get("messages")
        if messages is not None:
            self.calls.append(list(messages))

    def invoke(self, *args, **kwargs) -> ModelResponse:
        self._record(kwargs)
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        self._record(kwargs)
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        self._record(kwargs)
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        self._record(kwargs)
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def _run(agent_id: str, agent_name: str, messages: List[Message]) -> RunOutput:
    return RunOutput(
        run_id=f"run-{agent_id}-{messages[0].id}",
        agent_id=agent_id,
        agent_name=agent_name,
        messages=messages,
        content=messages[-1].content,
        status=RunStatus.completed,
    )


def _shared_session() -> AgentSession:
    """One user turn fanned out to two agents, then a turn addressed to the second agent only."""
    turn_one = Message(role="user", content="Plan a trip")
    turn_two = Message(role="user", content="Skeptic, what could go wrong?")
    return AgentSession(
        session_id="room",
        runs=[
            _run("researcher", "Researcher", [turn_one, Message(role="assistant", content="Kyoto in November.")]),
            _run(
                "skeptic",
                "Skeptic",
                [
                    turn_one,
                    Message(role="assistant", content=None, tool_calls=[{"id": "t1", "type": "function"}]),
                    Message(role="tool", content="weather: rain", tool_call_id="t1"),
                    Message(role="assistant", content="It rains there in November."),
                ],
            ),
            _run("skeptic", "Skeptic", [turn_two, Message(role="assistant", content="Crowds and rain.")]),
        ],
    )


def test_viewer_sees_other_agents_as_named_user_messages_and_the_user_turn_once():
    history = _shared_session().get_messages(viewer_agent_id="researcher")

    assert [(m.role, m.content) for m in history] == [
        ("user", "Plan a trip"),
        ("assistant", "Kyoto in November."),
        ("user", "Skeptic: It rains there in November."),
        ("user", "Skeptic, what could go wrong?"),
        ("user", "Skeptic: Crowds and rain."),
    ]


def test_viewer_keeps_its_own_runs_unchanged_including_tool_traffic():
    history = _shared_session().get_messages(viewer_agent_id="skeptic")

    assert [(m.role, m.content) for m in history] == [
        ("user", "Plan a trip"),
        ("user", "Researcher: Kyoto in November."),
        ("assistant", None),
        ("tool", "weather: rain"),
        ("assistant", "It rains there in November."),
        ("user", "Skeptic, what could go wrong?"),
        ("assistant", "Crowds and rain."),
    ]


def test_without_a_viewer_the_session_replays_as_before():
    history = _shared_session().get_messages()

    roles = [m.role for m in history]
    assert roles.count("user") == 3, "the fanned-out user turn is repeated per run"
    assert all(not (m.content or "").startswith(("Skeptic:", "Researcher:")) for m in history)


def test_history_copies_do_not_claim_the_user_message_id():
    turn = Message(role="user", content="Plan a trip")
    replayed = turn.model_copy(update={"from_history": True})
    session = AgentSession(
        session_id="room",
        runs=[
            _run("a", "A", [Message(role="user", content="earlier"), Message(role="assistant", content="ok")]),
            _run("b", "B", [replayed, turn, Message(role="assistant", content="sure")]),
        ],
    )

    history = session.get_messages(viewer_agent_id="a")

    assert [m.content for m in history if m.role == "user" and not m.content.startswith("B:")] == [
        "earlier",
        "Plan a trip",
    ]


def _agents(db: InMemoryDb):
    researcher = Agent(
        name="Researcher",
        model=RecordingModel("Kyoto in November."),
        db=db,
        add_history_to_context=True,
        shared_session=True,
        telemetry=False,
    )
    skeptic = Agent(
        name="Skeptic",
        model=RecordingModel("It rains there."),
        db=db,
        add_history_to_context=True,
        shared_session=True,
        telemetry=False,
    )
    return researcher, skeptic


def _sent(model: Any) -> List[tuple]:
    return [(m.role, m.content) for m in model.calls[-1] if m.role != "system"]


def test_agents_on_one_session_see_each_other_labelled_and_the_broadcast_once():
    researcher, skeptic = _agents(InMemoryDb())

    turn = Message(role="user", content="Plan a trip")
    researcher.run(turn, session_id="room")
    skeptic.run(turn, session_id="room")
    researcher.run("Thanks both", session_id="room")

    # The second agent gets the first agent's reply as context and the turn itself as its input,
    # not the turn twice.
    assert _sent(skeptic.model) == [
        ("user", "Researcher: Kyoto in November."),
        ("user", "Plan a trip"),
    ]
    assert _sent(researcher.model) == [
        ("user", "Plan a trip"),
        ("assistant", "Kyoto in November."),
        ("user", "Skeptic: It rains there."),
        ("user", "Thanks both"),
    ]


@pytest.mark.asyncio
async def test_agents_on_one_session_see_each_other_async():
    researcher, skeptic = _agents(InMemoryDb())

    turn = Message(role="user", content="Plan a trip")
    await researcher.arun(turn, session_id="room")
    await skeptic.arun(turn, session_id="room")
    await researcher.arun("Thanks both", session_id="room")

    assert _sent(researcher.model) == [
        ("user", "Plan a trip"),
        ("assistant", "Kyoto in November."),
        ("user", "Skeptic: It rains there."),
        ("user", "Thanks both"),
    ]


def test_shared_session_off_keeps_the_old_replay():
    db = InMemoryDb()
    researcher, skeptic = _agents(db)
    researcher.shared_session = False
    skeptic.shared_session = False

    turn = Message(role="user", content="Plan a trip")
    researcher.run(turn, session_id="room")
    skeptic.run(turn, session_id="room")
    researcher.run("Thanks both", session_id="room")

    sent = _sent(researcher.model)
    assert ("assistant", "It rains there.") in sent, "the other agent's reply replays as the viewer's own"
    assert [c for r, c in sent if r == "user"].count("Plan a trip") == 2
