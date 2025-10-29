import pytest

from agno.agent import Agent
from agno.culture.manager import CultureManager
from agno.knowledge.chunking.agentic import AgenticChunking
from agno.memory.manager import MemoryManager
from agno.models.anthropic import Claude
from agno.models.azure import AzureOpenAI
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.models.utils import get_model, get_model_from_string, resolve_model
from agno.team import Team


def test_openai_provider():
    """Test OpenAI provider."""
    model = get_model("gpt-4o", "openai")
    assert isinstance(model, OpenAIChat)
    assert model.id == "gpt-4o"


def test_anthropic_provider():
    """Test Anthropic provider."""
    model = get_model("claude-3-5-sonnet-20241022", "anthropic")
    assert isinstance(model, Claude)
    assert model.id == "claude-3-5-sonnet-20241022"


def test_google_provider():
    """Test Google/Gemini provider."""
    model = get_model("gemini-2.0-flash-exp", "google")
    assert isinstance(model, Gemini)
    assert model.id == "gemini-2.0-flash-exp"


def test_gemini_provider_alias():
    """Test Gemini as provider alias for Google."""
    model = get_model("gemini-2.0-flash-exp", "gemini")
    assert isinstance(model, Gemini)
    assert model.id == "gemini-2.0-flash-exp"


def test_groq_provider():
    """Test Groq provider."""
    model = get_model("llama-3.1-70b-versatile", "groq")
    assert isinstance(model, Groq)
    assert model.id == "llama-3.1-70b-versatile"


def test_case_insensitive_provider():
    """Test that provider names are case-insensitive."""
    model1 = get_model("gpt-4o", "OpenAI")
    model2 = get_model("gpt-4o", "OPENAI")
    model3 = get_model("gpt-4o", "openai")
    assert all(isinstance(m, OpenAIChat) for m in [model1, model2, model3])


def test_unknown_provider():
    """Test that unknown provider raises ValueError."""
    with pytest.raises(ValueError, match="not supported"):
        get_model("some-model", "unknown-provider")


def test_azure_provider_aliases():
    """Test that both 'azure' and 'azure-openai' work."""
    model1 = get_model("gpt-4o", "azure")
    model2 = get_model("gpt-4o", "azure-openai")
    assert isinstance(model1, AzureOpenAI)
    assert isinstance(model2, AzureOpenAI)


def test_valid_format_openai():
    """Test valid format for OpenAI."""
    model = get_model_from_string("openai:gpt-4o")
    assert isinstance(model, OpenAIChat)
    assert model.id == "gpt-4o"


def test_valid_format_anthropic():
    """Test valid format for Anthropic."""
    model = get_model_from_string("anthropic:claude-3-5-sonnet-20241022")
    assert isinstance(model, Claude)
    assert model.id == "claude-3-5-sonnet-20241022"


def test_valid_format_with_spaces():
    """Test that spaces around provider and model ID are stripped."""
    model = get_model_from_string(" openai : gpt-4o ")
    assert isinstance(model, OpenAIChat)
    assert model.id == "gpt-4o"


def test_invalid_format_no_colon():
    """Test that missing colon raises ValueError."""
    with pytest.raises(ValueError, match="Invalid model string format"):
        get_model_from_string("openai-gpt-4o")


def test_invalid_format_multiple_colons():
    """Test that multiple colons are handled (only first split)."""
    model = get_model_from_string("openai:gpt-4o:extra")
    assert isinstance(model, OpenAIChat)
    assert model.id == "gpt-4o:extra"


def test_invalid_format_empty_provider():
    """Test that empty provider raises ValueError."""
    with pytest.raises(ValueError, match="must be non-empty"):
        get_model_from_string(":gpt-4o")


def test_invalid_format_empty_model_id():
    """Test that empty model ID raises ValueError."""
    with pytest.raises(ValueError, match="must be non-empty"):
        get_model_from_string("openai:")


def test_invalid_format_empty_string():
    """Test that empty string raises ValueError."""
    with pytest.raises(ValueError, match="must be a non-empty string"):
        get_model_from_string("")


def test_invalid_format_none():
    """Test that None raises ValueError."""
    with pytest.raises(ValueError, match="must be a non-empty string"):
        get_model_from_string(None)  # type: ignore


def test_unknown_provider_in_string():
    """Test that unknown provider in string raises ValueError."""
    with pytest.raises(ValueError, match="not supported"):
        get_model_from_string("unknown:model-123")


def test_resolve_model_with_instance():
    """Test that Model instance is returned as-is."""
    original = OpenAIChat(id="gpt-4o")
    resolved = resolve_model(original)
    assert resolved is original


def test_resolve_model_with_string():
    """Test that string is converted to Model."""
    resolved = resolve_model("openai:gpt-4o")
    assert isinstance(resolved, OpenAIChat)
    assert resolved.id == "gpt-4o"


def test_resolve_model_with_none():
    """Test that None returns None."""
    resolved = resolve_model(None)
    assert resolved is None


def test_resolve_model_with_invalid_type():
    """Test that invalid type raises TypeError."""
    with pytest.raises(TypeError, match="Model must be"):
        resolve_model(123)  # type: ignore

    with pytest.raises(TypeError, match="Model must be"):
        resolve_model({"provider": "openai", "id": "gpt-4o"})  # type: ignore


def test_agent_with_model_string():
    """Test creating Agent with model string."""
    agent = Agent(model="openai:gpt-4o")
    assert isinstance(agent.model, OpenAIChat)
    assert agent.model.id == "gpt-4o"


