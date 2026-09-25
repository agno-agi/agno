"""Response storage and automatic conversation chaining are independent choices."""

import json

import httpx
import pytest
from openai import AsyncOpenAI, OpenAI

from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses


@pytest.fixture
def response_client():
    requests = []
    response = {
        "id": "resp_current",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.6-luna",
        "status": "completed",
        "error": None,
        "usage": None,
        "output": [
            {"type": "reasoning", "id": "rs_current", "summary": [], "encrypted_content": "encrypted-reasoning"},
            {
                "type": "function_call",
                "id": "fc_current",
                "call_id": "call_current",
                "name": "lookup",
                "arguments": "{}",
                "status": "completed",
            },
        ],
    }

    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if payload.get("stream"):
            events = [
                {"type": "response.created", "response": response},
                {"type": "response.output_item.added", "output_index": 1, "item": response["output"][1]},
                {"type": "response.output_item.done", "output_index": 1, "item": response["output"][1]},
                {"type": "response.completed", "response": response},
            ]
            body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=response)

    return requests, httpx.MockTransport(handle)


async def _invoke(model, mode, messages):
    assistant = Message(role="assistant")
    if mode == "sync":
        results = [model.invoke(messages, assistant)]
    elif mode == "async":
        results = [await model.ainvoke(messages, assistant)]
    elif mode == "sync_stream":
        results = list(model.invoke_stream(messages, assistant))
    else:
        results = [result async for result in model.ainvoke_stream(messages, assistant)]

    # Collect the provider state and tool calls that the next model iteration receives.
    provider_data = {}
    tool_calls = []
    for result in results:
        provider_data.update(result.provider_data or {})
        tool_calls.extend(result.tool_calls or [])
    return Message(role="assistant", provider_data=provider_data, tool_calls=tool_calls)


@pytest.mark.parametrize("mode", ["sync", "async", "sync_stream", "async_stream"])
@pytest.mark.parametrize("store", [None, True, False])
@pytest.mark.parametrize("disable_chaining", [False, True])
async def test_storage_and_chaining_on_wire(response_client, mode, store, disable_chaining):
    requests, transport = response_client
    options = {"use_previous_response_id": False} if disable_chaining else {}
    with OpenAI(api_key="test", http_client=httpx.Client(transport=transport)) as client:
        async with AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=transport)) as async_client:
            model = OpenAIResponses(id="gpt-5.6-luna", store=store, client=client, async_client=async_client, **options)
            messages = [
                Message(role="system", content="Fresh documentation for this turn"),
                Message(role="user", content="Recent question", from_history=True),
                Message(
                    role="assistant",
                    content="Recent answer",
                    provider_data={"response_id": "resp_previous"},
                    from_history=True,
                ),
                Message(role="user", content="Follow-up question"),
            ]
            await _invoke(model, mode, messages)

    payload = requests[0]
    assert payload["store"] is (store is not False)
    if not disable_chaining and store is not False:
        assert payload["previous_response_id"] == "resp_previous"
        assert payload["input"] == [{"role": "user", "content": "Follow-up question"}]
    else:
        assert "previous_response_id" not in payload
        assert [item["content"] for item in payload["input"]] == [message.content for message in messages]
        assert payload["include"].count("reasoning.encrypted_content") == 1
    assert "use_previous_response_id" not in payload


@pytest.mark.parametrize("mode", ["sync", "async", "sync_stream", "async_stream"])
async def test_stored_response_replays_reasoning_and_tool_calls(response_client, mode):
    requests, transport = response_client
    with OpenAI(api_key="test", http_client=httpx.Client(transport=transport)) as client:
        async with AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=transport)) as async_client:
            model = OpenAIResponses(
                id="gpt-5.6-luna",
                store=True,
                use_previous_response_id=False,
                include=["message.output_text.logprobs"],
                client=client,
                async_client=async_client,
            )
            messages = [
                Message(role="system", content="Fresh instructions"),
                Message(role="user", content="Look it up"),
            ]
            assistant = await _invoke(model, mode, messages)
            assert assistant.provider_data["response_id"] == "resp_current"
            assert assistant.provider_data["reasoning_output"]["encrypted_content"] == "encrypted-reasoning"
            messages.extend([assistant, Message(role="tool", tool_call_id="call_current", content="Found it")])
            await _invoke(model, mode, messages)

    assert len(requests) == 2
    for payload in requests:
        assert payload["store"] is True
        assert "previous_response_id" not in payload
        assert payload["include"] == ["message.output_text.logprobs", "reasoning.encrypted_content"]
    items = requests[1]["input"]
    assert items[:2] == [
        {"role": "developer", "content": "Fresh instructions"},
        {"role": "user", "content": "Look it up"},
    ]
    assert [item["type"] for item in items[2:]] == ["reasoning", "function_call", "function_call_output"]
    assert items[2]["encrypted_content"] == "encrypted-reasoning"
    assert items[3]["call_id"] == items[4]["call_id"] == "call_current"
    assert items[4]["output"] == "Found it"
    assert model.include == ["message.output_text.logprobs"]


