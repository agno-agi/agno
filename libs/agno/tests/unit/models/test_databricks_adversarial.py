"""Adversarial tests for the Databricks model implementation.

These tests exercise edge cases and malformed inputs to try to break
the Databricks model provider parsing, formatting, and error handling.
"""

import json
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest
from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.media import Video
from agno.models.databricks import Databricks
from agno.models.message import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_model(**kwargs) -> Databricks:
    defaults = {"endpoint": "test-ep", "host": "https://test.cloud.databricks.com"}
    defaults.update(kwargs)
    return Databricks(**defaults)


def _make_assistant() -> Message:
    return Message(role="assistant")


# ===========================================================================
# 1. Streaming SSE parsing (_parse_sse_line)
# ===========================================================================


class TestSSEParsing:
    def setup_method(self):
        self.model = _make_model()

    def test_malformed_sse_no_data_prefix(self):
        """Line without 'data:' prefix should be silently skipped."""
        assert self.model._parse_sse_line("event: ping") is None

    def test_sse_with_extra_whitespace(self):
        """Leading/trailing whitespace around data: and JSON should be handled."""
        line = '  data:  {"id":"1","choices":[{"delta":{"content":"ok"},"index":0}]}  '
        result = self.model._parse_sse_line(line)
        assert result is not None
        assert result.content == "ok"

    def test_sse_done_no_space(self):
        """'data:[DONE]' (no space) should be treated as done signal."""
        assert self.model._parse_sse_line("data:[DONE]") is None

    def test_sse_invalid_json(self):
        """Invalid JSON after 'data:' should raise ModelProviderError."""
        with pytest.raises(ModelProviderError):
            self.model._parse_sse_line("data: {not json at all}")

    def test_sse_empty_line(self):
        """Empty string should return None."""
        assert self.model._parse_sse_line("") is None

    def test_sse_data_prefix_only(self):
        """'data:' with nothing after it — empty string is not valid JSON."""
        with pytest.raises(ModelProviderError):
            self.model._parse_sse_line("data:")

    def test_sse_data_with_only_whitespace_after(self):
        """'data:   ' should also fail (empty payload is not valid JSON)."""
        with pytest.raises(ModelProviderError):
            self.model._parse_sse_line("data:   ")

    def test_sse_with_colon_in_json_value(self):
        """JSON containing colons should not confuse prefix detection."""
        line = 'data: {"id":"a:b","choices":[{"delta":{"content":"x:y"},"index":0}]}'
        result = self.model._parse_sse_line(line)
        assert result is not None
        assert result.content == "x:y"


# ===========================================================================
# 2. Response parsing (_parse_provider_response)
# ===========================================================================


