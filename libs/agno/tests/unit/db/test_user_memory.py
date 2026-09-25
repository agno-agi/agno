import os
import time
from datetime import datetime, timezone

import pytest

from agno.db.schemas import UserMemory
from agno.utils.dttm import to_epoch_s


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


CREATED_AT = 1_756_712_400  # 2025-09-01T07:40:00+00:00


def _memory() -> UserMemory:
    return UserMemory(memory_id="m1", memory="prefers window seats", user_id="u1", created_at=CREATED_AT)


def test_user_memory_timestamps_serialize_as_utc():
    # ``from_dict`` -> ``to_epoch_s`` reads an offset-less string as UTC, so a local
    # wall-clock stamp is a different instant once stored: the round trip is only
    # lossless while the serialized form carries its offset.
    as_dict = _memory().to_dict()

    assert as_dict["created_at"] == "2025-09-01T07:40:00+00:00"
    # ``updated_at`` was never set, so it mirrors ``created_at`` and must agree with it
    assert as_dict["updated_at"] == as_dict["created_at"]
    assert datetime.fromisoformat(as_dict["created_at"]).tzinfo is not None


def test_user_memory_timestamp_survives_both_shipped_readers():
    memory = _memory()
    as_dict = memory.to_dict()

    assert to_epoch_s(as_dict["created_at"]) == CREATED_AT
    # get_user_memory_stats parses the stored stamp the way a naive datetime's
    # ``.timestamp()`` does -- assuming the local zone. The two readers only agree on
    # an offset-bearing string, which is what the serializer must emit.
    local_reader = int(datetime.fromisoformat(as_dict["updated_at"].replace("Z", "+00:00")).timestamp())
    assert local_reader == CREATED_AT

    assert UserMemory.from_dict(as_dict).created_at == CREATED_AT


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="switching the host clock zone is POSIX-only")
@pytest.mark.parametrize("zone", ["Asia/Kolkata", "America/Los_Angeles", "Australia/Eucla"])
def test_user_memory_round_trip_survives_a_non_utc_host_clock(zone: str):
    original_zone = os.environ.get("TZ")
    os.environ["TZ"] = zone
    time.tzset()
    try:
        stored = _memory().to_dict()
        assert UserMemory.from_dict(stored).created_at == CREATED_AT
    finally:
        if original_zone is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_zone
        time.tzset()
