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


def _generic_schedule(schedule_id: str = "generic-schedule") -> dict:
    schedule = _studio_schedule(schedule_id)
    schedule.update(
        name="Generic schedule",
        endpoint="/external",
        payload=None,
        managed_by=None,
        owner_actor_id=None,
        target_type=None,
        target_id=None,
    )
    return schedule


def _install_caller_owned_schedule_schema(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE agno_schedules ADD COLUMN caller_note TEXT DEFAULT 'keep-me'")
        connection.execute("CREATE INDEX caller_schedule_endpoint_idx ON agno_schedules (endpoint)")
        connection.execute(
            "CREATE TABLE caller_schedule_audit (schedule_id TEXT NOT NULL, old_note TEXT, new_note TEXT)"
        )
        connection.execute(
            """
            CREATE TRIGGER caller_schedule_update_audit
            AFTER UPDATE ON agno_schedules
            BEGIN
                INSERT INTO caller_schedule_audit (schedule_id, old_note, new_note)
                VALUES (OLD.id, OLD.caller_note, NEW.caller_note);
            END
            """
        )


def _sqlite_schedule_state(path: Path) -> tuple:
    with sqlite3.connect(path) as connection:
        schema = tuple(
            connection.execute(
                """
                SELECT type, name, tbl_name, sql
                FROM sqlite_master
                WHERE tbl_name = 'agno_schedules'
                   OR name IN ('agno_schedules', 'caller_schedule_audit', 'agno_schedules__v2_9_down')
                ORDER BY type, name
                """
            )
        )
        columns = tuple(connection.execute("PRAGMA table_xinfo(agno_schedules)"))
        schedule = connection.execute("SELECT * FROM agno_schedules WHERE id='generic-schedule'").fetchone()
        audit_rows = tuple(connection.execute("SELECT * FROM caller_schedule_audit"))
    return schema, columns, schedule, audit_rows


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

    assert set(v2_9_0._V2_9_COLUMNS).issubset(columns)
    assert row == (None, None, None, None)
    assert {
        "agno_schedules_uq_generic_name",
        "agno_schedules_uq_studio_owner_name",
    }.issubset(unique_indexes)

    first = db.get_schedule("schedule-0")
    assert first is not None
    assert first["managed_by"] is None
    with pytest.raises(ScheduleNameConflictError):
        db.update_schedule("schedule-1", name="legacy-one")
    assert v2_9_0.down(db, "schedules", db.schedules_table_name) is True


def test_sync_sqlite_down_refuses_caller_owned_schema_without_partial_changes(tmp_path: Path):
    db_path = tmp_path / "caller-schema-sync.sqlite"
    db = SqliteDb(db_file=str(db_path))
    db.create_schedule(_generic_schedule())
    _install_caller_owned_schedule_schema(db_path)
    state_before = _sqlite_schedule_state(db_path)

    with pytest.raises(ValueError, match="caller-owned or unrecognized schema") as exc_info:
        v2_9_0.down(db, "schedules", db.schedules_table_name)

    message = str(exc_info.value)
    assert "column 'caller_note'" in message
    assert "index 'caller_schedule_endpoint_idx'" in message
    assert "trigger 'caller_schedule_update_audit'" in message
    assert _sqlite_schedule_state(db_path) == state_before


def test_sync_sqlite_down_does_not_delete_a_caller_table_using_the_temporary_name(tmp_path: Path):
    db_path = tmp_path / "caller-temp-table-sync.sqlite"
    db = SqliteDb(db_file=str(db_path))
    db.create_schedule(_generic_schedule())
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE agno_schedules__v2_9_down (secret TEXT NOT NULL)")
        connection.execute("INSERT INTO agno_schedules__v2_9_down VALUES ('keep-me')")

    with pytest.raises(ValueError, match="existing downgrade temporary object"):
        v2_9_0.down(db, "schedules", db.schedules_table_name)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT secret FROM agno_schedules__v2_9_down").fetchone() == ("keep-me",)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agno_schedules)")}
    assert set(v2_9_0._V2_9_COLUMNS).issubset(columns)


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

    assert set(v2_9_0._V2_9_COLUMNS).issubset(columns)
    assert "agno_schedules_uq_studio_owner_name" in indexes
    assert schedule is not None and schedule[:2] == ("studio", "actor-1")
    assert run is not None

    assert db.delete_schedule("studio-schedule") is True
    assert v2_9_0.down(db, "schedules", db.schedules_table_name) is True


