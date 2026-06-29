import os
import tempfile
from copy import deepcopy
from datetime import datetime

import pytest

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.memory import MemoryManager, UserMemory
from agno.memory.strategies import MemoryOptimizationStrategy
from agno.models.message import Message
from agno.models.openai import OpenAIChat


class DeterministicOptimizationStrategy(MemoryOptimizationStrategy):
    def __init__(self, optimized_memories):
        self.optimized_memories = optimized_memories

    def optimize(self, memories, model):
        return deepcopy(self.optimized_memories)

    async def aoptimize(self, memories, model):
        return deepcopy(self.optimized_memories)


class _FailingSyncSession:
    def __init__(self, session_factory):
        self._session = session_factory()
        self._failed = False

    def __enter__(self):
        self._session.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._session.__exit__(exc_type, exc, tb)

    def begin(self):
        return self._session.begin()

    def execute(self, stmt, *args, **kwargs):
        if not self._failed and getattr(stmt, "is_insert", False):
            self._failed = True
            raise RuntimeError("injected replacement failure")
        return self._session.execute(stmt, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


class _FailingAsyncSession:
    def __init__(self, session_factory):
        self._session = session_factory()
        self._failed = False

    async def __aenter__(self):
        await self._session.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return await self._session.__aexit__(exc_type, exc, tb)

    def begin(self):
        return self._session.begin()

    async def execute(self, stmt, *args, **kwargs):
        if not self._failed and getattr(stmt, "is_insert", False):
            self._failed = True
            raise RuntimeError("injected replacement failure")
        return await self._session.execute(stmt, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


def _inject_sync_replace_failure(db: SqliteDb) -> None:
    original_session_factory = db.Session
    db.Session = lambda: _FailingSyncSession(original_session_factory)


def _inject_async_replace_failure(db: AsyncSqliteDb) -> None:
    original_session_factory = db.async_session_factory
    db.async_session_factory = lambda: _FailingAsyncSession(original_session_factory)


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
    yield db
    db.close()


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
    """Test optimizing memories replaces stale rows and persists."""
    memory_with_db.add_user_memory(
        memory=UserMemory(
            memory="The user's name is John Doe",
            topics=["name", "user"],
            memory_id="stale-1",
            user_id="test_user",
            updated_at=datetime.now(),
        ),
        user_id="test_user",
    )
    memory_with_db.add_user_memory(
        memory=UserMemory(
            memory="The user likes to play basketball",
            topics=["sports", "hobbies"],
            memory_id="stale-2",
            user_id="test_user",
            updated_at=datetime.now(),
        ),
        user_id="test_user",
    )
    memory_with_db.add_user_memory(
        memory=UserMemory(
            memory="The user's favorite color is blue",
            topics=["preferences", "colors"],
            memory_id="stale-3",
            user_id="test_user",
            updated_at=datetime.now(),
        ),
        user_id="test_user",
    )

    strategy = DeterministicOptimizationStrategy(
        [
            UserMemory(
                memory="John Doe likes basketball and prefers blue.",
                topics=["summary"],
                memory_id="optimized-1",
            )
        ]
    )

    optimized = memory_with_db.optimize_memories(
        user_id="test_user",
        strategy=strategy,
        apply=True,
    )

    assert [memory.memory_id for memory in optimized] == ["optimized-1"]

    final_memories = memory_with_db.get_user_memories(user_id="test_user")
    assert [memory.memory_id for memory in final_memories] == ["optimized-1"]
    assert final_memories[0].memory == "John Doe likes basketball and prefers blue."

    persisted_manager = MemoryManager(model=memory_with_db.model, db=memory_with_db.db)
    persisted_memories = persisted_manager.get_user_memories(user_id="test_user")
    assert [memory.memory_id for memory in persisted_memories] == ["optimized-1"]


def test_optimize_memories_with_db_apply_false(memory_with_db):
    """Test optimizing memories without applying to database."""
    memory_with_db.add_user_memory(
        memory=UserMemory(
            memory="The user's name is John Doe",
            topics=["name", "user"],
            memory_id="original-1",
            user_id="test_user",
            updated_at=datetime.now(),
        ),
        user_id="test_user",
    )
    memory_with_db.add_user_memory(
        memory=UserMemory(
            memory="The user likes to play basketball",
            topics=["sports", "hobbies"],
            memory_id="original-2",
            user_id="test_user",
            updated_at=datetime.now(),
        ),
        user_id="test_user",
    )

    original_memories = memory_with_db.get_user_memories(user_id="test_user")
    strategy = DeterministicOptimizationStrategy(
        [UserMemory(memory="Optimized memory", topics=["summary"], memory_id="optimized-1")]
    )

    optimized = memory_with_db.optimize_memories(
        user_id="test_user",
        strategy=strategy,
        apply=False,
    )

    final_memories = memory_with_db.get_user_memories(user_id="test_user")
    assert [memory.memory_id for memory in optimized] == ["optimized-1"]
    assert final_memories == original_memories


def test_optimize_memories_with_db_empty(memory_with_db):
    """Test optimizing memories when no memories exist."""
    optimized = memory_with_db.optimize_memories(user_id="test_user", apply=False)

    assert optimized == []


def test_optimize_memories_with_db_empty_optimized_output_preserves_existing_rows(memory_with_db):
    """Test empty optimized output leaves existing rows intact."""
    memory_with_db.add_user_memory(
        memory=UserMemory(
            memory="Keep me",
            topics=["test"],
            memory_id="keep-1",
            user_id="test_user",
            updated_at=datetime.now(),
        ),
        user_id="test_user",
    )
    memory_with_db.add_user_memory(
        memory=UserMemory(
            memory="Keep me too",
            topics=["test"],
            memory_id="keep-2",
            user_id="test_user",
            updated_at=datetime.now(),
        ),
        user_id="test_user",
    )

    before = [(memory.memory_id, memory.memory) for memory in memory_with_db.get_user_memories(user_id="test_user")]

    optimized = memory_with_db.optimize_memories(
        user_id="test_user",
        strategy=DeterministicOptimizationStrategy([]),
        apply=True,
    )

    after = [(memory.memory_id, memory.memory) for memory in memory_with_db.get_user_memories(user_id="test_user")]
    assert optimized == []
    assert after == before


def test_optimize_memories_with_db_same_id_preserves_created_at_and_refreshes_updated_at(memory_with_db):
    """Test same-ID replacements keep created_at and advance updated_at."""
    memory_with_db.add_user_memory(
        memory=UserMemory(
            memory="Original",
            topics=["test"],
            memory_id="same-1",
            user_id="test_user",
            created_at=1000,
            updated_at=1000,
        ),
        user_id="test_user",
    )

    optimized = memory_with_db.optimize_memories(
        user_id="test_user",
        strategy=DeterministicOptimizationStrategy(
            [UserMemory(memory="Optimized", topics=["summary"], memory_id="same-1")]
        ),
        apply=True,
    )

    final_memories = memory_with_db.get_user_memories(user_id="test_user")
    assert [memory.memory_id for memory in optimized] == ["same-1"]
    assert [memory.memory_id for memory in final_memories] == ["same-1"]
    assert final_memories[0].memory == "Optimized"
    assert final_memories[0].created_at == 1000
    assert final_memories[0].updated_at is not None
    assert final_memories[0].updated_at > 1000


def test_optimize_memories_with_db_default_user_id(memory_with_db):
    """Test optimizing memories with default user_id."""
    memory_with_db.add_user_memory(
        memory=UserMemory(memory="Default user memory", topics=["test"], user_id="default", updated_at=datetime.now()),
        user_id="default",
    )

    strategy = DeterministicOptimizationStrategy(
        [UserMemory(memory="Default user summary", topics=["summary"], memory_id="default-optimized-1")]
    )
    optimized = memory_with_db.optimize_memories(strategy=strategy, apply=False)

    assert [memory.memory_id for memory in optimized] == ["default-optimized-1"]


def test_optimize_memories_persistence_across_instances(model, memory_db):
    """Test that optimized memories persist across different Memory instances."""
    memory1 = MemoryManager(model=model, db=memory_db)
    memory1.add_user_memory(
        memory=UserMemory(
            memory="The user's name is John Doe",
            topics=["name"],
            memory_id="persist-stale-1",
            user_id="test_user",
            updated_at=datetime.now(),
        ),
        user_id="test_user",
    )
    memory1.add_user_memory(
        memory=UserMemory(
            memory="The user likes basketball",
            topics=["sports"],
            memory_id="persist-stale-2",
            user_id="test_user",
            updated_at=datetime.now(),
        ),
        user_id="test_user",
    )

    strategy = DeterministicOptimizationStrategy(
        [UserMemory(memory="Persisted optimized memory", topics=["summary"], memory_id="persist-optimized-1")]
    )
    optimized = memory1.optimize_memories(user_id="test_user", strategy=strategy, apply=True)

    memory2 = MemoryManager(model=model, db=memory_db)
    final_memories = memory2.get_user_memories(user_id="test_user")
    assert len(final_memories) == len(optimized)
    assert final_memories[0].memory_id == optimized[0].memory_id


def test_optimize_memories_replace_failure_preserves_existing_rows(temp_db_file, model):
    """Test replacement rollback preserves existing memories on failure."""
    db = SqliteDb(db_file=temp_db_file)
    try:
        manager = MemoryManager(model=model, db=db)
        manager.add_user_memory(
            memory=UserMemory(memory="Keep me", topics=["test"], memory_id="keep-1", user_id="test_user"),
            user_id="test_user",
        )
        manager.add_user_memory(
            memory=UserMemory(memory="Keep me too", topics=["test"], memory_id="keep-2", user_id="test_user"),
            user_id="test_user",
        )

        strategy = DeterministicOptimizationStrategy(
            [UserMemory(memory="Should not persist", topics=["summary"], memory_id="optimized-1")]
        )

        before = [(memory.memory_id, memory.memory) for memory in manager.get_user_memories(user_id="test_user")]
        _inject_sync_replace_failure(db)

        with pytest.raises(RuntimeError, match="injected replacement failure"):
            manager.optimize_memories(user_id="test_user", strategy=strategy, apply=True)

        after = [(memory.memory_id, memory.memory) for memory in manager.get_user_memories(user_id="test_user")]
        assert after == before
    finally:
        db.close()


@pytest.mark.asyncio
async def test_aoptimize_memories_with_async_sqlite_persists_replacement(temp_db_file, model):
    """Test async optimization uses async SQLite replacement."""
    db = AsyncSqliteDb(db_file=temp_db_file)
    try:
        await db._get_table(table_type="memories", create_table_if_not_found=True)
        await db.upsert_user_memory(
            UserMemory(memory="Stale memory one", topics=["test"], memory_id="async-stale-1", user_id="test_user")
        )
        await db.upsert_user_memory(
            UserMemory(memory="Stale memory two", topics=["test"], memory_id="async-stale-2", user_id="test_user")
        )

        manager = MemoryManager(model=model, db=db)
        strategy = DeterministicOptimizationStrategy(
            [UserMemory(memory="Async optimized memory", topics=["summary"], memory_id="async-optimized-1")]
        )

        optimized = await manager.aoptimize_memories(user_id="test_user", strategy=strategy, apply=True)

        final_memories = await db.get_user_memories(user_id="test_user")
        assert [memory.memory_id for memory in optimized] == ["async-optimized-1"]
        assert [memory.memory_id for memory in final_memories] == ["async-optimized-1"]

        persisted_manager = MemoryManager(model=model, db=db)
        persisted_memories = await persisted_manager.aget_user_memories(user_id="test_user")
        assert [memory.memory_id for memory in persisted_memories] == ["async-optimized-1"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_aoptimize_memories_with_async_sqlite_replace_failure_preserves_existing_rows(temp_db_file, model):
    """Test async replacement rollback preserves existing memories on failure."""
    db = AsyncSqliteDb(db_file=temp_db_file)
    try:
        await db._get_table(table_type="memories", create_table_if_not_found=True)
        await db.upsert_user_memory(
            UserMemory(memory="Keep me", topics=["test"], memory_id="async-keep-1", user_id="test_user")
        )
        await db.upsert_user_memory(
            UserMemory(memory="Keep me too", topics=["test"], memory_id="async-keep-2", user_id="test_user")
        )

        manager = MemoryManager(model=model, db=db)
        before = [(memory.memory_id, memory.memory) for memory in await db.get_user_memories(user_id="test_user")]
        _inject_async_replace_failure(db)

        with pytest.raises(RuntimeError, match="injected replacement failure"):
            await manager.aoptimize_memories(
                user_id="test_user",
                strategy=DeterministicOptimizationStrategy(
                    [UserMemory(memory="Should not persist", topics=["summary"], memory_id="async-optimized-1")]
                ),
                apply=True,
            )

        after = [(memory.memory_id, memory.memory) for memory in await db.get_user_memories(user_id="test_user")]
        assert after == before
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_aoptimize_memories_with_async_sqlite_empty_optimized_output_preserves_rows(temp_db_file, model):
    """Test async empty optimized output leaves existing rows intact."""
    db = AsyncSqliteDb(db_file=temp_db_file)
    try:
        await db._get_table(table_type="memories", create_table_if_not_found=True)
        await db.upsert_user_memory(
            UserMemory(memory="Keep me", topics=["test"], memory_id="async-keep-1", user_id="test_user")
        )
        await db.upsert_user_memory(
            UserMemory(memory="Keep me too", topics=["test"], memory_id="async-keep-2", user_id="test_user")
        )

        manager = MemoryManager(model=model, db=db)
        before = [(memory.memory_id, memory.memory) for memory in await db.get_user_memories(user_id="test_user")]

        optimized = await manager.aoptimize_memories(
            user_id="test_user",
            strategy=DeterministicOptimizationStrategy([]),
            apply=True,
        )

        after = [(memory.memory_id, memory.memory) for memory in await db.get_user_memories(user_id="test_user")]
        assert optimized == []
        assert after == before
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_aoptimize_memories_with_async_sqlite_same_id_preserves_created_at_and_refreshes_updated_at(
    temp_db_file, model
):
    """Test async same-ID replacements keep created_at and advance updated_at."""
    db = AsyncSqliteDb(db_file=temp_db_file)
    try:
        await db._get_table(table_type="memories", create_table_if_not_found=True)
        await db.upsert_user_memory(
            UserMemory(
                memory="Original",
                topics=["test"],
                memory_id="async-same-1",
                user_id="test_user",
                created_at=1000,
                updated_at=1000,
            )
        )

        manager = MemoryManager(model=model, db=db)
        optimized = await manager.aoptimize_memories(
            user_id="test_user",
            strategy=DeterministicOptimizationStrategy(
                [UserMemory(memory="Optimized", topics=["summary"], memory_id="async-same-1")]
            ),
            apply=True,
        )

        final_memories = await db.get_user_memories(user_id="test_user")
        assert [memory.memory_id for memory in optimized] == ["async-same-1"]
        assert [memory.memory_id for memory in final_memories] == ["async-same-1"]
        assert final_memories[0].memory == "Optimized"
        assert final_memories[0].created_at == 1000
        assert final_memories[0].updated_at is not None
        assert final_memories[0].updated_at > 1000
    finally:
        await db.close()
