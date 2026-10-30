"""Unit tests for Mistral request and client params: the sampling parameters supported by the
Mistral chat-completions API are forwarded via get_request_params, zero values are not silently
dropped, and client/request kwargs are ones the mistralai SDK accepts."""

import inspect
import warnings
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

pytest.importorskip("mistralai")

from mistralai.client import Mistral as MistralClient
from mistralai.client.utils.retries import BackoffStrategy, RetryConfig
from mistralai.extra import response_format_from_pydantic_model

from agno.knowledge.embedder.mistral import MistralEmbedder
from agno.models.message import Message
from agno.models.mistral.mistral import MistralChat


def test_mistral_sampling_params_in_request_params():
    model = MistralChat(
        id="mistral-small-latest",
        frequency_penalty=0.5,
        presence_penalty=0.25,
        stop=["STOP"],
    )

    request_params = model.get_request_params()

    assert request_params["frequency_penalty"] == 0.5
    assert request_params["presence_penalty"] == 0.25
    assert request_params["stop"] == ["STOP"]


def test_mistral_sampling_params_omitted_when_not_provided():
    model = MistralChat(id="mistral-small-latest")

    request_params = model.get_request_params()

    assert "frequency_penalty" not in request_params
    assert "presence_penalty" not in request_params
    assert "stop" not in request_params


def test_mistral_request_params_can_override_sampling_params():
    model = MistralChat(
        id="mistral-small-latest",
        frequency_penalty=0.5,
        request_params={"frequency_penalty": 1.0},
    )

    request_params = model.get_request_params()

    assert request_params["frequency_penalty"] == 1.0


def test_mistral_to_dict_includes_sampling_params():
    model = MistralChat(
        id="mistral-small-latest",
        top_p=0.9,
        frequency_penalty=0.5,
        presence_penalty=0.25,
        stop=["STOP"],
    )

    model_dict = model.to_dict()

    assert model_dict["top_p"] == 0.9
    assert model_dict["frequency_penalty"] == 0.5
    assert model_dict["presence_penalty"] == 0.25
    assert model_dict["stop"] == ["STOP"]


# =============================================================================
# temperature / top_p / random_seed / penalties: zero values must not be dropped
# =============================================================================


def test_mistral_temperature_zero_included():
    """temperature=0.0 must appear in request params (falsy-check regression)."""
    model = MistralChat(id="mistral-small-latest", temperature=0.0)
    params = model.get_request_params()
    assert "temperature" in params
    assert params["temperature"] == 0.0


def test_mistral_top_p_zero_included():
    """top_p=0.0 must appear in request params (falsy-check regression)."""
    model = MistralChat(id="mistral-small-latest", top_p=0.0)
    params = model.get_request_params()
    assert "top_p" in params
    assert params["top_p"] == 0.0


def test_mistral_random_seed_zero_included():
    """random_seed=0 must appear in request params (falsy-check regression)."""
    model = MistralChat(id="mistral-small-latest", random_seed=0)
    params = model.get_request_params()
    assert "random_seed" in params
    assert params["random_seed"] == 0


def test_mistral_frequency_penalty_zero_included():
    """frequency_penalty=0.0 must appear in request params (falsy-check regression)."""
    model = MistralChat(id="mistral-small-latest", frequency_penalty=0.0)
    params = model.get_request_params()
    assert "frequency_penalty" in params
    assert params["frequency_penalty"] == 0.0


def test_mistral_presence_penalty_zero_included():
    """presence_penalty=0.0 must appear in request params (falsy-check regression)."""
    model = MistralChat(id="mistral-small-latest", presence_penalty=0.0)
    params = model.get_request_params()
    assert "presence_penalty" in params
    assert params["presence_penalty"] == 0.0


def test_mistral_temperature_none_excluded():
    """Unset temperature (None) must not appear in request params."""
    model = MistralChat(id="mistral-small-latest")
    params = model.get_request_params()
    assert "temperature" not in params


def test_mistral_top_p_none_excluded():
    """Unset top_p (None) must not appear in request params."""
    model = MistralChat(id="mistral-small-latest")
    params = model.get_request_params()
    assert "top_p" not in params


def test_mistral_positive_temperature_included():
    """Positive temperature is still forwarded correctly."""
    model = MistralChat(id="mistral-small-latest", temperature=0.7)
    params = model.get_request_params()
    assert params["temperature"] == 0.7


def test_mistral_all_sampling_params_zero():
    """All sampling params at zero must all appear in request params."""
    model = MistralChat(
        id="mistral-small-latest",
        temperature=0.0,
        top_p=0.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
    )
    params = model.get_request_params()
    assert params["temperature"] == 0.0
    assert params["top_p"] == 0.0
    assert params["frequency_penalty"] == 0.0
    assert params["presence_penalty"] == 0.0


# =============================================================================
# client params: agno fields map onto the mistralai.client.Mistral constructor
# =============================================================================


def test_mistral_get_client_maps_endpoint_and_timeout():
    model = MistralChat(api_key="test-key", endpoint="https://example.test", timeout=5)

    client = model.get_client()

    assert client.sdk_configuration.server_url == "https://example.test"
    assert client.sdk_configuration.timeout_ms == 5000


