"""Tests for MemoryManager CRUD operations and initialization.

Covers methods in agno/memory/manager.py: initialization, get_user_memories,
get_user_memory, add_user_memory, replace_user_memory, delete_user_memory,
clear, clear_user_memories, read_from_db, and aread_from_db.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.db.schemas import UserMemory
from agno.memory.manager import MemoryManager


@pytest.fixture
def mock_db():
    """Create a mock synchronous database."""
    db = MagicMock()
    db.get_user_memories = MagicMock(return_value=[])
    db.upsert_user_memory = MagicMock(return_value=None)
    db.delete_user_memory = MagicMock(return_value=None)
    db.clear_memories = MagicMock(return_value=None)
    return db


@pytest.fixture
def manager(mock_db):
    """Create a MemoryManager with mock db."""
    return MemoryManager(db=mock_db)


@pytest.fixture
def sample_memories():
    """Create sample UserMemory objects."""
    return [
        UserMemory(memory_id="mem1", user_id="user1", memory="I like cats", updated_at=100),
        UserMemory(memory_id="mem2", user_id="user1", memory="I work at Acme", updated_at=200),
        UserMemory(memory_id="mem3", user_id="user2", memory="I prefer dark mode", updated_at=150),
    ]


# =============================================================================
# Tests for initialization
# =============================================================================


class TestMemoryManagerInit:
    def test_default_initialization(self):
        """Default MemoryManager has expected defaults."""
        mm = MemoryManager()
        assert mm.model is None
        assert mm.db is None
        assert mm.add_memories is True
        assert mm.update_memories is True
        assert mm.delete_memories is False
        assert mm.clear_memories is False
        assert mm.debug_mode is False

    def test_initialization_with_db(self, mock_db):
        """MemoryManager can be initialized with a database."""
        mm = MemoryManager(db=mock_db)
        assert mm.db is mock_db

    def test_initialization_with_string_model(self):
        """String model is converted via get_model()."""
        with patch("agno.memory.manager.get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model
            mm = MemoryManager(model="gpt-4o")
            mock_get_model.assert_called_once_with("gpt-4o")
            assert mm.model is mock_model

    def test_initialization_with_model_instance(self):
        """Model instance is passed through get_model()."""
        mock_model = MagicMock()
        with patch("agno.memory.manager.get_model") as mock_get_model:
            mock_get_model.return_value = mock_model
            mm = MemoryManager(model=mock_model)
            assert mm.model is mock_model

    def test_configuration_flags(self):
        """All configuration flags are set correctly."""
        mm = MemoryManager(
            delete_memories=True,
            update_memories=False,
            add_memories=False,
            clear_memories=True,
            debug_mode=True,
        )
        assert mm.delete_memories is True
        assert mm.update_memories is False
        assert mm.add_memories is False
        assert mm.clear_memories is True
        assert mm.debug_mode is True


# =============================================================================
# Tests for read_from_db
# =============================================================================


class TestReadFromDb:
    def test_read_from_db_groups_by_user_id(self, manager, mock_db, sample_memories):
        """Memories are grouped by user_id."""
        mock_db.get_user_memories.return_value = sample_memories
        result = manager.read_from_db()
        assert "user1" in result
        assert "user2" in result
        assert len(result["user1"]) == 2
        assert len(result["user2"]) == 1

    def test_read_from_db_with_user_id(self, manager, mock_db, sample_memories):
        """When user_id is provided, it's passed to db."""
        user1_memories = [m for m in sample_memories if m.user_id == "user1"]
        mock_db.get_user_memories.return_value = user1_memories
        result = manager.read_from_db(user_id="user1")
        mock_db.get_user_memories.assert_called_with(user_id="user1")
        assert "user1" in result

    def test_read_from_db_no_db(self):
        """Returns None when no db is set."""
        mm = MemoryManager()
        result = mm.read_from_db()
        assert result is None

    def test_read_from_db_skips_null_ids(self, manager, mock_db):
        """Memories with null memory_id or user_id are skipped."""
        memories = [
            UserMemory(memory_id=None, user_id="user1", memory="no memory_id"),
            UserMemory(memory_id="mem1", user_id=None, memory="no user_id"),
            UserMemory(memory_id="mem2", user_id="user1", memory="valid"),
        ]
        mock_db.get_user_memories.return_value = memories
        result = manager.read_from_db()
        assert len(result.get("user1", [])) == 1
        assert result["user1"][0].memory_id == "mem2"


# =============================================================================
# Tests for get_user_memories
# =============================================================================


class TestGetUserMemories:
    def test_get_user_memories_returns_list(self, manager, mock_db, sample_memories):
        """Returns list of memories for a user."""
        mock_db.get_user_memories.return_value = [m for m in sample_memories if m.user_id == "user1"]
        result = manager.get_user_memories(user_id="user1")
        assert len(result) == 2

    def test_get_user_memories_default_user(self, manager, mock_db):
        """Uses 'default' user_id when none provided."""
        mock_db.get_user_memories.return_value = []
        result = manager.get_user_memories()
        mock_db.get_user_memories.assert_called_with(user_id="default")
        assert result == []

    def test_get_user_memories_no_db(self):
        """Returns empty list when no db."""
        mm = MemoryManager()
        result = mm.get_user_memories()
        assert result == []

    def test_get_user_memories_empty_result(self, manager, mock_db):
        """Returns empty list when no memories found."""
        mock_db.get_user_memories.return_value = []
        result = manager.get_user_memories(user_id="nonexistent")
        assert result == []


