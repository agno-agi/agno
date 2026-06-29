import inspect
from typing import Any

import pytest

from agno.agent.agent import Agent
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.session.summary import SessionSummaryManager
from agno.team import _hooks, _init, _messages
from agno.team import _run as team_run
from agno.team.team import Team


def test_all_team_pause_handlers_accept_run_context():
    for fn in [
        _hooks.handle_team_run_paused,
        _hooks.handle_team_run_paused_stream,
        _hooks.ahandle_team_run_paused,
        _hooks.ahandle_team_run_paused_stream,
    ]:
        params = inspect.signature(fn).parameters
        assert "run_context" in params, f"{fn.__name__} missing run_context param"


def test_handle_team_run_paused_forwards_run_context_to_cleanup(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    def spy_cleanup(team, run_response, session, run_context=None):
        captured["run_context"] = run_context

    monkeypatch.setattr(team_run, "_cleanup_and_store", spy_cleanup)
    monkeypatch.setattr("agno.run.approval.create_approval_from_pause", lambda **kwargs: None)

    team = Team(name="test-team", members=[Agent(name="m1")])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"key": "val"})

    _hooks.handle_team_run_paused(
        team=team,
        run_response=TeamRunOutput(run_id="r1", session_id="s1", messages=[]),
        session=TeamSession(session_id="s1"),
        run_context=run_context,
    )

    assert captured["run_context"] is run_context


@pytest.mark.asyncio
async def test_ahandle_team_run_paused_forwards_run_context_to_cleanup(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def spy_acleanup(team, run_response, session, run_context=None):
        captured["run_context"] = run_context

    async def noop_acreate_approval(**kwargs):
        return None

    monkeypatch.setattr(team_run, "_acleanup_and_store", spy_acleanup)
    monkeypatch.setattr("agno.run.approval.acreate_approval_from_pause", noop_acreate_approval)

    team = Team(name="test-team", members=[Agent(name="m1")])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"key": "val"})

    await _hooks.ahandle_team_run_paused(
        team=team,
        run_response=TeamRunOutput(run_id="r1", session_id="s1", messages=[]),
        session=TeamSession(session_id="s1"),
        run_context=run_context,
    )

    assert captured["run_context"] is run_context


def test_handle_team_run_paused_persists_session_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(team_run, "scrub_run_output_for_storage", lambda team, run_response: None)
    monkeypatch.setattr("agno.team._session.update_session_metrics", lambda team, session, run_response: None)
    monkeypatch.setattr("agno.run.approval.create_approval_from_pause", lambda **kwargs: None)

    team = Team(name="test-team", members=[Agent(name="m1")])
    monkeypatch.setattr(team, "save_session", lambda session: None)

    session = TeamSession(session_id="s1", session_data={})
    run_response = TeamRunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"watchlist": ["AAPL"]})

    result = _hooks.handle_team_run_paused(
        team=team,
        run_response=run_response,
        session=session,
        run_context=run_context,
    )

    assert result.status == RunStatus.paused
    assert session.session_data["session_state"] == {"watchlist": ["AAPL"]}
    assert result.session_state == {"watchlist": ["AAPL"]}


def test_handle_team_run_paused_without_run_context_does_not_set_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(team_run, "scrub_run_output_for_storage", lambda team, run_response: None)
    monkeypatch.setattr("agno.team._session.update_session_metrics", lambda team, session, run_response: None)
    monkeypatch.setattr("agno.run.approval.create_approval_from_pause", lambda **kwargs: None)

    team = Team(name="test-team", members=[Agent(name="m1")])
    monkeypatch.setattr(team, "save_session", lambda session: None)

    session = TeamSession(session_id="s1", session_data={})

    result = _hooks.handle_team_run_paused(
        team=team,
        run_response=TeamRunOutput(run_id="r1", session_id="s1", messages=[]),
        session=session,
    )

    assert result.status == RunStatus.paused
    assert "session_state" not in session.session_data


