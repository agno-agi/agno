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
# pytest libs/agno/tests/integration/db/surrealdb/test_surrealdb_knowledge.py
# ```

import time
from datetime import datetime

import pytest
from surrealdb import RecordID

from agno.db.schemas.knowledge import KnowledgeRow
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
    """Create a SurrealDB memory database for testing."""
    creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
    db = SurrealDb(None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE)
    return db


def test_crud_knowledge(db: SurrealDb):
    db.clear_knowledge()
    now = int(datetime.now().timestamp())

    # upsert
    new_kl = KnowledgeRow(name="name", description="description", created_at=now, updated_at=now)
    upserted_knowledge = db.upsert_knowledge_content(new_kl)
    assert upserted_knowledge is not None
    assert upserted_knowledge.id is not None
    # get
    knowledge = db.get_knowledge_content(upserted_knowledge.id)
    assert knowledge is not None
    # upsert another one
    new_kl_2 = KnowledgeRow(name="name 2", description="description")
    _upserted_knowledge_2 = db.upsert_knowledge_content(new_kl_2)
    # list
    # TODO: test pagination and sorting
    res, total = db.get_knowledge_contents()
    assert total == 2
    # delete
    _ = db.delete_knowledge_content(upserted_knowledge.id)
    # list
    res, total = db.get_knowledge_contents()
    assert total == 1


def test_knowledge_created_at_preserved_on_update(db: SurrealDb):
    """Test that knowledge created_at is preserved when updating."""
    db.clear_knowledge()

    now = int(datetime.now().timestamp())
    knowledge = KnowledgeRow(name="test_knowledge", description="original", created_at=now, updated_at=now)
    created = db.upsert_knowledge_content(knowledge)
    assert created is not None
    knowledge_id = created.id

    table = db._get_table("knowledge")
    record_id = RecordID(table, knowledge_id)
    raw_result = db._query_one("SELECT * FROM ONLY $record_id", {"record_id": record_id}, dict)
    assert raw_result is not None
    original_created_at = raw_result.get("created_at")
    original_updated_at = raw_result.get("updated_at")

    time.sleep(1.1)

    knowledge.id = knowledge_id
    knowledge.description = "updated description"
    db.upsert_knowledge_content(knowledge)

    raw_result = db._query_one("SELECT * FROM ONLY $record_id", {"record_id": record_id}, dict)
    assert raw_result is not None
    new_created_at = raw_result.get("created_at")
    new_updated_at = raw_result.get("updated_at")

    db.clear_knowledge()

    # created_at should not change on update
    assert original_created_at == new_created_at
    # updated_at should change on update
    assert original_updated_at != new_updated_at
