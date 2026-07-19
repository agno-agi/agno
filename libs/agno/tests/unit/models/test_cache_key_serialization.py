"""Tests for model cache key generation with non-serializable objects.

Verifies that _get_model_cache_key handles Pydantic model classes (ModelMetaclass)
and Pydantic model instances without raising TypeError.

Regression test for: https://github.com/agno-agi/agno/issues/7126
"""

import os

from pydantic import BaseModel

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
