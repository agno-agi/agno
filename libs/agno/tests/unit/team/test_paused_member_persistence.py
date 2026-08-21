"""
Unit tests for paused member run persistence in team routing helpers.

Regression test for: https://github.com/agno-agi/agno/issues/8925

When a member pauses during team.continue_run() routing, its RunOutput must be
persisted to session.runs so subsequent continue_run calls can find it after
session reload.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent import Agent
from agno.approval.decorator import approval
from agno.db.sqlite import SqliteDb
from agno.exceptions import RunNotContinuableError, RunNotFoundError
from agno.models.base import Model
from agno.models.message import Message
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
    from agno.team._run import _merge_requirement_decision
    from agno.tools.function import UserFeedbackQuestion

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


# ---------------------------------------------------------------------------
# The approval gate can refuse a continue AFTER the payload has bound, so the
# merge has to be undoable. Restoring the requirements list is not enough: its
# entries are the stored requirements the merge wrote into.
# ---------------------------------------------------------------------------


def _mixed_requirements() -> List[RunRequirement]:
    from agno.tools.function import UserFeedbackOption, UserFeedbackQuestion, UserInputField

    confirm_req = _make_requirement(
        tool_name="send_email", tool_call_id="tc-c", requires_confirmation=True, approval_type="required"
    )
    input_req = _make_requirement(
        tool_name="transfer",
        tool_call_id="tc-i",
        requires_user_input=True,
        user_input_schema=[UserInputField(name="note", field_type=str)],
    )
    input_req.user_input_schema = input_req.tool_execution.user_input_schema
    feedback_req = _make_requirement(
        tool_name="notify",
        tool_call_id="tc-f",
        user_feedback_schema=[
            UserFeedbackQuestion(question="Which channel?", options=[UserFeedbackOption(label="sms")])
        ],
    )
    feedback_req.user_feedback_schema = feedback_req.tool_execution.user_feedback_schema
    return [confirm_req, input_req, feedback_req]


def test_restoring_decisions_undoes_the_whole_merge():
    from agno.team._run import _apply_requirements_payload, _restore_requirement_decisions

    stored = _mixed_requirements()
    run_response = TeamRunOutput(
        run_id="run-1",
        session_id="session-1",
        requirements=stored,
        tools=[r.tool_execution for r in stored],
    )
    before = [r.to_dict() for r in stored]

    payload = [RunRequirement.from_dict(d) for d in before]
    payload[0].confirm()
    payload[1].provide_user_input({"note": "typed"})
    payload[2].provide_user_feedback({"Which channel?": ["sms"]})

    _, _, decisions = _apply_requirements_payload(run_response, payload)

    # The merge landed on every lane.
    assert stored[0].tool_execution.confirmed is True
    assert stored[1].tool_execution.user_input_schema[0].value == "typed"
    assert stored[2].tool_execution.user_feedback_schema[0].selected_options == ["sms"]
    assert stored[2].tool_execution.user_feedback_schema[0].options[0].selected is True

    _restore_requirement_decisions(decisions)

    assert [r.to_dict() for r in stored] == before, "the snapshot must cover every field the merge writes"
    assert not any(r.is_resolved() for r in stored)


# ---------------------------------------------------------------------------
# Round 10: conflicting identities, prefilled input, merge rollback, retry
# member phase, storage owning path
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Round 10.1: continue-payload binding when a payload requirement's identity
# conflicts with the stored requirements.
#
# Defect: in _backfill_approval_to_requirements, a payload entry whose
# requirement id matches stored requirement A but whose tool_call_id belongs
# to a DIFFERENT stored requirement B silently drops the id match
# ("cross-check failed") and falls through to the tool_call_id fallback,
# binding the entry to B. The client's confirmation then executes B's tool
# even though the entry named A. A conflicting identity must refuse the
# continue instead; the tool_call_id fallback exists only for entries whose id
# matches no stored requirement at all (RunRequirement auto-generates ids, so
# unknown ids are a normal wire condition).
# ---------------------------------------------------------------------------


def _stored_confirmation_requirements() -> List[RunRequirement]:
    req_a = RunRequirement(
        tool_execution=_make_tool_execution(tool_name="send_email", tool_call_id="tc-a", requires_confirmation=True),
        id="req-a",
    )
    req_b = RunRequirement(
        tool_execution=_make_tool_execution(
            tool_name="delete_records", tool_call_id="tc-b", requires_confirmation=True
        ),
        id="req-b",
    )
    return [req_a, req_b]


def _run_with(stored: List[RunRequirement]) -> TeamRunOutput:
    return TeamRunOutput(
        run_id="run-1",
        session_id="session-1",
        requirements=stored,
        tools=[r.tool_execution for r in stored],
    )


def test_conflicting_requirement_identity_refuses_the_continue():
    """Pins the fix for the cross-check fallthrough: a payload entry carrying
    stored requirement A's id but stored requirement B's tool_call_id must
    raise RunNotContinuableError and leave the run paused and unchanged. At
    the defective head the id match is silently discarded and the tool_call_id
    fallback binds the entry to B, so B's tool executes with a confirmation
    the client gave under A's identity."""
    from agno.team._run import _apply_requirements_payload

    stored = _stored_confirmation_requirements()
    run_response = _run_with(stored)

    conflicting = RunRequirement(
        tool_execution=_make_tool_execution(
            tool_name="delete_records", tool_call_id="tc-b", requires_confirmation=True
        ),
        id="req-a",  # stored A's identity over stored B's tool call
    )
    conflicting.confirm()

    with pytest.raises(RunNotContinuableError):
        _apply_requirements_payload(run_response, [conflicting])

    # The refusal left the run paused and untouched: B never received the
    # confirmation that was addressed to A, and the stored requirements are
    # still the ones routing sees.
    assert stored[1].confirmation is None
    assert stored[1].tool_execution.confirmed is None
    assert run_response.requirements == stored


def test_unknown_requirement_id_still_binds_by_unique_tool_call_id():
    """Pins behavior that must SURVIVE the conflicting-identity fix: an entry
    whose id matches no stored requirement (RunRequirement auto-generates a
    fresh id for every wire object, so unknown ids are normal) binds via the
    tool_call_id fallback when exactly one stored requirement carries that
    tool_call_id. This test passes at the defective head too; it guards the
    fix against over-tightening the fallback."""
    from agno.team._run import _apply_requirements_payload

    stored = _stored_confirmation_requirements()
    run_response = _run_with(stored)

    wire = RunRequirement(  # auto-generated id, unknown to the stored run
        tool_execution=_make_tool_execution(
            tool_name="delete_records", tool_call_id="tc-b", requires_confirmation=True
        ),
    )
    assert wire.id not in {r.id for r in stored}
    wire.confirm()

    _apply_requirements_payload(run_response, [wire])

    # The fallback bound the entry to the STORED requirement object and merged
    # only the decision onto it.
    assert run_response.requirements is not None
    assert run_response.requirements[0] is stored[1]
    assert stored[1].confirmation is True
    assert stored[1].tool_execution.confirmed is True


# ---------------------------------------------------------------------------
# Round 10.2: prefilled user-input pauses that could never resume.
#
# A requires_user_input tool can pause with EVERY canonical field already
# populated by model-supplied arguments — the pause exists so the user can
# review and accept them. _merge_requirement_decision computed
# input_was_open/feedback_was_open from the stored schema before merging, so a
# fully prefilled schema left both False, and the wire answered flag was
# copied only when the stored requirement carried NO input schema and NO
# feedback schema at all. The client's explicit answered=True was therefore
# dropped, stored answered stayed None, and continuation left the run paused
# forever.
#
# The correct behavior pinned here: when the stored canonical schema is
# complete (no field open), an explicit wire answered flag is accepted — while
# schemas are still never rebound and a wire answered=True with an OPEN stored
# field is still ignored.
# ---------------------------------------------------------------------------


def _prefilled_input_requirement() -> RunRequirement:
    """A user-input pause whose every field the model prefilled at pause time."""
    from agno.tools.function import UserInputField

    tool_execution = ToolExecution(
        tool_name="transfer",
        tool_args={"account_id": "victim", "note": "monthly rent"},
        tool_call_id="tc-prefilled",
        requires_user_input=True,
        user_input_schema=[
            UserInputField(name="account_id", field_type=str, value="victim"),
            UserInputField(name="note", field_type=str, value="monthly rent"),
        ],
    )
    return RunRequirement(tool_execution=tool_execution)


def test_wire_answered_flag_resolves_a_fully_prefilled_input_schema():
    """A fully prefilled schema has no open field for the merge to fill, so the
    client's explicit answered=True is the only signal that the user accepted
    the values. The merge dropped it (the wire flag was honored only when the
    stored requirement had no schema at all), leaving answered=None and the
    run paused forever."""
    from agno.team._run import _merge_requirement_decision

    stored = _prefilled_input_requirement()
    stored_schema = stored.tool_execution.user_input_schema
    assert stored.tool_execution.answered is None

    wire = RunRequirement.from_dict(stored.to_dict())
    # The user reviews the prefilled values and accepts them unchanged: every
    # field already has a value, so the client marks the requirement answered.
    wire.provide_user_input({})
    assert wire.tool_execution.answered is True

    _merge_requirement_decision(stored, wire)

    assert stored.tool_execution.answered is True, "an accepted prefilled pause must read as answered"
    assert stored.is_resolved()
    # The schema is never rebound and the model-fixed values stand.
    assert stored.tool_execution.user_input_schema is stored_schema
    assert [(f.name, f.value) for f in stored_schema] == [("account_id", "victim"), ("note", "monthly rent")]


def test_prefilled_input_pause_resolves_through_apply_requirements_payload():
    """The end-to-end consequence of the dropped flag: a continuation payload
    (raw dicts, as the wire delivers them) must leave the stored requirement
    resolved rather than permanently paused."""
    from agno.team._run import _apply_requirements_payload

    stored = _prefilled_input_requirement()
    run_response = TeamRunOutput(
        run_id="run-prefilled",
        session_id="session-prefilled",
        requirements=[stored],
        tools=[stored.tool_execution],
    )

    wire = RunRequirement.from_dict(stored.to_dict())
    wire.provide_user_input({})
    assert wire.tool_execution.answered is True
    payload = [wire.to_dict()]

    _apply_requirements_payload(run_response, payload)

    assert run_response.requirements is not None
    assert run_response.requirements[0] is stored, "binding must keep the stored requirement as the routed object"
    assert stored.tool_execution.answered is True, "the accepted prefilled pause must resolve on continue"
    assert stored.is_resolved()


def test_wire_answered_flag_still_ignored_while_a_field_is_open():
    """The safeguard the fix must not weaken: answered=True from the wire with
    a stored field still open would run the gated tool with that field empty,
    so it must continue to be ignored."""
    from agno.team._run import _merge_requirement_decision
    from agno.tools.function import UserInputField

    stored = RunRequirement(
        tool_execution=ToolExecution(
            tool_name="transfer",
            tool_args={"account_id": "victim"},
            tool_call_id="tc-open",
            requires_user_input=True,
            user_input_schema=[
                UserInputField(name="account_id", field_type=str, value="victim"),
                UserInputField(name="note", field_type=str),
            ],
        )
    )

    wire = RunRequirement.from_dict(stored.to_dict())
    wire.tool_execution.answered = True

    _merge_requirement_decision(stored, wire)

    assert stored.tool_execution.answered is None, "an open field must keep the requirement unanswered"
    assert not stored.is_resolved()