def test_team_history_skip_statuses_are_passed_to_context_history(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}
    team = Team(name="test-team", members=[], add_history_to_context=True, history_skip_statuses=[])
    session = TeamSession(session_id="s1")

    monkeypatch.setattr(team, "get_system_message", lambda **kwargs: None)

    def spy_get_messages(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(session, "get_messages", spy_get_messages)

    _messages._get_run_messages(
        team=team,
        run_response=TeamRunOutput(run_id="r1", session_id="s1", messages=[]),
        run_context=RunContext(run_id="r1", session_id="s1"),
        session=session,
        add_history_to_context=True,
        input_message="hello",
    )

    assert captured["skip_statuses"] == []


def test_team_summary_manager_inherits_history_skip_statuses():
    team = Team(name="test-team", members=[], history_skip_statuses=[])
    team.session_summary_manager = SessionSummaryManager()
    team.add_session_summary_to_context = None

    _init._set_session_summary_manager(team)

    assert team.session_summary_manager.skip_statuses == []


def test_session_summary_manager_uses_configured_skip_statuses(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}
    summary_manager = SessionSummaryManager(model=object(), skip_statuses=[])
    session = TeamSession(session_id="s1")

    class DummyModel:
        supports_native_structured_outputs = False
        supports_json_schema_outputs = False

    monkeypatch.setattr("agno.session.summary.get_model", lambda model: DummyModel())

    def spy_get_messages(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(session, "get_messages", spy_get_messages)

    messages = summary_manager._prepare_summary_messages(session)

    assert messages is not None
    assert captured["skip_statuses"] == []


def test_handle_team_run_paused_persists_state_when_session_data_is_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(team_run, "scrub_run_output_for_storage", lambda team, run_response: None)
    monkeypatch.setattr("agno.team._session.update_session_metrics", lambda team, session, run_response: None)
    monkeypatch.setattr("agno.run.approval.create_approval_from_pause", lambda **kwargs: None)

    team = Team(name="test-team", members=[Agent(name="m1")])
    monkeypatch.setattr(team, "save_session", lambda session: None)

    session = TeamSession(session_id="s1", session_data=None)
    run_response = TeamRunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"watchlist": ["AAPL"]})

    result = _hooks.handle_team_run_paused(
        team=team,
        run_response=run_response,
        session=session,
        run_context=run_context,
    )

    assert result.status == RunStatus.paused
    assert result.session_state == {"watchlist": ["AAPL"]}
    assert session.session_data == {"session_state": {"watchlist": ["AAPL"]}}


@pytest.mark.asyncio
async def test_ahandle_team_run_paused_persists_state_when_session_data_is_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(team_run, "scrub_run_output_for_storage", lambda team, run_response: None)
    monkeypatch.setattr("agno.team._session.update_session_metrics", lambda team, session, run_response: None)

    async def noop_acreate_approval(**kwargs):
        return None

    monkeypatch.setattr("agno.run.approval.acreate_approval_from_pause", noop_acreate_approval)

    team = Team(name="test-team", members=[Agent(name="m1")])

    async def noop_asave(session):
        return None

    monkeypatch.setattr(team, "asave_session", noop_asave)

    session = TeamSession(session_id="s1", session_data=None)
    run_response = TeamRunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"cart": ["item-1"]})

    result = await _hooks.ahandle_team_run_paused(
        team=team,
        run_response=run_response,
        session=session,
        run_context=run_context,
    )

    assert result.status == RunStatus.paused
    assert result.session_state == {"cart": ["item-1"]}
    assert session.session_data == {"session_state": {"cart": ["item-1"]}}


@pytest.mark.asyncio
async def test_ahandle_team_run_paused_persists_session_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(team_run, "scrub_run_output_for_storage", lambda team, run_response: None)
    monkeypatch.setattr("agno.team._session.update_session_metrics", lambda team, session, run_response: None)

    async def noop_acreate_approval(**kwargs):
        return None

    monkeypatch.setattr("agno.run.approval.acreate_approval_from_pause", noop_acreate_approval)

    team = Team(name="test-team", members=[Agent(name="m1")])

    async def noop_asave(session):
        return None

    monkeypatch.setattr(team, "asave_session", noop_asave)

    session = TeamSession(session_id="s1", session_data={})
    run_response = TeamRunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"cart": ["item-1"]})

    result = await _hooks.ahandle_team_run_paused(
        team=team,
        run_response=run_response,
        session=session,
        run_context=run_context,
    )

    assert result.status == RunStatus.paused
    assert session.session_data["session_state"] == {"cart": ["item-1"]}
    assert result.session_state == {"cart": ["item-1"]}


