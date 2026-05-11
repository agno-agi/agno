from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from boto3.session import Session
from pydantic import BaseModel

from agno.models.aws import AwsBedrock
from agno.models.aws.bedrock import STRUCTURED_OUTPUT_TOOL_NAME
from agno.models.message import Message


class MovieScript(BaseModel):
    title: str
    director: str
    year: int


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


SAMPLE_TOOLS = [
    {
        "function": {
            "name": "get_weather",
            "description": "Get weather",
            "parameters": {"properties": {"city": {"type": "string", "description": "City name"}}},
        }
    }
]

CONVERSE_RESPONSE = {
    "output": {"message": {"role": "assistant", "content": [{"text": "Hello"}]}},
    "usage": {"inputTokens": 10, "outputTokens": 5},
    "stopReason": "end_turn",
}


class TestFormatToolChoice:
    def setup_method(self):
        self.model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

    def test_string_auto(self):
        assert self.model._format_tool_choice("auto") == {"auto": {}}

    def test_string_auto_case_insensitive(self):
        assert self.model._format_tool_choice("AUTO") == {"auto": {}}
        assert self.model._format_tool_choice("Auto") == {"auto": {}}

    def test_string_any(self):
        assert self.model._format_tool_choice("any") == {"any": {}}

    def test_string_any_case_insensitive(self):
        assert self.model._format_tool_choice("Any") == {"any": {}}
        assert self.model._format_tool_choice("ANY") == {"any": {}}

    def test_string_none_returns_none(self):
        assert self.model._format_tool_choice("none") is None

    def test_string_none_case_insensitive(self):
        assert self.model._format_tool_choice("NONE") is None
        assert self.model._format_tool_choice("None") is None

    def test_string_bare_tool_name(self):
        assert self.model._format_tool_choice("get_weather") == {"tool": {"name": "get_weather"}}

    def test_dict_top_level_name(self):
        result = self.model._format_tool_choice({"type": "function", "name": "get_weather"})
        assert result == {"tool": {"name": "get_weather"}}

    def test_dict_nested_function_name(self):
        result = self.model._format_tool_choice({"type": "function", "function": {"name": "get_weather"}})
        assert result == {"tool": {"name": "get_weather"}}

    def test_bedrock_native_auto_passthrough(self):
        assert self.model._format_tool_choice({"auto": {}}) == {"auto": {}}

    def test_bedrock_native_any_passthrough(self):
        assert self.model._format_tool_choice({"any": {}}) == {"any": {}}

    def test_bedrock_native_tool_passthrough(self):
        choice = {"tool": {"name": "get_weather"}}
        assert self.model._format_tool_choice(choice) == {"tool": {"name": "get_weather"}}

    def test_anthropic_format_auto(self):
        assert self.model._format_tool_choice({"type": "auto"}) == {"auto": {}}

    def test_anthropic_format_any(self):
        assert self.model._format_tool_choice({"type": "any"}) == {"any": {}}

    def test_anthropic_format_none(self):
        assert self.model._format_tool_choice({"type": "none"}) is None

    def test_anthropic_format_tool_with_name(self):
        result = self.model._format_tool_choice({"type": "tool", "name": "get_weather"})
        assert result == {"tool": {"name": "get_weather"}}

    def test_dict_no_name_returns_none(self):
        assert self.model._format_tool_choice({"type": "function"}) is None

    def test_dict_empty_returns_none(self):
        assert self.model._format_tool_choice({}) is None

    def test_non_string_non_dict_returns_none(self):
        assert self.model._format_tool_choice(123) is None  # type: ignore