# ---------------------------------------------------------------------------
# Round 10.3: a merge exception inside _apply_requirements_payload must not
# bank earlier payload entries' decisions.
#
# _apply_requirements_payload snapshots the stored requirements' decision
# state (_snapshot_requirement_decisions) before binding the payload, but its
# except clause restores only the run object's requirements and tools list
# references. _merge_requirement_decision can raise on malformed wire data
# AFTER an earlier payload entry already merged - e.g. a user_feedback answer
# whose selected_options is not iterable raises TypeError in the option
# membership check. Without _restore_requirement_decisions in that except, the
# earlier entry's banked confirmation and the partially written feedback state
# survive the refusal, so a bare retry of the rejected request would execute
# tools the caller was told stayed untouched.
# ---------------------------------------------------------------------------


def _stored_confirm_and_feedback_requirements() -> List[RunRequirement]:
    from agno.tools.function import UserFeedbackOption, UserFeedbackQuestion

    confirm_req = _make_requirement(
        tool_name="send_email", tool_call_id="tc-confirm", requires_confirmation=True, approval_type="required"
    )
    feedback_req = _make_requirement(
        tool_name="notify",
        tool_call_id="tc-feedback",
        user_feedback_schema=[
            UserFeedbackQuestion(
                question="Which channel?",
                options=[UserFeedbackOption(label="email"), UserFeedbackOption(label="sms")],
            )
        ],
    )
    feedback_req.user_feedback_schema = feedback_req.tool_execution.user_feedback_schema
    return [confirm_req, feedback_req]


def _apply_two_entry_payload_that_raises_mid_merge(stored: List[RunRequirement]) -> TeamRunOutput:
    """Run the production payload apply with a valid first entry and a second
    entry whose feedback answer raises inside the merge, and return the run.

    The second entry's selected_options is an int: UserFeedbackQuestion's
    deserialization keeps it as-is, so the TypeError fires only inside
    _fill_user_feedback_answers ("option.label in question.selected_options"),
    after the first entry's confirmation already merged onto its stored
    requirement.
    """
    from agno.team._run import _apply_requirements_payload

    run_response = TeamRunOutput(
        run_id="run-1",
        session_id="session-1",
        requirements=stored,
        tools=[r.tool_execution for r in stored],
    )
    payload = [
        {"id": stored[0].id, "tool_execution": {"tool_call_id": "tc-confirm"}, "confirmation": True},
        {
            "id": stored[1].id,
            "tool_execution": {
                "tool_call_id": "tc-feedback",
                "user_feedback_schema": [{"question": "Which channel?", "selected_options": 5}],
            },
        },
    ]

    with pytest.raises(Exception):
        _apply_requirements_payload(run_response, payload)
    return run_response


def test_merge_exception_does_not_bank_an_earlier_entrys_confirmation():
    """Pins: the except in _apply_requirements_payload restores only list
    references, so the confirmation merged from the first payload entry
    survives when a later entry's merge raises.
    """
    stored = _stored_confirm_and_feedback_requirements()

    _apply_two_entry_payload_that_raises_mid_merge(stored)

    assert stored[0].confirmation is None, (
        "a refused continue must not bank the first entry's confirmation on the stored requirement"
    )
    assert stored[0].tool_execution.confirmed is None, (
        "a refused continue must not leave the stored tool execution confirmed"
    )
    assert not any(r.is_resolved() for r in stored)


def test_merge_exception_does_not_leave_partial_feedback_state():
    """Pins: _fill_user_feedback_answers writes selected_options before the
    option loop raises on the malformed value, and the except never restores
    decision fields - the corrupted answer survives the refusal.
    """
    stored = _stored_confirm_and_feedback_requirements()

    _apply_two_entry_payload_that_raises_mid_merge(stored)

    question = stored[1].tool_execution.user_feedback_schema[0]
    assert question.selected_options is None, (
        "a refused continue must not leave the malformed answer on the stored feedback question"
    )
    assert [option.selected for option in question.options] == [False, False]


# ---------------------------------------------------------------------------
# Round 10.4: async continue retries must not falsely complete member-only
# continuations.
#
# Defect: in _acontinue_run and _acontinue_run_stream the whole continue
# dispatch sits inside the retry loop. On attempt 1 the requirements payload
# binds (requirements_applied=True), member routing succeeds and consumes the
# member requirements, and then the leader model call raises a transient
# (non-ValueError) exception. On attempt 2 member_results is re-initialized to
# [], the requirements_applied guard skips re-binding, no requirements are
# left, and every branch is skipped — the run falls through to
# RunStatus.completed with content=None. The leader is never retried and the
# member results are lost. The sync _continue_run does not have this defect
# because its retry loop wraps only the model call.
#
# Correct behavior pinned here: after a transient leader-model failure that
# follows successful member routing, the retry re-runs the leader with the
# preserved member results and the run completes WITH the leader's content.
# ---------------------------------------------------------------------------


class _FlakyScriptedModel(Model):
    """Emits scripted turns offline: ('tool', name, args, id), ('content', text),
    or ('raise', message) which raises RuntimeError — a transient provider
    failure that the team retry loop is meant to absorb (it is deliberately
    not a ValueError, InputCheckError or RunCancelledException)."""

    def __init__(self, model_id: str, script: List[tuple]):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._script = list(script)
        self._i = 0

    def _next(self) -> ModelResponse:
        from agno.metrics import MessageMetrics

        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "raise":
            raise RuntimeError(turn[1])
        if turn[0] == "tool":
            _, name, args, tcid = turn
            r = ModelResponse(role="assistant")
            r.tool_calls = [{"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]
        else:
            r = ModelResponse(content=turn[1], role="assistant")
            r.event = ModelResponseEvent.assistant_response.value
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


def _flaky_emailer_agent(db: SqliteDb, resuming: bool) -> Agent:
    script = (
        [("content", "Email sent.")]
        if resuming
        else [("tool", "send_email", {"to": "a@example.com"}, "tc-send"), ("content", "Email sent.")]
    )
    return Agent(
        name="Emailer",
        id="emailer",
        model=_FlakyScriptedModel("m-emailer", script),
        tools=[send_email],
        db=db,
        telemetry=False,
    )


def _build_pausing_team(db: SqliteDb) -> Team:
    """Phase 1: leader delegates, the member's gated tool pauses the run."""
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_FlakyScriptedModel(
            "m-leader",
            [
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-deleg"),
                ("content", "All done."),
            ],
        ),
        members=[_flaky_emailer_agent(db, resuming=False)],
        db=db,
        telemetry=False,
    )


def _build_flaky_resuming_team(db: SqliteDb) -> Team:
    """Phase 2: the leader's FIRST call after member routing raises a
    transient RuntimeError; the retry's call returns the final content."""
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_FlakyScriptedModel(
            "m-leader-flaky",
            [("raise", "transient provider failure"), ("content", "final answer")],
        ),
        members=[_flaky_emailer_agent(db, resuming=True)],
        db=db,
        telemetry=False,
        retries=1,
        delay_between_retries=0,
    )


@pytest.mark.asyncio
async def test_async_continue_retry_reruns_leader_with_member_results_after_transient_failure(tmp_path):
    """Pins the defect where _acontinue_run's retry attempt resets
    member_results and skips re-binding after member routing consumed the
    requirements, falling through to a false COMPLETED with content=None
    instead of re-running the leader with the preserved member results."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "retry_member_phase.db")
    session_id = "s-retry-member-phase"

    team1 = _build_pausing_team(SqliteDb(db_file=db_file))
    run1 = await team1.arun("Email a@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []

    team2 = _build_flaky_resuming_team(SqliteDb(db_file=db_file))
    run2 = await team2.acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )

    # The confirmed member tool executed during routing on the first attempt.
    assert _EXECUTED == ["a@example.com"]
    # The retry must re-run the leader over the preserved member results and
    # complete with the leader's content — not an empty COMPLETED.
    assert run2.status == RunStatus.completed
    assert run2.content == "final answer", (
        "transient leader failure after member routing must retry the leader, "
        f"not complete with content={run2.content!r}"
    )


@pytest.mark.asyncio
async def test_async_streaming_continue_retry_reruns_leader_with_member_results_after_transient_failure(tmp_path):
    """Pins the same defect in _acontinue_run_stream: the retry attempt after
    a transient leader-model failure skips every branch and yields a falsely
    COMPLETED run with content=None instead of re-running the leader."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "retry_member_phase_stream.db")
    session_id = "s-retry-member-phase-stream"

    team1 = _build_pausing_team(SqliteDb(db_file=db_file))
    run1 = await team1.arun("Email a@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []

    team2 = _build_flaky_resuming_team(SqliteDb(db_file=db_file))
    final = None
    async for event in team2.acontinue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements(run1.requirements),
        stream=True,
        yield_run_output=True,
    ):
        if isinstance(event, TeamRunOutput):
            final = event

    assert final is not None
    assert _EXECUTED == ["a@example.com"]
    assert final.status == RunStatus.completed
    assert final.content == "final answer", (
        "transient leader failure after member routing must retry the leader, "
        f"not complete with content={final.content!r}"
    )


# ---------------------------------------------------------------------------
# Round 10.5: the storage view of a spared paused member run must resolve
# storage flags through the paused response's OWNING PATH in the team tree,
# not through a global first-match id search from the root team.
#
# Defect: duplicate leaf member ids across sibling subteams are supported, but
# _storage_view_of_spared_run resolves flags via _find_member_by_id(team,
# member_id) from the ROOT team, and _scrub_member_responses_keeping_paused
# recurses into nested spared runs passing the ROOT team unchanged. A paused
# run owned by the right subteam's leaf therefore picks up the LEFT subteam's
# same-id leaf and applies the wrong store_tool_messages setting.
# ---------------------------------------------------------------------------


def _build_root_with_duplicate_leaf_ids(
    left_store_tool_messages: bool, right_store_tool_messages: bool
) -> Tuple[Team, Team]:
    """Root -> [left subteam, right subteam]; each subteam holds a leaf agent
    with the SAME name, so both leaves derive the same url-safe member id."""
    from agno.utils.team import get_member_id

    left_worker = Agent(name="Worker", store_tool_messages=left_store_tool_messages, telemetry=False)
    right_worker = Agent(name="Worker", store_tool_messages=right_store_tool_messages, telemetry=False)
    left_team = Team(name="Left Team", members=[left_worker], telemetry=False)
    right_team = Team(name="Right Team", members=[right_worker], telemetry=False)
    root = Team(name="Root Team", members=[left_team, right_team], telemetry=False)

    assert get_member_id(left_worker) == get_member_id(right_worker), (
        "the setup requires duplicate leaf member ids across sibling subteams"
    )
    return root, right_team


def _paused_root_run_owned_by_right_leaf(root: Team, right_team: Team) -> TeamRunOutput:
    """Root run whose only member response is a paused right-subteam run that
    holds the paused leaf run: one completed tool call with its tool result
    message, plus an unresolved pending call on the same assistant turn."""
    from agno.utils.team import get_member_id

    leaf_run = RunOutput(
        run_id="member-run-right-worker",
        agent_id=get_member_id(right_team.members[0]),
        status=RunStatus.paused,
        messages=[
            Message(
                role="assistant",
                tool_calls=[
                    {"id": "tc-done", "type": "function", "function": {"name": "send_email", "arguments": "{}"}},
                    {"id": "tc-pending", "type": "function", "function": {"name": "send_sms", "arguments": "{}"}},
                ],
            ),
            Message(role="tool", tool_call_id="tc-done", content="Email sent"),
        ],
    )
    right_team_run = TeamRunOutput(
        run_id="team-run-right",
        team_id=get_member_id(right_team),
        status=RunStatus.paused,
        member_responses=[leaf_run],
    )
    return TeamRunOutput(
        run_id="team-run-root",
        team_id=get_member_id(root),
        status=RunStatus.paused,
        member_responses=[right_team_run],
    )


def _stored_leaf(view: TeamRunOutput) -> RunOutput:
    stored_right = view.member_responses[0]
    assert getattr(stored_right, "member_responses", None), "the paused leaf run must be spared for the resume"
    return stored_right.member_responses[0]


