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
# pytest libs/agno/tests/integration/db/surrealdb/test_surrealdb_memory.py
# ```

from datetime import datetime

import pytest

from agno.db.schemas.memory import UserMemory
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


def test_crud_memory(db: SurrealDb):
    now = datetime.now()
    new_mem = UserMemory(
        "Gavilar was Dalinar's brother and King of Alethkar",
        user_id="1",
        topics=["cosmere", "stormlight"],
        updated_at=now,
    )
    new_mem_2 = UserMemory("Reen was Vin's brother", user_id="2", topics=["cosmere", "mistborn"])
    new_mem_3 = UserMemory("Zeen was Spensa's father", user_id="2", topics=["cosmere", "skyward"])
    db.clear_memories()
    _mem = db.upsert_user_memory(new_mem)
    _last_mems = db.upsert_memories([new_mem_2, new_mem_3])
    stats, count = db.get_user_memory_stats()
    assert len(stats) == 2
    assert isinstance(stats[0]["last_memory_updated_at"], int)
    assert stats[0]["total_memories"] == 1
    assert stats[0]["user_id"] == "1"
    assert isinstance(stats[1]["last_memory_updated_at"], int)
    assert stats[1]["total_memories"] == 2
    assert stats[1]["user_id"] == "2"
    assert count == 2
    topics = db.get_all_memory_topics()
    assert set(topics) == set(["stormlight", "mistborn", "skyward", "cosmere"])
    user_mems, count = db.get_user_memories("1", deserialize=False)
    assert isinstance(user_mems, list)
    mem_id = user_mems[0].get("memory_id")
    assert mem_id
    user_mem = db.get_user_memory(mem_id)
    assert isinstance(user_mem, UserMemory)
    assert user_mem.user_id == "1"
    db.delete_user_memory(mem_id)
    user_mems, count = db.get_user_memories("1", deserialize=False)
    assert count == 0
    user_mems = db.get_user_memories("2")
    assert isinstance(user_mems, list)
    db.delete_user_memories([x.memory_id for x in user_mems if x.memory_id is not None])
    list_ = db.get_user_memories("2")
    assert len(list_) == 0
