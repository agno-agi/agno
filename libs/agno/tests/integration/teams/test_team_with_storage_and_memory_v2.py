import os
import tempfile
import uuid

import pytest

from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai.chat import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.team.team import Team


@pytest.fixture
def temp_storage_db_file():
    """Create a temporary SQLite database file for team storage testing."""
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
def team_storage(temp_storage_db_file):
    """Create a SQLite storage for team sessions."""
    # Use a unique table name for each test run
    table_name = f"team_sessions_{uuid.uuid4().hex[:8]}"
    storage = SqliteStorage(table_name=table_name, db_file=temp_storage_db_file, mode="team")
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
    return Memory(db=memory_db)




@pytest.fixture
def route_team(team_storage, memory):
    """Create a route team with storage and memory for testing."""
    return Team(
        name="Route Team",
        mode="collaborate",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        storage=team_storage,
        memory=memory,
        enable_user_memories=True,
        num_of_interactions_from_history=10,
        num_history_runs=10,
    )


@pytest.mark.asyncio
async def test_run_history_persistence(route_team, team_storage, memory):
    """Test that all runs within a session are persisted in storage."""
    user_id = "test_persistence_user@example.com"
    session_id = "test_persistence_session"
    num_turns = 5

    # Clear memory for this specific test case
    memory.clear()

    # Perform multiple turns
    conversation_messages = [
        "What's the weather like today?",
        "What about tomorrow?",
        "Any recommendations for indoor activities?",
        "Search for nearby museums.",
        "Which one has the best reviews?",
    ]

    assert len(conversation_messages) == num_turns

    for i, msg in enumerate(conversation_messages):
        print(f"Turn {i+1}: {msg}")
        await route_team.arun(msg, user_id=user_id, session_id=session_id)
        # Optional: Check memory state in RAM after each turn if needed for debugging
        # print(f"Runs in memory after turn {i+1}: {len(memory.runs.get(session_id, []))}")

    # Verify the stored session data after all turns
    team_session = team_storage.read(session_id=session_id)


    stored_memory_data = team_session.memory
    assert stored_memory_data is not None, "Memory data not found in stored session."
    print(f"Stored memory data: {stored_memory_data}")
    stored_runs = stored_memory_data["runs"]
    assert isinstance(stored_runs, list), "Stored runs data is not a list."


    first_user_message_content = stored_runs[0]['messages'][1]['content']
    assert first_user_message_content == conversation_messages[0]