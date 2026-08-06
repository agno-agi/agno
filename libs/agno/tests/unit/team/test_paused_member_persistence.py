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
        from agno.metrics import MessageMetrics

        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tools":
            r = ModelResponse(role="assistant")
            r.tool_calls = [
                {"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
                for name, args, tcid in turn[1]
            ]
        elif turn[0] == "tool":
            _, name, args, tcid = turn
            r = ModelResponse(role="assistant")
            r.tool_calls = [{"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]
        else:
            r = ModelResponse(content=turn[1], role="assistant")
            r.event = ModelResponseEvent.assistant_response.value
        # Every model turn reports the same usage so tests can assert
        # session-metrics totals as (number of model calls) * 15.
        r.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
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


# ---------------------------------------------------------------------------
# Deeper topologies: 3-level nesting, multiple paused members per sub-team,
# streaming resume, deep scrub, and session-metrics accuracy.
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def send_sms(to: str) -> str:
    _EXECUTED.append(f"sms:{to}")
    return f"SMS sent to {to}"


def _build_three_level_team(db: SqliteDb, resuming: bool) -> Team:
    inner = Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-inner",
            [("content", "Inner done.")]
            if resuming
            else [
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-inner-deleg"),
                ("content", "Inner done."),
            ],
        ),
        members=[_emailer_agent(db, resuming)],
        db=db,
        telemetry=False,
    )
    mid = Team(
        name="Division Team",
        id="div-team",
        model=_ScriptedModel(
            "m-mid",
            [("content", "Division done.")]
            if resuming
            else [
                (
                    "tool",
                    "delegate_task_to_member",
                    {"member_id": "comms-team", "task": "handle email"},
                    "tc-mid-deleg",
                ),
                ("content", "Division done."),
            ],
        ),
        members=[inner],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Org Team",
        id="org-team",
        model=_ScriptedModel(
            "m-outer",
            [("content", "All done.")]
            if resuming
            else [
                (
                    "tool",
                    "delegate_task_to_member",
                    {"member_id": "div-team", "task": "handle comms"},
                    "tc-outer-deleg",
                ),
                ("content", "All done."),
            ],
        ),
        members=[mid],
        db=db,
        telemetry=False,
    )


def _build_two_member_subteam(db: SqliteDb, resuming: bool) -> Team:
    smser = Agent(
        name="Smser",
        id="smser",
        model=_ScriptedModel(
            "m-smser",
            [("content", "SMS sent.")]
            if resuming
            else [("tool", "send_sms", {"to": "b@x.com"}, "tc-sms"), ("content", "SMS sent.")],
        ),
        tools=[send_sms],
        db=db,
        telemetry=False,
    )
    emailer = Agent(
        name="Emailer",
        id="emailer",
        model=_ScriptedModel(
            "m-emailer",
            [("content", "Email sent.")]
            if resuming
            else [("tool", "send_email", {"to": "a@x.com"}, "tc-send"), ("content", "Email sent.")],
        ),
        tools=[send_email],
        db=db,
        telemetry=False,
    )
    inner = Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-inner",
            [("content", "Inner done.")]
            if resuming
            else [
                (
                    "tools",
                    [
                        ("delegate_task_to_member", {"member_id": "emailer", "task": "email it"}, "tc-d1"),
                        ("delegate_task_to_member", {"member_id": "smser", "task": "sms it"}, "tc-d2"),
                    ],
                ),
                ("content", "Inner done."),
            ],
        ),
        members=[emailer, smser],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Org Team",
        id="org-team",
        model=_ScriptedModel(
            "m-outer",
            [("content", "Outer done.")]
            if resuming
            else [
                ("tool", "delegate_task_to_member", {"member_id": "comms-team", "task": "notify"}, "tc-outer"),
                ("content", "Outer done."),
            ],
        ),
        members=[inner],
        db=db,
        telemetry=False,
    )


def test_three_level_nested_pause_resumes_same_process(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "three_same.db")
    session_id = "s-three-same"

    outer = _build_three_level_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = outer.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    for req in run1.requirements or []:
        req.confirm()
    run2 = outer.continue_run(run1)
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"], "the confirmed tool must actually execute"


def test_three_level_nested_pause_survives_fresh_process_continue(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "three_fresh.db")
    session_id = "s-three-fresh"

    outer1 = _build_three_level_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = outer1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    outer2 = _build_three_level_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = outer2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]

    # Eight model turns at 15 tokens each across pause and resume, counted once.
    session = SqliteDb(db_file=db_file).get_session(session_id=session_id, session_type="team")
    metrics = (session.session_data or {}).get("session_metrics") or {}
    assert metrics.get("total_tokens") == 120, f"expected 120 total tokens, got {metrics.get('total_tokens')}"


