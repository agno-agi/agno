"""Integration tests for the Context related methods of the AsyncMongoDb class

Required to have a running MongoDB instance to run these tests.

These tests assume:
- Username=mongoadmin
- Password=secret
"""

import time

import pytest

try:
    from agno.db.mongo import AsyncMongoDb  # noqa: F401
except ImportError:
    pytest.skip(
        "Neither motor nor pymongo async installed, skipping AsyncMongoDb context integration tests",
        allow_module_level=True,
    )

from agno.db.schemas.context import ContextItem


@pytest.mark.asyncio
async def test_upsert_and_get_context_item(async_mongo_db_real):
    """Test upserting and retrieving a context item"""
    now = int(time.time())
    item = ContextItem(
        name="test_prompt",
        content="Hello {name}, you are a {role}",
        description="A test prompt",
        metadata={"env": "test"},
        variables=["name", "role"],
        created_at=now,
        updated_at=now,
    )

    # Upsert
    result = await async_mongo_db_real.upsert_context_item(item)
    assert result is not None
    assert result.id is not None
    assert result.name == "test_prompt"

    # Get it back
    retrieved = await async_mongo_db_real.get_context_item(result.id)
    assert retrieved is not None
    assert retrieved.name == "test_prompt"
    assert retrieved.content == "Hello {name}, you are a {role}"
    assert retrieved.metadata == {"env": "test"}


@pytest.mark.asyncio
async def test_update_context_item(async_mongo_db_real):
    """Test updating an existing context item"""
    now = int(time.time())
    item = ContextItem(
        name="update_test",
        content="Original {value}",
        variables=["value"],
        created_at=now,
        updated_at=now,
    )

    created = await async_mongo_db_real.upsert_context_item(item)
    assert created is not None

    # Update
    created.content = "Updated {value}"
    created.description = "Now with description"
    updated = await async_mongo_db_real.upsert_context_item(created)

    assert updated is not None
    assert updated.content == "Updated {value}"
    assert updated.description == "Now with description"


@pytest.mark.asyncio
async def test_get_context_item_nonexistent(async_mongo_db_real):
    """Test getting a nonexistent context item returns None"""
    result = await async_mongo_db_real.get_context_item("nonexistent_id")
    assert result is None


@pytest.mark.asyncio
async def test_get_all_context_items(async_mongo_db_real):
    """Test getting all context items"""
    now = int(time.time())

    for i in range(3):
        await async_mongo_db_real.upsert_context_item(
            ContextItem(name=f"prompt_{i}", content=f"Content {i}", created_at=now, updated_at=now)
        )

    items = await async_mongo_db_real.get_all_context_items()
    assert items is not None
    assert len(items) >= 3


@pytest.mark.asyncio
async def test_get_all_context_items_with_name_filter(async_mongo_db_real):
    """Test getting context items filtered by name"""
    now = int(time.time())

    await async_mongo_db_real.upsert_context_item(
        ContextItem(name="greeting", content="Hello", created_at=now, updated_at=now)
    )
    await async_mongo_db_real.upsert_context_item(
        ContextItem(name="farewell", content="Goodbye", created_at=now, updated_at=now)
    )

    items = await async_mongo_db_real.get_all_context_items(name="greeting")
    assert items is not None
    assert len(items) >= 1
    assert all(item.name == "greeting" for item in items)


@pytest.mark.asyncio
async def test_get_all_context_items_with_metadata_filter(async_mongo_db_real):
    """Test getting context items filtered by metadata"""
    now = int(time.time())

    await async_mongo_db_real.upsert_context_item(
        ContextItem(name="prod_prompt", content="Production", metadata={"env": "prod"}, created_at=now, updated_at=now)
    )
    await async_mongo_db_real.upsert_context_item(
        ContextItem(name="test_prompt", content="Testing", metadata={"env": "test"}, created_at=now, updated_at=now)
    )

    items = await async_mongo_db_real.get_all_context_items(metadata={"env": "prod"})
    assert items is not None
    assert len(items) >= 1
    assert all(item.metadata.get("env") == "prod" for item in items)


@pytest.mark.asyncio
async def test_delete_context_item(async_mongo_db_real):
    """Test deleting a context item"""
    now = int(time.time())
    item = ContextItem(
        name="delete_test",
        content="This will be deleted",
        created_at=now,
        updated_at=now,
    )

    created = await async_mongo_db_real.upsert_context_item(item)
    assert created is not None

    # Delete it
    await async_mongo_db_real.delete_context_item(created.id)

    # Verify it is gone
    retrieved = await async_mongo_db_real.get_context_item(created.id)
    assert retrieved is None


@pytest.mark.asyncio
async def test_clear_context_items(async_mongo_db_real):
    """Test clearing all context items"""
    now = int(time.time())

    await async_mongo_db_real.upsert_context_item(
        ContextItem(name="prompt_1", content="First", created_at=now, updated_at=now)
    )
    await async_mongo_db_real.upsert_context_item(
        ContextItem(name="prompt_2", content="Second", created_at=now, updated_at=now)
    )

    await async_mongo_db_real.clear_context_items()

    items = await async_mongo_db_real.get_all_context_items()
    assert items is not None
    assert len(items) == 0


@pytest.mark.asyncio
async def test_comprehensive_context_item_fields(async_mongo_db_real):
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

    created = await async_mongo_db_real.upsert_context_item(item)
    assert created is not None

    retrieved = await async_mongo_db_real.get_context_item(created.id)

    assert retrieved is not None
    assert retrieved.name == "comprehensive_prompt"
    assert retrieved.content == "Hello {name}, welcome to {place}"
    assert retrieved.description == "A comprehensive test prompt"
    assert retrieved.metadata == {"env": "test", "team": "engineering"}
    assert set(retrieved.variables) == {"name", "place"}
    assert retrieved.version == 3
    assert retrieved.parent_id == "parent_456"
    assert retrieved.optimization_notes == "Optimized for clarity"