def test_spared_leaf_storage_flags_resolve_through_owning_subteam():
    """Pins the defect where _storage_view_of_spared_run resolves a duplicate
    leaf id from the ROOT team: the left sibling's store_tool_messages=True
    wins over the owning right worker's False, so completed tool messages are
    persisted against the actual member's setting."""
    from agno.team._session import _scrub_member_responses_keeping_paused

    root, right_team = _build_root_with_duplicate_leaf_ids(
        left_store_tool_messages=True, right_store_tool_messages=False
    )
    root_run = _paused_root_run_owned_by_right_leaf(root, right_team)

    view = _scrub_member_responses_keeping_paused(root, root_run)

    leaf = _stored_leaf(view)
    roles = [m.role for m in leaf.messages or []]
    assert "tool" not in roles, (
        "the owning right worker's store_tool_messages=False must scrub completed tool "
        "messages, even though a left sibling shares the leaf member id"
    )
    kept_calls = [call["id"] for m in leaf.messages or [] if m.role == "assistant" for call in m.tool_calls or []]
    assert kept_calls == ["tc-pending"], "the unresolved call must survive the scrub for the resume"


def test_spared_leaf_keeps_tool_messages_when_owning_member_stores_them():
    """Pins the same wrong-duplicate resolution from the other side: the left
    sibling's store_tool_messages=False must not scrub a paused run owned by
    the right worker whose own setting is True."""
    from agno.team._session import _scrub_member_responses_keeping_paused

    root, right_team = _build_root_with_duplicate_leaf_ids(
        left_store_tool_messages=False, right_store_tool_messages=True
    )
    root_run = _paused_root_run_owned_by_right_leaf(root, right_team)

    view = _scrub_member_responses_keeping_paused(root, root_run)

    leaf = _stored_leaf(view)
    roles = [m.role for m in leaf.messages or []]
    assert "tool" in roles, (
        "the owning right worker's store_tool_messages=True must keep its completed tool "
        "messages, even though a left sibling with the same member id has it disabled"
    )
    kept_calls = [call["id"] for m in leaf.messages or [] if m.role == "assistant" for call in m.tool_calls or []]
    assert kept_calls == ["tc-done", "tc-pending"], "both tool calls must survive when the owning member stores them"


# ---------------------------------------------------------------------------
# Round 11: the payload binding must carry a failure, and must not latch
# ---------------------------------------------------------------------------


@tool(external_execution=True)
def fetch_ledger(quarter: str) -> str:
    raise AssertionError("an external-execution tool must never run in-process")


def _build_external_execution_team(db_file: str, resuming: bool) -> Team:
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


def test_external_execution_error_flag_survives_the_binding(tmp_path):
    """A frontend tool that reported a failure must not be rebound as a success.

    agno's own AG-UI interface sets tool_call_error before handing the
    requirements to continue_run, so dropping the flag while copying the result
    turns every reported failure into a success in the transcript and in
    storage.
    """
    db_file = str(tmp_path / "extern_err.db")
    session_id = "s-extern-err"

    run1 = _build_external_execution_team(db_file, resuming=False).run("Fetch it", session_id=session_id)
    assert run1.is_paused

    # Exactly what os/interfaces/agui/resume.py does for a failed frontend tool.
    payload: List[RunRequirement] = []
    for data in [r.to_dict() for r in run1.requirements or []]:
        req = RunRequirement.from_dict(data)
        req.tool_execution.tool_call_error = True
        req.set_external_execution_result("Ledger service returned 503")
        payload.append(req)

    run2 = _build_external_execution_team(db_file, resuming=True).continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=payload
    )

    msgs = [m for m in (run2.messages or []) if getattr(m, "tool_call_id", None) == "tc-ledger"]
    assert msgs, "the external execution result must reach the conversation"
    assert msgs[0].content == "Ledger service returned 503"
    assert msgs[0].tool_call_error is True, "a failed frontend tool must be recorded as an error"

    stored = [r for r in _reload_runs(db_file, session_id) if getattr(r, "team_id", None) == "ledger-team"]
    tools = [t for t in (stored[0].tools or []) if t.tool_name == "fetch_ledger"]
    assert [t.tool_call_error for t in tools] == [True], "the error flag must survive the storage round trip"


def test_rolling_back_a_refused_merge_restores_the_error_flag():
    """tool_call_error is a decision field, so the refusal snapshot has to cover
    it — otherwise a refused payload leaves its error flag written behind."""
    from agno.team._run import _requirement_decision_slots

    req = RunRequirement(
        tool_execution=ToolExecution(
            tool_name="fetch_ledger",
            tool_args={"quarter": "q3"},
            tool_call_id="tc-ledger",
            external_execution_required=True,
        )
    )
    slots = {attr for obj, attr in _requirement_decision_slots([req]) if obj is req.tool_execution}
    assert "tool_call_error" in slots, "the rollback must restore tool_call_error along with the result it describes"


def test_wire_answered_false_does_not_latch_a_prefilled_pause():
    """Only True is an accept gesture.

    The branch that honours an explicit wire flag sits under `answered is None`,
    so writing a wire False closes that guard for good: nothing in the codebase
    ever re-nulls the flag, and the pause becomes unresumable for the rest of
    the session with no client-side recovery.
    """
    from agno.team._run import _merge_requirement_decision

    stored = _prefilled_input_requirement()

    not_yet = RunRequirement.from_dict(stored.to_dict())
    not_yet.tool_execution.answered = False
    _merge_requirement_decision(stored, not_yet)
    assert not stored.is_resolved(), "answered=False must leave the pause unresolved"
    assert stored.tool_execution.answered is not False, "a wire False must not be written onto the stored requirement"

    accepted = RunRequirement.from_dict(stored.to_dict())
    accepted.tool_execution.answered = True
    _merge_requirement_decision(stored, accepted)

    assert stored.tool_execution.answered is True, "a later answered=True must still take effect"
    assert stored.is_resolved()


# ---------------------------------------------------------------------------
# Round 11: the storage view must never be the session's public state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_async_saves_keep_the_live_member_responses(monkeypatch):
    """Two overlapping saves on one session must not leave the scrubbed view live.

    cache_session hands every caller the same TeamSession, so rebinding
    session.runs for the length of an awaited write publishes the throwaway view:
    the second save captures it as the state to restore and puts it back for good.
    """
    from agno.session import TeamSession
    from agno.team import _storage as team_storage
    from agno.team._session import asave_session

    worker = Agent(name="Worker", id="worker", telemetry=False)
    team = Team(name="Root", id="root", members=[worker], telemetry=False)
    team.db = object()  # only truthiness is read; the upsert is stubbed below

    completed = RunOutput(run_id="m1", agent_id="worker", status=RunStatus.completed)
    team_run = TeamRunOutput(run_id="t1", team_id="root", member_responses=[completed])
    session = TeamSession(session_id="s1", team_id="root", runs=[team_run])

    async def _slow_upsert(team, session):
        await asyncio.sleep(0.01)

    monkeypatch.setattr(team_storage, "_aupsert_session", _slow_upsert)
    monkeypatch.setattr("agno.team._init._has_async_db", lambda t: True)

    await asyncio.gather(asave_session(team, session), asave_session(team, session))

    assert session.runs[0].member_responses == [completed], (
        "the live session lost its member responses to the storage view"
    )


@pytest.mark.asyncio
async def test_a_run_finishing_during_an_async_save_is_not_discarded(monkeypatch):
    """A concurrent upsert_run must not land in the throwaway view and vanish."""
    from agno.session import TeamSession
    from agno.team import _storage as team_storage
    from agno.team._session import asave_session

    worker = Agent(name="Worker", id="worker", telemetry=False)
    team = Team(name="Root", id="root", members=[worker], telemetry=False)
    team.db = object()

    run_a = TeamRunOutput(run_id="run-a", team_id="root", session_id="s")
    run_a.member_responses = []
    session = TeamSession(session_id="s", team_id="root", runs=[run_a])

    async def _slow_upsert(team, session):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(team_storage, "_aupsert_session", _slow_upsert)
    monkeypatch.setattr("agno.team._init._has_async_db", lambda t: True)

    save = asyncio.create_task(asave_session(team, session))
    await asyncio.sleep(0.01)  # land inside the DB-write window

    run_b = TeamRunOutput(run_id="run-b", team_id="root", session_id="s")
    run_b.member_responses = []
    session.upsert_run(run_b)

    await save

    ids = [r.run_id for r in session.runs or []]
    assert "run-b" in ids, f"the concurrently added run was dropped by the restore; runs={ids}"


# ---------------------------------------------------------------------------
# Round 11: a refusal must arrive before any member has executed
# ---------------------------------------------------------------------------


def _build_dup_leaf_org(db: SqliteDb, resuming: bool, break_right_leaf: bool = False) -> Team:
    """Two sub-teams, each delegating to a leaf named 'dup'.

    With break_right_leaf the right sub-team's leaf has been renamed, which is
    what a deploy landing while a run sits paused looks like: the stored run
    still names 'dup', so the right sub-team can no longer route its share.
    Without a preflight that refusal surfaces only once the right sub-team's
    own continue is under way — after the left sub-team has sent its email.
    """

    def make_subteam(side: str, send_tool, to: str, leaf_id: str) -> Team:
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
        return Team(
            name=f"{side} Team",
            id=f"{side}-team",
            model=_ScriptedModel(f"m-{side}", sub_script),
            members=[
                Agent(
                    name="Dup",
                    id=leaf_id,
                    model=_ScriptedModel(f"m-agent-{side}", agent_script),
                    tools=[send_tool],
                    db=db,
                    telemetry=False,
                )
            ],
            db=db,
            telemetry=False,
        )

    leader_turn = (
        "tools",
        [
            ("delegate_task_to_member", {"member_id": "left-team", "task": "send left"}, "tc-outer-left"),
            ("delegate_task_to_member", {"member_id": "right-team", "task": "send right"}, "tc-outer-right"),
        ],
    )
    return Team(
        name="Org Team",
        id="org-team",
        model=_ScriptedModel(
            "m-outer", [("content", "All done.")] if resuming else [leader_turn, ("content", "All done.")]
        ),
        members=[
            make_subteam("left", left_send_email, "left@example.com", "dup"),
            make_subteam("right", right_send_email, "right@example.com", "renamed" if break_right_leaf else "dup"),
        ],
        db=db,
        telemetry=False,
    )


def test_a_subteam_that_cannot_route_refuses_before_a_sibling_executes(tmp_path):
    """The refusal says the run remains paused, so nothing may have run."""
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "preflight_sync.db")
    session_id = "s-preflight-sync"

    run1 = _build_dup_leaf_org(SqliteDb(db_file=db_file), resuming=False).run("Email both sides", session_id=session_id)
    assert run1.is_paused
    assert len(run1.requirements or []) == 2

    broken = _build_dup_leaf_org(SqliteDb(db_file=db_file), resuming=True, break_right_leaf=True)
    with pytest.raises(RunNotContinuableError):
        broken.continue_run(
            run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
        )

    assert _LEFT_EXECUTED == [], f"the refusal claims the run is untouched, but a sibling fired: {_LEFT_EXECUTED}"
    assert _RIGHT_EXECUTED == []


@pytest.mark.asyncio
async def test_a_subteam_that_cannot_route_refuses_before_a_sibling_executes_async(tmp_path):
    """Async twin: members are gathered, so without a preflight the refusal
    lands only after every sibling coroutine has already finished."""
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "preflight_async.db")
    session_id = "s-preflight-async"

    run1 = await _build_dup_leaf_org(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email both sides", session_id=session_id
    )
    assert run1.is_paused

    broken = _build_dup_leaf_org(SqliteDb(db_file=db_file), resuming=True, break_right_leaf=True)
    with pytest.raises(RunNotContinuableError):
        await broken.acontinue_run(
            run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
        )

    assert _LEFT_EXECUTED == [], f"the refusal claims the run is untouched, but a sibling fired: {_LEFT_EXECUTED}"
    assert _RIGHT_EXECUTED == []


