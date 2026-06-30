from datetime import datetime, timezone

from agno.db.schemas import UserMemory


def test_user_memory_from_dict_handles_epoch_ints():
    memory = UserMemory.from_dict(
        {
            "memory_id": "m1",
            "memory": "hello",
            "created_at": 1_700_000_000,
            "updated_at": 1_700_000_123,
        }
    )

    assert isinstance(memory.created_at, int)
    assert isinstance(memory.updated_at, int)

    as_dict = memory.to_dict()
    assert as_dict["memory_id"] == "m1"
    assert isinstance(as_dict["created_at"], str)
    assert isinstance(as_dict["updated_at"], str)


def test_user_memory_from_dict_handles_iso_strings():
    memory = UserMemory.from_dict(
        {
            "memory_id": "m1",
            "memory": "hello",
            "created_at": "2025-01-02T03:04:05+00:00",
            "updated_at": "2025-01-02T03:04:06Z",
        }
    )

    assert isinstance(memory.created_at, int)
    assert isinstance(memory.updated_at, int)
    assert memory.to_dict()["memory_id"] == "m1"


def test_user_memory_init_normalizes_datetime_objects():
    now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    memory = UserMemory.from_dict(
        {
            "memory_id": "m1",
            "memory": "hello",
            "created_at": now,
            "updated_at": now,
        }
    )

    assert isinstance(memory.created_at, int)
    assert isinstance(memory.updated_at, int)
    assert memory.to_dict()["memory_id"] == "m1"
