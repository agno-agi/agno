"""Memory writes and literal topic filtering behave consistently in SQLite adapters."""

from inspect import isawaitable

import pytest
import pytest_asyncio

from agno.db.schemas.memory import UserMemory
from agno.db.sqlite import AsyncSqliteDb, SqliteDb


async def _resolve(value):
    return await value if isawaitable(value) else value


@pytest_asyncio.fixture(params=[SqliteDb, AsyncSqliteDb], ids=["sync", "async"])
async def db(request):
    database = request.param(
        db_url="sqlite+aiosqlite:///:memory:" if request.param is AsyncSqliteDb else "sqlite:///:memory:"
    )
    try:
        yield database
    finally:
        await _resolve(database.close())


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True], ids=["single", "bulk"])
@pytest.mark.parametrize("deserialize", [False, True], ids=["raw", "objects"])
async def test_first_memory_write_creates_table(db, bulk, deserialize):
    # Reading a missing table before writing must not prevent its creation.
    assert await _resolve(db.get_user_memories(user_id="alice")) == []
    memories = [UserMemory(memory_id="m1", memory="Likes tea", user_id="alice", created_at=100, updated_at=200)]
    if bulk:
        memories.append(
            UserMemory(memory_id="m2", memory="Likes coffee", user_id="alice", created_at=100, updated_at=200)
        )
        results = await _resolve(db.upsert_memories(memories, deserialize=deserialize, preserve_updated_at=True))
    else:
        results = [await _resolve(db.upsert_user_memory(memories[0], deserialize=deserialize))]

    assert all(result is not None for result in results)
    assert {result.memory_id if deserialize else result["memory_id"] for result in results} == {
        memory.memory_id for memory in memories
    }
    stored = await _resolve(db.get_user_memories(user_id="alice"))
    assert {memory.memory for memory in stored} == {memory.memory for memory in memories}
    if bulk:
        assert all(memory.updated_at == 200 for memory in stored)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "topic,other_topic",
    [
        ("caf\u00e9", "cafe"),
        ('say "hello"', "hello"),
        ("50%", "50 percent"),
        ("a_b", "axb"),
        (r"a\b", "ab"),
        ("Work", "work"),
        ("", "nonempty"),
    ],
)
async def test_memory_topics_match_literal_json_array_values(db, topic, other_topic):
    await _resolve(
        db.upsert_memories(
            [
                UserMemory(memory_id="wanted", memory="One", user_id="alice", topics=[topic]),
                UserMemory(memory_id="unrelated", memory="Two", user_id="alice", topics=[other_topic]),
                UserMemory(memory_id="other-user", memory="Three", user_id="bob", topics=[topic]),
            ]
        )
    )

    memories = await _resolve(db.get_user_memories(user_id="alice", topics=[topic]))

    assert [memory.memory_id for memory in memories] == ["wanted"]


@pytest.mark.asyncio
async def test_topic_filters_require_all_topics_without_duplicating_rows(db):
    await _resolve(
        db.upsert_memories(
            [
                UserMemory(memory_id="both1", memory="One", user_id="alice", topics=["work", "python", "python"]),
                UserMemory(memory_id="both2", memory="Two", user_id="alice", topics=["python", "work"]),
                UserMemory(memory_id="work-only", memory="Three", user_id="alice", topics=["work"]),
                UserMemory(memory_id="python-only", memory="Four", user_id="alice", topics=["python"]),
                UserMemory(memory_id="empty", memory="Five", user_id="alice", topics=[]),
                UserMemory(memory_id="none", memory="Six", user_id="alice", topics=None),
                UserMemory(memory_id="other-user", memory="Seven", user_id="bob", topics=["work", "python"]),
            ]
        )
    )

    memories = await _resolve(db.get_user_memories(user_id="alice", topics=["work", "python"]))
    assert {memory.memory_id for memory in memories} == {"both1", "both2"}
    rows, count = await _resolve(
        db.get_user_memories(
            user_id="alice",
            topics=["work", "python"],
            deserialize=False,
            limit=1,
            page=1,
        )
    )
    assert len(rows) == 1
    assert count == 2
    assert len(await _resolve(db.get_user_memories(user_id="alice", topics=[]))) == 6
    assert await _resolve(db.get_user_memories(user_id="alice", topics=["work", "missing"])) == []
