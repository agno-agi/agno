from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agno.db.base import AsyncBaseDb, BaseDb
from agno.memory.manager import MemoryManager, UserMemory
from agno.memory.strategies import MemoryOptimizationStrategy, MemoryOptimizationStrategyType


@pytest.fixture
def mock_db():
    db = MagicMock(spec=BaseDb)
    db.upsert_user_memory.return_value = None
    db.replace_user_memories.return_value = None
    return db


@pytest.fixture
def mock_async_db():
    return AsyncMock(spec=AsyncBaseDb)


@pytest.fixture
def mock_model():
    model = MagicMock()
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
    manager = MemoryManager(db=mock_db, model=mock_model)
    manager.get_user_memories = MagicMock(return_value=sample_memories)
    manager.clear_user_memories = MagicMock()

    with patch(
        "agno.memory.strategies.MemoryOptimizationStrategyFactory.create_strategy",
        return_value=mock_strategy,
    ) as mock_factory:
        mock_strategy.optimize.return_value = optimized_memories

        result = manager.optimize_memories(
            user_id="user-1",
            strategy=MemoryOptimizationStrategyType.SUMMARIZE,
            apply=True,
        )

    mock_factory.assert_called_once_with(MemoryOptimizationStrategyType.SUMMARIZE)
    mock_strategy.optimize.assert_called_once_with(memories=sample_memories, model=mock_model)
    manager.clear_user_memories.assert_not_called()
    mock_db.upsert_user_memory.assert_not_called()
    mock_db.replace_user_memories.assert_called_once_with(user_id="user-1", memories=optimized_memories)
    assert result == optimized_memories


def test_optimize_memories_apply_false(mock_db, mock_model, mock_strategy, sample_memories, optimized_memories):
    manager = MemoryManager(db=mock_db, model=mock_model)
    manager.get_user_memories = MagicMock(return_value=sample_memories)
    manager.clear_user_memories = MagicMock()

    with patch("agno.memory.strategies.MemoryOptimizationStrategyFactory.create_strategy", return_value=mock_strategy):
        mock_strategy.optimize.return_value = optimized_memories

        result = manager.optimize_memories(user_id="user-1", apply=False)

    manager.clear_user_memories.assert_not_called()
    mock_db.upsert_user_memory.assert_not_called()
    mock_db.replace_user_memories.assert_not_called()
    assert result == optimized_memories


def test_optimize_memories_empty(mock_db, mock_model):
    manager = MemoryManager(db=mock_db, model=mock_model)
    manager.get_user_memories = MagicMock(return_value=[])

    result = manager.optimize_memories(user_id="user-1")

    assert result == []
    mock_model.assert_not_called()
    mock_db.replace_user_memories.assert_not_called()


def test_optimize_memories_custom_strategy_instance(
    mock_db,
    mock_model,
    mock_strategy,
    sample_memories,
    optimized_memories,
):
    manager = MemoryManager(db=mock_db, model=mock_model)
    manager.get_user_memories = MagicMock(return_value=sample_memories)
    manager.clear_user_memories = MagicMock()
    mock_strategy.optimize.return_value = optimized_memories

    manager.optimize_memories(user_id="user-1", strategy=mock_strategy, apply=True)

    mock_strategy.optimize.assert_called_once()
    manager.clear_user_memories.assert_not_called()
    mock_db.upsert_user_memory.assert_not_called()
    mock_db.replace_user_memories.assert_called_once_with(user_id="user-1", memories=optimized_memories)


def test_optimize_memories_async_db_error(mock_async_db, mock_model):
    manager = MemoryManager(db=mock_async_db, model=mock_model)

    with pytest.raises(ValueError, match="not supported with an async DB"):
        manager.optimize_memories(user_id="user-1")


def test_async_db_contract_exposes_replacement_and_bulk_upsert(mock_async_db):
    assert hasattr(mock_async_db, "replace_user_memories")
    assert hasattr(mock_async_db, "upsert_memories")


def test_base_db_replace_user_memories_stages_upserts_before_stale_deletes():
    db = MagicMock(spec=BaseDb)
    existing_memories = [
        UserMemory(memory="stale", user_id="user-1", memory_id="stale-1"),
        UserMemory(memory="shared", user_id="user-1", memory_id="shared-1"),
    ]
    replacement_memories = [
        UserMemory(memory="shared updated", user_id="user-1", memory_id="shared-1"),
        UserMemory(memory="new", user_id="user-1", memory_id="new-1"),
    ]
    db.get_user_memories.return_value = existing_memories
    db.upsert_memories.return_value = replacement_memories

    result = BaseDb.replace_user_memories(db, user_id="user-1", memories=replacement_memories)

    assert result == replacement_memories
    db.get_user_memories.assert_called_once_with(user_id="user-1")
    db.upsert_memories.assert_called_once_with(memories=replacement_memories, deserialize=True)
    db.delete_user_memories.assert_called_once_with(memory_ids=["stale-1"], user_id="user-1")
    assert db.mock_calls == [
        call.get_user_memories(user_id="user-1"),
        call.upsert_memories(memories=replacement_memories, deserialize=True),
        call.delete_user_memories(memory_ids=["stale-1"], user_id="user-1"),
    ]


