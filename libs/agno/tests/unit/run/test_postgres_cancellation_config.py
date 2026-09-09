from unittest.mock import AsyncMock, patch

import pytest

from agno.db.postgres import PostgresDb
from agno.run.cancellation_management import PostgresRunCancellationManager


@pytest.mark.parametrize(
    "option,value", [("poll_interval", 0), ("ttl_seconds", -1), ("ttl_seconds", float("inf")), ("poll_interval", True)]
)
def test_invalid_intervals(option, value):
    db = PostgresDb(db_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused")
    with pytest.raises(ValueError):
        PostgresRunCancellationManager(db, namespace="test", **{option: value})


def test_setup_is_explicit():
    db = PostgresDb(db_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused")
    with patch.object(db.db_engine, "begin") as connect:
        manager = PostgresRunCancellationManager(db, namespace="test")
        with pytest.raises(ValueError, match="setup"):
            manager.is_cancelled("run")
        connect.assert_not_called()


async def test_worker_exhaustion_does_not_fail_terminal_cleanup():
    db = PostgresDb(db_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused")
    manager = PostgresRunCancellationManager(db, namespace="test")
    manager._ready = True
    with (
        patch(
            "agno.run.cancellation_management.postgres_cancellation_manager._WORKERS.run_sync", side_effect=TimeoutError
        ),
        patch(
            "agno.run.cancellation_management.postgres_cancellation_manager._WORKERS.run",
            new=AsyncMock(side_effect=TimeoutError),
        ),
    ):
        assert not manager.is_cancelled("run")
        assert not await manager.ais_cancelled("run")
        manager.cleanup_run("run")
        await manager.acleanup_run("run")
        manager.cleanup_member_runs("team")
        await manager.acleanup_member_runs("team")
        with pytest.raises(TimeoutError):
            manager.cancel_run("run")
