"""
Unit tests for paused member run persistence in team routing helpers.

Regression test for: https://github.com/agno-agi/agno/issues/8925

When a member pauses during team.continue_run() routing, its RunOutput must be
persisted to session.runs so subsequent continue_run calls can find it after
session reload.
"""

import json
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import RunNotContinuableError
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
        # Every model turn reports usage so runs carry realistic metrics.
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
# streaming resume, and the deep scrub.
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


# ---------------------------------------------------------------------------
# Same sub-team paused twice in one turn, and live-tree integrity.
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


# ---------------------------------------------------------------------------
# Chained pause on the streaming continue path: after the first confirmation
# is delivered, the member pauses on a second gated tool. The streaming
# continue must yield the final paused TeamRunOutput and persist the
# re-paused state, exactly like the other three routing variants.
# ---------------------------------------------------------------------------


def _build_nested_chained_team(db: SqliteDb, phase: str) -> Team:
    """phase: 'pause' -> emailer calls send_email; 'chain' -> emailer chains
    send_sms after the confirmed send_email runs; 'finish' -> emailer answers."""
    emailer_script = {
        "pause": [("tool", "send_email", {"to": "a@example.com"}, "tc-send")],
        "chain": [("tool", "send_sms", {"to": "c@x.com"}, "tc-sms-chain"), ("content", "Both sent.")],
        "finish": [("content", "Both sent.")],
    }[phase]
    emailer = Agent(
        name="Emailer",
        id="emailer",
        model=_ScriptedModel("m-emailer", emailer_script),
        tools=[send_email, send_sms],
        db=db,
        telemetry=False,
    )
    inner = Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-inner",
            [("content", "Inner done.")]
            if phase != "pause"
            else [
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-inner-deleg"),
                ("content", "Inner done."),
            ],
        ),
        members=[emailer],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Org Team",
        id="org-team",
        model=_ScriptedModel(
            "m-outer",
            [("content", "All done.")]
            if phase != "pause"
            else [
                (
                    "tool",
                    "delegate_task_to_member",
                    {"member_id": "comms-team", "task": "handle email"},
                    "tc-outer-deleg",
                ),
                ("content", "All done."),
            ],
        ),
        members=[inner],
        db=db,
        telemetry=False,
    )


def _assert_chained_pause_surfaced(final, db_file: str, session_id: str) -> None:
    assert final is not None, "streaming continue must yield the final TeamRunOutput on a chained pause"
    assert final.is_paused
    unresolved = [r for r in (final.requirements or []) if not r.is_resolved()]
    assert [r.tool_execution.tool_name for r in unresolved if r.tool_execution] == ["send_sms"]
    assert _EXECUTED == ["a@example.com"], "the chained send_sms must not run before its confirmation"

    # The re-paused state is persisted: a fresh reader sees the outer run
    # paused with the unresolved chained requirement.
    team_runs = [r for r in _reload_runs(db_file, session_id) if getattr(r, "team_id", None) == "org-team"]
    assert team_runs[0].is_paused
    stored_unresolved = [r for r in (team_runs[0].requirements or []) if not r.is_resolved()]
    assert [r.tool_execution.tool_name for r in stored_unresolved if r.tool_execution] == ["send_sms"]


def test_nested_chained_pause_streaming_repauses_and_resumes(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "chained_stream.db")
    session_id = "s-chained-stream"

    outer1 = _build_nested_chained_team(SqliteDb(db_file=db_file), phase="pause")
    run1 = outer1.run("Email then sms", session_id=session_id)
    assert run1.is_paused

    outer2 = _build_nested_chained_team(SqliteDb(db_file=db_file), phase="chain")
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
    _assert_chained_pause_surfaced(final, db_file, session_id)

    outer3 = _build_nested_chained_team(SqliteDb(db_file=db_file), phase="finish")
    run3 = None
    for event in outer3.continue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements([r for r in final.requirements or [] if not r.is_resolved()]),
        stream=True,
        yield_run_output=True,
    ):
        if isinstance(event, TeamRunOutput):
            run3 = event
    assert run3 is not None
    assert run3.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com", "sms:c@x.com"]


@pytest.mark.asyncio
async def test_nested_chained_pause_streaming_repauses_and_resumes_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "chained_stream_async.db")
    session_id = "s-chained-stream-async"

    outer1 = _build_nested_chained_team(SqliteDb(db_file=db_file), phase="pause")
    run1 = await outer1.arun("Email then sms", session_id=session_id)
    assert run1.is_paused

    outer2 = _build_nested_chained_team(SqliteDb(db_file=db_file), phase="chain")
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
    _assert_chained_pause_surfaced(final, db_file, session_id)

    outer3 = _build_nested_chained_team(SqliteDb(db_file=db_file), phase="finish")
    run3 = None
    async for event in outer3.acontinue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements([r for r in final.requirements or [] if not r.is_resolved()]),
        stream=True,
        yield_run_output=True,
    ):
        if isinstance(event, TeamRunOutput):
            run3 = event
    assert run3 is not None
    assert run3.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com", "sms:c@x.com"]


# ---------------------------------------------------------------------------
# One member paused in TWO delegations of the same turn: the requirements
# share member_agent_id but belong to distinct member runs, so grouping by
# (member id, member run id) must keep them separate — one continue per
# paused run, both confirmations execute.
# ---------------------------------------------------------------------------

_SHARED_CURSORS: Dict[str, int] = {}


class _SharedCursorModel(_ScriptedModel):
    """Script cursor kept in module scope by model id, so the copies a leader
    makes when it delegates to the same member twice in one turn consume
    consecutive script turns instead of each starting at turn one."""

    def _next(self):
        self._i = _SHARED_CURSORS.get(self.id, 0)
        response = super()._next()
        _SHARED_CURSORS[self.id] = self._i
        return response


def _build_same_member_twice(db: SqliteDb, resuming: bool) -> Team:
    _SHARED_CURSORS.pop("m-emailer-twice", None)
    emailer = Agent(
        name="Emailer",
        id="emailer",
        model=_SharedCursorModel(
            "m-emailer-twice",
            [("content", "Email sent."), ("content", "Email sent.")]
            if resuming
            else [
                ("tool", "send_email", {"to": "a@x.com"}, "tc-e1"),
                ("tool", "send_email", {"to": "b@x.com"}, "tc-e2"),
            ],
        ),
        tools=[send_email],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-leader-twice",
            [("content", "All done.")]
            if resuming
            else [
                (
                    "tools",
                    [
                        ("delegate_task_to_member", {"member_id": "emailer", "task": "task A"}, "tc-da"),
                        ("delegate_task_to_member", {"member_id": "emailer", "task": "task B"}, "tc-db"),
                    ],
                ),
                ("content", "All done."),
            ],
        ),
        members=[emailer],
        db=db,
        telemetry=False,
    )


