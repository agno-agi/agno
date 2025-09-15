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
# pytest libs/agno/tests/integration/memory/test_memory_surrealdb.py
# ```

import pytest
from agno.memory.v2.db.schema import MemoryRow
from agno.memory.v2.db.surrealdb import SurrealMemoryDb

from agno.debug import enable_debug_mode

enable_debug_mode()

# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "test"
SURREALDB_DATABASE = "test"


@pytest.fixture
def memory_db():
    """Create a SurrealDB memory database for testing."""
    # client = Surreal(url=SURREALDB_URL)
    # client.signin({"username": SURREALDB_USER, "password": SURREALDB_PASSWORD})
    # client.use(namespace=SURREALDB_NAMESPACE, database=SURREALDB_DATABASE)
    client = build_client(SURREALDB_URL, SURREALDB_USER, SURREALDB_PASSWORD, SURREALDB_NAMESPACE, SURREALDB_DATABASE)
    db = SurrealMemoryDb(client=client)
    db.drop_table()
    db.create()
    return db


def test_table_exists(memory_db):
    assert memory_db.table_exists()


def test_crud_memory(memory_db):
    memory = MemoryRow(memory={"foo": 42}, user_id="martin")
    memory_db.upsert_memory(memory)
    memories = memory_db.read_memories()
    assert len(memories) == 1
    assert memories[0].memory == {"foo": 42}
    assert memories[0].user_id == "martin"
    assert memory_db.memory_exists(memories[0])

    memory_2 = MemoryRow(memory={"callsign": "spin"}, user_id="spensa")
    memory_db.upsert_memory(memory_2)

    memories = memory_db.read_memories()
    assert len(memories) == 2

    memories = memory_db.read_memories(user_id="martin")
    assert len(memories) == 1

    # upsert duplicate
    memory.memory["bar"] = 200
    memory_db.upsert_memory(memory)
    memories = memory_db.read_memories(user_id="martin")
    assert len(memories) == 1
    assert memories[0].memory == {"foo": 42, "bar": 200}

    # delete memory
    memory_db.delete_memory(memory.id)
    memories = memory_db.read_memories()
    assert len(memories) == 1
    assert memories[0].memory == {"callsign": "spin"}
    assert memories[0].user_id == "spensa"
