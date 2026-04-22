# Run SurrealDB in a container before running this script
#
# ```
# docker run --rm --pull always -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root
# ```
#
# or with
#
# ```
# surreal start -u root -p root
# ```
#
# Then, run this test like this:
#
# ```
# pytest libs/agno/tests/integration/db/surrealdb/test_surrealdb_context.py
# ```

import time
from datetime import datetime

import pytest
from surrealdb import RecordID

from agno.db.schemas.context import ContextItem
from agno.db.surrealdb import SurrealDb
from agno.debug import enable_debug_mode

enable_debug_mode()

# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "test"
SURREALDB_DATABASE = "test"


@pytest.fixture
def db() -> SurrealDb:
    """Create a SurrealDB database for testing."""
    creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
    db = SurrealDb(None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE)
    return db


def test_crud_context(db: SurrealDb):
    db.clear_context_items()
    now = int(datetime.now().timestamp())

    # upsert
    item = ContextItem(
        name="test_prompt",
        content="Hello {name}, you are a {role}",
        description="A test prompt",
        metadata={"env": "test"},
        variables=["name", "role"],
        version=1,
        created_at=now,
        updated_at=now,
    )
    upserted = db.upsert_context_item(item)
    assert upserted is not None
    assert upserted.id is not None

    # get
    fetched = db.get_context_item(upserted.id)
    assert fetched is not None
    assert isinstance(fetched, ContextItem)
    assert fetched.name == "test_prompt"
    assert fetched.description == "A test prompt"
    assert fetched.metadata == {"env": "test"}
    assert set(fetched.variables) == {"name", "role"}

    # get, unserialized
    raw = db.get_context_item(upserted.id, deserialize=False)
    assert isinstance(raw, dict)
    assert raw["name"] == "test_prompt"

    # upsert another
    item2 = ContextItem(name="second_prompt", content="Goodbye {user}", variables=["user"], created_at=now, updated_at=now)
    _upserted2 = db.upsert_context_item(item2)

    # list
    items = db.get_all_context_items()
    assert len(items) == 2

    # list with name filter
    items = db.get_all_context_items(name="test_prompt")
    assert len(items) == 1

    # list with metadata filter
    items = db.get_all_context_items(metadata={"env": "test"})
    assert len(items) == 1

    # update
    fetched.content = "Updated {name}"
    fetched.variables = ["name"]
    updated = db.upsert_context_item(fetched)
    assert updated is not None
    assert updated.content == "Updated {name}"

    # delete
    db.delete_context_item(upserted.id)
    deleted = db.get_context_item(upserted.id)
    assert deleted is None

    # list after delete
    items = db.get_all_context_items()
    assert len(items) == 1

    # clear
    db.clear_context_items()
    items = db.get_all_context_items()
    assert len(items) == 0


def test_context_created_at_preserved_on_update(db: SurrealDb):
    """Test that context created_at is preserved when updating."""
    db.clear_context_items()

    now = int(datetime.now().timestamp())
    item = ContextItem(
        name="timestamp_test",
        content="Original content",
        created_at=now,
        updated_at=now,
    )
    created = db.upsert_context_item(item)
    assert created is not None
    item_id = created.id

    table = db._get_table("context")
    record_id = RecordID(table, item_id)
    raw_result = db._query_one("SELECT * FROM ONLY $record_id", {"record_id": record_id}, dict)
    assert raw_result is not None
    original_created_at = raw_result.get("created_at")
    original_updated_at = raw_result.get("updated_at")

    time.sleep(1.1)

    created.content = "Updated content"
    db.upsert_context_item(created)

    raw_result = db._query_one("SELECT * FROM ONLY $record_id", {"record_id": record_id}, dict)
    assert raw_result is not None
    new_created_at = raw_result.get("created_at")
    new_updated_at = raw_result.get("updated_at")

    db.clear_context_items()

    # created_at should not change on update
    assert original_created_at == new_created_at
    # updated_at should change on update
    assert original_updated_at != new_updated_at