class TestInvokeToolChoice:
    def test_invoke_includes_tool_choice(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        model.invoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=Message(role="assistant"),
            tools=SAMPLE_TOOLS,
            tool_choice={"type": "function", "name": "get_weather"},
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert "toolConfig" in call_kwargs
        assert call_kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": "get_weather"}}

    def test_invoke_no_tool_choice_omits_key(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        model.invoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=Message(role="assistant"),
            tools=SAMPLE_TOOLS,
            tool_choice=None,
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert "toolConfig" in call_kwargs
        assert "toolChoice" not in call_kwargs["toolConfig"]

    def test_invoke_tool_choice_without_tools_no_tool_config(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        model.invoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=Message(role="assistant"),
            tools=None,
            tool_choice={"type": "function", "name": "get_weather"},
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert "toolConfig" not in call_kwargs

    def test_invoke_string_any(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        model.invoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=Message(role="assistant"),
            tools=SAMPLE_TOOLS,
            tool_choice="any",
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert call_kwargs["toolConfig"]["toolChoice"] == {"any": {}}

    def test_invoke_string_none_omits_tool_choice(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        model.invoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=Message(role="assistant"),
            tools=SAMPLE_TOOLS,
            tool_choice="none",
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert "toolConfig" in call_kwargs
        assert "toolChoice" not in call_kwargs["toolConfig"]


class TestInvokeStreamToolChoice:
    def test_invoke_stream_includes_tool_choice(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse_stream.return_value = {
            "stream": [
                {"contentBlockDelta": {"delta": {"text": "Hello"}}},
                {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5}}},
            ]
        }

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        list(
            model.invoke_stream(
                messages=[Message(role="user", content="hi")],
                assistant_message=Message(role="assistant"),
                tools=SAMPLE_TOOLS,
                tool_choice={"type": "function", "function": {"name": "get_weather"}},
            )
        )

        call_kwargs = mock_client.converse_stream.call_args[1]
        assert "toolConfig" in call_kwargs
        assert call_kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": "get_weather"}}

    def test_invoke_stream_no_tool_choice_omits_key(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse_stream.return_value = {
            "stream": [
                {"contentBlockDelta": {"delta": {"text": "Hello"}}},
                {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5}}},
            ]
        }

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        list(
            model.invoke_stream(
                messages=[Message(role="user", content="hi")],
                assistant_message=Message(role="assistant"),
                tools=SAMPLE_TOOLS,
                tool_choice=None,
            )
        )

        call_kwargs = mock_client.converse_stream.call_args[1]
        assert "toolConfig" in call_kwargs
        assert "toolChoice" not in call_kwargs["toolConfig"]


@pytest.mark.asyncio
class TestAsyncInvokeToolChoice:
    async def test_ainvoke_includes_tool_choice(self):
        try:
            import aioboto3  # noqa: F401
        except ImportError:
            pytest.skip("aioboto3 not installed")

        mock_session, _ = _make_mock_session()
        mock_async_client = MagicMock()
        mock_async_client.converse = AsyncMock(return_value=CONVERSE_RESPONSE)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)

        with patch.object(model, "get_async_client", return_value=mock_async_client):
            await model.ainvoke(
                messages=[Message(role="user", content="hi")],
                assistant_message=Message(role="assistant"),
                tools=SAMPLE_TOOLS,
                tool_choice="any",
            )

        call_kwargs = mock_async_client.converse.call_args[1]
        assert "toolConfig" in call_kwargs
        assert call_kwargs["toolConfig"]["toolChoice"] == {"any": {}}

    async def test_ainvoke_stream_includes_tool_choice(self):
        try:
            import aioboto3  # noqa: F401
        except ImportError:
            pytest.skip("aioboto3 not installed")

        mock_session, _ = _make_mock_session()

        async def mock_stream():
            yield {"contentBlockDelta": {"delta": {"text": "Hello"}}}
            yield {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5}}}

        mock_async_client = MagicMock()
        mock_async_client.converse_stream = AsyncMock(return_value={"stream": mock_stream()})
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)

        with patch.object(model, "get_async_client", return_value=mock_async_client):
            responses = []
            async for response in model.ainvoke_stream(
                messages=[Message(role="user", content="hi")],
                assistant_message=Message(role="assistant"),
                tools=SAMPLE_TOOLS,
                tool_choice={"type": "tool", "name": "get_weather"},
            ):
                responses.append(response)

        call_kwargs = mock_async_client.converse_stream.call_args[1]
        assert "toolConfig" in call_kwargs
        assert call_kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": "get_weather"}}


class TestResponseFormatToTool:
    def setup_method(self):
        self.model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

    def test_pydantic_model_creates_tool(self):
        result = self.model._response_format_to_tool(MovieScript)
        assert result is not None
        assert result["toolSpec"]["name"] == STRUCTURED_OUTPUT_TOOL_NAME
        assert result["toolSpec"]["description"] == "Return a structured response matching the required schema"
        schema = result["toolSpec"]["inputSchema"]["json"]
        assert "title" in schema["properties"]
        assert "director" in schema["properties"]
        assert "year" in schema["properties"]

    def test_dict_returns_none(self):
        assert self.model._response_format_to_tool({"type": "json_object"}) is None

    def test_none_returns_none(self):
        assert self.model._response_format_to_tool(None) is None


