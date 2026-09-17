"""Unit tests proving ``current_run_id=run_response.run_id`` actually reaches the
continue-message builder at each of the three call sites in ``agent/_run.py``.

test_continue_run_history_exclusion.py calls ``_build_continue_run_messages``
directly with an explicit ``current_run_id``, so it never exercises the wiring
inside ``_run.py`` itself -- a refactor that drops ``current_run_id=run_response.run_id``
at any of the three call sites (``continue_run_dispatch``, ``_acontinue_run``,
``_acontinue_run_stream``) would pass that test suite unnoticed while reopening #10086.

These tests drive the real dispatch functions and stop them exactly at the
message-builder call via a ``BaseException`` sentinel, which passes through every
``except Exception`` / ``except (ValueError, RunNotFoundError)`` handler along the
continue path untouched -- so the rest of the pipeline (model call, tool execution,
persistence) never needs to be mocked.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

import pytest

from agno.agent import _init, _messages, _response, _run, _storage, _tools
from agno.agent.agent import Agent
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession

RUN_ID = "run-continue-wiring"
SESSION_ID = "session-wiring"


class _StoppedAtMessageBuilder(BaseException):
    """Raised the instant the message builder is reached."""


def _make_run() -> RunOutput:
    return RunOutput(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        status=RunStatus.running,
        tools=[],
        requirements=None,
        messages=[],
    )


def _patch_sync(monkeypatch: pytest.MonkeyPatch, agent: Agent, runs) -> None:
    monkeypatch.setattr(_init, "has_async_db", lambda agent: False)
    monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda agent, session=None, session_state=None: session_state)
    monkeypatch.setattr(_response, "get_response_format", lambda agent, run_context=None: None)
    monkeypatch.setattr(_tools, "determine_tools_for_model", lambda *a, **kw: [])
    monkeypatch.setattr(
        _storage,
        "read_or_create_session",
        lambda agent, session_id=None, user_id=None: AgentSession(session_id=session_id, user_id=user_id, runs=runs),
    )
    monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)


def _patch_async(monkeypatch: pytest.MonkeyPatch, agent: Agent, runs) -> None:
    async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
        return AgentSession(session_id=session_id, user_id=user_id, runs=runs)

    monkeypatch.setattr(_init, "has_async_db", lambda agent: False)
    monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
    monkeypatch.setattr(
        _storage,
        "read_or_create_session",
        lambda agent, session_id=None, user_id=None: AgentSession(session_id=session_id, user_id=user_id, runs=runs),
    )
    monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda agent, session=None, session_state=None: session_state)
    monkeypatch.setattr(_response, "get_response_format", lambda agent, run_context=None: None)
    monkeypatch.setattr(_tools, "determine_tools_for_model", lambda *a, **kw: [])
    monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)


def test_sync_continue_run_dispatch_passes_run_id_to_message_builder(monkeypatch: pytest.MonkeyPatch):
    agent = Agent(name="test-agent")
    _patch_sync(monkeypatch, agent, runs=[_make_run()])

    captured: dict = {}

    def fake_get_continue_run_messages(
        agent, input, session=None, add_history_to_context=None, run_context=None, current_run_id=None
    ):
        captured["current_run_id"] = current_run_id
        raise _StoppedAtMessageBuilder()

    monkeypatch.setattr(_messages, "get_continue_run_messages", fake_get_continue_run_messages)

    with pytest.raises(_StoppedAtMessageBuilder):
        _run.continue_run_dispatch(agent=agent, run_id=RUN_ID, session_id=SESSION_ID, stream=False)

    assert captured.get("current_run_id") == RUN_ID


@pytest.mark.asyncio
async def test_async_continue_run_passes_run_id_to_message_builder(monkeypatch: pytest.MonkeyPatch):
    agent = Agent(name="test-agent")
    _patch_async(monkeypatch, agent, runs=[_make_run()])

    captured: dict = {}

    async def fake_aget_continue_run_messages(
        agent, input, session=None, add_history_to_context=None, run_context=None, current_run_id=None
    ):
        captured["current_run_id"] = current_run_id
        raise _StoppedAtMessageBuilder()

    monkeypatch.setattr(_messages, "aget_continue_run_messages", fake_aget_continue_run_messages)

    with pytest.raises(_StoppedAtMessageBuilder):
        await _run.acontinue_run_dispatch(agent=agent, run_id=RUN_ID, session_id=SESSION_ID, stream=False)

    assert captured.get("current_run_id") == RUN_ID


@pytest.mark.asyncio
async def test_async_stream_continue_run_passes_run_id_to_message_builder(monkeypatch: pytest.MonkeyPatch):
    agent = Agent(name="test-agent")
    _patch_async(monkeypatch, agent, runs=[_make_run()])

    captured: dict = {}

    async def fake_aget_continue_run_messages(
        agent, input, session=None, add_history_to_context=None, run_context=None, current_run_id=None
    ):
        captured["current_run_id"] = current_run_id
        raise _StoppedAtMessageBuilder()

    monkeypatch.setattr(_messages, "aget_continue_run_messages", fake_aget_continue_run_messages)

    agen = _run.acontinue_run_dispatch(agent=agent, run_id=RUN_ID, session_id=SESSION_ID, stream=True)

    with pytest.raises(_StoppedAtMessageBuilder):
        async for _ in agen:
            pass

    assert captured.get("current_run_id") == RUN_ID