@pytest.mark.asyncio
async def test_a_refused_continue_still_resumes_once_the_member_is_back(tmp_path):
    """The refusal must leave the run resumable, and the resume must run each
    approved tool exactly once."""
    _LEFT_EXECUTED.clear()
    _RIGHT_EXECUTED.clear()
    db_file = str(tmp_path / "preflight_retry.db")
    session_id = "s-preflight-retry"

    run1 = await _build_dup_leaf_org(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email both sides", session_id=session_id
    )
    assert run1.is_paused

    broken = _build_dup_leaf_org(SqliteDb(db_file=db_file), resuming=True, break_right_leaf=True)
    with pytest.raises(RunNotContinuableError):
        await broken.acontinue_run(
            run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
        )

    fixed = _build_dup_leaf_org(SqliteDb(db_file=db_file), resuming=True)
    run2 = await fixed.acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )

    assert run2.status == RunStatus.completed
    assert _LEFT_EXECUTED == ["left@example.com"], f"the approved tool did not run exactly once: {_LEFT_EXECUTED}"
    assert _RIGHT_EXECUTED == ["right@example.com"]


def test_preflight_does_not_disturb_a_healthy_nested_continue(tmp_path):
    """The extra resolution pass must stay invisible when everything resolves."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "preflight_healthy.db")
    session_id = "s-preflight-healthy"

    run1 = _build_nested_team(SqliteDb(db_file=db_file), resuming=False).run("Send it", session_id=session_id)
    assert run1.is_paused

    run2 = _build_nested_team(SqliteDb(db_file=db_file), resuming=True).continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )

    assert not run2.is_paused
    assert _EXECUTED == ["a@example.com"], f"the healthy nested continue must still run its tool once: {_EXECUTED}"


# ---------------------------------------------------------------------------
# Round 11: an unresolved member requirement re-pauses; a refused background
# continue is reported
# ---------------------------------------------------------------------------


@tool(name="file_expense", requires_user_input=True, user_input_fields=["approver"])
def file_expense(amount: str, approver: str) -> str:
    _EXECUTED.append(f"{amount}:{approver}")
    return f"filed {amount} with {approver}"


def _build_user_input_member_team(db: SqliteDb, resuming: bool) -> Team:
    """A member whose gated tool needs a field the model did not fill."""
    agent_script = (
        [("content", "Filed.")]
        if resuming
        else [("tool", "file_expense", {"amount": "900"}, "tc-expense"), ("content", "Filed.")]
    )
    leader_script = (
        [("content", "All done.")]
        if resuming
        else [
            ("tool", "delegate_task_to_member", {"member_id": "filer", "task": "file it"}, "tc-deleg"),
            ("content", "All done."),
        ]
    )
    return Team(
        name="Finance Team",
        id="finance-team",
        model=_ScriptedModel("m-leader", leader_script),
        members=[
            Agent(
                name="Filer",
                id="filer",
                model=_ScriptedModel("m-filer", agent_script),
                tools=[file_expense],
                db=db,
                telemetry=False,
            )
        ],
        db=db,
        telemetry=False,
    )


def test_an_unresolved_member_requirement_repauses_instead_of_executing(tmp_path):
    """The team-level lane re-pauses its own unresolved requirements; the member
    lane must too, rather than run the gated tool on input nobody supplied."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "unresolved_member.db")
    session_id = "s-unresolved-member"

    run1 = _build_user_input_member_team(SqliteDb(db_file=db_file), resuming=False).run(
        "File the expense", session_id=session_id
    )
    assert run1.is_paused
    assert not run1.requirements[0].is_resolved(), "the requested field is unfilled, so the pause is unresolved"

    # The client sends the payload straight back without filling the field.
    untouched = [RunRequirement.from_dict(r.to_dict()) for r in run1.requirements or []]
    run2 = _build_user_input_member_team(SqliteDb(db_file=db_file), resuming=True).continue_run(
        run_id=run1.run_id, session_id=session_id, requirements=untouched
    )

    assert _EXECUTED == [], f"a gated tool ran on input nobody supplied: {_EXECUTED}"
    assert run2.is_paused, "an unresolved member requirement must leave the run paused"


@pytest.mark.asyncio
async def test_an_unresolved_member_requirement_repauses_instead_of_executing_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "unresolved_member_async.db")
    session_id = "s-unresolved-member-async"

    run1 = await _build_user_input_member_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "File the expense", session_id=session_id
    )
    assert run1.is_paused

    untouched = [RunRequirement.from_dict(r.to_dict()) for r in run1.requirements or []]
    run2 = await _build_user_input_member_team(SqliteDb(db_file=db_file), resuming=True).acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=untouched
    )

    assert _EXECUTED == [], f"a gated tool ran on input nobody supplied: {_EXECUTED}"
    assert run2.is_paused, "an unresolved member requirement must leave the run paused"


async def _drain_background_tasks() -> None:
    """The SSE generator returns when the producer pushes its sentinel, which
    happens before set_run_completed; wait for the detached task itself."""
    from agno.team._run import _background_tasks

    for _ in range(300):
        if not [t for t in list(_background_tasks) if not t.done()]:
            return
        await asyncio.sleep(0.01)


def _unbindable_payload(requirements):
    payload = _wire_requirements(requirements)
    payload[0].id = "not-a-stored-requirement-id"
    payload[0].tool_execution.tool_call_id = "tc-bogus"
    return payload


@pytest.mark.asyncio
async def test_background_continue_reports_a_refusal_to_the_client(tmp_path):
    """A refused continue must not reach the caller as an empty, successful stream."""
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "bg_refusal.db")
    session_id = "s-bg-refusal"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    chunks = []
    async for chunk in team2.acontinue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_unbindable_payload(run1.requirements),
        stream=True,
        stream_events=True,
        background=True,
    ):
        chunks.append(chunk)
    await _drain_background_tasks()

    assert _EXECUTED == [], "a refused continue must not execute the gated tool"
    assert [c for c in chunks if "RunError" in c], f"the refusal reached the client as an empty stream: {chunks!r}"
    buffer_status = event_buffer.get_run_status(run1.run_id)
    assert isinstance(buffer_status, RunStatus), (
        f"the buffer must hold a RunStatus, got {type(buffer_status)}: /resume formats it with .value"
    )
    assert buffer_status == RunStatus.paused, (
        f"a refused continue of a paused run must be recorded as paused, got {buffer_status!r}"
    )
    db_status = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status
    assert db_status == RunStatus.paused


@pytest.mark.asyncio
async def test_background_continue_refusal_keeps_the_run_resumable(tmp_path):
    """The run_response shape persisted ERROR over the pause the refusal was
    protecting, leaving nothing to resume."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "bg_refusal_obj.db")
    session_id = "s-bg-refusal-obj"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    async for _ in team2.acontinue_run(
        run_response=run1,
        session_id=session_id,
        requirements=_unbindable_payload(run1.requirements),
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()

    db_status = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status
    assert db_status == RunStatus.paused, (
        f"the refusal clobbered the paused run to {db_status!r}; it can no longer be resumed"
    )


@pytest.mark.asyncio
async def test_a_stale_run_response_cannot_resurrect_a_finished_run(tmp_path):
    """A caller-held run object outlives the run it describes.

    If it still reads as paused after someone else finished the run, writing it
    back would republish the finished run as a pending approval — and its gated
    tool could then be approved a second time.
    """
    _EXECUTED.clear()
    db_file = str(tmp_path / "stale_takeover.db")
    session_id = "s-stale-takeover"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused
    good = _wire_requirements(run1.requirements)

    done = await _build_flat_team(SqliteDb(db_file=db_file), resuming=True).acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert done.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]

    # The caller still holds the stale paused object from before that
    # completion, and sends a payload that would bind: only the guard stands
    # between this approve and a second execution.
    team3 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    with pytest.raises(RunNotContinuableError):
        async for _ in team3.acontinue_run(
            run_response=run1,
            session_id=session_id,
            requirements=_wire_requirements(run1.requirements),
            stream=True,
            stream_events=True,
            background=True,
        ):
            pass
    await _drain_background_tasks()

    status = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status
    assert status == RunStatus.completed, f"a finished run was resurrected to {status!r}"

    team4 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    retry = await team4.acontinue_run(run_id=run1.run_id, session_id=session_id, requirements=good)
    assert retry.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"], f"the gated tool ran a second time: {_EXECUTED}"


@pytest.mark.asyncio
async def test_a_stale_run_response_cannot_resurrect_a_cancelled_run(tmp_path):
    """A stale paused object over a cancelled stored run is refused up front.

    Without the guard, step 1 writes RUNNING over the cancellation and the
    continue then executes the gated tool on a run an operator cancelled.
    """
    _EXECUTED.clear()
    db_file = str(tmp_path / "stale_cancelled.db")
    session_id = "s-stale-cancelled"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    db = SqliteDb(db_file=db_file)
    session = db.get_session(session_id=session_id, session_type="team")
    for r in session.runs or []:
        if r.run_id == run1.run_id:
            r.status = RunStatus.cancelled
    db.upsert_session(session)

    # The caller still holds the paused object from before the cancellation and
    # sends a payload that would bind.
    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    with pytest.raises(RunNotContinuableError):
        async for _ in team2.acontinue_run(
            run_response=run1,
            session_id=session_id,
            requirements=_wire_requirements(run1.requirements),
            stream=True,
            stream_events=True,
            background=True,
        ):
            pass
    await _drain_background_tasks()

    status = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status
    assert status == RunStatus.cancelled, f"a cancelled run came back as {status!r}"
    assert _EXECUTED == [], f"the gated tool ran on a cancelled run: {_EXECUTED}"


@pytest.mark.asyncio
async def test_a_refused_continue_restores_the_status_it_replaced(tmp_path):
    """The refusal must put back whatever it took over, not a blanket pause.

    An errored run handed a refused continue has to come out errored. Coming
    out paused would turn a terminal state into a resumable approval.
    """
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "restore_status.db")
    session_id = "s-restore-status"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    db = SqliteDb(db_file=db_file)
    session = db.get_session(session_id=session_id, session_type="team")
    for r in session.runs or []:
        if r.run_id == run1.run_id:
            r.status = RunStatus.error
    db.upsert_session(session)

    # The caller still holds the paused object from before the failure.
    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    async for _ in team2.acontinue_run(
        run_response=run1,
        session_id=session_id,
        requirements=_unbindable_payload(run1.requirements),
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()

    status = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status
    assert status == RunStatus.error, f"an errored run came back as {status!r} after a refused continue"
    buffer_status = event_buffer.get_run_status(run1.run_id)
    assert isinstance(buffer_status, RunStatus) and buffer_status == RunStatus.error, (
        f"the buffer must report the restored status, got {buffer_status!r}"
    )
    assert _EXECUTED == []


@pytest.mark.asyncio
async def test_the_event_buffer_does_not_advertise_a_cancelled_run_as_paused(tmp_path):
    """Reconnecting clients read the buffer, not the DB.

    Recording a blanket PAUSED for any refusal tells every one of them that a
    cancelled run is waiting on an approval.
    """
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "buffer_status.db")
    session_id = "s-buffer-status"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    db = SqliteDb(db_file=db_file)
    session = db.get_session(session_id=session_id, session_type="team")
    for r in session.runs or []:
        if r.run_id == run1.run_id:
            r.status = RunStatus.cancelled
    db.upsert_session(session)

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    async for _ in team2.acontinue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_unbindable_payload(run1.requirements),
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()

    buffer_status = event_buffer.get_run_status(run1.run_id)
    assert isinstance(buffer_status, RunStatus), (
        f"the buffer must hold a RunStatus, got {type(buffer_status)}: /resume formats it with .value"
    )
    assert buffer_status == RunStatus.cancelled, (
        f"the buffer must report the cancelled run as cancelled, got {buffer_status!r}; advertising it as "
        "paused tells every reconnecting client it is resumable"
    )
    assert [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status == RunStatus.cancelled


@pytest.mark.asyncio
async def test_a_refusal_over_a_running_run_never_advertises_running(tmp_path):
    """A refusal while another continue holds the run must not record RUNNING
    as the buffer's final status: /resume treats RUNNING as in-flight and waits
    forever on a producer that already exited."""
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "running_refusal.db")
    session_id = "s-running-refusal"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    db = SqliteDb(db_file=db_file)
    session = db.get_session(session_id=session_id, session_type="team")
    for r in session.runs or []:
        if r.run_id == run1.run_id:
            r.status = RunStatus.running
    db.upsert_session(session)

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    async for _ in team2.acontinue_run(
        run_response=run1,
        session_id=session_id,
        requirements=_unbindable_payload(run1.requirements),
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()

    buffer_status = event_buffer.get_run_status(run1.run_id)
    assert isinstance(buffer_status, RunStatus) and buffer_status == RunStatus.paused, (
        f"the buffer's final status is {buffer_status!r}; RUNNING makes every reconnecting client hang"
    )
    assert _EXECUTED == []


@pytest.mark.asyncio
async def test_a_refused_continue_of_a_run_missing_from_the_session_stays_resumable(tmp_path):
    """When the stored session has no entry for the run, the caller's object is
    the only record of the pre-continue state; a refusal must restore it, not
    leave the RUNNING marker step 1 wrote."""
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "missing_run.db")
    session_id = "s-missing-run"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    db = SqliteDb(db_file=db_file)
    session = db.get_session(session_id=session_id, session_type="team")
    session.runs = [r for r in session.runs or [] if r.run_id != run1.run_id]
    db.upsert_session(session)

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    async for _ in team2.acontinue_run(
        run_response=run1,
        session_id=session_id,
        requirements=_unbindable_payload(run1.requirements),
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()

    stored = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0]
    assert stored.status == RunStatus.paused, (
        f"the refusal left the run advertised as {stored.status!r}; a RUNNING orphan can never be resumed"
    )
    buffer_status = event_buffer.get_run_status(run1.run_id)
    assert isinstance(buffer_status, RunStatus) and buffer_status == RunStatus.paused, (
        f"the buffer says {buffer_status!r} while the DB says paused; reconnecting clients read the buffer"
    )

    team3 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    done = await team3.acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert done.status == RunStatus.completed
    assert _EXECUTED == ["a@example.com"]


@pytest.mark.asyncio
async def test_a_refusal_does_not_erase_a_concurrently_persisted_run(tmp_path):
    """The refusal write-back must not save the step-1 session snapshot: a run
    another request persisted between step 1 and the refusal has to survive."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "concurrent_refusal.db")
    session_id = "s-concurrent-refusal"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    team3 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)

    async def refused_continue():
        async for _ in team2.acontinue_run(
            run_response=run1,
            session_id=session_id,
            requirements=_unbindable_payload(run1.requirements),
            stream=True,
            stream_events=True,
            background=True,
        ):
            pass

    async def second_ask():
        return await team3.arun("second ask", session_id=session_id)

    _, second = await asyncio.gather(refused_continue(), second_ask())
    await _drain_background_tasks()

    runs = _reload_runs(db_file, session_id)
    ids = [r.run_id for r in runs]
    assert second.run_id in ids, f"the refusal write-back erased the concurrently persisted run; DB holds {ids}"
    assert [r for r in runs if r.run_id == run1.run_id][0].status == RunStatus.paused


