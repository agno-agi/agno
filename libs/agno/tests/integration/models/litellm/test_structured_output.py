"""
Tests for LiteLLM structured output support.

This test verifies that the LiteLLM model properly passes response_format
to the underlying LiteLLM library for structured outputs.
"""

from typing import List
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.litellm import LiteLLM


class MovieScript(BaseModel):
    """A movie script structure for testing."""

    setting: str = Field(..., description="The movie's setting")
    genre: str = Field(..., description="The movie's genre")
    name: str = Field(..., description="The movie's name")
    characters: List[str] = Field(..., description="List of character names")
    storyline: str = Field(..., description="Brief storyline")


class SimpleOutput(BaseModel):
    """Simple output structure for testing."""

    answer: str = Field(..., description="The answer")
    confidence: float = Field(..., description="Confidence score between 0 and 1")


class TestLiteLLMStructuredOutputSupport:
    """Test that LiteLLM model supports structured outputs when enabled."""

    def test_supports_native_structured_outputs_default_false(self):
        """Test that supports_native_structured_outputs is False by default.

        This is intentional because LiteLLM supports many providers,
        and not all support structured outputs (e.g., Anthropic, Ollama).
        """
        model = LiteLLM(id="gpt-4o")
        assert model.supports_native_structured_outputs is False

    def test_supports_json_schema_outputs_default_false(self):
        """Test that supports_json_schema_outputs is False by default."""
        model = LiteLLM(id="gpt-4o")
        assert model.supports_json_schema_outputs is False

    def test_can_enable_structured_output_support(self):
        """Test that structured output support can be explicitly enabled."""
        model = LiteLLM(
            id="gpt-4o",
            supports_native_structured_outputs=True,
            supports_json_schema_outputs=True,
        )
        assert model.supports_native_structured_outputs is True
        assert model.supports_json_schema_outputs is True


class TestLiteLLMResponseFormatConversion:
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


class TestAdditionalPropertiesFalse:
    """Test the _add_additional_properties_false helper method."""

    def test_simple_object_schema(self):
        """Test that simple object schemas get additionalProperties: false."""
        model = LiteLLM(id="gpt-4o")
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name", "age"],
        }

        result = model._add_additional_properties_false(schema)

        assert result["additionalProperties"] is False

    def test_nested_object_schema(self):
        """Test that nested object schemas also get additionalProperties: false."""
        model = LiteLLM(id="gpt-4o")
        schema = {
            "type": "object",
            "properties": {
                "user": {"type": "object", "properties": {"name": {"type": "string"}}}
            },
        }

        result = model._add_additional_properties_false(schema)

        assert result["additionalProperties"] is False
        assert result["properties"]["user"]["additionalProperties"] is False

    def test_array_with_object_items(self):
        """Test that array item schemas get additionalProperties: false."""
        model = LiteLLM(id="gpt-4o")
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                    },
                }
            },
        }

        result = model._add_additional_properties_false(schema)

        assert result["additionalProperties"] is False
        assert result["properties"]["items"]["items"]["additionalProperties"] is False

    def test_schema_with_defs(self):
        """Test that $defs schemas get additionalProperties: false."""
        model = LiteLLM(id="gpt-4o")
        schema = {
            "type": "object",
            "properties": {"ref": {"$ref": "#/$defs/SubModel"}},
            "$defs": {
                "SubModel": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                }
            },
        }

        result = model._add_additional_properties_false(schema)

        assert result["additionalProperties"] is False
        assert result["$defs"]["SubModel"]["additionalProperties"] is False


class TestLiteLLMInvokeWithResponseFormat:
    """Test that invoke methods properly pass response_format to LiteLLM."""

    @patch("agno.models.litellm.chat.litellm")
    def test_invoke_passes_response_format_when_supported(self, mock_litellm):
        """Test that invoke passes response_format when supports_native_structured_outputs=True."""
        # Setup mock
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            '{"answer": "Paris", "confidence": 0.95}'
        )
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
    def test_invoke_does_not_pass_response_format_when_not_supported(
        self, mock_litellm
    ):
        """Test that invoke does NOT pass response_format when supports_native_structured_outputs=False.

        This is critical for providers like Anthropic that don't support response_format.
        """
        # Setup mock
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            '{"answer": "Paris", "confidence": 0.95}'
        )
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
        assert (
            "response_format" not in call_kwargs
            or call_kwargs.get("response_format") is None
        )


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
            id="gpt-4o",
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
