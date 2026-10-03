"""Tests for model cache key generation with non-serializable objects.

Verifies that _get_model_cache_key handles Pydantic model classes (ModelMetaclass)
and Pydantic model instances without raising TypeError.

Regression test for: https://github.com/agno-agi/agno/issues/7126
"""

import json
import os

import httpx
import pytest
from pydantic import BaseModel, create_model

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat


class DummyResponseFormat(BaseModel):
    answer: str
    confidence: float


class TestCacheKeySerialization:
    def setup_method(self):
        self.model = OpenAIChat(id="gpt-4o")
        self.messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello"),
        ]

    def test_cache_key_with_class_type_response_format(self):
        """Passing a Pydantic class (ModelMetaclass) as response_format should not raise."""
        key = self.model._get_model_cache_key(self.messages, stream=False, response_format=DummyResponseFormat)
        assert isinstance(key, str)
        assert len(key) == 32  # md5 hex digest

    def test_cache_key_with_pydantic_instance_response_format(self):
        """Passing a Pydantic model instance as response_format should not raise."""
        instance = DummyResponseFormat(answer="test", confidence=0.9)
        key = self.model._get_model_cache_key(self.messages, stream=False, response_format=instance)
        assert isinstance(key, str)
        assert len(key) == 32

    def test_cache_key_deterministic(self):
        """Same inputs should produce the same cache key."""
        key1 = self.model._get_model_cache_key(self.messages, stream=False, response_format=DummyResponseFormat)
        key2 = self.model._get_model_cache_key(self.messages, stream=False, response_format=DummyResponseFormat)
        assert key1 == key2

    def test_cache_key_differs_for_different_response_formats(self):
        """Different response_format values should produce different keys."""
        key_with_class = self.model._get_model_cache_key(
            self.messages, stream=False, response_format=DummyResponseFormat
        )
        key_without = self.model._get_model_cache_key(self.messages, stream=False, response_format=None)
        assert key_with_class != key_without

    @pytest.mark.parametrize("stream", [False, True])
    def test_same_named_response_formats_have_distinct_cache_keys(self, stream):
        first_format = create_model("Output", answer=(str, ...))
        second_format = create_model("Output", count=(int, ...))
        first_key = self.model._get_model_cache_key(self.messages, stream=stream, response_format=first_format)
        second_key = self.model._get_model_cache_key(self.messages, stream=stream, response_format=second_format)

        assert first_key != second_key

    @pytest.mark.parametrize("stream", [False, True])
    def test_equivalent_response_schemas_share_cache_keys(self, stream):
        first_format = create_model("Output", answer=(str, ...))
        equivalent_format = create_model("Output", answer=(str, ...))

        assert self.model._get_model_cache_key(
            self.messages, stream=stream, response_format=first_format
        ) == self.model._get_model_cache_key(self.messages, stream=stream, response_format=equivalent_format)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_response_cache_does_not_replay_another_same_named_schema(tmp_path, asynchronous):
    first_format = create_model("Output", answer=(str, ...))
    second_format = create_model("Output", count=(int, ...))
    requested_fields = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        properties = body["response_format"]["json_schema"]["schema"]["properties"]
        requested_fields.append(list(properties))
        content = {"answer": "sample"} if "answer" in properties else {"count": 2}
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(content)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as sync_client:
        async with httpx.AsyncClient(transport=transport) as async_client:
            model = OpenAIChat(
                id="test-model",
                api_key="test-key",
                cache_response=True,
                cache_dir=str(tmp_path),
                http_client=async_client if asynchronous else sync_client,
            )
            for response_format, expected in [
                (first_format, {"answer": "sample"}),
                (second_format, {"count": 2}),
                (first_format, {"answer": "sample"}),
            ]:
                messages = [Message(role="user", content="Return the requested result")]
                if asynchronous:
                    result = await model.aresponse(messages, response_format=response_format)
                else:
                    result = model.response(messages, response_format=response_format)
                assert json.loads(result.content) == expected

    assert requested_fields == [["answer"], ["count"]]
    assert len(list(tmp_path.glob("*.json"))) == 2