@pytest.mark.asyncio
async def test_three_level_nested_pause_resumes_same_process_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "three_same_async.db")
    session_id = "s-three-same-async"

    outer = _build_three_level_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = await outer.arun("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    for req in run1.requirements or []:
        req.confirm()
    run2 = await outer.acontinue_run(run1)
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"], "a swallowed member error must not report success"


def test_two_paused_members_in_one_subteam_both_execute(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "two_members.db")
    session_id = "s-two-members"

    outer1 = _build_two_member_subteam(SqliteDb(db_file=db_file), resuming=False)
    run1 = outer1.run("Notify everyone", session_id=session_id)
    assert run1.is_paused
    assert len(run1.requirements or []) == 2

    outer2 = _build_two_member_subteam(SqliteDb(db_file=db_file), resuming=True)
    run2 = outer2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert sorted(_EXECUTED) == ["a@x.com", "sms:b@x.com"], "both confirmed tools must execute"


@pytest.mark.asyncio
async def test_two_paused_members_in_one_subteam_both_execute_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "two_members_async.db")
    session_id = "s-two-members-async"

    outer1 = _build_two_member_subteam(SqliteDb(db_file=db_file), resuming=False)
    run1 = await outer1.arun("Notify everyone", session_id=session_id)
    assert run1.is_paused

    outer2 = _build_two_member_subteam(SqliteDb(db_file=db_file), resuming=True)
    run2 = await outer2.acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert sorted(_EXECUTED) == ["a@x.com", "sms:b@x.com"]


def test_nested_member_pause_fresh_process_continue_streaming(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "nested_stream.db")
    session_id = "s-nested-stream"

    outer1 = _build_nested_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = outer1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    outer2 = _build_nested_team(SqliteDb(db_file=db_file), resuming=True)
    final = None
    for event in outer2.continue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements(run1.requirements),
        stream=True,
        yield_run_output=True,
    ):
        if isinstance(event, TeamRunOutput):
            final = event
    assert final is not None
    assert final.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


@pytest.mark.asyncio
async def test_nested_member_pause_fresh_process_continue_streaming_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "nested_stream_async.db")
    session_id = "s-nested-stream-async"

    outer1 = _build_nested_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = await outer1.arun("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    outer2 = _build_nested_team(SqliteDb(db_file=db_file), resuming=True)
    final = None
    async for event in outer2.acontinue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements(run1.requirements),
        stream=True,
        yield_run_output=True,
    ):
        if isinstance(event, TeamRunOutput):
            final = event
    assert final is not None
    assert final.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


def test_completed_members_scrubbed_inside_spared_paused_subteam(tmp_path):
    """A paused sub-team run is spared, but the COMPLETED member responses
    inside it are still scrubbed with the default flag, at every level. The
    sub-team sits two levels down so its run is NOT a top-level session row —
    only the recursive scrub reaches the completed response inside it."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "deep_scrub.db")
    session_id = "s-deep-scrub"

    db = SqliteDb(db_file=db_file)
    reporter = Agent(
        name="Reporter",
        id="reporter",
        model=_ScriptedModel("m-reporter", [("content", "SENSITIVE_COMPLETED_RESULT")]),
        db=db,
        telemetry=False,
    )
    inner = Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-inner",
            [
                ("tool", "delegate_task_to_member", {"member_id": "reporter", "task": "report"}, "tc-rep"),
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-mail"),
                ("content", "Inner done."),
            ],
        ),
        members=[reporter, _emailer_agent(db, resuming=False)],
        db=db,
        telemetry=False,
    )
    mid = Team(
        name="Division Team",
        id="div-team",
        model=_ScriptedModel(
            "m-mid",
            [
                ("tool", "delegate_task_to_member", {"member_id": "comms-team", "task": "notify"}, "tc-mid"),
                ("content", "Division done."),
            ],
        ),
        members=[inner],
        db=db,
        telemetry=False,
    )
    outer = Team(
        name="Org Team",
        id="org-team",
        model=_ScriptedModel(
            "m-outer",
            [
                ("tool", "delegate_task_to_member", {"member_id": "div-team", "task": "handle comms"}, "tc-outer"),
                ("content", "Outer done."),
            ],
        ),
        members=[mid],
        db=db,
        telemetry=False,
    )

    run1 = outer.run("Report then email", session_id=session_id)
    assert run1.is_paused

    def walk(runs):
        stack = list(runs)
        while stack:
            r = stack.pop()
            yield r
            stack.extend(getattr(r, "member_responses", None) or [])

    persisted = _reload_runs(db_file, session_id)
    all_runs = list(walk(persisted))
    # The paused chain survives: the sub-team run and the paused emailer inside it.
    assert any(getattr(r, "team_id", None) == "comms-team" and r.is_paused for r in all_runs)
    assert any(getattr(r, "agent_id", None) == "emailer" and r.is_paused for r in all_runs)
    # Completed member responses are scrubbed at every level.
    for r in persisted:
        for m in walk(getattr(r, "member_responses", None) or []):
            assert getattr(m, "is_paused", False), f"completed member response persisted: {m.run_id}"


def test_session_metrics_not_double_counted_on_fresh_process_resume(tmp_path):
    """Every model turn reports 15 total tokens. Four turns happen across the
    pause and the resume (leader delegate, member tool call, member resume,
    leader continuation), so the session must report exactly 60 — not more."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "metrics.db")
    session_id = "s-metrics"

    team1 = _build_flat_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed

    session = SqliteDb(db_file=db_file).get_session(session_id=session_id, session_type="team")
    metrics = (session.session_data or {}).get("session_metrics") or {}
    assert metrics.get("total_tokens") == 60, f"expected 60 total tokens, got {metrics.get('total_tokens')}"


