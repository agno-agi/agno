"""Unit tests for GeminiInteractions model class."""

import base64
from unittest.mock import MagicMock, patch

import pytest

from agno.media import Audio, File, Image, Video
from agno.models.google.gemini_interactions import GeminiInteractions
from agno.models.message import Message


class TestGetClient:
    """Tests for client initialization."""

    def test_get_client_with_api_key(self):
        model = GeminiInteractions(api_key="test-key")

        with patch("agno.models.google.gemini_interactions.genai.Client") as mock_client_cls:
            model.get_client()
            _, kwargs = mock_client_cls.call_args
            assert kwargs["api_key"] == "test-key"

    def test_get_client_caches_instance(self):
        model = GeminiInteractions(api_key="test-key")

        with patch("agno.models.google.gemini_interactions.genai.Client") as mock_client_cls:
            client1 = model.get_client()
            client2 = model.get_client()
            assert client1 is client2
            mock_client_cls.assert_called_once()

    def test_get_client_timeout_configuration(self):
        model = GeminiInteractions(api_key="test-key", timeout=30.0)

        with patch("agno.models.google.gemini_interactions.genai.Client") as mock_client_cls:
            model.get_client()
            _, kwargs = mock_client_cls.call_args
            assert kwargs["http_options"]["timeout"] == 30000


class TestFormatTools:
    """Tests for tool formatting."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_no_tools(self):
        model = self._make_model()
        result = model._format_tools(None)
        assert result == []

    def test_function_tools(self):
        model = self._make_model()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                },
            }
        ]
        result = model._format_tools(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["name"] == "get_weather"
        assert result[0]["description"] == "Get weather for a city"
        assert result[0]["parameters"] == {"type": "object", "properties": {"city": {"type": "string"}}}

    def test_builtin_search_tool_added_in_request_kwargs(self):
        """Built-in tools are added in _get_request_kwargs, not _format_tools."""
        model = GeminiInteractions(api_key="test-key", search=True)
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert {"type": "google_search"} in kwargs["tools"]

    def test_builtin_url_context_tool_added_in_request_kwargs(self):
        model = GeminiInteractions(api_key="test-key", url_context=True)
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert {"type": "url_context"} in kwargs["tools"]

    def test_builtin_code_execution_tool_added_in_request_kwargs(self):
        model = GeminiInteractions(api_key="test-key", code_execution=True)
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert {"type": "code_execution"} in kwargs["tools"]

    def test_function_object_tools(self):
        """_format_tools handles Function objects from the agent."""
        from agno.tools.function import Function

        def dummy_func(x: str) -> str:
            """A dummy function."""
            return x

        func = Function(name="dummy", description="A dummy function", entrypoint=dummy_func)
        model = self._make_model()
        result = model._format_tools([func])
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["name"] == "dummy"


class TestBuildInput:
    """Tests for message formatting into interaction turns."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_user_message(self):
        model = self._make_model()
        messages = [Message(role="user", content="Hello")]
        steps = model._build_input(messages)
        assert len(steps) == 1
        assert steps[0]["type"] == "user_input"
        assert steps[0]["content"] == [{"type": "text", "text": "Hello"}]

    def test_system_message_skipped(self):
        model = self._make_model()
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hi"),
        ]
        steps = model._build_input(messages)
        assert len(steps) == 1
        assert steps[0]["type"] == "user_input"

    def test_assistant_message_without_tool_calls_skipped(self):
        """Assistant messages without tool calls produce no steps (text responses are not re-sent)."""
        model = self._make_model()
        messages = [Message(role="assistant", content="I can help")]
        steps = model._build_input(messages)
        assert len(steps) == 0

    def test_tool_call_message(self):
        model = self._make_model()
        messages = [
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                    }
                ],
            )
        ]
        steps = model._build_input(messages)
        assert len(steps) == 1
        assert steps[0]["type"] == "function_call"
        assert steps[0]["id"] == "call_123"
        assert steps[0]["name"] == "get_weather"
        assert steps[0]["arguments"] == {"city": "Paris"}

    def test_tool_result_message(self):
        model = self._make_model()
        messages = [Message(role="tool", content="Sunny, 25C", tool_call_id="call_123", tool_name="get_weather")]
        steps = model._build_input(messages)
        assert len(steps) == 1
        assert steps[0]["type"] == "function_result"
        assert steps[0]["call_id"] == "call_123"
        assert steps[0]["name"] == "get_weather"
        assert steps[0]["result"] == "Sunny, 25C"

    def test_tool_call_with_invalid_json_arguments(self):
        model = self._make_model()
        messages = [
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_456",
                        "type": "function",
                        "function": {"name": "func", "arguments": "not valid json"},
                    }
                ],
            )
        ]
        steps = model._build_input(messages)
        assert steps[0]["type"] == "function_call"
        assert steps[0]["arguments"] == {}

    def test_multi_turn_conversation(self):
        model = self._make_model()
        messages = [
            Message(role="system", content="Be helpful"),
            Message(role="user", content="Hi"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
            ),
            Message(role="tool", content="result", tool_call_id="c1", tool_name="f"),
            Message(role="user", content="How are you?"),
        ]
        steps = model._build_input(messages)
        # system skipped, assistant with tool_calls -> function_call, tool -> function_result, user -> user_input
        assert len(steps) == 4
        assert steps[0]["type"] == "user_input"
        assert steps[1]["type"] == "function_call"
        assert steps[2]["type"] == "function_result"
        assert steps[3]["type"] == "user_input"


