"""A failed memory read is not an empty one.

get_all_memory_topics and get_user_memory_stats return what the database holds: a list of
topics, and a (stats, total) pair. Two async backends answered a failed read with the
empty value - [] and ([], 0) - which is what a user with no memories gets. Their own sync
twins re-raise from the identical handler, as do 13 and 14 of the 18 backends respectively.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.mysql.async_mysql import AsyncMySQLDb
from agno.db.postgres.async_postgres import AsyncPostgresDb


def _engine() -> Mock:
    engine = Mock(spec=AsyncEngine)
    engine.url = "fake:///url"
    return engine


def _session_that_cannot_connect() -> Mock:
    """A session factory that fails the way a dropped database connection does."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(side_effect=OSError("server closed the connection"))
    session.__aexit__ = AsyncMock(return_value=None)
    return Mock(return_value=session)


@pytest.fixture
def async_mysql_db():
    return AsyncMySQLDb(db_engine=_engine(), db_schema="test_schema", session_table="test_sessions")


@pytest.fixture
def async_postgres_db():
    return AsyncPostgresDb(db_engine=_engine(), db_schema="test_schema", session_table="test_sessions")


# -- AsyncMySQLDb.get_all_memory_topics; MySQLDb.get_all_memory_topics re-raises --


@pytest.mark.asyncio
async def test_mysql_memory_topics_raise_when_the_database_fails(async_mysql_db):
    async_mysql_db._get_table = AsyncMock(return_value=Mock())
    async_mysql_db.async_session_factory = _session_that_cannot_connect()

    with pytest.raises(OSError, match="server closed"):
        await async_mysql_db.get_all_memory_topics()


@pytest.mark.asyncio
async def test_mysql_memory_topics_are_still_empty_without_a_table(async_mysql_db):
    """No memories table is a real "nothing stored", and stays that way."""
    async_mysql_db._get_table = AsyncMock(return_value=None)

    assert await async_mysql_db.get_all_memory_topics() == []


# -- AsyncPostgresDb.get_user_memory_stats; PostgresDb.get_user_memory_stats re-raises --


@pytest.mark.asyncio
async def test_postgres_memory_stats_raise_when_the_database_fails(async_postgres_db):
    """([], 0) reads as "this user has no memories". A dead connection must not say that."""
    async_postgres_db._get_table = AsyncMock(return_value=Mock())
    async_postgres_db.async_session_factory = _session_that_cannot_connect()

    with pytest.raises(OSError, match="server closed"):
        await async_postgres_db.get_user_memory_stats()


@pytest.mark.asyncio
async def test_postgres_memory_stats_are_still_empty_without_a_table(async_postgres_db):
    async_postgres_db._get_table = AsyncMock(return_value=None)

    assert await async_postgres_db.get_user_memory_stats() == ([], 0)
