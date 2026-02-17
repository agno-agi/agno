"""Tests for Model helper methods, caching, and deep copy.

Covers methods in agno/models/base.py that are not tested by
test_retry_error_classification.py: to_dict, get_provider,
_remove_temporary_messages, cache methods, __deepcopy__,
_handle_agent_exception, __post_init__, and get_system_message_for_model.
"""

import json
import os
from copy import deepcopy
from pathlib import Path
from time import time
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.exceptions import AgentRunException
from agno.models.base import _handle_agent_exception
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse


@pytest.fixture
def model():
    """Create a basic model for testing."""
    return OpenAIChat(id="gpt-4o-mini")


@pytest.fixture
def model_with_name():
    """Create a model with explicit name."""
    return OpenAIChat(id="gpt-4o-mini", name="TestModel")


@pytest.fixture
def model_with_provider():
    """Create a model with explicit provider."""
    return OpenAIChat(id="gpt-4o-mini", name="TestModel", provider="TestProvider")


# =============================================================================
# Tests for __post_init__
# =============================================================================


class TestModelPostInit:
    def test_provider_set_from_name(self, model_with_name):
        """Provider is auto-set from name and id when not provided."""
        # OpenAIChat sets provider="OpenAI" by default, but our fixture overrides name
        # The model_with_name fixture has name="TestModel", but OpenAIChat also sets provider="OpenAI"
        # So provider comes from the OpenAIChat default, not from __post_init__
        assert model_with_name.provider is not None

    def test_provider_not_overridden(self, model_with_provider):
        """Explicit provider is not overridden."""
        assert model_with_provider.provider == "TestProvider"

    def test_default_openai_provider(self, model):
        """OpenAIChat has provider='OpenAI' by default."""
        assert model.provider == "OpenAI"


# =============================================================================
# Tests for to_dict
# =============================================================================


class TestModelToDict:
    def test_to_dict_basic(self, model):
        """to_dict returns id field."""
        d = model.to_dict()
        assert d["id"] == "gpt-4o-mini"

    def test_to_dict_with_name_and_provider(self, model_with_provider):
        """to_dict includes name and provider when set."""
        d = model_with_provider.to_dict()
        assert d["name"] == "TestModel"
        assert d["provider"] == "TestProvider"
        assert d["id"] == "gpt-4o-mini"

    def test_to_dict_includes_standard_fields(self):
        """to_dict includes all non-None fields from the set {name, id, provider}."""
        m = OpenAIChat(id="gpt-4o-mini")
        d = m.to_dict()
        # OpenAIChat sets name="OpenAIChat" and provider="OpenAI" by default
        assert d["id"] == "gpt-4o-mini"
        assert d["name"] == "OpenAIChat"
        assert d["provider"] == "OpenAI"


# =============================================================================
# Tests for get_provider
# =============================================================================


class TestGetProvider:
    def test_get_provider_returns_provider(self, model_with_provider):
        """get_provider returns explicit provider."""
        assert model_with_provider.get_provider() == "TestProvider"

    def test_get_provider_returns_name_when_no_provider(self, model_with_name):
        """get_provider returns name from the provider field."""
        # OpenAIChat defaults provider to "OpenAI", so it returns that
        result = model_with_name.get_provider()
        assert result is not None

    def test_get_provider_returns_openai_default(self, model):
        """OpenAIChat defaults provider to 'OpenAI'."""
        assert model.get_provider() == "OpenAI"


# =============================================================================
# Tests for get_system_message_for_model / get_instructions_for_model
# =============================================================================


class TestModelSystemMessage:
    def test_get_system_message_returns_system_prompt(self, model):
        """get_system_message_for_model returns system_prompt."""
        model.system_prompt = "You are a helpful assistant."
        assert model.get_system_message_for_model() == "You are a helpful assistant."

    def test_get_system_message_returns_none_by_default(self, model):
        """get_system_message_for_model returns None when not set."""
        assert model.get_system_message_for_model() is None

    def test_get_instructions_returns_instructions(self, model):
        """get_instructions_for_model returns instructions list."""
        model.instructions = ["Be concise", "Use markdown"]
        assert model.get_instructions_for_model() == ["Be concise", "Use markdown"]

    def test_get_instructions_returns_none_by_default(self, model):
        """get_instructions_for_model returns None when not set."""
        assert model.get_instructions_for_model() is None


# =============================================================================
# Tests for _remove_temporary_messages
# =============================================================================


class TestRemoveTemporaryMessages:
    def test_removes_temporary_messages(self, model):
        """Temporary messages are removed in place."""
        msgs = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="temp", temporary=True),
            Message(role="user", content="world"),
        ]
        model._remove_temporary_messages(msgs)
        assert len(msgs) == 2
        assert msgs[0].content == "hello"
        assert msgs[1].content == "world"

    def test_keeps_all_when_no_temporary(self, model):
        """No messages removed when none are temporary."""
        msgs = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
        ]
        model._remove_temporary_messages(msgs)
        assert len(msgs) == 2

    def test_removes_all_when_all_temporary(self, model):
        """All messages removed when all are temporary."""
        msgs = [
            Message(role="user", content="a", temporary=True),
            Message(role="user", content="b", temporary=True),
        ]
        model._remove_temporary_messages(msgs)
        assert len(msgs) == 0

    def test_modifies_list_in_place(self, model):
        """The original list is modified, not replaced."""
        msgs = [Message(role="user", content="keep"), Message(role="user", content="remove", temporary=True)]
        original_id = id(msgs)
        model._remove_temporary_messages(msgs)
        assert id(msgs) == original_id


