"""Unit tests for HuggingFace client and request params: every field the model documents is
either a kwarg the huggingface_hub SDK accepts or is deprecated and ignored, so constructing a
client and binding a chat request never raises TypeError."""

import inspect
import warnings

import pytest

pytest.importorskip("huggingface_hub")

from huggingface_hub import (
    AsyncInferenceClient,
    ChatCompletionStreamOutput,
    ChatCompletionStreamOutputChoice,
    ChatCompletionStreamOutputDelta,
    ChatCompletionStreamOutputDeltaToolCall,
    ChatCompletionStreamOutputFunction,
    InferenceClient,
)

from agno.models.huggingface import HuggingFace

# =============================================================================
# Client params: InferenceClient takes headers, not default_headers, and has
# no counterpart for max_retries or default_query.
# =============================================================================


def test_huggingface_default_headers_map_to_headers():
    model = HuggingFace(api_key="test-key", default_headers={"X-Team": "agno"})

    assert model.get_client_params()["headers"] == {"X-Team": "agno"}
    assert "default_headers" not in model.get_client_params()


def test_huggingface_max_retries_warns_and_client_builds():
    with pytest.warns(DeprecationWarning, match="max_retries"):
        model = HuggingFace(api_key="test-key", max_retries=3)

    assert "max_retries" not in model.get_client_params()
    assert isinstance(model.get_client(), InferenceClient)


def test_huggingface_default_query_warns_and_client_builds():
    with pytest.warns(DeprecationWarning, match="default_query"):
        model = HuggingFace(api_key="test-key", default_query={"q": "1"})

    assert "default_query" not in model.get_client_params()
    assert isinstance(model.get_client(), InferenceClient)


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_huggingface_async_client_builds_with_every_documented_field():
    model = HuggingFace(
        api_key="test-key",
        base_url="https://example.test",
        timeout=5,
        max_retries=3,
        default_headers={"X-Team": "agno"},
        default_query={"q": "1"},
    )

    assert isinstance(model.get_async_client(), AsyncInferenceClient)


def test_huggingface_client_params_override_mapped_params():
    model = HuggingFace(api_key="test-key", timeout=5, client_params={"timeout": 60, "cookies": {"session": "abc"}})

    client_params = model.get_client_params()

    assert client_params["timeout"] == 60
    assert client_params["cookies"] == {"session": "abc"}
    assert isinstance(model.get_client(), InferenceClient)


def test_huggingface_default_construction_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        HuggingFace(api_key="test-key")


# =============================================================================
# store: chat_completion() has no such argument, so it rides in the body
# =============================================================================


def test_huggingface_store_moves_into_extra_body():
    model = HuggingFace(id="meta-llama/Llama-3.1-8B-Instruct", api_key="test-key", store=True)

    params = model.get_request_params()

    assert "store" not in params
    assert params["extra_body"] == {"store": True}


def test_huggingface_store_false_is_still_sent():
    model = HuggingFace(id="meta-llama/Llama-3.1-8B-Instruct", api_key="test-key", store=False)

    assert model.get_request_params()["extra_body"] == {"store": False}


def test_huggingface_store_merges_with_a_caller_supplied_extra_body():
    model = HuggingFace(
        id="meta-llama/Llama-3.1-8B-Instruct",
        api_key="test-key",
        store=True,
        request_params={"extra_body": {"guided_json": {"type": "object"}}},
    )

    extra_body = model.get_request_params()["extra_body"]

    assert extra_body == {"store": True, "guided_json": {"type": "object"}}


def test_a_caller_supplied_store_outranks_the_model_field():
    model = HuggingFace(
        id="meta-llama/Llama-3.1-8B-Instruct",
        api_key="test-key",
        store=True,
        request_params={"extra_body": {"store": False}},
    )

    assert model.get_request_params()["extra_body"] == {"store": False}


def test_huggingface_store_omitted_when_not_set():
    model = HuggingFace(id="meta-llama/Llama-3.1-8B-Instruct", api_key="test-key")

    params = model.get_request_params()

    assert "store" not in params
    assert "extra_body" not in params


def test_huggingface_empty_tools_omitted_from_request_params():
    model = HuggingFace(id="meta-llama/Llama-3.1-8B-Instruct", api_key="test-key")

    params = model.get_request_params(tools=[])

    assert "tools" not in params
    assert "tool_choice" not in params


