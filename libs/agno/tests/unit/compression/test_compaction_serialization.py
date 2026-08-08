import json
from datetime import datetime

from agno.compression.context import CompactionState
from agno.run.agent import RunOutput


def test_run_output_with_compaction_state_to_dict():
    compaction = CompactionState(
        summary="Test summary",
        compacted_message_ids={"msg-1", "msg-2"},
        total_compactions=3,
    )
    run = RunOutput(
        run_id="run-123",
        agent_id="agent-456",
        session_id="session-789",
        compaction_state=compaction,
    )

    result = run.to_dict()

    assert "compaction_state" in result
    assert result["compaction_state"]["summary"] == "Test summary"
    assert set(result["compaction_state"]["compacted_message_ids"]) == {"msg-1", "msg-2"}
    assert result["compaction_state"]["total_compactions"] == 3


def test_run_output_from_dict_restores_compaction_state():
    data = {
        "run_id": "run-abc",
        "agent_id": "agent-def",
        "session_id": "session-ghi",
        "compaction_state": {
            "summary": "Restored summary",
            "compacted_message_ids": ["id-x", "id-y", "id-z"],
            "compacted_count": 3,
            "total_compactions": 5,
            "total_tokens_saved": 10000,
            "updated_at": "2024-05-15T12:30:00",
        },
    }

    run = RunOutput.from_dict(data)

    assert run.compaction_state is not None
    assert run.compaction_state.summary == "Restored summary"
    assert run.compaction_state.compacted_message_ids == {"id-x", "id-y", "id-z"}
    assert run.compaction_state.compacted_count == 3
    assert run.compaction_state.total_compactions == 5
    assert run.compaction_state.total_tokens_saved == 10000
    assert run.compaction_state.updated_at == datetime(2024, 5, 15, 12, 30, 0)


def test_run_output_round_trip_preserves_all_fields():
    now = datetime(2024, 7, 20, 9, 15, 30)
    original_compaction = CompactionState(
        summary="Full round trip summary with details",
        compacted_message_ids={"a", "b", "c", "d", "e"},
        compacted_count=5,
        total_compactions=10,
        total_tokens_saved=25000,
        updated_at=now,
    )
    original = RunOutput(
        run_id="run-roundtrip",
        agent_id="agent-roundtrip",
        session_id="session-roundtrip",
        compaction_state=original_compaction,
    )

    restored = RunOutput.from_dict(original.to_dict())

    assert restored.compaction_state is not None
    assert restored.compaction_state.summary == original_compaction.summary
    assert restored.compaction_state.compacted_message_ids == original_compaction.compacted_message_ids
    assert restored.compaction_state.compacted_count == original_compaction.compacted_count
    assert restored.compaction_state.total_compactions == original_compaction.total_compactions
    assert restored.compaction_state.total_tokens_saved == original_compaction.total_tokens_saved
    assert restored.compaction_state.updated_at == original_compaction.updated_at


def test_run_output_without_compaction_state():
    run = RunOutput(
        run_id="run-no-compaction",
        agent_id="agent-1",
        session_id="session-1",
    )

    result = run.to_dict()

    # compaction_state should not be in dict if None
    assert "compaction_state" not in result or result.get("compaction_state") is None

    # Round-trip should preserve None
    restored = RunOutput.from_dict(result)
    assert restored.compaction_state is None


def test_compaction_state_json_compatible():
    compaction = CompactionState(
        summary="JSON test",
        compacted_message_ids={"1", "2", "3"},
        total_compactions=1,
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )

    # Should be JSON-serializable
    json_str = json.dumps(compaction.to_dict())

    # Should be parseable back
    parsed = json.loads(json_str)
    restored = CompactionState.from_dict(parsed)

    assert restored.summary == "JSON test"
    assert restored.compacted_message_ids == {"1", "2", "3"}
    assert restored.updated_at == datetime(2024, 1, 1, 0, 0, 0)


def test_run_output_json_full_round_trip():
    compaction = CompactionState(
        summary="Full JSON round trip",
        compacted_message_ids={"msg-alpha", "msg-beta"},
        total_compactions=7,
        total_tokens_saved=50000,
    )
    run = RunOutput(
        run_id="json-test",
        agent_id="agent-json",
        session_id="session-json",
        compaction_state=compaction,
    )

    # to_dict -> JSON string -> parse -> from_dict
    json_str = json.dumps(run.to_dict())
    parsed = json.loads(json_str)
    restored = RunOutput.from_dict(parsed)

    assert restored.compaction_state is not None
    assert restored.compaction_state.summary == "Full JSON round trip"
    assert restored.compaction_state.compacted_message_ids == {"msg-alpha", "msg-beta"}
    assert restored.compaction_state.total_compactions == 7
    assert restored.compaction_state.total_tokens_saved == 50000
