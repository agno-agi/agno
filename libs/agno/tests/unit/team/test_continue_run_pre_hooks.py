"""Tests for pre-hook execution on Team continue_run paths.

Regression coverage for the gap where run()/arun() execute pre_hooks but
continue_run()/acontinue_run() (and their streaming variants) used to skip
them — allowing HITL-resumed team runs to bypass guardrail/authz hooks.

On continue_run, only hooks decorated with @hook(run_on_continue=True) or
guardrails execute. Plain hooks are skipped since input was already validated.
"""

import asyncio

import agno.team._telemetry as team_telemetry
from agno.exceptions import InputCheckError
from agno.hooks import hook
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext, RunStatus
from agno.run.messages import RunMessages
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.session import TeamSession
from agno.team import _run as team_run
from agno.team.team import Team


def _make_paused_team_run() -> TeamRunOutput:
    return TeamRunOutput(
        run_id="run-1",
        session_id="session-1",
        status=RunStatus.paused,
        input=TeamRunInput(input_content="original team question"),
        messages=[Message(role="user", content="original team question")],
    )


def _make_run_context() -> RunContext:
    return RunContext(run_id="run-1", session_id="session-1", user_id="user-1")


def _make_team_session() -> TeamSession:
    return TeamSession(session_id="session-1", user_id="user-1")


def _make_run_messages() -> RunMessages:
    return RunMessages(messages=[Message(role="user", content="original team question")])


def _patch_team_sync_model(monkeypatch):
    calls = []

    def fake_model(*args, **kwargs):
        calls.append(1)
        return ModelResponse(role="assistant", content="continued")

    monkeypatch.setattr(team_run, "call_model_with_fallback", fake_model)
    return calls


async def _empty_async_generator(*args, **kwargs):
    return
    yield


# ---------------------------------------------------------------------------
# Sync, non-streaming (_continue_run)
# ---------------------------------------------------------------------------


