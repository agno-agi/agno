import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.utils import get_model_from_string
from agno.team import Team


class TestModelStringCore:
    """Test core model string functionality."""

    def test_create_model_with_string(self):
        """Test creating models from strings."""
        # Test successful creation
        model = get_model_from_string("openai:gpt-4o-mini")
        assert model.id == "gpt-4o-mini"
        assert "gpt-4o-mini" in model.model_string

    def test_create_model_with_model_object(self):
        """Test that passing Model objects works unchanged."""
        from agno.models.openai import OpenAIChat

        original = OpenAIChat(id="gpt-4o")
        result = get_model_from_string(original)

        assert result is original  # Should return the same object
        assert result.id == "gpt-4o"
        assert "gpt-4o" in result.model_string

    def test_invalid_format_raises_error(self):
        """Test that invalid format strings raise appropriate errors."""
        with pytest.raises(ValueError, match="Model string must be 'provider:model_id'"):
            get_model_from_string("invalid-format")

        with pytest.raises(ValueError, match="Both provider and model_id must be non-empty"):
            get_model_from_string(":")

        with pytest.raises(ValueError, match="Both provider and model_id must be non-empty"):
            get_model_from_string("provider:")

        with pytest.raises(ValueError, match="Both provider and model_id must be non-empty"):
            get_model_from_string(":model")

    def test_unsupported_provider_raises_error(self):
        """Test that unsupported providers raise appropriate errors."""
        with pytest.raises(ValueError, match="Provider 'unknown' not supported"):
            get_model_from_string("unknown:model-id")

    def test_invalid_type_raises_error(self):
        """Test that invalid types raise appropriate errors."""
        with pytest.raises(TypeError, match="Model must be Model instance or string"):
            get_model_from_string(123)  # type: ignore

        with pytest.raises(TypeError, match="Model must be Model instance or string"):
            get_model_from_string(None)  # type: ignore


class TestModelStringProviders:
    """Test model string functionality for all supported providers."""

    @pytest.mark.parametrize(
        "provider,model_class_name",
        [
            ("openai", "OpenAIChat"),
            ("openai-responses", "OpenAIResponses"),
            ("anthropic", "Claude"),
            ("google", "Gemini"),
            ("groq", "Groq"),
            ("ollama", "Ollama"),
            ("aws", "AwsBedrock"),
            ("aws-claude", "Claude"),
            ("azure-openai", "AzureOpenAI"),
            ("azure-ai-foundry", "AzureAIFoundry"),
            ("mistral", "MistralChat"),
            ("cohere", "Cohere"),
            ("together", "Together"),
            ("fireworks", "Fireworks"),
            ("perplexity", "Perplexity"),
            ("openrouter", "OpenRouter"),
            ("meta", "Llama"),
            ("llamaopenai", "LlamaOpenAI"),
            ("cerebras", "Cerebras"),
            ("cerebras-openai", "CerebrasOpenAI"),
            ("cometapi", "CometAPI"),
            ("xai", "xAI"),
            ("deepseek", "DeepSeek"),
            ("nvidia", "Nvidia"),
            ("sambanova", "Sambanova"),
            ("deepinfra", "DeepInfra"),
            ("nebius", "Nebius"),
            ("nexus", "Nexus"),
            ("internlm", "InternLM"),
            ("dashscope", "DashScope"),
            ("huggingface", "HuggingFace"),
            ("ibm", "WatsonX"),
            ("litellm", "LiteLLM"),
            ("litellm-openai", "LiteLLMOpenAI"),
            ("llama-cpp", "LlamaCpp"),
            ("lmstudio", "LMStudio"),
            ("portkey", "Portkey"),
            ("requesty", "Requesty"),
            ("siliconflow", "Siliconflow"),
            ("vllm", "VLLM"),
            ("vercel", "V0"),
            ("vertexai", "Claude"),
            ("langdb", "LangDB"),
            ("aimlapi", "AIMLAPI"),
        ],
    )
    def test_all_providers_supported(self, provider, model_class_name):
        """Test that all providers can create models from strings."""
        model_string = f"{provider}:test-model-id"

        try:
            model = get_model_from_string(model_string)
            assert model.id == "test-model-id"
            assert model.__class__.__name__ == model_class_name

            # Test model_string property exists and contains the model_id
            assert hasattr(model, "model_string")
            assert ":" in model.model_string
            assert "test-model-id" in model.model_string

        except ImportError:
            pytest.skip(f"Dependencies for {provider} not installed")


class TestAgentModelStrings:
    """Test model strings work with Agents."""

    def test_agent_with_string_model(self):
        """Test Agent creation with string model."""
        try:
            # Test main model
            agent = Agent(model="openai:gpt-4o-mini", telemetry=False)
            agent.initialize_agent()  # Explicitly initialize to resolve model strings
            assert agent.model is not None
            assert agent.model.id == "gpt-4o-mini"
            assert "gpt-4o-mini" in agent.model.model_string

            # Test reasoning model
            agent_reasoning = Agent(
                model="openai:gpt-4o-mini", reasoning_model="anthropic:claude-3-5-sonnet", telemetry=False
            )
            agent_reasoning.initialize_agent()  # Explicitly initialize to resolve model strings
            assert agent_reasoning.reasoning_model is not None
            assert "claude-3-5-sonnet" in agent_reasoning.reasoning_model.model_string

        except ImportError:
            pytest.skip("Model dependencies not installed")

    def test_agent_backward_compatibility(self):
        """Test that old object-based syntax still works."""
        try:
            from agno.models.openai import OpenAIChat

            # Old syntax
            old_agent = Agent(model=OpenAIChat(id="gpt-4o"), telemetry=False)
            old_agent.initialize_agent()

            # New syntax
            new_agent = Agent(model="openai:gpt-4o", telemetry=False)
            new_agent.initialize_agent()

            # Both should work and produce equivalent results
            assert old_agent.model.id == new_agent.model.id
            assert old_agent.model.model_string == new_agent.model.model_string
            assert old_agent.model.__class__ == new_agent.model.__class__

        except ImportError:
            pytest.skip("OpenAI dependencies not installed")


