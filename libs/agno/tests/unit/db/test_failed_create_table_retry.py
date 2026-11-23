from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.mysql.async_mysql import AsyncMySQLDb
from agno.db.mysql.mysql import MySQLDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.db.sqlite.sqlite import SqliteDb


def test_mysql_failed_table_creation_can_be_retried():
    """A failed CREATE TABLE on MySQLDb must not leave the table registered on MetaData."""
    engine = Mock()
    engine.url = "mysql+pymysql://user:pass@localhost/test"
    db = MySQLDb(db_engine=engine, db_schema="test_schema", session_table="test_sessions")

    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.begin = Mock(return_value=session)
    db.Session = Mock(return_value=session)

    attempts = {"retry_table": 0}

    def create_once(table, *args, **kwargs):
        if table.name == "retry_table":
            attempts["retry_table"] += 1
            if attempts["retry_table"] == 1:
                raise OSError("temporary DDL outage")

    with (
        patch.object(MySQLDb, "table_exists", return_value=False),
        patch("agno.db.mysql.mysql.is_table_available", return_value=False),
        patch.object(MySQLDb, "upsert_schema_version"),
        patch.object(Table, "create", create_once),
    ):
        with pytest.raises(OSError, match="temporary DDL outage"):
            db._get_or_create_table("retry_table", "knowledge", True)

        table = db._get_or_create_table("retry_table", "knowledge", True)

    assert table.name == "retry_table"
    assert attempts["retry_table"] == 2


@pytest.mark.asyncio
async def test_async_mysql_failed_table_creation_can_be_retried():
    """A failed CREATE TABLE on AsyncMySQLDb must not leave the table registered on MetaData."""
    engine = Mock(spec=AsyncEngine)
    engine.url = "mysql+aiomysql://user:pass@localhost/test"
    db = AsyncMySQLDb(db_engine=engine, db_schema="test_schema", session_table="test_sessions")
    db.create_schema = False

    attempts = {"create": 0}

    async def run_sync(fn, *args, **kwargs):
        attempts["create"] += 1
        if attempts["create"] == 1:
            raise OSError("temporary DDL outage")

    conn = Mock(run_sync=run_sync)
    begin_ctx = Mock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None))
    db.db_engine.begin = Mock(return_value=begin_ctx)

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.begin = Mock(return_value=session)
    session.execute = AsyncMock(return_value=Mock(scalar=Mock(return_value=1)))
    db.async_session_factory = Mock(return_value=session)

    with (
        patch.object(AsyncMySQLDb, "table_exists", AsyncMock(return_value=False)),
        patch.object(AsyncMySQLDb, "upsert_schema_version", AsyncMock()),
    ):
        with pytest.raises(OSError, match="temporary DDL outage"):
            await db._create_table("retry_table", "knowledge")

        table = await db._create_table("retry_table", "knowledge")

    assert table.name == "retry_table"
    assert attempts["create"] == 2


def test_sqlite_failed_table_creation_can_be_retried(tmp_path):
    """A failed CREATE TABLE on SqliteDb must not leave the table registered on MetaData."""
    engine = create_engine(f"sqlite:///{tmp_path / 'retry.db'}")
    db = SqliteDb(db_engine=engine, session_table="test_sessions")

    attempts = {"retry_table": 0}
    real_create = Table.create

    def create_once(table, *args, **kwargs):
        if table.name == "retry_table":
            attempts["retry_table"] += 1
            if attempts["retry_table"] == 1:
                raise OSError("temporary DDL outage")
        return real_create(table, *args, **kwargs)

    with (
        patch.object(SqliteDb, "upsert_schema_version"),
        patch.object(Table, "create", create_once),
    ):
        with pytest.raises(OSError, match="temporary DDL outage"):
            db._get_or_create_table("retry_table", "knowledge", True)

        table = db._get_or_create_table("retry_table", "knowledge", True)

    assert table.name == "retry_table"
    assert attempts["retry_table"] == 2


@pytest.mark.asyncio
async def test_async_sqlite_failed_table_creation_can_be_retried():
    """A failed CREATE TABLE on AsyncSqliteDb must not leave the table registered on MetaData."""
    engine = Mock(spec=AsyncEngine)
    engine.url = "sqlite+aiosqlite:///:memory:"
    engine.sync_engine = create_engine("sqlite:///:memory:")
    db = AsyncSqliteDb(db_engine=engine, session_table="test_sessions")

    attempts = {"create": 0}

    async def run_sync(fn, *args, **kwargs):
        attempts["create"] += 1
        if attempts["create"] == 1:
            raise OSError("temporary DDL outage")

    conn = Mock(run_sync=run_sync)
    begin_ctx = Mock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None))
    db.db_engine.begin = Mock(return_value=begin_ctx)

    with (
        patch.object(AsyncSqliteDb, "table_exists", AsyncMock(return_value=False)),
        patch.object(AsyncSqliteDb, "upsert_schema_version", AsyncMock()),
    ):
        with pytest.raises(OSError, match="temporary DDL outage"):
            await db._create_table("retry_table", "knowledge")

        table = await db._create_table("retry_table", "knowledge")

    assert table.name == "retry_table"
    assert attempts["create"] == 2
