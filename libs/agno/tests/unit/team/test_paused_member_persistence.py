"""
Unit tests for paused member run persistence in team routing helpers.

Regression test for: https://github.com/agno-agi/agno/issues/8925

When a member pauses during team.continue_run() routing, its RunOutput must be
persisted to session.runs so subsequent continue_run calls can find it after
session reload.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_execution(**overrides) -> ToolExecution:
    defaults = dict(tool_name="do_something", tool_args={"x": 1})
    defaults.update(overrides)
    return ToolExecution(**defaults)


def _make_requirement(**te_overrides) -> RunRequirement:
    return RunRequirement(tool_execution=_make_tool_execution(**te_overrides))


def _make_run_response_with_member_req():
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

    run_response, session = _make_run_response_with_member_req()

    member = MagicMock()
    member.name = "Member 1"
    paused_response = MagicMock(is_paused=True, content=None, run_id="member-run-1")
    paused_response.requirements = [_make_requirement(requires_user_input=True)]
    member.continue_run = MagicMock(return_value=paused_response)

    team = MagicMock()

    with (
        patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)),
        patch("agno.team._tools._propagate_member_pause"),
    ):
        _route_requirements_to_members(team, run_response=run_response, session=session, run_context=None)

    session.upsert_run.assert_called_once_with(paused_response)


def test_sync_routing_persists_completed_member_run():
    from agno.team._run import _route_requirements_to_members

    run_response, session = _make_run_response_with_member_req()

    member = MagicMock()
    member.name = "Member 1"
    completed_response = MagicMock(is_paused=False, content="done", run_id="member-run-1")
    member.continue_run = MagicMock(return_value=completed_response)

    team = MagicMock()

    with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
        _route_requirements_to_members(team, run_response=run_response, session=session, run_context=None)

    session.upsert_run.assert_called_once_with(completed_response)


# ---------------------------------------------------------------------------
# Async non-streaming
# ---------------------------------------------------------------------------


def test_async_routing_persists_paused_member_run():
    from agno.team._run import _aroute_requirements_to_members

    run_response, session = _make_run_response_with_member_req()

    member = MagicMock()
    member.name = "Member 1"
    paused_response = MagicMock(is_paused=True, content=None, run_id="member-run-1")
    paused_response.requirements = [_make_requirement(requires_user_input=True)]
    member.acontinue_run = AsyncMock(return_value=paused_response)

    team = MagicMock()

    async def exercise():
        with (
            patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)),
            patch("agno.team._tools._propagate_member_pause"),
        ):
            await _aroute_requirements_to_members(team, run_response=run_response, session=session, run_context=None)

    asyncio.run(exercise())
    session.upsert_run.assert_called_once_with(paused_response)


def test_async_routing_persists_completed_member_run():
    from agno.team._run import _aroute_requirements_to_members

    run_response, session = _make_run_response_with_member_req()

    member = MagicMock()
    member.name = "Member 1"
    completed_response = MagicMock(is_paused=False, content="done", run_id="member-run-1")
    member.acontinue_run = AsyncMock(return_value=completed_response)

    team = MagicMock()

    async def exercise():
        with patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)):
            await _aroute_requirements_to_members(team, run_response=run_response, session=session, run_context=None)

    asyncio.run(exercise())
    session.upsert_run.assert_called_once_with(completed_response)


# ---------------------------------------------------------------------------
# Sync streaming
# ---------------------------------------------------------------------------


def test_sync_streaming_routing_persists_paused_member_run():
    from agno.team._run import _route_requirements_to_members_stream

    run_response, session = _make_run_response_with_member_req()

    paused_response = RunOutput(run_id="member-run-1")
    paused_response.status = RunStatus.paused
    paused_response.content = None
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
        member_results = []
        list(
            _route_requirements_to_members_stream(
                team,
                run_response=run_response,
                session=session,
                member_results=member_results,
                run_context=None,
                stream_events=False,
            )
        )

    session.upsert_run.assert_called_once_with(paused_response)


# ---------------------------------------------------------------------------
# Async streaming
# ---------------------------------------------------------------------------


def test_async_streaming_routing_persists_paused_member_run():
    from agno.team._run import _aroute_requirements_to_members_stream

    run_response, session = _make_run_response_with_member_req()

    paused_response = RunOutput(run_id="member-run-1")
    paused_response.status = RunStatus.paused
    paused_response.content = None
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

    async def exercise():
        with (
            patch("agno.team._tools._find_member_route_by_id", return_value=(0, member)),
            patch("agno.team._tools._propagate_member_pause"),
            patch("agno.team._run.araise_if_cancelled", new_callable=AsyncMock),
            patch("agno.team._run.aregister_member_run", new_callable=AsyncMock),
        ):
            member_results = []
            async for _ in _aroute_requirements_to_members_stream(
                team,
                run_response=run_response,
                session=session,
                member_results=member_results,
                run_context=None,
                stream_events=False,
            ):
                pass

    asyncio.run(exercise())
    session.upsert_run.assert_called_once_with(paused_response)
