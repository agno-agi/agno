"""Transaction ownership, cancellation and legacy upgrades on real async drivers."""

import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection

from agno.db.postgres import AsyncPostgresDb
from agno.db.sqlite import AsyncSqliteDb
from agno.fs import FileSystem, SchemaOutdatedError
from agno.fs.db import AsyncDbFileSystem
from agno.fs.types import FileMeta


@pytest_asyncio.fixture(params=["sqlite", "sqlite_memory", "postgres"])
async def backend(request, tmp_path):
    schema = None
    if request.param == "postgres":
        # Use the suite's availability check and its existing local service.
        request.getfixturevalue("pg_engine")
        schema = "fs_async_" + uuid4().hex
        db = AsyncPostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    elif request.param == "sqlite_memory":
        db = AsyncSqliteDb(db_url="sqlite+aiosqlite:///:memory:")
    else:
        db = AsyncSqliteDb(db_file=str(tmp_path / "fs.db"))
    backend = AsyncDbFileSystem(db, db_schema=schema)
    try:
        yield backend
    finally:
        if schema:
            async with db.db_engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await db.close()


async def legacy_table(backend, nullable_user=False):
    name = backend.table.fullname
    async with backend.db.db_engine.begin() as conn:
        if backend.db_schema:
            await conn.execute(text(f'CREATE SCHEMA "{backend.db_schema}"'))
        user_column = ", user_id VARCHAR" if nullable_user else ""
        await conn.execute(
            text(
                f"CREATE TABLE {name} (namespace VARCHAR NOT NULL, path VARCHAR NOT NULL, content TEXT NOT NULL, "
                "size_bytes BIGINT NOT NULL, version BIGINT NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT"
                f"{user_column}, PRIMARY KEY (namespace, path))"
            )
        )
        await conn.execute(
            text(
                f"INSERT INTO {name} (namespace, path, content, size_bytes, version, created_at, updated_at) "
                "VALUES ('shared', 'a.md', 'original', 8, 3, 10, 20), ('users/alice', 'b.md', 'private', 7, 4, 11, 21)"
            )
        )
        if nullable_user:
            await conn.execute(
                text(
                    f"INSERT INTO {name} (namespace, path, content, size_bytes, version, created_at, updated_at, user_id) "
                    "VALUES ('private', 'c.md', 'carol', 5, 2, 12, 22, 'carol')"
                )
            )


async def schema_and_rows(backend):
    async with backend.db.db_engine.connect() as conn:
        columns, key = await conn.run_sync(
            lambda c: (
                inspect(c).get_columns(backend.table_name, schema=backend.db_schema),
                inspect(c).get_pk_constraint(backend.table_name, schema=backend.db_schema)["constrained_columns"],
            )
        )
        rows = (await conn.execute(text(f"SELECT * FROM {backend.table.fullname} ORDER BY namespace"))).mappings().all()
    return [dict(c, type=str(c["type"])) for c in columns], key, rows


@pytest.mark.asyncio
@pytest.mark.parametrize("nullable_user", [False, True])
async def test_async_legacy_upgrade_preserves_rows_and_partitions(backend, nullable_user):
    await legacy_table(backend, nullable_user)
    fs = FileSystem(backend, namespace="shared")
    with pytest.raises(SchemaOutdatedError):
        await fs.aread("a.md")
    before = (await schema_and_rows(backend))[2]
    assert await backend.aupgrade_schema() is True
    columns, key, rows = await schema_and_rows(backend)
    assert next(c for c in columns if c["name"] == "user_id")["nullable"] is False
    assert set(key) == {"namespace", "user_id", "path"}
    assert rows == [dict(row, user_id=row.get("user_id") or "") for row in before]
    if nullable_user:
        private = FileSystem(backend, namespace="private")
        assert await private.aread("c.md") is None
        assert await private.resolve(user_id="carol").aread("c.md") == "carol"
    assert await fs.aread("a.md") == "original"
    await fs.resolve(user_id="bob").awrite("a.md", "bob")
    assert await fs.aread("a.md") == "original"
    assert await fs.resolve(user_id="bob").aread("a.md") == "bob"
    assert await FileSystem(backend, namespace="users/{user_id}").resolve(user_id="alice").aread("b.md") == "private"
    assert await backend.aupgrade_schema() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_outer_transaction_rolls_back_after_savepoint_release(backend, monkeypatch, cancel):
    fs = FileSystem(backend, namespace="shared")
    await fs.awrite("a.md", "original")
    before = await fs.aread_with_meta("a.md")
    reached = asyncio.Event()
    original = AsyncConnection.run_sync

    async def interrupt_before_commit(connection, fn, *args, **kwargs):
        result = await original(connection, fn, *args, **kwargs)
        if not isinstance(result, FileMeta):
            return result
        reached.set()
        if cancel:
            await asyncio.Event().wait()
        raise RuntimeError("injected before outer commit")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncConnection, "run_sync", interrupt_before_commit)
        if cancel:
            task = asyncio.create_task(fs.awrite("a.md", "must roll back"))
            try:
                await asyncio.wait_for(reached.wait(), 5)
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        else:
            with pytest.raises(RuntimeError, match="injected"):
                await fs.awrite("a.md", "must roll back")
    assert await fs.aread_with_meta("a.md") == before
    assert (await fs.awrite("a.md", "retry", expected_version=before.metadata.version)).version == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_partial_move_rolls_back_and_connection_remains_usable(backend, monkeypatch, cancel):
    from sqlalchemy.util import await_only

    fs = FileSystem(backend, namespace="shared")
    await fs.awrite("src.md", "source")
    await fs.awrite("dst.md", "destination")
    before = [await fs.aread_with_meta(path) for path in ("src.md", "dst.md")]
    reached = asyncio.Event()

    original = Connection.execute

    def interrupt_after_delete(conn, statement, *args, **kwargs):
        result = original(conn, statement, *args, **kwargs)
        if statement.is_delete:
            reached.set()
            if cancel:
                await_only(asyncio.Event().wait())
            raise RuntimeError("injected after destination delete")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Connection, "execute", interrupt_after_delete)
        if cancel:
            task = asyncio.create_task(fs.amove("src.md", "dst.md", overwrite=True))
            try:
                await asyncio.wait_for(reached.wait(), 5)
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        else:
            with pytest.raises(RuntimeError, match="injected"):
                await fs.amove("src.md", "dst.md", overwrite=True)
    assert [await fs.aread_with_meta(path) for path in ("src.md", "dst.md")] == before
    await fs.amove("src.md", "dst.md", overwrite=True)
    assert await fs.aread("src.md") is None
    assert await fs.aread("dst.md") == "source"


