from typing import Any, Dict, List, Optional

from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses
from agno.models.response import ModelResponse


class _FakeError:
    def __init__(self, message: str):
        self.message = message


class _FakeOutputFunctionCall:
    def __init__(self, *, _id: str, call_id: Optional[str], name: str, arguments: str):
        self.type = "function_call"
        self.id = _id
        self.call_id = call_id
        self.name = name
        self.arguments = arguments


class _FakeResponse:
    def __init__(
        self,
        *,
        _id: str,
        output: List[Any],
        output_text: str = "",
        usage: Optional[Dict[str, Any]] = None,
        error: Optional[_FakeError] = None,
    ):
        self.id = _id
        self.output = output
        self.output_text = output_text
        self.usage = usage
        self.error = error


class _FakeStreamItem:
    def __init__(self, *, _id: str, call_id: Optional[str], name: str, arguments: str):
        self.type = "function_call"
        self.id = _id
        self.call_id = call_id
        self.name = name
        self.arguments = arguments


class _FakeStreamEvent:
    def __init__(
        self,
        *,
        type: str,
        item: Optional[_FakeStreamItem] = None,
        delta: str = "",
        response: Any = None,
        annotation: Any = None,
    ):
        self.type = type
        self.item = item
        self.delta = delta
        self.response = response
        self.annotation = annotation


def test_format_messages_maps_tool_output_fc_to_call_id():
    model = OpenAIResponses(id="gpt-4.1-mini")

    # Assistant emitted a function_call with both fc_* and call_* ids
    assistant_with_tool_call = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "fc_abc123",
                "call_id": "call_def456",
                "type": "function",
                "function": {"name": "execute_shell_command", "arguments": '{"command": "ls -la"}'},
            }
        ],
    )

    # Tool output referring to the fc_* id should be normalized to call_*
    tool_output = Message(role="tool", tool_call_id="fc_abc123", content="ok")

    fm = model._format_messages(
        messages=[
            Message(role="system", content="s"),
            Message(role="user", content="u"),
            assistant_with_tool_call,
            tool_output,
        ]
    )

    # Expect one function_call and one function_call_output normalized
    fc_items = [x for x in fm if x.get("type") == "function_call"]
    out_items = [x for x in fm if x.get("type") == "function_call_output"]

    assert len(fc_items) == 1
    assert fc_items[0]["id"] == "fc_abc123"
    assert fc_items[0]["call_id"] == "call_def456"

    assert len(out_items) == 1
    assert out_items[0]["call_id"] == "call_def456"


def test_parse_provider_response_maps_ids():
    model = OpenAIResponses(id="gpt-4.1-mini")

    fake_resp = _FakeResponse(
        _id="resp_1",
        output=[_FakeOutputFunctionCall(_id="fc_abc123", call_id="call_def456", name="execute", arguments="{}")],
        output_text="",
        usage=None,
        error=None,
    )

    mr: ModelResponse = model._parse_provider_response(fake_resp)  # type: ignore[arg-type]

    assert mr.tool_calls is not None and len(mr.tool_calls) == 1
    tc = mr.tool_calls[0]
    assert tc["id"] == "fc_abc123"
    assert tc["call_id"] == "call_def456"
    assert mr.extra is not None and "tool_call_ids" in mr.extra and mr.extra["tool_call_ids"][0] == "call_def456"


def test_process_stream_response_builds_tool_calls():
    model = OpenAIResponses(id="gpt-4.1-mini")
    assistant_message = Message(role="assistant")

    # Simulate function_call added and then completed
    added = _FakeStreamEvent(
        type="response.output_item.added",
        item=_FakeStreamItem(_id="fc_abc123", call_id="call_def456", name="execute", arguments="{}"),
    )
    mr, tool_use = model._parse_provider_response_delta(added, assistant_message, {})  # type: ignore[arg-type]
    assert mr is not None
    assert mr.role is None
    assert mr.content is None
    assert mr.tool_calls == []

    # Optional: simulate args delta
    delta_ev = _FakeStreamEvent(type="response.function_call_arguments.delta", delta='{"k":1}')
    mr, tool_use = model._parse_provider_response_delta(delta_ev, assistant_message, tool_use)  # type: ignore[arg-type]
    assert mr is not None
    assert mr.role is None
    assert mr.content is None
    assert mr.tool_calls == []

    done = _FakeStreamEvent(type="response.output_item.done")
    mr, tool_use = model._parse_provider_response_delta(done, assistant_message, tool_use)  # type: ignore[arg-type]

    assert mr is not None
    assert mr.tool_calls is not None and len(mr.tool_calls) == 1
    tc = mr.tool_calls[0]
    assert tc["id"] == "fc_abc123"
    assert tc["call_id"] == "call_def456"
    assert assistant_message.tool_calls is not None and len(assistant_message.tool_calls) == 1


