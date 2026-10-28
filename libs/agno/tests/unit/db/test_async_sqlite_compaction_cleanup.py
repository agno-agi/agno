"""Async session deletion must remove archives written by the sync adapter."""

import pytest
import pytest_asyncio
from sqlalchemy import inspect

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.session import AgentSession


@pytest_asyncio.fixture
async def databases(tmp_path):
    db_file = str(tmp_path / "compactions.db")
    sync_db = SqliteDb(db_file=db_file)
    async_db = AsyncSqliteDb(db_file=db_file)
    try:
        yield sync_db, async_db
    finally:
        await async_db.close()
        sync_db.close()


def _add_archive(db, session_id, user_id, create_session=True):
    if create_session:
        db.upsert_session(AgentSession(session_id=session_id, user_id=user_id))
    db.upsert_compaction(
        {
            "compaction_id": f"fold-{session_id}",
            "session_id": session_id,
            "user_id": user_id,
            "summary": "Old conversation",
            "archived_messages": f"Private transcript for {session_id}",
            "created_at": 1,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [None, "owner", "someone-else"])
async def test_delete_session_removes_only_authorized_archive(databases, user_id):
    sync_db, async_db = databases
    _add_archive(sync_db, "remove", "owner")
    _add_archive(sync_db, "keep", "owner")

    deleted = await async_db.delete_session("remove", user_id=user_id)

    expected_deleted = user_id != "someone-else"
    assert deleted is expected_deleted
    assert (sync_db.get_session("remove") is None) is expected_deleted
    assert (sync_db.get_compactions_for_session("remove") == []) is expected_deleted
    assert sync_db.get_session("keep") is not None
    assert sync_db.get_compaction("fold-keep")["archived_messages"] == "Private transcript for keep"


@pytest.mark.asyncio
async def test_delete_missing_session_does_not_remove_orphan_archive(databases):
    sync_db, async_db = databases
    _add_archive(sync_db, "keep", "owner")
    _add_archive(sync_db, "orphan", "owner", create_session=False)

    assert await async_db.delete_session("orphan", user_id="owner") is False
    assert sync_db.get_compaction("fold-orphan") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "deleted_ids"),
    [(None, {"remove", "foreign", "orphan"}), ("owner", {"remove"}), ("other-owner", {"foreign"})],
)
async def test_delete_sessions_scopes_archives_to_authorized_sessions(databases, user_id, deleted_ids):
    sync_db, async_db = databases
    _add_archive(sync_db, "remove", "owner")
    _add_archive(sync_db, "foreign", "other-owner")
    _add_archive(sync_db, "keep", "owner")
    _add_archive(sync_db, "orphan", "owner", create_session=False)

    assert await async_db.delete_sessions(["remove", "foreign", "orphan", "missing"], user_id=user_id) is None

    for session_id in ("remove", "foreign", "keep", "orphan"):
        assert (sync_db.get_compaction(f"fold-{session_id}") is None) is (session_id in deleted_ids)
        if session_id != "orphan":
            assert (sync_db.get_session(session_id) is None) is (session_id in deleted_ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
async def test_delete_without_compactions_does_not_create_archive_table(databases, bulk):
    sync_db, async_db = databases
    sync_db.upsert_session(AgentSession(session_id="remove", user_id="owner"))
    existing_tables = set(inspect(sync_db.db_engine).get_table_names())
    assert sync_db.compactions_table_name not in existing_tables

    if bulk:
        assert await async_db.delete_sessions(["remove"], user_id="owner") is None
    else:
        assert await async_db.delete_session("remove", user_id="owner") is True

    assert sync_db.get_session("remove") is None
    assert set(inspect(sync_db.db_engine).get_table_names()) == existing_tables
