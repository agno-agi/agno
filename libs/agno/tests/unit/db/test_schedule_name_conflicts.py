"""Backend contract tests for typed schedule-name uniqueness failures."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import DuplicateKeyError
from sqlalchemy.exc import IntegrityError

from agno.db.mongo.async_mongo import AsyncMongoDb
from agno.db.mongo.mongo import MongoDb
from agno.db.postgres.async_postgres import AsyncPostgresDb
from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.scheduler import ScheduleNameConflictError
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.db.sqlite.sqlite import SqliteDb


def _schedule(schedule_id: str, name: str) -> dict:
    return {
        "id": schedule_id,
        "name": name,
        "description": None,
        "method": "POST",
        "endpoint": "/agents/test/runs",
        "payload": None,
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "next_run_at": None,
        "locked_by": None,
        "locked_at": None,
        "created_at": 1,
        "updated_at": None,
    }


@pytest.mark.parametrize(
    "read",
    [
        lambda db: db.get_schedule("first"),
        lambda db: db.get_schedule_by_name("shared-name"),
        lambda db: db.get_schedules(),
        lambda db: db.claim_due_schedule("worker"),
        lambda db: db.get_schedule_run("run-1"),
        lambda db: db.get_schedule_runs("first"),
    ],
)
def test_sqlite_schedule_reads_propagate_backend_failures(tmp_path, read, caplog):
    db = SqliteDb(db_file=str(tmp_path / "read-failure.db"), schedules_table="read_failure_schedules")
    db.create_schedule(_schedule("first", "shared-name"))
    db.create_schedule_run({"id": "run-1", "schedule_id": "first", "attempt": 1, "status": "success", "created_at": 1})
    secret = "postgresql://admin:private-password@internal/agno"
    db.Session = MagicMock(side_effect=RuntimeError(secret))  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="private-password"):
        read(db)

    assert secret not in caplog.text


def test_sqlite_maps_only_schedule_name_integrity_errors(tmp_path):
    db = SqliteDb(
        db_file=str(tmp_path / "schedule-name-conflicts.db"),
        schedules_table="typed_schedule_conflicts",
    )
    first = _schedule("first", "shared-name")
    second = _schedule("second", "second-name")
    db.create_schedule(first)

    with pytest.raises(ScheduleNameConflictError, match="shared-name"):
        db.create_schedule(_schedule("duplicate-name", "shared-name"))

    with pytest.raises(IntegrityError):
        db.create_schedule(_schedule("first", "duplicate-id"))

    db.create_schedule(second)
    with pytest.raises(ScheduleNameConflictError, match="shared-name"):
        db.update_schedule("second", name="shared-name")

    with pytest.raises(IntegrityError):
        db.update_schedule("second", id="first")
    assert db.get_schedule("second")["name"] == "second-name"

    db.create_schedule({**_schedule("studio-a", "shared-name"), "managed_by": "studio", "owner_actor_id": "a"})
    db.create_schedule({**_schedule("studio-b", "shared-name"), "managed_by": "studio", "owner_actor_id": "b"})
    with pytest.raises(ScheduleNameConflictError, match="shared-name"):
        db.create_schedule(
            {**_schedule("studio-a-duplicate", "shared-name"), "managed_by": "studio", "owner_actor_id": "a"}
        )


@pytest.mark.asyncio
async def test_async_sqlite_maps_only_schedule_name_integrity_errors(tmp_path):
    db = AsyncSqliteDb(
        db_file=str(tmp_path / "async-schedule-name-conflicts.db"),
        schedules_table="typed_async_schedule_conflicts",
    )
    first = _schedule("first", "shared-name")
    second = _schedule("second", "second-name")
    await db.create_schedule(first)

    with pytest.raises(ScheduleNameConflictError, match="shared-name"):
        await db.create_schedule(_schedule("duplicate-name", "shared-name"))

    with pytest.raises(IntegrityError):
        await db.create_schedule(_schedule("first", "duplicate-id"))

    await db.create_schedule(second)
    with pytest.raises(ScheduleNameConflictError, match="shared-name"):
        await db.update_schedule("second", name="shared-name")

    with pytest.raises(IntegrityError):
        await db.update_schedule("second", id="first")
    assert (await db.get_schedule("second"))["name"] == "second-name"
    await db.db_engine.dispose()


class _SyncFailingSession:
    def __init__(self, error: Exception):
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def begin(self):
        return self

    def execute(self, *_args, **_kwargs):
        raise self.error


class _AsyncFailingSession:
    def __init__(self, error: Exception):
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def begin(self):
        return self

    async def execute(self, *_args, **_kwargs):
        raise self.error


def _psycopg_integrity_error(
    *, table_name: str = "test_schedules", constraint_name: str = "test_schedules_uq_generic_name"
) -> IntegrityError:
    original = RuntimeError("duplicate key")
    original.sqlstate = "23505"  # type: ignore[attr-defined]
    original.diag = SimpleNamespace(  # type: ignore[attr-defined]
        constraint_name=constraint_name,
        table_name=table_name,
        schema_name="test_schema",
    )
    return IntegrityError("INSERT", {}, original)


def _asyncpg_integrity_error(
    *, table_name: str = "test_schedules", constraint_name: str = "test_schedules_uq_generic_name"
) -> IntegrityError:
    cause = RuntimeError("duplicate key")
    cause.sqlstate = "23505"  # type: ignore[attr-defined]
    cause.constraint_name = constraint_name  # type: ignore[attr-defined]
    cause.table_name = table_name  # type: ignore[attr-defined]
    cause.schema_name = "test_schema"  # type: ignore[attr-defined]
    original = RuntimeError("asyncpg adapter integrity error")
    original.sqlstate = "23505"  # type: ignore[attr-defined]
    original.__cause__ = cause
    return IntegrityError("INSERT", {}, original)


def _sync_postgres_db(error: IntegrityError) -> PostgresDb:
    db = object.__new__(PostgresDb)
    db.schedules_table_name = "test_schedules"
    db.db_schema = "test_schema"
    db._get_table = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]
    db.Session = MagicMock(return_value=_SyncFailingSession(error))  # type: ignore[method-assign]
    return db


def _async_postgres_db(error: IntegrityError) -> AsyncPostgresDb:
    db = object.__new__(AsyncPostgresDb)
    db.schedules_table_name = "test_schedules"
    db.db_schema = "test_schema"
    db._get_table = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
    db.async_session_factory = MagicMock(return_value=_AsyncFailingSession(error))
    return db


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("constraint_suffix", ["uq_generic_name", "uq_studio_owner_name"])
def test_postgres_maps_exact_psycopg_schedule_name_constraint(operation, constraint_suffix):
    db = _sync_postgres_db(_psycopg_integrity_error(constraint_name=f"test_schedules_{constraint_suffix}"))

    with pytest.raises(ScheduleNameConflictError, match="shared-name"):
        if operation == "create":
            db.create_schedule({"id": "loser", "name": "shared-name"})
        else:
            db.update_schedule("loser", name="shared-name")


@pytest.mark.parametrize("operation", ["create", "update"])
def test_postgres_does_not_map_same_constraint_reported_for_another_table(operation):
    error = _psycopg_integrity_error(table_name="other_table")
    db = _sync_postgres_db(error)

    if operation == "create":
        with pytest.raises(IntegrityError) as exc_info:
            db.create_schedule({"id": "loser", "name": "shared-name"})
        assert exc_info.value is error
    else:
        with pytest.raises(IntegrityError) as exc_info:
            db.update_schedule("loser", name="shared-name")
        assert exc_info.value is error


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("constraint_suffix", ["uq_generic_name", "uq_studio_owner_name"])
async def test_async_postgres_maps_wrapped_asyncpg_schedule_name_constraint(operation, constraint_suffix):
    db = _async_postgres_db(_asyncpg_integrity_error(constraint_name=f"test_schedules_{constraint_suffix}"))

    with pytest.raises(ScheduleNameConflictError, match="shared-name"):
        if operation == "create":
            await db.create_schedule({"id": "loser", "name": "shared-name"})
        else:
            await db.update_schedule("loser", name="shared-name")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_async_postgres_does_not_map_same_constraint_reported_for_another_table(operation):
    error = _asyncpg_integrity_error(table_name="other_table")
    db = _async_postgres_db(error)

    if operation == "create":
        with pytest.raises(IntegrityError) as exc_info:
            await db.create_schedule({"id": "loser", "name": "shared-name"})
        assert exc_info.value is error
    else:
        with pytest.raises(IntegrityError) as exc_info:
            await db.update_schedule("loser", name="shared-name")
        assert exc_info.value is error


def _mongo_duplicate_error(key_pattern: dict) -> DuplicateKeyError:
    return DuplicateKeyError(
        "duplicate key",
        11000,
        {
            "keyPattern": key_pattern,
            "errmsg": "index: id_1 dup key: { id: ' index: name_1 dup key' }",
        },
    )


def _sync_mongo_db(error: DuplicateKeyError, operation: str) -> MongoDb:
    db = object.__new__(MongoDb)
    collection = MagicMock()
    if operation == "create":
        collection.insert_one.side_effect = error
    else:
        collection.update_one.side_effect = error
    db._get_collection = MagicMock(return_value=collection)  # type: ignore[method-assign]
    return db


def _async_mongo_db(error: DuplicateKeyError, operation: str) -> AsyncMongoDb:
    db = object.__new__(AsyncMongoDb)
    collection = AsyncMock()
    if operation == "create":
        collection.insert_one.side_effect = error
    else:
        collection.update_one.side_effect = error
    db._get_collection = AsyncMock(return_value=collection)  # type: ignore[method-assign]
    return db


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    "key_pattern",
    [{"name": 1}, {"name": 1, "managed_by": 1}, {"owner_actor_id": 1, "name": 1}],
)
def test_mongo_maps_only_structured_schedule_name_key_pattern(operation, key_pattern):
    db = _sync_mongo_db(_mongo_duplicate_error(key_pattern), operation)

    with pytest.raises(ScheduleNameConflictError, match="shared-name"):
        if operation == "create":
            db.create_schedule({"id": "loser", "name": "shared-name"})
        else:
            db.update_schedule("loser", name="shared-name")


@pytest.mark.parametrize("operation", ["create", "update"])
def test_mongo_does_not_map_misleading_message_for_id_key_pattern(operation):
    error = _mongo_duplicate_error({"id": 1})
    db = _sync_mongo_db(error, operation)

    if operation == "create":
        with pytest.raises(DuplicateKeyError) as exc_info:
            db.create_schedule({"id": "loser", "name": "shared-name"})
        assert exc_info.value is error
    else:
        with pytest.raises(DuplicateKeyError) as exc_info:
            db.update_schedule("loser", name="shared-name")
        assert exc_info.value is error


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    "key_pattern",
    [{"name": 1}, {"name": 1, "managed_by": 1}, {"owner_actor_id": 1, "name": 1}],
)
async def test_async_mongo_maps_only_structured_schedule_name_key_pattern(operation, key_pattern):
    db = _async_mongo_db(_mongo_duplicate_error(key_pattern), operation)

    with pytest.raises(ScheduleNameConflictError, match="shared-name"):
        if operation == "create":
            await db.create_schedule({"id": "loser", "name": "shared-name"})
        else:
            await db.update_schedule("loser", name="shared-name")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_async_mongo_does_not_map_misleading_message_for_id_key_pattern(operation):
    error = _mongo_duplicate_error({"id": 1})
    db = _async_mongo_db(error, operation)

    if operation == "create":
        with pytest.raises(DuplicateKeyError) as exc_info:
            await db.create_schedule({"id": "loser", "name": "shared-name"})
        assert exc_info.value is error
    else:
        with pytest.raises(DuplicateKeyError) as exc_info:
            await db.update_schedule("loser", name="shared-name")
        assert exc_info.value is error