@pytest.mark.asyncio
async def test_a_background_repause_is_not_advertised_as_completed(tmp_path):
    """A background continue that re-pauses must record PAUSED in the event
    buffer. This is the run_id-only shape AgentOS uses, where the producer has
    no caller-supplied run object to read the status from."""
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "repause_buffer.db")
    session_id = "s-repause-buffer"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    # Bindable payload without a confirmation: the continue binds, the
    # requirement stays unresolved, and the run re-pauses.
    unconfirmed = [RunRequirement.from_dict(r.to_dict()) for r in run1.requirements or []]
    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    async for _ in team2.acontinue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=unconfirmed,
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()

    assert _EXECUTED == []
    db_status = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status
    assert db_status == RunStatus.paused
    buffer_status = event_buffer.get_run_status(run1.run_id)
    assert isinstance(buffer_status, RunStatus) and buffer_status == RunStatus.paused, (
        f"the DB says paused but the buffer says {buffer_status!r}; a reconnecting client would stop "
        "waiting for the approval"
    )


@pytest.mark.asyncio
async def test_an_unknown_run_id_raises_run_not_found_in_the_async_non_stream_lane(tmp_path):
    """All four continue lanes must surface an unknown run id as
    RunNotFoundError; the async non-stream lane used to crash with
    AttributeError instead."""
    db_file = str(tmp_path / "unknown_run.db")
    team = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    with pytest.raises(RunNotFoundError):
        await team.acontinue_run(run_id="no-such-run", session_id="s-unknown-run")


def _build_own_tool_flat_team(db: SqliteDb, resuming: bool) -> Team:
    """Top-level team with its own gated tool plus a gated member tool, so a
    pause carries one team-level and one member-level requirement."""
    script = (
        [("content", "All done.")]
        if resuming
        else [
            (
                "tools",
                [
                    ("delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-deleg"),
                    ("publish", {"item": "release"}, "tc-pub"),
                ],
            ),
            ("content", "All done."),
        ]
    )
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel("m-leader", script),
        tools=[publish],
        members=[_emailer_agent(db, resuming)],
        db=db,
        telemetry=False,
    )


def test_a_sync_stream_cancel_keeps_team_level_requirements(tmp_path):
    """A cancel that lands during member routing must persist the run with its
    team-level requirements still attached, the same set the async stream
    persists."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "sync_cancel_reqs.db")
    session_id = "s-sync-cancel-reqs"

    team1 = _build_own_tool_flat_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Publish the release and email a@example.com", session_id=session_id)
    assert run1.is_paused
    names = sorted(r.tool_execution.tool_name for r in run1.requirements or [])
    assert names == ["publish", "send_email"], names

    team2 = _build_own_tool_flat_team(SqliteDb(db_file=db_file), resuming=True)
    stream = team2.continue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements(run1.requirements),
        stream=True,
        stream_events=True,
        yield_run_output=True,
    )
    # Cancel before iterating: the cancel lands inside member routing.
    Team.cancel_run(run1.run_id)

    final = None
    for ev in stream:
        if isinstance(ev, TeamRunOutput):
            final = ev

    assert final is not None and final.status == RunStatus.cancelled
    final_names = sorted(r.tool_execution.tool_name for r in (final.requirements or []))
    assert "publish" in final_names, f"the caller's run object lost the team-level requirement: {final_names}"
    stored = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0]
    stored_names = sorted(r.tool_execution.tool_name for r in (stored.requirements or []))
    assert "publish" in stored_names, f"the stored run lost the team-level requirement: {stored_names}"


_NOTES: List[Any] = []


@tool(requires_user_input=True, user_input_fields=["to"])
@approval(type="required")
def send_note(to: str, body: str) -> str:
    _NOTES.append((to, body))
    return f"note to {to}: {body}"


@tool(external_execution=True)
@approval(type="required")
def run_export(target: str) -> str:
    raise AssertionError("externally executed tools never run in-process")


_PINGS: List[Any] = []


@tool(requires_user_input=True)
@approval(type="required")
def run_ping() -> str:
    _PINGS.append("ping")
    return "pong"


_APPROVAL_TOOL_ARGS: Dict[str, Dict[str, Any]] = {
    "send_note": {"body": "hi"},
    "run_export": {"target": "reports"},
    "run_ping": {},
}


def _approval_team(db: SqliteDb, resuming: bool, member_tool=None) -> Team:
    member_tool = member_tool if member_tool is not None else send_note
    tool_name = member_tool.name
    tool_args = _APPROVAL_TOOL_ARGS[tool_name]
    agent = Agent(
        name="Noter",
        id="noter",
        model=_ScriptedModel(
            "m-noter",
            [("content", "Sent.")] if resuming else [("tool", tool_name, tool_args, "tc-note"), ("content", "Sent.")],
        ),
        tools=[member_tool],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Notes Team",
        id="notes-team",
        model=_ScriptedModel(
            "m-lead",
            [("content", "All done.")]
            if resuming
            else [
                ("tool", "delegate_task_to_member", {"member_id": "noter", "task": "note it"}, "tc-deleg"),
                ("content", "All done."),
            ],
        ),
        members=[agent],
        db=db,
        telemetry=False,
    )


def _resolve_required_approval(db: SqliteDb, run1, resolution_data, status: str = "approved") -> None:
    approvals, _ = db.get_approvals(run_id=run1.run_id, approval_type="required", limit=5)
    if not approvals:
        for r in run1.requirements or []:
            aid = getattr(r.tool_execution, "approval_id", None)
            if aid:
                record = db.get_approval(aid)
                if record:
                    approvals = [record]
                    break
    assert approvals, "no approval record was created for the paused run"
    db.update_approval(approvals[0]["id"], status=status, resolution_data=resolution_data)


def test_an_admin_approved_member_user_input_run_completes(tmp_path):
    """An approval resolved out of band with the missing input values must let a
    continue with no requirements payload finish the run."""
    _NOTES.clear()
    db_file = str(tmp_path / "admin_approval.db")
    session_id = "s-admin-approval"

    db = SqliteDb(db_file=db_file)
    run1 = _approval_team(db, resuming=False).run("Send a note", session_id=session_id)
    assert run1.is_paused

    _resolve_required_approval(db, run1, {"values": {"to": "bob@example.com"}})

    team2 = _approval_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.completed, f"admin-approved run did not complete: {run2.status}"
    assert _NOTES == [("bob@example.com", "hi")], _NOTES


@pytest.mark.asyncio
async def test_an_admin_approved_member_user_input_run_completes_async(tmp_path):
    _NOTES.clear()
    db_file = str(tmp_path / "admin_approval_async.db")
    session_id = "s-admin-approval-async"

    db = SqliteDb(db_file=db_file)
    run1 = await _approval_team(db, resuming=False).arun("Send a note", session_id=session_id)
    assert run1.is_paused

    _resolve_required_approval(db, run1, {"values": {"to": "bob@example.com"}})

    team2 = _approval_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = await team2.acontinue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.completed, f"admin-approved run did not complete: {run2.status}"
    assert _NOTES == [("bob@example.com", "hi")], _NOTES


def test_an_admin_approved_external_execution_member_run_completes(tmp_path):
    """An approval resolved with the external tool's result must let the
    continue finish instead of re-pausing on needs_external_execution."""
    db_file = str(tmp_path / "admin_approval_ext.db")
    session_id = "s-admin-approval-ext"

    db = SqliteDb(db_file=db_file)
    run1 = _approval_team(db, resuming=False, member_tool=run_export).run("Export it", session_id=session_id)
    assert run1.is_paused

    _resolve_required_approval(db, run1, {"result": "EXPORT_OK"})

    team2 = _approval_team(SqliteDb(db_file=db_file), resuming=True, member_tool=run_export)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.completed, f"admin-approved run did not complete: {run2.status}"


def test_an_approval_without_values_keeps_the_run_paused(tmp_path):
    """An approval that supplies none of the required input values must not let
    the gated tool run with None arguments; the run asks again."""
    _NOTES.clear()
    db_file = str(tmp_path / "admin_approval_empty.db")
    session_id = "s-admin-approval-empty"

    db = SqliteDb(db_file=db_file)
    run1 = _approval_team(db, resuming=False).run("Send a note", session_id=session_id)
    assert run1.is_paused

    _resolve_required_approval(db, run1, None)

    team2 = _approval_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.paused, f"an unfilled approval let the run reach {run2.status}"
    assert _NOTES == [], f"the gated tool ran without its input values: {_NOTES}"


def test_a_rejected_member_approval_skips_the_tool_and_completes(tmp_path):
    """A rejected approval must settle the requirement: the tool is skipped and
    the run finishes instead of re-pausing forever with nothing left to change."""
    _NOTES.clear()
    db_file = str(tmp_path / "admin_approval_rejected.db")
    session_id = "s-admin-approval-rejected"

    db = SqliteDb(db_file=db_file)
    run1 = _approval_team(db, resuming=False).run("Send a note", session_id=session_id)
    assert run1.is_paused

    _resolve_required_approval(db, run1, None, status="rejected")

    team2 = _approval_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.completed, f"a rejected approval left the run {run2.status}"
    assert _NOTES == [], f"the rejected tool executed: {_NOTES}"


def test_an_approved_zero_field_user_input_tool_completes(tmp_path):
    """An approved requirement with no input fields to fill is resolved; the
    empty schema must not read as 'not fully filled'."""
    _PINGS.clear()
    db_file = str(tmp_path / "admin_approval_zero.db")
    session_id = "s-admin-approval-zero"

    db = SqliteDb(db_file=db_file)
    run1 = _approval_team(db, resuming=False, member_tool=run_ping).run("Ping it", session_id=session_id)
    assert run1.is_paused

    _resolve_required_approval(db, run1, None)

    team2 = _approval_team(SqliteDb(db_file=db_file), resuming=True, member_tool=run_ping)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.completed, f"an approved zero-field tool left the run {run2.status}"
    assert _PINGS == ["ping"], _PINGS


_DEPLOYS: List[Any] = []


@tool(requires_confirmation=True)
@approval(type="required")
def deploy(target: str) -> str:
    _DEPLOYS.append(target)
    return f"deployed {target}"


def _team_level_approval_team(db: SqliteDb, resuming: bool) -> Team:
    return Team(
        name="Deploy Team",
        id="deploy-team",
        model=_ScriptedModel(
            "m-deploy",
            [("content", "Done.")]
            if resuming
            else [("tool", "deploy", {"target": "prod"}, "tc-dep"), ("content", "Done.")],
        ),
        tools=[deploy],
        members=[_emailer_agent(db, resuming)],
        db=db,
        telemetry=False,
    )


def test_a_team_level_approval_resolves_after_a_session_reload(tmp_path):
    """After a reload, run.tools and the requirement hold distinct copies of the
    gated tool call; the approved resolution must land on both."""
    _DEPLOYS.clear()
    db_file = str(tmp_path / "team_level_approval.db")
    session_id = "s-team-level-approval"

    db = SqliteDb(db_file=db_file)
    run1 = _team_level_approval_team(db, resuming=False).run("Deploy prod", session_id=session_id)
    assert run1.is_paused

    _resolve_required_approval(db, run1, None)

    team2 = _team_level_approval_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.completed, f"the approved team-level run came back {run2.status}"
    assert _DEPLOYS == ["prod"], _DEPLOYS


def test_sync_requirements_after_approval_mirrors_the_resolution():
    """Unit contract of _sync_requirements_after_approval: every field the
    requirement's needs_* properties read is mirrored from the applied tools."""
    from agno.run.approval import _sync_requirements_after_approval
    from agno.tools.function import UserInputField

    # Approved confirmation tool: the requirement-side confirmation is set.
    te = ToolExecution(
        tool_call_id="tc-c", tool_name="deploy", requires_confirmation=True, confirmed=True, approval_type="required"
    )
    req = RunRequirement(tool_execution=te)
    holder = MagicMock(requirements=[req])
    _sync_requirements_after_approval(holder, "approved")
    assert req.confirmation is True

    # Approved user-input tool with a DISTINCT schema copy: values are copied
    # onto the requirement's schema and the tool reads answered.
    te2 = ToolExecution(
        tool_call_id="tc-u",
        tool_name="send_note",
        requires_user_input=True,
        approval_type="required",
        user_input_schema=[UserInputField(name="to", field_type=str, value="bob@example.com")],
    )
    req2 = RunRequirement(tool_execution=te2)
    req2.user_input_schema = [UserInputField(name="to", field_type=str, value=None)]
    holder2 = MagicMock(requirements=[req2])
    _sync_requirements_after_approval(holder2, "approved")
    assert te2.answered is True
    assert [f.value for f in req2.user_input_schema] == ["bob@example.com"]
    assert req2.is_resolved()

    # Rejected user-input tool: settled through the reject lane, never answered
    # for execution.
    te3 = ToolExecution(
        tool_call_id="tc-r",
        tool_name="send_note",
        requires_user_input=True,
        approval_type="required",
        user_input_schema=[UserInputField(name="to", field_type=str, value=None)],
    )
    req3 = RunRequirement(tool_execution=te3)
    holder3 = MagicMock(requirements=[req3])
    _sync_requirements_after_approval(holder3, "rejected")
    assert te3.requires_user_input is False
    assert te3.requires_confirmation is True and te3.confirmed is False
    assert req3.confirmation is False
    assert req3.is_resolved()


