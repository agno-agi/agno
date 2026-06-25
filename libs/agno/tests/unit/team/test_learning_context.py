from unittest.mock import AsyncMock, MagicMock

import pytest
from typing_extensions import assert_type

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.session.team import TeamSession
from agno.team._messages import aget_system_message, get_system_message
from agno.team.team import Team


class _FakeModel(Model):
    def __init__(self) -> None:
        super().__init__(id="fake-model")

    def get_instructions_for_model(self, tools=None):
        return []

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse()

    def invoke_stream(self, *args, **kwargs):
        if False:
            yield ModelResponse()

    async def ainvoke_stream(self, *args, **kwargs):
        if False:
            yield ModelResponse()

    def _parse_provider_response(self, response, **kwargs) -> ModelResponse:
        return ModelResponse()

    def _parse_provider_response_delta(self, response) -> ModelResponse:
        return ModelResponse()


def _make_team(*, add_learnings_to_context: bool = True, learning=None) -> Team:
    team = Team(
        name="Learning Team",
        model=_FakeModel(),
        members=[],
        add_learnings_to_context=add_learnings_to_context,
        add_session_summary_to_context=True,
    )
    team.set_id()
    team._learning = learning
    return team


def _make_session() -> TeamSession:
    session = TeamSession(session_id="team-session")
    session.summary = MagicMock(summary="Summary: the user prefers bullet points.")
    return session


def _make_run_context() -> RunContext:
    return RunContext(
        run_id="run-1",
        session_id="team-session",
        user_id="user-1",
        session_state={"source": "session-state"},
    )


def _content(message: Message) -> str:
    content = message.content
    assert isinstance(content, str)
    assert_type(content, str)
    return content


def test_get_system_message_includes_learning_context():
    learning = MagicMock()
    learning.build_context.return_value = "<learning_context>\nStored preference\n</learning_context>"

    message = get_system_message(
        _make_team(learning=learning),
        _make_session(),
        run_context=_make_run_context(),
        add_session_state_to_context=True,
    )

    assert message is not None
    assert "<learning_context>\nStored preference\n</learning_context>" in _content(message)
    learning.build_context.assert_called_once_with(
        user_id="user-1",
        session_id="team-session",
        team_id="learning-team",
    )


@pytest.mark.asyncio
async def test_aget_system_message_includes_learning_context():
    learning = MagicMock()
    learning.abuild_context = AsyncMock(return_value="<learning_context>\nAsync preference\n</learning_context>")

    message = await aget_system_message(
        _make_team(learning=learning),
        _make_session(),
        run_context=_make_run_context(),
        add_session_state_to_context=True,
    )

    assert message is not None
    assert "<learning_context>\nAsync preference\n</learning_context>" in _content(message)
    learning.abuild_context.assert_awaited_once_with(
        user_id="user-1",
        session_id="team-session",
        team_id="learning-team",
    )


def test_get_system_message_skips_learning_context_when_flag_disabled():
    learning = MagicMock()
    learning.build_context.return_value = "<learning_context>should-not-appear</learning_context>"

    message = get_system_message(
        _make_team(add_learnings_to_context=False, learning=learning),
        _make_session(),
        run_context=_make_run_context(),
    )

    assert message is not None
    assert "should-not-appear" not in _content(message)
    learning.build_context.assert_not_called()


def test_get_system_message_skips_empty_learning_context():
    learning = MagicMock()
    learning.build_context.return_value = ""

    message = get_system_message(
        _make_team(learning=learning),
        _make_session(),
        run_context=_make_run_context(),
    )

    assert message is not None
    assert "<learning_context>" not in _content(message)
    learning.build_context.assert_called_once()


def test_get_system_message_places_learning_context_before_trailing_sections():
    learning = MagicMock()
    learning.build_context.return_value = "<learning_context>\nOrdered preference\n</learning_context>"

    message = get_system_message(
        _make_team(learning=learning),
        _make_session(),
        run_context=_make_run_context(),
        add_session_state_to_context=True,
    )

    assert message is not None
    content = _content(message)
    summary_index = content.index("Summary: the user prefers bullet points.")
    learning_index = content.index("<learning_context>\nOrdered preference\n</learning_context>")
    session_state_index = content.index("<session_state>")

    assert summary_index < learning_index < session_state_index