# ---------------------------------------------------------------------------
# Same sub-team paused twice in one turn, live-tree integrity, and
# exactly-once session metrics.
# ---------------------------------------------------------------------------


def _build_same_subteam_twice(db: SqliteDb, resuming: bool) -> Team:
    """The leader delegates TWICE to the same sub-team in one turn; a
    different member pauses in each delegation, so the session holds two
    distinct paused runs of the same sub-team."""
    smser = Agent(
        name="Smser",
        id="smser",
        model=_ScriptedModel(
            "m-smser",
            [("content", "SMS sent.")]
            if resuming
            else [("tool", "send_sms", {"to": "b@x.com"}, "tc-sms"), ("content", "SMS sent.")],
        ),
        tools=[send_sms],
        db=db,
        telemetry=False,
    )
    emailer = Agent(
        name="Emailer",
        id="emailer",
        model=_ScriptedModel(
            "m-emailer",
            [("content", "Email sent.")]
            if resuming
            else [("tool", "send_email", {"to": "a@x.com"}, "tc-send"), ("content", "Email sent.")],
        ),
        tools=[send_email],
        db=db,
        telemetry=False,
    )
    inner = Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-inner",
            # Run 1 consumes the first turn (pauses on emailer), run 2 the
            # second (pauses on smser); on resume the clamped last turn answers.
            [("content", "Inner done.")]
            if resuming
            else [
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "email it"}, "tc-d1"),
                ("tool", "delegate_task_to_member", {"member_id": "smser", "task": "sms it"}, "tc-d2"),
            ],
        ),
        members=[emailer, smser],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Org Team",
        id="org-team",
        model=_ScriptedModel(
            "m-outer",
            [("content", "Outer done.")]
            if resuming
            else [
                (
                    "tools",
                    [
                        ("delegate_task_to_member", {"member_id": "comms-team", "task": "task A"}, "tc-oa"),
                        ("delegate_task_to_member", {"member_id": "comms-team", "task": "task B"}, "tc-ob"),
                    ],
                ),
                ("content", "Outer done."),
            ],
        ),
        members=[inner],
        db=db,
        telemetry=False,
    )


def test_same_subteam_paused_twice_both_confirmations_execute(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "twice.db")
    session_id = "s-twice"

    outer1 = _build_same_subteam_twice(SqliteDb(db_file=db_file), resuming=False)
    run1 = outer1.run("Do task A and task B", session_id=session_id)
    assert run1.is_paused
    assert len(run1.requirements or []) == 2
    assert len({r.member_run_id for r in run1.requirements or []}) == 2, "two distinct paused member runs"

    outer2 = _build_same_subteam_twice(SqliteDb(db_file=db_file), resuming=True)
    run2 = outer2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert sorted(_EXECUTED) == ["a@x.com", "sms:b@x.com"], "both confirmed tools must execute"


