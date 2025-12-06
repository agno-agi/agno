import json
import time

from agno.models.message import Message, Metrics
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput


def test_timer_serialization():
    message_1 = Message(role="user", content="Hello, world!")
    message_2 = Message(role="assistant", metrics=Metrics())

    message_2.metrics.start_timer()
    message_2.metrics.stop_timer()

    run_response = RunOutput(messages=[message_1, message_2])

    assert json.dumps(run_response.to_dict()) is not None


def test_tool_execution_created_at_round_trip():
    """Test that created_at is preserved across serialization/deserialization and unique per instance."""
    # Test 1: Per-instance timestamps
    instance1 = ToolExecution(tool_name="test_tool_1")
    time.sleep(1.1)  # Wait > 1 second since created_at uses int(time())
    instance2 = ToolExecution(tool_name="test_tool_2")

    # Each instance should have its own timestamp
    assert instance1.created_at != instance2.created_at, (
        f"Bug: All instances share same timestamp! instance1={instance1.created_at}, instance2={instance2.created_at}"
    )

    # Test 2: Serialization preserves timestamp
    original = ToolExecution(tool_name="test_tool", tool_call_id="test_id")
    original_created_at = original.created_at

    serialized = original.to_dict()
    assert "created_at" in serialized
    assert serialized["created_at"] == original_created_at

    time.sleep(1.1)

    restored = ToolExecution.from_dict(serialized)
    assert restored.created_at == original_created_at, (
        f"Bug: Timestamp not preserved! original={original_created_at}, restored={restored.created_at}"
    )
