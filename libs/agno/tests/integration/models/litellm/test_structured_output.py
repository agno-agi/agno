"""
Tests for LiteLLM structured output support.

These tests verify that:
1. The structured output flags default to False (safe for all providers)
2. Users can explicitly enable structured outputs for supported models
3. The response_format parameter is correctly converted and passed to LiteLLM
4. The response_format is only passed when supports_native_structured_outputs=True
"""

from typing import List
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.litellm import LiteLLM


# Test Pydantic models
class SimpleOutput(BaseModel):
    """Simple output model for testing."""

    answer: str = Field(..., description="The answer")
    confidence: float = Field(..., description="Confidence score between 0 and 1")


class MovieScript(BaseModel):
    """Complex output model for testing nested types."""

    setting: str = Field(..., description="The movie setting")
    characters: List[str] = Field(..., description="List of character names")
    plot_summary: str = Field(..., description="Brief plot summary")


class TestLiteLLMStructuredOutputFlags:
    """Test that structured output flags are properly configured."""

    def test_default_flags_are_false(self):
        """Test that structured output flags default to False for safety."""
        model = LiteLLM(id="gpt-4o")
        assert model.supports_native_structured_outputs is False
        assert model.supports_json_schema_outputs is False

    def test_can_enable_native_structured_outputs(self):
        """Test that users can explicitly enable native structured outputs."""
        model = LiteLLM(
            id="gpt-4o",
            supports_native_structured_outputs=True,
        )
        assert model.supports_native_structured_outputs is True

    def test_can_enable_json_schema_outputs(self):
        """Test that users can explicitly enable JSON schema outputs."""
        model = LiteLLM(
            id="gpt-4o",
            supports_json_schema_outputs=True,
        )
        assert model.supports_json_schema_outputs is True

    def test_can_enable_both_flags(self):
        """Test that both flags can be enabled together."""
        model = LiteLLM(
            id="gpt-4o",
            supports_native_structured_outputs=True,
            supports_json_schema_outputs=True,
        )
        assert model.supports_native_structured_outputs is True
        assert model.supports_json_schema_outputs is True


class TestResponseFormatConversion:
    """Test the _get_response_format_param method."""

    def test_none_response_format(self):
        """Test that None response_format returns None."""
        model = LiteLLM(id="gpt-4o")
        result = model._get_response_format_param(None)
        assert result is None

    def test_dict_response_format_passthrough(self):
        """Test that dict response_format is passed through unchanged."""
        model = LiteLLM(id="gpt-4o")
        input_format = {"type": "json_object"}
        result = model._get_response_format_param(input_format)
        assert result == input_format

    def test_pydantic_model_conversion(self):
        """Test that Pydantic model is converted to JSON schema format."""
        model = LiteLLM(id="gpt-4o")
        result = model._get_response_format_param(SimpleOutput)

        assert result is not None
        assert result["type"] == "json_schema"
        assert result["json_schema"]["name"] == "SimpleOutput"
        assert result["json_schema"]["strict"] is True
        assert "schema" in result["json_schema"]
        assert "properties" in result["json_schema"]["schema"]

    def test_pydantic_model_includes_additional_properties_false(self):
        """Test that converted schema includes additionalProperties: false.
        
        This is required by OpenAI's strict mode for structured outputs.
        Without this, the API returns a 400 error.
        """
        model = LiteLLM(id="gpt-4o")
        result = model._get_response_format_param(SimpleOutput)

        schema = result["json_schema"]["schema"]
        # The schema should have additionalProperties: false set by get_response_schema_for_provider
        assert schema.get("additionalProperties") is False

    def test_complex_pydantic_model_conversion(self):
        """Test conversion of complex Pydantic model with nested types."""
        model = LiteLLM(id="gpt-4o")
        result = model._get_response_format_param(MovieScript)

        assert result is not None
        assert result["type"] == "json_schema"
        assert result["json_schema"]["name"] == "MovieScript"

        schema = result["json_schema"]["schema"]
        assert "setting" in schema["properties"]
        assert "characters" in schema["properties"]
        # Verify additionalProperties is set
        assert schema.get("additionalProperties") is False


