from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.db.base import AsyncBaseDb, BaseDb
from agno.memory.manager import MemoryManager, UserMemory
from agno.memory.strategies import (
    MemoryOptimizationStrategy,
    MemoryOptimizationStrategyType,
)


@pytest.fixture
def mock_db():
    db = MagicMock(spec=BaseDb)
    # Setup default behaviors
    db.upsert_user_memory.return_value = None
    return db


@pytest.fixture
def mock_async_db():
    db = AsyncMock(spec=AsyncBaseDb)
    return db


@pytest.fixture
def mock_model():
    model = MagicMock()
    # Patch get_model to return our mock model instead of validating it
    with patch("agno.memory.manager.get_model", return_value=model):
        yield model


@pytest.fixture
def mock_strategy():
    strategy = MagicMock(spec=MemoryOptimizationStrategy)
    strategy.count_tokens.return_value = 100
    return strategy


@pytest.fixture
def sample_memories():
    return [
        UserMemory(memory="Memory 1", user_id="user-1", memory_id="m1"),
        UserMemory(memory="Memory 2", user_id="user-1", memory_id="m2"),
    ]


@pytest.fixture
def optimized_memories():
    return [UserMemory(memory="Optimized Memory", user_id="user-1", memory_id="opt-1")]


def test_optimize_memories_success(mock_db, mock_model, mock_strategy, sample_memories, optimized_memories):
    """Test successful synchronous memory optimization."""
    # Setup
    manager = MemoryManager(db=mock_db, model=mock_model)
    manager.get_user_memories = MagicMock(return_value=sample_memories)
    manager.clear_user_memories = MagicMock()

    # Mock factory to return our mock strategy
    with patch(
        "agno.memory.strategies.MemoryOptimizationStrategyFactory.create_strategy", return_value=mock_strategy
    ) as mock_factory:
        # Mock strategy optimize method
        mock_strategy.optimize.return_value = optimized_memories

        # Execute
        result = manager.optimize_memories(
            user_id="user-1", strategy=MemoryOptimizationStrategyType.SUMMARIZE, apply=True
        )

        # Verify Factory usage
        mock_factory.assert_called_once_with(MemoryOptimizationStrategyType.SUMMARIZE)

        # Verify Optimization call
        mock_strategy.optimize.assert_called_once_with(memories=sample_memories, model=mock_model)

        # Verify DB operations (apply=True)
        manager.clear_user_memories.assert_called_once_with(user_id="user-1")
        mock_db.upsert_user_memory.assert_called()
        assert mock_db.upsert_user_memory.call_count == len(optimized_memories)
        assert result == optimized_memories


def test_optimize_memories_apply_false(mock_db, mock_model, mock_strategy, sample_memories, optimized_memories):
    """Test optimization without applying changes to DB."""
    manager = MemoryManager(db=mock_db, model=mock_model)
    manager.get_user_memories = MagicMock(return_value=sample_memories)
    manager.clear_user_memories = MagicMock()

    with patch("agno.memory.strategies.MemoryOptimizationStrategyFactory.create_strategy", return_value=mock_strategy):
        mock_strategy.optimize.return_value = optimized_memories

        result = manager.optimize_memories(user_id="user-1", apply=False)

        # Verify DB was NOT touched
        manager.clear_user_memories.assert_not_called()
        mock_db.upsert_user_memory.assert_not_called()
        assert result == optimized_memories


def test_optimize_memories_empty(mock_db, mock_model):
    """Test optimization with no existing memories."""
    manager = MemoryManager(db=mock_db, model=mock_model)
    manager.get_user_memories = MagicMock(return_value=[])

    result = manager.optimize_memories(user_id="user-1")

    assert result == []
    # Should return early before creating strategy
    mock_model.assert_not_called()


def test_optimize_memories_custom_strategy_instance(
    mock_db, mock_model, mock_strategy, sample_memories, optimized_memories
):
    """Test optimization passing a strategy instance directly."""
    manager = MemoryManager(db=mock_db, model=mock_model)
    manager.get_user_memories = MagicMock(return_value=sample_memories)
    manager.clear_user_memories = MagicMock()

    mock_strategy.optimize.return_value = optimized_memories

    # Pass instance directly
    manager.optimize_memories(user_id="user-1", strategy=mock_strategy, apply=True)

    # Verify method called on passed instance
    mock_strategy.optimize.assert_called_once()


