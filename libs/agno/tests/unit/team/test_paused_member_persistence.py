"""
Unit tests for paused member run persistence in team routing helpers.

Regression test for: https://github.com/agno-agi/agno/issues/8925

When a member pauses during team.continue_run() routing, its RunOutput must be
persisted to session.runs so subsequent continue_run calls can find it after
session reload.
"""

import json
from typing import Any, AsyncIterator, Iterator, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_execution(**overrides) -> ToolExecution:
    defaults = dict(tool_name="do_something", tool_args={"x": 1})
    defaults.update(overrides)
    return ToolExecution(**defaults)


def _make_requirement(**te_overrides) -> RunRequirement:
    return RunRequirement(tool_execution=_make_tool_execution(**te_overrides))


def _make_run_response_and_session():
    run_response = MagicMock()
    run_response.run_id = "team-run-1"
    run_response.member_responses = []

    member_run_output = MagicMock()
    member_run_output.run_id = "member-run-1"
    member_run_output.tools = None
    member_run_output.is_paused = False
    member_run_output.content = "done"

    req = _make_requirement(requires_confirmation=True)
    req.member_agent_id = "member-id-1"
    req.member_run_id = "member-run-1"
    req._member_run_response = member_run_output

    run_response.requirements = [req]

    session = MagicMock()
    session.session_id = "session-1"
    session.upsert_run = MagicMock()

    return run_response, session


# ---------------------------------------------------------------------------
# Sync non-streaming
# ---------------------------------------------------------------------------


def test_sync_routing_persists_paused_member_run():
    from agno.team._run import _route_requirements_to_members

    run_response, session = _make_run_response_and_session()

    paused_response = MagicMock(is_paused=True, content=None, run_id="member-run-1")
    paused_response.requirements = [_make_requirement(requires_user_input=True)]

    member = MagicMock()
    member.name = "Member 1"
    member.continue_run = MagicMock(return_value=paused_response)

    with (
        patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)),
        patch("agno.team._tools._propagate_member_pause"),
    ):
        _route_requirements_to_members(MagicMock(), run_response=run_response, session=session, run_context=None)

    session.upsert_run.assert_called_once_with(paused_response)


def test_sync_routing_persists_completed_member_run():
    from agno.team._run import _route_requirements_to_members

    run_response, session = _make_run_response_and_session()

    completed_response = MagicMock(is_paused=False, content="done", run_id="member-run-1")

    member = MagicMock()
    member.name = "Member 1"
    member.continue_run = MagicMock(return_value=completed_response)

    with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
        _route_requirements_to_members(MagicMock(), run_response=run_response, session=session, run_context=None)

    session.upsert_run.assert_called_once_with(completed_response)


# ---------------------------------------------------------------------------
# Async non-streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_routing_persists_paused_member_run():
    from agno.team._run import _aroute_requirements_to_members

    run_response, session = _make_run_response_and_session()

    paused_response = MagicMock(is_paused=True, content=None, run_id="member-run-1")
    paused_response.requirements = [_make_requirement(requires_user_input=True)]

    member = MagicMock()
    member.name = "Member 1"
    member.acontinue_run = AsyncMock(return_value=paused_response)

    with (
        patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)),
        patch("agno.team._tools._propagate_member_pause"),
    ):
        await _aroute_requirements_to_members(MagicMock(), run_response=run_response, session=session, run_context=None)

    session.upsert_run.assert_called_once_with(paused_response)


@pytest.mark.asyncio
async def test_async_routing_persists_completed_member_run():
    from agno.team._run import _aroute_requirements_to_members

    run_response, session = _make_run_response_and_session()

    completed_response = MagicMock(is_paused=False, content="done", run_id="member-run-1")

    member = MagicMock()
    member.name = "Member 1"
    member.acontinue_run = AsyncMock(return_value=completed_response)

    with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
        await _aroute_requirements_to_members(MagicMock(), run_response=run_response, session=session, run_context=None)

    session.upsert_run.assert_called_once_with(completed_response)


# ---------------------------------------------------------------------------
# Sync streaming
# ---------------------------------------------------------------------------