@pytest.mark.asyncio
async def test_failed_migration_rolls_back_ddl_and_data(backend):
    await legacy_table(backend)
    before = await schema_and_rows(backend)

    def fail_after_ddl(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lstrip().upper()
        # SQLite has copied the rows and dropped the old table. PostgreSQL has
        # added the column but has not yet replaced the primary key.
        if sql.startswith('DROP TABLE "AGNO_FS"') or (sql.startswith("ALTER TABLE") and "ADD COLUMN" in sql):
            raise RuntimeError("injected during migration")

    engine = backend.db.db_engine.sync_engine
    event.listen(engine, "after_cursor_execute", fail_after_ddl)
    try:
        with pytest.raises(RuntimeError, match="injected during migration"):
            await backend.aupgrade_schema()
    finally:
        event.remove(engine, "after_cursor_execute", fail_after_ddl)
    assert await schema_and_rows(backend) == before
    assert await backend.aupgrade_schema() is True
    assert await FileSystem(backend, namespace="shared").aread("a.md") == "original"


@pytest.mark.asyncio
async def test_sqlite_caller_managed_begin_is_respected(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "managed.db"))

    @event.listens_for(engine.sync_engine, "connect")
    def disable_legacy_begin(connection, record):
        connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    db = AsyncSqliteDb(db_engine=engine)
    try:
        fs = FileSystem(db)
        await fs.awrite("a.md", "original")
        await fs.awrite("a.md", "updated", expected_version=1)
        assert await fs.aread("a.md") == "updated"
        assert await fs.backend.aupgrade_schema() is False
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_interrupted_cold_creation_can_be_retried(backend, monkeypatch, cancel):
    reached = asyncio.Event()
    original = AsyncConnection.run_sync

    async def interrupt(connection, fn, *args, **kwargs):
        await original(connection, fn, *args, **kwargs)
        reached.set()
        if cancel:
            await asyncio.Event().wait()
        raise RuntimeError("injected after cold creation")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncConnection, "run_sync", interrupt)
        if cancel:
            task = asyncio.create_task(backend.awrite("shared", "a.md", "cancelled"))
            try:
                await asyncio.wait_for(reached.wait(), 5)
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        else:
            with pytest.raises(RuntimeError, match="injected"):
                await backend.awrite("shared", "a.md", "failed")
    async with backend.db.db_engine.connect() as conn:
        assert not await conn.run_sync(lambda c: inspect(c).has_table(backend.table_name, schema=backend.db_schema))
    assert await backend.awrite("shared", "a.md", "retry", expected_version=0)
    assert await backend.aread("shared", "a.md") == "retry"


@pytest.mark.asyncio
async def test_cancelled_migration_rolls_back_before_outer_commit(backend, monkeypatch):
    await legacy_table(backend)
    before = await schema_and_rows(backend)
    reached = asyncio.Event()
    original = AsyncConnection.run_sync

    async def interrupt(connection, fn, *args, **kwargs):
        result = await original(connection, fn, *args, **kwargs)
        assert result is True
        reached.set()
        await asyncio.Event().wait()

    with monkeypatch.context() as patch:
        patch.setattr(AsyncConnection, "run_sync", interrupt)
        task = asyncio.create_task(backend.aupgrade_schema())
        try:
            await asyncio.wait_for(reached.wait(), 5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert await schema_and_rows(backend) == before
    assert await backend.aupgrade_schema() is True


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"], indirect=True)
async def test_driver_cancellation_preserves_durable_files(backend):
    from sqlalchemy.util import await_only

    fs = FileSystem(backend, namespace="shared")
    await fs.awrite("src.md", "source")
    await fs.awrite("dst.md", "destination")
    reached = asyncio.Event()

    def interrupt(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("DELETE FROM"):
            reached.set()
            await_only(asyncio.Event().wait())

    # Cancellation inside SQLAlchemy execution may invalidate the connection.
    # Durable databases must roll back even when the pool replaces it; an
    # in-memory SQLite database is connection-owned and cannot survive that.
    engine = backend.db.db_engine.sync_engine
    event.listen(engine, "after_cursor_execute", interrupt)
    task = asyncio.create_task(fs.amove("src.md", "dst.md", overwrite=True))
    try:
        await asyncio.wait_for(reached.wait(), 5)
    finally:
        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            event.remove(engine, "after_cursor_execute", interrupt)
    assert await fs.aread("src.md") == "source"
    assert await fs.aread("dst.md") == "destination"
    await fs.amove("src.md", "dst.md", overwrite=True)
    assert await fs.aread("dst.md") == "source"
