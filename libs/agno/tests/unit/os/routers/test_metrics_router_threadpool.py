"""
Unit tests for the Metrics router event-loop safety.

Regression tests for #9091: the synchronous ``BaseDb`` metrics calls in the
``GET /metrics`` and ``POST /metrics/refresh`` endpoints must be dispatched to
a worker thread (via ``run_in_threadpool``) so a slow/blocking database call
does not stall the event loop and starve every other request.
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import BaseDb
from agno.os.routers.metrics.metrics import get_metrics_router
from agno.os.settings import AgnoAPISettings


def _create_mock_db_class():
    """Create a concrete BaseDb subclass with all abstract methods stubbed."""
    abstract_methods = {}
    for name in dir(BaseDb):
        attr = getattr(BaseDb, name, None)
        if getattr(attr, "__isabstractmethod__", False):
            abstract_methods[name] = MagicMock()
    return type("MockDb", (BaseDb,), abstract_methods)


@pytest.fixture
def mock_db():
    MockDbClass = _create_mock_db_class()
    db = MockDbClass()
    db.id = "test-db"
    db.to_dict = MagicMock(return_value={"type": "postgres", "id": "test-db"})
    return db


@pytest.fixture
def settings():
    # No security key => auth disabled.
    return AgnoAPISettings()


@pytest.fixture
def client(mock_db, settings):
    app = FastAPI()
    router = get_metrics_router(dbs={"test-db": [mock_db]}, settings=settings)
    app.include_router(router)
    return TestClient(app)


def test_get_metrics_runs_sync_db_call_off_event_loop(client, mock_db):
    """The blocking get_metrics call must run on a worker thread, not the loop thread."""
    call_thread_id = {"id": None}

    def _blocking_get_metrics(starting_date=None, ending_date=None):
        call_thread_id["id"] = threading.get_ident()
        return ([], None)

    mock_db.get_metrics = _blocking_get_metrics

    resp = client.get("/metrics")

    assert resp.status_code == 200
    # The sync DB call must have executed on a different thread than the caller.
    assert call_thread_id["id"] is not None
    assert call_thread_id["id"] != threading.get_ident()


def test_refresh_metrics_runs_sync_db_call_off_event_loop(client, mock_db):
    """The blocking calculate_metrics call must run on a worker thread, not the loop thread."""
    call_thread_id = {"id": None}

    def _blocking_calculate_metrics():
        call_thread_id["id"] = threading.get_ident()
        return []

    mock_db.calculate_metrics = _blocking_calculate_metrics

    resp = client.post("/metrics/refresh")

    assert resp.status_code == 200
    assert call_thread_id["id"] is not None
    assert call_thread_id["id"] != threading.get_ident()


def test_blocking_refresh_does_not_starve_other_requests(client, mock_db):
    """A slow /metrics/refresh must not block concurrent requests on the event loop."""

    def _slow_calculate_metrics():
        time.sleep(0.5)
        return []

    def _fast_get_metrics(starting_date=None, ending_date=None):
        return ([], None)

    mock_db.calculate_metrics = _slow_calculate_metrics
    mock_db.get_metrics = _fast_get_metrics

    async def _run():
        loop = asyncio.get_event_loop()

        def _post_refresh():
            return client.post("/metrics/refresh")

        def _get_metrics():
            return client.get("/metrics")

        start = time.perf_counter()
        slow = loop.run_in_executor(None, _post_refresh)
        # Give the slow request a head start so it is mid-flight.
        await asyncio.sleep(0.05)
        fast_start = time.perf_counter()
        fast = loop.run_in_executor(None, _get_metrics)
        fast_resp = await fast
        fast_elapsed = time.perf_counter() - fast_start
        slow_resp = await slow
        return slow_resp, fast_resp, fast_elapsed, time.perf_counter() - start

    slow_resp, fast_resp, fast_elapsed, _ = asyncio.run(_run())

    assert slow_resp.status_code == 200
    assert fast_resp.status_code == 200
    # The fast request must return well before the slow one finishes (0.5s),
    # proving the event loop was not blocked by the sync DB call.
    assert fast_elapsed < 0.4
