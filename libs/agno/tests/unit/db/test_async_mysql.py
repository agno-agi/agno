from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import Column, Table
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.mysql.async_mysql import AsyncMySQLDb
from agno.db.mysql.schemas import get_table_schema_definition
from agno.db.schemas.evals import EvalRunRecord, EvalType


@pytest.fixture
def mock_async_engine():
    """Create a mock async SQLAlchemy engine"""
    engine = Mock(spec=AsyncEngine)
    engine.url = "fake:///url"
    return engine


@pytest.fixture
def async_mysql_db(mock_async_engine):
    """Create an AsyncMySQLDb instance with mock engine"""
    return AsyncMySQLDb(
        db_engine=mock_async_engine,
        db_schema="test_schema",
        session_table="test_sessions",
    )


def _session_raising(error: Exception) -> Mock:
    """An async session factory whose execute() fails the way a live backend does."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.begin = Mock(return_value=session)
    session.execute = AsyncMock(side_effect=error)
    return Mock(return_value=session)


@pytest.mark.asyncio
async def test_delete_run_raises_on_a_backend_failure(async_mysql_db):
    """False means the run was not found. A dropped connection must not say that."""
    async_mysql_db._get_table = AsyncMock(return_value=Mock())
    async_mysql_db.async_session_factory = _session_raising(OSError("server closed the connection"))

    with pytest.raises(OSError, match="server closed"):
        await async_mysql_db.delete_run("run-1")


@pytest.mark.asyncio
async def test_delete_run_still_returns_false_when_there_is_no_such_run(async_mysql_db):
    """The meaning of False, pinned so it is not lost to the fix above."""
    async_mysql_db._get_table = AsyncMock(return_value=None)

    assert await async_mysql_db.delete_run("run-1") is False


@pytest.mark.asyncio
async def test_delete_runs_raises_on_a_backend_failure(async_mysql_db):
    async_mysql_db._get_table = AsyncMock(return_value=Mock())
    async_mysql_db.async_session_factory = _session_raising(OSError("server closed the connection"))

    with pytest.raises(OSError, match="server closed"):
        await async_mysql_db.delete_runs(["run-1", "run-2"])


@pytest.mark.asyncio
async def test_create_eval_run_creates_missing_table_and_inserts_records(async_mysql_db, monkeypatch):
    """The first evaluation must be inserted without explicitly creating tables first."""
    table = Table(
        async_mysql_db.eval_table_name,
        async_mysql_db.metadata,
        *(Column(name, config["type"]()) for name, config in get_table_schema_definition("evals").items()),
    )
    create_table = AsyncMock(return_value=table)
    monkeypatch.setattr(async_mysql_db, "_create_table", create_table)
    monkeypatch.setattr("agno.db.mysql.async_mysql.ais_table_available", AsyncMock(return_value=False))

    session = AsyncMock()
    session.__aenter__.return_value = session
    session.begin = Mock(return_value=session)
    monkeypatch.setattr(async_mysql_db, "async_session_factory", Mock(return_value=session))

    # Exercise table resolution on the first write and its cached result on the next.
    for run_id in ("first-eval", "second-eval"):
        eval_run = EvalRunRecord(
            run_id=run_id,
            eval_type=EvalType.ACCURACY,
            name="First evaluations",
            eval_data={"score": 0.9},
            eval_input={"prompt": "test prompt"},
        )
        assert await async_mysql_db.create_eval_run(eval_run) == eval_run
        statement = session.execute.await_args.args[0]
        assert statement.table is table
        parameters = statement.compile(dialect=mysql.dialect()).params
        assert parameters.items() >= eval_run.model_dump().items()
        assert isinstance(parameters["created_at"], int)
        assert isinstance(parameters["updated_at"], int)

    create_table.assert_awaited_once_with(table_name=async_mysql_db.eval_table_name, table_type="evals")
    assert session.execute.await_count == 2
