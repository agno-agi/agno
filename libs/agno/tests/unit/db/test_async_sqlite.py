from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from agno.db.sqlite.async_sqlite import AsyncSqliteDb


@pytest.mark.asyncio
async def test_failed_table_creation_can_be_retried(tmp_path):
    """A failed CREATE TABLE must not leave the table registered on MetaData."""
    db = AsyncSqliteDb(
        db_engine=create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/retry.db"),
        session_table="test_sessions",
    )
    db.create_schema = False
    attempts = {"create": 0}

    async def run_sync(fn, *args, **kwargs):
        attempts["create"] += 1
        if attempts["create"] == 1:
            raise OSError("temporary DDL outage")

    conn = Mock(run_sync=run_sync)
    begin_ctx = Mock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None))

    session = Mock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=Mock(scalar=Mock(return_value=1)))
    begin_ctx_sess = Mock(__aenter__=AsyncMock(return_value=session), __aexit__=AsyncMock(return_value=None))
    session.begin = Mock(return_value=begin_ctx_sess)
    db.async_session_factory = Mock(return_value=session)

    with (
        # AsyncEngine.begin is read-only on a real engine, so patch the class.
        patch.object(AsyncEngine, "begin", return_value=begin_ctx),
        patch.object(AsyncSqliteDb, "table_exists", AsyncMock(return_value=False)),
        patch("agno.db.sqlite.async_sqlite.ais_table_available", AsyncMock(return_value=False)),
        patch.object(AsyncSqliteDb, "upsert_schema_version", AsyncMock()),
    ):
        with pytest.raises(OSError, match="temporary DDL outage"):
            await db._get_or_create_table("retry_table", "knowledge", True)

        table = await db._get_or_create_table("retry_table", "knowledge", True)

    assert table.name == "retry_table"
    assert attempts["create"] == 2
    await db.db_engine.dispose()
