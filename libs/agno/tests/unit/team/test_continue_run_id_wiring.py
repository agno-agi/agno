"""Unit tests proving ``current_run_id=run_response.run_id`` actually reaches the
continue-message builder at each of the nine call sites in ``team/_run.py``.

Team-side counterpart to agent/tests/unit/agent/test_continue_run_id_wiring.py.
test_continue_run_history_exclusion.py (team) calls ``_build_continue_run_messages``
directly with an explicit ``current_run_id``, so it never exercises the wiring inside
``_run.py`` itself -- a refactor that drops ``current_run_id=run_response.run_id`` at
any of the nine call sites would pass that test suite unnoticed while reopening #10086
on the team side.

These tests drive the real dispatch functions (``continue_run_dispatch``,
``_continue_run_dispatch_stream_with_member_events``, ``_acontinue_run``,
``_acontinue_run_stream``) and stop them exactly at the message-builder call via a
``BaseException`` sentinel, which passes through every ``except Exception`` /
``except (KeyboardInterrupt, asyncio.CancelledError, GeneratorExit)`` handler along the
continue path untouched -- so the rest of the pipeline (model call, tool execution,
persistence) never needs to be mocked.

Confirmed red/green per site: temporarily changing each of the nine
``current_run_id=run_response.run_id`` call sites in ``agno/team/_run.py`` to
``current_run_id=None`` (one at a time) makes exactly the corresponding test below
fail, with the other eight still passing. See the report accompanying this file for
the full site -> test table.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run import RunContext, RunStatus
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team import _init, _response, _run, _run_options, _storage, _tools
from agno.team._run_options import ResolvedRunOptions
from agno.utils import team as team_utils

RUN_ID = "team-run-continue-wiring"
SESSION_ID = "team-session-wiring"


class _StoppedAtMessageBuilder(BaseException):
    """Raised the instant the message builder is reached."""


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _make_team() -> MagicMock:
    """A MagicMock team, with only the attributes real (unmocked) helper
    functions along the continue path actually branch on set to safe values.

    Everything else can stay an auto-Mock because it's either never touched
    before the sentinel fires, or is guarded by an ``isinstance``/``is None``
    check that a plain Mock naturally fails/passes safely.
    """
    team = MagicMock()
    team.db = None  # short-circuits check_and_apply_approval_resolution
    team.user_id = None
    team._learning = None  # short-circuits _aget_learning_tools
    team.tools = None  # short-circuits _check_and_refresh_mcp_tools/_connect_mcp_tools
    team.retries = 0  # `team.retries + 1` in the async retry loop
    team.events_to_skip = []  # iterated by handle_event
    team.store_events = False
    return team


def _make_team_session() -> TeamSession:
    return TeamSession(session_id=SESSION_ID, team_id=None, runs=[])


def _make_tool_execution(tool_call_id: str = "tc-1") -> ToolExecution:
    return ToolExecution(tool_call_id=tool_call_id, tool_name="dummy_tool", tool_args={})


def _make_resolved_requirement(member_agent_id: "str | None" = None) -> RunRequirement:
    """A RunRequirement that is already resolved (no confirmation/user-input/
    external-execution flags set on its tool_execution), optionally stamped
    as a member requirement."""
    req = RunRequirement(tool_execution=_make_tool_execution())
    req.member_agent_id = member_agent_id
    return req


def _make_team_run(status: RunStatus, tools=None, requirements=None) -> TeamRunOutput:
    return TeamRunOutput(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        status=status,
        tools=tools,
        requirements=requirements,
        messages=[],
    )


def _make_run_context() -> RunContext:
    return RunContext(run_id=RUN_ID, session_id=SESSION_ID, user_id=None)


def _make_resolved_run_options(stream: bool = True) -> ResolvedRunOptions:
    return ResolvedRunOptions(
        stream=stream,
        stream_events=False,
        yield_run_output=False,
        add_history_to_context=True,
        add_dependencies_to_context=False,
        add_session_state_to_context=False,
        dependencies=None,
        knowledge_filters=None,
        metadata=None,
        output_schema=None,
    )


def _fake_get_continue_run_messages(captured: dict):
    def fake(team, input, session=None, add_history_to_context=None, run_context=None, current_run_id=None):
        captured["current_run_id"] = current_run_id
        raise _StoppedAtMessageBuilder()

    return fake


def _fake_aget_continue_run_messages(captured: dict):
    async def fake(team, input, session=None, add_history_to_context=None, run_context=None, current_run_id=None):
        captured["current_run_id"] = current_run_id
        raise _StoppedAtMessageBuilder()

    return fake


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


def _patch_sync_dispatch(monkeypatch: pytest.MonkeyPatch, team_session: TeamSession) -> None:
    """Patch everything ``continue_run_dispatch`` and
    ``_continue_run_dispatch_stream_with_member_events`` touch before the
    message-builder call, other than the message builder itself."""
    monkeypatch.setattr(_init, "_has_async_db", lambda team: False)
    monkeypatch.setattr(
        _init,
        "_initialize_session",
        lambda team, session_id=None, user_id=None: (session_id, user_id),
    )
    monkeypatch.setattr(
        _storage,
        "_read_or_create_session",
        lambda team, session_id=None, user_id=None: team_session,
    )
    monkeypatch.setattr(_storage, "_update_metadata", lambda team, session=None: None)
    monkeypatch.setattr(
        _storage,
        "_load_session_state",
        lambda team, session=None, session_state=None: session_state,
    )
    monkeypatch.setattr(
        _run_options,
        "resolve_run_options",
        lambda team, **kwargs: SimpleNamespace(
            stream=False,
            stream_events=False,
            yield_run_output=False,
            dependencies=None,
            knowledge_filters=None,
            metadata=None,
        ),
    )
    monkeypatch.setattr(_response, "get_response_format", lambda team, run_context=None: None)
    monkeypatch.setattr(_tools, "_determine_tools_for_model", lambda *a, **kw: [])


def _patch_async_dispatch(monkeypatch: pytest.MonkeyPatch, team_session: TeamSession) -> None:
    """Patch everything ``_acontinue_run``/``_acontinue_run_stream`` touch
    before the message-builder call, other than the message builder itself."""

    async def fake_asetup_session(team, run_context, session_id, user_id, run_id):
        return team_session

    async def fake_aregister_run(run_id):
        return None

    async def fake_acleanup_run(run_id):
        return None

    async def fake_disconnect_mcp_tools(team):
        return None

    monkeypatch.setattr(_run, "_asetup_session", fake_asetup_session)
    monkeypatch.setattr(_run, "aregister_run", fake_aregister_run)
    monkeypatch.setattr(_run, "acleanup_run", fake_acleanup_run)
    monkeypatch.setattr(_init, "_disconnect_connectable_tools", lambda team: None)
    monkeypatch.setattr(_init, "_disconnect_mcp_tools", fake_disconnect_mcp_tools)
    monkeypatch.setattr(_tools, "_determine_tools_for_model", lambda *a, **kw: [])


# ===========================================================================
# Sync: continue_run_dispatch -- 3 call sites
# ===========================================================================


def test_sync_dispatch_snapshot_branch_passes_run_id(monkeypatch: pytest.MonkeyPatch):
    """Site 1 (~line 7736): the ``if _did_snapshot_dispatch:`` branch.

    ``_did_snapshot_dispatch`` is computed *before* the requirements/tools
    branch selection below it (which sets the same-named flag for a bare
    mid-flight resume, but that later assignment feeds a *different*,
    downstream check -- it does not loop back to re-enter this early branch).
    So the only way to land on this specific call site is fork=True or a
    truncating ``continue_from``. We use message truncation (not fork) so
    the run keeps its original run_id -- fork clones the run under a new one,
    which would make the id-passthrough assertion below meaningless.
    """
    team = _make_team()
    team_session = _make_team_session()
    _patch_sync_dispatch(monkeypatch, team_session)

    captured: dict = {}
    monkeypatch.setattr(_run, "_get_continue_run_messages", _fake_get_continue_run_messages(captured))

    run_response = TeamRunOutput(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        status=RunStatus.running,
        tools=None,
        requirements=None,
        messages=[Message(role="user", content="hi"), Message(role="assistant", content="there")],
    )

    with pytest.raises(_StoppedAtMessageBuilder):
        _run.continue_run_dispatch(team, run_response=run_response, continue_from=1, stream=False)

    assert captured.get("current_run_id") == RUN_ID
    assert run_response.run_id == RUN_ID  # sanity: truncation, not fork, was taken


def test_sync_dispatch_team_level_branch_passes_run_id(monkeypatch: pytest.MonkeyPatch):
    """Site 2 (~line 7981): the ``if has_team_level or _did_snapshot_dispatch:``
    branch, reached via a PAUSED run with an already-resolved team-level
    requirement (member_agent_id=None)."""
    team = _make_team()
    team_session = _make_team_session()
    _patch_sync_dispatch(monkeypatch, team_session)

    captured: dict = {}
    monkeypatch.setattr(_run, "_get_continue_run_messages", _fake_get_continue_run_messages(captured))

    req = _make_resolved_requirement(member_agent_id=None)
    run_response = _make_team_run(RunStatus.paused, tools=[_make_tool_execution()], requirements=[req])

    with pytest.raises(_StoppedAtMessageBuilder):
        _run.continue_run_dispatch(team, run_response=run_response, stream=False)

    assert captured.get("current_run_id") == RUN_ID


def test_sync_dispatch_member_only_branch_passes_run_id(monkeypatch: pytest.MonkeyPatch):
    """Site 3 (~line 8054): the ``if member_results and not has_team_level:``
    branch, reached via a PAUSED run with an already-resolved member-level
    requirement. ``_route_requirements_to_members`` is mocked away -- member
    routing itself is out of scope for this wiring proof."""
    team = _make_team()
    team_session = _make_team_session()
    _patch_sync_dispatch(monkeypatch, team_session)
    monkeypatch.setattr(
        _run,
        "_route_requirements_to_members",
        lambda team, run_response, session, run_context=None: ["[Member]: done"],
    )
    monkeypatch.setattr(team_utils, "get_member_id", lambda member: "team-self-id")

    captured: dict = {}
    monkeypatch.setattr(_run, "_get_continue_run_messages", _fake_get_continue_run_messages(captured))

    req = _make_resolved_requirement(member_agent_id="member-1")
    run_response = _make_team_run(RunStatus.paused, tools=[_make_tool_execution()], requirements=[req])

    with pytest.raises(_StoppedAtMessageBuilder):
        _run.continue_run_dispatch(team, run_response=run_response, stream=False)

    assert captured.get("current_run_id") == RUN_ID


# ===========================================================================
# Sync stream: _continue_run_dispatch_stream_with_member_events -- 2 call sites
# ===========================================================================
#
# This generator is called directly (it's a plain module-level function), not
# through continue_run_dispatch's routing -- simpler and just as faithful to
# the real call sites, per the two branches below.


def test_sync_stream_member_events_team_level_branch_passes_run_id(monkeypatch: pytest.MonkeyPatch):
    """Site 4 (~line 8217): the ``if has_team_level:`` branch."""
    monkeypatch.setattr(_response, "get_response_format", lambda team, run_context=None: None)
    monkeypatch.setattr(_tools, "_determine_tools_for_model", lambda *a, **kw: [])
    captured: dict = {}
    monkeypatch.setattr(_run, "_get_continue_run_messages", _fake_get_continue_run_messages(captured))

    team = _make_team()
    team_session = _make_team_session()
    req = _make_resolved_requirement(member_agent_id=None)
    run_response = _make_team_run(RunStatus.paused, tools=None, requirements=[req])
    run_context = _make_run_context()
    opts = _make_resolved_run_options(stream=True)

    gen = _run._continue_run_dispatch_stream_with_member_events(
        team=team,
        run_response=run_response,
        member_event_stream=iter([]),
        member_results=[],
        original_member_req_ids=set(),
        team_level_reqs=[],
        has_team_level=True,
        team_session=team_session,
        run_context=run_context,
        opts=opts,
        user_id=None,
        debug_mode=None,
        background_tasks=None,
    )

    with pytest.raises(_StoppedAtMessageBuilder):
        for _ in gen:
            pass

    assert captured.get("current_run_id") == RUN_ID


def test_sync_stream_member_events_member_only_branch_passes_run_id(monkeypatch: pytest.MonkeyPatch):
    """Site 5 (~line 8269): the ``if member_results:`` branch (no team-level
    requirements survived member routing)."""
    monkeypatch.setattr(_response, "get_response_format", lambda team, run_context=None: None)
    monkeypatch.setattr(_tools, "_determine_tools_for_model", lambda *a, **kw: [])
    captured: dict = {}
    monkeypatch.setattr(_run, "_get_continue_run_messages", _fake_get_continue_run_messages(captured))

    team = _make_team()
    team_session = _make_team_session()
    run_response = _make_team_run(RunStatus.paused, tools=None, requirements=[])
    run_context = _make_run_context()
    opts = _make_resolved_run_options(stream=True)

    gen = _run._continue_run_dispatch_stream_with_member_events(
        team=team,
        run_response=run_response,
        member_event_stream=iter([]),
        member_results=["[Member]: done"],
        original_member_req_ids=set(),
        team_level_reqs=[],
        has_team_level=False,
        team_session=team_session,
        run_context=run_context,
        opts=opts,
        user_id=None,
        debug_mode=None,
        background_tasks=None,
    )

    with pytest.raises(_StoppedAtMessageBuilder):
        for _ in gen:
            pass

    assert captured.get("current_run_id") == RUN_ID


# ===========================================================================
# Async: _acontinue_run -- 2 call sites
# ===========================================================================
#
# Called directly (plain async function taking run_response), bypassing
# acontinue_run_dispatch's own setup -- simpler and just as faithful.


@pytest.mark.asyncio
async def test_async_snapshot_unified_branch_passes_run_id(monkeypatch: pytest.MonkeyPatch):
    """Site 6 (~line 9749): the ``if has_team_level or _did_snapshot_dispatch:``
    branch, reached via a bare mid-flight resume (no tools, no requirements).
    Unlike the sync dispatch, async has no separate duplicate "snapshot"
    branch -- both the fork/truncate/bare-resume path and the resolved
    team-level-requirement path funnel into this single call site."""
    team = _make_team()
    team_session = _make_team_session()
    _patch_async_dispatch(monkeypatch, team_session)

    captured: dict = {}
    monkeypatch.setattr(_run, "_aget_continue_run_messages", _fake_aget_continue_run_messages(captured))

    run_response = _make_team_run(RunStatus.running, tools=None, requirements=None)
    run_context = _make_run_context()

    with pytest.raises(_StoppedAtMessageBuilder):
        await _run._acontinue_run(
            team,
            session_id=SESSION_ID,
            run_context=run_context,
            run_response=run_response,
            run_id=RUN_ID,
            response_format=None,
        )

    assert captured.get("current_run_id") == RUN_ID


@pytest.mark.asyncio
async def test_async_member_only_branch_passes_run_id(monkeypatch: pytest.MonkeyPatch):
    """Site 7 (~line 9798): the ``elif member_results:`` branch, reached via a
    PAUSED run with an already-resolved member-level requirement.
    ``_aroute_requirements_to_members`` is mocked away."""
    team = _make_team()
    team_session = _make_team_session()
    _patch_async_dispatch(monkeypatch, team_session)

    async def fake_aroute(team, run_response, session, run_context=None):
        return ["[Member]: done"]

    monkeypatch.setattr(_run, "_aroute_requirements_to_members", fake_aroute)
    monkeypatch.setattr(team_utils, "get_member_id", lambda member: "team-self-id")

    captured: dict = {}
    monkeypatch.setattr(_run, "_aget_continue_run_messages", _fake_aget_continue_run_messages(captured))

    req = _make_resolved_requirement(member_agent_id="member-1")
    run_response = _make_team_run(RunStatus.paused, tools=[_make_tool_execution()], requirements=[req])
    run_context = _make_run_context()

    with pytest.raises(_StoppedAtMessageBuilder):
        await _run._acontinue_run(
            team,
            session_id=SESSION_ID,
            run_context=run_context,
            run_response=run_response,
            run_id=RUN_ID,
            response_format=None,
        )

    assert captured.get("current_run_id") == RUN_ID


# ===========================================================================
# Async stream: _acontinue_run_stream -- 2 call sites
# ===========================================================================


@pytest.mark.asyncio
async def test_async_stream_snapshot_unified_branch_passes_run_id(monkeypatch: pytest.MonkeyPatch):
    """Site 8 (~line 10237): stream mirror of site 6."""
    team = _make_team()
    team_session = _make_team_session()
    _patch_async_dispatch(monkeypatch, team_session)

    captured: dict = {}
    monkeypatch.setattr(_run, "_aget_continue_run_messages", _fake_aget_continue_run_messages(captured))

    run_response = _make_team_run(RunStatus.running, tools=None, requirements=None)
    run_context = _make_run_context()

    agen = _run._acontinue_run_stream(
        team,
        session_id=SESSION_ID,
        run_context=run_context,
        run_response=run_response,
        run_id=RUN_ID,
        response_format=None,
    )

    with pytest.raises(_StoppedAtMessageBuilder):
        async for _ in agen:
            pass

    assert captured.get("current_run_id") == RUN_ID


@pytest.mark.asyncio
async def test_async_stream_member_only_branch_passes_run_id(monkeypatch: pytest.MonkeyPatch):
    """Site 9 (~line 10366): stream mirror of site 7.
    ``_aroute_requirements_to_members_stream`` is mocked away as an empty
    async generator that appends to ``member_results`` in place, mirroring
    what the real one does for the caller."""
    team = _make_team()
    team_session = _make_team_session()
    _patch_async_dispatch(monkeypatch, team_session)

    async def fake_aroute_stream(team, run_response, session, member_results, run_context=None, stream_events=False):
        member_results.append("[Member]: done")
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(_run, "_aroute_requirements_to_members_stream", fake_aroute_stream)
    monkeypatch.setattr(team_utils, "get_member_id", lambda member: "team-self-id")

    captured: dict = {}
    monkeypatch.setattr(_run, "_aget_continue_run_messages", _fake_aget_continue_run_messages(captured))

    req = _make_resolved_requirement(member_agent_id="member-1")
    run_response = _make_team_run(RunStatus.paused, tools=[_make_tool_execution()], requirements=[req])
    run_context = _make_run_context()

    agen = _run._acontinue_run_stream(
        team,
        session_id=SESSION_ID,
        run_context=run_context,
        run_response=run_response,
        run_id=RUN_ID,
        response_format=None,
    )

    with pytest.raises(_StoppedAtMessageBuilder):
        async for _ in agen:
            pass

    assert captured.get("current_run_id") == RUN_ID