def test_same_member_paused_twice_in_one_turn_both_execute(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "same_member_twice.db")
    session_id = "s-same-member-twice"

    team1 = _build_same_member_twice(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Do task A and task B", session_id=session_id)
    assert run1.is_paused
    assert len(run1.requirements or []) == 2
    assert {r.member_agent_id for r in run1.requirements or []} == {"emailer"}
    assert len({r.member_run_id for r in run1.requirements or []}) == 2, "two distinct paused member runs"

    team2 = _build_same_member_twice(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert sorted(_EXECUTED) == ["a@x.com", "b@x.com"], "both confirmed tools must execute"


@pytest.mark.asyncio
async def test_same_member_paused_twice_in_one_turn_both_execute_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "same_member_twice_async.db")
    session_id = "s-same-member-twice-async"

    team1 = _build_same_member_twice(SqliteDb(db_file=db_file), resuming=False)
    run1 = await team1.arun("Do task A and task B", session_id=session_id)
    assert run1.is_paused
    assert len({r.member_run_id for r in run1.requirements or []}) == 2

    team2 = _build_same_member_twice(SqliteDb(db_file=db_file), resuming=True)
    run2 = await team2.acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert sorted(_EXECUTED) == ["a@x.com", "b@x.com"]


# ---------------------------------------------------------------------------
# A requirement that cannot be routed to any current member fails loudly.
# The run stays paused and resumable; the approved tool is not silently
# skipped and the run does not report completed.
# ---------------------------------------------------------------------------


def _build_renamed_member_team(db: SqliteDb) -> Team:
    renamed = Agent(
        name="Emailer",
        id="emailer2",
        model=_ScriptedModel("m-emailer2", [("content", "Email sent.")]),
        tools=[send_email],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel("m-leader-renamed", [("content", "All done.")]),
        members=[renamed],
        db=db,
        telemetry=False,
    )


def test_unroutable_requirement_raises_and_run_stays_paused(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "unroutable.db")
    session_id = "s-unroutable"

    team1 = _build_flat_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    # The member id changed between pause and continue (e.g. a redeploy).
    team2 = _build_renamed_member_team(SqliteDb(db_file=db_file))
    with pytest.raises(RunNotContinuableError, match="emailer"):
        team2.continue_run(
            run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
        )

    assert _EXECUTED == [], "no confirmed tool may execute when routing fails"
    team_runs = [r for r in _reload_runs(db_file, session_id) if isinstance(r, TeamRunOutput)]
    assert team_runs[0].is_paused, "the stored run must stay paused and resumable"
    assert any(not r.is_resolved() for r in (team_runs[0].requirements or []))


@pytest.mark.asyncio
async def test_unroutable_requirement_raises_and_run_stays_paused_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "unroutable_async.db")
    session_id = "s-unroutable-async"

    team1 = _build_flat_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = await team1.arun("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    team2 = _build_renamed_member_team(SqliteDb(db_file=db_file))
    with pytest.raises(RunNotContinuableError, match="emailer"):
        await team2.acontinue_run(
            run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
        )

    assert _EXECUTED == [], "no confirmed tool may execute when routing fails"
    team_runs = [r for r in _reload_runs(db_file, session_id) if isinstance(r, TeamRunOutput)]
    assert team_runs[0].is_paused, "the stored run must stay paused and resumable"
    assert any(not r.is_resolved() for r in (team_runs[0].requirements or []))


# ---------------------------------------------------------------------------
# A sub-team's OWN gated tool: _propagate_member_pause stamps the sub-team's
# id on the lifted requirement so the parent can route it down; the sub-team
# must reclaim it as its own team-level requirement, both alone and mixed
# with a deep member requirement in the same turn.
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def publish(item: str) -> str:
    _EXECUTED.append(f"pub:{item}")
    return f"Published {item}"


def _build_subteam_own_tool(db: SqliteDb, resuming: bool, mixed: bool) -> Team:
    inner_pause_turn = (
        (
            "tools",
            [
                ("delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-inner-deleg"),
                ("publish", {"item": "release"}, "tc-pub"),
            ],
        )
        if mixed
        else ("tool", "publish", {"item": "release"}, "tc-pub")
    )
    inner = Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-inner", [("content", "Inner done.")] if resuming else [inner_pause_turn, ("content", "Inner done.")]
        ),
        tools=[publish],
        members=[_emailer_agent(db, resuming)],
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
                ("tool", "delegate_task_to_member", {"member_id": "comms-team", "task": "handle comms"}, "tc-outer"),
                ("content", "All done."),
            ],
        ),
        members=[inner],
        db=db,
        telemetry=False,
    )


@pytest.mark.parametrize("mixed", [False, True], ids=["alone", "with_member_requirement"])
def test_subteam_own_gated_tool_executes_on_continue(tmp_path, mixed):
    _EXECUTED.clear()
    db_file = str(tmp_path / "own_tool.db")
    session_id = "s-own-tool"

    outer1 = _build_subteam_own_tool(SqliteDb(db_file=db_file), resuming=False, mixed=mixed)
    run1 = outer1.run("Publish the release", session_id=session_id)
    assert run1.is_paused
    expected = ["publish", "send_email"] if mixed else ["publish"]
    assert sorted(r.tool_execution.tool_name for r in run1.requirements or []) == sorted(expected)

    outer2 = _build_subteam_own_tool(SqliteDb(db_file=db_file), resuming=True, mixed=mixed)
    run2 = outer2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert sorted(_EXECUTED) == (["a@example.com", "pub:release"] if mixed else ["pub:release"])


@pytest.mark.asyncio
@pytest.mark.parametrize("mixed", [False, True], ids=["alone", "with_member_requirement"])
async def test_subteam_own_gated_tool_executes_on_continue_async(tmp_path, mixed):
    _EXECUTED.clear()
    db_file = str(tmp_path / "own_tool_async.db")
    session_id = "s-own-tool-async"

    outer1 = _build_subteam_own_tool(SqliteDb(db_file=db_file), resuming=False, mixed=mixed)
    run1 = await outer1.arun("Publish the release", session_id=session_id)
    assert run1.is_paused

    outer2 = _build_subteam_own_tool(SqliteDb(db_file=db_file), resuming=True, mixed=mixed)
    run2 = await outer2.acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert sorted(_EXECUTED) == (["a@example.com", "pub:release"] if mixed else ["pub:release"])


# ---------------------------------------------------------------------------
# A member may share the team's id — or its url-safe name, which get_member_id
# falls back to. The member stamp on a requirement is then ambiguous, and
# continue dispatch must still route the member's requirement to the member:
# reclaiming it as team-level silently drops the confirmed tool.
# ---------------------------------------------------------------------------


def _build_id_collision_team(db: SqliteDb, resuming: bool) -> Team:
    return Team(
        name="Emailer Team",
        id="emailer",
        model=_ScriptedModel(
            "m-leader",
            [("content", "All done.")]
            if resuming
            else [
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-deleg"),
                ("content", "All done."),
            ],
        ),
        members=[_emailer_agent(db, resuming)],
        db=db,
        telemetry=False,
    )


def _build_deep_id_collision_team(db: SqliteDb, resuming: bool) -> Team:
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
    return Team(
        name="Org Team",
        id="emailer",
        model=_ScriptedModel(
            "m-outer",
            [("content", "All done.")]
            if resuming
            else [
                (
                    "tool",
                    "delegate_task_to_member",
                    {"member_id": "comms-team", "task": "handle email"},
                    "tc-outer-deleg",
                ),
                ("content", "All done."),
            ],
        ),
        members=[inner],
        db=db,
        telemetry=False,
    )


def _build_name_collision_team(db: SqliteDb, resuming: bool) -> Team:
    member = Agent(
        name="Emailer",
        model=_ScriptedModel(
            "m-emailer",
            [("content", "Email sent.")]
            if resuming
            else [("tool", "send_email", {"to": "a@example.com"}, "tc-send"), ("content", "Email sent.")],
        ),
        tools=[send_email],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Emailer",
        model=_ScriptedModel(
            "m-leader",
            [("content", "All done.")]
            if resuming
            else [
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-deleg"),
                ("content", "All done."),
            ],
        ),
        members=[member],
        db=db,
        telemetry=False,
    )


def test_member_sharing_team_id_resumes_fresh_process(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "id_collision.db")
    session_id = "s-id-collision"

    team1 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []

    team2 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


