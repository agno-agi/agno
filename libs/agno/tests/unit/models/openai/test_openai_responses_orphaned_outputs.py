"""Regression tests for issue #9372: orphaned function_call_output items.

The OpenAI Responses API rejects a request containing a `function_call_output`
whose `call_id` has no matching `function_call` in the request:
`No tool call found for function call output with call_id ...`.

History truncation (e.g. `num_history_messages`) can cut between an assistant
tool-call message and its tool result, leaving an orphaned output. The tool-result
branch of `_format_messages` must drop those outputs — except on the
`previous_response_id` chaining path (reasoning models), where the API holds the
conversation state server-side and outputs are deliberately sent without their calls.
"""

from typing import Any, List, Optional

from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses


def _assistant_with_tool_call(call_id: str = "call_def456", fc_id: str = "fc_abc123") -> Message:
    return Message(
        role="assistant",
        tool_calls=[
            {
                "id": fc_id,
                "call_id": call_id,
                "type": "function",
                "function": {"name": "execute_shell_command", "arguments": '{"command": "ls -la"}'},
            }
        ],
    )


def test_format_messages_drops_orphaned_function_call_output():
    """A tool result whose function_call was truncated out of the history must not be emitted."""
    model = OpenAIResponses(id="gpt-4.1-mini")

    # The assistant's tool-call message is gone (truncated); only the tool result survives.
    orphaned_tool_output = Message(role="tool", tool_call_id="call_def456", content="ok")

    fm = model._format_messages(
        messages=[
            Message(role="system", content="s"),
            Message(role="user", content="u"),
            orphaned_tool_output,
        ]
    )

    out_items = [x for x in fm if isinstance(x, dict) and x.get("type") == "function_call_output"]
    fc_items = [x for x in fm if isinstance(x, dict) and x.get("type") == "function_call"]

    assert out_items == []
    assert fc_items == []


def test_format_messages_drops_orphaned_output_with_fc_id():
    """Same, when the tool message references the assistant call by its fc_* id."""
    model = OpenAIResponses(id="gpt-4.1-mini")

    orphaned_tool_output = Message(role="tool", tool_call_id="fc_abc123", content="ok")

    fm = model._format_messages(
        messages=[
            Message(role="system", content="s"),
            Message(role="user", content="u"),
            orphaned_tool_output,
        ]
    )

    out_items = [x for x in fm if isinstance(x, dict) and x.get("type") == "function_call_output"]
    assert out_items == []


def test_format_messages_keeps_output_when_call_present():
    """Paired call + output must still be emitted (existing behavior preserved)."""
    model = OpenAIResponses(id="gpt-4.1-mini")

    tool_output = Message(role="tool", tool_call_id="call_def456", content="ok")

    fm = model._format_messages(
        messages=[
            Message(role="system", content="s"),
            Message(role="user", content="u"),
            _assistant_with_tool_call(),
            tool_output,
        ]
    )

    fc_items = [x for x in fm if isinstance(x, dict) and x.get("type") == "function_call"]
    out_items = [x for x in fm if isinstance(x, dict) and x.get("type") == "function_call_output"]

    assert len(fc_items) == 1
    assert len(out_items) == 1
    assert out_items[0]["call_id"] == "call_def456"


def test_format_messages_truncation_keeps_output_when_call_still_emitted():
    """Truncation that keeps the assistant call (e.g. limit=4) must still emit the output."""
    model = OpenAIResponses(id="gpt-4.1-mini")

    tool_output = Message(role="tool", tool_call_id="call_def456", content="ok")
    final_assistant = Message(role="assistant", content="done")

    fm = model._format_messages(
        messages=[
            Message(role="system", content="s"),
            Message(role="user", content="u"),
            _assistant_with_tool_call(),
            tool_output,
            final_assistant,
        ]
    )

    out_items = [x for x in fm if isinstance(x, dict) and x.get("type") == "function_call_output"]
    assert len(out_items) == 1
    assert out_items[0]["call_id"] == "call_def456"


def test_reasoning_chaining_keeps_outputs_without_calls(monkeypatch):
    """The previous_response_id chaining path must keep emitting outputs without calls."""
    model = OpenAIResponses(id="o4-mini")  # reasoning
    monkeypatch.setattr(model, "_using_reasoning_model", lambda: True)

    assistant_with_prev = Message(role="assistant")
    assistant_with_prev.provider_data = {"response_id": "resp_123"}  # type: ignore[attr-defined]

    # Tool output for a call made in the *previous* response — no function_call in this request.
    tool_output = Message(role="tool", tool_call_id="call_prev001", content="ok")

    fm = model._format_messages(
        messages=[
            Message(role="system", content="s"),
            Message(role="user", content="u"),
            assistant_with_prev,
            tool_output,
        ]
    )

    out_items = [x for x in fm if isinstance(x, dict) and x.get("type") == "function_call_output"]
    fc_items = [x for x in fm if isinstance(x, dict) and x.get("type") == "function_call"]

    # Output must survive; no function_call items are re-sent on the chaining path.
    assert len(out_items) == 1
    assert out_items[0]["call_id"] == "call_prev001"
    assert fc_items == []