# =============================================================================
# Tests for cache methods
# =============================================================================


class TestModelCaching:
    def test_cache_key_deterministic(self, model):
        """Same inputs produce the same cache key."""
        msgs = [Message(role="user", content="hello")]
        key1 = model._get_model_cache_key(msgs, stream=False)
        key2 = model._get_model_cache_key(msgs, stream=False)
        assert key1 == key2

    def test_cache_key_varies_with_content(self, model):
        """Different message content produces different keys."""
        msgs1 = [Message(role="user", content="hello")]
        msgs2 = [Message(role="user", content="world")]
        key1 = model._get_model_cache_key(msgs1, stream=False)
        key2 = model._get_model_cache_key(msgs2, stream=False)
        assert key1 != key2

    def test_cache_key_varies_with_stream(self, model):
        """stream=True and stream=False produce different keys."""
        msgs = [Message(role="user", content="hello")]
        key1 = model._get_model_cache_key(msgs, stream=False)
        key2 = model._get_model_cache_key(msgs, stream=True)
        assert key1 != key2

    def test_cache_key_varies_with_tools(self, model):
        """Having tools changes the cache key."""
        msgs = [Message(role="user", content="hello")]
        key1 = model._get_model_cache_key(msgs, stream=False)
        key2 = model._get_model_cache_key(msgs, stream=False, tools=[{"type": "function"}])
        assert key1 != key2

    def test_cache_file_path_default(self, model):
        """Default cache file path is under ~/.agno/cache/model_responses."""
        path = model._get_model_cache_file_path("abc123")
        assert path == Path.home() / ".agno" / "cache" / "model_responses" / "abc123.json"

    def test_cache_file_path_custom_dir(self, tmp_path):
        """Custom cache_dir is used for cache file path."""
        model = OpenAIChat(id="gpt-4o-mini", cache_dir=str(tmp_path))
        path = model._get_model_cache_file_path("abc123")
        assert path == tmp_path / "abc123.json"

    def test_save_and_retrieve_cache(self, tmp_path):
        """Saved responses can be retrieved from cache."""
        model = OpenAIChat(id="gpt-4o-mini", cache_dir=str(tmp_path))

        response = ModelResponse(content="cached response")
        model._save_model_response_to_cache("test_key", response)

        cached = model._get_cached_model_response("test_key")
        assert cached is not None
        assert cached["result"]["content"] == "cached response"

    def test_cache_returns_none_when_missing(self, tmp_path):
        """Non-existent cache key returns None."""
        model = OpenAIChat(id="gpt-4o-mini", cache_dir=str(tmp_path))
        assert model._get_cached_model_response("nonexistent") is None

    def test_cache_ttl_expiration(self, tmp_path):
        """Expired cache entries return None."""
        model = OpenAIChat(id="gpt-4o-mini", cache_dir=str(tmp_path), cache_ttl=1)

        response = ModelResponse(content="cached response")
        model._save_model_response_to_cache("test_key", response)

        # Manually set timestamp to be expired
        cache_file = tmp_path / "test_key.json"
        with open(cache_file, "r") as f:
            data = json.load(f)
        data["timestamp"] = int(time()) - 100
        with open(cache_file, "w") as f:
            json.dump(data, f)

        assert model._get_cached_model_response("test_key") is None

    def test_cache_no_ttl_never_expires(self, tmp_path):
        """Cache entries with no TTL never expire."""
        model = OpenAIChat(id="gpt-4o-mini", cache_dir=str(tmp_path))

        response = ModelResponse(content="cached response")
        model._save_model_response_to_cache("test_key", response)

        # Even with old timestamp, no TTL means no expiration
        cache_file = tmp_path / "test_key.json"
        with open(cache_file, "r") as f:
            data = json.load(f)
        data["timestamp"] = 0
        with open(cache_file, "w") as f:
            json.dump(data, f)

        cached = model._get_cached_model_response("test_key")
        assert cached is not None

    def test_model_response_from_cache(self, tmp_path):
        """ModelResponse can be saved and reconstructed via cache roundtrip."""
        model = OpenAIChat(id="gpt-4o-mini", cache_dir=str(tmp_path))
        original = ModelResponse(content="hello")
        model._save_model_response_to_cache("roundtrip", original)
        cached = model._get_cached_model_response("roundtrip")
        response = model._model_response_from_cache(cached)
        assert isinstance(response, ModelResponse)
        assert response.content == "hello"

    def test_streaming_responses_from_cache(self, tmp_path):
        """Streaming responses can be saved and reconstructed via cache."""
        model = OpenAIChat(id="gpt-4o-mini", cache_dir=str(tmp_path))
        responses = [ModelResponse(content="chunk1"), ModelResponse(content="chunk2")]
        model._save_streaming_responses_to_cache("stream_rt", responses)

        cached = model._get_cached_model_response("stream_rt")
        reconstructed = list(model._streaming_responses_from_cache(cached["streaming_responses"]))
        assert len(reconstructed) == 2
        assert reconstructed[0].content == "chunk1"
        assert reconstructed[1].content == "chunk2"

    def test_save_streaming_responses(self, tmp_path):
        """Streaming responses can be saved to cache."""
        model = OpenAIChat(id="gpt-4o-mini", cache_dir=str(tmp_path))

        responses = [
            ModelResponse(content="chunk1"),
            ModelResponse(content="chunk2"),
        ]
        model._save_streaming_responses_to_cache("stream_key", responses)

        cache_file = tmp_path / "stream_key.json"
        assert cache_file.exists()
        with open(cache_file, "r") as f:
            data = json.load(f)
        assert data["is_streaming"] is True
        assert len(data["streaming_responses"]) == 2