class TestResponseParsing:
    def setup_method(self):
        self.model = _make_model()

    def test_empty_choices_list(self):
        """Empty choices should return an empty ModelResponse, not crash."""
        resp = self.model._parse_provider_response({"choices": []})
        assert resp.content is None
        assert resp.tool_calls == []  # default_factory list

    def test_choices_is_none(self):
        """choices=None should be treated like empty list."""
        resp = self.model._parse_provider_response({"choices": None})
        assert resp.content is None

    def test_response_with_error_field_dict(self):
        """Error dict in response should raise ModelProviderError."""
        with pytest.raises(ModelProviderError, match="something went wrong"):
            self.model._parse_provider_response(
                {"error": {"message": "something went wrong", "code": "500"}}
            )

    def test_response_with_error_field_string(self):
        """Error as a plain string should also raise."""
        with pytest.raises(ModelProviderError, match="plain error string"):
            self.model._parse_provider_response({"error": "plain error string"})

    def test_response_with_error_dict_no_message_key(self):
        """Error dict missing 'message' key should use 'Unknown model error'."""
        with pytest.raises(ModelProviderError, match="Unknown model error"):
            self.model._parse_provider_response({"error": {"code": "500"}})

    def test_choice_missing_message_key(self):
        """choices[0] with no 'message' key should not crash (defaults to {})."""
        resp = self.model._parse_provider_response(
            {"choices": [{"index": 0, "finish_reason": "stop"}]}
        )
        # No content, no tool_calls — just an empty response
        assert resp.content is None
        assert resp.tool_calls == []

    def test_tool_calls_with_empty_function_name(self):
        """Tool call with empty function name should still be included."""
        resp = self.model._parse_provider_response({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "type": "function", "function": {"name": "", "arguments": "{}"}}
                    ],
                }
            }]
        })
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0]["function"]["name"] == ""

    def test_usage_is_none(self):
        """usage=None should not set response_usage."""
        resp = self.model._parse_provider_response({
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            "usage": None,
        })
        assert resp.response_usage is None

    def test_reasoning_content_in_message(self):
        """reasoning_content field should populate model_response.reasoning_content."""
        resp = self.model._parse_provider_response({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "final answer",
                    "reasoning_content": "I thought about it",
                }
            }]
        })
        assert resp.reasoning_content == "I thought about it"
        assert resp.content == "final answer"

    def test_reasoning_field_fallback(self):
        """'reasoning' field should also populate reasoning_content."""
        resp = self.model._parse_provider_response({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "reasoning": "my reasoning",
                }
            }]
        })
        assert resp.reasoning_content == "my reasoning"

    def test_provider_data_populated(self):
        """Provider data fields should be extracted."""
        resp = self.model._parse_provider_response({
            "id": "chat-123",
            "model": "ep",
            "system_fingerprint": "fp",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": "x"}}],
        })
        assert resp.provider_data["id"] == "chat-123"
        assert resp.provider_data["model"] == "ep"
        assert resp.provider_data["system_fingerprint"] == "fp"

    def test_completely_empty_response(self):
        """Response with no choices and no error should return empty ModelResponse."""
        resp = self.model._parse_provider_response({})
        assert resp.content is None


# ===========================================================================
# 3. Tool call parsing (parse_tool_calls)
# ===========================================================================


