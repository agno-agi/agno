"""Unit tests for reasoning model checker functions."""

import pytest

from agno.reasoning.anthropic import is_anthropic_reasoning_model
from agno.reasoning.gemini import is_gemini_reasoning_model
from agno.reasoning.vertexai import is_vertexai_reasoning_model


# Mock model classes for testing
class MockModel:
    """Base mock model for testing."""

    def __init__(self, class_name: str, model_id: str = "", **kwargs):
        self.__class__.__name__ = class_name
        self.id = model_id
        for key, value in kwargs.items():
            setattr(self, key, value)


# ============================================================================
# Gemini Reasoning Model Tests
# ============================================================================


def test_gemini_reasoning_model_with_thinking_budget():
    """Test Gemini model with thinking_budget parameter returns True."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-2.5-flash-preview",
        thinking_budget=1000,
    )
    assert is_gemini_reasoning_model(model) is True


def test_gemini_reasoning_model_with_include_thoughts():
    """Test Gemini model with include_thoughts parameter returns True."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-2.5-pro",
        include_thoughts=True,
    )
    assert is_gemini_reasoning_model(model) is True


def test_gemini_reasoning_model_with_version_only():
    """Test Gemini 2.5 model without explicit params but has '2.5' in ID returns True."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-2.5-flash",
    )
    assert is_gemini_reasoning_model(model) is True


def test_gemini_reasoning_model_with_both_params():
    """Test Gemini model with both thinking_budget and include_thoughts returns True."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-2.5-pro",
        thinking_budget=2000,
        include_thoughts=True,
    )
    assert is_gemini_reasoning_model(model) is True


def test_gemini_non_reasoning_model():
    """Test Gemini 1.5 model without thinking support returns False."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-1.5-flash",
    )
    assert is_gemini_reasoning_model(model) is False


def test_gemini_non_gemini_model():
    """Test non-Gemini model returns False."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet",
    )
    assert is_gemini_reasoning_model(model) is False


def test_gemini_model_with_none_params():
    """Test Gemini model with None params and no 2.5 in ID returns False."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-1.5-pro",
        thinking_budget=None,
        include_thoughts=None,
    )
    assert is_gemini_reasoning_model(model) is False


# ============================================================================
# Anthropic Reasoning Model Tests
# ============================================================================


def test_anthropic_reasoning_model_with_thinking():
    """Test Anthropic Claude model with thinking and provider returns True."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet",
        provider="Anthropic",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_anthropic_reasoning_model(model) is True


def test_anthropic_without_provider():
    """Test Claude model with thinking but no provider attribute returns False."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_anthropic_reasoning_model(model) is False


def test_anthropic_vertexai_provider():
    """Test Claude model with VertexAI provider returns False (should use VertexAI checker)."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet",
        provider="VertexAI",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_anthropic_reasoning_model(model) is False


def test_anthropic_without_thinking():
    """Test Anthropic Claude model without thinking parameter returns False."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet",
        provider="Anthropic",
    )
    assert is_anthropic_reasoning_model(model) is False


def test_anthropic_with_none_thinking():
    """Test Anthropic Claude model with None thinking parameter returns False."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet",
        provider="Anthropic",
        thinking=None,
    )
    assert is_anthropic_reasoning_model(model) is False


def test_anthropic_non_claude_model():
    """Test non-Claude model with Anthropic provider returns False."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-2.5-pro",
        provider="Anthropic",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_anthropic_reasoning_model(model) is False


def test_anthropic_wrong_provider():
    """Test Claude model with different provider returns False."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet",
        provider="OpenAI",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_anthropic_reasoning_model(model) is False


# ============================================================================
# VertexAI Reasoning Model Tests
# ============================================================================


def test_vertexai_reasoning_model_with_thinking():
    """Test VertexAI Claude model with thinking and provider returns True."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet@20240620",
        provider="VertexAI",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_vertexai_reasoning_model(model) is True


def test_vertexai_without_provider():
    """Test Claude model with thinking but no provider attribute returns False."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet@20240620",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_vertexai_reasoning_model(model) is False


def test_vertexai_anthropic_provider():
    """Test Claude model with Anthropic provider returns False (should use Anthropic checker)."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet",
        provider="Anthropic",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_vertexai_reasoning_model(model) is False


def test_vertexai_without_thinking():
    """Test VertexAI Claude model without thinking parameter returns False."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet@20240620",
        provider="VertexAI",
    )
    assert is_vertexai_reasoning_model(model) is False


def test_vertexai_with_none_thinking():
    """Test VertexAI Claude model with None thinking parameter returns False."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet@20240620",
        provider="VertexAI",
        thinking=None,
    )
    assert is_vertexai_reasoning_model(model) is False


def test_vertexai_non_claude_model():
    """Test non-Claude model with VertexAI provider returns False."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-2.5-pro",
        provider="VertexAI",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_vertexai_reasoning_model(model) is False


def test_vertexai_wrong_provider():
    """Test Claude model with different provider returns False."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet@20240620",
        provider="AWS",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_vertexai_reasoning_model(model) is False


# ============================================================================
# Cross-checker validation tests
# ============================================================================


def test_anthropic_and_vertexai_mutual_exclusivity():
    """Test that a model cannot be both Anthropic and VertexAI reasoning model."""
    # Anthropic Claude
    anthropic_model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet",
        provider="Anthropic",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_anthropic_reasoning_model(anthropic_model) is True
    assert is_vertexai_reasoning_model(anthropic_model) is False

    # VertexAI Claude
    vertexai_model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet@20240620",
        provider="VertexAI",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    assert is_vertexai_reasoning_model(vertexai_model) is True
    assert is_anthropic_reasoning_model(vertexai_model) is False


def test_all_checkers_return_false_for_non_reasoning_model():
    """Test that all checkers return False for a non-reasoning model."""
    model = MockModel(
        class_name="GPT4",
        model_id="gpt-4-turbo",
    )
    assert is_gemini_reasoning_model(model) is False
    assert is_anthropic_reasoning_model(model) is False
    assert is_vertexai_reasoning_model(model) is False
