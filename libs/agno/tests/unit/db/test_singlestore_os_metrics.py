"""Unit tests for the OS Metrics related methods of the SingleStoreDb class"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy import Column, MetaData, Table
from sqlalchemy.engine import Engine

from agno.db.singlestore.schemas import get_table_schema_definition
from agno.db.singlestore.singlestore import SingleStoreDb

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


@pytest.fixture
def singlestore_db():
    """Create a SingleStoreDb instance with mock engine"""
    engine = Mock(spec=Engine)
    engine.url = "fake:///url"
    db = SingleStoreDb(db_engine=engine, db_schema="test_schema", os_metrics_table="test_os_metrics")
    db._get_table = Mock(return_value=_os_metrics_table())
    db._calculate_os_metrics = Mock(return_value=None)
    return db


def test_get_os_metrics_by_date(singlestore_db):
    """A read returns the totals of each day, oldest first, with only the fields asked for."""
    singlestore_db.Session = _session_returning([], _day_rows())

    os_metrics, latest_updated_at = singlestore_db.get_os_metrics(
        TWO_DAYS_BACK, YESTERDAY, fields=["sessions_count", "runs_count"]
    )

    assert os_metrics == [
        {"date": TWO_DAYS_BACK, "sessions_count": 1, "runs_count": 1},
        {"date": YESTERDAY, "sessions_count": 2, "runs_count": 3},
    ]
    assert latest_updated_at == 200


def test_get_os_metrics_by_user(singlestore_db):
    """A read for one user totals only the rows of that user."""
    singlestore_db.Session = _session_returning(_day_rows()[:1])

    os_metrics, _ = singlestore_db.get_os_metrics(YESTERDAY, YESTERDAY, user_id="alice", fields=["runs_count"])

    statement = singlestore_db.Session.return_value.execute.call_args.args[0]
    assert "alice" in statement.compile().params.values()
    assert os_metrics == [{"date": YESTERDAY, "runs_count": 3}]


def test_refresh_os_metrics(singlestore_db):
    """A refresh reports when the rows were last updated before and after it, and whether any changed."""
    singlestore_db.Session = _session_returning(100, 200, 200, 200)
    singlestore_db._calculate_os_metrics.side_effect = lambda changed_ids: changed_ids.append("row-1")
    assert singlestore_db.refresh_os_metrics() == (100, 200, True)

    singlestore_db._calculate_os_metrics.side_effect = None
    assert singlestore_db.refresh_os_metrics() == (200, 200, False)


def test_get_os_metrics_totals_and_state(singlestore_db):
    """The totals of a date range are one record, and the state is read from the state row."""
    singlestore_db.Session = _session_returning([], _day_rows(), (200, {"hash": "hash-1"}))

    totals, latest_updated_at = singlestore_db.get_os_metrics_totals(
        TWO_DAYS_BACK, YESTERDAY, fields=["sessions_count", "runs_count"]
    )

    assert totals == {"sessions_count": 3, "runs_count": 4}
    assert latest_updated_at == 200
    assert singlestore_db.get_os_metrics_state() == (200, "hash-1")
