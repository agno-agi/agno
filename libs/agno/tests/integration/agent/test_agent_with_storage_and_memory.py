import os
import tempfile
import uuid

import pytest

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.anthropic.claude import Claude
from agno.models.openai.chat import OpenAIChat
from agno.storage.sqlite import SqliteStorage


@pytest.fixture
def temp_storage_db_file():
    """Create a temporary SQLite database file for agent storage testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up the temporary file after the test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def temp_memory_db_file():
    """Create a temporary SQLite database file for memory testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up the temporary file after the test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def agent_storage(temp_storage_db_file):
    """Create a SQLite storage for agent sessions."""
    # Use a unique table name for each test run
    table_name = f"agent_sessions_{uuid.uuid4().hex[:8]}"
    storage = SqliteStorage(table_name=table_name, db_file=temp_storage_db_file)
    storage.create()
    return storage


@pytest.fixture
def memory_db(temp_memory_db_file):
    """Create a SQLite memory database for testing."""
    db = SqliteMemoryDb(db_file=temp_memory_db_file)
    db.create()
    return db


@pytest.fixture
def memory(memory_db):
    """Create a Memory instance for testing."""
    return Memory(model=Claude(id="claude-3-5-sonnet-20241022"), db=memory_db)


@pytest.fixture
def chat_agent(agent_storage, memory):
    """Create an agent with storage and memory for testing."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
        memory=memory,
        enable_user_memories=True,
    )


@pytest.mark.asyncio
async def test_multi_user_multi_session_chat(chat_agent, agent_storage, memory):
    """Test multi-user multi-session chat with storage and memory."""
    # Define user and session IDs
    user_1_id = "user_1@example.com"
    user_2_id = "user_2@example.com"
    user_3_id = "user_3@example.com"

    user_1_session_1_id = "user_1_session_1"
    user_1_session_2_id = "user_1_session_2"
    user_2_session_1_id = "user_2_session_1"
    user_3_session_1_id = "user_3_session_1"

    # Clear memory for this test
    memory.clear()

    # Chat with user 1 - Session 1
    await chat_agent.arun(
        "My name is Mark Gonzales and I like anime and video games.", user_id=user_1_id, session_id=user_1_session_1_id
    )
    await chat_agent.arun(
        "I also enjoy reading manga and playing video games.", user_id=user_1_id, session_id=user_1_session_1_id
    )

    # Chat with user 1 - Session 2
    await chat_agent.arun("I'm going to the movies tonight.", user_id=user_1_id, session_id=user_1_session_2_id)

    # Chat with user 2
    await chat_agent.arun("Hi my name is John Doe.", user_id=user_2_id, session_id=user_2_session_1_id)
    await chat_agent.arun("I'm planning to hike this weekend.", user_id=user_2_id, session_id=user_2_session_1_id)

    # Chat with user 3
    await chat_agent.arun("Hi my name is Jane Smith.", user_id=user_3_id, session_id=user_3_session_1_id)
    await chat_agent.arun("I'm going to the gym tomorrow.", user_id=user_3_id, session_id=user_3_session_1_id)

    # Continue the conversation with user 1
    await chat_agent.arun("What do you suggest I do this weekend?", user_id=user_1_id, session_id=user_1_session_1_id)

    # Verify storage DB has the right sessions
    all_session_ids = agent_storage.get_all_session_ids()
    assert len(all_session_ids) == 4  # 4 sessions total

    # Check that each user has the expected sessions
    user_1_sessions = agent_storage.get_all_sessions(user_id=user_1_id)
    assert len(user_1_sessions) == 2
    assert user_1_session_1_id in [session.session_id for session in user_1_sessions]
    assert user_1_session_2_id in [session.session_id for session in user_1_sessions]

    user_2_sessions = agent_storage.get_all_sessions(user_id=user_2_id)
    assert len(user_2_sessions) == 1
    assert user_2_session_1_id in [session.session_id for session in user_2_sessions]

    user_3_sessions = agent_storage.get_all_sessions(user_id=user_3_id)
    assert len(user_3_sessions) == 1
    assert user_3_session_1_id in [session.session_id for session in user_3_sessions]

    # Verify memory DB has the right memories
    user_1_memories = memory.get_user_memories(user_id=user_1_id)
    assert len(user_1_memories) >= 1  # At least 1 memory for user 1

    user_2_memories = memory.get_user_memories(user_id=user_2_id)
    assert len(user_2_memories) >= 1  # At least 1 memory for user 2

    user_3_memories = memory.get_user_memories(user_id=user_3_id)
    assert len(user_3_memories) >= 1  # At least 1 memory for user 3

    # Verify memory content for user 1
    user_1_memory_texts = [m.memory for m in user_1_memories]
    assert any("Mark Gonzales" in text for text in user_1_memory_texts)
    assert any("anime" in text for text in user_1_memory_texts)
    assert any("video games" in text for text in user_1_memory_texts)
    assert any("manga" in text for text in user_1_memory_texts)

    # Verify memory content for user 2
    user_2_memory_texts = [m.memory for m in user_2_memories]
    assert any("John Doe" in text for text in user_2_memory_texts)
    assert any("hike" in text for text in user_2_memory_texts) or any("hiking" in text for text in user_2_memory_texts)

    # Verify memory content for user 3
    user_3_memory_texts = [m.memory for m in user_3_memories]
    assert any("Jane Smith" in text for text in user_3_memory_texts)
