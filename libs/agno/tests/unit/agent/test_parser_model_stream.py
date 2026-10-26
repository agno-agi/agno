"""Regression test for agno-agi/agno#7044/#7652: the parser_model call must not
force stream_model_response=False, and structured output is parsed once the
stream ends instead of once per chunk."""

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from agno.agent import _messages, _response
from agno.agent._response import aparse_response_with_parser_model_stream, parse_response_with_parser_model_stream
from agno.agent.agent import Agent
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.session import AgentSession


class _Output(BaseModel):
    summary: str


def _chunk(content: str) -> ModelResponse:
    return ModelResponse(content=content, event=ModelResponseEvent.assistant_response.value)


def _reasoning_chunk(reasoning_content: str) -> ModelResponse:
    return ModelResponse(reasoning_content=reasoning_content, event=ModelResponseEvent.assistant_response.value)


def _patch_parser_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_response, "get_response_format", lambda agent, model=None, run_context=None: _Output)
    monkeypatch.setattr(
        _messages,
        "get_messages_for_parser_model_stream",
        lambda agent, run_response, response_format, run_context=None: [Message(role="assistant", content="")],
    )


def _setup(monkeypatch: pytest.MonkeyPatch):
    agent = Agent()
    agent.parser_model = MagicMock()
    _patch_parser_helpers(monkeypatch)
    run_response = RunOutput(run_id="run-1", session_id="session-1", messages=[])
    run_context = RunContext(run_id="run-1", session_id="session-1", output_schema=_Output)
    session = AgentSession(session_id="session-1")
    return agent, run_response, run_context, session


def test_parser_model_stream_keeps_streaming_and_parses_once(monkeypatch: pytest.MonkeyPatch):
    agent, run_response, run_context, session = _setup(monkeypatch)
    agent.parser_model.response_stream.return_value = iter([_chunk('{"summ'), _chunk('ary": "ok"}')])

    list(
        parse_response_with_parser_model_stream(
            agent, session=session, run_response=run_response, run_context=run_context
        )
    )

    assert agent.parser_model.response_stream.call_args.kwargs["stream_model_response"] is True
    assert run_response.content == _Output(summary="ok")
    assert run_response.content_type == "_Output"


def test_parser_model_stream_skips_reasoning_only_chunks(monkeypatch: pytest.MonkeyPatch):
    """Regression: a thinking-enabled parser_model must not leak reasoning-only
    chunks (content=None) as visible RunContent events."""
    agent, run_response, run_context, session = _setup(monkeypatch)
    agent.parser_model.response_stream.return_value = iter(
        [_reasoning_chunk("thinking..."), _chunk('{"summary": "ok"}')]
    )

    events = list(
        parse_response_with_parser_model_stream(
            agent, session=session, run_response=run_response, run_context=run_context, stream_events=True
        )
    )

    content_events = [e for e in events if e.event == "RunContent"]
    assert all(e.content is not None for e in content_events)
    assert run_response.content == _Output(summary="ok")


@pytest.mark.asyncio
async def test_aparser_model_stream_keeps_streaming_and_parses_once(monkeypatch: pytest.MonkeyPatch):
    agent, run_response, run_context, session = _setup(monkeypatch)

    async def _achunks():
        for chunk in (_chunk('{"summ'), _chunk('ary": "ok"}')):
            yield chunk

    agent.parser_model.aresponse_stream.return_value = _achunks()

    events = aparse_response_with_parser_model_stream(
        agent, session=session, run_response=run_response, run_context=run_context
    )
    async for _ in events:
        pass

    assert agent.parser_model.aresponse_stream.call_args.kwargs["stream_model_response"] is True
    assert run_response.content == _Output(summary="ok")
    assert run_response.content_type == "_Output"
