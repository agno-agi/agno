from datetime import datetime

from agno.compression.context import (
    SUMMARY_PREFIX,
    CompactionState,
    create_summary_message,
)


def test_compaction_state_defaults():
    state = CompactionState()
    assert state.summary == ""
    assert state.compacted_message_ids == set()
    assert state.compacted_count == 0
    assert state.total_compactions == 0
    assert state.total_tokens_saved == 0
    assert state.updated_at is None


def test_compaction_state_with_values():
    now = datetime.now()
    state = CompactionState(
        summary="Test summary",
        compacted_message_ids={"msg-1", "msg-2", "msg-3"},
        compacted_count=3,
        total_compactions=2,
        total_tokens_saved=5000,
        updated_at=now,
    )
    assert state.summary == "Test summary"
    assert state.compacted_message_ids == {"msg-1", "msg-2", "msg-3"}
    assert state.compacted_count == 3
    assert state.total_compactions == 2
    assert state.total_tokens_saved == 5000
    assert state.updated_at == now


def test_compaction_state_to_dict():
    now = datetime(2024, 1, 15, 10, 30, 0)
    state = CompactionState(
        summary="Summary text",
        compacted_message_ids={"id-a", "id-b"},
        compacted_count=2,
        total_compactions=1,
        total_tokens_saved=1000,
        updated_at=now,
    )
    result = state.to_dict()

    assert result["summary"] == "Summary text"
    assert set(result["compacted_message_ids"]) == {"id-a", "id-b"}
    assert result["compacted_count"] == 2
    assert result["total_compactions"] == 1
    assert result["total_tokens_saved"] == 1000
    assert result["updated_at"] == "2024-01-15T10:30:00"


def test_compaction_state_to_dict_none_updated_at():
    state = CompactionState(summary="Test")
    result = state.to_dict()
    assert result["updated_at"] is None


def test_compaction_state_from_dict():
    data = {
        "summary": "Restored summary",
        "compacted_message_ids": ["msg-x", "msg-y"],
        "compacted_count": 5,
        "total_compactions": 3,
        "total_tokens_saved": 8000,
        "updated_at": "2024-06-20T14:45:30",
    }
    state = CompactionState.from_dict(data)

    assert state.summary == "Restored summary"
    assert state.compacted_message_ids == {"msg-x", "msg-y"}
    assert state.compacted_count == 5
    assert state.total_compactions == 3
    assert state.total_tokens_saved == 8000
    assert state.updated_at == datetime(2024, 6, 20, 14, 45, 30)


def test_compaction_state_from_dict_missing_fields():
    data = {"summary": "Only summary"}
    state = CompactionState.from_dict(data)

    assert state.summary == "Only summary"
    assert state.compacted_message_ids == set()
    assert state.compacted_count == 0
    assert state.total_compactions == 0
    assert state.total_tokens_saved == 0
    assert state.updated_at is None


def test_compaction_state_round_trip():
    now = datetime(2024, 3, 10, 8, 0, 0)
    original = CompactionState(
        summary="Full round trip test",
        compacted_message_ids={"a", "b", "c"},
        compacted_count=3,
        total_compactions=5,
        total_tokens_saved=15000,
        updated_at=now,
    )
    restored = CompactionState.from_dict(original.to_dict())

    assert restored.summary == original.summary
    assert restored.compacted_message_ids == original.compacted_message_ids
    assert restored.compacted_count == original.compacted_count
    assert restored.total_compactions == original.total_compactions
    assert restored.total_tokens_saved == original.total_tokens_saved
    assert restored.updated_at == original.updated_at


def test_get_summary_message_format():
    state = CompactionState(summary="The agent completed task X.")
    msg = state.get_summary_message()

    assert msg.role == "user"
    assert msg.content.startswith(SUMMARY_PREFIX)
    assert "The agent completed task X." in msg.content
    assert msg.from_history is True


def test_get_summary_message_empty_summary():
    state = CompactionState(summary="")
    msg = state.get_summary_message()

    assert msg.role == "user"
    assert msg.content == SUMMARY_PREFIX
    assert msg.from_history is True


def test_create_summary_message_function():
    msg = create_summary_message("Standalone summary text")

    assert msg.role == "user"
    assert msg.content.startswith(SUMMARY_PREFIX)
    assert "Standalone summary text" in msg.content
    assert msg.from_history is True


def test_compaction_state_set_serialization_order_independent():
    state1 = CompactionState(compacted_message_ids={"z", "a", "m"})
    state2 = CompactionState(compacted_message_ids={"a", "m", "z"})

    restored1 = CompactionState.from_dict(state1.to_dict())
    restored2 = CompactionState.from_dict(state2.to_dict())

    assert restored1.compacted_message_ids == restored2.compacted_message_ids
    assert restored1.compacted_message_ids == {"a", "m", "z"}