# =============================================================================
# Tests for get_user_memory
# =============================================================================


class TestGetUserMemory:
    def test_get_user_memory_found(self, manager, mock_db, sample_memories):
        """Returns specific memory by id."""
        mock_db.get_user_memories.return_value = [m for m in sample_memories if m.user_id == "user1"]
        result = manager.get_user_memory(memory_id="mem1", user_id="user1")
        assert result is not None
        assert result.memory_id == "mem1"

    def test_get_user_memory_not_found(self, manager, mock_db, sample_memories):
        """Returns None when memory_id not found."""
        mock_db.get_user_memories.return_value = [m for m in sample_memories if m.user_id == "user1"]
        result = manager.get_user_memory(memory_id="nonexistent", user_id="user1")
        assert result is None

    def test_get_user_memory_default_user(self, manager, mock_db):
        """Uses 'default' user_id when none provided."""
        mock_db.get_user_memories.return_value = []
        result = manager.get_user_memory(memory_id="mem1")
        mock_db.get_user_memories.assert_called_with(user_id="default")
        assert result is None

    def test_get_user_memory_no_db(self):
        """Returns None when no db."""
        mm = MemoryManager()
        result = mm.get_user_memory(memory_id="mem1")
        assert result is None


# =============================================================================
# Tests for add_user_memory
# =============================================================================


class TestAddUserMemory:
    def test_add_memory_with_id(self, manager, mock_db):
        """Memory with existing memory_id is preserved."""
        memory = UserMemory(memory_id="existing_id", memory="test memory")
        result = manager.add_user_memory(memory, user_id="user1")
        assert result == "existing_id"
        assert memory.user_id == "user1"

    def test_add_memory_generates_id(self, manager, mock_db):
        """Memory without memory_id gets one generated."""
        memory = UserMemory(memory="test memory")
        result = manager.add_user_memory(memory, user_id="user1")
        assert result is not None
        assert memory.memory_id is not None

    def test_add_memory_default_user(self, manager, mock_db):
        """Default user_id is 'default'."""
        memory = UserMemory(memory_id="mem1", memory="test")
        manager.add_user_memory(memory)
        assert memory.user_id == "default"

    def test_add_memory_sets_updated_at(self, manager, mock_db):
        """updated_at is set when not provided."""
        memory = UserMemory(memory_id="mem1", memory="test")
        manager.add_user_memory(memory)
        assert memory.updated_at is not None
        assert memory.updated_at > 0

    def test_add_memory_preserves_updated_at(self, manager, mock_db):
        """Existing updated_at is preserved."""
        memory = UserMemory(memory_id="mem1", memory="test", updated_at=42)
        manager.add_user_memory(memory)
        assert memory.updated_at == 42

    def test_add_memory_calls_upsert(self, manager, mock_db):
        """_upsert_db_memory is called with the memory."""
        memory = UserMemory(memory_id="mem1", memory="test")
        with patch.object(manager, "_upsert_db_memory") as mock_upsert:
            manager.add_user_memory(memory)
            mock_upsert.assert_called_once_with(memory=memory)

    def test_add_memory_no_db(self):
        """Returns None when no db."""
        mm = MemoryManager()
        memory = UserMemory(memory_id="mem1", memory="test")
        result = mm.add_user_memory(memory)
        assert result is None


# =============================================================================
# Tests for replace_user_memory
# =============================================================================


class TestReplaceUserMemory:
    def test_replace_memory(self, manager, mock_db):
        """Memory is replaced with new id and user_id."""
        memory = UserMemory(memory="updated content")
        with patch.object(manager, "_upsert_db_memory") as mock_upsert:
            result = manager.replace_user_memory("mem1", memory, user_id="user1")
            assert result == "mem1"
            assert memory.memory_id == "mem1"
            assert memory.user_id == "user1"
            mock_upsert.assert_called_once()

    def test_replace_memory_default_user(self, manager, mock_db):
        """Default user_id is 'default'."""
        memory = UserMemory(memory="updated")
        with patch.object(manager, "_upsert_db_memory"):
            manager.replace_user_memory("mem1", memory)
            assert memory.user_id == "default"

    def test_replace_memory_sets_updated_at(self, manager, mock_db):
        """updated_at is set when not provided."""
        memory = UserMemory(memory="updated")
        with patch.object(manager, "_upsert_db_memory"):
            manager.replace_user_memory("mem1", memory)
            assert memory.updated_at is not None

    def test_replace_memory_no_db(self):
        """Returns None when no db."""
        mm = MemoryManager()
        memory = UserMemory(memory="test")
        result = mm.replace_user_memory("mem1", memory)
        assert result is None