@pytest.mark.asyncio
async def test_member_sharing_team_id_resumes_fresh_process_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "id_collision_async.db")
    session_id = "s-id-collision-async"

    team1 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = await team1.arun("Email a@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []

    team2 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = await team2.acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


def test_member_sharing_team_id_resumes_fresh_process_streaming(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "id_collision_stream.db")
    session_id = "s-id-collision-stream"

    team1 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    team2 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=True)
    final = None
    for event in team2.continue_run(
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


def test_deep_member_sharing_top_team_id_resumes_fresh_process(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "deep_id_collision.db")
    session_id = "s-deep-id-collision"

    outer1 = _build_deep_id_collision_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = outer1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []

    outer2 = _build_deep_id_collision_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = outer2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


def test_member_sharing_team_name_resumes_fresh_process(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "name_collision.db")
    session_id = "s-name-collision"

    team1 = _build_name_collision_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []

    team2 = _build_name_collision_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


# ---------------------------------------------------------------------------
# to_dict() strips None values, so a wire payload may omit member provenance
# (member_run_id and friends). The dispatch backfill restores it from the
# stored session requirements; routing and the own-requirement reclaim must
# then behave exactly as with a complete payload.
# ---------------------------------------------------------------------------


def _wire_requirements_stripped(requirements, *fields: str) -> List[RunRequirement]:
    """Wire round-trip like _wire_requirements, but with the given payload keys
    deleted, the way a client that only echoes HITL-relevant fields sends them."""
    confirmed = []
    for data in [r.to_dict() for r in requirements or []]:
        for field in fields:
            data.pop(field, None)
        req = RunRequirement.from_dict(data)
        req.confirm()
        confirmed.append(req)
    return confirmed


def test_stripped_member_run_id_collision_still_routes(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "stripped_collision.db")
    session_id = "s-stripped-collision"

    team1 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    team2 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements_stripped(run1.requirements, "member_run_id"),
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


def test_stripped_member_run_id_ordinary_team_routes(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "stripped_flat.db")
    session_id = "s-stripped-flat"

    team1 = _build_flat_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements_stripped(run1.requirements, "member_run_id"),
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


def test_stripped_member_run_id_subteam_own_tool_still_reclaims(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "stripped_own_tool.db")
    session_id = "s-stripped-own-tool"

    outer1 = _build_subteam_own_tool(SqliteDb(db_file=db_file), resuming=False, mixed=False)
    run1 = outer1.run("Publish the release", session_id=session_id)
    assert run1.is_paused

    outer2 = _build_subteam_own_tool(SqliteDb(db_file=db_file), resuming=True, mixed=False)
    run2 = outer2.continue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements_stripped(run1.requirements, "member_run_id"),
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["pub:release"]


def test_unrecoverable_provenance_collision_fails_loudly(tmp_path):
    """A collision payload whose provenance cannot be restored (no matching
    stored requirement) must raise, never complete with the tool skipped."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "unrecoverable.db")
    session_id = "s-unrecoverable"

    team1 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    mangled = []
    for data in [r.to_dict() for r in run1.requirements or []]:
        data.pop("member_run_id", None)
        data["id"] = "req-unknown"
        data["tool_execution"]["tool_call_id"] = "tc-unknown"
        req = RunRequirement.from_dict(data)
        req.confirm()
        mangled.append(req)

    team2 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=True)
    with pytest.raises(ValueError):
        team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=mangled)
    assert _EXECUTED == []


def _build_same_member_twice_same_tool_call_id(db: SqliteDb, resuming: bool) -> Team:
    _SHARED_CURSORS.pop("m-emailer-shared-tcid", None)
    emailer = Agent(
        name="Emailer",
        id="emailer",
        model=_SharedCursorModel(
            "m-emailer-shared-tcid",
            [("content", "Email sent."), ("content", "Email sent.")]
            if resuming
            else [
                ("tool", "send_email", {"to": "a@x.com"}, "tc-shared"),
                ("tool", "send_email", {"to": "b@x.com"}, "tc-shared"),
            ],
        ),
        tools=[send_email],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-leader-shared-tcid",
            [("content", "All done.")]
            if resuming
            else [
                (
                    "tools",
                    [
                        ("delegate_task_to_member", {"member_id": "emailer", "task": "task A"}, "tc-da"),
                        ("delegate_task_to_member", {"member_id": "emailer", "task": "task B"}, "tc-db"),
                    ],
                ),
                ("content", "All done."),
            ],
        ),
        members=[emailer],
        db=db,
        telemetry=False,
    )


def test_stripped_payload_same_tool_call_id_both_runs_execute(tmp_path):
    """Two paused runs of one member can share a tool_call_id, so provenance
    restore must match by requirement id — a tool_call_id match hands both
    requirements the same member_run_id and strands one of the runs."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "stripped_same_tcid.db")
    session_id = "s-stripped-same-tcid"

    team1 = _build_same_member_twice_same_tool_call_id(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email both", session_id=session_id)
    assert run1.is_paused
    assert len(run1.requirements or []) == 2
    assert len({r.member_run_id for r in run1.requirements}) == 2

    team2 = _build_same_member_twice_same_tool_call_id(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements_stripped(run1.requirements, "member_run_id"),
    )
    assert run2.status == RunStatus.completed
    assert sorted(_EXECUTED) == ["a@x.com", "b@x.com"]


# ---------------------------------------------------------------------------
# Sibling sub-teams may contain members with the same leaf id. The leaf-id
# route picks the first sibling in member order; the continue must dispatch
# to the sibling that owns the paused run, and each sibling's own tool
# implementation must execute with its own arguments.
# ---------------------------------------------------------------------------

_LEFT_EXECUTED: List[str] = []
_RIGHT_EXECUTED: List[str] = []


@tool(name="send_email", requires_confirmation=True)
def left_send_email(to: str) -> str:
    _LEFT_EXECUTED.append(to)
    return f"LEFT sent to {to}"


@tool(name="send_email", requires_confirmation=True)
def right_send_email(to: str) -> str:
    _RIGHT_EXECUTED.append(to)
    return f"RIGHT sent to {to}"


def _build_sibling_dup_leaf_teams(
    db: SqliteDb,
    resuming: bool,
    delegate_to_both: bool,
    omit_right: bool = False,
    duplicate_right: bool = False,
) -> Team:
    def make_subteam(side: str, send_tool, to: str, team_id: Optional[str] = None) -> Team:
        agent_script = (
            [("content", "Email sent.")]
            if resuming
            else [("tool", "send_email", {"to": to}, f"tc-send-{side}"), ("content", "Email sent.")]
        )
        sub_script = (
            [("content", f"{side} done.")]
            if resuming
            else [
                ("tool", "delegate_task_to_member", {"member_id": "dup", "task": "send it"}, f"tc-deleg-{side}"),
                ("content", f"{side} done."),
            ]
        )
        member = Agent(
            name="Dup",
            id="dup",
            model=_ScriptedModel(f"m-agent-{side}", agent_script),
            tools=[send_tool],
            db=db,
            telemetry=False,
        )
        return Team(
            name=f"{side} Team",
            id=team_id or f"{side}-team",
            model=_ScriptedModel(f"m-{side}", sub_script),
            members=[member],
            db=db,
            telemetry=False,
        )

    if delegate_to_both:
        leader_turn = (
            "tools",
            [
                ("delegate_task_to_member", {"member_id": "left-team", "task": "send left"}, "tc-outer-left"),
                ("delegate_task_to_member", {"member_id": "right-team", "task": "send right"}, "tc-outer-right"),
            ],
        )
    else:
        leader_turn = ("tool", "delegate_task_to_member", {"member_id": "right-team", "task": "send right"}, "tc-outer")
    members = [make_subteam("left", left_send_email, "left@example.com")]
    if not omit_right:
        members.append(make_subteam("right", right_send_email, "right@example.com"))
    if duplicate_right:
        members.append(make_subteam("right2", right_send_email, "right2@example.com", team_id="right-team"))
    return Team(
        name="Org Team",
        id="org-team",
        model=_ScriptedModel(
            "m-outer", [("content", "All done.")] if resuming else [leader_turn, ("content", "All done.")]
        ),
        members=members,
        db=db,
        telemetry=False,
    )


def test_duplicate_leaf_id_across_siblings_routes_to_owning_subteam(tmp_path):
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "sibling_dup.db")
    session_id = "s-sibling-dup"

    outer1 = _build_sibling_dup_leaf_teams(SqliteDb(db_file=db_file), resuming=False, delegate_to_both=False)
    run1 = outer1.run("Email right", session_id=session_id)
    assert run1.is_paused
    assert _LEFT_EXECUTED == [] and _RIGHT_EXECUTED == []

    outer2 = _build_sibling_dup_leaf_teams(SqliteDb(db_file=db_file), resuming=True, delegate_to_both=False)
    run2 = outer2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _RIGHT_EXECUTED == ["right@example.com"]
    assert _LEFT_EXECUTED == []


@pytest.mark.asyncio
async def test_duplicate_leaf_id_across_siblings_routes_to_owning_subteam_async(tmp_path):
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "sibling_dup_async.db")
    session_id = "s-sibling-dup-async"

    outer1 = _build_sibling_dup_leaf_teams(SqliteDb(db_file=db_file), resuming=False, delegate_to_both=False)
    run1 = await outer1.arun("Email right", session_id=session_id)
    assert run1.is_paused

    outer2 = _build_sibling_dup_leaf_teams(SqliteDb(db_file=db_file), resuming=True, delegate_to_both=False)
    run2 = await outer2.acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _RIGHT_EXECUTED == ["right@example.com"]
    assert _LEFT_EXECUTED == []


