"""Regression test for agno-agi/agno#7044/#7652: the Team parser_model call must not
force stream_model_response=False, and structured output is parsed once the
stream ends instead of once per chunk.

Mirrors libs/agno/tests/unit/agent/test_parser_model_stream.py for Team.
"""

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team import _messages, _response
from agno.team._response import aparse_response_with_parser_model_stream, parse_response_with_parser_model_stream
from agno.team.team import Team


class _Output(BaseModel):
    summary: str


def _chunk(content: str) -> ModelResponse:
    return ModelResponse(content=content, event=ModelResponseEvent.assistant_response.value)


def _reasoning_chunk(reasoning_content: str) -> ModelResponse:
    return ModelResponse(reasoning_content=reasoning_content, event=ModelResponseEvent.assistant_response.value)


def _patch_parser_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_response, "get_response_format", lambda team, model=None, run_context=None: _Output)
    monkeypatch.setattr(
        _messages,
        "_get_messages_for_parser_model_stream",
        lambda team, run_response, response_format, run_context=None: [Message(role="assistant", content="")],
    )


def _setup(monkeypatch: pytest.MonkeyPatch):
    team = Team(name="t", members=[])
    team.parser_model = MagicMock()
    _patch_parser_helpers(monkeypatch)
    run_response = TeamRunOutput(run_id="run-1", session_id="session-1", team_id="team-1")
    run_context = RunContext(run_id="run-1", session_id="session-1", output_schema=_Output)
    session = TeamSession(session_id="session-1")
    return team, run_response, run_context, session


def test_parser_model_stream_keeps_streaming_and_parses_once(monkeypatch: pytest.MonkeyPatch):
    team, run_response, run_context, session = _setup(monkeypatch)
    team.parser_model.response_stream.return_value = iter([_chunk('{"summ'), _chunk('ary": "ok"}')])

    list(
        parse_response_with_parser_model_stream(
            team, session=session, run_response=run_response, run_context=run_context
        )
    )

    assert team.parser_model.response_stream.call_args.kwargs["stream_model_response"] is True
    assert run_response.content == _Output(summary="ok")
    assert run_response.content_type == "_Output"


def test_parser_model_stream_skips_reasoning_only_chunks(monkeypatch: pytest.MonkeyPatch):
    """Regression: a thinking-enabled parser_model must not leak reasoning-only
    chunks (content=None) as visible RunContent events."""
    team, run_response, run_context, session = _setup(monkeypatch)
    team.parser_model.response_stream.return_value = iter(
        [_reasoning_chunk("thinking..."), _chunk('{"summary": "ok"}')]
    )

    events = list(
        parse_response_with_parser_model_stream(
            team, session=session, run_response=run_response, run_context=run_context, stream_events=True
        )
    )

    content_events = [e for e in events if e.event == "TeamRunContent"]
    assert all(e.content is not None for e in content_events)
    assert run_response.content == _Output(summary="ok")


@pytest.mark.asyncio
async def test_aparser_model_stream_keeps_streaming_and_parses_once(monkeypatch: pytest.MonkeyPatch):
    team, run_response, run_context, session = _setup(monkeypatch)

    async def _achunks():
        for chunk in (_chunk('{"summ'), _chunk('ary": "ok"}')):
            yield chunk

    team.parser_model.aresponse_stream.return_value = _achunks()

    events = aparse_response_with_parser_model_stream(
        team, session=session, run_response=run_response, run_context=run_context
    )
    async for _ in events:
        pass

    assert team.parser_model.aresponse_stream.call_args.kwargs["stream_model_response"] is True
    assert run_response.content == _Output(summary="ok")
    assert run_response.content_type == "_Output"
