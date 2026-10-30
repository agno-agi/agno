"""Unit tests for agno.utils.message.safe_truncation_index."""

from agno.models.message import Message
from agno.utils.message import safe_truncation_index


def _assistant(*call_ids: str) -> Message:
    return Message(role="assistant", content=None, tool_calls=[{"id": call_id} for call_id in call_ids])


def _tool(call_id: str) -> Message:
    return Message(role="tool", content=f"result for {call_id}", tool_call_id=call_id)


def _orphaned(messages, boundary) -> list:
    """Tool call ids whose assistant survives messages[:boundary] but not its result."""
    kept = messages[:boundary]
    answered = {m.tool_call_id for m in kept if getattr(m, "tool_call_id", None)}
    orphans = []
    for m in kept:
        for tool_call in getattr(m, "tool_calls", None) or []:
            call_id = tool_call.get("id") if isinstance(tool_call, dict) else getattr(tool_call, "id", None)
            if call_id and call_id not in answered:
                orphans.append(call_id)
    return orphans


def test_interleaved_batches_snap_past_the_earlier_assistant():
    # Two assistants emit their calls before either result is recorded, so the result
    # of the first one sits *after* the assistant that triggered the snap.
    messages = [
        Message(role="user", content="q"),
        _assistant("tc1"),
        _assistant("tc2"),
        _tool("tc1"),
        _tool("tc2"),
    ]

    boundary = safe_truncation_index(messages, 4)

    assert boundary == 1, "cutting at 2 keeps assistant(tc1) but drops tool(tc1)"
    assert _orphaned(messages, boundary) == []


def test_three_interleaved_batches_snap_to_the_first_one():
    messages = [
        Message(role="user", content="q"),
        _assistant("tc1"),
        _assistant("tc2"),
        _assistant("tc3"),
        _tool("tc1"),
        _tool("tc2"),
        _tool("tc3"),
    ]

    boundary = safe_truncation_index(messages, 6)

    assert boundary == 1
    assert _orphaned(messages, boundary) == []


def test_result_of_a_multi_call_batch_still_counts():
    # assistant(tc1, tc2) answered after a second assistant batch: the whole first
    # exchange still has to go, because both of its results fall outside the cut.
    messages = [
        Message(role="user", content="q"),
        _assistant("tc1", "tc2"),
        _assistant("tc3"),
        _tool("tc1"),
        _tool("tc2"),
        _tool("tc3"),
    ]

    assert safe_truncation_index(messages, 5) == 1
    assert _orphaned(messages, safe_truncation_index(messages, 5)) == []
    # A boundary that keeps every result is already pair-safe.
    assert safe_truncation_index(messages, 6) == 6


def test_returned_boundary_is_a_fixed_point():
    messages = [
        Message(role="user", content="q"),
        _assistant("tc1"),
        _assistant("tc2"),
        _tool("tc1"),
        _tool("tc2"),
    ]

    for requested in range(len(messages) + 1):
        boundary = safe_truncation_index(messages, requested)
        assert safe_truncation_index(messages, boundary) == boundary
        assert _orphaned(messages, boundary) == []


def test_returns_the_largest_pair_safe_index():
    messages = [
        Message(role="user", content="q"),
        _assistant("tc1"),
        _tool("tc1"),
        _assistant("tc2"),
        _assistant("tc3"),
        _tool("tc2"),
        _tool("tc3"),
        Message(role="assistant", content="final answer"),
    ]

    for requested in range(len(messages) + 1):
        boundary = safe_truncation_index(messages, requested)
        expected = max(index for index in range(requested + 1) if not _orphaned(messages, index))
        assert boundary == expected, f"requested {requested}: {boundary} != {expected}"


def test_sequential_batches_are_unchanged():
    single = [
        Message(role="user", content="q"),
        _assistant("tc1"),
        _tool("tc1"),
        Message(role="assistant", content="final"),
    ]
    assert safe_truncation_index(single, 2) == 1
    assert safe_truncation_index(single, 3) == 3
    assert safe_truncation_index(single, 4) == 4

    multi = [
        Message(role="user", content="q"),
        _assistant("tc1", "tc2"),
        _tool("tc1"),
        _tool("tc2"),
        Message(role="assistant", content="final"),
    ]
    assert safe_truncation_index(multi, 2) == 1
    assert safe_truncation_index(multi, 3) == 1
    assert safe_truncation_index(multi, 4) == 4
    assert safe_truncation_index(multi, 5) == 5
    assert safe_truncation_index(multi, 1) == 1
    assert safe_truncation_index(multi, 0) == 0


def test_out_of_range_and_empty_boundaries_pass_through():
    assert safe_truncation_index([], 0) == 0
    messages = [Message(role="user", content="q")]
    assert safe_truncation_index(messages, 1) == 1
    assert safe_truncation_index(messages, 9) == 9
