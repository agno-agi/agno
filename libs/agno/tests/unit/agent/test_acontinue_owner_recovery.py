"""A run_id-only ``acontinue_run`` must resume under the paused run's owner.

The sync dispatch reads the session and recovers the owner via
``_resolve_continue_owner``. The async dispatch cannot read the session (async
DB), so before the fix a run_id-only ``acontinue_run`` resumed with
``user_id=None`` — knowledge access ran unscoped (admin-wide) instead of under
the pausing user's scope. These tests pin the recovery inside the async
implementations, right after the session is first read.
"""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.run import RunContext  # noqa: E402


class StopTest(Exception):
    """Sentinel raised right after the owner-recovery point."""


def _paused_session(run_id="r-1", owner="alice"):
    session = MagicMock()
    session.runs = [SimpleNamespace(run_id=run_id, user_id=owner)]
    return session


def _run_context(run_id="r-1"):
    return RunContext(run_id=run_id, session_id="s-1", user_id=None)


@pytest.mark.asyncio
class TestAgentAsyncOwnerRecovery:
    async def test_acontinue_run_recovers_owner_from_session(self, monkeypatch):
        from agno.agent import _run as agent_run
        from agno.agent import _storage

        monkeypatch.setattr(_storage, "aread_or_create_session", AsyncMock(return_value=_paused_session()))

        def boom(agent, session=None):
            raise StopTest

        monkeypatch.setattr(_storage, "update_metadata", boom)

        agent = MagicMock()
        agent.save_response_to_file = None
        agent.retries = 0
        run_context = _run_context()
        try:
            await agent_run._acontinue_run(agent, session_id="s-1", run_context=run_context, run_id="r-1", user_id=None)
        except Exception:
            pass

        assert run_context.user_id == "alice", "run_id-only async resume must recover the paused run's owner"

    async def test_acontinue_run_stream_recovers_owner_from_session(self, monkeypatch):
        from agno.agent import _run as agent_run
        from agno.agent import _storage

        monkeypatch.setattr(_storage, "aread_or_create_session", AsyncMock(return_value=_paused_session()))

        def boom(agent, session=None):
            raise StopTest

        monkeypatch.setattr(_storage, "update_metadata", boom)

        agent = MagicMock()
        agent.save_response_to_file = None
        agent.retries = 0
        run_context = _run_context()
        try:
            async for _event in agent_run._acontinue_run_stream(
                agent, session_id="s-1", run_context=run_context, run_id="r-1", user_id=None
            ):
                pass
        except Exception:
            pass

        assert run_context.user_id == "alice"

    async def test_background_stream_recovers_owner_and_forwards_it(self):
        from agno.agent import _run as agent_run
        from agno.run.base import RunStatus

        session = _paused_session()
        session_run = MagicMock()
        session_run.status = RunStatus.paused
        session.get_run.return_value = session_run

        captured = {}

        async def fake_stream(agent, **kwargs):
            captured.update(kwargs)
            if False:  # pragma: no cover - makes this an async generator
                yield None

        stream = MagicMock()
        stream.register_run = AsyncMock()
        stream.set_run_status = AsyncMock()
        stream.add_event = AsyncMock(return_value=0)
        stream.complete_run = AsyncMock()

        agent = MagicMock()
        agent.save_response_to_file = None
        agent.db = None
        run_context = _run_context()

        with (
            patch("agno.agent._run._acontinue_run_stream", side_effect=fake_stream),
            patch("agno.agent._storage.aread_or_create_session", new_callable=AsyncMock, return_value=session),
            patch("agno.agent._storage.update_metadata"),
            patch("agno.agent._session.asave_run", new_callable=AsyncMock),
            patch("agno.agent._session.asave_session", new_callable=AsyncMock),
            patch("agno.os.event_streams.get_event_stream", return_value=stream),
            patch("agno.os.utils.format_sse_event_with_index", return_value="data: x\n\n"),
        ):
            async for _chunk in agent_run._acontinue_run_background_stream(
                agent, run_context=run_context, session_id="s-1", run_id="r-1"
            ):
                pass

        assert run_context.user_id == "alice"
        assert captured.get("user_id") == "alice", "the recovered owner must flow into the continue stream"

    async def test_explicit_user_id_is_never_overridden(self, monkeypatch):
        from agno.agent import _run as agent_run
        from agno.agent import _storage

        monkeypatch.setattr(_storage, "aread_or_create_session", AsyncMock(return_value=_paused_session()))

        def boom(agent, session=None):
            raise StopTest

        monkeypatch.setattr(_storage, "update_metadata", boom)

        agent = MagicMock()
        agent.save_response_to_file = None
        agent.retries = 0
        run_context = RunContext(run_id="r-1", session_id="s-1", user_id="bob")
        try:
            await agent_run._acontinue_run(
                agent, session_id="s-1", run_context=run_context, run_id="r-1", user_id="bob"
            )
        except Exception:
            pass

        assert run_context.user_id == "bob"


@pytest.mark.asyncio
class TestTeamAsyncOwnerRecovery:
    async def test_team_acontinue_run_recovers_owner_from_session(self, monkeypatch):
        from agno.team import _run as team_run

        monkeypatch.setattr(team_run, "_asetup_session", AsyncMock(return_value=_paused_session()))

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

        assert run_context.user_id == "alice"

    async def test_team_acontinue_run_stream_recovers_owner_from_session(self, monkeypatch):
        from agno.team import _run as team_run

        monkeypatch.setattr(team_run, "_asetup_session", AsyncMock(return_value=_paused_session()))

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

        assert run_context.user_id == "alice"