def test_reasoning_previous_response_skips_prior_function_call_items(monkeypatch):
    model = OpenAIResponses(id="o4-mini")  # reasoning

    # Force _using_reasoning_model to True
    monkeypatch.setattr(model, "_using_reasoning_model", lambda: True)

    assistant_with_prev = Message(role="assistant")
    assistant_with_prev.provider_data = {"response_id": "resp_123"}  # type: ignore[attr-defined]

    assistant_with_tool_call = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "fc_abc123",
                "call_id": "call_def456",
                "type": "function",
                "function": {"name": "execute_shell_command", "arguments": "{}"},
            }
        ],
    )

    fm = model._format_messages(
        messages=[
            Message(role="system", content="s"),
            Message(role="user", content="u"),
            assistant_with_prev,
            assistant_with_tool_call,
        ]
    )

    # Expect no re-sent function_call when previous_response_id is present for reasoning models
    assert all(x.get("type") != "function_call" for x in fm)


def _history_message(role: str, content: str, response_id: Optional[str] = None) -> Message:
    message = Message(role=role, content=content, from_history=True)
    if response_id is not None:
        message.provider_data = {"response_id": response_id}
    return message


def test_reasoning_does_not_chain_across_history_window(monkeypatch):
    """A windowed history must reach the wire, so chaining stops at the window boundary."""
    model = OpenAIResponses(id="o4-mini")
    monkeypatch.setattr(model, "_using_reasoning_model", lambda: True)

    messages = [
        Message(role="system", content="s"),
        _history_message("user", "turn 1"),
        _history_message("assistant", "reply 1", response_id="resp_1"),
        _history_message("user", "turn 2"),
        _history_message("assistant", "reply 2", response_id="resp_2"),
        Message(role="user", content="turn 3"),
    ]

    request_params = model.get_request_params(messages=messages)
    assert "previous_response_id" not in request_params
    assert request_params["store"] is True

    # Every windowed message is still sent, so num_history_runs bounds what the model sees
    formatted = model._format_messages(messages=messages)
    assert [item["content"] for item in formatted] == ["s", "turn 1", "reply 1", "turn 2", "reply 2", "turn 3"]


def test_reasoning_chains_within_the_current_run(monkeypatch):
    """Chaining is still used for the tool-call loop inside a single run."""
    model = OpenAIResponses(id="o4-mini")
    monkeypatch.setattr(model, "_using_reasoning_model", lambda: True)

    assistant_this_run = Message(role="assistant", content="thinking")
    assistant_this_run.provider_data = {"response_id": "resp_current"}

    messages = [
        Message(role="system", content="s"),
        _history_message("user", "turn 1"),
        _history_message("assistant", "reply 1", response_id="resp_old"),
        Message(role="user", content="turn 2"),
        assistant_this_run,
        Message(role="tool", tool_call_id="fc_1", tool_name="get_weather", content="sunny"),
    ]

    request_params = model.get_request_params(messages=messages)
    assert request_params["previous_response_id"] == "resp_current"

    # Only the messages after the chained response are re-sent
    formatted = model._format_messages(messages=messages)
    assert len(formatted) == 1
    assert formatted[0]["type"] == "function_call_output"


def test_reasoning_chaining_ignores_stale_history_response_id(monkeypatch):
    """A run with no assistant turn yet must not chain off the last history response."""
    model = OpenAIResponses(id="o4-mini")
    monkeypatch.setattr(model, "_using_reasoning_model", lambda: True)

    messages = [
        _history_message("assistant", "reply 1", response_id="resp_old"),
        Message(role="user", content="turn 2"),
    ]

    assert model._find_chainable_response(messages) == (None, None)
