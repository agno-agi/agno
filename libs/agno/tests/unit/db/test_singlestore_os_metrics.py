"""Unit tests for the OS Metrics related methods of the SingleStoreDb class"""

import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine

from agno.db.singlestore import singlestore as singlestore_module
from agno.db.singlestore.singlestore import SingleStoreDb

TODAY = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)


def _row(**values) -> SimpleNamespace:
    """A result row, read by attribute or through _mapping"""
    return SimpleNamespace(_mapping=values, **values)


class _Result:
    """The result of one statement, whichever way its rows are read"""

    def __init__(self, rows=(), scalar=None, rowcount=0):
        self.rows = list(rows)
        self.scalar_value = scalar
        self.rowcount = rowcount

    def fetchall(self):
        return self.rows

    def fetchmany(self, size):
        batch, self.rows = self.rows[:size], self.rows[size:]
        return batch

    def scalar(self):
        return self.scalar_value

    def scalar_one(self):
        return self.scalar_value

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        return self.rows[0]

    def scalars(self):
        return _Result(self.rows)

    def all(self):
        return self.rows

    def mappings(self):
        return self


def _session_factory(handler) -> Mock:
    """A session factory whose execute() answers each statement with handler(sql, params)"""
    session = MagicMock()
    session.__enter__.return_value = session
    session.begin.return_value.__enter__.return_value = session

    def execute(statement, *args, **kwargs):
        compiled = statement.compile(dialect=mysql.dialect())
        return handler(str(compiled), compiled.params)

    session.execute.side_effect = execute
    return Mock(return_value=session)


def _day_start(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())


@pytest.fixture
def singlestore_db():
    """Create a SingleStoreDb instance with mock engine, and the tables built from their schemas"""
    engine = Mock(spec=Engine)
    engine.url = "fake:///url"
    db = SingleStoreDb(db_engine=engine)
    tables = {
        table_type: db._create_table_structure_only(table_name=f"test_{table_type}", table_type=table_type)
        for table_type in ["sessions", "runs", "os_metrics", "os_metrics_totals"]
    }
    db._get_table = Mock(side_effect=lambda table_type, create_table_if_not_found=False: tables[table_type])
    return db


@pytest.fixture
def writes(monkeypatch):
    """Every row the rebuild writes, in the order it writes them"""
    written = []
    monkeypatch.setattr(
        singlestore_module,
        "bulk_upsert_os_metrics",
        lambda session, table, os_metrics_records: written.extend(("row", row) for row in os_metrics_records),
    )
    monkeypatch.setattr(
        singlestore_module,
        "upsert_os_metrics_totals_row",
        lambda session, table, totals_row: written.append(("totals", totals_row)),
    )
    return written


def _rebuild_handler(sql: str, params: dict) -> _Result:
    """Yesterday has one agent session of alice and one completed run; today has nothing"""
    if "FROM test_sessions" in sql:
        if params.get("created_at_1") == _day_start(YESTERDAY):
            return _Result(
                [_row(session_type="agent", user_id="alice", agent_id="researcher", team_id=None, workflow_id=None)]
            )
        return _Result([])
    if "FROM test_runs" in sql:
        if params.get("created_at_1") == _day_start(YESTERDAY):
            run = _row(
                run_id="run-1",
                run_type="agent",
                agent_id="researcher",
                team_id=None,
                workflow_id=None,
                user_id="alice",
                parent_run_id=None,
                status="COMPLETED",
                metrics={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "duration": 1.2, "details": 1},
                model="gpt-5",
                model_provider="OpenAI",
                call_durations=[0.8],
                step_executor_runs=None,
                member_responses=None,
                workflow_agent_run=None,
            )
            return _Result([run])
        return _Result([])
    # The latest completed day, the stored rows of a day and its stored total row: none yet
    return _Result([])


