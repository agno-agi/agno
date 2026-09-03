"""cleanup_run/acleanup_run must FAIL OPEN on Redis faults (parity with
is_cancelled): they run inside terminal paths (producers' finally blocks,
continue/requeue seams) where a coordination blip must not fail the
surrounding operation - a stale key just lives until its TTL."""

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("redis", reason="redis not installed")

from agno.run.cancellation_management.redis_cancellation_manager import (  # noqa: E402
    RedisRunCancellationManager,
)


def test_cleanup_run_fails_open_on_redis_fault():
    client = MagicMock()
    client.delete.side_effect = ConnectionError("redis down")
    manager = RedisRunCancellationManager(redis_client=client)
    manager.cleanup_run("r1")  # must not raise


@pytest.mark.asyncio
async def test_acleanup_run_fails_open_on_redis_fault():
    client = MagicMock()
    client.delete = AsyncMock(side_effect=ConnectionError("redis down"))
    manager = RedisRunCancellationManager(async_redis_client=client)
    await manager.acleanup_run("r1")  # must not raise


class TestMemberRunMethodsFailOpen:
    """register_member_run/cleanup_member_runs (+async twins) sit inside
    member-delegation tool execution and team finalize - the two places a
    coordination raise turns a HEALTHY team run into an error. They were the
    only sibling methods missed by the fail-open treatment."""

    def test_register_member_run_fails_open(self):
        client = MagicMock()
        client.pipeline.side_effect = ConnectionError("redis down")
        manager = RedisRunCancellationManager(redis_client=client)
        manager.register_member_run("tr1", "mr1")  # must not raise

    @pytest.mark.asyncio
    async def test_aregister_member_run_fails_open(self):
        client = MagicMock()
        client.pipeline.side_effect = ConnectionError("redis down")
        manager = RedisRunCancellationManager(async_redis_client=client)
        await manager.aregister_member_run("tr1", "mr1")  # must not raise

    def test_cleanup_member_runs_fails_open(self):
        client = MagicMock()
        client.delete.side_effect = ConnectionError("redis down")
        manager = RedisRunCancellationManager(redis_client=client)
        manager.cleanup_member_runs("tr1")  # must not raise

    @pytest.mark.asyncio
    async def test_acleanup_member_runs_fails_open(self):
        client = MagicMock()
        client.delete = AsyncMock(side_effect=ConnectionError("redis down"))
        manager = RedisRunCancellationManager(async_redis_client=client)
        await manager.acleanup_member_runs("tr1")  # must not raise


class TestTeamFinalizeSurvivesRedisBlip:
    """The seam the finding names: team finalize calls cleanup_member_runs
    BEFORE the terminal save, so an unguarded raise errored out a run that
    had already succeeded - the successful output was never persisted."""

    @pytest.fixture()
    def broken_manager(self):
        from agno.run.cancel import get_cancellation_manager, set_cancellation_manager

        client = MagicMock()
        client.delete.side_effect = ConnectionError("redis down")
        client.pipeline.side_effect = ConnectionError("redis down")
        prior = get_cancellation_manager()
        set_cancellation_manager(RedisRunCancellationManager(redis_client=client))
        yield
        set_cancellation_manager(prior)

    def test_finalize_persists_successful_run_through_blip(self, broken_manager, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.run.base import RunStatus
        from agno.run.team import TeamRunOutput
        from agno.session import TeamSession
        from agno.team import Team
        from agno.team._run import _cleanup_and_store

        db = SqliteDb(db_file=str(tmp_path / "t.db"))
        team = Team(id="t1", name="T", members=[], db=db)
        run_response = TeamRunOutput(
            run_id="tr-blip", session_id="s-blip", team_id="t1", status=RunStatus.completed, content="done"
        )
        import time

        session = TeamSession(session_id="s-blip", team_id="t1", runs=[], created_at=int(time.time()))

        _cleanup_and_store(team, run_response, session)  # must not raise

        stored = db.get_session(session_id="s-blip", session_type="team")
        assert stored is not None
        stored_run = stored.get_run("tr-blip")
        assert stored_run is not None and stored_run.status == RunStatus.completed, (
            "the successful run must persist through the coordination blip"
        )
