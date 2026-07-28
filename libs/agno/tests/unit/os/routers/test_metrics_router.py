from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import APIRouter

from agno.os.routers.metrics import metrics as metrics_router
from agno.os.routers.metrics.metrics import attach_routes


def _route_endpoint(path: str):
    router = attach_routes(APIRouter(), dbs={})
    route = next(route for route in router.routes if getattr(route, "path", None) == path)
    return route.endpoint


@pytest.mark.asyncio
async def test_refresh_metrics_runs_sync_db_in_threadpool(monkeypatch):
    sync_db = SimpleNamespace(calculate_metrics=Mock(return_value=[]))
    get_db = AsyncMock(return_value=sync_db)
    run_in_threadpool = AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))

    monkeypatch.setattr(metrics_router, "get_db", get_db)
    monkeypatch.setattr(metrics_router, "run_in_threadpool", run_in_threadpool)

    endpoint = _route_endpoint("/metrics/refresh")
    request = Mock()
    request.state = SimpleNamespace()

    result = await endpoint(request=request, db_id="db-1", table=None)

    assert result == []
    get_db.assert_awaited_once_with({}, "db-1", None)
    run_in_threadpool.assert_awaited_once()
    sync_db.calculate_metrics.assert_called_once_with()


@pytest.mark.asyncio
async def test_get_metrics_runs_sync_db_in_threadpool(monkeypatch):
    sync_db = SimpleNamespace(get_metrics=Mock(return_value=([], None)))
    get_db = AsyncMock(return_value=sync_db)
    run_in_threadpool = AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))

    monkeypatch.setattr(metrics_router, "get_db", get_db)
    monkeypatch.setattr(metrics_router, "run_in_threadpool", run_in_threadpool)

    endpoint = _route_endpoint("/metrics")
    request = Mock()
    request.state = SimpleNamespace()

    result = await endpoint(request=request, starting_date=None, ending_date=None, db_id="db-1", table=None)

    assert result.metrics == []
    get_db.assert_awaited_once_with({}, "db-1", None)
    run_in_threadpool.assert_awaited_once()
    sync_db.get_metrics.assert_called_once_with(starting_date=None, ending_date=None)
