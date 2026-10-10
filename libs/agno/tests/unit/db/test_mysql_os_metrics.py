"""Unit tests for the OS Metrics related methods of the MySQLDb and AsyncMySQLDb classes"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from sqlalchemy import Column, MetaData, Table
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.mysql.async_mysql import AsyncMySQLDb
from agno.db.mysql.mysql import MySQLDb
from agno.db.mysql.schemas import get_table_schema_definition

YESTERDAY = date(2026, 1, 2)
TWO_DAYS_BACK = date(2026, 1, 1)


def _os_metrics_table() -> Table:
    """The OS metrics table, built from its schema without a database"""
    schema = get_table_schema_definition("os_metrics")
    columns = [Column(name, config["type"]()) for name, config in schema.items() if not name.startswith("_")]
    return Table("test_os_metrics", MetaData(), *columns)


def _day_rows() -> list:
    """The rows the totals query returns for two days, one row per day"""
    return [
        SimpleNamespace(date=YESTERDAY, updated_at=200, sessions_count=2, runs_count=3),
        SimpleNamespace(date=TWO_DAYS_BACK, updated_at=100, sessions_count=1, runs_count=1),
    ]


def _result(value) -> Mock:
    """The result of one statement, whichever way its rows are read"""
    return Mock(**{"fetchall.return_value": value, "scalar.return_value": value, "first.return_value": value})


def _session_returning(*values) -> Mock:
    """A session factory whose execute() returns the given values, one per statement"""
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute.side_effect = [_result(value) for value in values]
    return Mock(return_value=session)


def _async_session_returning(*values) -> Mock:
    """An async session factory whose execute() returns the given values, one per statement"""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.begin = Mock(return_value=session)
    session.execute = AsyncMock(side_effect=[_result(value) for value in values])
    return Mock(return_value=session)


@pytest.fixture
def mysql_db():
    """Create a MySQLDb instance with mock engine"""
    engine = Mock(spec=Engine)
    engine.url = "fake:///url"
    db = MySQLDb(db_engine=engine, db_schema="test_schema", os_metrics_table="test_os_metrics")
    db._get_table = Mock(return_value=_os_metrics_table())
    db._calculate_os_metrics = Mock(return_value=None)
    return db


@pytest.fixture
def async_mysql_db():
    """Create an AsyncMySQLDb instance with mock engine"""
    engine = Mock(spec=AsyncEngine)
    engine.url = "fake:///url"
    db = AsyncMySQLDb(db_engine=engine, db_schema="test_schema", os_metrics_table="test_os_metrics")
    db._get_table = AsyncMock(return_value=_os_metrics_table())
    db._calculate_os_metrics = AsyncMock(return_value=None)
    return db


# -- MySQLDb --


def test_get_os_metrics_by_date(mysql_db):
    """A read returns the totals of each day, oldest first, with only the fields asked for."""
    mysql_db.Session = _session_returning([], _day_rows())

    os_metrics, latest_updated_at = mysql_db.get_os_metrics(
        TWO_DAYS_BACK, YESTERDAY, fields=["sessions_count", "runs_count"]
    )

    assert os_metrics == [
        {"date": TWO_DAYS_BACK, "sessions_count": 1, "runs_count": 1},
        {"date": YESTERDAY, "sessions_count": 2, "runs_count": 3},
    ]
    assert latest_updated_at == 200


def test_get_os_metrics_by_user(mysql_db):
    """A read for one user totals only the rows of that user."""
    mysql_db.Session = _session_returning(_day_rows()[:1])

    os_metrics, _ = mysql_db.get_os_metrics(YESTERDAY, YESTERDAY, user_id="alice", fields=["runs_count"])

    statement = mysql_db.Session.return_value.execute.call_args.args[0]
    assert "alice" in statement.compile().params.values()
    assert os_metrics == [{"date": YESTERDAY, "runs_count": 3}]


def test_refresh_os_metrics(mysql_db):
    """A refresh reports when the rows were last updated before and after it, and whether any changed."""
    mysql_db.Session = _session_returning(100, 200, 200, 200)
    mysql_db._calculate_os_metrics.side_effect = lambda wait_for_rebuild, changed_ids: changed_ids.append("row-1")
    assert mysql_db.refresh_os_metrics() == (100, 200, True)

    mysql_db._calculate_os_metrics.side_effect = None
    assert mysql_db.refresh_os_metrics() == (200, 200, False)


def test_get_os_metrics_totals_and_state(mysql_db):
    """The totals of a date range are one record, and the state is read from the state row."""
    mysql_db.Session = _session_returning([], _day_rows(), (200, {"hash": "hash-1"}))

    totals, latest_updated_at = mysql_db.get_os_metrics_totals(
        TWO_DAYS_BACK, YESTERDAY, fields=["sessions_count", "runs_count"]
    )

    assert totals == {"sessions_count": 3, "runs_count": 4}
    assert latest_updated_at == 200
    assert mysql_db.get_os_metrics_state() == (200, "hash-1")


# -- AsyncMySQLDb --


@pytest.mark.asyncio
async def test_async_get_os_metrics_by_date(async_mysql_db):
    """A read returns the totals of each day, oldest first, with only the fields asked for."""
    async_mysql_db.async_session_factory = _async_session_returning([], _day_rows())

    os_metrics, latest_updated_at = await async_mysql_db.get_os_metrics(
        TWO_DAYS_BACK, YESTERDAY, fields=["sessions_count", "runs_count"]
    )

    assert os_metrics == [
        {"date": TWO_DAYS_BACK, "sessions_count": 1, "runs_count": 1},
        {"date": YESTERDAY, "sessions_count": 2, "runs_count": 3},
    ]
    assert latest_updated_at == 200


@pytest.mark.asyncio
async def test_async_get_os_metrics_by_user(async_mysql_db):
    """A read for one user totals only the rows of that user."""
    async_mysql_db.async_session_factory = _async_session_returning(_day_rows()[:1])

    os_metrics, _ = await async_mysql_db.get_os_metrics(YESTERDAY, YESTERDAY, user_id="alice", fields=["runs_count"])

    statement = async_mysql_db.async_session_factory.return_value.execute.call_args.args[0]
    assert "alice" in statement.compile().params.values()
    assert os_metrics == [{"date": YESTERDAY, "runs_count": 3}]


@pytest.mark.asyncio
async def test_async_refresh_os_metrics(async_mysql_db):
    """A refresh reports when the rows were last updated before and after it, and whether any changed."""
    async_mysql_db.async_session_factory = _async_session_returning(100, 200, 200, 200)
    async_mysql_db._calculate_os_metrics.side_effect = lambda wait_for_rebuild, changed_ids: changed_ids.append("row-1")
    assert await async_mysql_db.refresh_os_metrics() == (100, 200, True)

    async_mysql_db._calculate_os_metrics.side_effect = None
    assert await async_mysql_db.refresh_os_metrics() == (200, 200, False)


@pytest.mark.asyncio
async def test_async_get_os_metrics_totals_and_state(async_mysql_db):
    """The totals of a date range are one record, and the state is read from the state row."""
    async_mysql_db.async_session_factory = _async_session_returning([], _day_rows(), (200, {"hash": "hash-1"}))

    totals, latest_updated_at = await async_mysql_db.get_os_metrics_totals(
        TWO_DAYS_BACK, YESTERDAY, fields=["sessions_count", "runs_count"]
    )

    assert totals == {"sessions_count": 3, "runs_count": 4}
    assert latest_updated_at == 200
    assert await async_mysql_db.get_os_metrics_state() == (200, "hash-1")
