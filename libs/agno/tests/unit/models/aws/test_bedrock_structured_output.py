from typing import List
from unittest.mock import MagicMock

import pytest
from boto3.session import Session
from pydantic import BaseModel, Field

from agno.models.aws import AwsBedrock
from agno.models.message import Message


class MovieScript(BaseModel):
    name: str = Field(..., description="Movie name")
    genre: str = Field(..., description="Genre")
    characters: List[str] = Field(..., description="Characters")


def _make_mock_session():
    mock_session = MagicMock(spec=Session)
    mock_session.region_name = "us-east-1"
    mock_session.profile_name = None
    mock_creds = MagicMock()
    frozen = MagicMock()
    frozen.access_key = "ASIATEMP"
    frozen.secret_key = "secret"
    frozen.token = "token"
    mock_creds.get_frozen_credentials.return_value = frozen
    mock_session.get_credentials.return_value = mock_creds
    mock_client = MagicMock()
    mock_session.client.return_value = mock_client
    return mock_session, mock_client


CONVERSE_RESPONSE_TEXT = {
    "output": {
        "message": {
            "role": "assistant",
            "content": [{"text": '{"name": "Sunset", "genre": "Drama", "characters": ["Alice"]}'}],
        }
    },
    "usage": {"inputTokens": 10, "outputTokens": 5},
    "stopReason": "end_turn",
}

CONVERSE_RESPONSE_TOOL = {
    "output": {
        "message": {
            "role": "assistant",
            "content": [
                {
                    "toolUse": {
                        "toolUseId": "tool-123",
                        "name": "respond_with_MovieScript",
                        "input": {"name": "Sunset", "genre": "Drama", "characters": ["Alice"]},
                    }
                }
            ],
        }
    },
    "usage": {"inputTokens": 10, "outputTokens": 5},
    "stopReason": "tool_use",
}


class TestSupportsNativeStructuredOutputs:
    def test_claude_4_supports_native(self):
        model = AwsBedrock(id="us.anthropic.claude-4-sonnet-20260115-v1:0")
        assert model._supports_native_structured_outputs() is True

    def test_claude_opus_4_supports_native(self):
        model = AwsBedrock(id="anthropic.claude-opus-4-20251101-v1:0")
        assert model._supports_native_structured_outputs() is True

    def test_claude_sonnet_4_supports_native(self):
        model = AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0")
        assert model._supports_native_structured_outputs() is True

    def test_claude_haiku_4_supports_native(self):
        model = AwsBedrock(id="anthropic.claude-haiku-4-5-20251001-v1:0")
        assert model._supports_native_structured_outputs() is True

    def test_claude_3_5_does_not_support_native(self):
        model = AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0")
        assert model._supports_native_structured_outputs() is False

    def test_claude_3_sonnet_does_not_support_native(self):
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
        assert model._supports_native_structured_outputs() is False

    def test_mistral_does_not_support_native(self):
        model = AwsBedrock(id="mistral.mistral-small-2402-v1:0")
        assert model._supports_native_structured_outputs() is False


class TestBuildOutputConfig:
    def setup_method(self):
        self.model_native = AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0")
        self.model_fallback = AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0")

    def test_returns_none_for_none_input(self):
        assert self.model_native._build_output_config(None) is None

    def test_returns_none_for_non_pydantic(self):
        assert self.model_native._build_output_config({"type": "json"}) is None

    def test_returns_none_for_unsupported_model(self):
        assert self.model_fallback._build_output_config(MovieScript) is None

    def test_returns_config_for_supported_model(self):
        result = self.model_native._build_output_config(MovieScript)
        assert result is not None
        assert "textFormat" in result
        assert result["textFormat"]["type"] == "json_schema"
        assert "structure" in result["textFormat"]
        assert "jsonSchema" in result["textFormat"]["structure"]
        assert result["textFormat"]["structure"]["jsonSchema"]["name"] == "MovieScript"

    def test_schema_is_json_string(self):
        result = self.model_native._build_output_config(MovieScript)
        schema_str = result["textFormat"]["structure"]["jsonSchema"]["schema"]
        assert isinstance(schema_str, str)
        import json

        schema = json.loads(schema_str)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]


class TestEnsureAdditionalPropertiesFalse:
    def setup_method(self):
        self.model = AwsBedrock(id="anthropic.claude-sonnet-4-5-20250929-v1:0")

    def test_adds_to_root_object(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        self.model._ensure_additional_properties_false(schema)
        assert schema["additionalProperties"] is False

    def test_adds_to_nested_objects(self):
        schema = {
            "type": "object",
            "properties": {"nested": {"type": "object", "properties": {"y": {"type": "string"}}}},
        }
        self.model._ensure_additional_properties_false(schema)
        assert schema["additionalProperties"] is False
        assert schema["properties"]["nested"]["additionalProperties"] is False

    def test_handles_array_items(self):
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"z": {"type": "string"}}},
                }
            },
        }
        self.model._ensure_additional_properties_false(schema)
        assert schema["properties"]["items"]["items"]["additionalProperties"] is False


class TestResponseFormatToTool:
    def setup_method(self):
        self.model = AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0")

    def test_returns_none_for_none(self):
        assert self.model._response_format_to_tool(None) is None

    def test_returns_none_for_dict(self):
        assert self.model._response_format_to_tool({"type": "json"}) is None

    def test_creates_tool_for_pydantic(self):
        result = self.model._response_format_to_tool(MovieScript)
        assert result is not None
        assert "toolSpec" in result
        assert result["toolSpec"]["name"] == "respond_with_MovieScript"
        assert "inputSchema" in result["toolSpec"]


