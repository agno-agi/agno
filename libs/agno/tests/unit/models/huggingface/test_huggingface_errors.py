from unittest.mock import MagicMock, patch

import httpx
import pytest
from huggingface_hub.errors import HfHubHTTPError

from agno.exceptions import ContextWindowExceededError, ModelProviderError
from agno.models.huggingface import HuggingFace
from agno.models.message import Message

OVERFLOW_MESSAGE = (
    "Input validation error: `inputs` tokens + `max_new_tokens` must be <= 4096. "
    "Given: 4500 `inputs` tokens and 512 `max_new_tokens`"
)


def _overflow_error(status_code: int = 422) -> HfHubHTTPError:
    request = httpx.Request("POST", "https://router.huggingface.co/v1/chat/completions")
    response = httpx.Response(status_code, request=request, text=OVERFLOW_MESSAGE)
    return HfHubHTTPError(OVERFLOW_MESSAGE, response=response)


def _model(retries: int = 2) -> HuggingFace:
    return HuggingFace(
        id="meta-llama/Llama-3.1-8B-Instruct", api_key="hf_test", retries=retries, delay_between_retries=0
    )


def _invoke_kwargs():
    return {"messages": [Message(role="user", content="hi")], "assistant_message": Message(role="assistant")}


class TestHuggingFaceContextOverflow:
    def test_status_code_is_propagated_from_http_error(self):
        model = _model()
        client = MagicMock()
        client.chat.completions.create.side_effect = _overflow_error()

        with patch.object(HuggingFace, "get_client", return_value=client):
            with pytest.raises(ModelProviderError) as exc_info:
                model.invoke(**_invoke_kwargs())

        assert exc_info.value.status_code == 422

    def test_overflow_is_classified_and_not_retried(self):
        model = _model(retries=2)
        client = MagicMock()
        client.chat.completions.create.side_effect = _overflow_error()

        with patch.object(HuggingFace, "get_client", return_value=client):
            with pytest.raises(ContextWindowExceededError) as exc_info:
                model._invoke_with_retry(**_invoke_kwargs())

        assert exc_info.value.status_code == 422
        assert client.chat.completions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_async_overflow_is_classified_and_not_retried(self):
        model = _model(retries=2)
        client = MagicMock()

        async def create(**kwargs):
            raise _overflow_error()

        client.chat.completions.create = MagicMock(side_effect=create)

        with patch.object(HuggingFace, "get_async_client", return_value=client):
            with pytest.raises(ContextWindowExceededError) as exc_info:
                await model._ainvoke_with_retry(**_invoke_kwargs())

        assert exc_info.value.status_code == 422
        assert client.chat.completions.create.call_count == 1
