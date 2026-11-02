"""Unit tests for the component metrics related methods of the MySQLDb class."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy import Column, MetaData, Table
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.dml import Insert

from agno.db.mysql.mysql import MySQLDb
from agno.db.mysql.schemas import SESSION_TABLE_SCHEMA, get_table_schema_definition
from agno.db.mysql.utils import upsert_user_metrics_row

TODAY = datetime.now(timezone.utc).date()


def _table(name: str, schema: dict) -> Table:
    """A table built from its schema without a database."""
    columns = [Column(column, config["type"]()) for column, config in schema.items() if not column.startswith("_")]
    return Table(name, MetaData(), *columns)


TABLES = {
    "sessions": _table("test_sessions", SESSION_TABLE_SCHEMA),
    "component_metrics": _table("test_component_metrics", get_table_schema_definition("component_metrics")),
    "user_metrics": _table("test_user_metrics", get_table_schema_definition("user_metrics")),
    "metrics_refreshes": _table("test_metrics_refreshes", get_table_schema_definition("metrics_refreshes")),
}


def _get_table(table_type, create_table_if_not_found=False):
    return TABLES.get(table_type)


def _session_row(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        _mapping={
            "session_id": f"{user_id}-session",
            "session_type": "agent",
            "user_id": user_id,
            "agent_id": "agent-1",
            "team_id": None,
            "workflow_id": None,
            "metadata": None,
        }
    )


def _batches(rows):
    """Answers fetchmany one row at a time, then with nothing."""
    return [[row] for row in rows] + [[]]


class _FakeSession:
    """A session that answers each SELECT by the table it reads, and keeps every write."""

    def __init__(self, rows_by_table=None, scalar=None):
        self.rows_by_table = rows_by_table or {}
        self.scalar = scalar
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def begin(self):
        return self

    def connection(self, execution_options=None):
        return None

    def execute(self, statement, params=None, execution_options=None):
        if isinstance(statement, Insert):
            rows = params if params is not None else [statement.compile(dialect=mysql.dialect()).params]
            self.writes.append((statement.table.name, rows))
            return Mock()
        table_names = [getattr(table, "name", None) for table in statement.get_final_froms()]
        rows = next((self.rows_by_table[name] for name in table_names if name in self.rows_by_table), [])
        result = MagicMock()
        result.fetchall.return_value = rows
        result.first.return_value = rows[0] if rows else None
        result.fetchmany.side_effect = _batches(rows)
        result.scalar.return_value = self.scalar
        result.scalars.return_value.all.return_value = [row.date for row in rows if hasattr(row, "date")]
        result.mappings.return_value.all.return_value = [getattr(row, "_mapping", None) or vars(row) for row in rows]
        return result


@pytest.fixture
def mock_engine():
    """Create a mock SQLAlchemy engine"""
    engine = Mock(spec=Engine)
    engine.url = "fake:///url"
    engine.dialect = mysql.dialect()
    return engine


@pytest.fixture
def mysql_db(mock_engine):
    """Create a MySQLDb instance with mock engine that holds the lock and rebuilds the last three days"""
    db = MySQLDb(db_engine=mock_engine, db_schema="test_schema")
    db._get_table = Mock(side_effect=_get_table)
    db.get_latest_schema_version = Mock(return_value="3.0.0")
    db._claim_metrics_refresh = Mock(return_value={"finished_at": None, "fingerprint": None})
    db._heartbeat_metrics_refresh = Mock(return_value=True)
    db._release_metrics_refresh = Mock()
    db._get_metrics_dates_to_calculate = Mock(
        return_value=([TODAY - timedelta(days=days_ago) for days_ago in [2, 1, 0]], ["fingerprint"])
    )
    return db


def _written(session, table_name):
    return [row for name, rows in session.writes if name == table_name for row in rows]


def test_calculate_metrics_writes_each_day_and_its_user_metrics_rows_last(mysql_db):
    """Each day gets one row per user, then its user metrics rows; only a day ended a day ago is completed, and the
    lock is released with the fingerprint."""
    session = _FakeSession({"test_sessions": [_session_row("alice"), _session_row("bob")]})
    mysql_db.Session = Mock(return_value=session)

    calculated_dates = mysql_db.calculate_metrics_dates()

    assert calculated_dates == [TODAY - timedelta(days=days_ago) for days_ago in [2, 1, 0]]
    rows = _written(session, "test_component_metrics")
    assert [(row["date"], row["user_id"], row["sessions_count"]) for row in rows] == [
        (TODAY - timedelta(days=days_ago), user_id, 1) for days_ago in [2, 1, 0] for user_id in ["alice", "bob"]
    ]
    everyone_rows = [row for row in _written(session, "test_user_metrics") if row["user_id"] == ""]
    assert [
        (row["aggregation_period"], row["date"], row["agent_sessions_count"], row["completed"])
        for row in everyone_rows
        if row["aggregation_period"] == "daily"
    ] == [
        ("daily", TODAY - timedelta(days=2), 2, True),
        ("daily", TODAY - timedelta(days=1), 2, False),
        ("daily", TODAY, 2, False),
    ]
    # Every month a rebuilt day is in is reopened with the day
    month_rows = [row for row in everyone_rows if row["aggregation_period"] == "monthly"]
    assert {row["date"] for row in month_rows} == {row["date"].replace(day=1) for row in rows}
    mysql_db._release_metrics_refresh.assert_called_once()
    assert mysql_db._release_metrics_refresh.call_args.kwargs == {
        "fingerprint": ["fingerprint"],
        "claimed_fingerprint": None,
    }


def test_everyone_row_completed_is_compared_before_the_version_moves():
    """The everyone row is completed only while it keeps the version read, compared before the upsert moves it."""
    session = Mock()
    upsert_user_metrics_row(
        session,
        TABLES["user_metrics"],
        {"aggregation_period": "daily", "date": TODAY, "user_id": "", "completed": True},
        read_version=3,
    )

    statement = str(session.execute.call_args.args[0].compile(dialect=mysql.dialect()))
    assert "ON DUPLICATE KEY UPDATE" in statement
    completed = statement.index("completed = (test_user_metrics.version = %s AND")
    assert completed < statement.index("version = (test_user_metrics.version + %s)")


def test_reopen_metrics_days_raises_when_a_deadlock_rolled_back_the_write(mysql_db):
    """A deadlock rolls back the whole transaction, savepoint included, and the write with it: the reopen raises, so
    the write fails instead of committing nothing."""
    session = MagicMock()
    session.begin_nested.side_effect = OperationalError(
        "ROLLBACK TO SAVEPOINT sa_savepoint_1", {}, Exception(1305, "SAVEPOINT sa_savepoint_1 does not exist")
    )
    old_day = TODAY - timedelta(days=5)

    with pytest.raises(OperationalError):
        mysql_db._reopen_metrics_days(
            session, [int(datetime(old_day.year, old_day.month, old_day.day, 12, tzinfo=timezone.utc).timestamp())]
        )


def test_claim_metrics_refresh_returns_while_another_process_writes_a_day(mock_engine):
    """A claim waits a second for the holder's lock, then returns None, and sets the lock wait back."""
    db = MySQLDb(db_engine=mock_engine, db_schema="test_schema")
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute.side_effect = [
        Mock(scalar=Mock(return_value=50)),
        Mock(),
        OperationalError("INSERT", {}, Exception(1205, "Lock wait timeout exceeded")),
        Mock(),
    ]
    db.Session = Mock(return_value=session)

    assert db._claim_metrics_refresh(TABLES["metrics_refreshes"], "worker") is None
    assert str(session.execute.call_args_list[1].args[0]) == "SET SESSION innodb_lock_wait_timeout = 1"
    assert session.execute.call_args.args[1] == {"seconds": 50}
