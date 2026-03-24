import pytest

from agno.agent import Agent
from agno.culture.manager import CultureManager
from agno.knowledge.chunking.agentic import AgenticChunking
from agno.memory.manager import MemoryManager
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.models.utils import get_model
from agno.team import Team


def test_get_model_with_string():
    """Test get_model() with a model string."""
    model = get_model("openai:gpt-4o")
    assert isinstance(model, OpenAIChat)
    assert model.id == "gpt-4o"


def test_get_model_with_model_instance():
    """Test get_model() with a Model instance returns it as-is."""
    original = OpenAIChat(id="gpt-4o")
    result = get_model(original)
    assert result is original


def test_get_model_with_none():
    """Test get_model() with None returns None."""
    result = get_model(None)
    assert result is None


def test_get_model_parses_openai_string():
    """Test get_model() parses OpenAI model string."""
    model = get_model("openai:gpt-4o")
    assert isinstance(model, OpenAIChat)
    assert model.id == "gpt-4o"


def test_get_model_parses_anthropic_string():
    """Test get_model() parses Anthropic model string."""
    model = get_model("anthropic:claude-3-5-sonnet-20241022")
    assert isinstance(model, Claude)
    assert model.id == "claude-3-5-sonnet-20241022"


def test_get_model_strips_whitespace():
    """Test that get_model() strips spaces from model string."""
    model = get_model(" openai : gpt-4o ")
    assert isinstance(model, OpenAIChat)
    assert model.id == "gpt-4o"


def test_get_model_invalid_format_no_colon():
    """Test get_model() with invalid format (no colon)."""
    with pytest.raises(ValueError, match="Invalid model string format"):
        get_model("openai-gpt-4o")


def test_get_model_invalid_format_empty_provider():
    """Test get_model() with empty provider."""
    with pytest.raises(ValueError, match="Invalid model string format"):
        get_model(":gpt-4o")


def test_get_model_invalid_format_empty_model_id():
    """Test get_model() with empty model ID."""
    with pytest.raises(ValueError, match="Invalid model string format"):
        get_model("openai:")


def test_get_model_unknown_provider():
    """Test get_model() with unknown provider."""
    with pytest.raises(ValueError, match="not supported"):
        get_model("unknown-provider:model-123")


def test_agent_with_model_string():
    """Test creating Agent with model string."""
    agent = Agent(model="openai:gpt-4o")
    assert isinstance(agent.model, OpenAIChat)
    assert agent.model.id == "gpt-4o"


def test_agent_with_all_model_params_as_strings():
    """Test Agent with all 4 model parameters as strings."""
    agent = Agent(
        model="openai:gpt-4o",
        reasoning=True,
        reasoning_model="anthropic:claude-3-5-sonnet-20241022",
        parser_model="google:gemini-2.0-flash-exp",
        output_model="groq:llama-3.1-70b-versatile",
    )
    assert isinstance(agent.model, OpenAIChat)
    assert isinstance(agent.reasoning_model, Claude)
    assert isinstance(agent.parser_model, Gemini)
    assert isinstance(agent.output_model, Groq)


def test_agent_backward_compatibility():
    """Test that Model class syntax still works."""
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    assert isinstance(agent.model, OpenAIChat)
    assert agent.model.id == "gpt-4o"


def test_team_with_model_string():
    """Test creating Team with model string."""
    agent = Agent(model="openai:gpt-4o")
    team = Team(members=[agent], model="anthropic:claude-3-5-sonnet-20241022")
    assert isinstance(team.model, Claude)


def test_team_with_all_model_params_as_strings():
    """Test Team with all 4 model parameters as strings."""
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


def test_memory_manager_with_model_string():
    """Test MemoryManager accepts model string."""
    manager = MemoryManager(model="openai:gpt-4o")
    assert isinstance(manager.model, OpenAIChat)


def test_memory_manager_with_model_instance():
    """Test MemoryManager accepts Model instance."""
    manager = MemoryManager(model=OpenAIChat(id="gpt-4o"))
    assert isinstance(manager.model, OpenAIChat)


def test_culture_manager_with_model_string():
    """Test CultureManager accepts model string."""
    manager = CultureManager(model="openai:gpt-4o")
    assert isinstance(manager.model, OpenAIChat)


def test_culture_manager_with_model_instance():
    """Test CultureManager accepts Model instance."""
    manager = CultureManager(model=OpenAIChat(id="gpt-4o"))
    assert isinstance(manager.model, OpenAIChat)


def test_agentic_chunking_with_model_string():
    """Test AgenticChunking accepts model string."""
    chunking = AgenticChunking(model="openai:gpt-4o")
    assert isinstance(chunking.model, OpenAIChat)


def test_agentic_chunking_with_model_instance():
    """Test AgenticChunking accepts Model instance."""
    chunking = AgenticChunking(model=OpenAIChat(id="gpt-4o"))
    assert isinstance(chunking.model, OpenAIChat)


# ---------------------------------------------------------------------------
# normalize_provider tests (issue #7093)
# ---------------------------------------------------------------------------

def test_normalize_provider_openai():
    """OpenAI runtime provider string resolves to canonical 'openai'."""
    from agno.utils.model import normalize_provider

    assert normalize_provider("OpenAI") == "openai"


def test_normalize_provider_azure():
    """Azure runtime provider string resolves to canonical 'azure-openai'."""
    from agno.utils.model import normalize_provider

    assert normalize_provider("Azure") == "azure-openai"
    assert normalize_provider("azure") == "azure-openai"
    assert normalize_provider("AzureOpenAI") == "azure-openai"
    assert normalize_provider("azure-openai") == "azure-openai"


def test_normalize_provider_lmstudio():
    """LMStudio runtime provider string resolves to canonical 'lmstudio'."""
    from agno.utils.model import normalize_provider

    assert normalize_provider("LMStudio") == "lmstudio"
    assert normalize_provider("lmstudio") == "lmstudio"


def test_normalize_provider_siliconflow():
    """Siliconflow runtime provider string resolves to canonical 'siliconflow'."""
    from agno.utils.model import normalize_provider

    assert normalize_provider("Siliconflow") == "siliconflow"
    assert normalize_provider("SILICONFLOW") == "siliconflow"


def test_normalize_provider_aws_bedrock():
    """AwsBedrock runtime provider string resolves to canonical 'aws-bedrock'."""
    from agno.utils.model import normalize_provider

    assert normalize_provider("AwsBedrock") == "aws-bedrock"
    assert normalize_provider("aws-bedrock") == "aws-bedrock"
    assert normalize_provider("awsbedrock") == "aws-bedrock"


def test_normalize_provider_unknown_passthrough():
    """Unknown provider strings are returned lowercased (no silent drop)."""
    from agno.utils.model import normalize_provider

    assert normalize_provider("UnknownProvider") == "unknownprovider"


def test_get_model_azure_runtime_provider():
    """get_model() should parse 'Azure:gpt-4' into AzureOpenAI (issue #7093)."""
    from agno.models.azure import AzureOpenAI
    from agno.models.utils import get_model

    model = get_model("Azure:gpt-4")
    assert isinstance(model, AzureOpenAI)
    assert model.id == "gpt-4"


def test_get_model_provider_case_insensitive():
    """Provider string lookup is case-insensitive."""
    from agno.models.openai import OpenAIChat
    from agno.models.utils import get_model

    model = get_model("OpenAI:gpt-4o")
    assert isinstance(model, OpenAIChat)
    assert model.id == "gpt-4o"
