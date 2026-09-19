"""Proposed upstream native teardown regressions; imports real Agno entry points."""

import asyncio
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import agno.os.app as app_module
import agno.scheduler as scheduler_module
import agno.utils.http as http_module


async def observe(kind, mode):
    names = {"db": "db_lifespan", "http": "http_client_lifespan", "scheduler": "scheduler_lifespan"}
    calls = []
    body_error = ValueError("fixture-body")
    cleanup_error = RuntimeError("fixture-cleanup")
    drain_error = RuntimeError("fixture-drain")
    cancelled_error = None
    body_fails = mode in ("body_error", "body_cleanup", "body_drain_cleanup")
    close_fails = mode in ("cleanup_error", "body_cleanup", "cancel_cleanup", "drain_cleanup", "body_drain_cleanup")
    drain_fails = mode in ("drain_error", "drain_cleanup", "body_drain_cleanup")
    cancels = mode in ("cancel", "cancel_cleanup")

    async def close():
        calls.append("close")
        await asyncio.sleep(0)
        if close_fails:
            raise cleanup_error

    async def drain():
        calls.append("drain")
        await asyncio.sleep(0)
        if drain_fails:
            raise drain_error

    cleanup = AsyncMock(side_effect=close)
    drain_mock = AsyncMock(side_effect=drain)
    poller = SimpleNamespace(start=AsyncMock(), stop=cleanup)
    owner = SimpleNamespace(
        auto_provision_dbs=False,
        _close_databases=cleanup,
        _scheduler_base_url="http://fixture.invalid",
        _internal_service_token="fixture-not-a-credential",
        db=None,
        _scheduler_poll_interval=15,
    )
    app = SimpleNamespace(state=SimpleNamespace())
    with ExitStack() as stack:
        stack.enter_context(patch.object(app_module, "_drain_cancel_persist_tasks", drain_mock))
        stack.enter_context(patch.object(http_module, "aclose_default_clients", cleanup))
        stack.enter_context(patch.object(scheduler_module, "ScheduleExecutor", return_value=object()))
        stack.enter_context(patch.object(scheduler_module, "SchedulePoller", return_value=poller))
        factory = getattr(app_module, names[kind])
        observed = None

        async def run():
            nonlocal cancelled_error
            async with factory(app) if kind == "http" else factory(app, owner):
                if body_fails:
                    raise body_error
                if cancels:
                    asyncio.current_task().cancel()
                    try:
                        await asyncio.sleep(0)
                    except asyncio.CancelledError as exc:
                        cancelled_error = exc
                        raise

        task = asyncio.create_task(run())
        try:
            await task
        except (ValueError, RuntimeError, asyncio.CancelledError) as exc:
            observed = exc
        cleanup.assert_awaited_once()
        assert calls == (["drain", "close"] if kind == "db" else ["close"])
        if kind == "db":
            drain_mock.assert_awaited_once()
        if kind == "scheduler":
            poller.start.assert_awaited_once()
        expected_chain = []
        if close_fails:
            expected_chain.append(cleanup_error)
        if drain_fails:
            expected_chain.append(drain_error)
        if body_fails:
            expected_chain.append(body_error)
        if cancels:
            assert cancelled_error is not None
            expected_chain.append(cancelled_error)
        actual_chain = []
        current = observed
        while current is not None:
            assert not any(current is previous for previous in actual_chain), "exception cycle"
            actual_chain.append(current)
            assert current.__cause__ is None and not current.__suppress_context__
            current = current.__context__
        assert len(actual_chain) == len(expected_chain), (kind, mode, actual_chain)
        assert all(actual is expected for actual, expected in zip(actual_chain, expected_chain))
        assert task.cancelled() == (cancels and not close_fails)


@pytest.mark.parametrize(
    "kind,mode",
    [
        ("db", "normal"),
        ("db", "body_error"),
        ("db", "cancel"),
        ("db", "cleanup_error"),
        ("db", "body_cleanup"),
        ("db", "cancel_cleanup"),
        ("db", "drain_error"),
        ("db", "drain_cleanup"),
        ("db", "body_drain_cleanup"),
        ("http", "normal"),
        ("http", "body_error"),
        ("http", "cancel"),
        ("http", "cleanup_error"),
        ("http", "body_cleanup"),
        ("http", "cancel_cleanup"),
        ("scheduler", "normal"),
        ("scheduler", "body_error"),
        ("scheduler", "cancel"),
        ("scheduler", "cleanup_error"),
        ("scheduler", "body_cleanup"),
        ("scheduler", "cancel_cleanup"),
    ],
)
def test_native_teardown(kind, mode):
    asyncio.run(observe(kind, mode))
