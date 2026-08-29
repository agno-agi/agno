"""Scheduler-table tests for SqliteDb and AsyncSqliteDb get_schedules."""

import time
from uuid import uuid4

import pytest

from agno.db.sqlite import AsyncSqliteDb, SqliteDb


def _schedule_data(**overrides):
    now = int(time.time())
    d = {
        "id": str(uuid4()),
        "name": f"schedule-{uuid4()}",
        "description": None,
        "method": "POST",
        "endpoint": "/agents/a1/runs",
        "payload": None,
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "next_run_at": now + 3600,
        "locked_by": None,
        "locked_at": None,
        "created_at": now,
        "updated_at": None,
    }
    d.update(overrides)
    return d


@pytest.fixture
def sqlite_db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "test.db"))


@pytest.fixture
def async_sqlite_db(tmp_path):
    return AsyncSqliteDb(db_file=str(tmp_path / "test_async.db"))


# =============================================================================
# Sync SqliteDb
# =============================================================================


def test_sqlite_get_schedules_roundtrip_with_raise_on_error(sqlite_db):
    created = sqlite_db.create_schedule(_schedule_data(name="nightly"))

    schedules, total = sqlite_db.get_schedules(raise_on_error=True)

    assert total == 1
    assert schedules[0]["id"] == created["id"]


def test_sqlite_get_schedules_default_swallows_error(sqlite_db, monkeypatch):
    def _boom(table_type, create_table_if_not_found=False):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(sqlite_db, "_get_table", _boom)

    assert sqlite_db.get_schedules() == ([], 0)


def test_sqlite_get_schedules_raise_on_error_reraises(sqlite_db, monkeypatch):
    def _boom(table_type, create_table_if_not_found=False):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(sqlite_db, "_get_table", _boom)

    with pytest.raises(RuntimeError, match="forced failure"):
        sqlite_db.get_schedules(raise_on_error=True)


def test_sqlite_get_schedules_table_none_default_returns_empty(sqlite_db, monkeypatch):
    monkeypatch.setattr(sqlite_db, "_get_table", lambda table_type, create_table_if_not_found=False: None)

    assert sqlite_db.get_schedules() == ([], 0)


def test_sqlite_get_schedules_table_none_raises_under_flag(sqlite_db, monkeypatch):
    monkeypatch.setattr(sqlite_db, "_get_table", lambda table_type, create_table_if_not_found=False: None)

    with pytest.raises(RuntimeError, match="schedules table unavailable"):
        sqlite_db.get_schedules(raise_on_error=True)


def test_sqlite_get_schedules_never_created_table_raises_under_flag(sqlite_db):
    # A fresh DB without the schedules table counts as unavailable for strict callers
    with pytest.raises(RuntimeError, match="schedules table unavailable"):
        sqlite_db.get_schedules(raise_on_error=True)


# =============================================================================
# Async AsyncSqliteDb
# =============================================================================


@pytest.mark.asyncio
async def test_async_sqlite_get_schedules_roundtrip_with_raise_on_error(async_sqlite_db):
    created = await async_sqlite_db.create_schedule(_schedule_data(name="nightly"))

    schedules, total = await async_sqlite_db.get_schedules(raise_on_error=True)

    assert total == 1
    assert schedules[0]["id"] == created["id"]


@pytest.mark.asyncio
async def test_async_sqlite_get_schedules_default_swallows_error(async_sqlite_db, monkeypatch):
    async def _boom(table_type, create_table_if_not_found=False):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(async_sqlite_db, "_get_table", _boom)

    assert await async_sqlite_db.get_schedules() == ([], 0)


@pytest.mark.asyncio
async def test_async_sqlite_get_schedules_raise_on_error_reraises(async_sqlite_db, monkeypatch):
    async def _boom(table_type, create_table_if_not_found=False):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(async_sqlite_db, "_get_table", _boom)

    with pytest.raises(RuntimeError, match="forced failure"):
        await async_sqlite_db.get_schedules(raise_on_error=True)


@pytest.mark.asyncio
async def test_async_sqlite_get_schedules_table_none_default_returns_empty(async_sqlite_db, monkeypatch):
    async def _none(table_type, create_table_if_not_found=False):
        return None

    monkeypatch.setattr(async_sqlite_db, "_get_table", _none)

    assert await async_sqlite_db.get_schedules() == ([], 0)


@pytest.mark.asyncio
async def test_async_sqlite_get_schedules_table_none_raises_under_flag(async_sqlite_db, monkeypatch):
    async def _none(table_type, create_table_if_not_found=False):
        return None

    monkeypatch.setattr(async_sqlite_db, "_get_table", _none)

    with pytest.raises(RuntimeError, match="schedules table unavailable"):
        await async_sqlite_db.get_schedules(raise_on_error=True)


@pytest.mark.asyncio
async def test_async_sqlite_get_schedules_never_created_table_raises_under_flag(async_sqlite_db):
    # A fresh DB without the schedules table counts as unavailable for strict callers
    with pytest.raises(RuntimeError, match="schedules table unavailable"):
        await async_sqlite_db.get_schedules(raise_on_error=True)


# =============================================================================
# ScheduleManager end-to-end over sqlite
# =============================================================================


def test_manager_list_all_over_sqlite(sqlite_db):
    pytest.importorskip("croniter", reason="croniter not installed")
    pytest.importorskip("pytz", reason="pytz not installed")
    from agno.scheduler.manager import ScheduleManager

    mgr = ScheduleManager(sqlite_db)
    for i in range(3):
        sqlite_db.create_schedule(_schedule_data(name=f"schedule-{i}"))

    result = mgr.list_all()

    assert {s.name for s in result} == {"schedule-0", "schedule-1", "schedule-2"}


def test_manager_list_all_paginates_tied_created_at_without_loss(sqlite_db):
    # Every schedule shares the same created_at second, so pagination must rely on
    # the unique (created_at, id) sort to page across 250 rows with no dup or gap.
    pytest.importorskip("croniter", reason="croniter not installed")
    pytest.importorskip("pytz", reason="pytz not installed")
    from agno.scheduler.manager import ScheduleManager

    same_second = int(time.time())
    expected_ids = set()
    for i in range(250):
        created = sqlite_db.create_schedule(_schedule_data(name=f"schedule-{i}", created_at=same_second))
        expected_ids.add(created["id"])

    ids = [s.id for s in ScheduleManager(sqlite_db).list_all()]

    assert len(ids) == 250
    assert len(set(ids)) == 250
    assert set(ids) == expected_ids