def test_duplicate_leaf_id_both_siblings_paused_each_executes_own(tmp_path):
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "sibling_dup_both.db")
    session_id = "s-sibling-dup-both"

    outer1 = _build_sibling_dup_leaf_teams(SqliteDb(db_file=db_file), resuming=False, delegate_to_both=True)
    run1 = outer1.run("Email both sides", session_id=session_id)
    assert run1.is_paused
    assert len(run1.requirements or []) == 2

    outer2 = _build_sibling_dup_leaf_teams(SqliteDb(db_file=db_file), resuming=True, delegate_to_both=True)
    run2 = outer2.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _LEFT_EXECUTED == ["left@example.com"]
    assert _RIGHT_EXECUTED == ["right@example.com"]


# ---------------------------------------------------------------------------
# Requirements arrive from the wire, so their routing fields are unverified
# client input. The stored session requirement is the authority: on a unique
# match its provenance overwrites the payload's; an ambiguous payload (two
# stored requirements share a tool_call_id, no requirement ids to tell them
# apart) is refused with the run left paused, never guessed.
# ---------------------------------------------------------------------------


def test_ambiguous_stripped_payload_refuses_then_recovers(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "ambiguous_payload.db")
    session_id = "s-ambiguous-payload"

    team1 = _build_same_member_twice_same_tool_call_id(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email both", session_id=session_id)
    assert run1.is_paused

    team2 = _build_same_member_twice_same_tool_call_id(SqliteDb(db_file=db_file), resuming=True)
    with pytest.raises(RunNotContinuableError):
        team2.continue_run(
            run_id=run1.run_id,
            session_id=session_id,
            requirements=_wire_requirements_stripped(run1.requirements, "id", "member_run_id"),
        )
    assert _EXECUTED == []
    stored = [r for r in _reload_runs(db_file, session_id) if getattr(r, "run_id", None) == run1.run_id]
    assert stored and stored[0].status == RunStatus.paused

    # With the requirement ids included the same minimal payload resumes.
    team3 = _build_same_member_twice_same_tool_call_id(SqliteDb(db_file=db_file), resuming=True)
    run3 = team3.continue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements_stripped(run1.requirements, "member_run_id"),
    )
    assert run3.status == RunStatus.completed
    assert sorted(_EXECUTED) == ["a@x.com", "b@x.com"]


def test_lied_member_run_id_is_overwritten_by_stored(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "lied_run_id.db")
    session_id = "s-lied-run-id"

    team1 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    lied = []
    for data in [r.to_dict() for r in run1.requirements or []]:
        data["member_run_id"] = run1.run_id
        req = RunRequirement.from_dict(data)
        req.confirm()
        lied.append(req)

    team2 = _build_id_collision_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=lied)
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


def test_lied_member_agent_id_is_overwritten_by_stored(tmp_path):
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "lied_agent_id.db")
    session_id = "s-lied-agent-id"

    def build(resuming: bool) -> Team:
        def make_agent(side: str, send_tool, to: str) -> Agent:
            script = (
                [("content", "Email sent.")]
                if resuming
                else [("tool", "send_email", {"to": to}, f"tc-send-{side}"), ("content", "Email sent.")]
            )
            return Agent(
                name=f"{side} Agent",
                id=f"agent-{side}",
                model=_ScriptedModel(f"m-lied-{side}", script),
                tools=[send_tool],
                db=db,
                telemetry=False,
            )

        db = SqliteDb(db_file=db_file)
        return Team(
            name="Comms Team",
            id="comms-team",
            model=_ScriptedModel(
                "m-lied-leader",
                [("content", "All done.")]
                if resuming
                else [
                    ("tool", "delegate_task_to_member", {"member_id": "agent-right", "task": "send it"}, "tc-deleg"),
                    ("content", "All done."),
                ],
            ),
            members=[
                make_agent("left", left_send_email, "left@example.com"),
                make_agent("right", right_send_email, "right@example.com"),
            ],
            db=db,
            telemetry=False,
        )

    team1 = build(resuming=False)
    run1 = team1.run("Email right", session_id=session_id)
    assert run1.is_paused

    lied = []
    for data in [r.to_dict() for r in run1.requirements or []]:
        data["member_agent_id"] = "agent-left"
        data["member_agent_name"] = "left Agent"
        req = RunRequirement.from_dict(data)
        req.confirm()
        lied.append(req)

    team2 = build(resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=lied)
    assert run2.status == RunStatus.completed
    assert _RIGHT_EXECUTED == ["right@example.com"]
    assert _LEFT_EXECUTED == []


# ---------------------------------------------------------------------------
# The owner of the resolved paused run must resolve to exactly one direct
# member of the continuing team. A removed owner or several direct members
# sharing the owner's id refuse the continue and leave the run paused.
# ---------------------------------------------------------------------------


def test_removed_owner_refuses_and_recovers(tmp_path):
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "removed_owner.db")
    session_id = "s-removed-owner"

    outer1 = _build_sibling_dup_leaf_teams(SqliteDb(db_file=db_file), resuming=False, delegate_to_both=False)
    run1 = outer1.run("Email right", session_id=session_id)
    assert run1.is_paused

    without_owner = _build_sibling_dup_leaf_teams(
        SqliteDb(db_file=db_file), resuming=True, delegate_to_both=False, omit_right=True
    )
    with pytest.raises(RunNotContinuableError):
        without_owner.continue_run(
            run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
        )
    assert _LEFT_EXECUTED == [] and _RIGHT_EXECUTED == []
    stored = [r for r in _reload_runs(db_file, session_id) if getattr(r, "run_id", None) == run1.run_id]
    assert stored and stored[0].status == RunStatus.paused

    # With the owner back in the team the same continue succeeds.
    restored = _build_sibling_dup_leaf_teams(SqliteDb(db_file=db_file), resuming=True, delegate_to_both=False)
    run3 = restored.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run3.status == RunStatus.completed
    assert _RIGHT_EXECUTED == ["right@example.com"]
    assert _LEFT_EXECUTED == []