def test_sync_streaming_routing_persists_paused_member_run():
    from agno.team._run import _route_requirements_to_members_stream

    run_response, session = _make_run_response_and_session()

    paused_response = RunOutput(run_id="member-run-1")
    paused_response.status = RunStatus.paused
    paused_response.requirements = [_make_requirement(requires_user_input=True)]

    def member_stream(*args, **kwargs):
        yield paused_response

    member = MagicMock()
    member.name = "Member 1"
    member.continue_run = MagicMock(side_effect=lambda *a, **kw: member_stream())

    team = MagicMock()
    team.stream_member_events = False
    team.events_to_skip = []
    team.store_events = False

    with (
        patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)),
        patch("agno.team._tools._propagate_member_pause"),
        patch("agno.team._run.raise_if_cancelled"),
        patch("agno.team._run.register_member_run"),
    ):
        list(
            _route_requirements_to_members_stream(
                team,
                run_response=run_response,
                session=session,
                member_results=[],
                run_context=None,
                stream_events=False,
            )
        )

    session.upsert_run.assert_called_once_with(paused_response)


def test_sync_streaming_routing_persists_completed_member_run():
    from agno.team._run import _route_requirements_to_members_stream

    run_response, session = _make_run_response_and_session()

    completed_response = RunOutput(run_id="member-run-1")
    completed_response.status = RunStatus.completed
    completed_response.content = "done"

    def member_stream(*args, **kwargs):
        yield completed_response

    member = MagicMock()
    member.name = "Member 1"
    member.continue_run = MagicMock(side_effect=lambda *a, **kw: member_stream())

    team = MagicMock()
    team.stream_member_events = False
    team.events_to_skip = []
    team.store_events = False

    with (
        patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)),
        patch("agno.team._run.raise_if_cancelled"),
        patch("agno.team._run.register_member_run"),
    ):
        list(
            _route_requirements_to_members_stream(
                team,
                run_response=run_response,
                session=session,
                member_results=[],
                run_context=None,
                stream_events=False,
            )
        )

    session.upsert_run.assert_called_once_with(completed_response)


# ---------------------------------------------------------------------------
# Async streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_streaming_routing_persists_paused_member_run():
    from agno.team._run import _aroute_requirements_to_members_stream

    run_response, session = _make_run_response_and_session()

    paused_response = RunOutput(run_id="member-run-1")
    paused_response.status = RunStatus.paused
    paused_response.requirements = [_make_requirement(requires_user_input=True)]

    async def member_stream(*args, **kwargs):
        yield paused_response

    member = MagicMock()
    member.name = "Member 1"
    member.acontinue_run = MagicMock(side_effect=lambda *a, **kw: member_stream())

    team = MagicMock()
    team.stream_member_events = False
    team.events_to_skip = []
    team.store_events = False

    with (
        patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)),
        patch("agno.team._tools._propagate_member_pause"),
        patch("agno.team._run.araise_if_cancelled", new_callable=AsyncMock),
        patch("agno.team._run.aregister_member_run", new_callable=AsyncMock),
    ):
        async for _ in _aroute_requirements_to_members_stream(
            team,
            run_response=run_response,
            session=session,
            member_results=[],
            run_context=None,
            stream_events=False,
        ):
            pass

    session.upsert_run.assert_called_once_with(paused_response)


@pytest.mark.asyncio
async def test_async_streaming_routing_persists_completed_member_run():
    from agno.team._run import _aroute_requirements_to_members_stream

    run_response, session = _make_run_response_and_session()

    completed_response = RunOutput(run_id="member-run-1")
    completed_response.status = RunStatus.completed
    completed_response.content = "done"

    async def member_stream(*args, **kwargs):
        yield completed_response

    member = MagicMock()
    member.name = "Member 1"
    member.acontinue_run = MagicMock(side_effect=lambda *a, **kw: member_stream())

    team = MagicMock()
    team.stream_member_events = False
    team.events_to_skip = []
    team.store_events = False

    with (
        patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)),
        patch("agno.team._run.araise_if_cancelled", new_callable=AsyncMock),
        patch("agno.team._run.aregister_member_run", new_callable=AsyncMock),
    ):
        async for _ in _aroute_requirements_to_members_stream(
            team,
            run_response=run_response,
            session=session,
            member_results=[],
            run_context=None,
            stream_events=False,
        ):
            pass

    session.upsert_run.assert_called_once_with(completed_response)


