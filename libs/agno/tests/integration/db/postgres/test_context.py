"""Integration tests for the Context related methods of the PostgresDb class"""

import time
from datetime import datetime

import pytest

from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.context import ContextItem


@pytest.fixture(autouse=True)
def cleanup_context(postgres_db_real: PostgresDb):
    """Fixture to clean-up context rows after each test"""
    yield

    with postgres_db_real.Session() as session:
        try:
            context_table = postgres_db_real._get_table("context")
            session.execute(context_table.delete())
            session.commit()
        except Exception:
            session.rollback()


@pytest.fixture
def sample_context_item() -> ContextItem:
    """Fixture returning a sample ContextItem"""
    now = int(datetime.now().timestamp())
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


def test_upsert_context_item(postgres_db_real: PostgresDb, sample_context_item: ContextItem):
    """Ensure upsert_context_item inserts a new context item correctly"""
    result = postgres_db_real.upsert_context_item(sample_context_item)

    assert result is not None
    assert isinstance(result, ContextItem)
    assert result.id is not None
    assert result.name == sample_context_item.name
    assert result.content == sample_context_item.content
    assert result.description == sample_context_item.description
    assert result.metadata == sample_context_item.metadata
    assert set(result.variables) == set(sample_context_item.variables)


def test_update_context_item(postgres_db_real: PostgresDb, sample_context_item: ContextItem):
    """Ensure upsert_context_item updates an existing context item correctly"""
    created = postgres_db_real.upsert_context_item(sample_context_item)
    assert created is not None

    created.content = "Updated: Hello {name}"
    created.variables = ["name"]
    created.description = "Updated description"

    result = postgres_db_real.upsert_context_item(created)

    assert result is not None
    assert isinstance(result, ContextItem)
    assert result.content == "Updated: Hello {name}"
    assert result.variables == ["name"]
    assert result.description == "Updated description"


def test_get_context_item_by_id(postgres_db_real: PostgresDb, sample_context_item: ContextItem):
    """Ensure get_context_item returns a ContextItem by ID"""
    created = postgres_db_real.upsert_context_item(sample_context_item)
    assert created is not None

    result = postgres_db_real.get_context_item(id=created.id)

    assert result is not None
    assert isinstance(result, ContextItem)
    assert result.id == created.id
    assert result.name == "test_prompt"
    assert result.content == "Hello {name}, you are a {role}"


def test_get_context_item_nonexistent(postgres_db_real: PostgresDb):
    """Ensure get_context_item returns None for nonexistent item"""
    result = postgres_db_real.get_context_item(id="nonexistent_id")
    assert result is None


def test_get_all_context_items(postgres_db_real: PostgresDb):
    """Ensure get_all_context_items returns all items"""
    now = int(datetime.now().timestamp())

    postgres_db_real.upsert_context_item(
        ContextItem(name="prompt_1", content="First prompt", created_at=now, updated_at=now)
    )
    postgres_db_real.upsert_context_item(
        ContextItem(name="prompt_2", content="Second prompt", created_at=now, updated_at=now)
    )
    postgres_db_real.upsert_context_item(
        ContextItem(name="prompt_3", content="Third prompt", created_at=now, updated_at=now)
    )

    items = postgres_db_real.get_all_context_items()
    assert items is not None
    assert len(items) == 3


def test_get_all_context_items_with_name_filter(postgres_db_real: PostgresDb):
    """Ensure get_all_context_items filters by name correctly"""
    now = int(datetime.now().timestamp())

    postgres_db_real.upsert_context_item(
        ContextItem(name="greeting", content="Hello {name}", created_at=now, updated_at=now)
    )
    postgres_db_real.upsert_context_item(
        ContextItem(name="farewell", content="Goodbye {name}", created_at=now, updated_at=now)
    )

    items = postgres_db_real.get_all_context_items(name="greeting")
    assert items is not None
    assert len(items) == 1
    assert items[0].name == "greeting"
    assert items[0].content == "Hello {name}"


def test_get_all_context_items_with_metadata_filter(postgres_db_real: PostgresDb):
    """Ensure get_all_context_items filters by metadata correctly"""
    now = int(datetime.now().timestamp())

    postgres_db_real.upsert_context_item(
        ContextItem(name="prod_prompt", content="Production", metadata={"env": "prod"}, created_at=now, updated_at=now)
    )
    postgres_db_real.upsert_context_item(
        ContextItem(name="test_prompt", content="Testing", metadata={"env": "test"}, created_at=now, updated_at=now)
    )

    items = postgres_db_real.get_all_context_items(metadata={"env": "prod"})
    assert items is not None
    assert len(items) == 1
    assert items[0].name == "prod_prompt"