class TestGetRequestKwargs:
    """Tests for request parameter building."""

    def _make_model(self, **kwargs):
        return GeminiInteractions(api_key="test-key", **kwargs)

    def test_basic_request(self):
        model = self._make_model()
        messages = [Message(role="user", content="Hello")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["model"] == "gemini-3-flash-preview"
        assert "input" in kwargs
        assert "system_instruction" not in kwargs

    def test_system_instruction_extracted(self):
        model = self._make_model()
        messages = [
            Message(role="system", content="You are a poet"),
            Message(role="user", content="Write a haiku"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["system_instruction"] == "You are a poet"

    def test_generation_config(self):
        model = self._make_model(temperature=0.5, top_p=0.9, max_output_tokens=100)
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["generation_config"]["temperature"] == 0.5
        assert kwargs["generation_config"]["top_p"] == 0.9
        assert kwargs["generation_config"]["max_output_tokens"] == 100

    def test_generation_config_omitted_when_empty(self):
        model = self._make_model()
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert "generation_config" not in kwargs

    def test_tools_included(self):
        model = self._make_model()
        # Tools are already formatted by _format_tools before reaching _get_request_kwargs
        tools = [
            {"type": "function", "name": "func", "description": "desc", "parameters": {}},
        ]
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages, tools=tools)
        assert "tools" in kwargs
        assert kwargs["tools"][0]["name"] == "func"

    def test_store_parameter(self):
        model = self._make_model(store=False)
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["store"] is False

    def test_previous_interaction_id_from_provider_data(self):
        """Previous interaction ID is read from assistant message provider_data."""
        model = self._make_model()
        messages = [
            Message(role="user", content="First message"),
            Message(role="assistant", content="Response", provider_data={"interaction_id": "interactions/abc123"}),
            Message(role="user", content="Follow up"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["previous_interaction_id"] == "interactions/abc123"

    def test_no_previous_interaction_id_on_first_turn(self):
        model = self._make_model()
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert "previous_interaction_id" not in kwargs

    def test_thinking_config(self):
        model = self._make_model(thinking_level="high")
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["generation_config"]["thinking_level"] == "high"

    def test_response_modalities(self):
        model = self._make_model(response_modalities=["text", "image"])
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["response_modalities"] == ["text", "image"]


class TestParseInteractionResponse:
    """Tests for parsing Interaction API responses."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def _make_model_output_step(self, text):
        """Create a mock ModelOutputStep with TextContent."""
        from agno.models.google.gemini_interactions import ModelOutputStep, TextContent

        mock_text = MagicMock(spec=TextContent)
        mock_text.text = text
        mock_text.__class__ = TextContent

        mock_step = MagicMock(spec=ModelOutputStep)
        mock_step.content = [mock_text]
        mock_step.__class__ = ModelOutputStep
        return mock_step

    def _make_thought_step(self, summary_text, signature=None):
        from agno.models.google.gemini_interactions import TextContent, ThoughtStep

        # ThoughtStep.summary is List[TextContent | ImageContent]
        mock_summary_item = MagicMock(spec=TextContent)
        mock_summary_item.text = summary_text
        mock_summary_item.__class__ = TextContent

        mock_step = MagicMock(spec=ThoughtStep)
        mock_step.summary = [mock_summary_item]
        mock_step.signature = signature
        mock_step.__class__ = ThoughtStep
        return mock_step

    def _make_function_call_step(self, call_id, name, arguments, signature=None):
        from agno.models.google.gemini_interactions import FunctionCallStep

        mock_step = MagicMock(spec=FunctionCallStep)
        mock_step.id = call_id
        mock_step.name = name
        mock_step.arguments = arguments
        mock_step.signature = signature
        mock_step.__class__ = FunctionCallStep
        return mock_step

    def test_parse_text_response(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/test123"
        mock_interaction.steps = [self._make_model_output_step("Hello, world!")]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.role == "assistant"
        assert response.content == "Hello, world!"
        assert response.provider_data["interaction_id"] == "interactions/test123"

    def test_parse_function_call_response(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/test456"
        mock_interaction.steps = [self._make_function_call_step("call_1", "get_weather", {"city": "Paris"})]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0]["id"] == "call_1"
        assert response.tool_calls[0]["function"]["name"] == "get_weather"
        assert response.tool_calls[0]["function"]["arguments"] == '{"city": "Paris"}'

    def test_parse_thought_response(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/thought1"
        mock_interaction.steps = [
            self._make_thought_step("Let me think about this...", signature="sig123"),
            self._make_model_output_step("Here is my answer."),
        ]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.reasoning_content == "Let me think about this..."
        assert response.content == "Here is my answer."
        assert response.provider_data["thought_signature"] == "sig123"

    def test_parse_usage_metrics(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/metrics1"
        mock_interaction.steps = [self._make_model_output_step("Hello")]

        mock_usage = MagicMock()
        mock_usage.total_input_tokens = 10
        mock_usage.total_output_tokens = 20
        mock_usage.total_tokens = 30
        mock_interaction.usage = mock_usage

        response = model._parse_provider_response(mock_interaction)
        assert response.response_usage is not None
        assert response.response_usage.input_tokens == 10
        assert response.response_usage.output_tokens == 20
        assert response.response_usage.total_tokens == 30

    def test_parse_empty_response(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/empty1"
        mock_interaction.steps = []
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.role == "assistant"
        assert response.content is None
        assert response.tool_calls == []

    def test_interaction_id_in_provider_data(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/first"
        mock_interaction.steps = []
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.provider_data["interaction_id"] == "interactions/first"

    def test_multiple_function_calls(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/multi"
        mock_interaction.steps = [
            self._make_function_call_step("call_1", "func_a", {"x": 1}),
            self._make_function_call_step("call_2", "func_b", {"y": 2}),
        ]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert len(response.tool_calls) == 2
        assert response.tool_calls[0]["function"]["name"] == "func_a"
        assert response.tool_calls[1]["function"]["name"] == "func_b"

    def test_function_call_with_signature(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/sig"
        mock_interaction.steps = [
            self._make_function_call_step("call_1", "func", {"x": 1}, signature="thought_sig_abc"),
        ]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.tool_calls[0]["thought_signature"] == "thought_sig_abc"

    def test_parse_none_usage_fields(self):
        """Usage fields that are None should default to 0."""
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/nullusage"
        mock_interaction.steps = [self._make_model_output_step("Hi")]

        mock_usage = MagicMock()
        mock_usage.total_input_tokens = None
        mock_usage.total_output_tokens = None
        mock_usage.total_tokens = None
        mock_interaction.usage = mock_usage

        response = model._parse_provider_response(mock_interaction)
        assert response.response_usage.input_tokens == 0
        assert response.response_usage.output_tokens == 0
        assert response.response_usage.total_tokens == 0


class TestInvoke:
    """Tests for the invoke method."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_invoke_calls_interactions_create(self):
        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/invoke1"
        mock_interaction.steps = []
        mock_interaction.usage = None
        mock_client.interactions.create.return_value = mock_interaction

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        model.invoke(messages, assistant_message)

        mock_client.interactions.create.assert_called_once()
        call_kwargs = mock_client.interactions.create.call_args[1]
        assert call_kwargs["model"] == "gemini-3-flash-preview"
        assert "input" in call_kwargs

    def test_invoke_passes_tools(self):
        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/tools1"
        mock_interaction.steps = []
        mock_interaction.usage = None
        mock_client.interactions.create.return_value = mock_interaction

        # Tools passed to invoke() are already formatted by _format_tools (Interactions API format)
        tools = [
            {"type": "function", "name": "search", "description": "Search", "parameters": {}},
        ]
        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        model.invoke(messages, assistant_message, tools=tools)

        call_kwargs = mock_client.interactions.create.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tools"][0]["name"] == "search"

    def test_invoke_error_raises_model_provider_error(self):
        from agno.exceptions import ModelProviderError

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client
        mock_client.interactions.create.side_effect = Exception("API error")

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        with pytest.raises(ModelProviderError, match="API error"):
            model.invoke(messages, assistant_message)

    def test_invoke_returns_interaction_id_in_provider_data(self):
        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/tracked1"
        mock_interaction.steps = []
        mock_interaction.usage = None
        mock_client.interactions.create.return_value = mock_interaction

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        response = model.invoke(messages, assistant_message)
        assert response.provider_data["interaction_id"] == "interactions/tracked1"


class TestInvokeAsync:
    """Tests for the async invoke method."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    @pytest.mark.asyncio
    async def test_ainvoke_calls_interactions_create(self):
        from unittest.mock import AsyncMock

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/async1"
        mock_interaction.steps = []
        mock_interaction.usage = None
        mock_client.aio.interactions.create = AsyncMock(return_value=mock_interaction)

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        await model.ainvoke(messages, assistant_message)

        mock_client.aio.interactions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_ainvoke_error_raises_model_provider_error(self):
        from unittest.mock import AsyncMock

        from agno.exceptions import ModelProviderError

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client
        mock_client.aio.interactions.create = AsyncMock(side_effect=Exception("Async error"))

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        with pytest.raises(ModelProviderError, match="Async error"):
            await model.ainvoke(messages, assistant_message)


class TestInvokeStream:
    """Tests for streaming invoke."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_invoke_stream_sets_stream_param(self):
        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client
        mock_client.interactions.create.return_value = iter([])

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        list(model.invoke_stream(messages, assistant_message))

        call_kwargs = mock_client.interactions.create.call_args[1]
        assert call_kwargs["stream"] is True

    def test_invoke_stream_handles_text_delta(self):
        from agno.models.google.gemini_interactions import DeltaText, interaction_types

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        # Create a mock StepDelta event with DeltaText
        mock_event = MagicMock(spec=interaction_types.StepDelta)
        mock_event.__class__ = interaction_types.StepDelta
        mock_delta = MagicMock(spec=DeltaText)
        mock_delta.__class__ = DeltaText
        mock_delta.text = "Hello"
        mock_event.delta = mock_delta

        mock_client.interactions.create.return_value = iter([mock_event])

        messages = [Message(role="user", content="Hi")]
        assistant_message = Message(role="assistant")

        responses = list(model.invoke_stream(messages, assistant_message))
        assert any(r.content == "Hello" for r in responses)

    def test_invoke_stream_handles_interaction_created(self):
        from agno.models.google.gemini_interactions import interaction_types

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        mock_event = MagicMock(spec=interaction_types.InteractionCreatedEvent)
        mock_event.__class__ = interaction_types.InteractionCreatedEvent
        mock_event.interaction = MagicMock()
        mock_event.interaction.id = "interactions/stream1"

        mock_client.interactions.create.return_value = iter([mock_event])

        messages = [Message(role="user", content="Hi")]
        assistant_message = Message(role="assistant")

        responses = list(model.invoke_stream(messages, assistant_message))
        assert any(
            r.provider_data and r.provider_data.get("interaction_id") == "interactions/stream1" for r in responses
        )
        assert any(r.role == "assistant" for r in responses)

    def test_invoke_stream_handles_function_call_with_argument_deltas(self):
        from agno.models.google.gemini_interactions import (
            DeltaArgumentsDelta,
            FunctionCallStep,
            interaction_types,
        )

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        # StepStart with FunctionCallStep (arguments initially empty)
        mock_step = MagicMock(spec=FunctionCallStep)
        mock_step.__class__ = FunctionCallStep
        mock_step.id = "call_stream_1"
        mock_step.name = "get_weather"
        mock_step.arguments = {}
        mock_step.signature = None

        mock_start = MagicMock(spec=interaction_types.StepStart)
        mock_start.__class__ = interaction_types.StepStart
        mock_start.step = mock_step
        mock_start.index = 0

        # DeltaArgumentsDelta with the actual arguments
        mock_delta = MagicMock(spec=DeltaArgumentsDelta)
        mock_delta.__class__ = DeltaArgumentsDelta
        mock_delta.arguments = '{"city": "London"}'

        mock_delta_event = MagicMock(spec=interaction_types.StepDelta)
        mock_delta_event.__class__ = interaction_types.StepDelta
        mock_delta_event.delta = mock_delta
        mock_delta_event.index = 0

        # StepStop to emit the complete tool call
        mock_stop = MagicMock(spec=interaction_types.StepStop)
        mock_stop.__class__ = interaction_types.StepStop
        mock_stop.index = 0

        mock_client.interactions.create.return_value = iter([mock_start, mock_delta_event, mock_stop])

        messages = [Message(role="user", content="Weather?")]
        assistant_message = Message(role="assistant")

        responses = list(model.invoke_stream(messages, assistant_message))
        tool_responses = [r for r in responses if r.tool_calls]
        assert len(tool_responses) == 1
        assert tool_responses[0].tool_calls[0]["function"]["name"] == "get_weather"
        assert tool_responses[0].tool_calls[0]["function"]["arguments"] == '{"city": "London"}'

    def test_invoke_stream_error_raises_model_provider_error(self):
        from agno.exceptions import ModelProviderError

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client
        mock_client.interactions.create.side_effect = Exception("Stream error")

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        with pytest.raises(ModelProviderError, match="Stream error"):
            list(model.invoke_stream(messages, assistant_message))


class TestToDict:
    """Tests for model serialization."""

    def test_basic_serialization(self):
        model = GeminiInteractions(api_key="test-key")
        d = model.to_dict()
        assert d["id"] == "gemini-3-flash-preview"
        assert d["name"] == "GeminiInteractions"
        assert d["provider"] == "Google"

    def test_serialization_with_params(self):
        model = GeminiInteractions(
            api_key="test-key",
            temperature=0.7,
            search=True,
            store=False,
        )
        d = model.to_dict()
        assert d["temperature"] == 0.7
        assert d["search"] is True
        assert d["store"] is False

    def test_none_values_excluded(self):
        model = GeminiInteractions(api_key="test-key")
        d = model.to_dict()
        assert "temperature" not in d
        assert "thinking_level" not in d

    def test_service_tier_serialization(self):
        model = GeminiInteractions(api_key="test-key", service_tier="flex")
        d = model.to_dict()
        assert d["service_tier"] == "flex"


class TestMultimodalInput:
    """Tests for multimodal input support in _build_input."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_image_from_bytes(self):
        model = self._make_model()
        img_bytes = b"\x89PNG\r\n\x1a\n"
        messages = [Message(role="user", content="What is this?", images=[Image(content=img_bytes)])]
        steps = model._build_input(messages)
        assert len(steps) == 1
        content = steps[0]["content"]
        assert len(content) == 2  # text + image
        assert content[0]["type"] == "text"
        image_item = content[1]
        assert image_item["type"] == "image"
        assert image_item["mime_type"] == "image/jpeg"
        assert image_item["data"] == base64.b64encode(img_bytes).decode("utf-8")

    def test_image_from_url(self):
        model = self._make_model()
        messages = [
            Message(
                role="user",
                content="Describe this",
                images=[Image(url="https://example.com/img.png", mime_type="image/png")],
            )
        ]
        steps = model._build_input(messages)
        image_item = steps[0]["content"][1]
        assert image_item["type"] == "image"
        assert image_item["uri"] == "https://example.com/img.png"
        assert image_item["mime_type"] == "image/png"

    def test_audio_from_bytes(self):
        model = self._make_model()
        audio_bytes = b"RIFF\x00\x00\x00\x00WAVEfmt "
        messages = [
            Message(role="user", content="Transcribe", audio=[Audio(content=audio_bytes, mime_type="audio/wav")])
        ]
        steps = model._build_input(messages)
        audio_item = steps[0]["content"][1]
        assert audio_item["type"] == "audio"
        assert audio_item["mime_type"] == "audio/wav"
        assert audio_item["data"] == base64.b64encode(audio_bytes).decode("utf-8")

    def test_video_from_url(self):
        model = self._make_model()
        messages = [
            Message(
                role="user",
                content="What happens in this video?",
                videos=[Video(url="https://example.com/video.mp4")],
            )
        ]
        steps = model._build_input(messages)
        video_item = steps[0]["content"][1]
        assert video_item["type"] == "video"
        assert video_item["uri"] == "https://example.com/video.mp4"

    def test_document_from_bytes(self):
        model = self._make_model()
        pdf_bytes = b"%PDF-1.4 fake content"
        messages = [
            Message(
                role="user",
                content="Summarize this document",
                files=[File(content=pdf_bytes, mime_type="application/pdf")],
            )
        ]
        steps = model._build_input(messages)
        doc_item = steps[0]["content"][1]
        assert doc_item["type"] == "document"
        assert doc_item["mime_type"] == "application/pdf"

    def test_multiple_media_types_combined(self):
        model = self._make_model()
        messages = [
            Message(
                role="user",
                content="Compare these",
                images=[Image(content=b"img1"), Image(content=b"img2")],
                audio=[Audio(content=b"audio1", mime_type="audio/mp3")],
            )
        ]
        steps = model._build_input(messages)
        content = steps[0]["content"]
        # 1 text + 2 images + 1 audio
        assert len(content) == 4
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image"
        assert content[2]["type"] == "image"
        assert content[3]["type"] == "audio"

    def test_image_only_no_text(self):
        """Message with only images and no text content."""
        model = self._make_model()
        messages = [Message(role="user", content=None, images=[Image(content=b"imgdata")])]
        steps = model._build_input(messages)
        assert len(steps) == 1
        content = steps[0]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "image"


class TestMultimodalOutput:
    """Tests for multimodal output parsing."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_parse_image_output(self):
        from agno.models.google.gemini_interactions import ImageContent, ModelOutputStep

        if ImageContent is None:
            pytest.skip("ImageContent not available in SDK")

        model = self._make_model()

        img_data = base64.b64encode(b"fake_png_data").decode("utf-8")
        mock_img = MagicMock(spec=ImageContent)
        mock_img.__class__ = ImageContent
        mock_img.data = img_data
        mock_img.mime_type = "image/png"
        mock_img.uri = None

        mock_step = MagicMock(spec=ModelOutputStep)
        mock_step.__class__ = ModelOutputStep
        mock_step.content = [mock_img]

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/img_out"
        mock_interaction.steps = [mock_step]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.images is not None
        assert len(response.images) == 1
        assert response.images[0].content == b"fake_png_data"
        assert response.images[0].mime_type == "image/png"

    def test_parse_audio_output(self):
        from agno.models.google.gemini_interactions import AudioContent, ModelOutputStep

        if AudioContent is None:
            pytest.skip("AudioContent not available in SDK")

        model = self._make_model()

        audio_data = base64.b64encode(b"fake_wav_data").decode("utf-8")
        mock_audio = MagicMock(spec=AudioContent)
        mock_audio.__class__ = AudioContent
        mock_audio.data = audio_data
        mock_audio.mime_type = "audio/wav"
        mock_audio.uri = None

        mock_step = MagicMock(spec=ModelOutputStep)
        mock_step.__class__ = ModelOutputStep
        mock_step.content = [mock_audio]

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/audio_out"
        mock_interaction.steps = [mock_step]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.audio is not None
        assert response.audio.content == b"fake_wav_data"
        assert response.audio.mime_type == "audio/wav"

    def test_parse_mixed_text_and_image_output(self):
        from agno.models.google.gemini_interactions import ImageContent, ModelOutputStep, TextContent

        if ImageContent is None:
            pytest.skip("ImageContent not available in SDK")

        model = self._make_model()

        mock_text = MagicMock(spec=TextContent)
        mock_text.__class__ = TextContent
        mock_text.text = "Here is the generated image:"

        img_data = base64.b64encode(b"generated_image").decode("utf-8")
        mock_img = MagicMock(spec=ImageContent)
        mock_img.__class__ = ImageContent
        mock_img.data = img_data
        mock_img.mime_type = "image/png"
        mock_img.uri = None

        mock_step = MagicMock(spec=ModelOutputStep)
        mock_step.__class__ = ModelOutputStep
        mock_step.content = [mock_text, mock_img]

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/mixed"
        mock_interaction.steps = [mock_step]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.content == "Here is the generated image:"
        assert response.images is not None
        assert len(response.images) == 1


class TestServiceTier:
    """Tests for service_tier (flex/priority inference)."""

    def test_service_tier_in_request_kwargs(self):
        model = GeminiInteractions(api_key="test-key", service_tier="flex")
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["service_tier"] == "flex"

    def test_priority_tier_in_request_kwargs(self):
        model = GeminiInteractions(api_key="test-key", service_tier="priority")
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["service_tier"] == "priority"

    def test_no_service_tier_by_default(self):
        model = GeminiInteractions(api_key="test-key")
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert "service_tier" not in kwargs


class TestStructuredOutput:
    """Tests for structured output / response_format."""

    def test_pydantic_model_response_format(self):
        from pydantic import BaseModel as PydanticModel

        class MovieReview(PydanticModel):
            title: str
            rating: int
            summary: str

        model = GeminiInteractions(api_key="test-key")
        messages = [Message(role="user", content="Review The Matrix")]
        kwargs = model._get_request_kwargs(messages, response_format=MovieReview)
        assert kwargs["response_format"]["type"] == "text"
        assert kwargs["response_format"]["mime_type"] == "application/json"
        assert "schema" in kwargs["response_format"]
        schema = kwargs["response_format"]["schema"]
        assert "title" in schema["properties"]
        assert "rating" in schema["properties"]
        assert "summary" in schema["properties"]

    def test_dict_response_format_passthrough(self):
        model = GeminiInteractions(api_key="test-key")
        messages = [Message(role="user", content="Hi")]
        custom_format = {"type": "text", "json_schema": {"type": "object"}}
        kwargs = model._get_request_kwargs(messages, response_format=custom_format)
        assert kwargs["response_format"] == custom_format

    def test_no_response_format_by_default(self):
        model = GeminiInteractions(api_key="test-key")
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert "response_format" not in kwargs
