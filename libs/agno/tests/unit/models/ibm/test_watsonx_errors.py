from unittest.mock import MagicMock, patch

import httpx
import pytest

pytest.importorskip("ibm_watsonx_ai")

from ibm_watsonx_ai.wml_client_error import ApiRequestFailure  # noqa: E402

from agno.exceptions import ContextWindowExceededError, ModelProviderError  # noqa: E402
from agno.models.ibm import WatsonX  # noqa: E402
from agno.models.message import Message  # noqa: E402

OVERFLOW_MESSAGE = "the number of input tokens 9000 cannot exceed the total tokens limit 8192 for this model"


def _overflow_error() -> ApiRequestFailure:
    request = httpx.Request("POST", "https://eu-de.ml.cloud.ibm.com/ml/v1/text/chat")
    response = httpx.Response(400, request=request, text=OVERFLOW_MESSAGE)
    return ApiRequestFailure("Failure during chat", response)


def _model(retries: int = 2) -> WatsonX:
    return WatsonX(
        id="ibm/granite-3-8b-instruct", api_key="key", project_id="project", retries=retries, delay_between_retries=0
    )


def _invoke_kwargs():
    return {"messages": [Message(role="user", content="hi")], "assistant_message": Message(role="assistant")}


class TestWatsonXContextOverflow:
    def test_status_code_is_propagated_from_api_request_failure(self):
        model = _model()
        client = MagicMock()
        client.chat.side_effect = _overflow_error()

        with patch.object(WatsonX, "get_client", return_value=client):
            with pytest.raises(ModelProviderError) as exc_info:
                model.invoke(**_invoke_kwargs())

        assert exc_info.value.status_code == 400

    def test_plain_exception_defaults_to_502(self):
        model = _model()
        client = MagicMock()
        client.chat.side_effect = RuntimeError("boom")

        with patch.object(WatsonX, "get_client", return_value=client):
            with pytest.raises(ModelProviderError) as exc_info:
                model.invoke(**_invoke_kwargs())

        assert exc_info.value.status_code == 502

    def test_overflow_is_classified_and_not_retried(self):
        model = _model(retries=2)
        client = MagicMock()
        client.chat.side_effect = _overflow_error()

        with patch.object(WatsonX, "get_client", return_value=client):
            with pytest.raises(ContextWindowExceededError) as exc_info:
                model._invoke_with_retry(**_invoke_kwargs())

        assert exc_info.value.status_code == 400
        assert client.chat.call_count == 1

    @pytest.mark.asyncio
    async def test_async_overflow_is_classified_and_not_retried(self):
        model = _model(retries=2)
        client = MagicMock()

        async def achat(**kwargs):
            raise _overflow_error()

        client.achat = MagicMock(side_effect=achat)

        with patch.object(WatsonX, "get_client", return_value=client):
            with pytest.raises(ContextWindowExceededError) as exc_info:
                await model._ainvoke_with_retry(**_invoke_kwargs())

        assert exc_info.value.status_code == 400
        assert client.achat.call_count == 1