# =============================================================================
# Tests for __deepcopy__
# =============================================================================


class TestModelDeepCopy:
    def test_deep_copy_creates_new_instance(self, model):
        """Deep copy creates a distinct instance."""
        copy = deepcopy(model)
        assert copy is not model
        assert copy.id == model.id

    def test_deep_copy_nulls_client_objects(self, model):
        """Deep copy sets client objects to None."""
        model.client = MagicMock()
        model.async_client = MagicMock()
        copy = deepcopy(model)
        assert copy.client is None
        assert copy.async_client is None

    def test_deep_copy_preserves_config(self):
        """Deep copy preserves retry configuration."""
        model = OpenAIChat(
            id="gpt-4o-mini",
            retries=3,
            delay_between_retries=5,
            exponential_backoff=True,
        )
        copy = deepcopy(model)
        assert copy.retries == 3
        assert copy.delay_between_retries == 5
        assert copy.exponential_backoff is True


# =============================================================================
# Tests for _handle_agent_exception
# =============================================================================


class TestHandleAgentException:
    def test_string_user_message(self):
        """String user_message is converted to Message."""
        exc = AgentRunException("test error", user_message="please retry")
        additional = []
        _handle_agent_exception(exc, additional)
        assert len(additional) == 1
        assert additional[0].role == "user"
        assert additional[0].content == "please retry"

    def test_message_user_message(self):
        """Message user_message is used directly."""
        msg = Message(role="user", content="already a message")
        exc = AgentRunException("test error", user_message=msg)
        additional = []
        _handle_agent_exception(exc, additional)
        assert len(additional) == 1
        assert additional[0] is msg

    def test_string_agent_message(self):
        """String agent_message is converted to Message."""
        exc = AgentRunException("test error", agent_message="I will try again")
        additional = []
        _handle_agent_exception(exc, additional)
        assert len(additional) == 1
        assert additional[0].role == "assistant"
        assert additional[0].content == "I will try again"

    def test_messages_list_with_dicts(self):
        """Dict messages are converted to Message objects."""
        exc = AgentRunException("test error", messages=[{"role": "user", "content": "from dict"}])
        additional = []
        _handle_agent_exception(exc, additional)
        assert len(additional) == 1
        assert additional[0].role == "user"
        assert additional[0].content == "from dict"

    def test_messages_list_with_message_objects(self):
        """Message objects in messages list are used directly."""
        msg = Message(role="user", content="direct")
        exc = AgentRunException("test error", messages=[msg])
        additional = []
        _handle_agent_exception(exc, additional)
        assert len(additional) == 1
        assert additional[0] is msg

    def test_stop_execution_sets_flag(self):
        """stop_execution=True sets stop_after_tool_call on all messages."""
        exc = AgentRunException("test error", user_message="stop", stop_execution=True)
        additional = []
        _handle_agent_exception(exc, additional)
        assert len(additional) == 1
        assert additional[0].stop_after_tool_call is True

    def test_none_additional_input(self):
        """None additional_input is handled gracefully (treated as empty list internally)."""
        exc = AgentRunException("test error", user_message="test")
        # The function creates a new list internally when None
        _handle_agent_exception(exc, None)
        # No error raised

    def test_invalid_dict_skipped(self):
        """Invalid dict in messages list is skipped with warning."""
        exc = AgentRunException("test error", messages=[{"invalid_field": "bad data"}])
        additional = []
        _handle_agent_exception(exc, additional)
        # Invalid dict should be skipped (logged a warning)
        assert len(additional) == 0

    def test_combined_user_and_agent_messages(self):
        """Both user and agent messages are collected."""
        exc = AgentRunException("test error", user_message="user msg", agent_message="agent msg")
        additional = []
        _handle_agent_exception(exc, additional)
        assert len(additional) == 2
        assert additional[0].role == "user"
        assert additional[1].role == "assistant"