class TestLiteLLMInvokeWithResponseFormat:
    """Test that invoke methods properly pass response_format to LiteLLM."""

    @patch("agno.models.litellm.chat.litellm")
    def test_invoke_passes_response_format_when_supported(self, mock_litellm):
        """Test that invoke passes response_format when supports_native_structured_outputs=True."""
        # Setup mock
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"answer": "Paris", "confidence": 0.95}'
        mock_response.choices[0].message.tool_calls = None
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
        mock_litellm.completion.return_value = mock_response
        mock_litellm.validate_environment.return_value = {"keys_in_environment": True}

        # Enable structured output support
        model = LiteLLM(
            id="gpt-4o",
            api_key="test-key",
            supports_native_structured_outputs=True,
        )
        model.client = mock_litellm

        # Create a mock message
        from agno.models.message import Message

        messages = [Message(role="user", content="What is the capital of France?")]
        assistant_message = Message(role="assistant", content="")

        # Call invoke with response_format
        model.invoke(
            messages=messages,
            assistant_message=assistant_message,
            response_format=SimpleOutput,
        )

        # Verify response_format was passed to completion
        call_kwargs = mock_litellm.completion.call_args[1]
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"]["type"] == "json_schema"
        assert call_kwargs["response_format"]["json_schema"]["name"] == "SimpleOutput"

    @patch("agno.models.litellm.chat.litellm")
    def test_invoke_does_not_pass_response_format_when_not_supported(self, mock_litellm):
        """Test that invoke does NOT pass response_format when supports_native_structured_outputs=False.
        
        This is critical for providers like Anthropic that don't support response_format.
        """
        # Setup mock
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"answer": "Paris", "confidence": 0.95}'
        mock_response.choices[0].message.tool_calls = None
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
        mock_litellm.completion.return_value = mock_response
        mock_litellm.validate_environment.return_value = {"keys_in_environment": True}

        # Keep structured output support disabled (default)
        model = LiteLLM(
            id="anthropic--claude-4-sonnet",
            api_key="test-key",
            # supports_native_structured_outputs=False  # Default
        )
        model.client = mock_litellm

        from agno.models.message import Message

        messages = [Message(role="user", content="What is the capital of France?")]
        assistant_message = Message(role="assistant", content="")

        # Call invoke with response_format (but model doesn't support it)
        model.invoke(
            messages=messages,
            assistant_message=assistant_message,
            response_format=SimpleOutput,
        )

        # Verify response_format was NOT passed to completion
        call_kwargs = mock_litellm.completion.call_args[1]
        assert "response_format" not in call_kwargs

    @patch("agno.models.litellm.chat.litellm")
    def test_invoke_without_response_format(self, mock_litellm):
        """Test that invoke works without response_format."""
        # Setup mock
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "The capital of France is Paris."
        mock_response.choices[0].message.tool_calls = None
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
        mock_litellm.completion.return_value = mock_response
        mock_litellm.validate_environment.return_value = {"keys_in_environment": True}

        model = LiteLLM(id="gpt-4o", api_key="test-key")
        model.client = mock_litellm

        from agno.models.message import Message

        messages = [Message(role="user", content="What is the capital of France?")]
        assistant_message = Message(role="assistant", content="")

        # Call invoke without response_format
        model.invoke(
            messages=messages,
            assistant_message=assistant_message,
            response_format=None,
        )

        # Verify response_format was NOT passed to completion
        call_kwargs = mock_litellm.completion.call_args[1]
        assert "response_format" not in call_kwargs or call_kwargs.get("response_format") is None


class TestAgentWithLiteLLMStructuredOutput:
    """Test Agent integration with LiteLLM structured outputs."""

    def test_agent_with_structured_output_enabled_openai(self):
        """Test that Agent works with LiteLLM when structured outputs are enabled for OpenAI."""
        model = LiteLLM(
            id="gpt-4o",
            supports_native_structured_outputs=True,
        )
        agent = Agent(
            model=model,
            output_schema=SimpleOutput,
            structured_outputs=True,
        )

        assert agent.model.supports_native_structured_outputs is True

    def test_agent_with_structured_output_disabled_anthropic(self):
        """Test that Agent falls back to JSON mode for Anthropic (which doesn't support response_format)."""
        model = LiteLLM(id="anthropic--claude-4-sonnet")  # defaults to False
        agent = Agent(
            model=model,
            output_schema=SimpleOutput,
            structured_outputs=True,
        )

        # Model doesn't support native structured outputs, so agent should use JSON mode
        assert agent.model.supports_native_structured_outputs is False

    def test_different_models_different_settings(self):
        """Test that different models can have different structured output settings."""
        # OpenAI model with structured outputs enabled
        openai_model = LiteLLM(
            id="gpt-4o-mini",
            supports_native_structured_outputs=True,
        )
        
        # Anthropic model with structured outputs disabled (default)
        anthropic_model = LiteLLM(
            id="claude-sonnet-4-20250514",
        )
        
        # Gemini model with structured outputs enabled
        gemini_model = LiteLLM(
            id="gemini-2.5-flash",
            supports_native_structured_outputs=True,
        )

        assert openai_model.supports_native_structured_outputs is True
        assert anthropic_model.supports_native_structured_outputs is False
        assert gemini_model.supports_native_structured_outputs is True