def test_ambiguous_owner_id_refuses(tmp_path):
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "ambiguous_owner.db")
    session_id = "s-ambiguous-owner"

    outer1 = _build_sibling_dup_leaf_teams(
        SqliteDb(db_file=db_file), resuming=False, delegate_to_both=False, duplicate_right=True
    )
    run1 = outer1.run("Email right", session_id=session_id)
    assert run1.is_paused

    outer2 = _build_sibling_dup_leaf_teams(
        SqliteDb(db_file=db_file), resuming=True, delegate_to_both=False, duplicate_right=True
    )
    with pytest.raises(RunNotContinuableError):
        outer2.continue_run(
            run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
        )
    assert _LEFT_EXECUTED == [] and _RIGHT_EXECUTED == []
    stored = [r for r in _reload_runs(db_file, session_id) if getattr(r, "run_id", None) == run1.run_id]
    assert stored and stored[0].status == RunStatus.paused


# ---------------------------------------------------------------------------
# The payload's requirements bind one-to-one to the stored requirements, and
# the STORED requirement is what routing sees afterwards — only the client's
# decision state crosses over. Trusting the wire copy lets a swapped or
# duplicated requirement id execute one member's approved arguments through
# another member's tool, and a forged entry skip the stored approval.
# ---------------------------------------------------------------------------


def _build_two_agents_shared_tool_call_id(db: SqliteDb, resuming: bool) -> Team:
    def make_agent(side: str, send_tool, to: str) -> Agent:
        script = (
            [("content", "Email sent.")]
            if resuming
            else [("tool", "send_email", {"to": to}, "tc-shared"), ("content", "Email sent.")]
        )
        return Agent(
            name=f"{side} Agent",
            id=f"{side}-agent",
            model=_ScriptedModel(f"m-shared-{side}", script),
            tools=[send_tool],
            db=db,
            telemetry=False,
        )

    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-shared-leader",
            [("content", "All done.")]
            if resuming
            else [
                (
                    "tools",
                    [
                        ("delegate_task_to_member", {"member_id": "left-agent", "task": "send left"}, "tc-dl"),
                        ("delegate_task_to_member", {"member_id": "right-agent", "task": "send right"}, "tc-dr"),
                    ],
                ),
                ("content", "All done."),
            ],
        ),
        members=[
            make_agent("left", left_send_email, "left@example.com"),
            make_agent("right", right_send_email, "right@example.com"),
        ],
        db=db,
        telemetry=False,
    )


def test_swapped_requirement_ids_execute_each_members_own_arguments(tmp_path):
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "swapped_ids.db")
    session_id = "s-swapped-ids"

    team1 = _build_two_agents_shared_tool_call_id(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email both", session_id=session_id)
    assert run1.is_paused
    assert len(run1.requirements or []) == 2
    assert {r.tool_execution.tool_call_id for r in run1.requirements} == {"tc-shared"}

    payload_dicts = [r.to_dict() for r in run1.requirements]
    payload_dicts[0]["id"], payload_dicts[1]["id"] = payload_dicts[1]["id"], payload_dicts[0]["id"]
    swapped = []
    for data in payload_dicts:
        req = RunRequirement.from_dict(data)
        req.confirm()
        swapped.append(req)

    team2 = _build_two_agents_shared_tool_call_id(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=swapped)
    assert run2.status == RunStatus.completed
    assert _LEFT_EXECUTED == ["left@example.com"]
    assert _RIGHT_EXECUTED == ["right@example.com"]


def test_duplicate_requirement_id_payload_refuses(tmp_path):
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "dup_req_id.db")
    session_id = "s-dup-req-id"

    team1 = _build_two_agents_shared_tool_call_id(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email both", session_id=session_id)
    assert run1.is_paused

    payload_dicts = [r.to_dict() for r in run1.requirements]
    payload_dicts[1]["id"] = payload_dicts[0]["id"]
    duplicated = []
    for data in payload_dicts:
        req = RunRequirement.from_dict(data)
        req.confirm()
        duplicated.append(req)

    team2 = _build_two_agents_shared_tool_call_id(SqliteDb(db_file=db_file), resuming=True)
    with pytest.raises(RunNotContinuableError):
        team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=duplicated)
    assert _LEFT_EXECUTED == [] and _RIGHT_EXECUTED == []
    stored = [r for r in _reload_runs(db_file, session_id) if getattr(r, "run_id", None) == run1.run_id]
    assert stored and stored[0].status == RunStatus.paused


def test_forged_unmatched_requirement_refuses(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "forged_req.db")
    session_id = "s-forged-req"

    team1 = _build_flat_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    forged_data = run1.requirements[0].to_dict()
    forged_data["id"] = "req-forged"
    forged_data["tool_execution"]["tool_call_id"] = "tc-forged"
    forged_data["tool_execution"]["tool_args"] = {"to": "attacker@evil.com"}
    forged = RunRequirement.from_dict(forged_data)
    forged.confirm()

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    with pytest.raises(RunNotContinuableError):
        team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=[forged])
    assert _EXECUTED == []
    stored = [r for r in _reload_runs(db_file, session_id) if getattr(r, "run_id", None) == run1.run_id]
    assert stored and stored[0].status == RunStatus.paused


def test_forged_result_does_not_suppress_confirmed_execution(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "forged_result.db")
    session_id = "s-forged-result"

    team1 = _build_flat_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    data = run1.requirements[0].to_dict()
    data["tool_execution"]["result"] = "forged: already sent"
    req = RunRequirement.from_dict(data)
    req.confirm()

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=[req])
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


def test_refusal_leaves_live_run_object_retryable(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "live_retry.db")
    session_id = "s-live-retry"

    team1 = _build_same_member_twice_same_tool_call_id(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email both", session_id=session_id)
    assert run1.is_paused
    original_req_ids = sorted(r.id for r in run1.requirements or [])

    team2 = _build_same_member_twice_same_tool_call_id(SqliteDb(db_file=db_file), resuming=True)
    with pytest.raises(RunNotContinuableError):
        team2.continue_run(
            run_response=run1,
            session_id=session_id,
            requirements=_wire_requirements_stripped(run1.requirements, "id", "member_run_id"),
        )
    assert _EXECUTED == []
    # The live object still carries the stored requirements the refusal asks for.
    assert sorted(r.id for r in run1.requirements or []) == original_req_ids
    assert all(r.member_run_id is not None for r in run1.requirements)

    run3 = team2.continue_run(
        run_response=run1,
        session_id=session_id,
        requirements=_wire_requirements(run1.requirements),
    )
    assert run3.status == RunStatus.completed
    assert sorted(_EXECUTED) == ["a@x.com", "b@x.com"]


def test_duplicate_direct_agent_ids_refuse_continue(tmp_path):
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "dup_agent_ids.db")
    session_id = "s-dup-agent-ids"

    def build(resuming: bool) -> Team:
        db = SqliteDb(db_file=db_file)
        left = Agent(
            name="left Agent",
            id="dup",
            model=_ScriptedModel(
                "m-dupa-left",
                [("content", "Email sent.")]
                if resuming
                else [("tool", "send_email", {"to": "left@example.com"}, "tc-send-l"), ("content", "Email sent.")],
            ),
            tools=[left_send_email],
            db=db,
            telemetry=False,
        )
        right = Agent(
            name="right Agent",
            id="dup",
            model=_ScriptedModel("m-dupa-right", [("content", "Never runs.")]),
            tools=[right_send_email],
            db=db,
            telemetry=False,
        )
        return Team(
            name="Comms Team",
            id="comms-team",
            model=_ScriptedModel(
                "m-dupa-leader",
                [("content", "All done.")]
                if resuming
                else [
                    ("tool", "delegate_task_to_member", {"member_id": "dup", "task": "send it"}, "tc-deleg"),
                    ("content", "All done."),
                ],
            ),
            members=[left, right],
            db=db,
            telemetry=False,
        )

    team1 = build(resuming=False)
    run1 = team1.run("Email left", session_id=session_id)
    assert run1.is_paused

    team2 = build(resuming=True)
    with pytest.raises(RunNotContinuableError):
        team2.continue_run(
            run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
        )
    assert _LEFT_EXECUTED == [] and _RIGHT_EXECUTED == []
    stored = [r for r in _reload_runs(db_file, session_id) if getattr(r, "run_id", None) == run1.run_id]
    assert stored and stored[0].status == RunStatus.paused


