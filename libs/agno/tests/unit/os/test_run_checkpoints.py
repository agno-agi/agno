import pytest

from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.os.checkpoints import build_run_checkpoint_snapshot, list_run_checkpoints
from agno.run import RunStatus
from agno.run.agent import RunOutput


def test_list_run_checkpoints_uses_message_markers_and_terminal_end():
    first = Message(role="user", content="hello")
    tool = Message(role="tool", content="done")
    tool.checkpoint_status = RunStatus.running.value
    tool.checkpoint_created_at = 123
    final = Message(role="assistant", content="final answer")
    run = RunOutput(
        run_id="run-1",
        session_id="session-1",
        status=RunStatus.completed,
        messages=[first, tool, final],
        last_checkpoint_at_message_index=2,
        created_at=100,
    )

    checkpoints = list_run_checkpoints(run)

    assert [checkpoint["message_index"] for checkpoint in checkpoints] == [2, 3]
    # checkpoint_id is a 1-based display ordinal (Checkpoint 1, 2, 3, …),
    # NOT equal to the message_index — so the FE renders "Checkpoint 1, 2"
    # even when the underlying boundaries are at indices 2 and 3.
    assert [checkpoint["checkpoint_id"] for checkpoint in checkpoints] == ["1", "2"]
    assert checkpoints[0]["reason"] == "checkpoint"
    assert checkpoints[0]["status"] == RunStatus.running.value
    assert checkpoints[0]["created_at"] == 123
    assert checkpoints[1]["reason"] == "end"
    assert checkpoints[1]["status"] == RunStatus.completed.value


def test_list_run_checkpoints_assigns_sequential_ids_regardless_of_index_gaps():
    """A run with checkpoints at indices 4, 6, 7 still labels them 1, 2, 3."""
    msgs = [Message(role="user", content=f"m{i}") for i in range(7)]
    # Mark messages at indices 4 and 6 (1-based) as checkpoint boundaries.
    msgs[3].checkpoint_status = RunStatus.running.value
    msgs[5].checkpoint_status = RunStatus.running.value
    run = RunOutput(
        run_id="run-2",
        session_id="session-1",
        status=RunStatus.completed,
        messages=msgs,
    )

    checkpoints = list_run_checkpoints(run)

    assert [c["message_index"] for c in checkpoints] == [4, 6, 7]
    assert [c["checkpoint_id"] for c in checkpoints] == ["1", "2", "3"]


def test_snapshot_checkpoint_id_matches_timeline_ordinal():
    """The single-checkpoint payload from build_run_checkpoint_snapshot
    carries the same display ordinal the timeline endpoint would return."""
    msgs = [Message(role="user", content=f"m{i}") for i in range(7)]
    msgs[3].checkpoint_status = RunStatus.running.value
    msgs[5].checkpoint_status = RunStatus.running.value
    run = RunOutput(
        run_id="run-3",
        session_id="session-1",
        status=RunStatus.completed,
        messages=msgs,
    )

    # Snapshot at message_index=6 → timeline ordinal 2 (the second checkpoint).
    payload = build_run_checkpoint_snapshot(run, 6)
    assert payload["checkpoint"]["checkpoint_id"] == "2"
    assert payload["checkpoint"]["message_index"] == 6

    # Snapshot at the terminal end (index 7) → ordinal 3.
    payload_end = build_run_checkpoint_snapshot(run, 7)
    assert payload_end["checkpoint"]["checkpoint_id"] == "3"


def test_build_run_checkpoint_snapshot_truncates_messages_and_tools_without_mutating_source():
    assistant = Message(
        role="assistant",
        tool_calls=[{"id": "tool-keep", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
    )
    tool_message = Message(role="tool", content="tool result", tool_call_id="tool-keep")
    final = Message(role="assistant", content="final")
    run = RunOutput(
        run_id="run-1",
        session_id="session-1",
        status=RunStatus.completed,
        messages=[assistant, tool_message, final],
        tools=[
            ToolExecution(tool_call_id="tool-keep", tool_name="lookup", result="tool result"),
            ToolExecution(tool_call_id="tool-drop", tool_name="other", result="other result"),
        ],
    )

    payload = build_run_checkpoint_snapshot(run, 2)

    snapshot = payload["snapshot"]
    assert payload["checkpoint"]["message_index"] == 2
    assert [message["role"] for message in snapshot["messages"]] == ["assistant", "tool"]
    assert [tool["tool_call_id"] for tool in snapshot["tools"]] == ["tool-keep"]
    assert len(run.messages or []) == 3
    assert len(run.tools or []) == 2


def test_build_run_checkpoint_snapshot_rejects_invalid_message_index():
    run = RunOutput(run_id="run-1", messages=[Message(role="user", content="hello")])

    with pytest.raises(ValueError, match="between 0 and 1"):
        build_run_checkpoint_snapshot(run, 2)
