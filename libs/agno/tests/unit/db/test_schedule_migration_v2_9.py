"""Schedule provenance and uniqueness migration tests for 2.9."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from agno.db.migrations.manager import MigrationManager
from agno.db.migrations.versions import v2_9_0
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.schemas.scheduler import ScheduleNameConflictError
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb


def _create_legacy_schedule_table(path: Path, names: list[str]) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE agno_schedules (
                id TEXT PRIMARY KEY NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                method TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                payload JSON,
                cron_expr TEXT NOT NULL,
                timezone TEXT NOT NULL,
                timeout_seconds BIGINT NOT NULL,
                max_retries BIGINT NOT NULL,
                retry_delay_seconds BIGINT NOT NULL,
                enabled BOOLEAN NOT NULL,
                next_run_at BIGINT,
                locked_by TEXT,
                locked_at BIGINT,
                created_at BIGINT NOT NULL,
                updated_at BIGINT
            )
            """
        )
        for index, name in enumerate(names):
            connection.execute(
                """
                INSERT INTO agno_schedules (
                    id, name, method, endpoint, cron_expr, timezone,
                    timeout_seconds, max_retries, retry_delay_seconds,
                    enabled, created_at
                ) VALUES (?, ?, 'POST', '/external', '0 9 * * *', 'UTC', 3600, 0, 60, 1, 1)
                """,
                (f"schedule-{index}", name),
            )


def _studio_schedule(schedule_id: str = "studio-schedule") -> dict:
    return {
        "id": schedule_id,
        "name": "Private Studio schedule",
        "method": "POST",
        "endpoint": "/agents/private-agent/runs",
        "payload": {"message": "private prompt"},
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "managed_by": "studio",
        "owner_actor_id": "actor-1",
        "target_type": "agent",
        "target_id": "private-agent",
        "enabled": True,
        "created_at": 1,
    }


def _studio_schedule_run(schedule_id: str = "studio-schedule") -> dict:
    return {
        "id": "studio-run",
        "schedule_id": schedule_id,
        "attempt": 1,
        "status": "success",
        "input": {"message": "private prompt"},
        "output": {"content": "private response"},
        "created_at": 1,
    }


def test_sync_sqlite_upgrade_preserves_generic_rows_and_enforces_unique_names(tmp_path: Path):
    class CustomSqliteDb(SqliteDb):
        pass

    db_path = tmp_path / "legacy-sync.sqlite"
    _create_legacy_schedule_table(db_path, ["legacy-one", "legacy-two"])
    db = CustomSqliteDb(db_file=str(db_path))

    assert v2_9_0.up(db, "schedules", db.schedules_table_name) is True
    assert v2_9_0.up(db, "schedules", db.schedules_table_name) is False

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agno_schedules)")}
        row = connection.execute(
            "SELECT managed_by, owner_actor_id, target_type, target_id FROM agno_schedules WHERE id='schedule-0'"
        ).fetchone()
        unique_indexes = {
            index[1] for index in connection.execute("PRAGMA index_list(agno_schedules)") if index[2] == 1
        }

    assert set(v2_9_0._PROVENANCE_COLUMNS).issubset(columns)
    assert row == (None, None, None, None)
    assert "agno_schedules_uq_name" in unique_indexes

    first = db.get_schedule("schedule-0")
    assert first is not None
    assert first["managed_by"] is None
    with pytest.raises(ScheduleNameConflictError):
        db.update_schedule("schedule-1", name="legacy-one")
    assert v2_9_0.down(db, "schedules", db.schedules_table_name) is True


def test_sync_sqlite_down_refuses_to_expose_studio_schedule_and_run_history(tmp_path: Path):
    db_path = tmp_path / "studio-sync.sqlite"
    db = SqliteDb(db_file=str(db_path))
    db.create_schedule(_studio_schedule())
    db.create_schedule_run(_studio_schedule_run())

    with pytest.raises(ValueError, match="Cannot remove Studio schedule provenance"):
        v2_9_0.down(db, "schedules", db.schedules_table_name)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agno_schedules)")}
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(agno_schedules)")}
        schedule = connection.execute(
            "SELECT managed_by, owner_actor_id, payload FROM agno_schedules WHERE id='studio-schedule'"
        ).fetchone()
        run = connection.execute("SELECT input, output FROM agno_schedule_runs WHERE id='studio-run'").fetchone()

    assert set(v2_9_0._PROVENANCE_COLUMNS).issubset(columns)
    assert "agno_schedules_uq_name" in indexes
    assert schedule is not None and schedule[:2] == ("studio", "actor-1")
    assert run is not None

    assert db.delete_schedule("studio-schedule") is True
    assert v2_9_0.down(db, "schedules", db.schedules_table_name) is True


