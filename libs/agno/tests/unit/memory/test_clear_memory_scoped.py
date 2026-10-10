"""
Regression test for agno#9983:
clear_memory LLM tool must only clear the calling user's memories, not all users'.
"""
import pytest
from agno.db.base import UserMemory
from agno.db.sqlite.sqlite import SqliteDb
from agno.memory.manager import MemoryManager


@pytest.fixture
def tmp_db(tmp_path):
    db_file = str(tmp_path / "test_memories.db")
    db = SqliteDb(db_file=db_file)
    return db


def test_clear_memory_tool_is_user_scoped(tmp_db):
    """clear_memory tool must only delete the calling user's memories."""
    db = tmp_db

    # Seed two users
    db.upsert_user_memory(UserMemory(user_id="alice", memory="alice-fact-1"))
    db.upsert_user_memory(UserMemory(user_id="alice", memory="alice-fact-2"))
    db.upsert_user_memory(UserMemory(user_id="bob", memory="bob-fact-1"))

    assert len(db.get_user_memories(user_id="alice")) == 2
    assert len(db.get_user_memories(user_id="bob")) == 1

    # Build the tool functions for alice's session
    manager = MemoryManager(db=db)
    tools = manager._get_db_tools(
        user_id="alice",
        db=db,
        input_string="",
        enable_clear_memory=True,
    )
    clear_fn = next(f for f in tools if f.__name__ == "clear_memory")

    # Invoke the tool as alice
    result = clear_fn()
    assert result == "Memory cleared successfully"

    # Alice's memories are gone
    assert len(db.get_user_memories(user_id="alice")) == 0

    # Bob's memories are untouched
    bob_memories = db.get_user_memories(user_id="bob")
    assert len(bob_memories) == 1, (
        f"clear_memory wiped bob's memories too — unscoped db.clear_memories() was called. "
        f"Bob has {len(bob_memories)} memories (expected 1)."
    )


@pytest.mark.asyncio
async def test_async_clear_memory_tool_is_user_scoped(tmp_db):
    """Async clear_memory tool must only delete the calling user's memories."""
    db = tmp_db

    db.upsert_user_memory(UserMemory(user_id="alice", memory="alice-async-1"))
    db.upsert_user_memory(UserMemory(user_id="bob", memory="bob-async-1"))

    manager = MemoryManager(db=db)
    tools = await manager._aget_db_tools(
        user_id="alice",
        db=db,
        input_string="",
        enable_clear_memory=True,
    )
    clear_fn = next(f for f in tools if f.__name__ == "clear_memory")

    result = await clear_fn()
    assert result == "Memory cleared successfully"

    assert len(db.get_user_memories(user_id="alice")) == 0
    bob_memories = db.get_user_memories(user_id="bob")
    assert len(bob_memories) == 1, (
        f"Async clear_memory wiped bob's memories — unscoped db.clear_memories() was called. "
        f"Bob has {len(bob_memories)} memories (expected 1)."
    )