def test_agent_with_reasoning_model_string():
    """Test creating Agent with reasoning_model string."""
    agent = Agent(
        model="openai:gpt-4o",
        reasoning=True,
        reasoning_model="anthropic:claude-3-5-sonnet-20241022",
    )
    assert isinstance(agent.model, OpenAIChat)
    assert isinstance(agent.reasoning_model, Claude)


def test_agent_with_parser_model_string():
    """Test creating Agent with parser_model string."""
    agent = Agent(model="openai:gpt-4o", parser_model="openai:gpt-4o-mini")
    assert isinstance(agent.model, OpenAIChat)
    assert isinstance(agent.parser_model, OpenAIChat)
    assert agent.parser_model.id == "gpt-4o-mini"


def test_agent_with_output_model_string():
    """Test creating Agent with output_model string."""
    agent = Agent(model="openai:gpt-4o", output_model="anthropic:claude-3-5-sonnet-20241022")
    assert isinstance(agent.model, OpenAIChat)
    assert isinstance(agent.output_model, Claude)


def test_agent_with_all_model_strings():
    """Test creating Agent with all model parameters as strings."""
    agent = Agent(
        model="openai:gpt-4o",
        reasoning=True,
        reasoning_model="anthropic:claude-3-5-sonnet-20241022",
        parser_model="openai:gpt-4o-mini",
        output_model="google:gemini-2.0-flash-exp",
    )
    assert isinstance(agent.model, OpenAIChat)
    assert isinstance(agent.reasoning_model, Claude)
    assert isinstance(agent.parser_model, OpenAIChat)
    assert isinstance(agent.output_model, Gemini)


def test_agent_backward_compatibility():
    """Test that old Model class syntax still works."""
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    assert isinstance(agent.model, OpenAIChat)
    assert agent.model.id == "gpt-4o"


def test_agent_with_none_models():
    """Test that None values work correctly."""
    agent = Agent(model=None, reasoning_model=None)
    assert agent.model is None
    assert agent.reasoning_model is None


def test_team_with_model_string():
    """Test creating Team with model string."""
    agent1 = Agent(model="openai:gpt-4o", name="Agent 1")
    agent2 = Agent(model="anthropic:claude-3-5-sonnet-20241022", name="Agent 2")
    team = Team(members=[agent1, agent2], model="openai:gpt-4o")
    assert isinstance(team.model, OpenAIChat)
    assert team.model.id == "gpt-4o"


def test_team_with_all_model_strings():
    """Test creating Team with all model parameters as strings."""
    agent = Agent(model="openai:gpt-4o")
    team = Team(
        members=[agent],
        model="anthropic:claude-3-5-sonnet-20241022",
        reasoning=True,
        reasoning_model="openai:gpt-4o",
        parser_model="google:gemini-2.0-flash-exp",
        output_model="groq:llama-3.1-70b-versatile",
    )
    assert isinstance(team.model, Claude)
    assert isinstance(team.reasoning_model, OpenAIChat)
    assert isinstance(team.parser_model, Gemini)
    assert isinstance(team.output_model, Groq)


def test_team_backward_compatibility():
    """Test that old Model class syntax still works for Team."""
    agent = Agent(model="openai:gpt-4o")
    team = Team(members=[agent], model=OpenAIChat(id="gpt-4o"))
    assert isinstance(team.model, OpenAIChat)
    assert team.model.id == "gpt-4o"


def test_memory_manager_with_model_string():
    """Test that MemoryManager accepts model string (used to reject)."""
    manager = MemoryManager(model="openai:gpt-4o")
    assert isinstance(manager.model, OpenAIChat)
    assert manager.model.id == "gpt-4o"


def test_memory_manager_with_model_instance():
    """Test that MemoryManager still accepts Model instance."""
    manager = MemoryManager(model=OpenAIChat(id="gpt-4o"))
    assert isinstance(manager.model, OpenAIChat)
    assert manager.model.id == "gpt-4o"


def test_memory_manager_with_none():
    """Test that MemoryManager accepts None."""
    manager = MemoryManager(model=None)
    assert manager.model is None


# Tests for CultureManager with model strings (regression test for bug)


def test_culture_manager_with_model_string():
    """Test that CultureManager accepts model string (used to reject)."""
    manager = CultureManager(model="openai:gpt-4o")
    assert isinstance(manager.model, OpenAIChat)
    assert manager.model.id == "gpt-4o"


def test_culture_manager_with_model_instance():
    """Test that CultureManager still accepts Model instance."""
    manager = CultureManager(model=OpenAIChat(id="gpt-4o"))
    assert isinstance(manager.model, OpenAIChat)
    assert manager.model.id == "gpt-4o"


def test_culture_manager_with_none():
    """Test that CultureManager accepts None."""
    manager = CultureManager(model=None)
    assert manager.model is None


def test_agentic_chunking_with_model_string():
    """Test that AgenticChunking accepts model string."""
    chunking = AgenticChunking(model="openai:gpt-4o")
    assert isinstance(chunking.model, OpenAIChat)
    assert chunking.model.id == "gpt-4o"


def test_agentic_chunking_with_model_instance():
    """Test that AgenticChunking still accepts Model instance."""
    chunking = AgenticChunking(model=OpenAIChat(id="gpt-4o"))
    assert isinstance(chunking.model, OpenAIChat)
    assert chunking.model.id == "gpt-4o"


def test_agentic_chunking_with_none_uses_default():
    """Test that AgenticChunking with None uses default OpenAI model."""
    chunking = AgenticChunking(model=None)
    assert isinstance(chunking.model, OpenAIChat)
    # Should use default model