def test_sync_sqlite_upgrade_fails_clearly_without_partially_migrating_duplicates(tmp_path: Path):
    db_path = tmp_path / "legacy-duplicates.sqlite"
    _create_legacy_schedule_table(db_path, ["duplicate", "duplicate"])
    db = SqliteDb(db_file=str(db_path))

    with pytest.raises(ValueError, match="duplicate names already exist"):
        v2_9_0.up(db, "schedules", db.schedules_table_name)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agno_schedules)")}
    assert set(v2_9_0._PROVENANCE_COLUMNS).isdisjoint(columns)


@pytest.mark.asyncio
async def test_async_sqlite_upgrade_preserves_generic_rows_and_enforces_unique_names(tmp_path: Path):
    class CustomAsyncSqliteDb(AsyncSqliteDb):
        pass

    db_path = tmp_path / "legacy-async.sqlite"
    _create_legacy_schedule_table(db_path, ["legacy-one"])
    db = CustomAsyncSqliteDb(db_file=str(db_path))
    try:
        assert await v2_9_0.async_up(db, "schedules", db.schedules_table_name) is True
        async with db.async_session_factory() as session:
            columns = {row[1] for row in (await session.execute(text("PRAGMA table_info(agno_schedules)"))).fetchall()}
            row = (
                await session.execute(
                    text("SELECT managed_by, owner_actor_id FROM agno_schedules WHERE id='schedule-0'")
                )
            ).fetchone()
        assert set(v2_9_0._PROVENANCE_COLUMNS).issubset(columns)
        assert tuple(row) == (None, None)
        assert await v2_9_0.async_down(db, "schedules", db.schedules_table_name) is True
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_async_sqlite_down_refuses_to_expose_studio_schedule_and_run_history(tmp_path: Path):
    db_path = tmp_path / "studio-async.sqlite"
    db = AsyncSqliteDb(db_file=str(db_path))
    try:
        await db.create_schedule(_studio_schedule())
        await db.create_schedule_run(_studio_schedule_run())

        with pytest.raises(ValueError, match="Cannot remove Studio schedule provenance"):
            await v2_9_0.async_down(db, "schedules", db.schedules_table_name)

        async with db.async_session_factory() as session:
            columns = {row[1] for row in (await session.execute(text("PRAGMA table_info(agno_schedules)"))).fetchall()}
            indexes = {row[1] for row in (await session.execute(text("PRAGMA index_list(agno_schedules)"))).fetchall()}
            schedule = (
                await session.execute(
                    text("SELECT managed_by, owner_actor_id, payload FROM agno_schedules WHERE id='studio-schedule'")
                )
            ).fetchone()
            run = (
                await session.execute(text("SELECT input, output FROM agno_schedule_runs WHERE id='studio-run'"))
            ).fetchone()

        assert set(v2_9_0._PROVENANCE_COLUMNS).issubset(columns)
        assert "agno_schedules_uq_name" in indexes
        assert schedule is not None and tuple(schedule[:2]) == ("studio", "actor-1")
        assert run is not None

        assert await db.delete_schedule("studio-schedule") is True
        assert await v2_9_0.async_down(db, "schedules", db.schedules_table_name) is True
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_migration_manager_includes_schedule_tables(tmp_path: Path):
    db_path = tmp_path / "legacy-manager.sqlite"
    _create_legacy_schedule_table(db_path, ["legacy-one"])
    db = SqliteDb(db_file=str(db_path))

    await MigrationManager(db).up(target_version="2.9.0", table_type="schedules")

    assert db.get_latest_schema_version(db.schedules_table_name) == "2.9.0"
    assert db.get_schedule("schedule-0") is not None

    await MigrationManager(db).down(target_version="2.5.6", table_type="schedules")

    assert db.get_latest_schema_version(db.schedules_table_name) == "2.5.6"
    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agno_schedules)")}
    assert set(v2_9_0._PROVENANCE_COLUMNS).isdisjoint(columns)


@pytest.mark.asyncio
async def test_migration_manager_keeps_version_when_studio_downgrade_is_refused(tmp_path: Path):
    db_path = tmp_path / "studio-manager.sqlite"
    db = SqliteDb(db_file=str(db_path))
    db.create_schedule(_studio_schedule())
    db.create_schedule_run(_studio_schedule_run())
    db.upsert_schema_version(db.schedules_table_name, "2.9.0")

    with pytest.raises(ValueError, match="Cannot remove Studio schedule provenance"):
        await MigrationManager(db).down(target_version="2.5.6", table_type="schedules")

    assert db.get_latest_schema_version(db.schedules_table_name) == "2.9.0"
    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agno_schedules)")}
        assert connection.execute("SELECT 1 FROM agno_schedule_runs WHERE id='studio-run'").fetchone() == (1,)
    assert set(v2_9_0._PROVENANCE_COLUMNS).issubset(columns)