# ---------------------------------------------------------------------------
# End-to-end persistence across a session reload (scripted model, no network)
#
# A member pause must survive the default store_member_responses=False scrub
# and a full process restart: pause -> save -> reload with fresh Team/Agent
# objects -> continue_run with wire-serialized requirements -> the gated tool
# executes and the run completes. The nested-team variant is the regression
# target: the paused sub-member run lives only inside the sub-team's
# TeamRunOutput.member_responses (sub-teams skip save_session), so scrubbing
# it leaves nothing to resume.
# ---------------------------------------------------------------------------


class _ScriptedModel(Model):
    """Emits scripted turns offline: ('tool', name, args, id) or ('content', text)."""

    def __init__(self, model_id: str, script: List[tuple]):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._script = list(script)
        self._i = 0

    def _next(self) -> ModelResponse:
        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tool":
            _, name, args, tcid = turn
            r = ModelResponse(role="assistant")
            r.tool_calls = [{"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]
            return r
        r = ModelResponse(content=turn[1], role="assistant")
        r.event = ModelResponseEvent.assistant_response.value
        return r

    def invoke(self, *a, **k):
        return self._next()

    async def ainvoke(self, *a, **k):
        return self._next()

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


_EXECUTED: List[str] = []


@tool(requires_confirmation=True)
def send_email(to: str) -> str:
    _EXECUTED.append(to)
    return f"Email sent to {to}"


def _wire_requirements(requirements) -> List[RunRequirement]:
    """Round-trip requirements through their wire format and confirm them,
    the way a frontend or a fresh process would send them back."""
    confirmed = []
    for data in [r.to_dict() for r in requirements or []]:
        req = RunRequirement.from_dict(data)
        req.confirm()
        confirmed.append(req)
    return confirmed


def _emailer_agent(db: SqliteDb, resuming: bool) -> Agent:
    script = (
        [("content", "Email sent.")]
        if resuming
        else [("tool", "send_email", {"to": "a@example.com"}, "tc-send"), ("content", "Email sent.")]
    )
    return Agent(
        name="Emailer",
        id="emailer",
        model=_ScriptedModel("m-emailer", script),
        tools=[send_email],
        db=db,
        telemetry=False,
    )


def _build_flat_team(db: SqliteDb, resuming: bool, **team_kwargs) -> Team:
    script = (
        [("content", "All done.")]
        if resuming
        else [
            ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-deleg"),
            ("content", "All done."),
        ]
    )
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel("m-leader", script),
        members=[_emailer_agent(db, resuming)],
        db=db,
        telemetry=False,
        **team_kwargs,
    )


def _build_nested_team(db: SqliteDb, resuming: bool) -> Team:
    inner_script = (
        [("content", "Inner done.")]
        if resuming
        else [
            ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-inner-deleg"),
            ("content", "Inner done."),
        ]
    )
    outer_script = (
        [("content", "All done.")]
        if resuming
        else [
            ("tool", "delegate_task_to_member", {"member_id": "comms-team", "task": "handle email"}, "tc-outer-deleg"),
            ("content", "All done."),
        ]
    )
    inner = Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel("m-inner", inner_script),
        members=[_emailer_agent(db, resuming)],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Org Team",
        id="org-team",
        model=_ScriptedModel("m-outer", outer_script),
        members=[inner],
        db=db,
        telemetry=False,
    )


def _reload_runs(db_file: str, session_id: str):
    session = SqliteDb(db_file=db_file).get_session(session_id=session_id, session_type="team")
    assert session is not None
    return session.runs or []