@pytest.mark.asyncio
async def test_async_base_db_replace_user_memories_stages_upserts_before_stale_deletes():
    db = AsyncMock(spec=AsyncBaseDb)
    existing_memories = [
        UserMemory(memory="stale", user_id="user-1", memory_id="stale-1"),
        UserMemory(memory="shared", user_id="user-1", memory_id="shared-1"),
    ]
    replacement_memories = [
        UserMemory(memory="shared updated", user_id="user-1", memory_id="shared-1"),
        UserMemory(memory="new", user_id="user-1", memory_id="new-1"),
    ]
    db.get_user_memories.return_value = existing_memories
    db.upsert_memories.return_value = replacement_memories

    result = await AsyncBaseDb.replace_user_memories(db, user_id="user-1", memories=replacement_memories)

    assert result == replacement_memories
    db.get_user_memories.assert_awaited_once_with(user_id="user-1")
    db.upsert_memories.assert_awaited_once_with(memories=replacement_memories, deserialize=True)
    db.delete_user_memories.assert_awaited_once_with(memory_ids=["stale-1"], user_id="user-1")
    assert db.mock_calls == [
        call.get_user_memories(user_id="user-1"),
        call.upsert_memories(memories=replacement_memories, deserialize=True),
        call.delete_user_memories(memory_ids=["stale-1"], user_id="user-1"),
    ]


@pytest.mark.asyncio
async def test_aoptimize_memories_success(
    mock_async_db,
    mock_model,
    mock_strategy,
    sample_memories,
    optimized_memories,
):
    manager = MemoryManager(db=mock_async_db, model=mock_model)
    manager.aget_user_memories = AsyncMock(return_value=sample_memories)
    manager.aclear_user_memories = AsyncMock()

    with patch("agno.memory.strategies.MemoryOptimizationStrategyFactory.create_strategy", return_value=mock_strategy):
        mock_strategy.aoptimize = AsyncMock(return_value=optimized_memories)

        result = await manager.aoptimize_memories(
            user_id="user-1",
            strategy=MemoryOptimizationStrategyType.SUMMARIZE,
            apply=True,
        )

    mock_strategy.aoptimize.assert_called_once_with(memories=sample_memories, model=mock_model)
    manager.aclear_user_memories.assert_not_called()
    mock_async_db.upsert_user_memory.assert_not_called()
    mock_async_db.replace_user_memories.assert_awaited_once_with(
        user_id="user-1",
        memories=optimized_memories,
    )
    assert result == optimized_memories


@pytest.mark.asyncio
async def test_aoptimize_memories_apply_false(
    mock_async_db,
    mock_model,
    mock_strategy,
    sample_memories,
    optimized_memories,
):
    manager = MemoryManager(db=mock_async_db, model=mock_model)
    manager.aget_user_memories = AsyncMock(return_value=sample_memories)
    manager.aclear_user_memories = AsyncMock()

    with patch("agno.memory.strategies.MemoryOptimizationStrategyFactory.create_strategy", return_value=mock_strategy):
        mock_strategy.aoptimize = AsyncMock(return_value=optimized_memories)

        result = await manager.aoptimize_memories(user_id="user-1", apply=False)

    manager.aclear_user_memories.assert_not_called()
    mock_async_db.upsert_user_memory.assert_not_called()
    mock_async_db.replace_user_memories.assert_not_called()
    assert result == optimized_memories


@pytest.mark.asyncio
async def test_aoptimize_memories_empty(mock_async_db, mock_model):
    manager = MemoryManager(db=mock_async_db, model=mock_model)
    manager.aget_user_memories = AsyncMock(return_value=[])

    result = await manager.aoptimize_memories(user_id="user-1")

    assert result == []
    mock_async_db.replace_user_memories.assert_not_called()


@pytest.mark.asyncio
async def test_aoptimize_memories_sync_db_compatibility(
    mock_db,
    mock_model,
    mock_strategy,
    sample_memories,
    optimized_memories,
):
    manager = MemoryManager(db=mock_db, model=mock_model)
    manager.get_user_memories = MagicMock(return_value=sample_memories)
    manager.clear_user_memories = MagicMock()

    with patch("agno.memory.strategies.MemoryOptimizationStrategyFactory.create_strategy", return_value=mock_strategy):
        mock_strategy.aoptimize = AsyncMock(return_value=optimized_memories)

        result = await manager.aoptimize_memories(user_id="user-1", apply=True)

    mock_strategy.aoptimize.assert_called_once()
    manager.clear_user_memories.assert_not_called()
    mock_db.upsert_user_memory.assert_not_called()
    mock_db.replace_user_memories.assert_called_once_with(user_id="user-1", memories=optimized_memories)
    assert result == optimized_memories
