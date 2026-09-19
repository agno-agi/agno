"""AgentOS lifespans run their cleanup when the app body exits with an error."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.os.app import db_lifespan, http_client_lifespan, scheduler_lifespan


def _agent_os() -> MagicMock:
    agent_os = MagicMock()
    agent_os.auto_provision_dbs = False
    agent_os._close_databases = AsyncMock()
    agent_os._scheduler_base_url = "http://127.0.0.1:7777"
    agent_os._internal_service_token = "token"
    agent_os._scheduler_poll_interval = 15
    return agent_os


async def test_http_client_lifespan_closes_clients_when_body_raises():
    with patch("agno.utils.http.aclose_default_clients", new_callable=AsyncMock) as aclose:
        with pytest.raises(ValueError):
            async with http_client_lifespan(None):
                raise ValueError("boom")

    aclose.assert_awaited_once()


async def test_db_lifespan_drains_and_closes_when_body_raises():
    agent_os = _agent_os()
    with patch("agno.os.app._drain_cancel_persist_tasks", new_callable=AsyncMock) as drain:
        with pytest.raises(ValueError):
            async with db_lifespan(MagicMock(), agent_os):
                raise ValueError("boom")

    drain.assert_awaited_once()
    agent_os._close_databases.assert_awaited_once()


async def test_db_lifespan_closes_databases_when_drain_fails():
    agent_os = _agent_os()
    with patch(
        "agno.os.app._drain_cancel_persist_tasks",
        new_callable=AsyncMock,
        side_effect=RuntimeError("drain failed"),
    ):
        with pytest.raises(RuntimeError, match="drain failed"):
            async with db_lifespan(MagicMock(), agent_os):
                pass

    agent_os._close_databases.assert_awaited_once()


async def test_db_lifespan_normal_exit_still_drains_then_closes():
    agent_os = _agent_os()
    order = []
    agent_os._close_databases.side_effect = lambda: order.append("close")
    with patch(
        "agno.os.app._drain_cancel_persist_tasks",
        new_callable=AsyncMock,
        side_effect=lambda: order.append("drain"),
    ):
        async with db_lifespan(MagicMock(), agent_os):
            pass

    assert order == ["drain", "close"]


async def test_scheduler_lifespan_stops_poller_when_body_raises():
    poller = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    with (
        patch("agno.scheduler.ScheduleExecutor"),
        patch("agno.scheduler.SchedulePoller", return_value=poller),
    ):
        with pytest.raises(ValueError):
            async with scheduler_lifespan(MagicMock(), _agent_os()):
                raise ValueError("boom")

    poller.start.assert_awaited_once()
    poller.stop.assert_awaited_once()