class TestTeamModelStrings:
    """Test model strings work with Teams."""

    def test_team_with_string_model(self):
        """Test Team creation with string model."""
        try:
            from agno.agent import Agent

            # Create team with string model
            agent = Agent(name="test-agent", telemetry=False)
            team = Team(name="test-team", members=[agent], model="openai:gpt-4o-mini", telemetry=False)
            team._resolve_model_strings()  # Explicitly resolve model strings

            assert team.model is not None
            assert team.model.id == "gpt-4o-mini"
            assert "gpt-4o-mini" in team.model.model_string

        except ImportError:
            pytest.skip("Model dependencies not installed")

    def test_team_backward_compatibility(self):
        """Test that old object-based syntax still works for teams."""
        try:
            from agno.agent import Agent
            from agno.models.openai import OpenAIChat

            agent = Agent(name="test-agent", telemetry=False)

            # Old syntax
            old_team = Team(name="old-team", members=[agent], model=OpenAIChat(id="gpt-4o"), telemetry=False)
            old_team._resolve_model_strings()

            # New syntax
            new_team = Team(name="new-team", members=[agent], model="openai:gpt-4o", telemetry=False)
            new_team._resolve_model_strings()

            # Both should work and produce equivalent results
            assert old_team.model.id == new_team.model.id
            assert old_team.model.model_string == new_team.model.model_string
            assert old_team.model.__class__ == new_team.model.__class__

        except ImportError:
            pytest.skip("OpenAI dependencies not installed")


class TestModelStringEdgeCases:
    """Test edge cases and error conditions."""

    def test_model_string_with_colons_in_model_id(self):
        """Test model IDs that contain colons."""
        model_string = "openai:gpt-4:special-version"

        try:
            model = get_model_from_string(model_string)
            # Should split on first colon only
            assert model.id == "gpt-4:special-version"

        except ImportError:
            pytest.skip("OpenAI dependencies not installed")

    def test_case_insensitive_providers(self):
        """Test that provider names are case insensitive."""
        try:
            model1 = get_model_from_string("OPENAI:gpt-4o")
            model2 = get_model_from_string("openai:gpt-4o")
            model3 = get_model_from_string("OpenAI:gpt-4o")

            assert model1.id == model2.id == model3.id == "gpt-4o"
            # Model strings may vary in casing based on provider name
            assert "gpt-4o" in model1.model_string
            assert "gpt-4o" in model2.model_string
            assert "gpt-4o" in model3.model_string

        except ImportError:
            pytest.skip("OpenAI dependencies not installed")

    def test_whitespace_handling(self):
        """Test that whitespace in model strings is handled correctly."""
        try:
            model = get_model_from_string("  openai : gpt-4o  ")
            assert model.id == "gpt-4o"
            assert "gpt-4o" in model.model_string

        except ImportError:
            pytest.skip("OpenAI dependencies not installed")

    def test_model_string_round_trip(self):
        """Test that model_string property produces strings that can round-trip through get_model_from_string."""
        test_cases = [
            ("openai:gpt-4o", "OpenAIChat"),
            ("anthropic:claude-3-5-sonnet", "Claude"),
            ("google:gemini-2.0-flash", "Gemini"),
            ("meta:llama-3", "Llama"),
            ("azure-openai:gpt-4o", "AzureOpenAI"),
        ]

        for model_string, expected_class_name in test_cases:
            try:
                # Create model from string
                original_model = get_model_from_string(model_string)
                assert original_model.__class__.__name__ == expected_class_name

                # Get the model_string property
                generated_string = original_model.model_string

                # Create another model from the generated string
                recreated_model = get_model_from_string(generated_string)

                # Verify they're the same type and have the same id
                assert type(original_model) == type(recreated_model), (
                    f"Round-trip failed for {model_string}: "
                    f"{type(original_model).__name__} != {type(recreated_model).__name__}"
                )
                assert original_model.id == recreated_model.id

            except ImportError:
                pytest.skip(f"Dependencies for {model_string} not installed")

    def test_model_string_property(self):
        """Test the model_string property on Model instances."""

        class CustomModel(Model):
            def __init__(self, id: str, name: str = None, provider: str = None):
                # Need to set these before calling super().__init__ as it's a dataclass
                object.__setattr__(self, "id", id)
                object.__setattr__(self, "name", name)
                object.__setattr__(self, "provider", provider)

            def invoke(self, *args, **kwargs):
                pass

            async def ainvoke(self, *args, **kwargs):
                pass

            def invoke_stream(self, *args, **kwargs):
                pass

            async def ainvoke_stream(self, *args, **kwargs):
                pass

            def _parse_provider_response(self, *args, **kwargs):
                pass

            def _parse_provider_response_delta(self, *args, **kwargs):
                pass

        # Test with provider
        model_with_provider = CustomModel(id="test-model", provider="custom-provider")
        result = model_with_provider.model_string
        assert ":" in result
        assert "test-model" in result

        # Test without provider (fallback to class name)
        model_without_provider = CustomModel(id="test-model")
        result = model_without_provider.model_string
        assert ":" in result
        assert "test-model" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
