"""A ``Team`` given a list of ``Message`` objects must send them as-is, like an ``Agent`` does.

``Agent.run([...])`` appends a list of messages to the run with their roles kept
and records them in ``extra_messages``. ``Team.run([...])`` flattened the same
input into one user string through ``get_text_from_message``, so assistant turns
handed in as input reached the model as user text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

import pytest

from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.team._messages import _get_user_message


@dataclass
class _RecordingModel(OpenAIChat):
    """Records the provider-bound messages instead of calling OpenAI."""

    seen: List[Message] = field(default_factory=list)

    def invoke(self, messages: List[Message], *_args: Any, **_kwargs: Any) -> ModelResponse:
        self.seen = list(messages)
        return ModelResponse(content="ok")

    async def ainvoke(self, messages: List[Message], *_args: Any, **_kwargs: Any) -> ModelResponse:
        self.seen = list(messages)
        return ModelResponse(content="ok")


@dataclass
class _RecordingMemoryManager:
    model: Any = None
    db: Any = None
    seen: List[Message] = field(default_factory=list)

    def create_user_memories(self, *, messages: List[Message], **_kwargs: Any) -> str:
        self.seen = list(messages)
        return "ok"

    async def acreate_user_memories(self, *, messages: List[Message], **_kwargs: Any) -> str:
        self.seen = list(messages)
        return "ok"


def _team(model: _RecordingModel, memory_manager: Any = None) -> Team:
    return Team(
        name="roleful",
        model=model,
        members=[],
        markdown=False,
        telemetry=False,
        memory_manager=memory_manager,
        update_memory_on_run=memory_manager is not None,
        add_memories_to_context=False,
    )


ROLEFUL_INPUT = [
    Message(role="user", content="stored question"),
    Message(role="assistant", content="stored answer"),
    Message(role="user", content="current question"),
]


def _conversation(model: _RecordingModel) -> List[tuple]:
    return [(m.role, m.content) for m in model.seen if m.role != "system"]


def test_team_keeps_message_list_input_roleful():
    model = _RecordingModel(id="gpt-test", api_key="sk-test")

    response = _team(model).run(ROLEFUL_INPUT)

    assert response.content == "ok"
    assert _conversation(model) == [
        ("user", "stored question"),
        ("assistant", "stored answer"),
        ("user", "current question"),
    ]


@pytest.mark.asyncio
async def test_team_keeps_message_list_input_roleful_async():
    model = _RecordingModel(id="gpt-test", api_key="sk-test")

    response = await _team(model).arun(ROLEFUL_INPUT)

    assert response.content == "ok"
    assert _conversation(model) == [
        ("user", "stored question"),
        ("assistant", "stored answer"),
        ("user", "current question"),
    ]


def test_team_processes_roleful_input_for_memory():
    model = _RecordingModel(id="gpt-test", api_key="sk-test")
    memory_manager = _RecordingMemoryManager()

    _team(model, memory_manager).run(ROLEFUL_INPUT)

    assert [(message.role, message.content) for message in memory_manager.seen] == [
        ("user", "stored question"),
        ("assistant", "stored answer"),
        ("user", "current question"),
    ]


@pytest.mark.asyncio
async def test_team_processes_roleful_input_for_memory_async():
    model = _RecordingModel(id="gpt-test", api_key="sk-test")
    memory_manager = _RecordingMemoryManager()

    await _team(model, memory_manager).arun(ROLEFUL_INPUT)

    assert [(message.role, message.content) for message in memory_manager.seen] == [
        ("user", "stored question"),
        ("assistant", "stored answer"),
        ("user", "current question"),
    ]


def test_team_accepts_role_dicts_and_skips_invalid_entries():
    model = _RecordingModel(id="gpt-test", api_key="sk-test")

    _team(model).run([{"role": "user", "content": "from a dict"}, {"role": "bogus role", "content": 1}])

    assert _conversation(model) == [("user", "from a dict")]


def test_team_still_joins_a_list_of_strings():
    model = _RecordingModel(id="gpt-test", api_key="sk-test")

    _team(model).run(["first line", "second line"])

    assert _conversation(model) == [("user", "first line\nsecond line")]


def test_roleful_list_still_flattens_for_verbatim_member_input():
    model = _RecordingModel(id="gpt-test", api_key="sk-test")
    team = _team(model)

    message = _get_user_message(
        team,
        run_response=TeamRunOutput(),
        run_context=RunContext(run_id="run-id", session_id="session-id"),
        input_message=ROLEFUL_INPUT,
    )

    assert message.content == "stored question\ncurrent question"
