"""Unpaired function_call items must not be sent to the OpenAI Responses API.

The Responses API requires every `function_call` to be paired with a
`function_call_output` carrying the same `call_id`, and rejects the whole
request otherwise:

    No tool output found for function call call_00000000.
"""

from typing import Any, Dict, List

from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses

# Shape observed in affected sessions: uuid id, no call_id.
DELEGATE_CALL_ID = "d4f8a1b2-3c5e-4a91-b7d2-8e6f0a1c2b3d"


def _delegate_tool_call(call_id: str = DELEGATE_CALL_ID) -> Dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "delegate_task_to_member",
            "arguments": '{"member_id": "researcher", "task": "Research X"}',
        },
    }


def _calls(formatted: List[Any]) -> List[Dict[str, Any]]:
    return [x for x in formatted if isinstance(x, dict) and x.get("type") == "function_call"]


def _outputs(formatted: List[Any]) -> List[Dict[str, Any]]:
    return [x for x in formatted if isinstance(x, dict) and x.get("type") == "function_call_output"]


def _unpaired(formatted: List[Any]) -> List[Any]:
    output_ids = {x["call_id"] for x in _outputs(formatted)}
    return [x.get("call_id") for x in _calls(formatted) if x.get("call_id") not in output_ids]


def test_complete_turn_is_preserved():
    """A call with its result must still be sent — both halves, correctly paired."""
    model = OpenAIResponses(id="gpt-4.1-mini")

    formatted = model._format_messages(
        messages=[
            Message(role="user", content="Research X"),
            Message(role="assistant", content="", tool_calls=[_delegate_tool_call()]),
            Message(
                role="tool",
                tool_call_id=DELEGATE_CALL_ID,
                tool_name="delegate_task_to_member",
                content="Researcher: findings for X",
            ),
            Message(role="assistant", content="Here are the findings."),
        ]
    )

    assert len(_calls(formatted)) == 1
    assert len(_outputs(formatted)) == 1
    assert _unpaired(formatted) == []


def test_call_with_no_recorded_result_is_dropped():
    """The reported bug: a run persisted with a tool call and no tool message.

    The call must not be emitted, since no output can pair with it.
    """
    model = OpenAIResponses(id="gpt-4.1-mini")

    formatted = model._format_messages(
        messages=[
            Message(role="user", content="Research X"),
            Message(role="assistant", content="", tool_calls=[_delegate_tool_call()]),
            # No tool message was ever recorded for the call above.
            Message(role="assistant", content="Here are the findings."),
        ]
    )

    assert _calls(formatted) == [], "an unpairable function_call must not be sent"
    assert _unpaired(formatted) == []


def test_result_without_tool_call_id_does_not_orphan_its_call():
    """A tool result that cannot be formatted is dropped at the output branch.

    Its call must be dropped too, or the two branches disagree and the request
    goes out unpaired.
    """
    model = OpenAIResponses(id="gpt-4.1-mini")

    formatted = model._format_messages(
        messages=[
            Message(role="user", content="Research X"),
            Message(role="assistant", content="", tool_calls=[_delegate_tool_call()]),
            Message(role="tool", tool_call_id=None, tool_name="delegate_task_to_member", content="findings"),
        ]
    )

    assert _outputs(formatted) == []
    assert _calls(formatted) == []


def test_only_the_unpaired_call_is_dropped():
    """Healthy history must survive alongside a poisoned call."""
    model = OpenAIResponses(id="gpt-4.1-mini")

    answered = DELEGATE_CALL_ID
    unanswered = "b2c3d4e5-f6a7-8901-bcde-f23456789012"

    formatted = model._format_messages(
        messages=[
            Message(role="user", content="Research X and Y"),
            Message(role="assistant", content="", tool_calls=[_delegate_tool_call(answered)]),
            Message(
                role="tool",
                tool_call_id=answered,
                tool_name="delegate_task_to_member",
                content="Researcher: findings for X",
            ),
            Message(role="assistant", content="", tool_calls=[_delegate_tool_call(unanswered)]),
            # Result for the second delegation was never recorded.
            Message(role="assistant", content="Here are the findings."),
        ]
    )

    assert len(_calls(formatted)) == 1, "the answered call must survive"
    assert len(_outputs(formatted)) == 1
    assert _unpaired(formatted) == []


def test_parallel_calls_in_one_message_are_filtered_individually():
    """One assistant message can carry several calls; only unpaired ones drop."""
    model = OpenAIResponses(id="gpt-4.1-mini")

    answered = DELEGATE_CALL_ID
    unanswered = "c3d4e5f6-a7b8-9012-cdef-345678901234"

    formatted = model._format_messages(
        messages=[
            Message(role="user", content="Research X and Y"),
            Message(
                role="assistant",
                content="",
                tool_calls=[_delegate_tool_call(answered), _delegate_tool_call(unanswered)],
            ),
            Message(
                role="tool",
                tool_call_id=answered,
                tool_name="delegate_task_to_member",
                content="Researcher: findings for X",
            ),
        ]
    )

    assert len(_calls(formatted)) == 1
    assert _unpaired(formatted) == []