def test_handle_team_run_paused_stream_forwards_run_context_to_cleanup(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    def spy_cleanup(team, run_response, session, run_context=None):
        captured["run_context"] = run_context

    monkeypatch.setattr(team_run, "_cleanup_and_store", spy_cleanup)
    monkeypatch.setattr("agno.run.approval.create_approval_from_pause", lambda **kwargs: None)

    team = Team(name="test-team", members=[Agent(name="m1")])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"key": "val"})

    events = list(
        _hooks.handle_team_run_paused_stream(
            team=team,
            run_response=TeamRunOutput(run_id="r1", session_id="s1", messages=[]),
            session=TeamSession(session_id="s1"),
            run_context=run_context,
        )
    )

    assert captured["run_context"] is run_context
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_ahandle_team_run_paused_stream_forwards_run_context_to_cleanup(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def spy_acleanup(team, run_response, session, run_context=None):
        captured["run_context"] = run_context

    async def noop_acreate_approval(**kwargs):
        return None

    monkeypatch.setattr(team_run, "_acleanup_and_store", spy_acleanup)
    monkeypatch.setattr("agno.run.approval.acreate_approval_from_pause", noop_acreate_approval)

    team = Team(name="test-team", members=[Agent(name="m1")])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"key": "val"})

    events = []
    async for event in _hooks.ahandle_team_run_paused_stream(
        team=team,
        run_response=TeamRunOutput(run_id="r1", session_id="s1", messages=[]),
        session=TeamSession(session_id="s1"),
        run_context=run_context,
    ):
        events.append(event)

    assert captured["run_context"] is run_context
    assert len(events) >= 1


def test_handle_team_run_paused_stream_persists_session_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(team_run, "scrub_run_output_for_storage", lambda team, run_response: None)
    monkeypatch.setattr("agno.team._session.update_session_metrics", lambda team, session, run_response: None)
    monkeypatch.setattr("agno.run.approval.create_approval_from_pause", lambda **kwargs: None)

    team = Team(name="test-team", members=[Agent(name="m1")])
    monkeypatch.setattr(team, "save_session", lambda session: None)

    session = TeamSession(session_id="s1", session_data={})
    run_response = TeamRunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"watchlist": ["AAPL"]})

    events = list(
        _hooks.handle_team_run_paused_stream(
            team=team,
            run_response=run_response,
            session=session,
            run_context=run_context,
        )
    )

    assert len(events) >= 1
    assert session.session_data["session_state"] == {"watchlist": ["AAPL"]}
    assert run_response.session_state == {"watchlist": ["AAPL"]}


@pytest.mark.asyncio
async def test_ahandle_team_run_paused_stream_persists_session_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(team_run, "scrub_run_output_for_storage", lambda team, run_response: None)
    monkeypatch.setattr("agno.team._session.update_session_metrics", lambda team, session, run_response: None)

    async def noop_acreate_approval(**kwargs):
        return None

    monkeypatch.setattr("agno.run.approval.acreate_approval_from_pause", noop_acreate_approval)

    team = Team(name="test-team", members=[Agent(name="m1")])

    async def noop_asave(session):
        return None

    monkeypatch.setattr(team, "asave_session", noop_asave)

    session = TeamSession(session_id="s1", session_data={})
    run_response = TeamRunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"cart": ["item-1"]})

    events = []
    async for event in _hooks.ahandle_team_run_paused_stream(
        team=team,
        run_response=run_response,
        session=session,
        run_context=run_context,
    ):
        events.append(event)

    assert len(events) >= 1
    assert session.session_data["session_state"] == {"cart": ["item-1"]}
    assert run_response.session_state == {"cart": ["item-1"]}