# ---------------------------------------------------------------------------
# When routing raises, the caller's in-memory run object must keep ALL its
# requirements (the dispatch temporarily strips team-level ones for routing),
# so a retry after fixing the team does not lose an approved tool.
# ---------------------------------------------------------------------------


def _build_leader_tool_and_member(db: SqliteDb, member_id: str) -> Team:
    member = Agent(
        name="Emailer",
        id=member_id,
        model=_ScriptedModel("m-emailer", [("tool", "send_email", {"to": "a@x.com"}, "tc-send"), ("content", "Sent.")]),
        tools=[send_email],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-leader",
            [
                (
                    "tools",
                    [
                        ("delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-deleg"),
                        ("publish", {"item": "release"}, "tc-pub"),
                    ],
                ),
                ("content", "All done."),
            ],
        ),
        tools=[publish],
        members=[member],
        db=db,
        telemetry=False,
    )


def test_unroutable_raise_preserves_caller_requirements(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "preserve.db")
    session_id = "s-preserve"

    team1 = _build_leader_tool_and_member(SqliteDb(db_file=db_file), member_id="emailer")
    run1 = team1.run("Email and publish", session_id=session_id)
    assert run1.is_paused
    assert sorted(r.tool_execution.tool_name for r in run1.requirements or []) == ["publish", "send_email"]

    for req in run1.requirements or []:
        req.confirm()

    # The member id changed underneath the caller's live run object.
    team2 = _build_leader_tool_and_member(SqliteDb(db_file=db_file), member_id="emailer2")
    with pytest.raises(RunNotContinuableError, match="emailer"):
        team2.continue_run(run_response=run1, session_id=session_id)

    names = sorted(r.tool_execution.tool_name for r in run1.requirements or [])
    assert names == ["publish", "send_email"], "the raise must not strip the caller's requirements"


# ---------------------------------------------------------------------------
# An unresolved team-level requirement on a streaming continue must yield the
# final paused TeamRunOutput (the dispatch-entry pause exit), exactly once.
# ---------------------------------------------------------------------------


def test_team_level_pause_streaming_continue_yields_final_output(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "team_level_stream.db")
    session_id = "s-team-level-stream"

    db = SqliteDb(db_file=db_file)
    team1 = Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel("m-leader", [("tool", "publish", {"item": "release"}, "tc-pub"), ("content", "Done.")]),
        tools=[publish],
        members=[_emailer_agent(db, resuming=False)],
        db=db,
        telemetry=False,
    )
    run1 = team1.run("Publish the release", session_id=session_id)
    assert run1.is_paused

    # Continue WITHOUT resolving the requirement: the run must re-pause and
    # the stream must yield exactly one final TeamRunOutput.
    team2 = Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel("m-leader2", [("content", "Done.")]),
        tools=[publish],
        members=[_emailer_agent(SqliteDb(db_file=db_file), resuming=True)],
        db=SqliteDb(db_file=db_file),
        telemetry=False,
    )
    finals = [
        event
        for event in team2.continue_run(run_id=run1.run_id, session_id=session_id, stream=True, yield_run_output=True)
        if isinstance(event, TeamRunOutput)
    ]
    assert len(finals) == 1, "exactly one final TeamRunOutput must be yielded on a team-level re-pause"
    assert finals[0].is_paused
    assert _EXECUTED == []


# ---------------------------------------------------------------------------
# A continue payload is bound to the stored requirements as one unit. A refusal
# on any entry must leave every stored requirement exactly as the session holds
# it: the refusal tells the client the run is untouched and still resumable, so
# a bare retry of a rejected request must not execute the part that bound.
# ---------------------------------------------------------------------------


def _build_two_gated_members(db: SqliteDb, resuming: bool) -> Team:
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
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-leader",
            [("content", "All done.")]
            if resuming
            else [
                (
                    "tools",
                    [
                        ("delegate_task_to_member", {"member_id": "emailer", "task": "email"}, "tc-deleg-e"),
                        ("delegate_task_to_member", {"member_id": "smser", "task": "sms"}, "tc-deleg-s"),
                    ],
                ),
                ("content", "All done."),
            ],
        ),
        members=[_emailer_agent(db, resuming), smser],
        db=db,
        telemetry=False,
    )