def test_mistral_max_retries_warns_and_client_builds():
    with pytest.warns(DeprecationWarning, match="max_retries"):
        model = MistralChat(api_key="test-key", max_retries=3)

    assert isinstance(model.get_client(), MistralClient)


def test_mistral_client_params_override_mapped_params():
    retry_config = RetryConfig("backoff", BackoffStrategy(1, 50, 1.1, 100), False)
    model = MistralChat(
        api_key="test-key",
        timeout=5,
        client_params={"timeout_ms": 1234, "retry_config": retry_config},
    )

    client = model.get_client()

    assert client.sdk_configuration.timeout_ms == 1234
    assert client.sdk_configuration.retry_config is retry_config


def test_mistral_default_construction_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        MistralChat(api_key="test-key")
        MistralEmbedder(api_key="test-key")


# =============================================================================
# safe_mode: legacy alias for safe_prompt, the only kwarg the SDK accepts
# =============================================================================


def test_mistral_safe_mode_aliases_safe_prompt():
    with pytest.warns(DeprecationWarning, match="safe_mode"):
        model = MistralChat(id="mistral-small-latest", safe_mode=True)

    params = model.get_request_params()

    assert "safe_mode" not in params
    assert params["safe_prompt"] is True


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_mistral_request_params_accepted_by_sdk_chat_methods():
    model = MistralChat(api_key="test-key", safe_mode=True, safe_prompt=True, temperature=0.1, stop=["STOP"])
    client = model.get_client()
    params = model.get_request_params()

    for method in (client.chat.complete, client.chat.stream, client.chat.complete_async, client.chat.stream_async):
        inspect.signature(method).bind(model=model.id, messages=[], **params)


# =============================================================================
# response_format: a Pydantic output schema reaches streaming and non-streaming calls
# =============================================================================


class MovieScript(BaseModel):
    title: str
    genre: str


async def _no_chunks():
    return
    yield


def _model_with_mock_client() -> MistralChat:
    client = MagicMock()
    client.chat.stream.return_value = iter([])
    client.chat.stream_async = AsyncMock(return_value=_no_chunks())
    client.chat.complete_async = AsyncMock()
    model = MistralChat(id="mistral-small-latest", mistral_client=client)
    model._parse_provider_response = MagicMock()  # type: ignore[method-assign]
    return model


def _invoke_kwargs(response_format=None):
    return {
        "messages": [Message(role="user", content="hi")],
        "assistant_message": Message(role="assistant"),
        "response_format": response_format,
    }


def test_mistral_invoke_stream_sends_pydantic_response_format():
    model = _model_with_mock_client()

    list(model.invoke_stream(**_invoke_kwargs(MovieScript)))

    sent = model.mistral_client.chat.stream.call_args.kwargs  # type: ignore[union-attr]
    assert sent["response_format"] == response_format_from_pydantic_model(MovieScript)


@pytest.mark.asyncio
async def test_mistral_ainvoke_stream_sends_pydantic_response_format():
    model = _model_with_mock_client()

    async for _ in model.ainvoke_stream(**_invoke_kwargs(MovieScript)):
        pass

    sent = model.mistral_client.chat.stream_async.call_args.kwargs  # type: ignore[union-attr]
    assert sent["response_format"] == response_format_from_pydantic_model(MovieScript)


def test_mistral_invoke_sends_pydantic_response_format():
    model = _model_with_mock_client()

    model.invoke(**_invoke_kwargs(MovieScript))

    sent = model.mistral_client.chat.complete.call_args.kwargs  # type: ignore[union-attr]
    assert sent["response_format"] == response_format_from_pydantic_model(MovieScript)


@pytest.mark.asyncio
async def test_mistral_ainvoke_sends_pydantic_response_format():
    model = _model_with_mock_client()

    await model.ainvoke(**_invoke_kwargs(MovieScript))

    sent = model.mistral_client.chat.complete_async.call_args.kwargs  # type: ignore[union-attr]
    assert sent["response_format"] == response_format_from_pydantic_model(MovieScript)


def test_mistral_stream_without_output_schema_omits_response_format():
    model = _model_with_mock_client()

    list(model.invoke_stream(**_invoke_kwargs()))

    assert "response_format" not in model.mistral_client.chat.stream.call_args.kwargs  # type: ignore[union-attr]


# =============================================================================
# MistralEmbedder client params
# =============================================================================


def test_mistral_embedder_client_maps_endpoint_and_timeout():
    embedder = MistralEmbedder(api_key="test-key", endpoint="https://example.test", timeout=5)

    client = embedder.client

    assert client.sdk_configuration.server_url == "https://example.test"
    assert client.sdk_configuration.timeout_ms == 5000


def test_mistral_embedder_max_retries_warns_and_client_builds():
    with pytest.warns(DeprecationWarning, match="max_retries"):
        embedder = MistralEmbedder(api_key="test-key", max_retries=3)

    assert isinstance(embedder.client, MistralClient)