# =============================================================================
# The binding check: what the model builds has to be what the SDK accepts.
# =============================================================================


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_every_documented_field_binds_against_the_sdk():
    model = HuggingFace(
        id="meta-llama/Llama-3.1-8B-Instruct",
        api_key="test-key",
        base_url="https://example.test",
        timeout=5,
        max_retries=3,
        default_headers={"X-Team": "agno"},
        default_query={"q": "1"},
        store=True,
        frequency_penalty=0.5,
        max_tokens=128,
        temperature=0.1,
        stop=["STOP"],
        top_p=0.9,
    )

    inspect.signature(InferenceClient.__init__).bind(None, **model.get_client_params())
    inspect.signature(AsyncInferenceClient.__init__).bind(None, **model.get_client_params())

    request_params = model.get_request_params(tools=[{"type": "function"}])
    client = model.get_client()
    for method in (client.chat.completions.create, model.get_async_client().chat.completions.create):
        inspect.signature(method).bind(model=model.id, messages=[], **request_params)


# =============================================================================
# Streaming tool calls: every call in a chunk is kept, whichever way a provider
# splits calls across chunks.
# =============================================================================


def _delta_tool_call(index, id=None, name=None, arguments=""):
    # Providers send id and type only on the first piece of a call, as the SDK surfaces them here.
    return ChatCompletionStreamOutputDeltaToolCall(
        index=index,
        id=id,
        type="function" if id else None,
        function=ChatCompletionStreamOutputFunction(name=name, arguments=arguments),
    )


def _build_tool_calls(*chunks):
    """Run tool call chunks through the same delta parsing and assembly a streaming run uses."""
    model = HuggingFace(id="meta-llama/Llama-3.1-8B-Instruct", api_key="test-key")
    streamed_tool_calls = []
    for tool_calls in chunks:
        chunk = ChatCompletionStreamOutput(
            id="chatcmpl-1",
            choices=[
                ChatCompletionStreamOutputChoice(
                    index=0,
                    delta=ChatCompletionStreamOutputDelta(role="assistant", tool_calls=tool_calls),
                )
            ],
            created=0,
            model=model.id,
            system_fingerprint="",
        )
        streamed_tool_calls.extend(model._parse_provider_response_delta(chunk).tool_calls)
    return model.parse_tool_calls(streamed_tool_calls)


def _expected_tool_call(id, name, arguments):
    return {"id": id, "type": "function", "function": {"name": name, "arguments": arguments}}


def test_huggingface_stream_keeps_every_whole_call_in_one_chunk():
    parsed = _build_tool_calls(
        [
            _delta_tool_call(0, "call_1", "get_weather", '{"city": "Paris"}'),
            _delta_tool_call(1, "call_2", "get_time", '{"tz": "UTC"}'),
        ]
    )

    assert parsed == [
        _expected_tool_call("call_1", "get_weather", '{"city": "Paris"}'),
        _expected_tool_call("call_2", "get_time", '{"tz": "UTC"}'),
    ]


def test_huggingface_stream_joins_calls_split_across_shared_chunks():
    parsed = _build_tool_calls(
        [
            _delta_tool_call(0, "call_1", "search", '{"q": '),
            _delta_tool_call(1, "call_2", "fetch", '{"url": '),
        ],
        [
            _delta_tool_call(0, arguments='"agno"}'),
            _delta_tool_call(1, arguments='"https://agno.com"}'),
        ],
    )

    assert parsed == [
        _expected_tool_call("call_1", "search", '{"q": "agno"}'),
        _expected_tool_call("call_2", "fetch", '{"url": "https://agno.com"}'),
    ]


def test_huggingface_stream_keeps_a_call_starting_in_the_chunk_that_ends_the_previous_one():
    # Keeping only the first entry of the middle chunk loses call_2's id, type and name, and the
    # follow-up request is then rejected for carrying a tool call with type None.
    parsed = _build_tool_calls(
        [_delta_tool_call(0, "call_1", "get_weather", '{"city": ')],
        [
            _delta_tool_call(0, arguments='"Paris"}'),
            _delta_tool_call(1, "call_2", "get_weather", '{"city": '),
        ],
        [_delta_tool_call(1, arguments='"Tokyo"}')],
    )

    assert parsed == [
        _expected_tool_call("call_1", "get_weather", '{"city": "Paris"}'),
        _expected_tool_call("call_2", "get_weather", '{"city": "Tokyo"}'),
    ]


def test_huggingface_parse_tool_calls_rejects_a_missing_index_instead_of_merging_calls():
    # Treating a missing index as 0 would join separate calls into one with invalid JSON arguments.
    with pytest.raises(TypeError):
        HuggingFace.parse_tool_calls(
            [
                _delta_tool_call(None, "call_1", "get_weather", '{"city": "Paris"}'),
                _delta_tool_call(None, "call_2", "get_weather", '{"city": "Tokyo"}'),
            ]
        )
