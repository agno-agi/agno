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

from datetime import datetime

import pytest

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