@pytest.mark.asyncio
async def test_fresh_sqlite_unique_name_index_is_reversible(tmp_path: Path):
    db_path = tmp_path / "fresh-manager.sqlite"
    db = SqliteDb(db_file=str(db_path))
    db.create_schedule(
        {
            "id": "schedule-0",
            "name": "reusable-after-down",
            "method": "POST",
            "endpoint": "/external",
            "cron_expr": "0 9 * * *",
            "timezone": "UTC",
            "timeout_seconds": 3600,
            "max_retries": 0,
            "retry_delay_seconds": 60,
            "enabled": True,
            "created_at": 1,
        }
    )

    with sqlite3.connect(db_path) as connection:
        indexes_before = {row[1] for row in connection.execute("PRAGMA index_list(agno_schedules)")}
    assert "agno_schedules_uq_name" in indexes_before

    await MigrationManager(db).down(target_version="2.5.6", table_type="schedules")

    with sqlite3.connect(db_path) as connection:
        indexes_after = {row[1] for row in connection.execute("PRAGMA index_list(agno_schedules)")}
        connection.execute(
            """
            INSERT INTO agno_schedules (
                id, name, method, endpoint, cron_expr, timezone,
                timeout_seconds, max_retries, retry_delay_seconds,
                enabled, created_at
            ) VALUES ('schedule-1', 'reusable-after-down', 'POST', '/external',
                      '0 9 * * *', 'UTC', 3600, 0, 60, 1, 1)
            """
        )

    assert "agno_schedules_uq_name" not in indexes_after
    assert v2_9_0.down(db, "schedules", db.schedules_table_name) is False


def test_sync_sqlite_down_is_safe_when_schedule_table_was_never_created(tmp_path: Path):
    db = SqliteDb(db_file=str(tmp_path / "missing-sync.sqlite"))

    assert v2_9_0.down(db, "schedules", db.schedules_table_name) is False


@pytest.mark.asyncio
async def test_async_sqlite_down_is_idempotent_and_missing_table_safe(tmp_path: Path):
    db_path = tmp_path / "missing-async.sqlite"
    db = AsyncSqliteDb(db_file=str(db_path))
    try:
        assert await v2_9_0.async_down(db, "schedules", db.schedules_table_name) is False
        _create_legacy_schedule_table(db_path, ["legacy-one"])
        assert await v2_9_0.async_up(db, "schedules", db.schedules_table_name) is True
        assert await v2_9_0.async_down(db, "schedules", db.schedules_table_name) is True
        assert await v2_9_0.async_down(db, "schedules", db.schedules_table_name) is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_migration_manager_does_not_log_backend_exception_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db = SqliteDb(db_file=str(tmp_path / "redaction.sqlite"))
    secret = "postgresql://admin:private-password@internal.example/agno"
    logs: list[str] = []

    def fail_migration(_db, _table_type: str, _table_name: str) -> bool:
        raise RuntimeError(secret)

    monkeypatch.setattr(v2_9_0, "up", fail_migration)
    monkeypatch.setattr("agno.db.migrations.manager.log_error", logs.append)

    with pytest.raises(RuntimeError, match="private-password"):
        await MigrationManager(db)._up_migration("v2_9_0", "schedules", db.schedules_table_name)

    assert logs == ["Migration to version v2_9_0 failed"]
    assert secret not in "".join(logs)


@pytest.mark.asyncio
async def test_postgres_dispatch_covers_sync_and_async(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    class CustomPostgresDb(PostgresDb):
        pass

    class CustomAsyncPostgresDb(AsyncPostgresDb):
        pass

    monkeypatch.setattr(
        v2_9_0,
        "_migrate_postgres",
        lambda _db, table_name: calls.append(("sync", table_name)) or True,
    )

    async def migrate_async(_db, table_name: str) -> bool:
        calls.append(("async", table_name))
        return True

    monkeypatch.setattr(v2_9_0, "_migrate_async_postgres", migrate_async)

    monkeypatch.setattr(
        v2_9_0,
        "_revert_postgres",
        lambda _db, table_name: calls.append(("sync-down", table_name)) or True,
    )

    async def revert_async(_db, table_name: str) -> bool:
        calls.append(("async-down", table_name))
        return True

    monkeypatch.setattr(v2_9_0, "_revert_async_postgres", revert_async)

    sync_db = object.__new__(CustomPostgresDb)
    async_db = object.__new__(CustomAsyncPostgresDb)

    assert v2_9_0.up(sync_db, "schedules", "agno_schedules") is True
    assert await v2_9_0.async_up(async_db, "schedules", "agno_schedules") is True
    assert v2_9_0.down(sync_db, "schedules", "agno_schedules") is True
    assert await v2_9_0.async_down(async_db, "schedules", "agno_schedules") is True
    assert calls == [
        ("sync", "agno_schedules"),
        ("async", "agno_schedules"),
        ("sync-down", "agno_schedules"),
        ("async-down", "agno_schedules"),
    ]

    assert v2_9_0.up(SimpleNamespace(), "sessions", "agno_sessions") is False  # type: ignore[arg-type]
