import os
import tempfile
from datetime import datetime

import pytest

from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager, UserMemory
from agno.memory.strategies.types import MemoryOptimizationStrategyType
from agno.models.message import Message
from agno.models.openai import OpenAIChat


@pytest.fixture
def temp_db_file():
    """Create a temporary SQLite database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up the temporary file after the test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def memory_db(temp_db_file):
    """Create a SQLite memory database for testing."""
    db = SqliteDb(db_file=temp_db_file)
    return db


@pytest.fixture
def model():
    """Create a Gemini model for testing."""
    return OpenAIChat(id="gpt-4o-mini")


@pytest.fixture
def memory_with_db(model, memory_db):
    """Create a Memory instance with database connections."""
    return MemoryManager(model=model, db=memory_db)


def test_add_user_memory_with_db(memory_with_db: MemoryManager):
    """Test adding a user memory with database persistence."""
    # Create a user memory
    user_memory = UserMemory(
        user_id="test_user",
        memory="The user's name is John Doe",
        topics=["name", "user"],
        updated_at=datetime.now(),
    )

    # Add the memory
    memory_id = memory_with_db.add_user_memory(memory=user_memory, user_id="test_user")

    # Verify the memory was added to the in-memory store
    assert memory_id is not None
    assert memory_with_db.get_user_memory(user_id="test_user", memory_id=memory_id) is not None
    assert (
        memory_with_db.get_user_memory(user_id="test_user", memory_id=memory_id).memory == "The user's name is John Doe"
    )

    # Create a new Memory instance with the same database
    new_memory = MemoryManager(model=memory_with_db.model, db=memory_with_db.db)

    # Verify the memory was loaded from the database
    assert new_memory.get_user_memory(user_id="test_user", memory_id=memory_id) is not None
    assert new_memory.get_user_memory(user_id="test_user", memory_id=memory_id).memory == "The user's name is John Doe"


def test_create_user_memory_with_db(memory_with_db):
    """Test creating user memories with database persistence."""
    # Create messages to generate memories from
    message = "My name is John Doe and I like to play basketball"
    # Create memories from the messages
    result = memory_with_db.create_user_memories(message, user_id="test_user")

    # Verify memories were created
    assert len(result) > 0

    # Get all memories for the user
    memories = memory_with_db.get_user_memories("test_user")

    # Verify memories were added to the in-memory store
    assert len(memories) > 0

    assert memories[0].input == message
    assert "john doe" in memories[0].memory.lower()


def test_create_user_memories_with_db(memory_with_db):
    """Test creating user memories with database persistence."""
    # Create messages to generate memories from
    messages = [
        Message(role="user", content="My name is John Doe"),
        Message(role="user", content="I like to play basketball"),
    ]

    # Create memories from the messages
    result = memory_with_db.create_user_memories(messages=messages, user_id="test_user")

    # Verify memories were created
    assert len(result) > 0

    # Get all memories for the user
    memories = memory_with_db.get_user_memories(user_id="test_user")

    # Verify memories were added to the in-memory store
    assert len(memories) > 0

    # Create a new Memory instance with the same database
    new_memory = MemoryManager(model=memory_with_db.model, db=memory_with_db.db)

    # Verify memories were loaded from the database
    new_memories = new_memory.get_user_memories(user_id="test_user")
    assert len(new_memories) > 0


@pytest.mark.asyncio
async def test_acreate_user_memory_with_db(memory_with_db):
    """Test async creation of a user memory with database persistence."""
    # Create a message to generate a memory from
    message = "My name is John Doe and I like to play basketball"

    # Create memory from the message
    result = await memory_with_db.acreate_user_memories(message, user_id="test_user")

    # Verify memory was created
    assert len(result) > 0

    # Get all memories for the user
    memories = memory_with_db.get_user_memories(user_id="test_user")

    # Verify memory was added to the in-memory store
    assert len(memories) > 0

    # Create a new Memory instance with the same database
    new_memory = MemoryManager(model=memory_with_db.model, db=memory_with_db.db)

    # Verify memory was loaded from the database
    new_memories = new_memory.get_user_memories(user_id="test_user")
    assert len(new_memories) > 0


@pytest.mark.asyncio
async def test_acreate_user_memories_with_db(memory_with_db):
    """Test async creation of multiple user memories with database persistence."""
    # Create messages to generate memories from
    messages = [
        Message(role="user", content="My name is John Doe"),
        Message(role="user", content="I like to play basketball"),
        Message(role="user", content="My favorite color is blue"),
    ]

    # Create memories from the messages
    result = await memory_with_db.acreate_user_memories(messages=messages, user_id="test_user")

    # Verify memories were created
    assert len(result) > 0

    # Get all memories for the user
    memories = memory_with_db.get_user_memories("test_user")

    # Verify memories were added to the in-memory store
    assert len(memories) > 0

    # Create a new Memory instance with the same database
    new_memory = MemoryManager(model=memory_with_db.model, db=memory_with_db.db)

    # Verify memories were loaded from the database
    new_memories = new_memory.get_user_memories(user_id="test_user")
    assert len(new_memories) > 0


def test_search_user_memories_semantic(memory_with_db):
    """Test semantic search of user memories."""
    # Add multiple memories with different content
    memory1 = UserMemory(memory="The user's name is John Doe", topics=["name", "user"], updated_at=datetime.now())

    memory2 = UserMemory(
        memory="The user likes to play basketball", topics=["sports", "hobbies"], updated_at=datetime.now()
    )

    memory3 = UserMemory(
        memory="The user's favorite color is blue", topics=["preferences", "colors"], updated_at=datetime.now()
    )

    # Add the memories
    memory_with_db.add_user_memory(memory=memory1, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory2, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory3, user_id="test_user")

    # Search for memories related to sports
    results = memory_with_db.search_user_memories(
        query="sports and hobbies", retrieval_method="semantic", user_id="test_user"
    )

    # Verify the search returned relevant memories
    assert len(results) > 0
    assert any("basketball" in memory.memory for memory in results)


def test_memory_persistence_across_instances(model, memory_db):
    """Test that memories persist across different Memory instances."""
    # Create the first Memory instance
    memory1 = MemoryManager(model=model, db=memory_db)

    # Add a user memory
    user_memory = UserMemory(memory="The user's name is John Doe", topics=["name", "user"], updated_at=datetime.now())

    memory_id = memory1.add_user_memory(memory=user_memory, user_id="test_user")

    # Create a second Memory instance with the same database
    memory2 = MemoryManager(model=model, db=memory_db)

    # Verify the memory is accessible from the second instance
    assert memory2.get_user_memory(user_id="test_user", memory_id=memory_id) is not None
    assert memory2.get_user_memory(user_id="test_user", memory_id=memory_id).memory == "The user's name is John Doe"


def test_memory_operations_with_db(memory_with_db):
    """Test various memory operations with database persistence."""
    # Add a user memory
    user_memory = UserMemory(memory="The user's name is John Doe", topics=["name", "user"], updated_at=datetime.now())

    memory_id = memory_with_db.add_user_memory(memory=user_memory, user_id="test_user")

    # Replace the memory
    updated_memory = UserMemory(
        memory="The user's name is Jane Doe", topics=["name", "user"], updated_at=datetime.now()
    )

    memory_with_db.replace_user_memory(memory_id=memory_id, memory=updated_memory, user_id="test_user")

    # Verify the memory was updated
    assert (
        memory_with_db.get_user_memory(user_id="test_user", memory_id=memory_id).memory == "The user's name is Jane Doe"
    )

    # Delete the memory
    memory_with_db.delete_user_memory(user_id="test_user", memory_id=memory_id)

    # Verify the memory was deleted
    assert memory_with_db.get_user_memory(user_id="test_user", memory_id=memory_id) is None

    # Create a new Memory instance with the same database
    new_memory = MemoryManager(model=memory_with_db.model, db=memory_with_db.db)

    # Verify the memory is still deleted in the new instance
    assert new_memory.get_user_memory(user_id="test_user", memory_id=memory_id) is None


def test_search_user_memories_last_n(memory_with_db):
    """Test retrieving the most recent memories."""
    # Add multiple memories with different timestamps
    memory1 = UserMemory(memory="First memory", topics=["test"], updated_at=datetime(2023, 1, 1))

    memory2 = UserMemory(memory="Second memory", topics=["test"], updated_at=datetime(2023, 1, 2))

    memory3 = UserMemory(memory="Third memory", topics=["test"], updated_at=datetime(2023, 1, 3))

    # Add the memories
    memory_with_db.add_user_memory(memory=memory1, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory2, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory3, user_id="test_user")

    # Get the last 2 memories
    results = memory_with_db.search_user_memories(retrieval_method="last_n", limit=2, user_id="test_user")

    # Verify the search returned the most recent memories
    assert len(results) == 2
    assert results[0].memory == "Second memory"
    assert results[1].memory == "Third memory"


def test_search_user_memories_first_n(memory_with_db):
    """Test retrieving the oldest memories."""
    # Add multiple memories with different timestamps
    memory1 = UserMemory(memory="First memory", topics=["test"], updated_at=datetime(2023, 1, 1))

    memory2 = UserMemory(memory="Second memory", topics=["test"], updated_at=datetime(2023, 1, 2))

    memory3 = UserMemory(memory="Third memory", topics=["test"], updated_at=datetime(2023, 1, 3))

    # Add the memories
    memory_with_db.add_user_memory(memory=memory1, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory2, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory3, user_id="test_user")

    # Get the first 2 memories
    results = memory_with_db.search_user_memories(retrieval_method="first_n", limit=2, user_id="test_user")

    # Verify the search returned the oldest memories
    assert len(results) == 2
    assert results[0].memory == "First memory"
    assert results[1].memory == "Second memory"


def test_update_memory_task_with_db(memory_with_db):
    """Test updating memory with a task using database persistence."""
    # Add multiple memories with different content
    memory1 = UserMemory(memory="The user's name is John Doe", topics=["name", "user"], updated_at=datetime.now())
    memory2 = UserMemory(
        memory="The user likes to play basketball", topics=["sports", "hobbies"], updated_at=datetime.now()
    )
    memory3 = UserMemory(
        memory="The user's favorite color is blue", topics=["preferences", "colors"], updated_at=datetime.now()
    )

    # Add the memories
    memory_with_db.add_user_memory(memory=memory1, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory2, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory3, user_id="test_user")

    # Update memories with a task
    task = "The user's age is 30"
    response = memory_with_db.update_memory_task(task=task, user_id="test_user")

    # Verify the task was processed
    assert response is not None

    # Get all memories for the user
    memories = memory_with_db.get_user_memories("test_user")

    # Verify memories were updated
    assert len(memories) > 0
    assert any("30" in memory.memory for memory in memories)

    response = memory_with_db.update_memory_task(task="Delete any memories of the user's name", user_id="test_user")

    # Verify the task was processed
    assert response is not None

    # Get all memories for the user
    memories = memory_with_db.get_user_memories("test_user")
    assert len(memories) > 0
    assert any("John Doe" not in memory.memory for memory in memories)


@pytest.mark.flaky(max_runs=3)
@pytest.mark.asyncio
async def test_aupdate_memory_task_with_db(memory_with_db):
    """Test async updating memory with a task using database persistence."""
    # Add multiple memories with different content
    memory1 = UserMemory(memory="The user's name is John Doe", topics=["name", "user"], updated_at=datetime.now())
    memory2 = UserMemory(
        memory="The user likes to play basketball", topics=["sports", "hobbies"], updated_at=datetime.now()
    )
    memory3 = UserMemory(
        memory="The user's favorite color is blue", topics=["preferences", "colors"], updated_at=datetime.now()
    )

    # Add the memories
    memory_with_db.add_user_memory(memory=memory1, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory2, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory3, user_id="test_user")

    # Update memories with a task asynchronously
    task = "The user's occupation is software engineer"
    response = await memory_with_db.aupdate_memory_task(task=task, user_id="test_user")

    # Verify the task was processed
    assert response is not None

    # Get all memories for the user
    memories = memory_with_db.get_user_memories("test_user")

    # Verify memories were updated
    assert len(memories) > 0
    assert any(
        "occupation" in memory.memory.lower() and "software engineer" in memory.memory.lower() for memory in memories
    )

    response = await memory_with_db.aupdate_memory_task(
        task="Delete any memories of the user's name", user_id="test_user"
    )

    # Verify the task was processed
    assert response is not None

    # Get all memories for the user
    memories = memory_with_db.get_user_memories("test_user")
    assert len(memories) > 0
    assert any("John Doe" not in memory.memory for memory in memories)


def test_optimize_memories_with_db(memory_with_db):
    """Test optimizing memories with database persistence."""
    # Add multiple memories with different content
    memory1 = UserMemory(
        memory="The user's name is John Doe", topics=["name", "user"], user_id="test_user", updated_at=datetime.now()
    )
    memory2 = UserMemory(
        memory="The user likes to play basketball",
        topics=["sports", "hobbies"],
        user_id="test_user",
        updated_at=datetime.now(),
    )
    memory3 = UserMemory(
        memory="The user's favorite color is blue",
        topics=["preferences", "colors"],
        user_id="test_user",
        updated_at=datetime.now(),
    )

    # Add the memories
    memory_with_db.add_user_memory(memory=memory1, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory2, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory3, user_id="test_user")

    # Get original count
    original_memories = memory_with_db.get_user_memories(user_id="test_user")
    original_count = len(original_memories)

    # Optimize memories with default SUMMARIZE strategy
    optimized = memory_with_db.optimize_memories(
        user_id="test_user",
        strategy=MemoryOptimizationStrategyType.SUMMARIZE,
        apply=True,
    )

    # Verify optimization returned results
    assert len(optimized) > 0
    assert all(isinstance(mem, UserMemory) for mem in optimized)

    # Verify memories were replaced in database
    final_memories = memory_with_db.get_user_memories(user_id="test_user")
    assert len(final_memories) == len(optimized)
    assert len(final_memories) < original_count  # Should be fewer after summarization

    # Verify optimized memory contains information from original memories
    optimized_content = " ".join([mem.memory.lower() for mem in optimized])
    assert "john doe" in optimized_content or "basketball" in optimized_content or "blue" in optimized_content


def test_optimize_memories_with_db_apply_false(memory_with_db):
    """Test optimizing memories without applying to database."""
    # Add multiple memories with different content
    memory1 = UserMemory(
        memory="The user's name is John Doe", topics=["name", "user"], user_id="test_user", updated_at=datetime.now()
    )
    memory2 = UserMemory(
        memory="The user likes to play basketball",
        topics=["sports", "hobbies"],
        user_id="test_user",
        updated_at=datetime.now(),
    )

    # Add the memories
    memory_with_db.add_user_memory(memory=memory1, user_id="test_user")
    memory_with_db.add_user_memory(memory=memory2, user_id="test_user")

    # Get original memories
    original_memories = memory_with_db.get_user_memories(user_id="test_user")
    original_count = len(original_memories)

    # Optimize memories with apply=False
    optimized = memory_with_db.optimize_memories(
        user_id="test_user",
        strategy=MemoryOptimizationStrategyType.SUMMARIZE,
        apply=False,
    )

    # Verify optimization returned results
    assert len(optimized) > 0

    # Verify original memories are still in database (not replaced)
    final_memories = memory_with_db.get_user_memories(user_id="test_user")
    assert len(final_memories) == original_count
    assert final_memories == original_memories


def test_optimize_memories_with_db_empty(memory_with_db):
    """Test optimizing memories when no memories exist."""
    # Optimize memories for user with no memories
    optimized = memory_with_db.optimize_memories(user_id="test_user", apply=False)

    # Should return empty list
    assert optimized == []


def test_optimize_memories_with_db_default_user_id(memory_with_db):
    """Test optimizing memories with default user_id."""
    # Add memories with default user_id
    memory1 = UserMemory(memory="Default user memory", topics=["test"], user_id="default", updated_at=datetime.now())
    memory_with_db.add_user_memory(memory=memory1, user_id="default")

    # Optimize without specifying user_id (should default to "default")
    optimized = memory_with_db.optimize_memories(strategy=MemoryOptimizationStrategyType.SUMMARIZE, apply=False)

    # Verify optimization worked
    assert len(optimized) > 0


def test_optimize_memories_persistence_across_instances(model, memory_db):
    """Test that optimized memories persist across different Memory instances."""
    # Create the first Memory instance
    memory1 = MemoryManager(model=model, db=memory_db)

    # Add multiple memories
    memory1_obj = UserMemory(
        memory="The user's name is John Doe", topics=["name"], user_id="test_user", updated_at=datetime.now()
    )
    memory2_obj = UserMemory(
        memory="The user likes basketball", topics=["sports"], user_id="test_user", updated_at=datetime.now()
    )

    memory1.add_user_memory(memory=memory1_obj, user_id="test_user")
    memory1.add_user_memory(memory=memory2_obj, user_id="test_user")

    # Optimize memories
    optimized = memory1.optimize_memories(user_id="test_user", apply=True)

    # Create a second Memory instance with the same database
    memory2 = MemoryManager(model=model, db=memory_db)

    # Verify optimized memories are accessible from the second instance
    final_memories = memory2.get_user_memories(user_id="test_user")
    assert len(final_memories) == len(optimized)
    assert final_memories[0].memory_id == optimized[0].memory_id