def test_optimize_memories_async_db_error(mock_async_db, mock_model):
    """Test that calling sync optimize with async DB raises ValueError."""
    manager = MemoryManager(db=mock_async_db, model=mock_model)

    with pytest.raises(ValueError, match="not supported with an async DB"):
        manager.optimize_memories(user_id="user-1")


@pytest.mark.asyncio
async def test_aoptimize_memories_success(
    mock_async_db, mock_model, mock_strategy, sample_memories, optimized_memories
):
    """Test successful async memory optimization."""
    manager = MemoryManager(db=mock_async_db, model=mock_model)
    manager.aget_user_memories = AsyncMock(return_value=sample_memories)
    manager.aclear_user_memories = AsyncMock()

    with patch("agno.memory.strategies.MemoryOptimizationStrategyFactory.create_strategy", return_value=mock_strategy):
        mock_strategy.aoptimize = AsyncMock(return_value=optimized_memories)

        result = await manager.aoptimize_memories(
            user_id="user-1", strategy=MemoryOptimizationStrategyType.SUMMARIZE, apply=True
        )

        # Verify async calls
        mock_strategy.aoptimize.assert_called_once_with(memories=sample_memories, model=mock_model)
        manager.aclear_user_memories.assert_called_once_with(user_id="user-1")
        assert mock_async_db.upsert_user_memory.await_count == len(optimized_memories)
        assert result == optimized_memories


@pytest.mark.asyncio
async def test_aoptimize_memories_apply_false(
    mock_async_db, mock_model, mock_strategy, sample_memories, optimized_memories
):
    """Test async optimization without applying to DB."""
    manager = MemoryManager(db=mock_async_db, model=mock_model)
    manager.aget_user_memories = AsyncMock(return_value=sample_memories)
    manager.aclear_user_memories = AsyncMock()

    with patch("agno.memory.strategies.MemoryOptimizationStrategyFactory.create_strategy", return_value=mock_strategy):
        mock_strategy.aoptimize = AsyncMock(return_value=optimized_memories)

        result = await manager.aoptimize_memories(user_id="user-1", apply=False)

        manager.aclear_user_memories.assert_not_called()
        mock_async_db.upsert_user_memory.assert_not_called()
        assert result == optimized_memories


@pytest.mark.asyncio
async def test_aoptimize_memories_empty(mock_async_db, mock_model):
    """Test async optimization with empty memories."""
    manager = MemoryManager(db=mock_async_db, model=mock_model)
    manager.aget_user_memories = AsyncMock(return_value=[])

    result = await manager.aoptimize_memories(user_id="user-1")

    assert result == []


@pytest.mark.asyncio
async def test_aoptimize_memories_sync_db_compatibility(
    mock_db, mock_model, mock_strategy, sample_memories, optimized_memories
):
    """Test that async optimize works even with a sync DB (hybrid usage)."""
    manager = MemoryManager(db=mock_db, model=mock_model)
    # Note: With sync DB, it calls get_user_memories (sync) not aget
    manager.get_user_memories = MagicMock(return_value=sample_memories)
    manager.clear_user_memories = MagicMock()
    # But upsert/clear might be handled differently depending on implementation
    # The code handles `isinstance(self.db, AsyncBaseDb)` checks.

    # Since we mocked db as BaseDb, manager treats it as sync

    with patch("agno.memory.strategies.MemoryOptimizationStrategyFactory.create_strategy", return_value=mock_strategy):
        mock_strategy.aoptimize = AsyncMock(return_value=optimized_memories)

        # It should use the async strategy method, but sync DB methods
        result = await manager.aoptimize_memories(user_id="user-1", apply=True)

        mock_strategy.aoptimize.assert_called_once()
        # Should use sync upsert since DB is sync
        mock_db.upsert_user_memory.assert_called()
        assert result == optimized_memories
