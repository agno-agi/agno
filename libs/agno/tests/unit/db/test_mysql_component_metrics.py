"""Unit tests for the component metrics related methods of the MySQLDb and AsyncMySQLDb classes."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from sqlalchemy import Column, MetaData, Table
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from agno.db.mysql.async_mysql import AsyncMySQLDb
from agno.db.mysql.mysql import MySQLDb
from agno.db.mysql.schemas import SESSION_TABLE_SCHEMA, get_table_schema_definition
from agno.db.mysql.utils import build_component_metrics_run, upsert_user_metrics_row

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
        result.fetchmany.side_effect = _batches(rows)
        result.scalar.return_value = self.scalar
        result.scalars.return_value.all.return_value = [row.date for row in rows if hasattr(row, "date")]
        result.mappings.return_value.all.return_value = [getattr(row, "_mapping", None) or vars(row) for row in rows]
        return result


class _FakeAsyncSession(_FakeSession):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def connection(self, execution_options=None):
        return None

    async def execute(self, statement, params=None):
        return _FakeSession.execute(self, statement, params)

    async def stream(self, statement):
        rows = _FakeSession.execute(self, statement).fetchall()
        return Mock(fetchmany=AsyncMock(side_effect=_batches(rows)), close=AsyncMock())


@pytest.fixture
def mock_engine():
    """Create a mock SQLAlchemy engine"""
    engine = Mock(spec=Engine)
    engine.url = "fake:///url"
    return engine


@pytest.fixture
def mock_async_engine():
    """Create a mock async SQLAlchemy engine"""
    engine = Mock(spec=AsyncEngine)
    engine.url = "fake:///url"
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


@pytest.fixture
def async_mysql_db(mock_async_engine):
    """Create an AsyncMySQLDb instance with mock engine that holds the lock and rebuilds the last three days"""
    db = AsyncMySQLDb(db_engine=mock_async_engine, db_schema="test_schema")
    db._get_table = AsyncMock(side_effect=_get_table)
    db.get_latest_schema_version = AsyncMock(return_value="3.0.0")
    db._claim_metrics_refresh = AsyncMock(return_value={"finished_at": None, "fingerprint": None})
    db._heartbeat_metrics_refresh = AsyncMock(return_value=True)
    db._release_metrics_refresh = AsyncMock()
    db._get_metrics_dates_to_calculate = AsyncMock(
        return_value=([TODAY - timedelta(days=days_ago) for days_ago in [2, 1, 0]], ["fingerprint"])
    )
    return db


def _written(session, table_name):
    return [row for name, rows in session.writes if name == table_name for row in rows]


def test_calculate_metrics_writes_each_day_and_its_totals_rows_last(mysql_db):
    """Each day gets one row per user, then its user and everyone totals rows; only a day ended a day ago is
    completed, and the lock is released with the fingerprint."""
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
    # Every month a rebuilt day is in is reopened with the day, then gets its totals rows after the days
    month_rows = [row for row in everyone_rows if row["aggregation_period"] == "monthly"]
    assert {row["date"] for row in month_rows} == {row["date"].replace(day=1) for row in rows}
    mysql_db._release_metrics_refresh.assert_called_once()
    assert mysql_db._release_metrics_refresh.call_args.kwargs == {"fingerprint": ["fingerprint"]}


def test_totals_row_completed_is_compared_before_the_version_moves():
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


def test_nested_runs_are_put_back_in_place():
    """Runs nested inside a run come back under the run they are nested inside, in their stored order."""
    row = SimpleNamespace(
        _mapping={
            "run_id": "team-run",
            "metrics": {},
            "model": "gpt-5",
            "model_provider": "OpenAI",
            "call_durations": [1.5],
            "nested_runs": [
                {"path": "1000000002", "depth": 1, "key": "member_responses", "run_id": "m2", "call_durations": []},
                {
                    "path": "1000000001000000001",
                    "depth": 2,
                    "key": "member_responses",
                    "run_id": "m1-1",
                    "call_durations": None,
                },
                {"path": "1000000001", "depth": 1, "key": "member_responses", "run_id": "m1", "call_durations": None},
            ],
        }
    )

    run = build_component_metrics_run(row)

    members = run["run_data"]["member_responses"]
    assert [member["run_id"] for member in members] == ["m1", "m2"]
    assert [nested["run_id"] for nested in members[0]["member_responses"]] == ["m1-1"]
    assert run["run_data"]["messages"] == [{"role": "assistant", "metrics": {"duration": 1.5}}]


def test_a_read_never_calculates_before_the_first_calculation_finished(mysql_db):
    """A read calculates no metrics before a first calculation has finished, nor once AgentOS calculates them."""
    mysql_db._get_metrics_refresh_row = Mock(return_value=({"finished_at": None}, 0))
    mysql_db.calculate_metrics_dates = Mock()
    mysql_db.Session = Mock(return_value=_FakeSession())

    mysql_db.get_metrics()
    mysql_db.calculate_metrics_dates.assert_not_called()

    mysql_db._get_metrics_refresh_row = Mock(return_value=({"finished_at": 1}, 0))
    mysql_db._metrics_refreshed_at = 0.0
    mysql_db.stop_metrics_refresh_on_read()
    mysql_db.get_metrics()
    mysql_db.calculate_metrics_dates.assert_not_called()


def test_get_metrics_versions(mysql_db):
    """No version is read before a first calculation finished; then each everyone row's version, keyed by its period
    and date."""
    rows = [
        SimpleNamespace(aggregation_period="daily", date=TODAY - timedelta(days=1), version=1),
        SimpleNamespace(aggregation_period="monthly", date=TODAY.replace(day=1), version=4),
    ]
    mysql_db.Session = Mock(return_value=_FakeSession({"test_user_metrics": rows}))
    mysql_db._metrics_refreshed_at = float("inf")

    mysql_db._get_metrics_refresh_row = Mock(return_value=({"finished_at": None}, 0))
    assert mysql_db.get_metrics_versions(TODAY - timedelta(days=1), TODAY) is None

    mysql_db._get_metrics_refresh_row = Mock(return_value=({"finished_at": 1}, 0))
    assert mysql_db.get_metrics_versions(TODAY - timedelta(days=1), TODAY) == {
        f"daily {(TODAY - timedelta(days=1)).isoformat()}": 1,
        f"monthly {TODAY.replace(day=1).isoformat()}": 4,
    }


@pytest.mark.asyncio
async def test_async_get_metrics_versions(async_mysql_db):
    """No version is read before a first calculation finished; then each everyone row's version, keyed by its period
    and date."""
    rows = [SimpleNamespace(aggregation_period="daily", date=TODAY, version=2)]
    async_mysql_db.async_session_factory = Mock(return_value=_FakeAsyncSession({"test_user_metrics": rows}))
    async_mysql_db._metrics_refreshed_at = float("inf")

    async_mysql_db._get_metrics_refresh_row = AsyncMock(return_value=({"finished_at": None}, 0))
    assert await async_mysql_db.get_metrics_versions(TODAY, TODAY) is None

    async_mysql_db._get_metrics_refresh_row = AsyncMock(return_value=({"finished_at": 1}, 0))
    assert await async_mysql_db.get_metrics_versions(TODAY, TODAY) == {f"daily {TODAY.isoformat()}": 2}