class TestStructuredOutputInvoke:
    def test_invoke_with_pydantic_schema_injects_tool(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "123",
                                "name": STRUCTURED_OUTPUT_TOOL_NAME,
                                "input": {"title": "Inception", "director": "Nolan", "year": 2010},
                            }
                        }
                    ],
                }
            },
            "usage": {"inputTokens": 10, "outputTokens": 20},
            "stopReason": "tool_use",
        }

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        response = model.invoke(
            messages=[Message(role="user", content="Create a movie script")],
            assistant_message=Message(role="assistant"),
            response_format=MovieScript,
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert "toolConfig" in call_kwargs
        assert call_kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": STRUCTURED_OUTPUT_TOOL_NAME}}

        tools = call_kwargs["toolConfig"]["tools"]
        assert len(tools) == 1
        assert tools[0]["toolSpec"]["name"] == STRUCTURED_OUTPUT_TOOL_NAME

        assert response.content == '{"title": "Inception", "director": "Nolan", "year": 2010}'
        assert response.tool_calls == []

    def test_invoke_with_pydantic_schema_alongside_tools(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "123",
                                "name": STRUCTURED_OUTPUT_TOOL_NAME,
                                "input": {"title": "Movie", "director": "Dir", "year": 2020},
                            }
                        }
                    ],
                }
            },
            "usage": {"inputTokens": 10, "outputTokens": 20},
            "stopReason": "tool_use",
        }

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        model.invoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=Message(role="assistant"),
            response_format=MovieScript,
            tools=SAMPLE_TOOLS,
        )

        call_kwargs = mock_client.converse.call_args[1]
        tools = call_kwargs["toolConfig"]["tools"]
        assert len(tools) == 2
        tool_names = [t["toolSpec"]["name"] for t in tools]
        assert "get_weather" in tool_names
        assert STRUCTURED_OUTPUT_TOOL_NAME in tool_names

    def test_invoke_with_dict_response_format_no_tool_injection(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse.return_value = CONVERSE_RESPONSE

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        model.invoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=Message(role="assistant"),
            response_format={"type": "json_object"},
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert "toolConfig" not in call_kwargs


class TestStructuredOutputStreaming:
    def test_invoke_stream_with_pydantic_schema(self):
        mock_session, mock_client = _make_mock_session()
        mock_client.converse_stream.return_value = {
            "stream": [
                {
                    "contentBlockStart": {
                        "start": {"toolUse": {"toolUseId": "123", "name": STRUCTURED_OUTPUT_TOOL_NAME}}
                    }
                },
                {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"title": "'}}}},
                {"contentBlockDelta": {"delta": {"toolUse": {"input": 'Test"}'}}}},
                {"contentBlockStop": {}},
                {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5}}},
            ]
        }

        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0", session=mock_session)
        responses = list(
            model.invoke_stream(
                messages=[Message(role="user", content="hi")],
                assistant_message=Message(role="assistant"),
                response_format=MovieScript,
            )
        )

        call_kwargs = mock_client.converse_stream.call_args[1]
        assert call_kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": STRUCTURED_OUTPUT_TOOL_NAME}}

        contents = [r.content for r in responses if r.content]
        assert '{"title": "' in contents
        assert 'Test"}' in contents

        tool_calls = [r.tool_calls for r in responses if r.tool_calls]
        assert len(tool_calls) == 0


class TestParseProviderResponse:
    def setup_method(self):
        self.model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")

    def test_structured_output_tool_returns_content(self):
        response = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "123",
                                "name": STRUCTURED_OUTPUT_TOOL_NAME,
                                "input": {"key": "value"},
                            }
                        }
                    ],
                }
            },
            "usage": {"inputTokens": 10, "outputTokens": 5},
            "stopReason": "tool_use",
        }

        result = self.model._parse_provider_response(response, response_format=MovieScript)
        assert result.content == '{"key": "value"}'
        assert result.tool_calls == []

    def test_regular_tool_not_intercepted(self):
        response = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"toolUse": {"toolUseId": "123", "name": "get_weather", "input": {"city": "NYC"}}}],
                }
            },
            "usage": {"inputTokens": 10, "outputTokens": 5},
            "stopReason": "tool_use",
        }

        result = self.model._parse_provider_response(response, response_format=MovieScript)
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["function"]["name"] == "get_weather"