def test_get_all_context_items_no_matches(postgres_db_real: PostgresDb):
    """Ensure get_all_context_items returns empty list when no matches"""
    items = postgres_db_real.get_all_context_items(name="nonexistent")
    assert items is not None
    assert len(items) == 0


def test_delete_context_item(postgres_db_real: PostgresDb, sample_context_item: ContextItem):
    """Ensure delete_context_item deletes the context item"""
    created = postgres_db_real.upsert_context_item(sample_context_item)
    assert created is not None

    # Verify item exists
    item = postgres_db_real.get_context_item(created.id)
    assert item is not None

    # Delete the item
    postgres_db_real.delete_context_item(created.id)

    # Verify item is deleted
    item = postgres_db_real.get_context_item(created.id)
    assert item is None


def test_delete_one_of_many(postgres_db_real: PostgresDb):
    """Ensure deleting one context item does not affect others"""
    now = int(datetime.now().timestamp())

    item1 = postgres_db_real.upsert_context_item(
        ContextItem(name="keep_this", content="Keep", created_at=now, updated_at=now)
    )
    item2 = postgres_db_real.upsert_context_item(
        ContextItem(name="delete_this", content="Delete", created_at=now, updated_at=now)
    )
    assert item1 is not None
    assert item2 is not None

    # Delete item2
    postgres_db_real.delete_context_item(item2.id)

    # Verify item2 is gone
    assert postgres_db_real.get_context_item(item2.id) is None

    # Verify item1 still exists
    remaining = postgres_db_real.get_context_item(item1.id)
    assert remaining is not None
    assert remaining.name == "keep_this"


def test_clear_context_items(postgres_db_real: PostgresDb):
    """Ensure clear_context_items removes all items"""
    now = int(datetime.now().timestamp())

    postgres_db_real.upsert_context_item(ContextItem(name="prompt_1", content="First", created_at=now, updated_at=now))
    postgres_db_real.upsert_context_item(ContextItem(name="prompt_2", content="Second", created_at=now, updated_at=now))

    postgres_db_real.clear_context_items()

    items = postgres_db_real.get_all_context_items()
    assert items is not None
    assert len(items) == 0


def test_clear_empty_context(postgres_db_real: PostgresDb):
    """Ensure clear_context_items on empty table does not raise"""
    postgres_db_real.clear_context_items()

    items = postgres_db_real.get_all_context_items()
    assert items is not None
    assert len(items) == 0


def test_context_created_at_preserved_on_update(postgres_db_real: PostgresDb):
    """Ensure created_at is preserved when updating a context item"""
    now = int(datetime.now().timestamp())
    item = ContextItem(
        name="timestamp_test",
        content="Original content",
        created_at=now,
        updated_at=now,
    )
    created = postgres_db_real.upsert_context_item(item)
    assert created is not None
    original_created_at = created.created_at

    time.sleep(1.1)

    # Update content
    created.content = "Updated content"
    updated = postgres_db_real.upsert_context_item(created)
    assert updated is not None

    assert updated.created_at == original_created_at
    assert updated.updated_at != original_created_at


def test_comprehensive_context_item_fields(postgres_db_real: PostgresDb):
    """Ensure all ContextItem fields are properly handled"""
    now = int(datetime.now().timestamp())
    item = ContextItem(
        name="comprehensive_prompt",
        content="Hello {name}, welcome to {place}",
        description="A comprehensive test prompt with all fields",
        metadata={"env": "test", "team": "engineering", "priority": "high"},
        variables=["name", "place"],
        version=3,
        parent_id="parent_456",
        optimization_notes="Optimized for clarity and brevity",
        created_at=now,
        updated_at=now,
    )

    result = postgres_db_real.upsert_context_item(item)
    assert result is not None

    # Retrieve and verify all fields
    retrieved = postgres_db_real.get_context_item(result.id)

    assert retrieved is not None and isinstance(retrieved, ContextItem)
    assert retrieved.name == "comprehensive_prompt"
    assert retrieved.content == "Hello {name}, welcome to {place}"
    assert retrieved.description == "A comprehensive test prompt with all fields"
    assert retrieved.metadata == {"env": "test", "team": "engineering", "priority": "high"}
    assert set(retrieved.variables) == {"name", "place"}
    assert retrieved.version == 3
    assert retrieved.parent_id == "parent_456"
    assert retrieved.optimization_notes == "Optimized for clarity and brevity"
