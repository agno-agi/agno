import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.db.redis import AsyncRedisDb


@pytest.fixture
def make_mock_client():
    def _factory(scan_keys=None):
        client = MagicMock()
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock(return_value=True)
        client.delete = AsyncMock(return_value=1)
        client.sadd = AsyncMock(return_value=1)
        client.srem = AsyncMock(return_value=1)
        client.aclose = AsyncMock(return_value=None)
        client.scan_iter.return_value.__aiter__.return_value = scan_keys or []
        return client

    return _factory


@pytest.fixture
def mock_client(make_mock_client):
    return make_mock_client()


@pytest.fixture
def db(mock_client):
    return AsyncRedisDb(redis_client=mock_client)


def test_init_with_url():
    db = AsyncRedisDb(db_url="redis://localhost:6379")
    assert db.redis_client is not None
    assert db.db_prefix == "agno"


def test_init_with_client(mock_client):
    db = AsyncRedisDb(redis_client=mock_client)
    assert db.redis_client is mock_client


def test_init_requires_url_or_client():
    with pytest.raises(ValueError, match="One of redis_client or db_url must be provided"):
        AsyncRedisDb()


def test_id_is_deterministic():
    db1 = AsyncRedisDb(db_url="redis://localhost:6379")
    db2 = AsyncRedisDb(db_url="redis://localhost:6379")
    assert db1.id == db2.id


def test_id_differs_with_prefix():
    db1 = AsyncRedisDb(db_url="redis://localhost:6379", db_prefix="agno")
    db2 = AsyncRedisDb(db_url="redis://localhost:6379", db_prefix="other")
    assert db1.id != db2.id


def test_table_names_propagated():
    db = AsyncRedisDb(
        db_url="redis://localhost:6379",
        session_table="my_sessions",
        memory_table="my_memories",
        metrics_table="my_metrics",
        eval_table="my_evals",
        knowledge_table="my_knowledge",
        culture_table="my_culture",
        traces_table="my_traces",
        spans_table="my_spans",
    )
    assert db.session_table_name == "my_sessions"
    assert db.memory_table_name == "my_memories"
    assert db.metrics_table_name == "my_metrics"
    assert db.eval_table_name == "my_evals"
    assert db.knowledge_table_name == "my_knowledge"
    assert db.culture_table_name == "my_culture"
    assert db.trace_table_name == "my_traces"
    assert db.span_table_name == "my_spans"


@pytest.mark.asyncio
async def test_table_exists_always_true(db):
    assert await db.table_exists("anything") is True


@pytest.mark.asyncio
async def test_schema_version_methods_are_noops(db):
    assert await db.get_latest_schema_version("agno_sessions") is None
    assert await db.upsert_schema_version("agno_sessions", "1.0.0") is None


@pytest.mark.asyncio
async def test_store_record_writes_serialized_payload_and_indexes(mock_client):
    db = AsyncRedisDb(redis_client=mock_client, db_prefix="agno", expire=42)

    ok = await db._store_record(
        table_type="sessions",
        record_id="s1",
        data={"session_id": "s1", "user_id": "u1"},
        index_fields=["user_id"],
    )
    assert ok is True

    mock_client.set.assert_awaited_once()
    args, kwargs = mock_client.set.call_args
    assert args[0] == "agno:sessions:s1"
    assert json.loads(args[1]) == {"session_id": "s1", "user_id": "u1"}
    assert kwargs["ex"] == 42
    mock_client.sadd.assert_awaited_once_with("agno:sessions:index:user_id:u1", "s1")


@pytest.mark.asyncio
async def test_store_record_returns_false_on_client_failure(db, mock_client):
    mock_client.set.side_effect = RuntimeError("boom")
    assert await db._store_record("sessions", "s1", {"session_id": "s1"}) is False