def test_sync_sqlite_down_refuses_to_drop_pending_or_claimed_manual_work(tmp_path: Path):
    db_path = tmp_path / "pending-trigger-sync.sqlite"
    db = SqliteDb(db_file=str(db_path))
    schedule = _studio_schedule("generic-schedule")
    schedule.update(managed_by=None, owner_actor_id=None, next_run_at=2**62)
    db.create_schedule(schedule)
    assert db.trigger_schedule("generic-schedule")["pending_trigger_count"] == 1

    with pytest.raises(ValueError, match="pending or claimed manual triggers"):
        v2_9_0.down(db, "schedules", db.schedules_table_name)

    claimed = db.claim_due_schedule("worker")
    assert claimed is not None and claimed["pending_trigger_count"] == 0
    assert claimed["manual_trigger_claimed"] is True
    with pytest.raises(ValueError, match="pending or claimed manual triggers"):
        v2_9_0.down(db, "schedules", db.schedules_table_name)

    assert db.release_schedule(
        "generic-schedule",
        worker_id=claimed["locked_by"],
        locked_at=claimed["locked_at"],
    )
    assert db.get_schedule("generic-schedule")["manual_trigger_claimed"] is False
    assert v2_9_0.down(db, "schedules", db.schedules_table_name) is True


@pytest.mark.asyncio
async def test_async_sqlite_down_refuses_claimed_manual_work_then_succeeds_after_release(tmp_path: Path):
    db = AsyncSqliteDb(db_file=str(tmp_path / "claimed-trigger-async.sqlite"))
    schedule = _generic_schedule()
    schedule["next_run_at"] = 2**62
    try:
        await db.create_schedule(schedule)
        await db.trigger_schedule(schedule["id"])
        claimed = await db.claim_due_schedule("worker")
        assert claimed is not None
        assert claimed["pending_trigger_count"] == 0
        assert claimed["manual_trigger_claimed"] is True

        with pytest.raises(ValueError, match="pending or claimed manual triggers"):
            await v2_9_0.async_down(db, "schedules", db.schedules_table_name)

        assert await db.release_schedule(
            schedule["id"],
            worker_id=claimed["locked_by"],
            locked_at=claimed["locked_at"],
        )
        assert (await db.get_schedule(schedule["id"]))["manual_trigger_claimed"] is False
        assert await v2_9_0.async_down(db, "schedules", db.schedules_table_name) is True
    finally:
        await db.close()


def test_sync_sqlite_upgrade_fails_clearly_without_partially_migrating_duplicates(tmp_path: Path):
    db_path = tmp_path / "legacy-duplicates.sqlite"
    _create_legacy_schedule_table(db_path, ["duplicate", "duplicate"])
    db = SqliteDb(db_file=str(db_path))

    with pytest.raises(ValueError, match="duplicates already exist"):
        v2_9_0.up(db, "schedules", db.schedules_table_name)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agno_schedules)")}
    assert set(v2_9_0._V2_9_COLUMNS).isdisjoint(columns)


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
        assert set(v2_9_0._V2_9_COLUMNS).issubset(columns)
        assert tuple(row) == (None, None)
        assert await v2_9_0.async_down(db, "schedules", db.schedules_table_name) is True
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_async_sqlite_down_refuses_caller_owned_schema_without_partial_changes(tmp_path: Path):
    db_path = tmp_path / "caller-schema-async.sqlite"
    db = AsyncSqliteDb(db_file=str(db_path))
    try:
        await db.create_schedule(_generic_schedule())
        _install_caller_owned_schedule_schema(db_path)
        state_before = _sqlite_schedule_state(db_path)

        with pytest.raises(ValueError, match="caller-owned or unrecognized schema") as exc_info:
            await v2_9_0.async_down(db, "schedules", db.schedules_table_name)

        message = str(exc_info.value)
        assert "column 'caller_note'" in message
        assert "index 'caller_schedule_endpoint_idx'" in message
        assert "trigger 'caller_schedule_update_audit'" in message
        assert _sqlite_schedule_state(db_path) == state_before
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

        assert set(v2_9_0._V2_9_COLUMNS).issubset(columns)
        assert "agno_schedules_uq_studio_owner_name" in indexes
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
    assert set(v2_9_0._V2_9_COLUMNS).isdisjoint(columns)


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
    assert set(v2_9_0._V2_9_COLUMNS).issubset(columns)