def test_refused_payload_does_not_bank_the_entries_that_bound(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "atomic.db")
    session_id = "s-atomic"

    team1 = _build_two_gated_members(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email and sms", session_id=session_id)
    assert run1.is_paused
    assert len(run1.requirements or []) == 2

    # First entry binds cleanly, second matches no stored requirement.
    payload = _wire_requirements(run1.requirements)
    payload[1].id = "bogus-requirement-id"
    payload[1].tool_execution.tool_call_id = "bogus-tool-call-id"

    with pytest.raises(RunNotContinuableError):
        team1.continue_run(run_response=run1, requirements=payload)

    assert _EXECUTED == []
    # The stored requirements carry no part of the rejected payload's decision.
    assert [r.confirmation for r in run1.requirements or []] == [None, None]
    assert [r.tool_execution.confirmed for r in run1.requirements or []] == [None, None]
    assert not any(r.is_resolved() for r in run1.requirements or [])

    # A bare retry therefore executes nothing, exactly as it would have before
    # the refused call.
    team1.continue_run(run_response=run1)
    assert _EXECUTED == []


def test_binding_refuses_a_stored_id_paired_with_another_tool_call(tmp_path):
    """A valid requirement id carrying a different tool call must not bind: the
    id match alone would confirm one member's tool with the other's arguments."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "crosscheck.db")
    session_id = "s-crosscheck"

    team1 = _build_two_gated_members(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Email and sms", session_id=session_id)
    assert run1.is_paused

    payload = _wire_requirements(run1.requirements)
    # Entry 0 keeps its own (valid) requirement id but carries entry 1's tool call.
    payload[0].tool_execution.tool_call_id = payload[1].tool_execution.tool_call_id
    payload[0].tool_execution.tool_name = payload[1].tool_execution.tool_name

    with pytest.raises(RunNotContinuableError):
        team1.continue_run(run_response=run1, requirements=payload)
    assert _EXECUTED == []


# ---------------------------------------------------------------------------
# The stored schema is the tool's contract. A continue payload supplies answers
# for the fields the model left open — it does not get to rename them, refill
# the ones the model fixed, or declare itself answered.
# ---------------------------------------------------------------------------


_TRANSFERRED: List[Dict[str, Any]] = []


@tool(requires_user_input=True, user_input_fields=["note"])
def transfer_funds(account_id: str, note: str) -> str:
    _TRANSFERRED.append({"account_id": account_id, "note": note})
    return "Transfer done."


def _build_user_input_team(db: SqliteDb, resuming: bool) -> Team:
    banker = Agent(
        name="Banker",
        id="banker",
        model=_ScriptedModel(
            "m-banker",
            [("content", "Transfer done.")]
            if resuming
            else [("tool", "transfer_funds", {"account_id": "victim"}, "tc-xfer"), ("content", "Transfer done.")],
        ),
        tools=[transfer_funds],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Bank Team",
        id="bank-team",
        model=_ScriptedModel(
            "m-leader",
            [("content", "All done.")]
            if resuming
            else [
                ("tool", "delegate_task_to_member", {"member_id": "banker", "task": "move it"}, "tc-deleg"),
                ("content", "All done."),
            ],
        ),
        members=[banker],
        db=db,
        telemetry=False,
    )


def _answered_payload(requirements, values: Dict[str, Any]) -> List[RunRequirement]:
    """Wire round-trip that fills the open input fields, as a frontend would."""
    payload = []
    for data in [r.to_dict() for r in requirements or []]:
        req = RunRequirement.from_dict(data)
        req.provide_user_input(values)
        payload.append(req)
    return payload


def test_user_input_answers_reach_the_member_tool(tmp_path):
    _TRANSFERRED.clear()
    db_file = str(tmp_path / "user_input.db")
    session_id = "s-user-input"

    team1 = _build_user_input_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Move the money", session_id=session_id)
    assert run1.is_paused

    team2 = _build_user_input_team(SqliteDb(db_file=db_file), resuming=True)
    team2.continue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_answered_payload(run1.requirements, {"note": "monthly rent"}),
    )
    assert _TRANSFERRED == [{"account_id": "victim", "note": "monthly rent"}]


def test_wire_schema_cannot_rewrite_an_argument_the_model_fixed(tmp_path):
    """Renaming an open field to a fixed argument's name must not reach tool_args."""
    _TRANSFERRED.clear()
    db_file = str(tmp_path / "schema_tamper.db")
    session_id = "s-schema-tamper"

    team1 = _build_user_input_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Move the money", session_id=session_id)
    assert run1.is_paused

    payload = _answered_payload(run1.requirements, {"note": "ok"})
    for req in payload:
        for schema in (req.user_input_schema, req.tool_execution.user_input_schema):
            for field in schema or []:
                if field.name == "note":
                    field.name = "account_id"
                    field.value = "attacker"

    team2 = _build_user_input_team(SqliteDb(db_file=db_file), resuming=True)
    team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=payload)

    # The renamed field answers nothing the stored schema asked for, so it never
    # reaches tool_args: the argument the model fixed at pause time stands.
    assert [t["account_id"] for t in _TRANSFERRED] == [] or all(t["account_id"] == "victim" for t in _TRANSFERRED)
    assert "attacker" not in [t["account_id"] for t in _TRANSFERRED]


def test_user_input_answer_sent_only_on_the_tool_execution_reaches_the_tool(tmp_path):
    """to_dict ships the schema at both levels, but a client may answer on
    either one alone. Both lanes have to reach the stored tool execution."""
    _TRANSFERRED.clear()
    db_file = str(tmp_path / "te_only.db")
    session_id = "s-te-only"

    team1 = _build_user_input_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Move the money", session_id=session_id)
    assert run1.is_paused

    payload = []
    for data in [r.to_dict() for r in run1.requirements or []]:
        req = RunRequirement.from_dict(data)
        for field in req.tool_execution.user_input_schema or []:
            if field.name == "note":
                field.value = "wire-only"
        req.user_input_schema = None
        payload.append(req)

    team2 = _build_user_input_team(SqliteDb(db_file=db_file), resuming=True)
    team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=payload)
    assert _TRANSFERRED == [{"account_id": "victim", "note": "wire-only"}]


def test_tampered_tool_execution_schema_does_not_change_the_executed_arguments(tmp_path):
    """The dispatch reads the tool execution's schema, so that copy is the one
    an attacker would rename. The stored schema still decides what runs: the
    honest answer sent alongside it lands, and the renamed field does not."""
    _TRANSFERRED.clear()
    db_file = str(tmp_path / "te_tamper.db")
    session_id = "s-te-tamper"

    team1 = _build_user_input_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Move the money", session_id=session_id)
    assert run1.is_paused

    payload = _answered_payload(run1.requirements, {"note": "monthly rent"})
    for req in payload:
        for field in req.tool_execution.user_input_schema or []:
            if field.name == "note":
                field.name = "account_id"
                field.value = "attacker"

    team2 = _build_user_input_team(SqliteDb(db_file=db_file), resuming=True)
    team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=payload)

    assert _TRANSFERRED == [{"account_id": "victim", "note": "monthly rent"}]