@pytest.mark.asyncio
async def test_a_reread_cancelled_run_is_refused_too(tmp_path):
    """A caller who re-reads a cancelled run and continues with the fresh
    object gets the same refusal the run_id lane gives."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "reread_cancelled.db")
    session_id = "s-reread-cancelled"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    db = SqliteDb(db_file=db_file)
    session = db.get_session(session_id=session_id, session_type="team")
    for r in session.runs or []:
        if r.run_id == run1.run_id:
            r.status = RunStatus.cancelled
    db.upsert_session(session)

    fresh = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0]
    assert fresh.is_paused is False

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    with pytest.raises(RunNotContinuableError):
        async for _ in team2.acontinue_run(
            run_response=fresh,
            session_id=session_id,
            requirements=_wire_requirements(run1.requirements),
            stream=True,
            stream_events=True,
            background=True,
        ):
            pass
    await _drain_background_tasks()

    status = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status
    assert status == RunStatus.cancelled, f"a cancelled run came back as {status!r}"
    assert _EXECUTED == [], f"the gated tool ran on a cancelled run: {_EXECUTED}"


@pytest.mark.asyncio
async def test_a_completed_run_object_cannot_be_continued_in_place(tmp_path):
    """A second background continue with the (now completed) caller object must
    refuse, not edit the finished run in place and fire its tool again."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "completed_in_place.db")
    session_id = "s-completed-in-place"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused
    good = _wire_requirements(run1.requirements)

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    async for _ in team2.acontinue_run(
        run_response=run1,
        session_id=session_id,
        requirements=good,
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()
    assert _EXECUTED == ["a@example.com"]

    team3 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    with pytest.raises(RunNotContinuableError):
        async for _ in team3.acontinue_run(
            run_response=run1,
            session_id=session_id,
            requirements=_wire_requirements(run1.requirements),
            stream=True,
            stream_events=True,
            background=True,
        ):
            pass
    await _drain_background_tasks()
    assert _EXECUTED == ["a@example.com"], f"the gated tool ran a second time: {_EXECUTED}"


@pytest.mark.asyncio
async def test_a_background_fork_does_not_restamp_the_original_runs_buffer(tmp_path):
    """A fork produces a run with a different id; the forked run's status must
    not land under the original run's event-buffer key."""
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "fork_buffer.db")
    session_id = "s-fork-buffer"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused
    await _build_flat_team(SqliteDb(db_file=db_file), resuming=True).acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status == RunStatus.completed

    # A resuming=False team replays the delegation, so the fork pauses on its
    # own approval.
    async for _ in _build_flat_team(SqliteDb(db_file=db_file), resuming=False).acontinue_run(
        run_id=run1.run_id,
        session_id=session_id,
        fork=True,
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()

    buffer_status = event_buffer.get_run_status(run1.run_id)
    assert buffer_status == RunStatus.completed, (
        f"the original completed run's buffer entry took the fork's status: {buffer_status!r}"
    )


@pytest.mark.asyncio
async def test_a_run_id_auto_fork_does_not_restamp_the_original_runs_buffer(tmp_path):
    """A background continue of a completed run by run_id auto-forks; the
    auto-fork's status must not land under the original run's buffer key."""
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "auto_fork_buffer.db")
    session_id = "s-auto-fork-buffer"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused
    await _build_flat_team(SqliteDb(db_file=db_file), resuming=True).acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status == RunStatus.completed

    # No fork flag: the dispatcher auto-forks the completed run, and the
    # resuming=False team replays the delegation so the fork pauses.
    async for _ in _build_flat_team(SqliteDb(db_file=db_file), resuming=False).acontinue_run(
        run_id=run1.run_id,
        session_id=session_id,
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()

    buffer_status = event_buffer.get_run_status(run1.run_id)
    assert buffer_status == RunStatus.completed, (
        f"the original completed run's buffer entry took the auto-fork's status: {buffer_status!r}"
    )


class _BoomModel(_ScriptedModel):
    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("leader boom")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("leader boom")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("leader boom")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("leader boom")
        yield


@pytest.mark.asyncio
async def test_a_failed_background_continue_is_not_advertised_as_completed(tmp_path):
    """A background continue whose team leader fails must record ERROR in the
    event buffer, matching the DB and the error event the client received."""
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "leader_error.db")
    session_id = "s-leader-error"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    team2.model = _BoomModel("m-leader", [("content", "All done.")])

    chunks = []
    async for chunk in team2.acontinue_run(
        run_id=run1.run_id,
        session_id=session_id,
        requirements=_wire_requirements(run1.requirements),
        stream=True,
        stream_events=True,
        background=True,
    ):
        chunks.append(chunk)
    await _drain_background_tasks()

    assert [c for c in chunks if "TeamRunError" in c], "the failure must reach the client"
    db_status = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status
    assert db_status == RunStatus.error, db_status
    buffer_status = event_buffer.get_run_status(run1.run_id)
    assert buffer_status == RunStatus.error, (
        f"the DB says {db_status!r} but reconnecting clients are told {buffer_status!r}"
    )


@pytest.mark.asyncio
async def test_a_cached_team_refusal_still_restores_the_stored_status(tmp_path):
    """With cache_session the handler's session read can hand back the very
    object step 1 wrote; the restore must still land in the DB."""
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "cached_refusal.db")
    session_id = "s-cached-refusal"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True, cache_session=True)
    async for _ in team2.acontinue_run(
        run_response=run1,
        session_id=session_id,
        requirements=_unbindable_payload(run1.requirements),
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()

    stored = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0]
    assert stored.status == RunStatus.paused, (
        f"the cached-team refusal left the stored run {stored.status!r}; it can no longer be resumed"
    )
    buffer_status = event_buffer.get_run_status(run1.run_id)
    assert isinstance(buffer_status, RunStatus) and buffer_status == RunStatus.paused


