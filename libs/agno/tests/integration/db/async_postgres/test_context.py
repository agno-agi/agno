"""Integration tests for the Context related methods of the AsyncPostgresDb class"""

import time

import pytest
import pytest_asyncio

from agno.db.postgres import AsyncPostgresDb
from agno.db.schemas.context import ContextItem


@pytest_asyncio.fixture(autouse=True)
async def cleanup_context(async_postgres_db_real: AsyncPostgresDb):
    """Fixture to clean-up context rows after each test"""
    yield

    try:
        context_table = await async_postgres_db_real._get_table("context")
        async with async_postgres_db_real.async_session_factory() as session:
            await session.execute(context_table.delete())
            await session.commit()
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture
def sample_context_item() -> ContextItem:
    """Fixture returning a sample ContextItem"""
    now = int(time.time())
    return ContextItem(
        name="test_prompt",
        content="Hello {name}, you are a {role}",
        description="A test prompt template",
        metadata={"env": "test", "team": "engineering"},
        variables=["name", "role"],
        version=1,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_upsert_context_item(async_postgres_db_real: AsyncPostgresDb, sample_context_item: ContextItem):
    """Test upserting a context item"""
    result = await async_postgres_db_real.upsert_context_item(sample_context_item)

    assert result is not None
    assert isinstance(result, ContextItem)
    assert result.id is not None
    assert result.name == "test_prompt"
    assert result.content == "Hello {name}, you are a {role}"
    assert result.metadata == {"env": "test", "team": "engineering"}

    # Update the item
    result.content = "Updated: Hi {name}"
    result.variables = ["name"]
    updated = await async_postgres_db_real.upsert_context_item(result)

    assert updated is not None
    assert updated.content == "Updated: Hi {name}"
    assert updated.variables == ["name"]


@pytest.mark.asyncio
async def test_get_context_item(async_postgres_db_real: AsyncPostgresDb, sample_context_item: ContextItem):
    """Test getting a single context item"""
    created = await async_postgres_db_real.upsert_context_item(sample_context_item)
    assert created is not None

    result = await async_postgres_db_real.get_context_item(created.id)

    assert result is not None
    assert isinstance(result, ContextItem)
    assert result.id == created.id
    assert result.name == "test_prompt"
    assert result.content == "Hello {name}, you are a {role}"


@pytest.mark.asyncio
async def test_get_context_item_nonexistent(async_postgres_db_real: AsyncPostgresDb):
    """Test getting a nonexistent context item returns None"""
    result = await async_postgres_db_real.get_context_item("nonexistent_id")
    assert result is None


@pytest.mark.asyncio
async def test_get_all_context_items(async_postgres_db_real: AsyncPostgresDb):
    """Test getting all context items"""
    now = int(time.time())

    for i in range(3):
        await async_postgres_db_real.upsert_context_item(
            ContextItem(name=f"prompt_{i}", content=f"Content {i}", created_at=now, updated_at=now)
        )

    items = await async_postgres_db_real.get_all_context_items()
    assert items is not None
    assert len(items) == 3


@pytest.mark.asyncio
async def test_get_all_context_items_with_name_filter(async_postgres_db_real: AsyncPostgresDb):
    """Test getting context items filtered by name"""
    now = int(time.time())

    await async_postgres_db_real.upsert_context_item(
        ContextItem(name="greeting", content="Hello {name}", created_at=now, updated_at=now)
    )
    await async_postgres_db_real.upsert_context_item(
        ContextItem(name="farewell", content="Goodbye {name}", created_at=now, updated_at=now)
    )

    items = await async_postgres_db_real.get_all_context_items(name="greeting")
    assert items is not None
    assert len(items) == 1
    assert items[0].name == "greeting"


@pytest.mark.asyncio
async def test_get_all_context_items_with_metadata_filter(async_postgres_db_real: AsyncPostgresDb):
    """Test getting context items filtered by metadata"""
    now = int(time.time())

    await async_postgres_db_real.upsert_context_item(
        ContextItem(name="prod_prompt", content="Production", metadata={"env": "prod"}, created_at=now, updated_at=now)
    )
    await async_postgres_db_real.upsert_context_item(
        ContextItem(name="test_prompt", content="Testing", metadata={"env": "test"}, created_at=now, updated_at=now)
    )

    items = await async_postgres_db_real.get_all_context_items(metadata={"env": "prod"})
    assert items is not None
    assert len(items) == 1
    assert items[0].name == "prod_prompt"


@pytest.mark.asyncio
async def test_delete_context_item(async_postgres_db_real: AsyncPostgresDb, sample_context_item: ContextItem):
    """Test deleting a context item"""
    created = await async_postgres_db_real.upsert_context_item(sample_context_item)
    assert created is not None

    # Verify it exists
    result = await async_postgres_db_real.get_context_item(created.id)
    assert result is not None

    # Delete it
    await async_postgres_db_real.delete_context_item(created.id)

    # Verify it is gone
    result = await async_postgres_db_real.get_context_item(created.id)
    assert result is None


@pytest.mark.asyncio
async def test_delete_one_of_many(async_postgres_db_real: AsyncPostgresDb):
    """Test deleting one context item does not affect others"""
    now = int(time.time())

    item1 = await async_postgres_db_real.upsert_context_item(
        ContextItem(name="keep_this", content="Keep", created_at=now, updated_at=now)
    )
    item2 = await async_postgres_db_real.upsert_context_item(
        ContextItem(name="delete_this", content="Delete", created_at=now, updated_at=now)
    )
    assert item1 is not None
    assert item2 is not None

    await async_postgres_db_real.delete_context_item(item2.id)

    # Verify item2 is gone
    assert await async_postgres_db_real.get_context_item(item2.id) is None

    # Verify item1 still exists
    remaining = await async_postgres_db_real.get_context_item(item1.id)
    assert remaining is not None
    assert remaining.name == "keep_this"


@pytest.mark.asyncio
async def test_clear_context_items(async_postgres_db_real: AsyncPostgresDb):
    """Test clearing all context items"""
    now = int(time.time())

    await async_postgres_db_real.upsert_context_item(
        ContextItem(name="prompt_1", content="First", created_at=now, updated_at=now)
    )
    await async_postgres_db_real.upsert_context_item(
        ContextItem(name="prompt_2", content="Second", created_at=now, updated_at=now)
    )

    # Verify items exist
    items = await async_postgres_db_real.get_all_context_items()
    assert len(items) == 2

    # Clear all
    await async_postgres_db_real.clear_context_items()

    # Verify all gone
    items = await async_postgres_db_real.get_all_context_items()
    assert items is not None
    assert len(items) == 0


@pytest.mark.asyncio
async def test_context_created_at_preserved_on_update(async_postgres_db_real: AsyncPostgresDb):
    """Test that created_at is preserved when updating a context item"""
    now = int(time.time())
    item = ContextItem(
        name="timestamp_test",
        content="Original content",
        created_at=now,
        updated_at=now,
    )
    created = await async_postgres_db_real.upsert_context_item(item)
    assert created is not None
    original_created_at = created.created_at

    time.sleep(1.1)

    created.content = "Updated content"
    updated = await async_postgres_db_real.upsert_context_item(created)
    assert updated is not None

    assert updated.created_at == original_created_at
    assert updated.updated_at != original_created_at


@pytest.mark.asyncio
async def test_comprehensive_context_item_fields(async_postgres_db_real: AsyncPostgresDb):
    """Test all ContextItem fields are properly handled"""
    now = int(time.time())
    item = ContextItem(
        name="comprehensive_prompt",
        content="Hello {name}, welcome to {place}",
        description="A comprehensive test prompt",
        metadata={"env": "test", "team": "engineering"},
        variables=["name", "place"],
        version=3,
        parent_id="parent_456",
        optimization_notes="Optimized for clarity",
        created_at=now,
        updated_at=now,
    )

    created = await async_postgres_db_real.upsert_context_item(item)
    assert created is not None

    retrieved = await async_postgres_db_real.get_context_item(created.id)

    assert retrieved is not None
    assert retrieved.name == "comprehensive_prompt"
    assert retrieved.content == "Hello {name}, welcome to {place}"
    assert retrieved.description == "A comprehensive test prompt"
    assert retrieved.metadata == {"env": "test", "team": "engineering"}
    assert set(retrieved.variables) == {"name", "place"}
    assert retrieved.version == 3
    assert retrieved.parent_id == "parent_456"
    assert retrieved.optimization_notes == "Optimized for clarity"
