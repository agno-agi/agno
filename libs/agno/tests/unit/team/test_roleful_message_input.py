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
from agno.team import Team


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


def _team(model: _RecordingModel) -> Team:
    return Team(name="roleful", model=model, members=[], markdown=False, telemetry=False)


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


def test_team_accepts_role_dicts_and_skips_invalid_entries():
    model = _RecordingModel(id="gpt-test", api_key="sk-test")

    _team(model).run([{"role": "user", "content": "from a dict"}, {"role": "bogus role", "content": 1}])

    assert _conversation(model) == [("user", "from a dict")]


def test_team_still_joins_a_list_of_strings():
    model = _RecordingModel(id="gpt-test", api_key="sk-test")

    _team(model).run(["first line", "second line"])

    assert _conversation(model) == [("user", "first line\nsecond line")]
