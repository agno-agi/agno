"""Regression tests: call-site ``dependencies`` merge with ``Team.dependencies``.

Bug: call-site dependencies (e.g. channel/thread ids injected by the Slack/WhatsApp
interfaces) used to REPLACE ``Team.dependencies`` wholesale, so prompt-template variables
configured on the team silently dropped out of the system message on those surfaces. They
must merge instead, with call-site keys winning on conflict.

These tests exercise the fixed ``resolve_run_options`` merge, run the team's dependency
resolution, then render the system message — the same message an interface would send.
"""

from unittest.mock import MagicMock

import pytest

from agno.run import RunContext
from agno.session import TeamSession
from agno.team._messages import get_system_message
from agno.team._run import _aresolve_run_dependencies, _resolve_run_dependencies
from agno.team._run_options import resolve_run_options
from agno.team.team import Team


def _make_team(**kwargs) -> Team:
    """Create a Team with a mocked model so the system message can be rendered offline."""
    team = Team(name="test-team", mode="coordinate", members=[], **kwargs)
    mock_model = MagicMock()
    mock_model.get_instructions_for_model = MagicMock(return_value=None)
    mock_model.get_system_message_for_model = MagicMock(return_value=None)
    team.model = mock_model
    return team


def _render_system_message(team: Team, *, callsite_deps=None) -> str:
    """Resolve run options (the fixed merge) + dependencies, then render the system message (sync)."""
    opts = resolve_run_options(team, dependencies=callsite_deps)
    run_context = RunContext(run_id="r1", session_id="s1", dependencies=opts.dependencies)
    _resolve_run_dependencies(team, run_context=run_context)
    session = TeamSession(session_id="s1")
    msg = get_system_message(team, session, run_context=run_context)
    assert msg is not None
    return msg.content


async def _arender_system_message(team: Team, *, callsite_deps=None) -> str:
    """Async variant: resolve options + async dependency resolution, then render."""
    opts = resolve_run_options(team, dependencies=callsite_deps)
    run_context = RunContext(run_id="r1", session_id="s1", dependencies=opts.dependencies)
    await _aresolve_run_dependencies(team, run_context=run_context)
    session = TeamSession(session_id="s1")
    msg = get_system_message(team, session, run_context=run_context)
    assert msg is not None
    return msg.content


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


class TestTeamRunDependenciesMerge:
    def test_team_template_var_survives_callsite_runtime_keys(self):
        """The core bug: an interface passes runtime context deps; team template vars must remain."""
        team = _make_team(dependencies={"x": "RESOLVED"}, instructions="X={x}")
        content = _render_system_message(team, callsite_deps={"channel": "C123"})
        assert "X=RESOLVED" in content

    def test_callsite_key_also_available_for_substitution(self):
        team = _make_team(dependencies={"x": "RESOLVED"}, instructions="X={x} Z={z}")
        content = _render_system_message(team, callsite_deps={"z": "1"})
        assert "X=RESOLVED Z=1" in content

    def test_callsite_key_overrides_team_key_on_conflict(self):
        team = _make_team(dependencies={"x": "team"}, instructions="X={x}")
        content = _render_system_message(team, callsite_deps={"x": "call"})
        assert "X=call" in content

    def test_no_callsite_deps_team_deps_still_resolve(self):
        team = _make_team(dependencies={"x": "RESOLVED"}, instructions="X={x}")
        content = _render_system_message(team, callsite_deps=None)
        assert "X=RESOLVED" in content

    def test_resolver_callable_merges_with_callsite(self):
        def resolve_x():
            return "RESOLVED"

        team = _make_team(dependencies={"x": resolve_x}, instructions="X={x} Z={z}")
        content = _render_system_message(team, callsite_deps={"z": "1"})
        assert "X=RESOLVED Z=1" in content


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


class TestTeamArunDependenciesMerge:
    @pytest.mark.asyncio
    async def test_team_template_var_survives_callsite_runtime_keys(self):
        team = _make_team(dependencies={"x": "RESOLVED"}, instructions="X={x}")
        content = await _arender_system_message(team, callsite_deps={"channel": "C123"})
        assert "X=RESOLVED" in content

    @pytest.mark.asyncio
    async def test_callsite_key_also_available_for_substitution(self):
        team = _make_team(dependencies={"x": "RESOLVED"}, instructions="X={x} Z={z}")
        content = await _arender_system_message(team, callsite_deps={"z": "1"})
        assert "X=RESOLVED Z=1" in content

    @pytest.mark.asyncio
    async def test_callsite_key_overrides_team_key_on_conflict(self):
        team = _make_team(dependencies={"x": "team"}, instructions="X={x}")
        content = await _arender_system_message(team, callsite_deps={"x": "call"})
        assert "X=call" in content

    @pytest.mark.asyncio
    async def test_no_callsite_deps_team_deps_still_resolve(self):
        team = _make_team(dependencies={"x": "RESOLVED"}, instructions="X={x}")
        content = await _arender_system_message(team, callsite_deps=None)
        assert "X=RESOLVED" in content

    @pytest.mark.asyncio
    async def test_async_resolver_callable_merges_with_callsite(self):
        async def resolve_x():
            return "RESOLVED"

        team = _make_team(dependencies={"x": resolve_x}, instructions="X={x} Z={z}")
        content = await _arender_system_message(team, callsite_deps={"z": "1"})
        assert "X=RESOLVED Z=1" in content
