"""Unit tests for MySQLDb scheduler methods and initialization."""

from contextlib import contextmanager
from unittest.mock import Mock, patch, MagicMock

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import Table

from agno.db.mysql.mysql import MySQLDb
from agno.db.mysql.schemas import (
    SCHEDULE_TABLE_SCHEMA,
    get_table_schema_definition,
    _get_schedule_runs_table_schema,
)
from agno.db.utils import json_serializer


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

class _ColumnMock(Mock):
    """Mock that supports comparison operators like SQLAlchemy Column objects."""

    def __le__(self, other):
        return Mock()

    def __lt__(self, other):
        return Mock()

    def __ge__(self, other):
        return Mock()

    def __gt__(self, other):
        return Mock()


@pytest.fixture
def mock_engine():
    engine = Mock(spec=Engine)
    engine.url = "mysql://fake"
    return engine


@pytest.fixture
def mock_session():
    """Mock Session supporting ``with Session() as sess, sess.begin():``."""
    session = Mock(spec=Session)
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)

    begin_ctx = Mock()
    begin_ctx.__enter__ = Mock(return_value=session)
    begin_ctx.__exit__ = Mock(return_value=None)
    session.begin = Mock(return_value=begin_ctx)
    return session


@pytest.fixture
def mysql_db(mock_engine):
    return MySQLDb(
        db_engine=mock_engine,
        db_schema="test_schema",
        session_table="test_sessions",
    )


def _mock_table():
    """Return a mock Table whose columns support SQLAlchemy-style comparisons."""
    table = Mock(spec=Table)
    table.c = Mock()
    for col in (
        "id", "name", "enabled", "created_at", "next_run_at",
        "locked_by", "locked_at", "schedule_id",
    ):
        setattr(table.c, col, _ColumnMock())
    return table


@contextmanager
def _patch_sql():
    """Patch select / func / or_ so query building stays inside mock-land."""
    chain = MagicMock()
    chain.return_value = chain
    chain.where.return_value = chain
    chain.select_from.return_value = chain
    chain.alias.return_value = chain
    chain.order_by.return_value = chain
    chain.limit.return_value = chain
    chain.offset.return_value = chain
    chain.with_for_update.return_value = chain

    with patch("agno.db.mysql.mysql.select", chain), \
         patch("agno.db.mysql.mysql.func") as mock_func, \
         patch("agno.db.mysql.mysql.or_", return_value=Mock()):
        mock_func.count.return_value = Mock()
        yield


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestMySQLDbInit:
    def test_init_with_engine(self, mock_engine):
        db = MySQLDb(db_engine=mock_engine, session_table="sessions")
        assert db.db_engine is mock_engine
        assert db.db_schema == "ai"
        assert db.session_table_name == "sessions"

    @patch("agno.db.mysql.mysql.create_engine")
    def test_init_with_url(self, mock_create_engine):
        mock_eng = Mock(spec=Engine)
        mock_create_engine.return_value = mock_eng
        db = MySQLDb(db_url="mysql://user:pass@localhost/db", session_table="s")
        mock_create_engine.assert_called_once_with(
            "mysql://user:pass@localhost/db",
            json_serializer=json_serializer,
        )
        assert db.db_engine is mock_eng

    def test_init_without_engine_or_url(self):
        with pytest.raises((ValueError, AttributeError)):
            MySQLDb(session_table="sessions")

    def test_default_schedule_table_names(self, mock_engine):
        db = MySQLDb(db_engine=mock_engine, session_table="s")
        assert db.schedules_table_name == "agno_schedules"
        assert db.schedule_runs_table_name == "agno_schedule_runs"

    def test_deterministic_id(self, mock_engine):
        a = MySQLDb(db_engine=mock_engine)
        b = MySQLDb(db_engine=mock_engine)
        assert a.id == b.id


# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

class TestScheduleSchemas:
    def test_schedule_schema_fields(self):
        actual = {k for k in SCHEDULE_TABLE_SCHEMA if not k.startswith("_")}
        expected = {
            "id", "name", "description", "method", "endpoint",
            "payload", "cron_expr", "timezone", "timeout_seconds",
            "max_retries", "retry_delay_seconds", "enabled",
            "next_run_at", "locked_by", "locked_at", "created_at", "updated_at",
        }
        assert expected == actual

    def test_schedule_runs_schema_fields(self):
        schema = _get_schedule_runs_table_schema()
        expected = {
            "id", "schedule_id", "attempt", "triggered_at",
            "completed_at", "status", "status_code", "run_id",
            "session_id", "error", "input", "output",
            "requirements", "created_at",
        }
        assert expected == set(schema.keys())

    def test_get_table_schema_definition_schedules(self):
        assert get_table_schema_definition("schedules") is SCHEDULE_TABLE_SCHEMA

    def test_get_table_schema_definition_schedule_runs(self):
        schema = get_table_schema_definition("schedule_runs")
        assert "schedule_id" in schema

    def test_schedule_runs_fk_custom_table(self):
        schema = _get_schedule_runs_table_schema(
            schedules_table_name="my_sched", db_schema="mydb"
        )
        assert schema["schedule_id"]["foreign_key"] == "mydb.my_sched.id"

    def test_schedule_has_composite_index(self):
        indexes = SCHEDULE_TABLE_SCHEMA.get("__composite_indexes__", [])
        names = [idx["name"] for idx in indexes]
        assert "enabled_next_run_at" in names


