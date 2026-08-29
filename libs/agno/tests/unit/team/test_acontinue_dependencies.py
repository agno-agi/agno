"""Team async continue paths must resolve callable dependencies.

``_acontinue_run`` / ``_acontinue_run_stream`` previously never called
``_aresolve_run_dependencies``, so a callable dependency configured on a Team
was resolved on ``team.run()``/``team.arun()`` and on the sync continue
dispatch, but an async continuation ran with the raw callables still in
``run_context.dependencies``. These tests pin the resolution inside both async
implementations, right after the continue metadata is restored.
"""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.run import RunContext  # noqa: E402


class StopTest(Exception):
    """Sentinel raised right after the dependency-resolution point."""


def _paused_session(run_id="r-1", owner="alice"):
    session = MagicMock()
    session.runs = [SimpleNamespace(run_id=run_id, user_id=owner)]
    return session


def _run_context():
    run_context = RunContext(run_id="r-1", session_id="s-1", user_id=None)
    run_context.dependencies = {"robot_name": lambda: "Anna"}
    return run_context


@pytest.mark.asyncio
class TestTeamAsyncContinueDependencies:
    async def test_acontinue_run_resolves_dependencies(self, monkeypatch):
        from agno.team import _run as team_run

        monkeypatch.setattr(team_run, "_asetup_session", AsyncMock(return_value=_paused_session()))
        monkeypatch.setattr(team_run, "_resolve_continue_owner_team", lambda *a, **k: "alice")
        resolved = AsyncMock()
        monkeypatch.setattr(team_run, "_aresolve_run_dependencies", resolved)

        def boom(*args, **kwargs):
            raise StopTest

        monkeypatch.setattr(team_run, "_resolve_continue_from_team", boom)

        team = MagicMock()
        team.save_response_to_file = None
        team.retries = 0
        run_context = _run_context()
        try:
            await team_run._acontinue_run(team, session_id="s-1", run_context=run_context, run_id="r-1", user_id=None)
        except Exception:
            pass

        resolved.assert_awaited_once_with(team, run_context=run_context)

    async def test_acontinue_run_stream_resolves_dependencies(self, monkeypatch):
        from agno.team import _run as team_run

        monkeypatch.setattr(team_run, "_asetup_session", AsyncMock(return_value=_paused_session()))
        monkeypatch.setattr(team_run, "_resolve_continue_owner_team", lambda *a, **k: "alice")
        resolved = AsyncMock()
        monkeypatch.setattr(team_run, "_aresolve_run_dependencies", resolved)

        def boom(*args, **kwargs):
            raise StopTest

        monkeypatch.setattr(team_run, "_resolve_continue_from_team", boom)

        team = MagicMock()
        team.save_response_to_file = None
        team.retries = 0
        run_context = _run_context()
        try:
            async for _event in team_run._acontinue_run_stream(
                team, session_id="s-1", run_context=run_context, run_id="r-1", user_id=None
            ):
                pass
        except Exception:
            pass

        resolved.assert_awaited_once_with(team, run_context=run_context)

    async def test_acontinue_run_skips_resolution_when_dependencies_none(self, monkeypatch):
        from agno.team import _run as team_run

        monkeypatch.setattr(team_run, "_asetup_session", AsyncMock(return_value=_paused_session()))
        monkeypatch.setattr(team_run, "_resolve_continue_owner_team", lambda *a, **k: "alice")
        resolved = AsyncMock()
        monkeypatch.setattr(team_run, "_aresolve_run_dependencies", resolved)

        def boom(*args, **kwargs):
            raise StopTest

        monkeypatch.setattr(team_run, "_resolve_continue_from_team", boom)

        team = MagicMock()
        team.save_response_to_file = None
        team.retries = 0
        run_context = RunContext(run_id="r-1", session_id="s-1", user_id=None)
        run_context.dependencies = None
        try:
            await team_run._acontinue_run(team, session_id="s-1", run_context=run_context, run_id="r-1", user_id=None)
        except Exception:
            pass

        resolved.assert_not_awaited()
