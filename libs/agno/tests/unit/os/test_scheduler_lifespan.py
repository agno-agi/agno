from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI

from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.os.app import _db_supports_scheduler, scheduler_lifespan


def test_db_supports_scheduler_true_for_sqlite(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "scheduler.db"))
    assert _db_supports_scheduler(db) is True


def test_db_supports_scheduler_false_for_in_memory():
    db = InMemoryDb()
    assert _db_supports_scheduler(db) is False


@pytest.mark.asyncio
async def test_scheduler_lifespan_skips_unsupported_db():
    app = FastAPI()
    agent_os = SimpleNamespace(
        enable_scheduler=True,
        db=InMemoryDb(),
        scheduler_base_url="http://localhost:7777",
        _internal_service_token="test-token",
        scheduler_poll_interval=30,
        _scheduler_poller=None,
    )

    with patch("agno.scheduler.poller.SchedulePoller") as mock_poller_cls:
        async with scheduler_lifespan(app, agent_os):
            pass

    mock_poller_cls.assert_not_called()
    assert agent_os._scheduler_poller is None


@pytest.mark.asyncio
async def test_scheduler_lifespan_sets_runtime_poller(tmp_path):
    app = FastAPI()
    db = SqliteDb(db_file=str(tmp_path / "scheduler.db"))
    agent_os = SimpleNamespace(
        enable_scheduler=True,
        db=db,
        scheduler_base_url="http://localhost:7777",
        _internal_service_token="test-token",
        scheduler_poll_interval=30,
        _scheduler_poller=None,
    )

    fake_poller = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())

    with patch("agno.scheduler.poller.SchedulePoller", return_value=fake_poller) as mock_poller_cls:
        async with scheduler_lifespan(app, agent_os):
            assert agent_os._scheduler_poller is fake_poller
            assert app.state.scheduler_poller is fake_poller

    mock_poller_cls.assert_called_once()
    fake_poller.stop.assert_awaited_once()
    assert agent_os._scheduler_poller is None
    assert app.state.scheduler_poller is None
