"""Unit tests for reasoning model checker functions."""

from agno.reasoning.anthropic import is_anthropic_reasoning_model
from agno.reasoning.azure_ai_foundry import is_ai_foundry_reasoning_model
from agno.reasoning.deepseek import is_deepseek_reasoning_model
from agno.reasoning.gemini import is_gemini_reasoning_model
from agno.reasoning.groq import is_groq_reasoning_model
from agno.reasoning.ollama import is_ollama_reasoning_model
from agno.reasoning.openai import is_openai_reasoning_model
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


def test_gemini_3_pro_model():
    """Test Gemini 3 Pro model returns True."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-3-pro",
    )
    assert is_gemini_reasoning_model(model) is True


def test_gemini_3_flash_model():
    """Test Gemini 3 Flash model returns True."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-3-flash",
    )
    assert is_gemini_reasoning_model(model) is True


def test_gemini_3_deepthink_model():
    """Test Gemini 3 DeepThink model returns True."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-3-pro-deepthink",
    )
    assert is_gemini_reasoning_model(model) is True


def test_gemini_3_0_version_model():
    """Test Gemini 3.0 version model returns True."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-3.0-flash",
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
# OpenAI Reasoning Model Tests
# ============================================================================


def test_openai_chat_with_o4_model():
    """Test OpenAIChat model with o4 in ID returns True."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="gpt-o4",
    )
    assert is_openai_reasoning_model(model) is True


def test_openai_chat_with_o3_model():
    """Test OpenAIChat model with o3 in ID returns True."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="gpt-o3-mini",
    )
    assert is_openai_reasoning_model(model) is True


def test_openai_chat_with_o1_model():
    """Test OpenAIChat model with o1 in ID returns True."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="o1-preview",
    )
    assert is_openai_reasoning_model(model) is True


def test_openai_chat_with_4_1_in_id():
    """Test OpenAIChat model with 4.1 in ID returns True."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="claude-opus-4.1",
    )
    assert is_openai_reasoning_model(model) is True


def test_openai_chat_with_4_5_in_id():
    """Test OpenAIChat model with 4.5 in ID returns True."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="claude-sonnet-4.5",
    )
    assert is_openai_reasoning_model(model) is True


def test_openai_chat_with_5_1_in_id():
    """Test OpenAIChat model with 5.1 in ID returns True (GPT-5.1)."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="gpt-5.1",
    )
    assert is_openai_reasoning_model(model) is True


def test_openai_chat_with_5_2_in_id():
    """Test OpenAIChat model with 5.2 in ID returns True."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="gpt-5.2-turbo",
    )
    assert is_openai_reasoning_model(model) is True


def test_openai_responses_with_reasoning_model():
    """Test OpenAIResponses model with o1 in ID returns True."""
    model = MockModel(
        class_name="OpenAIResponses",
        model_id="o1-mini",
    )
    assert is_openai_reasoning_model(model) is True


def test_azure_openai_with_reasoning_model():
    """Test AzureOpenAI model with o3 in ID returns True."""
    model = MockModel(
        class_name="AzureOpenAI",
        model_id="gpt-o3",
    )
    assert is_openai_reasoning_model(model) is True


def test_openai_like_with_deepseek_r1():
    """Test OpenAILike model with deepseek-r1 in ID returns True."""
    from agno.models.openai.like import OpenAILike

    # Create a proper OpenAILike instance
    model = OpenAILike(
        id="deepseek-r1",
        name="DeepSeek",
    )
    assert is_openai_reasoning_model(model) is True


def test_openai_chat_without_reasoning_id():
    """Test OpenAIChat model without reasoning model ID returns False."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="gpt-4-turbo",
    )
    assert is_openai_reasoning_model(model) is False


def test_openai_non_openai_model():
    """Test non-OpenAI model returns False."""
    model = MockModel(
        class_name="Claude",
        model_id="claude-3-5-sonnet",
    )
    assert is_openai_reasoning_model(model) is False