@pytest.mark.asyncio
async def test_a_refusal_does_not_overwrite_a_run_another_request_finished(tmp_path):
    """The restore writes only over step 1's RUNNING marker: a run another
    request completed during the window must stay completed."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "cas_window.db")
    session_id = "s-cas-window"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    async def _finish_then_refuse(*args: Any, **kwargs: Any):
        db2 = SqliteDb(db_file=db_file)
        session = db2.get_session(session_id=session_id, session_type="team")
        for r in session.runs or []:
            if r.run_id == run1.run_id:
                r.status = RunStatus.completed
        db2.upsert_session(session)
        raise RunNotContinuableError("another request finished this run")
        yield

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    with patch("agno.team._run._acontinue_run_stream", new=_finish_then_refuse):
        async for _ in team2.acontinue_run(
            run_response=run1,
            session_id=session_id,
            requirements=_unbindable_payload(run1.requirements),
            stream=True,
            stream_events=True,
            background=True,
        ):
            pass
    await _drain_background_tasks()

    status = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status
    assert status == RunStatus.completed, (
        f"the refusal stamped {status!r} over a run another request finished; its approval is live again"
    )


@pytest.mark.asyncio
async def test_a_read_failure_during_refusal_still_restores_the_run(tmp_path):
    """When the handler's session read fails, the restore falls back to the
    step-1 session instead of leaving the run advertised as RUNNING."""
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "read_failure.db")
    session_id = "s-read-failure"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    with patch("agno.team._storage._aread_session", new_callable=AsyncMock, return_value=None):
        async for _ in team2.acontinue_run(
            run_response=run1,
            session_id=session_id,
            requirements=_unbindable_payload(run1.requirements),
            stream=True,
            stream_events=True,
            background=True,
        ):
            pass
    await _drain_background_tasks()

    stored = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0]
    assert stored.status == RunStatus.paused, f"a failed session read left the run advertised as {stored.status!r}"
    assert event_buffer.get_run_status(run1.run_id) == RunStatus.paused


def test_paused_buffer_entries_are_reclaimed_after_the_cleanup_interval():
    """A pause can wait on an approval forever; its buffer entry must not pin
    memory for the process lifetime. A reclaimed entry is rebuilt by add_event
    when the run is continued."""
    from agno.os.managers import EventsBuffer

    buf = EventsBuffer(cleanup_interval=-1)
    buf.add_event("r-paused-reclaim", MagicMock())
    buf.set_run_completed("r-paused-reclaim", RunStatus.paused)
    buf.cleanup_runs()
    assert buf.get_run_status("r-paused-reclaim") is None, "the paused buffer entry was never reclaimed"
    assert "r-paused-reclaim" not in buf.run_metadata


_FIRED: List[str] = []


@tool(requires_confirmation=True)
@approval(type="required")
def alpha_action(target: str) -> str:
    _FIRED.append(f"alpha:{target}")
    return "alpha done"


@tool(requires_confirmation=True)
@approval(type="required")
def beta_action(target: str) -> str:
    _FIRED.append(f"beta:{target}")
    return "beta done"


def _two_member_approval_team(db: SqliteDb, resuming: bool, collide: bool = False) -> Team:
    """Two members, each pausing on its own approval-gated tool. With collide,
    both provider tool calls share one provider-local tool_call_id."""
    alpha_tcid = "call_1"
    beta_tcid = "call_1" if collide else "call_2"
    alpha = Agent(
        name="Alpha",
        id="alpha",
        model=_ScriptedModel(
            "m-alpha",
            [("content", "Alpha done.")]
            if resuming
            else [("tool", "alpha_action", {"target": "A"}, alpha_tcid), ("content", "Alpha done.")],
        ),
        tools=[alpha_action],
        db=db,
        telemetry=False,
    )
    beta = Agent(
        name="Beta",
        id="beta",
        model=_ScriptedModel(
            "m-beta",
            [("content", "Beta done.")]
            if resuming
            else [("tool", "beta_action", {"target": "B"}, beta_tcid), ("content", "Beta done.")],
        ),
        tools=[beta_action],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Ops Team",
        id="ops-team",
        model=_ScriptedModel(
            "m-lead",
            [("content", "All done.")]
            if resuming
            else [
                (
                    "tools",
                    [
                        ("delegate_task_to_member", {"member_id": "alpha", "task": "do alpha"}, "tc-d1"),
                        ("delegate_task_to_member", {"member_id": "beta", "task": "do beta"}, "tc-d2"),
                    ],
                ),
                ("content", "All done."),
            ],
        ),
        members=[alpha, beta],
        db=db,
        telemetry=False,
    )


def _approval_record_for_tool(db: SqliteDb, tool_name: str):
    records, _ = db.get_approvals(approval_type="required", limit=50)
    matches = [a for a in records if a["tool_name"] == tool_name]
    assert matches, f"no approval record for {tool_name}; records: {[a['tool_name'] for a in records]}"
    return matches[0]


def test_one_approval_does_not_resolve_a_sibling_members_tool(tmp_path):
    """Each member's gated tool is decided by ITS OWN approval record. With one
    record approved and the other pending, nothing may execute."""
    _FIRED.clear()
    db_file = str(tmp_path / "sibling_approvals.db")
    session_id = "s-sibling-approvals"

    db = SqliteDb(db_file=db_file)
    run1 = _two_member_approval_team(db, resuming=False).run("Do both", session_id=session_id)
    assert run1.is_paused
    records, _ = db.get_approvals(approval_type="required", limit=50)
    assert len(records) == 2, f"expected one approval record per paused member, got {len(records)}"

    db.update_approval(_approval_record_for_tool(db, "alpha_action")["id"], status="approved", resolution_data=None)

    team2 = _two_member_approval_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.paused, f"a pending sibling approval let the run reach {run2.status}"
    assert _FIRED == [], f"a tool executed while its own approval was pending: {_FIRED}"

    # Resolving the second record completes the run and fires both tools.
    db2 = SqliteDb(db_file=db_file)
    db2.update_approval(_approval_record_for_tool(db2, "beta_action")["id"], status="approved", resolution_data=None)
    team3 = _two_member_approval_team(SqliteDb(db_file=db_file), resuming=True)
    run3 = team3.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run3.status == RunStatus.completed, run3.status
    assert sorted(_FIRED) == ["alpha:A", "beta:B"], _FIRED


def test_a_rejected_sibling_does_not_block_or_get_run_by_anothers_approval(tmp_path):
    """Approve one member, reject the other: the approved tool runs, the
    rejected one is skipped, and the run completes."""
    _FIRED.clear()
    db_file = str(tmp_path / "mixed_approvals.db")
    session_id = "s-mixed-approvals"

    db = SqliteDb(db_file=db_file)
    run1 = _two_member_approval_team(db, resuming=False).run("Do both", session_id=session_id)
    assert run1.is_paused

    db.update_approval(_approval_record_for_tool(db, "alpha_action")["id"], status="approved", resolution_data=None)
    db.update_approval(_approval_record_for_tool(db, "beta_action")["id"], status="rejected", resolution_data=None)

    team2 = _two_member_approval_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.completed, run2.status
    assert _FIRED == ["alpha:A"], f"the rejected member's tool must not run: {_FIRED}"


@pytest.mark.asyncio
async def test_one_approval_does_not_resolve_a_sibling_with_colliding_tool_call_ids(tmp_path):
    """Provider-local tool_call_ids can collide across members; the collision
    must not let one member's approval decide for the other."""
    _FIRED.clear()
    db_file = str(tmp_path / "colliding_approvals.db")
    session_id = "s-colliding-approvals"

    db = SqliteDb(db_file=db_file)
    run1 = await _two_member_approval_team(db, resuming=False, collide=True).arun("Do both", session_id=session_id)
    assert run1.is_paused

    db.update_approval(_approval_record_for_tool(db, "alpha_action")["id"], status="approved", resolution_data=None)

    team2 = _two_member_approval_team(SqliteDb(db_file=db_file), resuming=True, collide=True)
    run2 = await team2.acontinue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.paused, f"a pending sibling approval let the run reach {run2.status}"
    assert _FIRED == [], f"a tool executed while its own approval was pending: {_FIRED}"


def test_a_deleted_sibling_approval_blocks_the_continue(tmp_path):
    """A tool whose own approval record is gone stays unresolved. Falling back
    to a sibling's record would let that sibling's approval execute it."""
    _FIRED.clear()
    db_file = str(tmp_path / "deleted_approval.db")
    session_id = "s-deleted-approval"

    db = SqliteDb(db_file=db_file)
    run1 = _two_member_approval_team(db, resuming=False).run("Do both", session_id=session_id)
    assert run1.is_paused

    db.update_approval(_approval_record_for_tool(db, "alpha_action")["id"], status="approved", resolution_data=None)
    assert db.delete_approval(_approval_record_for_tool(db, "beta_action")["id"])

    team2 = _two_member_approval_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.paused, f"a deleted sibling record let the run reach {run2.status}"
    assert _FIRED == [], f"a tool executed with its own approval record deleted: {_FIRED}"


_SHIPPED: List[str] = []


@tool(requires_confirmation=True)
@approval(type="required")
def ship(target: str) -> str:
    _SHIPPED.append(f"ship:{target}")
    return f"shipped {target}"


def _same_tool_two_member_team(db: SqliteDb, resuming: bool) -> Team:
    """Two members calling the SAME gated tool with colliding provider-local
    tool_call_ids: neither name nor id can tell their requirements apart."""

    def member(name: str, mid: str, target: str) -> Agent:
        return Agent(
            name=name,
            id=mid,
            model=_ScriptedModel(
                f"m-{mid}",
                [("content", "Done.")]
                if resuming
                else [("tool", "ship", {"target": target}, "call_1"), ("content", "Done.")],
            ),
            tools=[ship],
            db=db,
            telemetry=False,
        )

    return Team(
        name="Ship Team",
        id="ship-team",
        model=_ScriptedModel(
            "m-lead",
            [("content", "All done.")]
            if resuming
            else [
                (
                    "tools",
                    [
                        ("delegate_task_to_member", {"member_id": "alpha", "task": "ship A"}, "tc-d1"),
                        ("delegate_task_to_member", {"member_id": "beta", "task": "ship B"}, "tc-d2"),
                    ],
                ),
                ("content", "All done."),
            ],
        ),
        members=[member("Alpha", "alpha", "A"), member("Beta", "beta", "B")],
        db=db,
        telemetry=False,
    )


def test_an_ambiguous_tool_owner_blocks_instead_of_borrowing_a_sibling_record(tmp_path):
    """Two members calling the same tool with colliding tool_call_ids: a member
    whose own record is gone must block, not resolve through the requirement
    that happens to match first."""
    _SHIPPED.clear()
    db_file = str(tmp_path / "ambiguous_owner.db")
    session_id = "s-ambiguous-owner"

    db = SqliteDb(db_file=db_file)
    run1 = _same_tool_two_member_team(db, resuming=False).run("Ship both", session_id=session_id)
    assert run1.is_paused
    records, _ = db.get_approvals(approval_type="required", limit=50)
    assert len(records) == 2

    approved_record, deleted_record = records
    db.update_approval(approved_record["id"], status="approved", resolution_data=None)
    assert db.delete_approval(deleted_record["id"])

    team2 = _same_tool_two_member_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.paused, f"an ambiguous owner match let the run reach {run2.status}"
    assert _SHIPPED == [], f"a tool with no record of its own executed on a sibling's approval: {_SHIPPED}"


def test_an_ambiguous_value_match_resolves_no_owner():
    """Unit contract of _member_run_id_for_tool: identity wins outright; a
    value match fitting requirements of more than one member is ambiguous."""
    from agno.run.approval import _AMBIGUOUS_OWNER, _member_run_id_for_tool

    te_a = ToolExecution(tool_call_id="call_1", tool_name="ship", approval_type="required")
    te_b = ToolExecution(tool_call_id="call_1", tool_name="ship", approval_type="required")
    req_a = RunRequirement(tool_execution=te_a)
    req_a.member_run_id = "run-alpha"
    req_b = RunRequirement(tool_execution=te_b)
    req_b.member_run_id = "run-beta"
    holder = MagicMock(requirements=[req_a, req_b])

    assert _member_run_id_for_tool(holder, te_b) == "run-beta"
    reloaded_copy = ToolExecution(tool_call_id="call_1", tool_name="ship", approval_type="required")
    assert _member_run_id_for_tool(holder, reloaded_copy) == _AMBIGUOUS_OWNER


