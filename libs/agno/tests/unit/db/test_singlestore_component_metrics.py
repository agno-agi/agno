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
    build_component_metrics_runs_query,
    upsert_aggregate_metrics_row,
)
from agno.db.utils import calculate_date_component_metrics
from agno.run.base import RunStatus

TODAY = datetime.now(timezone.utc).date()


def _table(name: str, schema: dict) -> Table:
    """A table built from its schema without a database."""
    columns = [Column(column, config["type"]()) for column, config in schema.items() if not column.startswith("_")]
    return Table(name, MetaData(), *columns)


TABLES = {
    "sessions": _table("test_sessions", SESSION_TABLE_SCHEMA),
    "component_metrics": _table("test_component_metrics", get_table_schema_definition("component_metrics")),
    "aggregate_metrics": _table("test_aggregate_metrics", get_table_schema_definition("aggregate_metrics")),
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


def test_calculate_metrics_writes_each_day_and_its_aggregate_metrics_rows_last(singlestore_db):
    """Each day gets one row per user, then its aggregate metrics rows; only a day ended a day ago is completed, and the
    lock is released with the fingerprint."""
    session = _FakeSession({"test_sessions": [_session_row("alice"), _session_row("bob")]})
    singlestore_db.Session = Mock(return_value=session)

    calculated_dates = singlestore_db.calculate_metrics_dates()

    assert calculated_dates == [TODAY - timedelta(days=days_ago) for days_ago in [2, 1, 0]]
    rows = _written(session, "test_component_metrics")
    assert [(row["date"], row["user_id"], row["sessions_count"]) for row in rows] == [
        (TODAY - timedelta(days=days_ago), user_id, 1) for days_ago in [2, 1, 0] for user_id in ["alice", "bob"]
    ]
    everyone_rows = [row for row in _written(session, "test_aggregate_metrics") if row["user_id"] == ""]
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
    upsert_aggregate_metrics_row(
        session,
        TABLES["aggregate_metrics"],
        {"aggregation_period": "daily", "date": TODAY, "user_id": "", "completed": True},
        read_version=3,
    )

    statement = str(session.execute.call_args.args[0].compile(dialect=mysql.dialect()))
    assert "ON DUPLICATE KEY UPDATE" in statement
    completed = statement.index("completed = (test_aggregate_metrics.version = %s AND")
    assert completed < statement.index("version = (test_aggregate_metrics.version + %s)")


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


def test_has_legacy_runs_column_reads_the_connection_database_without_a_db_schema(mock_engine):
    """Without a db_schema the runs column is looked up in the connection's database."""
    db = SingleStoreDb(db_engine=mock_engine)
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute.return_value.scalar.return_value = 1
    db.Session = Mock(return_value=session)

    assert db._has_legacy_runs_column() is True
    statement, params = session.execute.call_args.args
    assert "TABLE_SCHEMA = COALESCE(:schema, DATABASE())" in str(statement)
    assert params["schema"] is None


def test_tool_calls_the_runs_query_reads_are_counted_in_tool_metrics():
    """Each tool call the runs query reads is put back on its run, a nested run's read as stored, and counted under
    its tool."""
    tool_call = {"toolkit": None, "tool_name": "search", "tool_call_error": None, "metrics": {"duration": 0.4}}
    run = build_component_metrics_run(
        SimpleNamespace(
            _mapping={
                "run_id": "team-run",
                "run_type": "team",
                "agent_id": None,
                "team_id": "team-1",
                "workflow_id": None,
                "user_id": "alice",
                "parent_run_id": None,
                "status": RunStatus.completed.value,
                "metrics": None,
                "model": None,
                "model_provider": None,
                "call_durations": None,
                "tools": [tool_call],
                "step_executor_runs": None,
                "member_responses": [{"run_id": "member-run", "agent_id": "agent-1", "tools": [tool_call]}],
                "workflow_agent_run": None,
            }
        )
    )

    (row,) = calculate_date_component_metrics(TODAY, [], [run], set(), [])
    assert row["tool_metrics"] == {
        "": {"search": {"count": 2, "failed_count": 0, "total_ms": 800, "max_ms": 400, "buckets": {"le_400": 2}}}
    }


def test_runs_query_reads_only_what_tool_metrics_counts_and_skips_the_copied_tool_calls():
    """Of each tool call of a run the runs query reads only what tool_metrics counts, never its arguments or result,
    and it skips those answered in the first messages a forked run copied."""
    runs_table = _table("test_runs", get_table_schema_definition("runs"))
    statement = str(
        build_component_metrics_runs_query(runs_table, 0, 1).compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "JSON_EXTRACT_JSON(test_runs.run_data, 'tools')" in statement
    assert "tool_args" not in statement and "'result'" not in statement
    assert "'role') = 'tool'" in statement
    assert ".run_id IS NULL GROUP BY test_runs.run_id" in statement


def test_component_metrics_read_returns_tool_metrics(singlestore_db):
    """A read returns the tool_metrics of the rows it totals."""
    tool_metrics = {
        "": {"search": {"count": 2, "failed_count": 1, "total_ms": 800, "max_ms": 600, "buckets": {"le_600": 2}}}
    }
    session = _FakeSession(
        {
            "test_aggregate_metrics": [
                SimpleNamespace(
                    aggregation_period="daily", date=TODAY, user_id="", updated_at=1, tool_metrics=tool_metrics
                )
            ]
        }
    )
    singlestore_db.Session = Mock(return_value=session)

    metrics, latest_updated_at = singlestore_db.get_component_metrics(
        starting_date=TODAY, ending_date=TODAY, fields=["tool_metrics"]
    )

    assert metrics == [{"date": TODAY, "tool_metrics": tool_metrics}]
    assert latest_updated_at == 1


def test_get_metrics_returns_a_day_with_only_a_regenerated_run(singlestore_db):
    """A day row with tokens but no sessions or runs counted is read, as get_metrics_totals counts it."""
    session = _FakeSession()
    session.execute = Mock(wraps=session.execute)
    singlestore_db.Session = Mock(return_value=session)

    singlestore_db._get_aggregate_metrics_rows(TODAY, TODAY, "")

    statement = str(session.execute.call_args_list[0].args[0].compile(dialect=mysql.dialect()))
    assert "test_aggregate_metrics.total_tokens > %s" in statement