def test_team_continue_run_executes_pre_hooks(monkeypatch):
    calls = []

    @hook(run_on_continue=True)
    def pre_hook(run_input=None, session=None, user_id=None):
        calls.append({"session_id": getattr(session, "session_id", None), "user_id": user_id})

    team = Team(name="hook-test-team", members=[], pre_hooks=[pre_hook])
    _patch_team_sync_model(monkeypatch)
    monkeypatch.setattr(team_run, "_cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(team_telemetry, "log_team_telemetry", lambda *a, **k: None)

    result = team_run._continue_run(
        team,
        run_response=_make_paused_team_run(),
        run_messages=_make_run_messages(),
        run_context=_make_run_context(),
        tools=[],
        session=_make_team_session(),
        user_id="user-1",
    )

    assert result.status == RunStatus.completed
    assert calls == [{"session_id": "session-1", "user_id": "user-1"}]


def test_team_continue_run_pre_hook_guardrail_blocks_model_call(monkeypatch):
    @hook(run_on_continue=True)
    def blocking_hook(run_input=None):
        raise InputCheckError("authz denied on team resume")

    team = Team(name="guard-test-team", members=[], pre_hooks=[blocking_hook])
    model_calls = _patch_team_sync_model(monkeypatch)
    monkeypatch.setattr(team_run, "_cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(team_telemetry, "log_team_telemetry", lambda *a, **k: None)

    result = team_run._continue_run(
        team,
        run_response=_make_paused_team_run(),
        run_messages=_make_run_messages(),
        run_context=_make_run_context(),
        tools=[],
        session=_make_team_session(),
        user_id="user-1",
    )

    assert model_calls == [], "model must not be invoked when a pre-hook guardrail fails"
    assert result.status == RunStatus.error
    assert "authz denied on team resume" in str(result.content)


# ---------------------------------------------------------------------------
# Sync, streaming (_continue_run_stream)
# ---------------------------------------------------------------------------


def test_team_continue_run_stream_executes_pre_hooks(monkeypatch):
    calls = []

    @hook(run_on_continue=True)
    def pre_hook(run_input=None, session=None, user_id=None):
        calls.append(getattr(session, "session_id", None))

    team = Team(name="hook-test-team-stream", members=[], pre_hooks=[pre_hook])

    def empty_model_stream(*args, **kwargs):
        return
        yield

    import agno.team._response as team_response

    monkeypatch.setattr(team_response, "_handle_model_response_stream", empty_model_stream)
    monkeypatch.setattr(team_response, "parse_response_with_parser_model_stream", empty_model_stream)
    monkeypatch.setattr(team_response, "generate_response_with_output_model_stream", empty_model_stream)
    monkeypatch.setattr(team_run, "_cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(team_telemetry, "log_team_telemetry", lambda *a, **k: None)

    list(
        team_run._continue_run_stream(
            team,
            run_response=_make_paused_team_run(),
            run_messages=_make_run_messages(),
            run_context=_make_run_context(),
            tools=[],
            session=_make_team_session(),
            user_id="user-1",
        )
    )

    assert calls == ["session-1"]


# ---------------------------------------------------------------------------
# Async, non-streaming (_acontinue_run)
# ---------------------------------------------------------------------------


def test_team_acontinue_run_executes_pre_hooks(monkeypatch):
    async def main():
        calls = []

        @hook(run_on_continue=True)
        async def pre_hook(run_input=None, session=None):
            calls.append(getattr(session, "session_id", None))

        team = Team(name="hook-test-team-async", members=[], pre_hooks=[pre_hook])

        async def fake_session(team, run_context=None, session_id=None, user_id=None, run_id=None):
            return TeamSession(session_id=session_id, user_id=user_id)

        model_calls = []

        async def fake_model(*args, **kwargs):
            model_calls.append(1)
            return ModelResponse(role="assistant", content="continued")

        async def async_noop(*args, **kwargs):
            return None

        monkeypatch.setattr(team_run, "_asetup_session", fake_session)
        monkeypatch.setattr(team_run, "acall_model_with_fallback", fake_model)
        monkeypatch.setattr(team_run, "_acleanup_and_store", async_noop)
        monkeypatch.setattr(team_telemetry, "alog_team_telemetry", async_noop)

        result = await team_run._acontinue_run(
            team,
            session_id="session-1",
            run_context=_make_run_context(),
            run_response=_make_paused_team_run(),
            requirements=[],
            user_id="user-1",
        )

        assert result.status == RunStatus.completed
        assert model_calls == [1]
        assert calls == ["session-1"]

    asyncio.run(main())


def test_team_acontinue_run_pre_hook_guardrail_blocks(monkeypatch):
    async def main():
        @hook(run_on_continue=True)
        def blocking_hook(run_input=None):
            raise InputCheckError("authz denied on team resume")

        team = Team(name="guard-test-team-async", members=[], pre_hooks=[blocking_hook])

        async def fake_session(team, run_context=None, session_id=None, user_id=None, run_id=None):
            return TeamSession(session_id=session_id, user_id=user_id)

        model_calls = []

        async def fake_model(*args, **kwargs):
            model_calls.append(1)
            return ModelResponse(role="assistant", content="continued")

        async def async_noop(*args, **kwargs):
            return None

        monkeypatch.setattr(team_run, "_asetup_session", fake_session)
        monkeypatch.setattr(team_run, "acall_model_with_fallback", fake_model)
        monkeypatch.setattr(team_run, "_acleanup_and_store", async_noop)
        monkeypatch.setattr(team_telemetry, "alog_team_telemetry", async_noop)

        result = await team_run._acontinue_run(
            team,
            session_id="session-1",
            run_context=_make_run_context(),
            run_response=_make_paused_team_run(),
            requirements=[],
            user_id="user-1",
        )

        assert model_calls == [], "model must not be invoked when a pre-hook guardrail fails"
        assert result.status == RunStatus.error
        assert "authz denied on team resume" in str(result.content)

    asyncio.run(main())


# ---------------------------------------------------------------------------
# Async, streaming (_acontinue_run_stream)
# ---------------------------------------------------------------------------


def test_team_acontinue_run_stream_executes_pre_hooks(monkeypatch):
    async def main():
        calls = []

        @hook(run_on_continue=True)
        async def pre_hook(run_input=None, session=None):
            calls.append(getattr(session, "session_id", None))

        team = Team(name="hook-test-team-async-stream", members=[], pre_hooks=[pre_hook])

        async def fake_session(team, run_context=None, session_id=None, user_id=None, run_id=None):
            return TeamSession(session_id=session_id, user_id=user_id)

        async def async_noop(*args, **kwargs):
            return None

        import agno.team._response as team_response

        monkeypatch.setattr(team_run, "_asetup_session", fake_session)
        monkeypatch.setattr(team_response, "_ahandle_model_response_stream", _empty_async_generator)
        monkeypatch.setattr(team_response, "aparse_response_with_parser_model_stream", _empty_async_generator)
        monkeypatch.setattr(team_response, "agenerate_response_with_output_model_stream", _empty_async_generator)
        monkeypatch.setattr(team_run, "_acleanup_and_store", async_noop)
        monkeypatch.setattr(team_telemetry, "alog_team_telemetry", async_noop)

        async for _ in team_run._acontinue_run_stream(
            team,
            session_id="session-1",
            run_context=_make_run_context(),
            run_response=_make_paused_team_run(),
            requirements=[],
            user_id="user-1",
        ):
            pass

        assert calls == ["session-1"]

    asyncio.run(main())


# ---------------------------------------------------------------------------
# Background hooks mode (run_hooks_in_background=True)
# ---------------------------------------------------------------------------


class _FakeBackgroundTasks:
    """Minimal stand-in for fastapi.BackgroundTasks."""

    def __init__(self):
        self.queued = []

    def add_task(self, func, **kwargs):
        self.queued.append(func)


def test_team_continue_run_background_mode_queues_non_guardrail_hooks(monkeypatch):
    executed = []

    @hook(run_on_continue=True)
    def audit_hook(run_input=None, session=None):
        executed.append(1)

    team = Team(name="bg-continue-team", members=[], pre_hooks=[audit_hook])
    team._run_hooks_in_background = True
    _patch_team_sync_model(monkeypatch)
    monkeypatch.setattr(team_run, "_cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(team_telemetry, "log_team_telemetry", lambda *a, **k: None)
    background_tasks = _FakeBackgroundTasks()

    result = team_run._continue_run(
        team,
        run_response=_make_paused_team_run(),
        run_messages=_make_run_messages(),
        run_context=_make_run_context(),
        tools=[],
        session=_make_team_session(),
        user_id="user-1",
        background_tasks=background_tasks,
    )

    assert result.status == RunStatus.completed
    assert executed == [], "non-guardrail pre-hook must not run inline in background mode"
    assert background_tasks.queued == [audit_hook], "pre-hook should be queued for background execution"


def test_team_continue_run_stream_emits_pre_hook_events(monkeypatch):
    calls = []

    @hook(run_on_continue=True)
    def pre_hook(run_input=None, session=None):
        calls.append(1)

    team = Team(name="stream-ev-team", members=[], pre_hooks=[pre_hook])

    def empty_model_stream(*args, **kwargs):
        return
        yield

    import agno.team._response as team_response

    monkeypatch.setattr(team_response, "_handle_model_response_stream", empty_model_stream)
    monkeypatch.setattr(team_response, "parse_response_with_parser_model_stream", empty_model_stream)
    monkeypatch.setattr(team_response, "generate_response_with_output_model_stream", empty_model_stream)
    monkeypatch.setattr(team_run, "_cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(team_telemetry, "log_team_telemetry", lambda *a, **k: None)

    events = list(
        team_run._continue_run_stream(
            team,
            run_response=_make_paused_team_run(),
            run_messages=_make_run_messages(),
            run_context=_make_run_context(),
            tools=[],
            session=_make_team_session(),
            user_id="user-1",
            stream_events=True,
        )
    )

    assert calls == [1]
    event_names = [type(e).__name__ for e in events]
    assert any("PreHookStarted" in name for name in event_names), event_names
    assert any("PreHookCompleted" in name for name in event_names), event_names
