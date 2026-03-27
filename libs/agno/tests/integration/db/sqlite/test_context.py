"""Integration tests for the Context related methods of the SqliteDb class"""

from datetime import datetime

import pytest

from agno.db.schemas.context import ContextItem
from agno.db.sqlite.sqlite import SqliteDb


@pytest.fixture(autouse=True)
def cleanup_context(sqlite_db_real: SqliteDb):
    """Fixture to clean-up context rows after each test"""
    yield

    with sqlite_db_real.Session() as session:
        try:
            context_table = sqlite_db_real._get_table("context")
            if context_table is not None:
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
        description="A test prompt",
        metadata={"env": "test"},
        variables=["name", "role"],
        version=1,
        created_at=now,
        updated_at=now,
    )


def test_upsert_context_item(sqlite_db_real: SqliteDb, sample_context_item: ContextItem):
    """Ensure upsert_context_item inserts a new context item correctly"""
    result = sqlite_db_real.upsert_context_item(sample_context_item)

    assert result is not None
    assert isinstance(result, ContextItem)
    assert result.id is not None
    assert result.name == sample_context_item.name
    assert result.content == sample_context_item.content
    assert result.description == sample_context_item.description
    assert result.metadata == sample_context_item.metadata
    assert set(result.variables) == set(sample_context_item.variables)


def test_get_context_item(sqlite_db_real: SqliteDb, sample_context_item: ContextItem):
    """Ensure get_context_item returns a ContextItem"""
    created = sqlite_db_real.upsert_context_item(sample_context_item)
    assert created is not None

    result = sqlite_db_real.get_context_item(created.id)

    assert result is not None
    assert isinstance(result, ContextItem)
    assert result.name == "test_prompt"
    assert result.content == "Hello {name}, you are a {role}"


def test_get_context_item_nonexistent(sqlite_db_real: SqliteDb):
    """Ensure get_context_item returns None for nonexistent item"""
    result = sqlite_db_real.get_context_item("nonexistent_id")
    assert result is None


def test_get_all_context_items(sqlite_db_real: SqliteDb):
    """Ensure get_all_context_items returns all items"""
    now = int(datetime.now().timestamp())

    sqlite_db_real.upsert_context_item(
        ContextItem(name="prompt_1", content="First prompt", created_at=now, updated_at=now)
    )
    sqlite_db_real.upsert_context_item(
        ContextItem(name="prompt_2", content="Second prompt", created_at=now, updated_at=now)
    )

    items = sqlite_db_real.get_all_context_items()
    assert items is not None
    assert len(items) == 2


def test_get_all_context_items_with_name_filter(sqlite_db_real: SqliteDb):
    """Ensure get_all_context_items filters by name"""
    now = int(datetime.now().timestamp())

    sqlite_db_real.upsert_context_item(
        ContextItem(name="prompt_1", content="First prompt", created_at=now, updated_at=now)
    )
    sqlite_db_real.upsert_context_item(
        ContextItem(name="prompt_2", content="Second prompt", created_at=now, updated_at=now)
    )

    items = sqlite_db_real.get_all_context_items(name="prompt_1")
    assert items is not None
    assert len(items) == 1
    assert items[0].name == "prompt_1"


def test_get_all_context_items_with_metadata_filter(sqlite_db_real: SqliteDb):
    """Ensure get_all_context_items filters by metadata"""
    now = int(datetime.now().timestamp())

    sqlite_db_real.upsert_context_item(
        ContextItem(name="prompt_1", content="First", metadata={"env": "prod"}, created_at=now, updated_at=now)
    )
    sqlite_db_real.upsert_context_item(
        ContextItem(name="prompt_2", content="Second", metadata={"env": "test"}, created_at=now, updated_at=now)
    )

    items = sqlite_db_real.get_all_context_items(metadata={"env": "prod"})
    assert items is not None
    assert len(items) == 1
    assert items[0].name == "prompt_1"


def test_update_context_item(sqlite_db_real: SqliteDb, sample_context_item: ContextItem):
    """Ensure upsert_context_item updates an existing context item correctly"""
    created = sqlite_db_real.upsert_context_item(sample_context_item)
    assert created is not None

    # Update fields
    created.content = "Updated {name}"
    created.variables = ["name"]
    result = sqlite_db_real.upsert_context_item(created)

    assert result is not None
    assert result.content == "Updated {name}"
    assert result.variables == ["name"]


def test_delete_context_item(sqlite_db_real: SqliteDb, sample_context_item: ContextItem):
    """Ensure delete_context_item deletes the context item"""
    created = sqlite_db_real.upsert_context_item(sample_context_item)
    assert created is not None

    # Verify item exists
    item = sqlite_db_real.get_context_item(created.id)
    assert item is not None

    # Delete the item
    sqlite_db_real.delete_context_item(created.id)

    # Verify item is deleted
    item = sqlite_db_real.get_context_item(created.id)
    assert item is None


def test_delete_one_of_many(sqlite_db_real: SqliteDb):
    """Ensure deleting one item does not affect others"""
    now = int(datetime.now().timestamp())

    item1 = sqlite_db_real.upsert_context_item(
        ContextItem(name="prompt_1", content="First", created_at=now, updated_at=now)
    )
    item2 = sqlite_db_real.upsert_context_item(
        ContextItem(name="prompt_2", content="Second", created_at=now, updated_at=now)
    )
    assert item1 is not None
    assert item2 is not None

    sqlite_db_real.delete_context_item(item1.id)

    # Verify item1 is gone
    assert sqlite_db_real.get_context_item(item1.id) is None

    # Verify item2 still exists
    assert sqlite_db_real.get_context_item(item2.id) is not None


def test_clear_context_items(sqlite_db_real: SqliteDb):
    """Ensure clear_context_items removes all items"""
    now = int(datetime.now().timestamp())

    sqlite_db_real.upsert_context_item(ContextItem(name="prompt_1", content="First", created_at=now, updated_at=now))
    sqlite_db_real.upsert_context_item(ContextItem(name="prompt_2", content="Second", created_at=now, updated_at=now))

    sqlite_db_real.clear_context_items()

    items = sqlite_db_real.get_all_context_items()
    assert items is not None
    assert len(items) == 0


def test_comprehensive_context_item_fields(sqlite_db_real: SqliteDb):
    """Ensure all ContextItem fields are properly handled"""
    now = int(datetime.now().timestamp())
    item = ContextItem(
        name="comprehensive_prompt",
        content="Hello {name}, welcome to {place}",
        description="A comprehensive test prompt",
        metadata={"env": "test", "team": "engineering"},
        variables=["name", "place"],
        version=2,
        parent_id="parent_123",
        optimization_notes="Optimized for clarity",
        created_at=now,
        updated_at=now,
    )

    result = sqlite_db_real.upsert_context_item(item)
    assert result is not None

    # Retrieve and verify all fields
    retrieved = sqlite_db_real.get_context_item(result.id)
    assert retrieved is not None
    assert retrieved.name == "comprehensive_prompt"
    assert retrieved.content == "Hello {name}, welcome to {place}"
    assert retrieved.description == "A comprehensive test prompt"
    assert retrieved.metadata == {"env": "test", "team": "engineering"}
    assert set(retrieved.variables) == {"name", "place"}
    assert retrieved.version == 2
    assert retrieved.parent_id == "parent_123"
    assert retrieved.optimization_notes == "Optimized for clarity"