def test_background_storage_does_not_enable_chaining():
    model = OpenAIResponses(id="gpt-5.6-luna", store=False, background=True, use_previous_response_id=False)
    messages = [
        Message(role="assistant", content="Earlier answer", provider_data={"response_id": "resp_previous"}),
        Message(role="user", content="Follow-up"),
    ]
    params = model.get_request_params(messages)
    assert params["store"] is True
    assert "previous_response_id" not in params
    assert len(model._format_messages(messages)) == 2


@pytest.fixture
def stale_chain_client():
    """Reject any chained request as OpenAI does for an unknown previous_response_id."""
    requests = []
    response = {
        "id": "resp_new",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.6-luna",
        "status": "completed",
        "error": None,
        "usage": None,
        "output": [
            {
                "type": "message",
                "id": "msg_new",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Recovered", "annotations": []}],
            }
        ],
    }

    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "previous_response_id" in payload:
            body = {
                "error": {
                    "message": f"Previous response with id '{payload['previous_response_id']}' not found.",
                    "type": "invalid_request_error",
                    "param": "previous_response_id",
                    "code": None,
                }
            }
            return httpx.Response(400, json=body)
        if payload.get("stream"):
            events = [
                {"type": "response.created", "response": response},
                {"type": "response.completed", "response": response},
            ]
            body_text = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(200, text=body_text, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=response)

    return requests, httpx.MockTransport(handle)


def _stale_chain_messages():
    return [
        Message(role="system", content="Instructions"),
        Message(role="user", content="Look it up", from_history=True),
        Message(
            role="assistant",
            provider_data={"response_id": "resp_stale"},
            tool_calls=[
                {
                    "id": "fc_old",
                    "call_id": "call_old",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
            from_history=True,
        ),
        Message(role="tool", tool_call_id="call_old", content="Found it", from_history=True),
        Message(role="assistant", content="Here it is", provider_data={"response_id": "resp_stale"}, from_history=True),
        Message(role="user", content="Thanks, and again?"),
    ]


@pytest.mark.parametrize("mode", ["sync", "async", "sync_stream", "async_stream"])
async def test_stale_previous_response_id_is_retried_with_replayed_context(stale_chain_client, mode):
    requests, transport = stale_chain_client
    with OpenAI(api_key="test", http_client=httpx.Client(transport=transport)) as client:
        async with AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=transport)) as async_client:
            model = OpenAIResponses(id="gpt-5.6-luna", client=client, async_client=async_client)
            messages = _stale_chain_messages()
            assistant = await _invoke(model, mode, messages)

    assert assistant.provider_data["response_id"] == "resp_new"
    assert [("previous_response_id" in payload) for payload in requests] == [True, False]
    assert requests[0]["input"] == [{"role": "user", "content": "Thanks, and again?"}]

    replayed = requests[1]["input"]
    assert [item.get("role") or item["type"] for item in replayed] == [
        "developer",
        "user",
        "function_call",
        "function_call_output",
        "assistant",
        "user",
    ]
    # The rejected ids are unknown to the server, so the replayed call must not carry one.
    assert "id" not in replayed[2]
    assert replayed[2]["call_id"] == replayed[3]["call_id"] == "call_old"
    assert requests[1]["store"] is True


@pytest.mark.parametrize("mode", ["sync", "async", "sync_stream", "async_stream"])
async def test_other_bad_requests_are_not_retried(mode):
    from agno.exceptions import ModelProviderError

    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            400, json={"error": {"message": "Invalid value for 'tools'.", "type": "invalid_request_error"}}
        )

    transport = httpx.MockTransport(handle)
    with OpenAI(api_key="test", http_client=httpx.Client(transport=transport)) as client:
        async with AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=transport)) as async_client:
            model = OpenAIResponses(id="gpt-5.6-luna", client=client, async_client=async_client)
            with pytest.raises(ModelProviderError, match="Invalid value"):
                await _invoke(model, mode, _stale_chain_messages())

    assert len(requests) == 1


async def test_missing_previous_response_is_not_retried_without_a_chain(stale_chain_client):
    """A user-supplied previous_response_id in request_params is not something Agno can recover from."""
    from agno.exceptions import ModelProviderError

    requests, transport = stale_chain_client
    with OpenAI(api_key="test", http_client=httpx.Client(transport=transport)) as client:
        model = OpenAIResponses(id="gpt-4.1-mini", client=client, request_params={"previous_response_id": "resp_user"})
        with pytest.raises(ModelProviderError, match="not found"):
            await _invoke(model, "sync", [Message(role="user", content="hi")])

    assert len(requests) == 1
