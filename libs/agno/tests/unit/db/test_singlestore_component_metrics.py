"""Unit tests for the component metrics related methods of the SingleStoreDb class."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy import Column, MetaData, Table
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.dml import Insert

from agno.db.singlestore.schemas import SESSION_TABLE_SCHEMA, get_table_schema_definition
from agno.db.singlestore.singlestore import SingleStoreDb
from agno.db.singlestore.utils import (
    build_component_metrics_run,
    upsert_user_metrics_row,
)

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
    return engine


@pytest.fixture
def singlestore_db(mock_engine):
    """Create a SingleStoreDb instance with mock engine that holds the lock and rebuilds the last three days"""
    db = SingleStoreDb(db_engine=mock_engine, db_schema="test_schema")
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


def test_calculate_metrics_writes_each_day_and_its_user_metrics_rows_last(singlestore_db):
    """Each day gets one row per user, then its user metrics rows; only a day ended a day ago is completed, and the
    lock is released with the fingerprint."""
    session = _FakeSession({"test_sessions": [_session_row("alice"), _session_row("bob")]})
    singlestore_db.Session = Mock(return_value=session)

    calculated_dates = singlestore_db.calculate_metrics_dates()

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
    singlestore_db._release_metrics_refresh.assert_called_once()
    assert singlestore_db._release_metrics_refresh.call_args.kwargs == {
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


def test_build_component_metrics_run_rebuilds_the_stored_run_shape():
    """Runs nested inside a run come back as stored, and the run's own requests as its messages."""
    member = {"run_id": "m1", "member_responses": [{"run_id": "m1-1"}]}
    row = SimpleNamespace(
        _mapping={
            "run_id": "team-run",
            "metrics": {},
            "model": "gpt-5",
            "model_provider": "OpenAI",
            "call_durations": [1.5],
            "step_executor_runs": None,
            "member_responses": [member],
            "workflow_agent_run": None,
        }
    )

    run = build_component_metrics_run(row)

    assert run["run_data"]["member_responses"] == [member]
    assert run["run_data"]["messages"] == [{"role": "assistant", "metrics": {"duration": 1.5}}]


def test_claim_metrics_refresh_returns_while_another_process_writes_a_day(mock_engine):
    """A claim whose lock wait times out returns None."""
    db = SingleStoreDb(db_engine=mock_engine, db_schema="test_schema")
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute.side_effect = OperationalError("INSERT", {}, Exception(1205, "Lock wait timeout exceeded"))
    db.Session = Mock(return_value=session)

    assert db._claim_metrics_refresh(TABLES["metrics_refreshes"], "worker") is None


def test_release_metrics_refresh_keeps_a_rebuild_mark_over_a_claim_of_no_fingerprint(mock_engine):
    """A mark a rebuild wrote after a claim that found no fingerprint stays, so the next calculation rebuilds
    yesterday and today."""
    db = SingleStoreDb(db_engine=mock_engine, db_schema="test_schema")
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute.return_value.scalar.return_value = ["rebuild", "mark"]
    db.Session = Mock(return_value=session)

    db._release_metrics_refresh(TABLES["metrics_refreshes"], "worker", fingerprint=["today"], claimed_fingerprint=None)

    statement = str(session.execute.call_args.args[0].compile(dialect=mysql.dialect()))
    assert "fingerprint" not in statement


def test_calculate_metrics_rebuild_from_records_a_failed_reopen_before_any_refresh(singlestore_db, monkeypatch):
    """A rebuild whose reopen fails before any metrics refresh ran is shown as failed with its error."""

    def _fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("agno.db.singlestore.singlestore.reopen_metrics_days_from", _fail)
    singlestore_db.Session = Mock(return_value=_FakeSession())

    with pytest.raises(RuntimeError):
        singlestore_db.calculate_metrics_dates(rebuild_from=TODAY - timedelta(days=3))
    singlestore_db._release_metrics_refresh.assert_called_once_with(
        TABLES["metrics_refreshes"], None, error="boom", started_at=None, finished_at=None
    )


def test_get_component_metrics_reads_every_owner_from_the_everyone_rows(singlestore_db):
    """Every owner is read from the everyone rows of the user metrics table, totalled in Python."""
    user_metrics_row = {
        "aggregation_period": "daily",
        "date": TODAY,
        "user_id": "",
        "agent_sessions_count": 2,
        "team_sessions_count": 1,
        "workflow_sessions_count": 0,
        "root_runs_count": 3,
        "token_details": {"cache_read_tokens": 4},
        "model_metrics": {"OpenAI": {"gpt-5": {"count": 3}}},
        "updated_at": 200,
    }
    singlestore_db.Session = Mock(
        return_value=_FakeSession({"test_user_metrics": [SimpleNamespace(_mapping=user_metrics_row)]})
    )

    metrics, latest_updated_at = singlestore_db.get_component_metrics(
        TODAY, TODAY, fields=["sessions_count", "root_runs_count", "cache_read_tokens", "model_metrics"]
    )

    assert metrics == [
        {
            "date": TODAY,
            "sessions_count": 3,
            "root_runs_count": 3,
            "cache_read_tokens": 4,
            "model_metrics": [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 3, "cost": None}],
        }
    ]
    assert latest_updated_at == 200


def test_a_read_never_calculates_before_the_first_calculation_finished(singlestore_db):
    """A read calculates no metrics before a first calculation has finished, nor once AgentOS calculates them."""
    singlestore_db._get_metrics_refresh_row = Mock(return_value=({"finished_at": None}, 0))
    singlestore_db.calculate_metrics_dates = Mock()
    singlestore_db.Session = Mock(return_value=_FakeSession())

    singlestore_db.get_metrics()
    singlestore_db.calculate_metrics_dates.assert_not_called()

    singlestore_db._get_metrics_refresh_row = Mock(return_value=({"finished_at": 1}, 0))
    singlestore_db._metrics_refreshed_at = 0.0
    singlestore_db.stop_metrics_refresh_on_read()
    singlestore_db.get_metrics()
    singlestore_db.calculate_metrics_dates.assert_not_called()


def test_get_metrics_versions(singlestore_db):
    """No version is read before a first calculation finished; then each everyone row's version, keyed by its period
    and date."""
    rows = [
        SimpleNamespace(aggregation_period="daily", date=TODAY - timedelta(days=1), version=1),
        SimpleNamespace(aggregation_period="monthly", date=TODAY.replace(day=1), version=4),
    ]
    singlestore_db.Session = Mock(return_value=_FakeSession({"test_user_metrics": rows}))
    singlestore_db._metrics_refreshed_at = float("inf")

    singlestore_db._get_metrics_refresh_row = Mock(return_value=({"finished_at": None}, 0))
    assert singlestore_db.get_metrics_versions(TODAY - timedelta(days=1), TODAY) is None

    singlestore_db._get_metrics_refresh_row = Mock(return_value=({"finished_at": 1}, 0))
    assert singlestore_db.get_metrics_versions(TODAY - timedelta(days=1), TODAY) == {
        f"daily {(TODAY - timedelta(days=1)).isoformat()}": 1,
        f"monthly {TODAY.replace(day=1).isoformat()}": 4,
    }
