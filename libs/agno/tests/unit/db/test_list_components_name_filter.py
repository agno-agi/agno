"""Tests for the exact-match name filter on BaseDb.list_components."""

from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import BigInteger, Column, DateTime, MetaData, String, Table
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.base import ComponentType
from agno.db.postgres import PostgresDb
from agno.db.postgres.async_postgres import AsyncPostgresDb
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb


@pytest.fixture
def sqlite_db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "components.db"))


def _seed(db):
    db.upsert_component(component_id="a1", component_type=ComponentType.AGENT, name="alpha")
    db.upsert_component(component_id="a2", component_type=ComponentType.AGENT, name="beta")
    db.upsert_component(component_id="t1", component_type=ComponentType.TEAM, name="alpha")


class TestSqliteNameFilter:
    def test_name_filter_returns_matches_and_filtered_total(self, sqlite_db):
        _seed(sqlite_db)

        rows, total = sqlite_db.list_components(name="alpha")

        assert {r["component_id"] for r in rows} == {"a1", "t1"}
        assert total == 2

    def test_name_filter_combines_with_component_type(self, sqlite_db):
        _seed(sqlite_db)

        rows, total = sqlite_db.list_components(component_type=ComponentType.AGENT, name="alpha")

        assert [r["component_id"] for r in rows] == ["a1"]
        assert total == 1

    def test_name_filter_is_exact_match(self, sqlite_db):
        _seed(sqlite_db)

        rows, total = sqlite_db.list_components(name="alph")

        assert rows == []
        assert total == 0

    def test_no_name_filter_preserves_existing_behavior(self, sqlite_db):
        _seed(sqlite_db)

        rows, total = sqlite_db.list_components()

        assert total == 3
        assert len(rows) == 3


class TestPostgresNameFilter:
    def test_name_filter_lands_in_count_and_select(self):
        """The name clause must appear in both the count and select statements
        so the returned total counts the filtered set."""
        engine = Mock(spec=Engine)
        engine.url = "fake:///url"
        db = PostgresDb(db_engine=engine, db_schema="test_schema")

        table = Table(
            "agno_components",
            MetaData(),
            Column("component_id", String),
            Column("component_type", String),
            Column("name", String),
            Column("deleted_at", DateTime),
            Column("created_at", BigInteger),
        )

        executed = []

        def fake_execute(stmt):
            executed.append(stmt)
            result = MagicMock()
            result.scalar.return_value = 0
            result.mappings.return_value.all.return_value = []
            return result

        sess = MagicMock()
        sess.__enter__.return_value = sess
        sess.execute.side_effect = fake_execute

        with patch.object(db, "_get_table", return_value=table), patch.object(db, "Session", return_value=sess):
            rows, total = db.list_components(name="alpha")

        assert rows == []
        assert total == 0
        assert len(executed) == 2
        count_sql, select_sql = str(executed[0]), str(executed[1])
        assert "agno_components.name =" in count_sql
        assert "agno_components.name =" in select_sql


class TestAsyncAdaptersAcceptNameParam:
    """The async stubs must accept name= and still raise NotImplementedError.

    Callers detect adapters without the parameter via TypeError and async
    adapters via NotImplementedError, so the two must stay distinguishable.
    """

    def test_async_sqlite_raises_not_implemented_not_type_error(self, tmp_path):
        db = AsyncSqliteDb(db_file=str(tmp_path / "async.db"))

        with pytest.raises(NotImplementedError):
            db.list_components(name="alpha")

    def test_async_postgres_raises_not_implemented_not_type_error(self):
        engine = Mock(spec=AsyncEngine)
        engine.url = "fake:///url"
        db = AsyncPostgresDb(db_engine=engine)

        with pytest.raises(NotImplementedError):
            db.list_components(name="alpha")
