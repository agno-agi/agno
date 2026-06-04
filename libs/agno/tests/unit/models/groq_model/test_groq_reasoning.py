from unittest.mock import MagicMock


class TestGroqReasoningExtraction:
    """Test that Groq model extracts reasoning from gpt-oss models."""

    def test_parse_provider_response_extracts_reasoning(self):
        """Test that _parse_provider_response extracts reasoning field from gpt-oss."""
        from agno.models.groq import Groq

        model = Groq(id="openai/gpt-oss-20b", api_key="test-key")

        mock_message = MagicMock()
        mock_message.role = "assistant"
        mock_message.content = "2 + 2 = 4"
        mock_message.reasoning = "The user asks for 2+2. Simple addition. Answer is 4."
        mock_message.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None

        result = model._parse_provider_response(mock_response)

        assert result.content == "2 + 2 = 4"
        assert result.reasoning_content == "The user asks for 2+2. Simple addition. Answer is 4."

    def test_parse_provider_response_no_reasoning(self):
        """Test that _parse_provider_response works when no reasoning field is present."""
        from agno.models.groq import Groq

        model = Groq(id="llama-3.3-70b-versatile", api_key="test-key")

        mock_message = MagicMock()
        mock_message.role = "assistant"
        mock_message.content = "Hello!"
        mock_message.tool_calls = None
        del mock_message.reasoning

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None

        result = model._parse_provider_response(mock_response)

        assert result.content == "Hello!"
        assert result.reasoning_content is None

    def test_parse_provider_response_delta_extracts_reasoning(self):
        """Test that _parse_provider_response_delta extracts reasoning from streaming chunks."""
        from agno.models.groq import Groq

        model = Groq(id="openai/gpt-oss-20b", api_key="test-key")

        mock_delta = MagicMock()
        mock_delta.content = "The answer"
        mock_delta.reasoning = "Thinking..."
        mock_delta.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.delta = mock_delta

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.x_groq = None

        result = model._parse_provider_response_delta(mock_response)

        assert result.content == "The answer"
        assert result.reasoning_content == "Thinking..."

    def test_parse_provider_response_delta_no_reasoning(self):
        """Test that _parse_provider_response_delta works when no reasoning field is present."""
        from agno.models.groq import Groq

        model = Groq(id="llama-3.3-70b-versatile", api_key="test-key")

        mock_delta = MagicMock()
        mock_delta.content = "Hello"
        mock_delta.tool_calls = None
        del mock_delta.reasoning

        mock_choice = MagicMock()
        mock_choice.delta = mock_delta

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.x_groq = None

        result = model._parse_provider_response_delta(mock_response)

        assert result.content == "Hello"
        assert result.reasoning_content is None
