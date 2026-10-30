import time
from datetime import date, datetime, timedelta, timezone
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
from agno.db.mysql.utils import build_os_metrics_run, upsert_os_metrics_totals_row

TODAY = datetime.now(timezone.utc).date()


def _table(name: str, schema: dict) -> Table:
    """A table built from its schema without a database."""
    columns = [Column(column, config["type"]()) for column, config in schema.items() if not column.startswith("_")]
    return Table(name, MetaData(), *columns)


TABLES = {
    "sessions": _table("test_sessions", SESSION_TABLE_SCHEMA),
    "os_metrics": _table("test_os_metrics", get_table_schema_definition("os_metrics")),
    "os_metrics_totals": _table("test_os_metrics_totals", get_table_schema_definition("os_metrics_totals")),
}


def _get_table(table_type, create_table_if_not_found=False):
    return TABLES.get(table_type)


def _session_row(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        _mapping={
            "session_type": "agent",
            "user_id": user_id,
            "agent_id": "agent-1",
            "team_id": None,
            "workflow_id": None,
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
        result.first.return_value = rows[0] if rows else None
        result.mappings.return_value.first.return_value = None
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


def _lock_connection(locked: int = 1) -> MagicMock:
    """A connection whose GET_LOCK returns the given value."""
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.scalar.return_value = locked
    return conn


def _async_lock_connection(locked: int = 1) -> MagicMock:
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=Mock(**{"scalar.return_value": locked}))
    conn.commit = AsyncMock()
    return conn


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
    """Create a MySQLDb instance with mock engine, rebuilding from two days back"""
    db = MySQLDb(db_engine=mock_engine, db_schema="test_schema")
    db._get_table = Mock(side_effect=_get_table)
    db._get_os_metrics_calculation_starting_date = Mock(return_value=TODAY - timedelta(days=2))
    db._get_os_metrics_fingerprint = Mock(return_value=("fingerprint",))
    return db


@pytest.fixture
def async_mysql_db(mock_async_engine):
    """Create an AsyncMySQLDb instance with mock engine, rebuilding from two days back"""
    db = AsyncMySQLDb(db_engine=mock_async_engine, db_schema="test_schema")
    db._get_table = AsyncMock(side_effect=_get_table)
    db._get_os_metrics_calculation_starting_date = AsyncMock(return_value=TODAY - timedelta(days=2))
    db._get_os_metrics_fingerprint = AsyncMock(return_value=("fingerprint",))
    return db


def _written(session, table_name):
    return [row for name, rows in session.writes if name == table_name for row in rows]


def test_calculate_os_metrics(mysql_db):
    """Each day gets one row per user, then its totals row; only a day ended a day ago is completed."""
    session = _FakeSession({"test_sessions": [_session_row("alice"), _session_row("bob")]})
    mysql_db.Session = Mock(session_factory=Mock(return_value=session))
    mysql_db.db_engine.connect = Mock(return_value=_lock_connection())

    results, written_totals_rows = mysql_db._calculate_os_metrics(wait_for_rebuild=True)

    rows = _written(session, "test_os_metrics")
    assert [(row["date"], row["user_id"], row["sessions_count"]) for row in rows] == [
        (TODAY - timedelta(days=days_ago), user_id, 1) for days_ago in [2, 1, 0] for user_id in ["alice", "bob"]
    ]
    assert len(results) == 6
    assert [name for name, _ in session.writes] == ["test_os_metrics", "test_os_metrics_totals"] * 3
    totals_rows = _written(session, "test_os_metrics_totals")
    assert [(row["date"], row["sessions_count"], row["completed"]) for row in totals_rows] == [
        (TODAY - timedelta(days=2), 2, True),
        (TODAY - timedelta(days=1), 2, False),
        (TODAY, 2, False),
    ]
    assert len(written_totals_rows) == 3


def test_legacy_runs_are_counted_and_forked_session_copies_are_not(mysql_db):
    """A run kept only in the legacy runs column counts on the day it was created; a run a forked session copied does
    not."""
    schema = dict(SESSION_TABLE_SCHEMA)
    schema["runs"] = {"type": mysql.JSON}
    legacy_sessions = _table("test_sessions", schema)
    mysql_db._get_table = Mock(
        side_effect=lambda table_type, create_table_if_not_found=False: (
            legacy_sessions if table_type == "sessions" else TABLES.get(table_type)
        )
    )
    legacy_run = {
        "run_id": "legacy-run",
        "agent_id": "agent-1",
        "status": "COMPLETED",
        "model": "gpt-5",
        "metrics": {"total_tokens": 30},
        "created_at": int(datetime.combine(TODAY - timedelta(days=2), datetime.min.time(), timezone.utc).timestamp()),
    }
    copied_run = {"run_id": "copied-run", "agent_id": "agent-1", "forked_from_session_id": "s0", "metrics": {}}
    session_row = _session_row("alice")
    session_row._mapping["created_at"] = 0
    session_row._mapping["runs"] = [legacy_run, copied_run]
    session = _FakeSession({"test_sessions": [session_row]})
    mysql_db.Session = Mock(return_value=session, session_factory=Mock(return_value=session))
    mysql_db.db_engine.connect = Mock(return_value=_lock_connection())

    mysql_db._calculate_os_metrics(wait_for_rebuild=True)

    row = _written(session, "test_os_metrics")[0]
    assert (row["user_id"], row["sessions_count"], row["runs_count"], row["total_tokens"]) == ("alice", 1, 1, 30)


def test_lazy_refresh_skipped_when_nothing_new(mysql_db):
    """A lazy refresh with the same sessions and runs as the last rebuild takes no lock and writes nothing."""
    mysql_db.Session = Mock(session_factory=Mock(return_value=_FakeSession()))
    mysql_db.db_engine.connect = Mock(return_value=_lock_connection())
    mysql_db._calculate_os_metrics(wait_for_rebuild=True)

    assert mysql_db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert mysql_db.db_engine.connect.call_count == 1


def test_rebuild_skipped_while_another_holds_the_lock(mysql_db):
    """A lazy refresh does not wait for another rebuild, and the next read tries again."""
    mysql_db.db_engine.connect = Mock(return_value=_lock_connection(locked=0))

    assert mysql_db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert mysql_db._os_metrics_refreshed_at == 0.0


def test_calculate_month_os_metrics(mysql_db):
    """A completed month gets its rows from its days' rows, then its totals row."""
    month_start = date(2026, 9, 1)
    days = [month_start + timedelta(days=offset) for offset in range(30)]
    day_row = {"aggregation_period": "daily", "user_id": "alice", "component_type": "agent", "component_id": "a-1"}
    session = _FakeSession(
        {
            "test_os_metrics_totals": [
                SimpleNamespace(aggregation_period="daily", date=day, completed=True) for day in days
            ],
            "test_os_metrics": [
                SimpleNamespace(_mapping={**day_row, "date": day, "parent_component_id": "", "sessions_count": 1})
                for day in days
            ],
        }
    )
    mysql_db.Session = Mock(session_factory=Mock(return_value=session))

    totals_rows = mysql_db._calculate_month_os_metrics(TABLES["os_metrics"], TABLES["os_metrics_totals"], Mock())

    assert [(row["aggregation_period"], row["date"], row["sessions_count"]) for row in totals_rows] == [
        ("monthly", month_start, 30)
    ]
    month_rows = _written(session, "test_os_metrics")
    assert [(row["aggregation_period"], row["user_id"], row["sessions_count"]) for row in month_rows] == [
        ("monthly", "alice", 30)
    ]
    assert [name for name, _ in session.writes] == ["test_os_metrics", "test_os_metrics_totals"]


def test_totals_row_version_moves_in_the_upsert():
    """A stored totals row's version is moved by the database, in the same statement as the write."""
    session = Mock()
    upsert_os_metrics_totals_row(session, TABLES["os_metrics_totals"], {"aggregation_period": "daily", "date": TODAY})

    statement = str(session.execute.call_args.args[0].compile(dialect=mysql.dialect()))
    assert "ON DUPLICATE KEY UPDATE" in statement
    assert "version = (test_os_metrics_totals.version + %s)" in statement


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

    run = build_os_metrics_run(row)

    members = run["run_data"]["member_responses"]
    assert [member["run_id"] for member in members] == ["m1", "m2"]
    assert [nested["run_id"] for nested in members[0]["member_responses"]] == ["m1-1"]
    assert run["run_data"]["messages"] == [{"role": "assistant", "metrics": {"duration": 1.5}}]


def test_get_os_metrics(mysql_db):
    """Every owner is read from the totals rows; one owner from that owner's rows."""
    day_rows = [SimpleNamespace(date=TODAY, updated_at=200, sessions_count=2, runs_count=3)]
    mysql_db._os_metrics_refreshed_at = time.time()
    mysql_db.Session = Mock(return_value=_FakeSession({"test_os_metrics_totals": day_rows}))

    os_metrics, latest_updated_at = mysql_db.get_os_metrics(TODAY, TODAY, fields=["sessions_count", "runs_count"])

    assert os_metrics == [{"date": TODAY, "sessions_count": 2, "runs_count": 3}]
    assert latest_updated_at == 200

    mysql_db.Session = Mock(return_value=_FakeSession({"test_os_metrics": day_rows}))
    totals, _ = mysql_db.get_os_metrics_totals(TODAY, TODAY, user_id="alice", fields=["sessions_count"])
    assert totals == {"sessions_count": 2}


def test_get_os_metrics_versions(mysql_db):
    """None while sessions exist and yesterday has no totals row, the version of each totals row once built."""
    mysql_db._os_metrics_refreshed_at = time.time()
    mysql_db._os_metrics_fingerprint = ("fingerprint",)
    mysql_db.Session = Mock(return_value=_FakeSession({"test_sessions": [SimpleNamespace(session_id="s-1")]}))

    assert mysql_db.get_os_metrics_versions(TODAY - timedelta(days=1), TODAY) is None
    assert mysql_db._os_metrics_fingerprint is None

    built_days = [
        SimpleNamespace(aggregation_period="daily", date=TODAY - timedelta(days=1), version=1),
        SimpleNamespace(aggregation_period="daily", date=TODAY, version=4),
    ]
    mysql_db.Session = Mock(return_value=_FakeSession({"test_os_metrics_totals": built_days}))
    assert mysql_db.get_os_metrics_versions(TODAY - timedelta(days=1), TODAY) == {
        f"daily {(TODAY - timedelta(days=1)).isoformat()}": 1,
        f"daily {TODAY.isoformat()}": 4,
    }


@pytest.mark.asyncio
async def test_async_calculate_os_metrics(async_mysql_db):
    """Each day gets one row per user, then its totals row, and a lazy refresh with nothing new takes no lock."""
    session = _FakeAsyncSession({"test_sessions": [_session_row("alice"), _session_row("bob")]})
    async_mysql_db.async_session_factory = Mock(return_value=session)
    async_mysql_db.db_engine.connect = Mock(return_value=_async_lock_connection())

    results, written_totals_rows = await async_mysql_db._calculate_os_metrics(wait_for_rebuild=True)

    assert len(results) == 6
    assert [name for name, _ in session.writes] == ["test_os_metrics", "test_os_metrics_totals"] * 3
    totals_rows = _written(session, "test_os_metrics_totals")
    assert [(row["date"], row["sessions_count"], row["completed"]) for row in totals_rows] == [
        (TODAY - timedelta(days=2), 2, True),
        (TODAY - timedelta(days=1), 2, False),
        (TODAY, 2, False),
    ]
    assert len(written_totals_rows) == 3

    assert await async_mysql_db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert async_mysql_db.db_engine.connect.call_count == 1


@pytest.mark.asyncio
async def test_async_calculate_month_os_metrics(async_mysql_db):
    """A completed month gets its rows from its days' rows, then its totals row."""
    month_start = date(2026, 9, 1)
    days = [month_start + timedelta(days=offset) for offset in range(30)]
    day_row = {"aggregation_period": "daily", "user_id": "alice", "component_type": "agent", "component_id": "a-1"}
    session = _FakeAsyncSession(
        {
            "test_os_metrics_totals": [
                SimpleNamespace(aggregation_period="daily", date=day, completed=True) for day in days
            ],
            "test_os_metrics": [
                SimpleNamespace(_mapping={**day_row, "date": day, "parent_component_id": "", "sessions_count": 1})
                for day in days
            ],
        }
    )
    async_mysql_db.async_session_factory = Mock(return_value=session)

    totals_rows = await async_mysql_db._calculate_month_os_metrics(
        TABLES["os_metrics"], TABLES["os_metrics_totals"], Mock()
    )

    assert [(row["aggregation_period"], row["date"], row["sessions_count"]) for row in totals_rows] == [
        ("monthly", month_start, 30)
    ]
    month_rows = _written(session, "test_os_metrics")
    assert [(row["aggregation_period"], row["user_id"], row["sessions_count"]) for row in month_rows] == [
        ("monthly", "alice", 30)
    ]
    assert [name for name, _ in session.writes] == ["test_os_metrics", "test_os_metrics_totals"]


@pytest.mark.asyncio
async def test_async_get_os_metrics(async_mysql_db):
    """Every owner is read from the totals rows."""
    day_rows = [SimpleNamespace(date=TODAY, updated_at=200, sessions_count=2, runs_count=3)]
    async_mysql_db._os_metrics_refreshed_at = time.time()
    async_mysql_db.async_session_factory = Mock(return_value=_FakeAsyncSession({"test_os_metrics_totals": day_rows}))

    os_metrics, latest_updated_at = await async_mysql_db.get_os_metrics(
        TODAY, TODAY, fields=["sessions_count", "runs_count"]
    )

    assert os_metrics == [{"date": TODAY, "sessions_count": 2, "runs_count": 3}]
    assert latest_updated_at == 200


@pytest.mark.asyncio
async def test_async_get_os_metrics_versions(async_mysql_db):
    """None while sessions exist and yesterday has no totals row."""
    async_mysql_db._os_metrics_refreshed_at = time.time()
    async_mysql_db.async_session_factory = Mock(
        return_value=_FakeAsyncSession({"test_sessions": [SimpleNamespace(session_id="s-1")]})
    )

    assert await async_mysql_db.get_os_metrics_versions(TODAY - timedelta(days=1), TODAY) is None