def test_calculate_os_metrics_writes_each_day_and_its_totals_row_last(singlestore_db, writes):
    """Each day gets its rows, then its totals row; a day without traffic gets a totals row of zeros."""
    singlestore_db.Session = _session_factory(_rebuild_handler)
    singlestore_db._get_os_metrics_calculation_starting_date = Mock(return_value=YESTERDAY)
    singlestore_db._get_os_metrics_fingerprint = Mock(return_value=("fingerprint",))
    singlestore_db._lock_os_metrics = Mock(return_value=123)
    singlestore_db._unlock_os_metrics = Mock()
    singlestore_db._calculate_month_os_metrics = Mock(return_value=[])

    results, written_totals_rows = singlestore_db._calculate_os_metrics(wait_for_rebuild=True)

    assert [(kind, row["date"]) for kind, row in writes] == [
        ("row", YESTERDAY),
        ("totals", YESTERDAY),
        ("totals", TODAY),
    ]
    row = writes[0][1]
    assert (row["user_id"], row["component_type"], row["component_id"], row["parent_component_id"]) == (
        "alice",
        "agent",
        "researcher",
        "",
    )
    assert (row["sessions_count"], row["runs_count"], row["total_tokens"]) == (1, 1, 15)
    assert row["status_metrics"] == {"COMPLETED": 1}
    assert row["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 1}]
    assert (row["duration_runs_count"], row["max_duration_ms"], row["model_calls_count"]) == (1, 1200, 1)

    yesterday_totals, today_totals = writes[1][1], writes[2][1]
    assert (yesterday_totals["aggregation_period"], yesterday_totals["runs_count"]) == ("daily", 1)
    assert yesterday_totals["completed"] is False
    assert (today_totals["sessions_count"], today_totals["runs_count"]) == (0, 0)

    assert results == [row]
    assert written_totals_rows == [yesterday_totals, today_totals]
    # The lock is taken for each day, and released with the time it was taken until
    assert singlestore_db._lock_os_metrics.call_count == 2
    singlestore_db._unlock_os_metrics.assert_called_with(singlestore_db._get_table("os_metrics_totals"), 123)
    assert singlestore_db._os_metrics_fingerprint == ("fingerprint",)


def test_calculate_os_metrics_skips_a_lazy_refresh_with_nothing_new(singlestore_db, writes):
    """A lazy refresh skips when the sessions and runs are those of the last rebuild; an explicit one rebuilds."""
    singlestore_db.Session = _session_factory(_rebuild_handler)
    singlestore_db._get_os_metrics_calculation_starting_date = Mock(return_value=YESTERDAY)
    singlestore_db._get_os_metrics_fingerprint = Mock(return_value=("fingerprint",))
    singlestore_db._os_metrics_fingerprint = ("fingerprint",)
    singlestore_db._lock_os_metrics = Mock(return_value=123)
    singlestore_db._unlock_os_metrics = Mock()
    singlestore_db._calculate_month_os_metrics = Mock(return_value=[])

    assert singlestore_db._calculate_os_metrics(wait_for_rebuild=False) is None
    singlestore_db._lock_os_metrics.assert_not_called()
    assert writes == []

    assert singlestore_db._calculate_os_metrics(wait_for_rebuild=True) is not None
    assert writes


def test_calculate_os_metrics_skips_while_another_process_rebuilds(singlestore_db, writes):
    """A lazy refresh that finds the lock taken writes nothing and lets the next read try again."""
    singlestore_db.Session = _session_factory(_rebuild_handler)
    singlestore_db._get_os_metrics_calculation_starting_date = Mock(return_value=YESTERDAY)
    singlestore_db._get_os_metrics_fingerprint = Mock(return_value=("fingerprint",))
    singlestore_db._lock_os_metrics = Mock(return_value=None)

    assert singlestore_db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert writes == []
    assert singlestore_db._os_metrics_refreshed_at == 0.0


def test_calculate_month_os_metrics_writes_month_rows_then_its_totals_row(singlestore_db, writes, monkeypatch):
    """A completed month without month rows gets them from its days' rows, added up a batch at a time, then a
    completed month totals row."""
    monkeypatch.setattr(singlestore_module, "OS_METRICS_BATCH_SIZE", 1)
    month_start = date(2026, 9, 1)
    daily_row = {
        "aggregation_period": "daily",
        "user_id": "alice",
        "component_type": "agent",
        "component_id": "researcher",
        "parent_component_id": "",
        "sessions_count": 1,
        "runs_count": 2,
    }

    def handler(sql: str, params: dict) -> _Result:
        if "FROM test_os_metrics_totals" in sql:
            return _Result(
                [
                    _row(aggregation_period="daily", date=date(2026, 9, 1), completed=True),
                    _row(aggregation_period="daily", date=date(2026, 9, 30), completed=True),
                    _row(aggregation_period="daily", date=date(2026, 10, 1), completed=True),
                ]
            )
        return _Result([_row(**daily_row, date=date(2026, 9, 1)), _row(**daily_row, date=date(2026, 9, 30))])

    singlestore_db.Session = _session_factory(handler)
    singlestore_db._lock_os_metrics = Mock(return_value=123)
    singlestore_db._unlock_os_metrics = Mock()

    results = singlestore_db._calculate_month_os_metrics(
        singlestore_db._get_table("os_metrics"), singlestore_db._get_table("os_metrics_totals"), True
    )

    assert [(kind, row["aggregation_period"], row["date"]) for kind, row in writes] == [
        ("row", "monthly", month_start),
        ("totals", "monthly", month_start),
    ]
    assert (writes[0][1]["sessions_count"], writes[0][1]["runs_count"]) == (2, 4)
    assert writes[1][1]["completed"] is True
    assert results == [writes[1][1]]
    singlestore_db._unlock_os_metrics.assert_called_once()


def test_get_os_metrics_reads_every_owner_from_the_totals_rows(singlestore_db):
    """A read for every owner totals the totals rows of each day, oldest first, with only the fields asked for."""
    statements = []

    def handler(sql: str, params: dict) -> _Result:
        statements.append(sql)
        return _Result(
            [
                _row(date=YESTERDAY, updated_at=200, sessions_count=2, status_metrics={"COMPLETED": 3}),
                _row(date=YESTERDAY - timedelta(days=1), updated_at=100, sessions_count=1, status_metrics={}),
            ]
        )

    singlestore_db.Session = _session_factory(handler)
    singlestore_db._os_metrics_refreshed_at = time.time()

    os_metrics, latest_updated_at = singlestore_db.get_os_metrics(
        YESTERDAY - timedelta(days=1), YESTERDAY, fields=["sessions_count", "status_metrics"]
    )

    assert os_metrics == [
        {"date": YESTERDAY - timedelta(days=1), "sessions_count": 1, "status_metrics": {}},
        {"date": YESTERDAY, "sessions_count": 2, "status_metrics": {"COMPLETED": 3}},
    ]
    assert latest_updated_at == 200
    assert "FROM test_os_metrics_totals" in statements[0]


def test_get_os_metrics_totals_for_one_user(singlestore_db):
    """The totals of one user's rows over a date range are one record, read from that user's rows."""
    statements = []

    def handler(sql: str, params: dict) -> _Result:
        statements.append((sql, params))
        return _Result(
            [
                _row(date=YESTERDAY, updated_at=200, runs_count=2, max_duration_ms=900),
                _row(date=YESTERDAY, updated_at=150, runs_count=1, max_duration_ms=1500),
            ]
        )

    singlestore_db.Session = _session_factory(handler)
    singlestore_db._os_metrics_refreshed_at = time.time()

    totals, latest_updated_at = singlestore_db.get_os_metrics_totals(
        YESTERDAY, YESTERDAY, user_id="alice", fields=["runs_count", "max_duration_ms"]
    )

    assert totals == {"runs_count": 3, "max_duration_ms": 1500}
    assert latest_updated_at == 200
    sql, params = statements[0]
    assert "FROM test_os_metrics " in sql
    assert "alice" in params.values()


def test_get_os_metrics_versions(singlestore_db):
    """The versions of the totals rows, keyed by period and date; None while yesterday is not built."""
    built_days = [YESTERDAY, TODAY]

    def handler(sql: str, params: dict) -> _Result:
        if "version" in sql:
            return _Result([_row(aggregation_period="daily", date=YESTERDAY, version=3)])
        if "FROM test_os_metrics_totals" in sql:
            return _Result(built_days)
        # A session exists
        return _Result([_row(session_id="session-1")])

    singlestore_db.Session = _session_factory(handler)
    singlestore_db._os_metrics_refreshed_at = time.time()
    singlestore_db._calculate_os_metrics = Mock()

    assert singlestore_db.get_os_metrics_versions(YESTERDAY, TODAY) == {f"daily {YESTERDAY.isoformat()}": 3}

    built_days.remove(YESTERDAY)
    singlestore_db._os_metrics_fingerprint = ("fingerprint",)
    assert singlestore_db.get_os_metrics_versions(YESTERDAY, TODAY) is None
    assert singlestore_db._os_metrics_fingerprint is None


def test_refresh_os_metrics(singlestore_db):
    """A refresh reports when the totals rows were last updated before and after it, and whether any was written."""
    updated_at = iter([100, 200, 200, 200])
    singlestore_db.Session = _session_factory(lambda sql, params: _Result(scalar=next(updated_at)))
    singlestore_db._calculate_os_metrics = Mock(return_value=([], [{"date": YESTERDAY}]))
    assert singlestore_db.refresh_os_metrics() == (100, 200, True)

    singlestore_db._calculate_os_metrics = Mock(return_value=None)
    assert singlestore_db.refresh_os_metrics() == (200, 200, False)