@pytest.mark.asyncio
async def test_sync_migration_manager_keeps_version_and_schema_when_caller_schema_is_refused(tmp_path: Path):
    db_path = tmp_path / "caller-schema-manager-sync.sqlite"
    db = SqliteDb(db_file=str(db_path))
    db.create_schedule(_generic_schedule())
    db.upsert_schema_version(db.schedules_table_name, "2.9.0")
    _install_caller_owned_schedule_schema(db_path)
    state_before = _sqlite_schedule_state(db_path)

    with pytest.raises(ValueError, match="caller-owned or unrecognized schema"):
        await MigrationManager(db).down(target_version="2.5.6", table_type="schedules")

    assert db.get_latest_schema_version(db.schedules_table_name) == "2.9.0"
    assert _sqlite_schedule_state(db_path) == state_before


@pytest.mark.asyncio
async def test_async_migration_manager_keeps_version_and_schema_when_caller_schema_is_refused(tmp_path: Path):
    db_path = tmp_path / "caller-schema-manager-async.sqlite"
    db = AsyncSqliteDb(db_file=str(db_path))
    try:
        await db.create_schedule(_generic_schedule())
        await db.upsert_schema_version(db.schedules_table_name, "2.9.0")
        _install_caller_owned_schedule_schema(db_path)
        state_before = _sqlite_schedule_state(db_path)

        with pytest.raises(ValueError, match="caller-owned or unrecognized schema"):
            await MigrationManager(db).down(target_version="2.5.6", table_type="schedules")

        assert await db.get_latest_schema_version(db.schedules_table_name) == "2.9.0"
        assert _sqlite_schedule_state(db_path) == state_before
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_fresh_sqlite_scoped_indexes_are_reversible_without_losing_run_history(tmp_path: Path):
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
    db.create_schedule_run(
        {
            "id": "run-0",
            "schedule_id": "schedule-0",
            "attempt": 1,
            "status": "success",
            "created_at": 1,
        }
    )

    with sqlite3.connect(db_path) as connection:
        indexes_before = {row[1] for row in connection.execute("PRAGMA index_list(agno_schedules)")}
    assert "agno_schedules_uq_generic_name" in indexes_before
    assert "agno_schedules_uq_studio_owner_name" in indexes_before

    await MigrationManager(db).down(target_version="2.5.6", table_type="schedules")

    with sqlite3.connect(db_path) as connection:
        indexes_after = {row[1] for row in connection.execute("PRAGMA index_list(agno_schedules)")}
        columns_after = {row[1] for row in connection.execute("PRAGMA table_info(agno_schedules)")}
        assert connection.execute("SELECT schedule_id FROM agno_schedule_runs WHERE id='run-0'").fetchone() == (
            "schedule-0",
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
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

    assert "agno_schedules_uq_generic_name" not in indexes_after
    assert "agno_schedules_uq_studio_owner_name" not in indexes_after
    assert set(v2_9_0._V2_9_COLUMNS).isdisjoint(columns_after)
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