def test_a_reissued_team_approval_record_still_resolves(tmp_path):
    """A team-level tool whose stamped record was deleted and re-created under
    the same run resolves against the re-issued record; the stale id must not
    block the run forever."""
    _DEPLOYS.clear()
    db_file = str(tmp_path / "reissued_record.db")
    session_id = "s-reissued-record"

    db = SqliteDb(db_file=db_file)
    run1 = _team_level_approval_team(db, resuming=False).run("Deploy prod", session_id=session_id)
    assert run1.is_paused
    records, _ = db.get_approvals(approval_type="required", limit=50)
    assert len(records) == 1
    original = records[0]

    assert db.delete_approval(original["id"])
    reissued = dict(original)
    reissued["id"] = "reissued-record-id"
    reissued["status"] = "pending"
    db.create_approval(reissued)
    db.update_approval("reissued-record-id", status="approved", resolution_data=None)

    team2 = _team_level_approval_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.completed, (
        f"the re-issued approved record was not found; the run is stuck at {run2.status}"
    )
    assert _DEPLOYS == ["prod"], _DEPLOYS


_MIXED: List[str] = []


@tool(requires_confirmation=True)
@approval(type="required")
def announce(item: str) -> str:
    _MIXED.append(f"announce:{item}")
    return f"announced {item}"


@tool(requires_confirmation=True)
@approval(type="required")
def notify(to: str) -> str:
    _MIXED.append(f"notify:{to}")
    return f"notified {to}"


def _mixed_approval_team(db: SqliteDb, resuming: bool) -> Team:
    """A team-level gated tool plus a delegated member gated tool, each backed
    by its own approval record."""
    noter = Agent(
        name="Noter",
        id="noter",
        model=_ScriptedModel(
            "m-noter",
            [("content", "Notified.")]
            if resuming
            else [("tool", "notify", {"to": "ops@example.com"}, "tc-notify"), ("content", "Notified.")],
        ),
        tools=[notify],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Mixed Team",
        id="mixed-team",
        model=_ScriptedModel(
            "m-lead",
            [("content", "All done.")]
            if resuming
            else [
                (
                    "tools",
                    [
                        ("delegate_task_to_member", {"member_id": "noter", "task": "notify ops"}, "tc-deleg"),
                        ("announce", {"item": "release"}, "tc-announce"),
                    ],
                ),
                ("content", "All done."),
            ],
        ),
        tools=[announce],
        members=[noter],
        db=db,
        telemetry=False,
    )


def test_a_team_approval_does_not_decide_a_member_tools_record(tmp_path):
    """The team pause's record must not overwrite the approval id a member
    tool already owns; approving only the team record leaves the member's
    record pending and nothing executes."""
    _MIXED.clear()
    db_file = str(tmp_path / "mixed_team_member.db")
    session_id = "s-mixed-team-member"

    db = SqliteDb(db_file=db_file)
    run1 = _mixed_approval_team(db, resuming=False).run("Announce and notify", session_id=session_id)
    assert run1.is_paused
    records, _ = db.get_approvals(approval_type="required", limit=50)
    assert len(records) == 2, f"expected a team record and a member record, got {len(records)}"

    db.update_approval(_approval_record_for_tool(db, "announce")["id"], status="approved", resolution_data=None)

    team2 = _mixed_approval_team(SqliteDb(db_file=db_file), resuming=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run2.status == RunStatus.paused, f"the member's pending record was ignored: {run2.status}"
    assert _MIXED == [], f"a tool executed on the team record alone: {_MIXED}"

    db2 = SqliteDb(db_file=db_file)
    db2.update_approval(_approval_record_for_tool(db2, "notify")["id"], status="approved", resolution_data=None)
    team3 = _mixed_approval_team(SqliteDb(db_file=db_file), resuming=True)
    run3 = team3.continue_run(run_id=run1.run_id, session_id=session_id)
    assert run3.status == RunStatus.completed, run3.status
    assert sorted(_MIXED) == ["announce:release", "notify:ops@example.com"], _MIXED


def test_a_reclaimed_paused_buffer_keeps_its_event_index():
    """Reclaiming a paused entry must not reset the monotonic event index: a
    later continuation would recycle indices a client's cursor already covers,
    and its events would be silently deduplicated away."""
    from agno.os.managers import EventsBuffer

    buf = EventsBuffer(cleanup_interval=3600)
    assert buf.add_event("r-reclaim-idx", MagicMock()) == 0
    assert buf.add_event("r-reclaim-idx", MagicMock()) == 1
    buf.set_run_completed("r-reclaim-idx", RunStatus.paused)
    buf.cleanup_interval = -1
    buf.cleanup_runs()
    assert buf.get_run_status("r-reclaim-idx") is None

    # The continuation after the reclaim keeps ascending.
    buf.cleanup_interval = 3600
    assert buf.add_event("r-reclaim-idx", MagicMock()) == 2, "the reclaimed run's event index restarted"
    assert buf.get_run_status("r-reclaim-idx") == RunStatus.running


@pytest.mark.asyncio
async def test_a_background_fork_from_a_stale_object_keeps_the_originals_buffer_status(tmp_path):
    """A fork's bookkeeping under the original run's key reflects the original
    run's stored status, not the stale caller object's."""
    from agno.os.managers import event_buffer

    _EXECUTED.clear()
    db_file = str(tmp_path / "stale_fork_buffer.db")
    session_id = "s-stale-fork-buffer"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused
    done = await _build_flat_team(SqliteDb(db_file=db_file), resuming=True).acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=_wire_requirements(run1.requirements)
    )
    assert done.status == RunStatus.completed

    # The caller still holds the stale paused object and forks off it.
    team3 = _build_flat_team(SqliteDb(db_file=db_file), resuming=False)
    async for _ in team3.acontinue_run(
        run_response=run1,
        session_id=session_id,
        fork=True,
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()

    assert [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0].status == RunStatus.completed
    buffer_status = event_buffer.get_run_status(run1.run_id)
    assert buffer_status == RunStatus.completed, (
        f"the completed original is advertised as {buffer_status!r} because the stale object leaked into "
        "the fork's bookkeeping"
    )


def test_a_paused_buffer_entry_reused_by_a_continue_is_not_reclaimed():
    """A continue reuses the paused run's buffer entry; its stale paused
    metadata must not let a later cleanup pass delete the live continuation."""
    from agno.os.managers import EventsBuffer

    buf = EventsBuffer(cleanup_interval=3600)
    buf.add_event("r-reuse", MagicMock())
    buf.set_run_completed("r-reuse", RunStatus.paused)
    assert buf.get_run_status("r-reuse") == RunStatus.paused

    # The continuation's first event takes the run over.
    buf.add_event("r-reuse", MagicMock())
    assert buf.get_run_status("r-reuse") == RunStatus.running
    assert "completed_at" not in buf.run_metadata["r-reuse"]

    buf.cleanup_interval = -1
    buf.cleanup_runs()
    assert buf.get_run_status("r-reuse") == RunStatus.running, "cleanup reclaimed a live continuation"
    assert buf.get_event_count("r-reuse") == 2


@pytest.mark.asyncio
async def test_a_background_fork_from_a_run_object_does_not_orphan_the_original(tmp_path):
    """A fork executes under a new run id; the original run must keep the
    status it has instead of being stranded at RUNNING."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "fork_orphan.db")
    session_id = "s-fork-orphan"

    run1 = await _build_flat_team(SqliteDb(db_file=db_file), resuming=False).arun(
        "Email a@example.com", session_id=session_id
    )
    assert run1.is_paused

    team2 = _build_flat_team(SqliteDb(db_file=db_file), resuming=True)
    async for _ in team2.acontinue_run(
        run_response=run1,
        session_id=session_id,
        requirements=_wire_requirements(run1.requirements),
        fork=True,
        stream=True,
        stream_events=True,
        background=True,
    ):
        pass
    await _drain_background_tasks()

    stored = [r for r in _reload_runs(db_file, session_id) if r.run_id == run1.run_id][0]
    assert stored.status == RunStatus.paused, (
        f"the original run was left {stored.status!r} after a fork branched off it"
    )


def test_idless_tool_results_are_scrubbed_too():
    """store_tool_messages=False stores NO tool-result message; ids only decide
    which assistant calls lost their answer. The pending call survives."""
    from agno.team._session import _scrub_tool_results_keeping_unresolved

    run = RunOutput(run_id="r-idless")
    run.messages = [
        Message(role="user", content="do it"),
        Message(role="assistant", tool_calls=[{"id": "t1", "type": "function", "function": {"name": "a"}}]),
        Message(role="tool", tool_call_id="t1", content="resolved result"),
        Message(role="tool", tool_call_id=None, content="LEGACY IDLESS RESULT"),
        Message(role="assistant", tool_calls=[{"id": "p1", "type": "function", "function": {"name": "gated"}}]),
    ]
    _scrub_tool_results_keeping_unresolved(run)

    assert not any(m.role == "tool" for m in run.messages), (
        f"a tool-result message survived the scrub: {[m.content for m in run.messages if m.role == 'tool']}"
    )
    pending = [c["id"] for m in run.messages if m.role == "assistant" for c in (m.tool_calls or [])]
    assert pending == ["p1"], f"the pending gated call must survive: {pending}"


def test_an_unresolvable_member_response_is_stored_fail_closed():
    """When the owning member cannot be found at storage time, the stored view
    scrubs as if every storage flag were off; the pending call survives."""
    from agno.team._session import _storage_view_of_spared_run

    member_run = RunOutput(run_id="r-member", agent_id="ghost")
    member_run.status = RunStatus.paused
    member_run.messages = [
        Message(role="user", content="do it"),
        Message(role="assistant", tool_calls=[{"id": "t9", "type": "function", "function": {"name": "a"}}]),
        Message(role="tool", tool_call_id="t9", content="SECRET TOOL RESULT"),
        Message(role="assistant", tool_calls=[{"id": "p9", "type": "function", "function": {"name": "gated"}}]),
    ]
    team = _build_flat_team(SqliteDb(db_file=":memory:"), resuming=True)

    view = _storage_view_of_spared_run(team, member_run)

    assert not any(m.role == "tool" for m in view.messages or []), "an unresolved member's tool result was stored"
    pending = [c["id"] for m in view.messages or [] if m.role == "assistant" for c in (m.tool_calls or [])]
    assert "p9" in pending, f"the pending gated call must survive fail-closed storage: {pending}"
    # The live object the caller holds is untouched.
    assert any(m.role == "tool" for m in member_run.messages)


def test_a_routing_failure_restores_the_callers_team_level_requirements(tmp_path):
    """A plain exception during member routing must leave the caller's run
    object carrying each team-level requirement exactly once."""
    _EXECUTED.clear()
    db_file = str(tmp_path / "routing_failure_reqs.db")
    session_id = "s-routing-failure-reqs"

    team1 = _build_own_tool_flat_team(SqliteDb(db_file=db_file), resuming=False)
    run1 = team1.run("Publish the release and email a@example.com", session_id=session_id)
    assert run1.is_paused

    def _boom_stream(*args: Any, **kwargs: Any):
        raise RuntimeError("router boom")
        yield

    team2 = _build_own_tool_flat_team(SqliteDb(db_file=db_file), resuming=True)
    with patch("agno.team._run._route_requirements_to_members_stream", new=_boom_stream):
        with pytest.raises(RuntimeError, match="router boom"):
            for _ in team2.continue_run(
                run_response=run1,
                session_id=session_id,
                requirements=_wire_requirements(run1.requirements),
                stream=True,
                stream_events=True,
            ):
                pass

    names = [r.tool_execution.tool_name for r in (run1.requirements or [])]
    assert names.count("publish") == 1, f"the caller's run object carries: {names}"