@pytest.mark.asyncio
async def test_same_subteam_paused_twice_both_confirmations_execute_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "twice_async.db")
    session_id = "s-twice-async"

    outer1 = _build_same_subteam_twice(SqliteDb(db_file=db_file), resuming=False)
    run1 = await outer1.arun("Do task A and task B", session_id=session_id)
    assert run1.is_paused

    outer2 = _build_same_subteam_twice(SqliteDb(db_file=db_file), resuming=True)
    run2 = await outer2.acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert sorted(_EXECUTED) == ["a@x.com", "sms:b@x.com"]


def _build_completed_sibling_team(db: SqliteDb, resuming: bool) -> Team:
    """Flat team where 'reporter' completes and then 'emailer' pauses."""
    reporter = Agent(
        name="Reporter",
        id="reporter",
        model=_ScriptedModel("m-reporter", [("content", "Report ready.")]),
        db=db,
        telemetry=False,
    )
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-leader",
            [("content", "All done.")]
            if resuming
            else [
                ("tool", "delegate_task_to_member", {"member_id": "reporter", "task": "report"}, "tc-rep"),
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-mail"),
                ("content", "All done."),
            ],
        ),
        members=[reporter, _emailer_agent(db, resuming)],
        db=db,
        telemetry=False,
    )


def test_metrics_exact_with_completed_sibling_before_pause(tmp_path):
    """Reporter completes before the pause; with the default flag its
    response is scrubbed from storage, but its tokens count exactly once.
    Six model turns at 15 tokens each = 90."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "metrics_sibling.db")
    session_id = "s-metrics-sibling"

    team1 = _build_completed_sibling_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Report then email", session_id=session_id)
    assert run1.is_paused

    # The pause-time save counts only runs that reached a final state.
    session = SqliteDb(db_file=db_file).get_session(session_id=session_id, session_type="team")
    metrics = (session.session_data or {}).get("session_metrics") or {}
    assert metrics.get("total_tokens") == 15, "only the completed reporter run is counted while paused"

    team2 = _build_completed_sibling_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed

    session = SqliteDb(db_file=db_file).get_session(session_id=session_id, session_type="team")
    metrics = (session.session_data or {}).get("session_metrics") or {}
    assert metrics.get("total_tokens") == 90, f"expected 90 total tokens, got {metrics.get('total_tokens')}"


def test_live_run_tree_not_mutated_by_save(tmp_path):
    """The default-flag scrub writes filtered copies to storage; the run tree
    the caller holds keeps every member response, at every level. The
    completed reporter sits three levels down, where the recursive scrub
    reaches it — on the storage copy only."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "live_tree.db")
    session_id = "s-live-tree"

    db = SqliteDb(db_file=db_file)
    reporter = Agent(
        name="Reporter",
        id="reporter",
        model=_ScriptedModel("m-reporter", [("content", "Report ready.")]),
        db=db,
        telemetry=False,
    )
    inner = Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-inner",
            [
                ("tool", "delegate_task_to_member", {"member_id": "reporter", "task": "report"}, "tc-rep"),
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-mail"),
                ("content", "Inner done."),
            ],
        ),
        members=[reporter, _emailer_agent(db, resuming=False)],
        db=db,
        telemetry=False,
    )
    mid = Team(
        name="Division Team",
        id="div-team",
        model=_ScriptedModel(
            "m-mid",
            [
                ("tool", "delegate_task_to_member", {"member_id": "comms-team", "task": "notify"}, "tc-mid"),
                ("content", "Division done."),
            ],
        ),
        members=[inner],
        db=db,
        telemetry=False,
    )
    outer = Team(
        name="Org Team",
        id="org-team",
        model=_ScriptedModel(
            "m-outer",
            [
                ("tool", "delegate_task_to_member", {"member_id": "div-team", "task": "handle comms"}, "tc-outer"),
                ("content", "Outer done."),
            ],
        ),
        members=[mid],
        db=db,
        telemetry=False,
    )

    run1 = outer.run("Report then email", session_id=session_id)
    assert run1.is_paused

    # Live tree intact at depth 3: both the completed reporter and the paused emailer.
    div_run = run1.member_responses[0]
    comms_run = div_run.member_responses[0]
    agent_ids = {getattr(m, "agent_id", None) for m in comms_run.member_responses}
    assert agent_ids == {"reporter", "emailer"}

    # Storage scrubbed at every level: no completed member response anywhere.
    def walk(runs):
        stack = list(runs)
        while stack:
            r = stack.pop()
            yield r
            stack.extend(getattr(r, "member_responses", None) or [])

    for r in _reload_runs(db_file, session_id):
        for m in walk(getattr(r, "member_responses", None) or []):
            assert getattr(m, "is_paused", False), f"completed member response persisted: {m.run_id}"
