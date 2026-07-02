import pytest

from agno.db.valkey.valkey import ValkeyDb


@pytest.fixture
def valkey_db() -> ValkeyDb:
    """Create a ValkeyDb instance connected to localhost:6379 with a test prefix."""
    db = ValkeyDb(
        host="localhost",
        port=6379,
        db_prefix="agno_test",
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
        culture_table="test_culture",
        traces_table="test_traces",
        spans_table="test_spans",
    )
    return db


@pytest.fixture(autouse=True)
def cleanup_valkey(valkey_db: ValkeyDb):
    """Clean up all test keys after each test."""
    yield

    from agno.db.valkey.utils import get_all_keys_for_table

    table_types = [
        "sessions",
        "memories",
        "metrics",
        "evals",
        "knowledge",
        "culture",
        "traces",
        "spans",
    ]
    for table_type in table_types:
        keys = get_all_keys_for_table(
            valkey_client=valkey_db.valkey_client,
            prefix=valkey_db.db_prefix,
            table_type=table_type,
        )
        if keys:
            valkey_db.valkey_client.delete(keys)
        # Also clean up index keys
        pattern = f"{valkey_db.db_prefix}:{table_type}:index:*"
        cursor = "0"
        while True:
            result = valkey_db.valkey_client.scan(cursor=cursor, match=pattern, count=1000)
            new_cursor = result[0]
            index_keys = result[1] if len(result) > 1 else []
            if index_keys:
                valkey_db.valkey_client.delete(index_keys)
            if isinstance(new_cursor, bytes):
                new_cursor = new_cursor.decode("utf-8")
            cursor = str(new_cursor)
            if cursor == "0":
                break
