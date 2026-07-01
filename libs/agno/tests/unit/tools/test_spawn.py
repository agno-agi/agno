"""
Unit tests for SpawnAgentTools.

These tests validate the toolkit structure, tool resolution, model resolution,
and depth limiting without making any real API calls.
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.models.base import Model
from agno.tools.function import Function
from agno.tools.spawn import SpawnAgentTools
from agno.tools.toolkit import Toolkit

# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


class FakeModel(Model):
    """Minimal Model stub that satisfies all abstract methods."""

    def invoke(self, *args, **kwargs):
        return MagicMock()

    async def ainvoke(self, *args, **kwargs):
        return MagicMock()

    def invoke_stream(self, *args, **kwargs):
        yield MagicMock()

    async def ainvoke_stream(self, *args, **kwargs):
        yield MagicMock()

    def _parse_provider_response(self, response, **kwargs):
        return MagicMock()

    def _parse_provider_response_delta(self, response):
        return MagicMock()


class FakeToolkit(Toolkit):
    """Minimal Toolkit stub for testing deep-copy behavior."""

    def __init__(self):
        super().__init__(name="fake_toolkit", tools=[])
        self.marker = "original"


@pytest.fixture
def models():
    return {
        "fast": FakeModel(id="fake-fast"),
        "balanced": FakeModel(id="fake-balanced"),
        "powerful": FakeModel(id="fake-powerful"),
    }


@pytest.fixture
def tools():
    return {
        "reader": FakeToolkit(),
        "shell": FakeToolkit(),
    }


@pytest.fixture
def spawn(models, tools):
    return SpawnAgentTools(
        available_tools=tools,
        available_models=models,
        default_model_tier="balanced",
        max_depth=3,
    )


# ---------------------------------------------------------------
# Toolkit registration
# ---------------------------------------------------------------


class TestRegistration:
    def test_inherits_from_toolkit(self):
        st = SpawnAgentTools()
        assert isinstance(st, Toolkit)

    def test_name_is_spawn_agent_tools(self):
        st = SpawnAgentTools()
        assert st.name == "spawn_agent_tools"

    def test_spawn_agent_function_registered(self, spawn):
        assert "spawn_agent" in spawn.functions

    def test_spawn_agent_is_a_function_object(self, spawn):
        func = spawn.functions["spawn_agent"]
        assert isinstance(func, Function)

    def test_schema_has_required_params(self, spawn):
        func = Function.from_callable(spawn.spawn_agent)
        required = func.parameters.get("required", [])
        assert "task" in required
        assert "persona" in required
        assert "instructions" in required

    def test_schema_has_optional_params(self, spawn):
        func = Function.from_callable(spawn.spawn_agent)
        props = func.parameters.get("properties", {})
        required = func.parameters.get("required", [])
        assert "tools_needed" in props
        assert "tools_needed" not in required
        assert "model_tier" in props
        assert "model_tier" not in required

    def test_description_is_set(self, spawn):
        func = Function.from_callable(spawn.spawn_agent)
        assert func.description is not None
        assert "ephemeral" in func.description.lower()


# ---------------------------------------------------------------
# Tool resolution
# ---------------------------------------------------------------


class TestToolResolution:
    def test_empty_string_returns_empty_list(self, spawn):
        result = spawn._resolve_tools("")
        assert result == []

    def test_whitespace_only_returns_empty_list(self, spawn):
        result = spawn._resolve_tools("   ")
        assert result == []

    def test_single_known_tool(self, spawn):
        result = spawn._resolve_tools("reader")
        assert len(result) == 1
        assert isinstance(result[0], Toolkit)

    def test_multiple_known_tools(self, spawn):
        result = spawn._resolve_tools("reader,shell")
        assert len(result) == 2

    def test_unknown_tool_is_skipped(self, spawn):
        result = spawn._resolve_tools("reader,nonexistent,shell")
        assert len(result) == 2

    def test_all_unknown_returns_empty(self, spawn):
        result = spawn._resolve_tools("foo,bar")
        assert result == []

    def test_whitespace_in_names_is_trimmed(self, spawn):
        result = spawn._resolve_tools(" reader , shell ")
        assert len(result) == 2

    def test_toolkit_is_deep_copied(self, spawn):
        result = spawn._resolve_tools("reader")
        original = spawn.available_tools["reader"]
        copy = result[0]
        # They should be different objects
        assert copy is not original
        # But same type
        assert type(copy) is type(original)


# ---------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------


class TestModelResolution:
    def test_known_tier(self, spawn):
        model = spawn._resolve_model("fast")
        assert model is not None
        assert model.id == "fake-fast"

    def test_default_tier_when_empty(self, spawn):
        model = spawn._resolve_model("")
        assert model is not None
        assert model.id == "fake-balanced"

    def test_unknown_tier_falls_back_to_default(self, spawn):
        model = spawn._resolve_model("nonexistent")
        assert model is not None
        assert model.id == "fake-balanced"

    def test_no_models_configured_returns_none(self):
        st = SpawnAgentTools(available_models={})
        model = st._resolve_model("anything")
        assert model is None


# ---------------------------------------------------------------
# Depth limiting
# ---------------------------------------------------------------


class TestDepthLimiting:
    def test_initial_depth_is_zero(self, spawn):
        assert spawn._current_depth == 0

    def test_depth_setter_works(self, spawn):
        spawn._current_depth = 2
        assert spawn._current_depth == 2
        spawn._current_depth = 0

    def test_spawn_returns_error_at_max_depth(self, spawn):
        spawn._current_depth = 3  # equals max_depth
        result = spawn.spawn_agent(
            task="test",
            persona="tester",
            instructions="do nothing",
        )
        assert "[ERROR]" in result
        assert "depth" in result.lower()
        # Reset
        spawn._current_depth = 0

    def test_spawn_returns_error_above_max_depth(self, spawn):
        spawn._current_depth = 5
        result = spawn.spawn_agent(
            task="test",
            persona="tester",
            instructions="do nothing",
        )
        assert "[ERROR]" in result
        spawn._current_depth = 0

    def test_custom_max_depth(self):
        st = SpawnAgentTools(
            available_models={"fast": FakeModel(id="f")},
            max_depth=1,
        )
        st._current_depth = 1
        result = st.spawn_agent(
            task="test",
            persona="tester",
            instructions="do nothing",
        )
        assert "[ERROR]" in result
        st._current_depth = 0


# ---------------------------------------------------------------
# Ephemeral agent execution (mocked)
# ---------------------------------------------------------------


class TestEphemeralExecution:
    @patch("agno.tools.spawn.SpawnAgentTools._run_ephemeral")
    def test_spawn_calls_run_ephemeral(self, mock_run, spawn):
        mock_run.return_value = "mocked result"
        result = spawn.spawn_agent(
            task="Analyse this code",
            persona="a code reviewer",
            instructions="Look for bugs",
            tools_needed="reader",
            model_tier="fast",
        )
        assert result == "mocked result"
        mock_run.assert_called_once()

    @patch("agno.tools.spawn.SpawnAgentTools._run_ephemeral")
    def test_depth_resets_after_success(self, mock_run, spawn):
        mock_run.return_value = "ok"
        spawn.spawn_agent(
            task="t",
            persona="p",
            instructions="i",
        )
        assert spawn._current_depth == 0

    @patch("agno.tools.spawn.SpawnAgentTools._run_ephemeral")
    def test_depth_resets_after_exception(self, mock_run, spawn):
        mock_run.side_effect = RuntimeError("boom")
        # The mock raises before the try/except inside _run_ephemeral
        # can catch it, so spawn_agent propagates it. The finally
        # block should still reset depth.
        with pytest.raises(RuntimeError):
            spawn.spawn_agent(
                task="t",
                persona="p",
                instructions="i",
            )
        assert spawn._current_depth == 0

    @patch("agno.tools.spawn.SpawnAgentTools._run_ephemeral")
    def test_instructions_include_persona(self, mock_run, spawn):
        mock_run.return_value = "ok"
        spawn.spawn_agent(
            task="do something",
            persona="a security expert",
            instructions="check for XSS",
        )
        call_kwargs = mock_run.call_args
        instructions = call_kwargs.kwargs.get("instructions") or call_kwargs[1].get("instructions")
        joined = " ".join(instructions)
        assert "security expert" in joined

    def test_run_ephemeral_returns_error_on_exception(self, spawn):
        # Pass a model that will fail when Agent tries to use it
        result = spawn._run_ephemeral(
            task="test",
            persona="tester",
            model=FakeModel(id="will-fail"),
            tools=[],
            instructions=["test"],
        )
        # Agent.run() will fail because FakeModel doesn't produce
        # real responses, so we expect an error string
        assert isinstance(result, str)


# ---------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------


class TestConfiguration:
    def test_default_model_tier(self):
        st = SpawnAgentTools(default_model_tier="powerful")
        assert st.default_model_tier == "powerful"

    def test_default_max_depth(self):
        st = SpawnAgentTools()
        assert st.max_depth == 3

    def test_custom_max_depth(self):
        st = SpawnAgentTools(max_depth=10)
        assert st.max_depth == 10

    def test_inherit_session_state_default_false(self):
        st = SpawnAgentTools()
        assert st.inherit_session_state is False

    def test_inherit_session_state_true(self):
        st = SpawnAgentTools(inherit_session_state=True)
        assert st.inherit_session_state is True

    def test_empty_available_tools(self):
        st = SpawnAgentTools()
        assert st.available_tools == {}

    def test_empty_available_models(self):
        st = SpawnAgentTools()
        assert st.available_models == {}
