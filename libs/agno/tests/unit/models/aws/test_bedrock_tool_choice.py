from unittest.mock import MagicMock, patch

import pytest
from boto3.session import Session

from agno.models.aws import AwsBedrock
from agno.models.message import Message


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
        mock_async_client.converse = MagicMock(return_value=CONVERSE_RESPONSE)
        mock_async_client.__aenter__ = MagicMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = MagicMock(return_value=None)

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