class TestInvokeWithStructuredOutput:
    def test_native_path_includes_output_config(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE_TEXT

        model = AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0", session=mock_session)
        model.invoke(
            messages=[Message(role="user", content="Write a movie script")],
            assistant_message=Message(role="assistant"),
            response_format=MovieScript,
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert "outputConfig" in call_kwargs
        assert call_kwargs["outputConfig"]["textFormat"]["type"] == "json_schema"
        # No toolConfig should be present unless tools were explicitly passed
        assert "toolConfig" not in call_kwargs

    def test_fallback_path_uses_tool(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE_TOOL

        model = AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0", session=mock_session)
        response = model.invoke(
            messages=[Message(role="user", content="Write a movie script")],
            assistant_message=Message(role="assistant"),
            response_format=MovieScript,
        )

        call_kwargs = mock_client.converse.call_args[1]
        # No outputConfig for fallback
        assert "outputConfig" not in call_kwargs
        # Should have toolConfig with forced tool
        assert "toolConfig" in call_kwargs
        assert call_kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": "respond_with_MovieScript"}}
        # Response content should be extracted from tool input
        assert '"name": "Sunset"' in response.content

    def test_native_path_no_tool_config_without_tools(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE_TEXT

        model = AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0", session=mock_session)
        model.invoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=Message(role="assistant"),
            response_format=MovieScript,
            tools=None,
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert "outputConfig" in call_kwargs
        assert "toolConfig" not in call_kwargs

    def test_native_path_preserves_tools(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE_TEXT

        tools = [
            {
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"properties": {"city": {"type": "string"}}},
                }
            }
        ]

        model = AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0", session=mock_session)
        model.invoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=Message(role="assistant"),
            response_format=MovieScript,
            tools=tools,
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert "outputConfig" in call_kwargs
        assert "toolConfig" in call_kwargs
        # Should have the weather tool but not the schema tool
        tool_names = [t["toolSpec"]["name"] for t in call_kwargs["toolConfig"]["tools"]]
        assert "get_weather" in tool_names
        assert "respond_with_MovieScript" not in tool_names


class TestInvokeStreamWithStructuredOutput:
    def test_native_path_includes_output_config(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse_stream.return_value = {
            "stream": [
                {"contentBlockDelta": {"delta": {"text": '{"name": "Test"}'}}},
                {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5}}},
            ]
        }

        model = AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0", session=mock_session)
        list(
            model.invoke_stream(
                messages=[Message(role="user", content="hi")],
                assistant_message=Message(role="assistant"),
                response_format=MovieScript,
            )
        )

        call_kwargs = mock_client.converse_stream.call_args[1]
        assert "outputConfig" in call_kwargs
        assert call_kwargs["outputConfig"]["textFormat"]["type"] == "json_schema"

    def test_fallback_streams_tool_input_as_content(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse_stream.return_value = {
            "stream": [
                {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "t1", "name": "respond_with_MovieScript"}}}},
                {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"name": "'}}}},
                {"contentBlockDelta": {"delta": {"toolUse": {"input": 'Test"}'}}}},
                {"contentBlockStop": {}},
                {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5}}},
            ]
        }

        model = AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0", session=mock_session)
        responses = list(
            model.invoke_stream(
                messages=[Message(role="user", content="hi")],
                assistant_message=Message(role="assistant"),
                response_format=MovieScript,
            )
        )

        call_kwargs = mock_client.converse_stream.call_args[1]
        assert "outputConfig" not in call_kwargs
        assert "toolConfig" in call_kwargs
        # Content should be streamed from tool input chunks
        content_chunks = [r.content for r in responses if r.content]
        assert len(content_chunks) == 2
        assert content_chunks[0] == '{"name": "'
        assert content_chunks[1] == 'Test"}'


@pytest.mark.asyncio
class TestAsyncInvokeWithStructuredOutput:
    async def test_ainvoke_native_path(self):
        try:
            import aioboto3  # noqa: F401
        except ImportError:
            pytest.skip("aioboto3 not installed")

        from unittest.mock import AsyncMock, patch

        mock_session, _ = _make_mock_session()
        mock_async_client = MagicMock()
        mock_async_client.converse = AsyncMock(return_value=CONVERSE_RESPONSE_TEXT)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        model = AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0", session=mock_session)

        with patch.object(model, "get_async_client", return_value=mock_async_client):
            await model.ainvoke(
                messages=[Message(role="user", content="hi")],
                assistant_message=Message(role="assistant"),
                response_format=MovieScript,
            )

        call_kwargs = mock_async_client.converse.call_args[1]
        assert "outputConfig" in call_kwargs
        assert call_kwargs["outputConfig"]["textFormat"]["type"] == "json_schema"

    async def test_ainvoke_stream_fallback_path(self):
        try:
            import aioboto3  # noqa: F401
        except ImportError:
            pytest.skip("aioboto3 not installed")

        from unittest.mock import AsyncMock, patch

        mock_session, _ = _make_mock_session()

        async def mock_stream():
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "t1", "name": "respond_with_MovieScript"}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"name": "Test"}'}}}}
            yield {"contentBlockStop": {}}
            yield {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5}}}

        mock_async_client = MagicMock()
        mock_async_client.converse_stream = AsyncMock(return_value={"stream": mock_stream()})
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        model = AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0", session=mock_session)

        with patch.object(model, "get_async_client", return_value=mock_async_client):
            responses = []
            async for r in model.ainvoke_stream(
                messages=[Message(role="user", content="hi")],
                assistant_message=Message(role="assistant"),
                response_format=MovieScript,
            ):
                responses.append(r)

        call_kwargs = mock_async_client.converse_stream.call_args[1]
        assert "outputConfig" not in call_kwargs
        assert "toolConfig" in call_kwargs
        assert call_kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": "respond_with_MovieScript"}}
