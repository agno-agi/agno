import pytest

from agno.agent import Agent
from agno.culture.manager import CultureManager
from agno.knowledge.chunking.agentic import AgenticChunking
from agno.memory.manager import MemoryManager
from agno.models.anthropic import Claude
from agno.models.cloudflare import Cloudflare
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.minimax import MiniMax
from agno.models.n1n import N1N
from agno.models.openai import OpenAIChat, OpenAIResponses
from agno.models.utils import get_model
from agno.team import Team


def test_get_model_with_string():
    """Test get_model() with a model string."""
    model = get_model("openai:gpt-4o")
    assert isinstance(model, OpenAIResponses)
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
    assert isinstance(model, OpenAIResponses)
    assert model.id == "gpt-4o"


def test_get_model_parses_anthropic_string():
    """Test get_model() parses Anthropic model string."""
    model = get_model("anthropic:claude-3-5-sonnet-20241022")
    assert isinstance(model, Claude)
    assert model.id == "claude-3-5-sonnet-20241022"


def test_get_model_parses_cloudflare_string():
    """Test get_model() parses Cloudflare AI Gateway model string (Workers AI id after first colon)."""
    model = get_model("cloudflare:workers-ai/@cf/meta/llama-3.3-70b-instruct-fp8-fast")
    assert isinstance(model, Cloudflare)
    assert model.id == "workers-ai/@cf/meta/llama-3.3-70b-instruct-fp8-fast"


def test_get_model_parses_cloudflare_workers_ai_catalog_binding():
    """Workers AI catalog ids (@cf/...) are normalized to workers-ai/@cf/... for the gateway."""
    model = get_model("cloudflare:@cf/google/gemma-4-26b-a4b-it")
    assert isinstance(model, Cloudflare)
    assert model.id == "workers-ai/@cf/google/gemma-4-26b-a4b-it"


def test_get_model_parses_minimax_string():
    """Test get_model() parses MiniMax model string."""
    model = get_model("minimax:MiniMax-M2.7")
    assert isinstance(model, MiniMax)
    assert model.id == "MiniMax-M2.7"


def test_get_model_parses_n1n_string():
    """Test get_model() parses N1N model string."""
    model = get_model("n1n:gpt-4o")
    assert isinstance(model, N1N)
    assert model.id == "gpt-4o"


def test_get_model_strips_whitespace():
    """Test that get_model() strips spaces from model string."""
    model = get_model(" openai : gpt-4o ")
    assert isinstance(model, OpenAIResponses)
    assert model.id == "gpt-4o"


def test_get_model_invalid_format_no_colon():
    """Test get_model() with invalid format (no colon and no recognised prefix)."""
    # ``openai-gpt-4o`` starts with ``openai-``, not ``gpt-``/``claude-``/etc.,
    # so sniffing should fail and the error surface.
    with pytest.raises(ValueError, match="Invalid model string format"):
        get_model("openai-gpt-4o")


def test_get_model_sniffs_openai_gpt_prefix():
    """Bare ``gpt-*`` resolves to OpenAI without an explicit provider prefix."""
    model = get_model("gpt-4o")
    assert isinstance(model, OpenAIChat)
    assert model.id == "gpt-4o"


def test_get_model_sniffs_anthropic_claude_prefix():
    """Bare ``claude-*`` resolves to the Anthropic direct client."""
    model = get_model("claude-3-5-sonnet-20241022")
    assert isinstance(model, Claude)
    assert model.id == "claude-3-5-sonnet-20241022"


def test_get_model_sniffs_google_gemini_prefix():
    """Bare ``gemini-*`` resolves to Google Gemini."""
    model = get_model("gemini-2.0-flash-exp")
    assert isinstance(model, Gemini)
    assert model.id == "gemini-2.0-flash-exp"


def test_get_model_sniffs_openai_reasoning_prefix():
    """Bare ``o1-*`` / ``o3-*`` / ``o4-*`` resolves to OpenAI."""
    for model_id in ("o1-mini", "o3-mini", "o4-mini"):
        model = get_model(model_id)
        assert isinstance(model, OpenAIChat), f"{model_id} did not sniff to OpenAI"
        assert model.id == model_id


def test_get_model_sniffs_openai_reasoning_exact():
    """Exact ``o1`` / ``o3`` / ``o4`` (no dash) resolves to OpenAI."""
    for model_id in ("o1", "o3", "o4"):
        model = get_model(model_id)
        assert isinstance(model, OpenAIChat), f"{model_id} did not sniff to OpenAI"
        assert model.id == model_id


def test_get_model_sniff_does_not_override_explicit_prefix():
    """Explicit ``<provider>:<id>`` takes precedence — sniffing only fires for bare IDs."""
    # ``anthropic:claude-...`` still parses via the explicit path, not the sniffer.
    model = get_model("anthropic:claude-3-5-sonnet-20241022")
    assert isinstance(model, Claude)


def test_get_model_sniff_unknown_prefix_still_raises():
    """A bare ID with no recognised prefix still raises the format error."""
    with pytest.raises(ValueError, match="Invalid model string format"):
        get_model("some-unknown-model-42")


def test_get_model_sniff_error_message_lists_supported_prefixes():
    """Error message mentions the recognised prefix families so users can self-correct."""
    with pytest.raises(ValueError, match=r"gpt-\*"):
        get_model("some-unknown-model-42")


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
    assert isinstance(agent.model, OpenAIResponses)
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
    assert isinstance(agent.model, OpenAIResponses)
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
    assert isinstance(team.reasoning_model, OpenAIResponses)
    assert isinstance(team.parser_model, Gemini)
    assert isinstance(team.output_model, Groq)


def test_memory_manager_with_model_string():
    """Test MemoryManager accepts model string."""
    manager = MemoryManager(model="openai:gpt-4o")
    assert isinstance(manager.model, OpenAIResponses)


def test_memory_manager_with_model_instance():
    """Test MemoryManager accepts Model instance."""
    manager = MemoryManager(model=OpenAIChat(id="gpt-4o"))
    assert isinstance(manager.model, OpenAIChat)


def test_culture_manager_with_model_string():
    """Test CultureManager accepts model string."""
    manager = CultureManager(model="openai:gpt-4o")
    assert isinstance(manager.model, OpenAIResponses)


def test_culture_manager_with_model_instance():
    """Test CultureManager accepts Model instance."""
    manager = CultureManager(model=OpenAIChat(id="gpt-4o"))
    assert isinstance(manager.model, OpenAIChat)


def test_agentic_chunking_with_model_string():
    """Test AgenticChunking accepts model string."""
    chunking = AgenticChunking(model="openai:gpt-4o")
    assert isinstance(chunking.model, OpenAIResponses)


def test_agentic_chunking_with_model_instance():
    """Test AgenticChunking accepts Model instance."""
    chunking = AgenticChunking(model=OpenAIChat(id="gpt-4o"))
    assert isinstance(chunking.model, OpenAIChat)
