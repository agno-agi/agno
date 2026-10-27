"""Unit tests for HuggingFace client and request params: every field the model documents is
either a kwarg the huggingface_hub SDK accepts or is deprecated and ignored, so constructing a
client and binding a chat request never raises TypeError."""

import inspect
import warnings

import pytest

pytest.importorskip("huggingface_hub")

from huggingface_hub import AsyncInferenceClient, InferenceClient

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