def test_openai_like_without_deepseek_r1():
    """Test OpenAILike model without deepseek-r1 returns False."""
    from agno.models.openai.like import OpenAILike

    # Create a proper OpenAILike instance
    model = OpenAILike(
        id="gpt-4-turbo",
        name="GPT-4",
    )
    assert is_openai_reasoning_model(model) is False


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
    """Test non-Claude model with VertexAI provider and thinking returns True (future-proof design)."""
    model = MockModel(
        class_name="Gemini",
        model_id="gemini-2.5-pro",
        provider="VertexAI",
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    # After future-proofing, any VertexAI model with thinking support returns True
    assert is_vertexai_reasoning_model(model) is True


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
# DeepSeek Reasoning Model Tests
# ============================================================================


def test_deepseek_with_reasoner_model():
    """Test DeepSeek model with deepseek-reasoner ID returns True."""
    model = MockModel(
        class_name="DeepSeek",
        model_id="deepseek-reasoner",
    )
    assert is_deepseek_reasoning_model(model) is True


def test_deepseek_with_r1_model():
    """Test DeepSeek model with deepseek-r1 ID returns True."""
    model = MockModel(
        class_name="DeepSeek",
        model_id="deepseek-r1",
    )
    assert is_deepseek_reasoning_model(model) is True


def test_deepseek_with_r1_distill_model():
    """Test DeepSeek model with deepseek-r1-distill variant returns True."""
    model = MockModel(
        class_name="DeepSeek",
        model_id="deepseek-r1-distill-qwen-32b",
    )
    assert is_deepseek_reasoning_model(model) is True


def test_deepseek_with_r1_distill_llama_model():
    """Test DeepSeek model with deepseek-r1-distill-llama variant returns True."""
    model = MockModel(
        class_name="DeepSeek",
        model_id="deepseek-r1-distill-llama-70b",
    )
    assert is_deepseek_reasoning_model(model) is True


def test_deepseek_with_chat_model():
    """Test DeepSeek model with deepseek-chat returns False (not a reasoning model)."""
    model = MockModel(
        class_name="DeepSeek",
        model_id="deepseek-chat",
    )
    assert is_deepseek_reasoning_model(model) is False


def test_deepseek_with_v3_model():
    """Test DeepSeek model with v3 (non-reasoning) returns False."""
    model = MockModel(
        class_name="DeepSeek",
        model_id="deepseek-v3",
    )
    assert is_deepseek_reasoning_model(model) is False


def test_deepseek_non_deepseek_model():
    """Test non-DeepSeek model returns False."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="deepseek-reasoner",
    )
    assert is_deepseek_reasoning_model(model) is False


# ============================================================================
# Groq Reasoning Model Tests
# ============================================================================


def test_groq_with_deepseek():
    """Test Groq model with deepseek in ID returns True."""
    model = MockModel(
        class_name="Groq",
        model_id="deepseek-r1-distill-llama-70b",
    )
    assert is_groq_reasoning_model(model) is True


def test_groq_without_deepseek():
    """Test Groq model without deepseek in ID returns False."""
    model = MockModel(
        class_name="Groq",
        model_id="llama-3.3-70b-versatile",
    )
    assert is_groq_reasoning_model(model) is False


def test_groq_non_groq_model():
    """Test non-Groq model returns False."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="deepseek-chat",
    )
    assert is_groq_reasoning_model(model) is False


# ============================================================================
# Ollama Reasoning Model Tests
# ============================================================================


def test_ollama_with_qwq():
    """Test Ollama model with qwq in ID returns True."""
    model = MockModel(
        class_name="Ollama",
        model_id="qwq:32b",
    )
    assert is_ollama_reasoning_model(model) is True


def test_ollama_with_deepseek_r1():
    """Test Ollama model with deepseek-r1 in ID returns True."""
    model = MockModel(
        class_name="Ollama",
        model_id="deepseek-r1:7b",
    )
    assert is_ollama_reasoning_model(model) is True


def test_ollama_with_qwen2_5_coder():
    """Test Ollama model with qwen2.5-coder in ID returns True."""
    model = MockModel(
        class_name="Ollama",
        model_id="qwen2.5-coder:32b",
    )
    assert is_ollama_reasoning_model(model) is True


def test_ollama_with_openthinker():
    """Test Ollama model with openthinker in ID returns True."""
    model = MockModel(
        class_name="Ollama",
        model_id="openthinker:7b",
    )
    assert is_ollama_reasoning_model(model) is True


def test_ollama_with_unsupported_model():
    """Test Ollama model with unsupported ID returns False."""
    model = MockModel(
        class_name="Ollama",
        model_id="llama3.2:3b",
    )
    assert is_ollama_reasoning_model(model) is False


def test_ollama_non_ollama_model():
    """Test non-Ollama model returns False."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="qwq-chat",
    )
    assert is_ollama_reasoning_model(model) is False


# ============================================================================
# Azure AI Foundry Reasoning Model Tests
# ============================================================================


def test_ai_foundry_with_deepseek():
    """Test AzureAIFoundry model with deepseek in ID returns True."""
    model = MockModel(
        class_name="AzureAIFoundry",
        model_id="deepseek-r1",
    )
    assert is_ai_foundry_reasoning_model(model) is True


def test_ai_foundry_with_o1():
    """Test AzureAIFoundry model with o1 in ID returns True."""
    model = MockModel(
        class_name="AzureAIFoundry",
        model_id="gpt-o1-preview",
    )
    assert is_ai_foundry_reasoning_model(model) is True


def test_ai_foundry_with_o3():
    """Test AzureAIFoundry model with o3 in ID returns True."""
    model = MockModel(
        class_name="AzureAIFoundry",
        model_id="gpt-o3-mini",
    )
    assert is_ai_foundry_reasoning_model(model) is True


def test_ai_foundry_with_o4():
    """Test AzureAIFoundry model with o4 in ID returns True."""
    model = MockModel(
        class_name="AzureAIFoundry",
        model_id="gpt-o4",
    )
    assert is_ai_foundry_reasoning_model(model) is True


def test_ai_foundry_with_unsupported_model():
    """Test AzureAIFoundry model with unsupported ID returns False."""
    model = MockModel(
        class_name="AzureAIFoundry",
        model_id="gpt-4-turbo",
    )
    assert is_ai_foundry_reasoning_model(model) is False


def test_ai_foundry_non_ai_foundry_model():
    """Test non-AzureAIFoundry model returns False."""
    model = MockModel(
        class_name="OpenAIChat",
        model_id="deepseek-r1",
    )
    assert is_ai_foundry_reasoning_model(model) is False


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
    assert is_openai_reasoning_model(model) is False
    assert is_anthropic_reasoning_model(model) is False
    assert is_vertexai_reasoning_model(model) is False
    assert is_deepseek_reasoning_model(model) is False
    assert is_groq_reasoning_model(model) is False
    assert is_ollama_reasoning_model(model) is False
    assert is_ai_foundry_reasoning_model(model) is False
