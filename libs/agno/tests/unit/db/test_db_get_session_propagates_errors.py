"""``get_session`` on the SQL adapters must re-raise a read failure.

The agent, team and workflow read helpers let read errors propagate (see
``test_read_session_propagates_errors.py``), because ``None`` is taken to mean
"row does not exist" and the caller then creates a fresh session that overwrites
the real row on the next write. That only works when the adapter underneath
re-raises too. The sync Postgres and SQLite adapters do; the async Postgres and
both MySQL adapters returned ``None`` from the same except block.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("pymysql")
pytest.importorskip("asyncmy")

from agno.db.mysql.async_mysql import AsyncMySQLDb  # noqa: E402
from agno.db.mysql.mysql import MySQLDb  # noqa: E402
from agno.db.postgres.async_postgres import AsyncPostgresDb  # noqa: E402
from agno.db.postgres.postgres import PostgresDb  # noqa: E402


class _SimulatedFailover(Exception):
    """Distinctive error to prove the exception surfaced unchanged."""


def _bare(cls):
    """An adapter without a database: only what get_session touches before the table lookup."""
    db = object.__new__(cls)
    db.db_schema = "ai"
    db.session_table_name = "agno_sessions"
    return db


@pytest.mark.parametrize("cls", [PostgresDb, MySQLDb])
def test_sync_get_session_reraises_a_read_failure(cls):
    db = _bare(cls)
    with patch.object(db, "_get_table", side_effect=_SimulatedFailover("simulated failover")):
        with pytest.raises(_SimulatedFailover, match="simulated failover"):
            db.get_session(session_id="s1")


@pytest.mark.parametrize("cls", [PostgresDb, MySQLDb])
def test_sync_get_session_returns_none_when_there_is_nothing_to_read(cls):
    db = _bare(cls)
    with patch.object(db, "_get_table", return_value=None):
        assert db.get_session(session_id="s1") is None


@pytest.mark.parametrize("cls", [AsyncPostgresDb, AsyncMySQLDb])
async def test_async_get_session_reraises_a_read_failure(cls):
    db = _bare(cls)
    with patch.object(db, "_get_table", AsyncMock(side_effect=_SimulatedFailover("simulated failover"))):
        with pytest.raises(_SimulatedFailover, match="simulated failover"):
            await db.get_session(session_id="s1")


@pytest.mark.parametrize("cls", [AsyncPostgresDb, AsyncMySQLDb])
async def test_async_get_session_returns_none_when_there_is_nothing_to_read(cls):
    db = _bare(cls)
    with patch.object(db, "_get_table", AsyncMock(return_value=None)):
        assert await db.get_session(session_id="s1") is None