# =============================================================================
# Tests for delete_user_memory
# =============================================================================


class TestDeleteUserMemory:
    def test_delete_memory(self, manager, mock_db):
        """Memory is deleted via _delete_db_memory."""
        with patch.object(manager, "_delete_db_memory") as mock_delete:
            manager.delete_user_memory("mem1", user_id="user1")
            mock_delete.assert_called_once_with(memory_id="mem1", user_id="user1")

    def test_delete_memory_default_user(self, manager, mock_db):
        """Default user_id is 'default'."""
        with patch.object(manager, "_delete_db_memory") as mock_delete:
            manager.delete_user_memory("mem1")
            mock_delete.assert_called_once_with(memory_id="mem1", user_id="default")

    def test_delete_memory_no_db(self):
        """Returns None when no db."""
        mm = MemoryManager()
        result = mm.delete_user_memory("mem1")
        assert result is None


# =============================================================================
# Tests for clear
# =============================================================================


class TestClear:
    def test_clear_calls_db(self, manager, mock_db):
        """clear() calls db.clear_memories()."""
        manager.clear()
        mock_db.clear_memories.assert_called_once()

    def test_clear_no_db(self):
        """clear() does nothing when no db."""
        mm = MemoryManager()
        mm.clear()  # Should not raise


# =============================================================================
# Tests for clear_user_memories
# =============================================================================


class TestClearUserMemories:
    def test_clear_user_memories(self, manager, mock_db, sample_memories):
        """Clears all memories for a specific user via batch delete."""
        user1_memories = [m for m in sample_memories if m.user_id == "user1"]
        mock_db.get_user_memories.return_value = user1_memories
        mock_db.delete_user_memories = MagicMock()
        manager.clear_user_memories(user_id="user1")
        mock_db.delete_user_memories.assert_called_once()
        call_args = mock_db.delete_user_memories.call_args
        assert call_args.kwargs["user_id"] == "user1"
        assert len(call_args.kwargs["memory_ids"]) == 2

    def test_clear_user_memories_default_user(self, manager, mock_db):
        """Uses 'default' user_id when none provided."""
        mock_db.get_user_memories.return_value = []
        manager.clear_user_memories()
        mock_db.get_user_memories.assert_called_with(user_id="default")

    def test_clear_user_memories_no_db(self):
        """Does nothing when no db."""
        mm = MemoryManager()
        mm.clear_user_memories()  # Should not raise

    def test_clear_user_memories_async_db_raises(self):
        """Raises ValueError when using async db with sync clear."""
        from agno.db.base import AsyncBaseDb

        mock_async_db = MagicMock(spec=AsyncBaseDb)
        mm = MemoryManager(db=mock_async_db)
        with pytest.raises(ValueError, match="not supported with an async DB"):
            mm.clear_user_memories(user_id="user1")


# =============================================================================
# Tests for async read_from_db
# =============================================================================


class TestAsyncReadFromDb:
    @pytest.mark.asyncio
    async def test_aread_from_db_with_async_db(self):
        """aread_from_db works with AsyncBaseDb."""
        from agno.db.base import AsyncBaseDb

        mock_db = MagicMock(spec=AsyncBaseDb)
        mock_db.get_user_memories = AsyncMock(
            return_value=[
                UserMemory(memory_id="mem1", user_id="user1", memory="async memory"),
            ]
        )
        mm = MemoryManager(db=mock_db)
        result = await mm.aread_from_db(user_id="user1")
        assert "user1" in result
        assert len(result["user1"]) == 1

    @pytest.mark.asyncio
    async def test_aread_from_db_with_sync_db(self, mock_db, sample_memories):
        """aread_from_db falls back to sync calls for sync db."""
        mock_db.get_user_memories.return_value = [m for m in sample_memories if m.user_id == "user1"]
        mm = MemoryManager(db=mock_db)
        result = await mm.aread_from_db(user_id="user1")
        assert "user1" in result

    @pytest.mark.asyncio
    async def test_aread_from_db_no_db(self):
        """Returns None when no db."""
        mm = MemoryManager()
        result = await mm.aread_from_db()
        assert result is None


# =============================================================================
# Tests for async get_user_memories
# =============================================================================


class TestAsyncGetUserMemories:
    @pytest.mark.asyncio
    async def test_aget_user_memories(self, mock_db, sample_memories):
        """aget_user_memories returns memories for a user."""
        mock_db.get_user_memories.return_value = [m for m in sample_memories if m.user_id == "user1"]
        mm = MemoryManager(db=mock_db)
        result = await mm.aget_user_memories(user_id="user1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_aget_user_memories_default_user(self, mock_db):
        """Uses 'default' user_id when none provided."""
        mock_db.get_user_memories.return_value = []
        mm = MemoryManager(db=mock_db)
        result = await mm.aget_user_memories()
        mock_db.get_user_memories.assert_called_with(user_id="default")
        assert result == []

    @pytest.mark.asyncio
    async def test_aget_user_memories_no_db(self):
        """Returns empty list when no db."""
        mm = MemoryManager()
        result = await mm.aget_user_memories()
        assert result == []
