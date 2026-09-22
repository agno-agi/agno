from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from agno.exceptions import ContextWindowExceededError, ModelProviderError
from agno.models.aws import AwsBedrock
from agno.models.message import Message


def _overflow_error(with_status: bool = True) -> ClientError:
    response = {
        "Error": {"Code": "ValidationException", "Message": "Input is too long for requested model."},
    }
    if with_status:
        response["ResponseMetadata"] = {"HTTPStatusCode": 400}
    return ClientError(response, "Converse")


def _model(retries: int = 2) -> AwsBedrock:
    return AwsBedrock(
        id="anthropic.claude-3-5-sonnet-20241022-v2:0",
        aws_access_key_id="key",
        aws_secret_access_key="secret",
        aws_region="us-east-1",
        retries=retries,
        delay_between_retries=0,
    )


def _invoke_kwargs():
    return {"messages": [Message(role="user", content="hi")], "assistant_message": Message(role="assistant")}


class TestBedrockContextOverflow:
    def test_status_code_is_propagated_from_client_error(self):
        model = _model()
        client = MagicMock()
        client.converse.side_effect = _overflow_error()

        with patch.object(AwsBedrock, "get_client", return_value=client):
            with pytest.raises(ModelProviderError) as exc_info:
                model.invoke(**_invoke_kwargs())

        assert exc_info.value.status_code == 400

    def test_missing_response_metadata_defaults_to_502(self):
        model = _model()
        client = MagicMock()
        client.converse.side_effect = _overflow_error(with_status=False)

        with patch.object(AwsBedrock, "get_client", return_value=client):
            with pytest.raises(ModelProviderError) as exc_info:
                model.invoke(**_invoke_kwargs())

        assert exc_info.value.status_code == 502

    def test_overflow_is_classified_and_not_retried(self):
        model = _model(retries=2)
        client = MagicMock()
        client.converse.side_effect = _overflow_error()

        with patch.object(AwsBedrock, "get_client", return_value=client):
            with pytest.raises(ContextWindowExceededError) as exc_info:
                model._invoke_with_retry(**_invoke_kwargs())

        assert exc_info.value.status_code == 400
        assert client.converse.call_count == 1

    @pytest.mark.asyncio
    async def test_async_overflow_is_classified_and_not_retried(self):
        client = MagicMock()

        async def converse(**kwargs):
            raise _overflow_error()

        client.converse = MagicMock(side_effect=converse)
        model = _model(retries=2)
        model.async_client = client

        with pytest.raises(ContextWindowExceededError) as exc_info:
            await model._ainvoke_with_retry(**_invoke_kwargs())

        assert exc_info.value.status_code == 400
        assert client.converse.call_count == 1
