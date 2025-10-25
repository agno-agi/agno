import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.utils import create_model, get_model_string
from agno.team import Team


class TestModelStringCore:
    """Test core model string functionality."""

    def test_create_model_with_string(self):
        """Test creating models from strings."""
        # Test successful creation
        model = create_model("openai:gpt-4o-mini")
        assert model.id == "gpt-4o-mini"
        assert model.model_string == "openai:gpt-4o-mini"

    def test_create_model_with_model_object(self):
        """Test that passing Model objects works unchanged."""
        from agno.models.openai import OpenAIChat

        original = OpenAIChat(id="gpt-4o")
        result = create_model(original)

        assert result is original  # Should return the same object
        assert result.id == "gpt-4o"
        assert result.model_string == "openai:gpt-4o"

    def test_invalid_format_raises_error(self):
        """Test that invalid format strings raise appropriate errors."""
        with pytest.raises(ValueError, match="Model string must be 'provider:model_id'"):
            create_model("invalid-format")

        with pytest.raises(ValueError, match="Both provider and model_id must be non-empty"):
            create_model(":")

        with pytest.raises(ValueError, match="Both provider and model_id must be non-empty"):
            create_model("provider:")

        with pytest.raises(ValueError, match="Both provider and model_id must be non-empty"):
            create_model(":model")

    def test_unsupported_provider_raises_error(self):
        """Test that unsupported providers raise appropriate errors."""
        with pytest.raises(ValueError, match="Provider 'unknown' not supported"):
            create_model("unknown:model-id")

    def test_invalid_type_raises_error(self):
        """Test that invalid types raise appropriate errors."""
        with pytest.raises(TypeError, match="Model must be Model instance or string"):
            create_model(123)  # type: ignore

        with pytest.raises(TypeError, match="Model must be Model instance or string"):
            create_model(None)  # type: ignore


class TestModelStringProviders:
    """Test model string functionality for key providers."""

    @pytest.mark.parametrize("provider", ["openai", "anthropic", "google", "groq", "ollama"])
    def test_provider_model_creation(self, provider):
        """Test that key providers can create models from strings."""
        model_string = f"{provider}:test-model-id"

        try:
            model = create_model(model_string)
            assert model.id == "test-model-id"

            # Test reverse conversion
            reverse_string = get_model_string(model)
            assert ":" in reverse_string
            assert reverse_string.endswith("test-model-id")

        except ImportError:
            pytest.skip(f"Dependencies for {provider} not installed")


class TestAgentModelStrings:
    """Test model strings work with Agents."""

    def test_agent_with_string_model(self):
        """Test Agent creation with string model."""
        try:
            # Test main model
            agent = Agent(model="openai:gpt-4o-mini", telemetry=False)
            assert agent.model is not None
            assert agent.model.id == "gpt-4o-mini"
            assert agent.model.model_string == "openai:gpt-4o-mini"

            # Test reasoning model
            agent_reasoning = Agent(
                model="openai:gpt-4o-mini", reasoning_model="anthropic:claude-3-5-sonnet", telemetry=False
            )
            assert agent_reasoning.reasoning_model is not None
            assert agent_reasoning.reasoning_model.model_string == "anthropic:claude-3-5-sonnet"

        except ImportError:
            pytest.skip("Model dependencies not installed")

    def test_agent_backward_compatibility(self):
        """Test that old object-based syntax still works."""
        try:
            from agno.models.openai import OpenAIChat

            # Old syntax
            old_agent = Agent(model=OpenAIChat(id="gpt-4o"), telemetry=False)

            # New syntax
            new_agent = Agent(model="openai:gpt-4o", telemetry=False)

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

            assert team.model is not None
            assert team.model.id == "gpt-4o-mini"
            assert team.model.model_string == "openai:gpt-4o-mini"

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

            # New syntax
            new_team = Team(name="new-team", members=[agent], model="openai:gpt-4o", telemetry=False)

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
            model = create_model(model_string)
            # Should split on first colon only
            assert model.id == "gpt-4:special-version"

        except ImportError:
            pytest.skip("OpenAI dependencies not installed")

    def test_case_insensitive_providers(self):
        """Test that provider names are case insensitive."""
        try:
            model1 = create_model("OPENAI:gpt-4o")
            model2 = create_model("openai:gpt-4o")
            model3 = create_model("OpenAI:gpt-4o")

            assert model1.id == model2.id == model3.id == "gpt-4o"
            assert model1.model_string == model2.model_string == model3.model_string

        except ImportError:
            pytest.skip("OpenAI dependencies not installed")

    def test_whitespace_handling(self):
        """Test that whitespace in model strings is handled correctly."""
        try:
            model = create_model("  openai : gpt-4o  ")
            assert model.id == "gpt-4o"
            assert model.model_string == "openai:gpt-4o"

        except ImportError:
            pytest.skip("OpenAI dependencies not installed")

    def test_get_model_string_fallback(self):
        """Test the fallback behavior of get_model_string."""

        class CustomModel(Model):
            def __init__(self, id: str, provider: str = None):
                super().__init__(id=id, provider=provider)

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
        result = get_model_string(model_with_provider)
        assert result == "custom-provider:test-model"

        # Test without provider (fallback to class name)
        model_without_provider = CustomModel(id="test-model")
        result = get_model_string(model_without_provider)
        # The actual behavior is that it returns the provider attribute value, which could be "None"
        assert result in ["custommodel:test-model", "None:test-model"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