class TestParseToolCalls:
    def test_empty_tool_calls_data(self):
        """Empty list should return empty list."""
        assert Databricks.parse_tool_calls([]) == []

    def test_tool_call_with_high_index_no_preceding(self):
        """Index > 0 with no preceding entries should create placeholder entries."""
        result = Databricks.parse_tool_calls([
            {"index": 2, "id": "c3", "type": "function", "function": {"name": "foo", "arguments": "{}"}}
        ])
        assert len(result) == 3
        # Indices 0 and 1 should be placeholder dicts with proper structure
        assert result[0]["function"]["name"] == ""
        assert result[0]["function"]["arguments"] == ""
        assert result[1]["function"]["name"] == ""
        assert result[2]["id"] == "c3"
        assert result[2]["function"]["name"] == "foo"

    def test_tool_call_with_no_function_key(self):
        """Tool call missing 'function' key should not crash (defaults to {})."""
        result = Databricks.parse_tool_calls([
            {"index": 0, "id": "c1", "type": "function"}
        ])
        assert len(result) == 1
        assert result[0]["function"]["name"] == ""
        assert result[0]["function"]["arguments"] == ""

    def test_multiple_calls_same_index_concatenate(self):
        """Multiple tool calls at same index should concatenate arguments."""
        result = Databricks.parse_tool_calls([
            {"index": 0, "id": "c1", "type": "function", "function": {"name": "fn", "arguments": '{"a":'}},
            {"index": 0, "function": {"arguments": '"b"}'}},
        ])
        assert len(result) == 1
        assert result[0]["function"]["arguments"] == '{"a":"b"}'
        assert result[0]["function"]["name"] == "fn"

    def test_tool_call_with_none_function_arguments(self):
        """function.arguments=None should be treated as empty string."""
        result = Databricks.parse_tool_calls([
            {"index": 0, "id": "c1", "type": "function", "function": {"name": "fn", "arguments": None}}
        ])
        assert result[0]["function"]["arguments"] == ""

    def test_multiple_distinct_tool_calls(self):
        """Two tool calls at different indices."""
        result = Databricks.parse_tool_calls([
            {"index": 0, "id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
            {"index": 1, "id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
        ])
        assert len(result) == 2
        assert result[0]["function"]["name"] == "a"
        assert result[1]["function"]["name"] == "b"

    def test_concatenation_updates_id_and_type_on_later_chunk(self):
        """If a later chunk supplies id/type, those should update the entry."""
        result = Databricks.parse_tool_calls([
            {"index": 0, "function": {"name": "fn", "arguments": "{"}},
            {"index": 0, "id": "late-id", "type": "function", "function": {"arguments": "}"}},
        ])
        assert result[0]["id"] == "late-id"
        assert result[0]["type"] == "function"
        assert result[0]["function"]["arguments"] == "{}"


# ===========================================================================
# 4. Message formatting (_format_message)
# ===========================================================================


class TestMessageFormatting:
    def setup_method(self):
        self.model = _make_model()

    def test_role_not_in_default_role_map(self):
        """A role not in default_role_map should fall back to the raw role string."""
        msg = Message(role="unknown_role", content="hi")
        result = self.model._format_message(msg)
        assert result["role"] == "unknown_role"

    def test_model_role_maps_to_assistant(self):
        """'model' role should map to 'assistant'."""
        msg = Message(role="model", content="hi")
        result = self.model._format_message(msg)
        assert result["role"] == "assistant"

    def test_empty_tool_calls_removed(self):
        """Message with empty tool_calls list should have tool_calls key removed."""
        msg = Message(role="assistant", content="hi", tool_calls=[])
        result = self.model._format_message(msg)
        assert "tool_calls" not in result

    def test_none_content_becomes_empty_string(self):
        """Message with content=None should have content set to empty string."""
        msg = Message(role="user", content=None)
        result = self.model._format_message(msg)
        assert result["content"] == ""

    def test_videos_logs_warning(self):
        """Videos should trigger an unsupported warning log."""
        msg = Message(role="user", content="test", videos=[Video(url="http://example.com/v.mp4")])
        with patch("agno.models.databricks.databricks.log_warning") as mock_warn:
            self.model._format_message(msg)
            mock_warn.assert_called_once()
            assert "unsupported" in mock_warn.call_args[0][0].lower()

    def test_custom_role_map(self):
        """Custom role_map should override default_role_map."""
        model = _make_model(role_map={"user": "human", "assistant": "bot", "system": "sys", "tool": "tool"})
        msg = Message(role="user", content="hello")
        result = model._format_message(msg)
        assert result["role"] == "human"

    def test_custom_role_map_missing_role_falls_back(self):
        """Custom role_map missing the message role should fall back to raw role."""
        model = _make_model(role_map={"user": "human"})
        msg = Message(role="assistant", content="hi")
        result = model._format_message(msg)
        assert result["role"] == "assistant"

    def test_audio_output_overrides_content(self):
        """Message with audio_output should set content to empty string and add audio."""
        from agno.media import Audio
        msg = Message(role="assistant", content="some text")
        msg.audio_output = Audio(id="audio-1", content=b"data")
        result = self.model._format_message(msg)
        assert result["content"] == ""
        assert result["audio"]["id"] == "audio-1"

    def test_files_with_no_content_preserved(self):
        """Message with files but content=None: files should be preserved in content list."""
        from agno.media import File
        msg = Message(role="user", content=None, files=[File(url="http://example.com/f.pdf")])
        with patch("agno.models.databricks.databricks._format_file_for_message", return_value={"type": "file", "url": "x"}):
            result = self.model._format_message(msg)
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "file"

    def test_files_with_string_content(self):
        """Message with files and string content should convert content to list."""
        from agno.media import File
        msg = Message(role="user", content="some text", files=[File(url="http://example.com/f.pdf")])
        with patch("agno.models.databricks.databricks._format_file_for_message", return_value={"type": "file", "url": "x"}):
            result = self.model._format_message(msg)
        assert isinstance(result["content"], list)
        # First item should be the file, second the text
        assert result["content"][0]["type"] == "file"
        assert result["content"][1]["type"] == "text"
        assert result["content"][1]["text"] == "some text"


# ===========================================================================
# 5. Request params (get_request_params)
# ===========================================================================


class TestRequestParams:
    def test_all_unsupported_params_logged(self):
        """All unsupported params should trigger a single warning with all names."""
        model = _make_model(
            frequency_penalty=0.5,
            logit_bias={1: 10},
            presence_penalty=0.3,
            seed=42,
            user="u1",
            metadata={"k": "v"},
        )
        with patch("agno.models.databricks.databricks.log_warning") as mock_warn:
            model.get_request_params()
            mock_warn.assert_called_once()
            warning_text = mock_warn.call_args[0][0]
            for name in ["frequency_penalty", "logit_bias", "presence_penalty", "seed", "user", "metadata"]:
                assert name in warning_text

    def test_response_format_as_basemodel(self):
        """BaseModel subclass should be converted to json_schema format."""
        class MyModel(BaseModel):
            name: str
            age: int

        model = _make_model()
        params = model.get_request_params(response_format=MyModel)
        assert "response_format" in params
        assert params["response_format"]["type"] == "json_schema"
        assert params["response_format"]["json_schema"]["name"] == "MyModel"
        assert "schema" in params["response_format"]["json_schema"]
        assert params["response_format"]["json_schema"]["strict"] is True

    def test_response_format_as_dict(self):
        """Dict response_format should be passed through as-is."""
        model = _make_model()
        fmt = {"type": "json_object"}
        params = model.get_request_params(response_format=fmt)
        assert params["response_format"] == fmt

    def test_tools_with_tool_choice(self):
        """Tools and tool_choice should both appear in params."""
        model = _make_model()
        tools = [{"type": "function", "function": {"name": "fn", "parameters": {}}}]
        params = model.get_request_params(tools=tools, tool_choice="auto")
        assert params["tools"] == tools
        assert params["tool_choice"] == "auto"

    def test_tools_without_tool_choice(self):
        """Tools without tool_choice should not include tool_choice."""
        model = _make_model()
        tools = [{"type": "function", "function": {"name": "fn", "parameters": {}}}]
        params = model.get_request_params(tools=tools)
        assert "tools" in params
        assert "tool_choice" not in params

    def test_request_params_override(self):
        """request_params dict should override/add to base params."""
        model = _make_model(temperature=0.5, request_params={"temperature": 0.9, "custom_key": "val"})
        params = model.get_request_params()
        assert params["temperature"] == 0.9
        assert params["custom_key"] == "val"

    def test_none_params_omitted(self):
        """None-valued base params should not appear in output."""
        model = _make_model()
        params = model.get_request_params()
        assert "temperature" not in params
        assert "max_tokens" not in params
        assert "stop" not in params

    def test_strict_output_false(self):
        """strict_output=False should set strict=False in json_schema."""
        class MyModel(BaseModel):
            x: int

        model = _make_model(strict_output=False)
        params = model.get_request_params(response_format=MyModel)
        assert params["response_format"]["json_schema"]["strict"] is False


# ===========================================================================
# 6. Client initialization
# ===========================================================================


class TestClientInit:
    def test_get_client_returns_same_instance(self):
        """Multiple calls to get_client() should return the same instance."""
        model = _make_model()
        c1 = model.get_client()
        c2 = model.get_client()
        assert c1 is c2

    def test_host_sets_workspace_url(self):
        """Setting host should also set workspace_url if not explicitly set."""
        model = _make_model(host="https://myhost.com")
        client = model.get_client()
        assert client.settings.workspace_url == "https://myhost.com"

    def test_explicit_workspace_url_overrides_host(self):
        """Explicit workspace_url should take precedence over host for workspace_url."""
        model = _make_model(host="https://myhost.com", workspace_url="https://myworkspace.com")
        client = model.get_client()
        assert client.settings.host == "https://myhost.com"
        assert client.settings.workspace_url == "https://myworkspace.com"

    def test_endpoint_defaults_to_id(self):
        """endpoint should default to id if not set."""
        model = Databricks(id="my-model-id", host="https://test.cloud.databricks.com")
        assert model.endpoint == "my-model-id"


# ===========================================================================
# 7. Error handling (invoke)
# ===========================================================================


class TestErrorHandling:
    def test_invoke_generic_exception_wraps_in_provider_error(self):
        """Generic exceptions from the client should be wrapped in ModelProviderError."""
        mock_client = Mock()
        mock_client.request_json.side_effect = RuntimeError("connection dropped")
        model = _make_model()
        model.client = mock_client

        with pytest.raises(ModelProviderError, match="connection dropped"):
            model.invoke([Message(role="user", content="hi")], _make_assistant())

    def test_invoke_model_provider_error_re_raised(self):
        """ModelProviderError should be re-raised directly."""
        mock_client = Mock()
        mock_client.request_json.side_effect = ModelProviderError(
            message="bad request", model_name="Databricks", model_id="ep"
        )
        model = _make_model()
        model.client = mock_client

        with pytest.raises(ModelProviderError, match="bad request"):
            model.invoke([Message(role="user", content="hi")], _make_assistant())

    def test_invoke_error_response_raises(self):
        """Response with 'error' key should raise ModelProviderError."""
        mock_client = Mock()
        mock_client.request_json.return_value = {"error": {"message": "model overloaded"}}
        model = _make_model()
        model.client = mock_client

        with pytest.raises(ModelProviderError, match="model overloaded"):
            model.invoke([Message(role="user", content="hi")], _make_assistant())


# ===========================================================================
# 8. Streaming edge cases
# ===========================================================================


class TestStreamingEdgeCases:
    def _make_stream_model(self, lines):
        """Create a model with a mocked streaming client yielding the given lines."""
        @contextmanager
        def stream_ctx():
            response = Mock()
            response.iter_lines.return_value = lines
            yield response

        mock_client = Mock()
        mock_client.stream.return_value = stream_ctx()
        model = _make_model()
        model.client = mock_client
        return model

    def test_stream_yields_no_chunks(self):
        """Stream with no lines should yield no responses."""
        model = self._make_stream_model([])
        chunks = list(model.invoke_stream([Message(role="user", content="hi")], _make_assistant()))
        assert chunks == []

    def test_stream_yields_only_done(self):
        """Stream with only [DONE] should yield no responses."""
        model = self._make_stream_model(["data: [DONE]"])
        chunks = list(model.invoke_stream([Message(role="user", content="hi")], _make_assistant()))
        assert chunks == []

    def test_stream_chunk_with_no_choices(self):
        """Stream chunk with empty choices should yield ModelResponse with no content."""
        model = self._make_stream_model([
            'data: {"id":"1","choices":[]}'
        ])
        chunks = list(model.invoke_stream([Message(role="user", content="hi")], _make_assistant()))
        assert len(chunks) == 1
        assert chunks[0].content is None

    def test_stream_chunk_with_reasoning_content(self):
        """Stream delta with reasoning_content should populate reasoning_content."""
        model = self._make_stream_model([
            'data: {"id":"1","choices":[{"delta":{"reasoning_content":"thinking..."},"index":0}]}'
        ])
        chunks = list(model.invoke_stream([Message(role="user", content="hi")], _make_assistant()))
        assert len(chunks) == 1
        assert chunks[0].reasoning_content == "thinking..."

    def test_stream_chunk_with_reasoning_fallback(self):
        """Stream delta with 'reasoning' field should fall back to reasoning_content."""
        model = self._make_stream_model([
            'data: {"id":"1","choices":[{"delta":{"reasoning":"fallback thinking"},"index":0}]}'
        ])
        chunks = list(model.invoke_stream([Message(role="user", content="hi")], _make_assistant()))
        assert len(chunks) == 1
        assert chunks[0].reasoning_content == "fallback thinking"

    def test_stream_chunk_with_tool_calls_delta(self):
        """Stream delta with tool_calls should be captured."""
        tc = [{"index": 0, "id": "c1", "type": "function", "function": {"name": "fn", "arguments": "{}"}}]
        model = self._make_stream_model([
            f'data: {{"id":"1","choices":[{{"delta":{{"tool_calls":{json.dumps(tc)}}},"index":0}}]}}'
        ])
        chunks = list(model.invoke_stream([Message(role="user", content="hi")], _make_assistant()))
        assert len(chunks) == 1
        assert chunks[0].tool_calls == tc

    def test_stream_chunk_with_usage(self):
        """Stream chunk with usage at top level should populate response_usage."""
        model = self._make_stream_model([
            'data: {"id":"1","choices":[],"usage":{"prompt_tokens":5,"completion_tokens":3,"total_tokens":8}}'
        ])
        chunks = list(model.invoke_stream([Message(role="user", content="hi")], _make_assistant()))
        assert len(chunks) == 1
        assert chunks[0].response_usage is not None
        assert chunks[0].response_usage.total_tokens == 8

    def test_stream_mixed_lines(self):
        """Stream with empty lines, non-data lines, content, and [DONE]."""
        model = self._make_stream_model([
            "",
            ": keep-alive",
            'data: {"id":"1","choices":[{"delta":{"content":"A"},"index":0}]}',
            "",
            "event: ping",
            'data: {"id":"1","choices":[{"delta":{"content":"B"},"index":0}]}',
            "data: [DONE]",
        ])
        chunks = list(model.invoke_stream([Message(role="user", content="hi")], _make_assistant()))
        contents = [c.content for c in chunks if c.content]
        assert contents == ["A", "B"]

    def test_stream_invalid_json_raises(self):
        """Stream line with invalid JSON should raise ModelProviderError."""
        model = self._make_stream_model([
            "data: NOT_JSON"
        ])
        with pytest.raises(ModelProviderError, match="Failed to decode"):
            list(model.invoke_stream([Message(role="user", content="hi")], _make_assistant()))


# ===========================================================================
# 9. _parse_provider_response_delta edge cases
# ===========================================================================


class TestResponseDeltaParsing:
    def setup_method(self):
        self.model = _make_model()

    def test_delta_empty_response(self):
        """Completely empty delta response."""
        resp = self.model._parse_provider_response_delta({})
        assert resp.content is None
        assert resp.tool_calls == []

    def test_delta_choices_none(self):
        """choices=None in delta."""
        resp = self.model._parse_provider_response_delta({"choices": None})
        assert resp.content is None

    def test_delta_with_content_sets_provider_data(self):
        """Delta with content should also capture provider data."""
        resp = self.model._parse_provider_response_delta({
            "id": "chat-1",
            "model": "ep",
            "system_fingerprint": "fp1",
            "choices": [{"delta": {"content": "hi"}, "index": 0}],
        })
        assert resp.content == "hi"
        assert resp.provider_data["id"] == "chat-1"

    def test_delta_without_content_no_provider_data(self):
        """Delta without content should not set provider_data even if id/model present."""
        resp = self.model._parse_provider_response_delta({
            "id": "chat-1",
            "model": "ep",
            "choices": [{"delta": {}, "index": 0}],
        })
        # provider_data is only set when content is not None
        assert resp.provider_data is None

    def test_delta_tool_calls_non_list_ignored(self):
        """tool_calls that is not a list should be ignored."""
        resp = self.model._parse_provider_response_delta({
            "choices": [{"delta": {"tool_calls": "not-a-list"}, "index": 0}],
        })
        assert resp.tool_calls == []

    def test_delta_with_usage(self):
        """Usage in delta response."""
        resp = self.model._parse_provider_response_delta({
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })
        assert resp.response_usage is not None
        assert resp.response_usage.input_tokens == 10
        assert resp.response_usage.output_tokens == 5


# ===========================================================================
# 10. _build_payload edge cases
# ===========================================================================


class TestBuildPayload:
    def test_stream_includes_stream_options(self):
        """Streaming payload should include stream_options when explicitly enabled."""
        model = _make_model(include_stream_usage=True)
        payload = model._build_payload(
            [Message(role="user", content="hi")], stream=True
        )
        assert payload["stream"] is True
        assert payload["stream_options"] == {"include_usage": True}

    def test_stream_options_disabled(self):
        """include_stream_usage=False should omit stream_options."""
        model = _make_model(include_stream_usage=False)
        payload = model._build_payload(
            [Message(role="user", content="hi")], stream=True
        )
        assert "stream_options" not in payload

    def test_non_stream_no_stream_options(self):
        """Non-streaming payload should never have stream_options."""
        model = _make_model()
        payload = model._build_payload(
            [Message(role="user", content="hi")], stream=False
        )
        assert "stream_options" not in payload
        assert payload["stream"] is False


# ===========================================================================
# 11. to_dict / from_dict
# ===========================================================================


class TestSerialization:
    def test_to_dict_omits_none_values(self):
        """to_dict should not include None-valued fields."""
        model = _make_model()
        d = model.to_dict()
        for v in d.values():
            assert v is not None

    def test_from_dict_roundtrip(self):
        """from_dict should reconstruct a model from to_dict output."""
        model = _make_model(temperature=0.7, max_tokens=100)
        d = model.to_dict()
        restored = Databricks.from_dict(d)
        assert restored.temperature == 0.7
        assert restored.max_tokens == 100
        assert restored.endpoint == "test-ep"


# ===========================================================================
# 12. _get_metrics edge cases
# ===========================================================================


class TestGetMetrics:
    def setup_method(self):
        self.model = _make_model()

    def test_empty_usage_dict(self):
        """Empty usage dict should produce zero metrics."""
        metrics = self.model._get_metrics({})
        assert metrics.input_tokens == 0
        assert metrics.output_tokens == 0
        assert metrics.total_tokens == 0

    def test_usage_with_none_values(self):
        """None token values should default to 0."""
        metrics = self.model._get_metrics({
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        })
        assert metrics.input_tokens == 0
        assert metrics.output_tokens == 0
        assert metrics.total_tokens == 0

    def test_usage_with_token_details(self):
        """Token detail sub-dicts should be parsed."""
        metrics = self.model._get_metrics({
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "prompt_tokens_details": {"audio_tokens": 2, "cached_tokens": 3},
            "completion_tokens_details": {"audio_tokens": 1, "reasoning_tokens": 4},
        })
        assert metrics.audio_input_tokens == 2
        assert metrics.cache_read_tokens == 3
        assert metrics.audio_output_tokens == 1
        assert metrics.reasoning_tokens == 4

    def test_usage_with_cost(self):
        """Cost field should be captured."""
        metrics = self.model._get_metrics({"cost": 0.0042})
        assert metrics.cost == 0.0042

    def test_usage_with_none_detail_dicts(self):
        """None detail dicts should not crash."""
        metrics = self.model._get_metrics({
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "total_tokens": 8,
            "prompt_tokens_details": None,
            "completion_tokens_details": None,
        })
        assert metrics.audio_input_tokens == 0
        assert metrics.reasoning_tokens == 0
