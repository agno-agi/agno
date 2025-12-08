import pytest

from agno.agent.agent import Agent
from agno.db.base import UserMemory


def test_get_user_memories(shared_db):
    shared_db.clear_memories()
    shared_db.upsert_user_memory(memory=UserMemory(user_id="test_user", memory="test_memory"))

    agent = Agent(db=shared_db)

    memories = agent.get_user_memories(user_id="test_user")
    assert len(memories) == 1
    assert memories[0].user_id == "test_user"
    assert memories[0].memory == "test_memory"


@pytest.mark.asyncio
async def test_get_user_memories_async(shared_db):
    shared_db.clear_memories()
    shared_db.upsert_user_memory(memory=UserMemory(user_id="test_user", memory="test_memory"))

    agent = Agent(db=shared_db)

    memories = await agent.aget_user_memories(user_id="test_user")
    assert len(memories) == 1
    assert memories[0].user_id == "test_user"
    assert memories[0].memory == "test_memory"