def test_flat_member_pause_survives_fresh_process_continue(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "flat.db")
    session_id = "s-flat"

    team1 = _build_flat_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []

    # The paused member run survives the save with the default flag: the team
    # run row keeps it in member_responses with everything resume needs.
    team_runs = [r for r in _reload_runs(db_file, session_id) if isinstance(r, TeamRunOutput)]
    assert len(team_runs) == 1
    spared = [m for m in team_runs[0].member_responses if getattr(m, "is_paused", False)]
    assert len(spared) == 1
    assert spared[0].run_id is not None
    assert spared[0].messages, "resume continues the model conversation from these messages"
    assert spared[0].tools and spared[0].tools[0].requires_confirmation
    assert spared[0].requirements and not spared[0].requirements[0].is_resolved()

    # Fresh process: new objects, wire-serialized requirements.
    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]

    # The member run completed, so the next save scrubbed it again.
    team_runs = [r for r in _reload_runs(db_file, session_id) if isinstance(r, TeamRunOutput)]
    assert all(r.member_responses == [] for r in team_runs)


def test_nested_member_pause_survives_fresh_process_continue(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "nested.db")
    session_id = "s-nested"

    outer1 = _build_nested_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = outer1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []

    # The paused sub-member run is only reachable through the sub-team's
    # TeamRunOutput (sub-teams skip save_session), so it must survive there.
    inner_runs = [r for r in _reload_runs(db_file, session_id) if getattr(r, "team_id", None) == "comms-team"]
    assert len(inner_runs) == 1
    spared = [m for m in inner_runs[0].member_responses if getattr(m, "is_paused", False)]
    assert len(spared) == 1
    assert spared[0].messages
    assert spared[0].tools and spared[0].tools[0].requires_confirmation
    assert spared[0].requirements and not spared[0].requirements[0].is_resolved()

    outer2 = _build_nested_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = outer2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]

    team_runs = [r for r in _reload_runs(db_file, session_id) if isinstance(r, TeamRunOutput)]
    assert all(r.member_responses == [] for r in team_runs)


@pytest.mark.asyncio
async def test_nested_member_pause_survives_fresh_process_continue_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "nested_async.db")
    session_id = "s-nested-async"

    outer1 = _build_nested_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = await outer1.arun("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    inner_runs = [r for r in _reload_runs(db_file, session_id) if getattr(r, "team_id", None) == "comms-team"]
    assert len(inner_runs) == 1
    assert any(getattr(m, "is_paused", False) for m in inner_runs[0].member_responses)

    outer2 = _build_nested_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = await outer2.acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


def test_nested_member_pause_resumes_same_process(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "nested_same.db")
    session_id = "s-nested-same"

    outer = _build_nested_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = outer.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    for req in run1.requirements or []:
        req.confirm()
    run2 = outer.continue_run(run1)
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"], "the confirmed tool must actually execute"


def test_completed_member_responses_still_scrubbed_with_default_flag(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "completed.db")
    session_id = "s-completed"

    emailer = Agent(
        name="Emailer",
        id="emailer",
        model=_ScriptedModel("m-emailer", [("content", "No email needed.")]),
        db=SqliteDb(db_file=db_file),
        telemetry=False,
    )
    team = Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-leader",
            [
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "check"}, "tc-deleg"),
                ("content", "All done."),
            ],
        ),
        members=[emailer],
        db=SqliteDb(db_file=db_file),
        telemetry=False,
    )
    run = team.run("Anything to send?", session_id=session_id)
    assert run.status == RunStatus.completed

    team_runs = [r for r in _reload_runs(db_file, session_id) if isinstance(r, TeamRunOutput)]
    assert len(team_runs) == 1
    assert team_runs[0].member_responses == []


def test_store_member_responses_true_keeps_paused_and_completed(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "flag_true.db")
    session_id = "s-flag-true"

    team1 = _build_flat_team(SqliteDb(db_file=db_file), resuming=False, store_member_responses=True)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    team_runs = [r for r in _reload_runs(db_file, session_id) if isinstance(r, TeamRunOutput)]
    assert len(team_runs) == 1
    assert len(team_runs[0].member_responses) == 1

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True, store_member_responses=True)
    run2 = team2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]

    # With the flag on, completed member responses are kept.
    team_runs = [r for r in _reload_runs(db_file, session_id) if isinstance(r, TeamRunOutput)]
    assert len(team_runs[0].member_responses) == 1