@pytest.mark.asyncio
async def test_get_record_returns_none_when_missing(db, mock_client):
    mock_client.get.return_value = None
    assert await db._get_record("sessions", "missing") is None


@pytest.mark.asyncio
async def test_get_record_deserializes_payload(db, mock_client):
    mock_client.get.return_value = json.dumps({"session_id": "s1", "user_id": "u1"})
    assert await db._get_record("sessions", "s1") == {"session_id": "s1", "user_id": "u1"}
    mock_client.get.assert_awaited_once_with("agno:sessions:s1")


@pytest.mark.asyncio
async def test_delete_record_removes_indexes_then_key(db, mock_client):
    mock_client.get.return_value = json.dumps({"session_id": "s1", "user_id": "u1"})
    mock_client.delete.return_value = 1

    ok = await db._delete_record("sessions", "s1", index_fields=["user_id"])
    assert ok is True
    mock_client.srem.assert_awaited_once_with("agno:sessions:index:user_id:u1", "s1")
    mock_client.delete.assert_awaited_once_with("agno:sessions:s1")


@pytest.mark.asyncio
async def test_delete_record_returns_false_when_nothing_to_delete(db, mock_client):
    mock_client.get.return_value = None
    mock_client.delete.return_value = 0
    assert await db._delete_record("sessions", "missing") is False


@pytest.mark.asyncio
async def test_get_all_records_skips_index_keys(make_mock_client):
    client = make_mock_client(
        scan_keys=[
            "agno:sessions:s1",
            "agno:sessions:index:user_id:u1",
            "agno:sessions:s2",
        ]
    )
    client.get.side_effect = [
        json.dumps({"session_id": "s1"}),
        json.dumps({"session_id": "s2"}),
    ]
    db = AsyncRedisDb(redis_client=client)
    records = await db._get_all_records("sessions")
    assert records == [{"session_id": "s1"}, {"session_id": "s2"}]


@pytest.mark.asyncio
async def test_delete_session_returns_false_when_user_id_mismatch(db, mock_client):
    mock_client.get.return_value = json.dumps({"session_id": "s1", "user_id": "owner"})
    assert await db.delete_session("s1", user_id="intruder") is False
    mock_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_session_succeeds_when_user_id_matches(db, mock_client):
    mock_client.get.return_value = json.dumps({"session_id": "s1", "user_id": "owner"})
    mock_client.delete.return_value = 1
    assert await db.delete_session("s1", user_id="owner") is True
    mock_client.delete.assert_awaited()


@pytest.mark.asyncio
async def test_get_session_respects_user_id_filter(db, mock_client):
    mock_client.get.return_value = json.dumps({"session_id": "s1", "user_id": "owner"})
    assert await db.get_session("s1", user_id="intruder", deserialize=False) is None
    assert await db.get_session("s1", deserialize=False) == {"session_id": "s1", "user_id": "owner"}


@pytest.mark.asyncio
async def test_clear_memories_deletes_all_keys_at_once(make_mock_client):
    keys = ["agno:memories:m1", "agno:memories:m2"]
    client = make_mock_client(scan_keys=keys)
    db = AsyncRedisDb(redis_client=client)
    await db.clear_memories()
    client.delete.assert_awaited_once_with(*keys)


@pytest.mark.asyncio
async def test_clear_memories_noop_when_empty(db, mock_client):
    await db.clear_memories()
    mock_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_user_memory_respects_user_id(db, mock_client):
    mock_client.get.return_value = json.dumps({"memory_id": "m1", "user_id": "owner", "memory": "hi"})
    assert await db.get_user_memory("m1", deserialize=False, user_id="intruder") is None
    assert await db.get_user_memory("m1", deserialize=False, user_id="owner") == {
        "memory_id": "m1",
        "user_id": "owner",
        "memory": "hi",
    }


@pytest.mark.asyncio
async def test_close_calls_aclose(db, mock_client):
    await db.close()
    mock_client.aclose.assert_awaited_once()
