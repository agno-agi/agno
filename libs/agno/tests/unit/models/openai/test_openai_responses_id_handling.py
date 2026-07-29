from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import APIStatusError

from agno.exceptions import ModelProviderError
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


def test_format_messages_without_previous_response_id_sends_full_history(monkeypatch):
    model = OpenAIResponses(id="o4-mini")
    monkeypatch.setattr(model, "_using_reasoning_model", lambda: True)

    assistant_with_prev = Message(role="assistant", content="prior")
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
    messages = [
        Message(role="system", content="s"),
        Message(role="user", content="u"),
        assistant_with_prev,
        assistant_with_tool_call,
    ]

    fm = model._format_messages(messages=messages, use_previous_response_id=False)

    # system -> developer via role_map
    assert any(x.get("role") == "developer" for x in fm)
    assert any(x.get("type") == "function_call" for x in fm)


# ---------------------------------------------------------------------------
# previous_response_id recovery on "not found" 400
# ---------------------------------------------------------------------------


class _InvokeFakeResponse:
    def __init__(self, *, _id: str = "resp_ok", output_text: str = "ok"):
        self.id = _id
        self.status = "completed"
        self.output: List[Any] = []
        self.output_text = output_text
        self.usage = None
        self.error = None


def _make_fake_client() -> MagicMock:
    client = MagicMock()
    client.is_closed.return_value = False
    return client


def _previous_response_not_found_error(response_id: str = "resp_missing") -> APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(400, request=request)
    message = f"Previous response with id '{response_id}' not found."
    return APIStatusError(message=message, response=response, body={"error": {"message": message}})


def _history_with_previous_response_id() -> List[Message]:
    assistant_with_prev = Message(role="assistant", content="prior answer")
    assistant_with_prev.provider_data = {"response_id": "resp_stale"}  # type: ignore[attr-defined]
    return [
        Message(role="system", content="be helpful"),
        Message(role="user", content="first question"),
        assistant_with_prev,
        Message(role="user", content="follow up"),
    ]


def test_invoke_valid_previous_response_id_no_retry():
    model = OpenAIResponses(id="o4-mini")
    fake_client = _make_fake_client()
    fake_client.responses.create.return_value = _InvokeFakeResponse(_id="resp_new")
    model.client = fake_client

    result = model.invoke(
        messages=_history_with_previous_response_id(),
        assistant_message=Message(role="assistant"),
    )

    assert result is not None
    assert fake_client.responses.create.call_count == 1
    _, kwargs = fake_client.responses.create.call_args
    assert kwargs.get("previous_response_id") == "resp_stale"


def test_invoke_invalid_previous_response_id_retries_with_full_history():
    model = OpenAIResponses(id="o4-mini")
    fake_client = _make_fake_client()
    fake_client.responses.create.side_effect = [
        _previous_response_not_found_error("resp_stale"),
        _InvokeFakeResponse(_id="resp_recovered", output_text="recovered"),
    ]
    model.client = fake_client

    result = model.invoke(
        messages=_history_with_previous_response_id(),
        assistant_message=Message(role="assistant"),
    )

    assert result is not None
    assert result.provider_data is not None
    assert result.provider_data.get("response_id") == "resp_recovered"
    assert fake_client.responses.create.call_count == 2

    first_kwargs = fake_client.responses.create.call_args_list[0].kwargs
    second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
    assert first_kwargs.get("previous_response_id") == "resp_stale"
    assert "previous_response_id" not in second_kwargs

    second_input = second_kwargs.get("input") or []
    # Full history (system mapped to developer), not the trimmed previous_response_id slice
    assert any(isinstance(item, dict) and item.get("role") == "developer" for item in second_input)
    assert any(
        isinstance(item, dict) and item.get("role") == "user" and item.get("content") == "first question"
        for item in second_input
    )
    assert any(
        isinstance(item, dict) and item.get("role") == "user" and item.get("content") == "follow up"
        for item in second_input
    )


def test_invoke_non_reasoning_model_never_retries_on_previous_response_error():
    model = OpenAIResponses(id="gpt-4.1-mini")
    fake_client = _make_fake_client()
    fake_client.responses.create.side_effect = _previous_response_not_found_error("resp_stale")
    model.client = fake_client

    with pytest.raises(ModelProviderError):
        model.invoke(
            messages=_history_with_previous_response_id(),
            assistant_message=Message(role="assistant"),
        )

    assert fake_client.responses.create.call_count == 1
    _, kwargs = fake_client.responses.create.call_args
    assert "previous_response_id" not in kwargs


@pytest.mark.asyncio
async def test_ainvoke_valid_previous_response_id_no_retry():
    model = OpenAIResponses(id="o4-mini")
    fake_client = _make_fake_client()
    fake_client.responses.create = AsyncMock(return_value=_InvokeFakeResponse(_id="resp_new"))
    model.async_client = fake_client

    result = await model.ainvoke(
        messages=_history_with_previous_response_id(),
        assistant_message=Message(role="assistant"),
    )

    assert result is not None
    assert fake_client.responses.create.call_count == 1
    _, kwargs = fake_client.responses.create.call_args
    assert kwargs.get("previous_response_id") == "resp_stale"