# ---------------------------------------------------------------------------
# _get_table routing
# ---------------------------------------------------------------------------

class TestGetTableRouting:
    def test_routes_schedules(self, mysql_db):
        mock_t = _mock_table()
        mysql_db._get_or_create_table = Mock(return_value=mock_t)
        assert mysql_db._get_table("schedules") is mock_t
        mysql_db._get_or_create_table.assert_called_once_with(
            table_name=mysql_db.schedules_table_name,
            table_type="schedules",
            create_table_if_not_found=False,
        )

    def test_routes_schedule_runs(self, mysql_db):
        mock_t = _mock_table()
        mysql_db._get_or_create_table = Mock(return_value=mock_t)
        assert mysql_db._get_table("schedule_runs") is mock_t

    def test_unknown_type_raises(self, mysql_db):
        with pytest.raises(ValueError, match="Unknown table type"):
            mysql_db._get_table("nonexistent")


# ---------------------------------------------------------------------------
# get_schedule
# ---------------------------------------------------------------------------

class TestGetSchedule:
    def test_returns_row_dict(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)

        row = Mock()
        row._mapping = {"id": "s1", "name": "daily"}
        mock_session.execute.return_value.fetchone.return_value = row

        result = mysql_db.get_schedule("s1")
        assert result == {"id": "s1", "name": "daily"}

    def test_returns_none_when_missing(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        mock_session.execute.return_value.fetchone.return_value = None
        assert mysql_db.get_schedule("x") is None

    def test_returns_none_when_no_table(self, mysql_db):
        mysql_db._get_table = Mock(return_value=None)
        assert mysql_db.get_schedule("x") is None


# ---------------------------------------------------------------------------
# get_schedule_by_name
# ---------------------------------------------------------------------------

class TestGetScheduleByName:
    def test_returns_row(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        row = Mock()
        row._mapping = {"id": "s1", "name": "nightly"}
        mock_session.execute.return_value.fetchone.return_value = row
        assert mysql_db.get_schedule_by_name("nightly") == {"id": "s1", "name": "nightly"}

    def test_returns_none_when_missing(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        mock_session.execute.return_value.fetchone.return_value = None
        assert mysql_db.get_schedule_by_name("nope") is None


# ---------------------------------------------------------------------------
# get_schedules (pagination, enabled filter)
# ---------------------------------------------------------------------------

class TestGetSchedules:
    def test_returns_list_and_count(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)

        row1, row2 = Mock(), Mock()
        row1._mapping = {"id": "a"}
        row2._mapping = {"id": "b"}

        mock_session.execute.side_effect = [
            Mock(scalar=Mock(return_value=2)),
            Mock(fetchall=Mock(return_value=[row1, row2])),
        ]

        with _patch_sql():
            results, total = mysql_db.get_schedules(enabled=True, limit=10, page=1)

        assert total == 2
        assert len(results) == 2
        assert results[0]["id"] == "a"

    def test_empty_when_no_table(self, mysql_db):
        mysql_db._get_table = Mock(return_value=None)
        results, total = mysql_db.get_schedules()
        assert results == []
        assert total == 0


# ---------------------------------------------------------------------------
# create_schedule
# ---------------------------------------------------------------------------

class TestCreateSchedule:
    def test_creates_and_returns(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        data = {"id": "s1", "name": "test", "cron_expr": "0 * * * *"}
        assert mysql_db.create_schedule(data) is data

    def test_raises_when_no_table(self, mysql_db):
        mysql_db._get_table = Mock(return_value=None)
        with pytest.raises(RuntimeError, match="Failed to get or create schedules table"):
            mysql_db.create_schedule({"id": "s1"})


# ---------------------------------------------------------------------------
# update_schedule
# ---------------------------------------------------------------------------

class TestUpdateSchedule:
    def test_updates_and_returns_refreshed(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        mysql_db.get_schedule = Mock(return_value={"id": "s1", "enabled": False})
        result = mysql_db.update_schedule("s1", enabled=False)
        assert result == {"id": "s1", "enabled": False}

    def test_returns_none_when_no_table(self, mysql_db):
        mysql_db._get_table = Mock(return_value=None)
        assert mysql_db.update_schedule("x", enabled=True) is None


# ---------------------------------------------------------------------------
# delete_schedule (also deletes runs)
# ---------------------------------------------------------------------------

class TestDeleteSchedule:
    def test_deletes_runs_then_schedule(self, mysql_db, mock_session):
        sched_table = _mock_table()
        runs_table = _mock_table()

        def side_effect(table_type, **kw):
            return {"schedules": sched_table, "schedule_runs": runs_table}.get(table_type)

        mysql_db._get_table = Mock(side_effect=side_effect)
        mysql_db.Session = Mock(return_value=mock_session)
        mock_session.execute.return_value = Mock(rowcount=1)

        assert mysql_db.delete_schedule("s1") is True
        assert mock_session.execute.call_count == 2

    def test_returns_false_when_no_table(self, mysql_db):
        mysql_db._get_table = Mock(return_value=None)
        assert mysql_db.delete_schedule("x") is False

    def test_delete_without_runs_table(self, mysql_db, mock_session):
        sched_table = _mock_table()

        def side_effect(table_type, **kw):
            if table_type == "schedules":
                return sched_table
            return None

        mysql_db._get_table = Mock(side_effect=side_effect)
        mysql_db.Session = Mock(return_value=mock_session)
        mock_session.execute.return_value = Mock(rowcount=1)

        assert mysql_db.delete_schedule("s1") is True
        assert mock_session.execute.call_count == 1


# ---------------------------------------------------------------------------
# claim_due_schedule (SELECT FOR UPDATE + skip_locked)
# ---------------------------------------------------------------------------

class TestClaimDueSchedule:
    def test_claims_and_returns_updated_row(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)

        row = Mock()
        row._mapping = {"id": "s1", "locked_by": None, "locked_at": None}

        mock_session.execute.side_effect = [
            Mock(fetchone=Mock(return_value=row)),  # SELECT FOR UPDATE
            Mock(),  # UPDATE claim
        ]

        with _patch_sql():
            result = mysql_db.claim_due_schedule("worker-1", lock_grace_seconds=300)

        assert result is not None
        assert result["id"] == "s1"
        assert result["locked_by"] == "worker-1"
        assert isinstance(result["locked_at"], int)

    def test_returns_none_when_nothing_due(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)

        mock_session.execute.return_value.fetchone.return_value = None

        with _patch_sql():
            assert mysql_db.claim_due_schedule("w") is None

    def test_returns_none_when_no_table(self, mysql_db):
        mysql_db._get_table = Mock(return_value=None)
        assert mysql_db.claim_due_schedule("w") is None


# ---------------------------------------------------------------------------
# release_schedule
# ---------------------------------------------------------------------------

class TestReleaseSchedule:
    def test_clears_lock(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        mock_session.execute.return_value = Mock(rowcount=1)
        assert mysql_db.release_schedule("s1") is True

    def test_with_next_run_at(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        mock_session.execute.return_value = Mock(rowcount=1)
        assert mysql_db.release_schedule("s1", next_run_at=9999) is True

    def test_returns_false_when_not_found(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        mock_session.execute.return_value = Mock(rowcount=0)
        assert mysql_db.release_schedule("missing") is False

    def test_returns_false_when_no_table(self, mysql_db):
        mysql_db._get_table = Mock(return_value=None)
        assert mysql_db.release_schedule("x") is False


# ---------------------------------------------------------------------------
# Schedule runs
# ---------------------------------------------------------------------------

class TestCreateScheduleRun:
    def test_creates_and_returns(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        data = {"id": "r1", "schedule_id": "s1", "status": "pending"}
        assert mysql_db.create_schedule_run(data) is data

    def test_raises_when_no_table(self, mysql_db):
        mysql_db._get_table = Mock(return_value=None)
        with pytest.raises(RuntimeError, match="Failed to get or create schedule_runs table"):
            mysql_db.create_schedule_run({"id": "r1"})


class TestGetScheduleRuns:
    def test_returns_paginated_runs(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)

        row = Mock()
        row._mapping = {"id": "r1", "schedule_id": "s1", "status": "success"}

        mock_session.execute.side_effect = [
            Mock(scalar=Mock(return_value=1)),
            Mock(fetchall=Mock(return_value=[row])),
        ]

        with _patch_sql():
            runs, total = mysql_db.get_schedule_runs("s1", limit=10, page=1)

        assert total == 1
        assert len(runs) == 1
        assert runs[0]["id"] == "r1"

    def test_empty_when_no_table(self, mysql_db):
        mysql_db._get_table = Mock(return_value=None)
        runs, total = mysql_db.get_schedule_runs("s1")
        assert runs == []
        assert total == 0


class TestUpdateScheduleRun:
    def test_updates_and_returns(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        mysql_db.get_schedule_run = Mock(return_value={"id": "r1", "status": "success"})
        assert mysql_db.update_schedule_run("r1", status="success") == {"id": "r1", "status": "success"}

    def test_returns_none_when_no_table(self, mysql_db):
        mysql_db._get_table = Mock(return_value=None)
        assert mysql_db.update_schedule_run("r1", status="fail") is None


class TestGetScheduleRun:
    def test_returns_row(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        row = Mock()
        row._mapping = {"id": "r1", "status": "running"}
        mock_session.execute.return_value.fetchone.return_value = row
        assert mysql_db.get_schedule_run("r1") == {"id": "r1", "status": "running"}

    def test_returns_none_when_missing(self, mysql_db, mock_session):
        mysql_db._get_table = Mock(return_value=_mock_table())
        mysql_db.Session = Mock(return_value=mock_session)
        mock_session.execute.return_value.fetchone.return_value = None
        assert mysql_db.get_schedule_run("nope") is None