def test_wire_answered_flag_alone_does_not_resolve_an_open_field(tmp_path):
    """answered=True with no values must not run a gated tool with the field empty."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "answered_flip.db")
    session_id = "s-answered-flip"

    @tool(requires_user_input=True, user_input_fields=["note"])
    def file_report(subject: str, note: str) -> str:
        _EXECUTED.append(f"{subject}:{note}")
        return "Filed."

    def build(resuming: bool) -> Team:
        return Team(
            name="Desk Team",
            id="desk-team",
            model=_ScriptedModel(
                "m-leader",
                [("content", "All done.")]
                if resuming
                else [("tool", "file_report", {"subject": "q3"}, "tc-file"), ("content", "All done.")],
            ),
            tools=[file_report],
            members=[_emailer_agent(SqliteDb(db_file=db_file), resuming)],
            db=SqliteDb(db_file=db_file),
            telemetry=False,
        )

    run1 = build(resuming=False).run("File it", session_id=session_id)
    assert run1.is_paused

    payload = []
    for data in [r.to_dict() for r in run1.requirements or []]:
        req = RunRequirement.from_dict(data)
        req.tool_execution.answered = True
        payload.append(req)

    run2 = build(resuming=True).continue_run(run_id=run1.run_id, session_id=session_id, requirements=payload)
    assert run2.is_paused, "an unanswered field must keep the run paused"
    assert _EXECUTED == []


def test_external_execution_result_reaches_the_tool_execution(tmp_path):
    """The result is the answer for an external-execution requirement, so it is
    the one payload value that crosses onto the stored tool execution."""
    db_file = str(tmp_path / "external.db")
    session_id = "s-external"

    @tool(external_execution=True)
    def fetch_ledger(quarter: str) -> str:
        raise AssertionError("an external-execution tool must never run in-process")

    def build(resuming: bool) -> Team:
        return Team(
            name="Ledger Team",
            id="ledger-team",
            model=_ScriptedModel(
                "m-leader",
                [("content", "All done.")]
                if resuming
                else [("tool", "fetch_ledger", {"quarter": "q3"}, "tc-ledger"), ("content", "All done.")],
            ),
            tools=[fetch_ledger],
            members=[_emailer_agent(SqliteDb(db_file=db_file), resuming)],
            db=SqliteDb(db_file=db_file),
            telemetry=False,
        )

    run1 = build(resuming=False).run("Fetch it", session_id=session_id)
    assert run1.is_paused

    payload = []
    for data in [r.to_dict() for r in run1.requirements or []]:
        req = RunRequirement.from_dict(data)
        req.external_execution_result = "ledger-rows"
        req.tool_execution.result = "ledger-rows"
        payload.append(req)

    run2 = build(resuming=True).continue_run(run_id=run1.run_id, session_id=session_id, requirements=payload)
    assert run2.status == RunStatus.completed
    stored = [r for r in _reload_runs(db_file, session_id) if getattr(r, "team_id", None) == "ledger-team"]
    results = [t.result for t in (stored[0].tools or []) if t.tool_name == "fetch_ledger"]
    assert results == ["ledger-rows"]


# ---------------------------------------------------------------------------
# A refusal raised below the top level must not damage the caller's run object.
# The requirement objects a parent routes into a sub-team are the parent's own,
# so the sub-team's reclaim has to work on a copy: de-stamping in place leaves
# the parent holding what looks like a team-level requirement of its own, and
# the retry the refusal invites then completes with the approved tool skipped.
# ---------------------------------------------------------------------------


def test_nested_refusal_keeps_the_subteam_requirement_routable(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "nested_refusal.db")
    session_id = "s-nested-refusal"

    outer1 = _build_subteam_own_tool(SqliteDb(db_file=db_file), resuming=False, mixed=True)
    run1 = outer1.run("Publish the release", session_id=session_id)
    assert run1.is_paused
    stamps_at_pause = {
        r.tool_execution.tool_name: r.member_agent_id for r in run1.requirements or [] if r.tool_execution
    }
    assert stamps_at_pause["publish"] == "comms-team"

    for req in run1.requirements or []:
        req.confirm()

    # The deep member's continue fails once, the way a transient model outage
    # would, so the sub-team's dispatch raises after the reclaim has run.
    outer2 = _build_subteam_own_tool(SqliteDb(db_file=db_file), resuming=True, mixed=True)
    inner = outer2.members[0]
    emailer = inner.members[0]
    original_continue = emailer.continue_run

    def failing_continue(*args, **kwargs):
        raise RuntimeError("transient model outage")

    emailer.continue_run = failing_continue  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        outer2.continue_run(run_response=run1)
    emailer.continue_run = original_continue  # type: ignore[method-assign]

    assert _EXECUTED == []
    stamps_after = {r.tool_execution.tool_name: r.member_agent_id for r in run1.requirements or [] if r.tool_execution}
    assert stamps_after == stamps_at_pause, "a refusal below must not restamp the caller's requirements"

    # The retry the refusal invites executes every approved tool.
    outer3 = _build_subteam_own_tool(SqliteDb(db_file=db_file), resuming=True, mixed=True)
    run3 = outer3.continue_run(run_response=run1)
    assert run3.status == RunStatus.completed
    assert sorted(_EXECUTED) == ["a@example.com", "pub:release"]


# ---------------------------------------------------------------------------
# The scrub builds a storage view; it does not replace the session's live runs.
# Rebinding them would freeze the stored copy of a paused member run at PAUSED
# while the resume continues the live one, so a finished run would advertise a
# pending approval for good.
# ---------------------------------------------------------------------------


def test_completed_run_stores_no_stale_paused_member(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "stale.db")
    session_id = "s-stale"

    # One team object across both calls, with the session cached: the cached
    # session is what would hold a frozen copy of the paused member run.
    outer = _build_nested_team(SqliteDb(db_file=db_file), resuming=False)
    outer.cache_session = True
    run1 = outer.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused

    run2 = outer.continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]

    for run in _reload_runs(db_file, session_id):
        assert not run.is_paused
        for member_response in getattr(run, "member_responses", None) or []:
            assert not member_response.is_paused, "a finished run must not keep a paused member snapshot"


# ---------------------------------------------------------------------------
# Sparing a paused member run so it can be resumed must not carry its data past
# that member's own storage flags — the delegation path applies them to every
# member run it persists.
# ---------------------------------------------------------------------------


def test_spared_paused_member_run_honours_store_tool_messages(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "flags.db")
    session_id = "s-flags"

    def build(phase: str) -> Team:
        team = _build_nested_chained_team(SqliteDb(db_file=db_file), phase=phase)
        team.members[0].members[0].store_tool_messages = False
        return team

    run1 = build("pause").run("Email then sms", session_id=session_id)
    assert run1.is_paused

    # Confirm send_email; the member runs it and chains a gated send_sms.
    run2 = build("chain").continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert run2.is_paused
    assert _EXECUTED == ["a@example.com"]

    def leaf_runs(runs):
        for run in runs:
            for member_response in getattr(run, "member_responses", None) or []:
                if getattr(member_response, "agent_id", None) == "emailer":
                    yield member_response
                yield from leaf_runs([member_response])

    stored_leaves = list(leaf_runs(_reload_runs(db_file, session_id)))
    assert stored_leaves, "the paused member run must still be persisted for the resume"
    for leaf in stored_leaves:
        roles = [m.role for m in leaf.messages or []]
        assert "tool" not in roles, "store_tool_messages=False must reach a spared paused member run"
        pending = [call["id"] for m in leaf.messages or [] if m.role == "assistant" for call in m.tool_calls or []]
        assert "tc-sms-chain" in pending, "the unresolved call must survive the scrub for the resume"

    # And the resume still works from a fresh process.
    unresolved = [r for r in run2.requirements or [] if not r.is_resolved()]
    run3 = build("finish").continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(unresolved)
    )
    assert run3.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com", "sms:c@x.com"]


def test_live_run_tree_keeps_its_tool_messages_after_a_save(tmp_path):
    """The storage scrub is copy-on-write: the caller's in-flight run keeps
    everything the member's flags strip from the stored copy."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "cow.db")
    session_id = "s-cow"

    team = _build_nested_chained_team(SqliteDb(db_file=db_file), phase="pause")
    team.members[0].members[0].store_tool_messages = False
    run1 = team.run("Email then sms", session_id=session_id)
    assert run1.is_paused

    def leaves(run):
        for member_response in getattr(run, "member_responses", None) or []:
            if getattr(member_response, "agent_id", None) == "emailer":
                yield member_response
            yield from leaves(member_response)

    live = list(leaves(run1))
    assert live, "the live run tree must still hold the member response"
    for leaf in live:
        assert leaf.messages, "the live member run must keep its messages"


# ---------------------------------------------------------------------------
# The user-feedback lane of the decision merge. No tool decorator declares
# feedback, so it is pinned directly on the merge.
# ---------------------------------------------------------------------------


def _feedback_requirement() -> RunRequirement:
    from agno.tools.function import UserFeedbackOption, UserFeedbackQuestion

    schema = [
        UserFeedbackQuestion(
            question="Which channel?",
            options=[UserFeedbackOption(label="email"), UserFeedbackOption(label="sms")],
        )
    ]
    req = _make_requirement(tool_name="notify", tool_call_id="tc-fb", user_feedback_schema=schema)
    req.user_feedback_schema = schema
    return req


def test_user_feedback_selections_reach_the_stored_tool_execution():
    from agno.team._run import _merge_requirement_decision

    stored = _feedback_requirement()
    wire = RunRequirement.from_dict(stored.to_dict())
    wire.provide_user_feedback({"Which channel?": ["sms"]})

    _merge_requirement_decision(stored, wire)

    stored_question = stored.tool_execution.user_feedback_schema[0]
    assert stored_question.selected_options == ["sms"]
    assert [(o.label, o.selected) for o in stored_question.options] == [("email", False), ("sms", True)]
    assert stored.tool_execution.answered is True
    assert stored.is_resolved()


def test_user_feedback_answer_for_an_unknown_question_is_ignored():
    from agno.tools.function import UserFeedbackQuestion

    from agno.team._run import _merge_requirement_decision

    stored = _feedback_requirement()
    wire = RunRequirement.from_dict(stored.to_dict())
    for question in wire.tool_execution.user_feedback_schema or []:
        question.question = "Which account?"
        question.selected_options = ["drain-it"]
    wire.user_feedback_schema = [UserFeedbackQuestion(question="Which account?", selected_options=["drain-it"])]

    _merge_requirement_decision(stored, wire)

    stored_question = stored.tool_execution.user_feedback_schema[0]
    assert stored_question.question == "Which channel?"
    assert stored_question.selected_options is None
    assert stored.tool_execution.answered is None, "an unanswered question must leave the run unresolved"
