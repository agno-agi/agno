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
    def test_uses_tool_based_fallback(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE_TOOL

        model = AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0", session=mock_session)
        response = model.invoke(
            messages=[Message(role="user", content="Write a movie script")],
            assistant_message=Message(role="assistant"),
            response_format=MovieScript,
        )

        call_kwargs = mock_client.converse.call_args[1]
        # boto3 Converse API doesn't support outputConfig, so we use tool-based fallback
        assert "outputConfig" not in call_kwargs
        # Should have toolConfig with forced tool
        assert "toolConfig" in call_kwargs
        assert call_kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": "respond_with_MovieScript"}}
        # Response content should be extracted from tool input
        assert '"name": "Sunset"' in response.content

    def test_preserves_existing_tools(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE_TOOL

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
        assert "toolConfig" in call_kwargs
        tool_names = [t["toolSpec"]["name"] for t in call_kwargs["toolConfig"]["tools"]]
        assert "get_weather" in tool_names
        assert "respond_with_MovieScript" in tool_names


class TestInvokeStreamWithStructuredOutput:
    def test_streams_tool_input_as_content(self):
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

        model = AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0", session=mock_session)
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
    async def test_ainvoke_uses_tool_fallback(self):
        try:
            import aioboto3  # noqa: F401
        except ImportError:
            pytest.skip("aioboto3 not installed")

        from unittest.mock import AsyncMock, patch

        mock_session, _ = _make_mock_session()
        mock_async_client = MagicMock()
        mock_async_client.converse = AsyncMock(return_value=CONVERSE_RESPONSE_TOOL)
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
        assert "outputConfig" not in call_kwargs
        assert "toolConfig" in call_kwargs
        assert call_kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": "respond_with_MovieScript"}}

    async def test_ainvoke_stream_uses_tool_fallback(self):
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

        model = AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0", session=mock_session)

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