@pytest.mark.asyncio
async def test_ainvoke_invalid_previous_response_id_retries_with_full_history():
    model = OpenAIResponses(id="o4-mini")
    fake_client = _make_fake_client()
    fake_client.responses.create = AsyncMock(
        side_effect=[
            _previous_response_not_found_error("resp_stale"),
            _InvokeFakeResponse(_id="resp_recovered", output_text="recovered"),
        ]
    )
    model.async_client = fake_client

    result = await model.ainvoke(
        messages=_history_with_previous_response_id(),
        assistant_message=Message(role="assistant"),
    )

    assert result is not None
    assert result.provider_data is not None
    assert result.provider_data.get("response_id") == "resp_recovered"
    assert fake_client.responses.create.call_count == 2

    first_kwargs = fake_client.responses.create.call_args_list[0].kwargs
    second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
    assert first_kwargs.get("previous_response_id") == "resp_stale"
    assert "previous_response_id" not in second_kwargs

    second_input = second_kwargs.get("input") or []
    assert any(isinstance(item, dict) and item.get("role") == "developer" for item in second_input)
    assert any(
        isinstance(item, dict) and item.get("role") == "user" and item.get("content") == "first question"
        for item in second_input
    )


@pytest.mark.asyncio
async def test_ainvoke_non_reasoning_model_never_retries_on_previous_response_error():
    model = OpenAIResponses(id="gpt-4.1-mini")
    fake_client = _make_fake_client()
    fake_client.responses.create = AsyncMock(side_effect=_previous_response_not_found_error("resp_stale"))
    model.async_client = fake_client

    with pytest.raises(ModelProviderError):
        await model.ainvoke(
            messages=_history_with_previous_response_id(),
            assistant_message=Message(role="assistant"),
        )

    assert fake_client.responses.create.call_count == 1
    _, kwargs = fake_client.responses.create.call_args
    assert "previous_response_id" not in kwargs


def _history_with_tool_call_and_previous_response_id() -> List[Message]:
    tool_call_msg = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "fc_abc",
                "call_id": "call_abc",
                "type": "function",
                "function": {"name": "do_it", "arguments": "{}"},
            }
        ],
    )
    prev = Message(role="assistant", content="prior")
    prev.provider_data = {"response_id": "resp_stale"}  # type: ignore[attr-defined]
    return [
        Message(role="user", content="q1"),
        tool_call_msg,
        Message(role="tool", tool_call_id="fc_abc", content="result"),
        prev,
        Message(role="user", content="q2"),
    ]


class _AsyncEmptyStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def test_invoke_stale_id_resends_function_call_items():
    model = OpenAIResponses(id="gpt-5.4-mini")
    fake_client = _make_fake_client()
    fake_client.responses.create.side_effect = [
        _previous_response_not_found_error("resp_stale"),
        _InvokeFakeResponse(_id="resp_recovered"),
    ]
    model.client = fake_client

    model.invoke(
        messages=_history_with_tool_call_and_previous_response_id(),
        assistant_message=Message(role="assistant"),
    )

    assert fake_client.responses.create.call_count == 2
    second_input = fake_client.responses.create.call_args_list[1].kwargs.get("input") or []
    fc_items = [x for x in second_input if isinstance(x, dict) and x.get("type") == "function_call"]
    assert len(fc_items) == 1
    assert fc_items[0]["id"] == "fc_abc"


def test_invoke_stream_stale_id_retries_without_previous_response_id():
    model = OpenAIResponses(id="gpt-5.4-mini")
    fake_client = _make_fake_client()
    fake_client.responses.create.side_effect = [
        _previous_response_not_found_error("resp_stale"),
        iter([]),
    ]
    model.client = fake_client

    list(
        model.invoke_stream(
            messages=_history_with_previous_response_id(),
            assistant_message=Message(role="assistant"),
        )
    )

    assert fake_client.responses.create.call_count == 2
    first_kwargs = fake_client.responses.create.call_args_list[0].kwargs
    second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
    assert first_kwargs.get("previous_response_id") == "resp_stale"
    assert "previous_response_id" not in second_kwargs


@pytest.mark.asyncio
async def test_ainvoke_stream_stale_id_retries_without_previous_response_id():
    model = OpenAIResponses(id="gpt-5.4-mini")
    fake_client = _make_fake_client()
    fake_client.responses.create = AsyncMock(
        side_effect=[
            _previous_response_not_found_error("resp_stale"),
            _AsyncEmptyStream(),
        ]
    )
    model.async_client = fake_client

    chunks = [
        chunk
        async for chunk in model.ainvoke_stream(
            messages=_history_with_previous_response_id(),
            assistant_message=Message(role="assistant"),
        )
    ]

    assert chunks == []
    assert fake_client.responses.create.call_count == 2
    second_kwargs = fake_client.responses.create.call_args_list[1].kwargs
    assert "previous_response_id" not in second_kwargs


def test_detector_matches_error_carried_only_in_response_body():
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    # Empty exception message; the detail lives only in the JSON body.
    response = httpx.Response(
        400, json={"error": {"message": "Previous response with id 'resp_x' not found."}}, request=request
    )
    exc = APIStatusError("", response=response, body=None)
    assert OpenAIResponses._is_previous_response_not_found_error(exc) is True


def test_recovery_drops_user_supplied_previous_response_id():
    model = OpenAIResponses(id="gpt-5.4-mini", request_params={"previous_response_id": "resp_user"})
    params = model.get_request_params(
        messages=_history_with_previous_response_id(),
        use_previous_response_id=False,
    )
    assert "previous_response_id" not in params
