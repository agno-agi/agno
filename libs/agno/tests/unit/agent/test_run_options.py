"""Tests for centralized run option resolution."""

import dataclasses

import pytest

from agno.agent._run_options import ResolvedRunOptions, resolve_run_options
from agno.agent.agent import Agent


def _make_agent(**kwargs) -> Agent:
    """Create a minimal Agent instance for testing."""
    return Agent(**kwargs)


class TestResolvedRunOptionsImmutable:
    def test_frozen_raises_on_assignment(self):
        opts = ResolvedRunOptions(
            stream=True,
            stream_events=False,
            yield_run_output=False,
            add_history_to_context=False,
            add_dependencies_to_context=False,
            add_session_state_to_context=False,
            dependencies=None,
            knowledge_filters=None,
            metadata=None,
            output_schema=None,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            opts.stream = False  # type: ignore[misc]


class TestDefaultResolution:
    def test_all_defaults_from_agent(self):
        agent = _make_agent(
            stream=True,
            stream_events=True,
            add_history_to_context=True,
            add_dependencies_to_context=True,
            add_session_state_to_context=True,
            dependencies={"db": "postgres"},
            knowledge_filters={"topic": "test"},
            metadata={"env": "test"},
        )
        opts = resolve_run_options(agent)
        assert opts.stream is True
        assert opts.stream_events is True
        assert opts.add_history_to_context is True
        assert opts.add_dependencies_to_context is True
        assert opts.add_session_state_to_context is True
        assert opts.dependencies == {"db": "postgres"}
        assert opts.knowledge_filters == {"topic": "test"}
        assert opts.metadata == {"env": "test"}

    def test_bare_agent_defaults(self):
        agent = _make_agent()
        opts = resolve_run_options(agent)
        assert opts.stream is False
        assert opts.stream_events is False
        assert opts.yield_run_output is False
        assert opts.add_history_to_context is False
        assert opts.add_dependencies_to_context is False
        assert opts.add_session_state_to_context is False
        assert opts.dependencies is None
        assert opts.knowledge_filters is None
        assert opts.metadata is None
        assert opts.output_schema is None


class TestCallSiteOverrides:
    def test_stream_override(self):
        agent = _make_agent(stream=False)
        opts = resolve_run_options(agent, stream=True)
        assert opts.stream is True

    def test_stream_events_override(self):
        agent = _make_agent(stream=True, stream_events=False)
        opts = resolve_run_options(agent, stream_events=True)
        assert opts.stream_events is True

    def test_yield_run_output_override(self):
        agent = _make_agent()
        opts = resolve_run_options(agent, yield_run_output=True)
        assert opts.yield_run_output is True

    def test_context_flags_override(self):
        agent = _make_agent(
            add_history_to_context=False,
            add_dependencies_to_context=False,
            add_session_state_to_context=False,
        )
        opts = resolve_run_options(
            agent,
            add_history_to_context=True,
            add_dependencies_to_context=True,
            add_session_state_to_context=True,
        )
        assert opts.add_history_to_context is True
        assert opts.add_dependencies_to_context is True
        assert opts.add_session_state_to_context is True

    def test_dependencies_override(self):
        agent = _make_agent(dependencies={"a": 1})
        opts = resolve_run_options(agent, dependencies={"b": 2})
        assert opts.dependencies == {"b": 2}

    def test_output_schema_override(self):
        from pydantic import BaseModel

        class MySchema(BaseModel):
            name: str

        agent = _make_agent()
        opts = resolve_run_options(agent, output_schema=MySchema)
        assert opts.output_schema is MySchema


class TestStreamEventsCoupling:
    def test_stream_false_forces_stream_events_false(self):
        agent = _make_agent(stream_events=True)
        opts = resolve_run_options(agent, stream=False, stream_events=True)
        assert opts.stream is False
        assert opts.stream_events is False

    def test_stream_none_agent_none_defaults_both_false(self):
        agent = _make_agent()
        opts = resolve_run_options(agent)
        assert opts.stream is False
        assert opts.stream_events is False

    def test_stream_true_allows_stream_events(self):
        agent = _make_agent()
        opts = resolve_run_options(agent, stream=True, stream_events=True)
        assert opts.stream is True
        assert opts.stream_events is True


class TestMetadataMerge:
    def test_both_none(self):
        agent = _make_agent()
        opts = resolve_run_options(agent)
        assert opts.metadata is None

    def test_only_callsite(self):
        agent = _make_agent()
        opts = resolve_run_options(agent, metadata={"run": "value"})
        assert opts.metadata == {"run": "value"}

    def test_only_agent(self):
        agent = _make_agent(metadata={"agent": "value"})
        opts = resolve_run_options(agent)
        assert opts.metadata == {"agent": "value"}

    def test_merge_agent_takes_precedence(self):
        agent = _make_agent(metadata={"shared": "agent_wins", "agent_only": "a"})
        opts = resolve_run_options(agent, metadata={"shared": "run_value", "run_only": "r"})
        # agent.metadata takes precedence on conflicts
        assert opts.metadata["shared"] == "agent_wins"
        assert opts.metadata["agent_only"] == "a"
        assert opts.metadata["run_only"] == "r"

    def test_merge_does_not_mutate_callsite(self):
        agent = _make_agent(metadata={"a": 1})
        callsite_meta = {"b": 2}
        resolve_run_options(agent, metadata=callsite_meta)
        assert callsite_meta == {"b": 2}


class TestKnowledgeFilterMerge:
    def test_no_filters(self):
        agent = _make_agent()
        opts = resolve_run_options(agent)
        assert opts.knowledge_filters is None

    def test_only_agent_filters(self):
        agent = _make_agent(knowledge_filters={"topic": "test"})
        opts = resolve_run_options(agent)
        assert opts.knowledge_filters == {"topic": "test"}

    def test_only_callsite_filters(self):
        agent = _make_agent()
        opts = resolve_run_options(agent, knowledge_filters={"topic": "run"})
        assert opts.knowledge_filters == {"topic": "run"}

    def test_dict_merge_callsite_takes_precedence(self):
        agent = _make_agent(knowledge_filters={"topic": "agent", "agent_key": "a"})
        opts = resolve_run_options(agent, knowledge_filters={"topic": "run", "run_key": "r"})
        # get_effective_filters: run-level takes precedence for dicts
        assert opts.knowledge_filters["topic"] == "run"
        assert opts.knowledge_filters["agent_key"] == "a"
        assert opts.knowledge_filters["run_key"] == "r"

    def test_list_merge(self):
        from agno.filters import EQ

        agent_filters = [EQ("a", "1")]
        run_filters = [EQ("b", "2")]
        agent = _make_agent(knowledge_filters=agent_filters)
        opts = resolve_run_options(agent, knowledge_filters=run_filters)
        assert len(opts.knowledge_filters) == 2


class TestAgentNotMutated:
    def test_resolve_does_not_mutate_agent(self):
        agent = _make_agent(
            stream=True,
            metadata={"a": 1},
            dependencies={"db": "test"},
            knowledge_filters={"topic": "test"},
        )
        original_stream = agent.stream
        original_metadata = agent.metadata.copy()
        original_deps = agent.dependencies.copy()

        resolve_run_options(
            agent,
            stream=False,
            metadata={"b": 2},
            dependencies={"other": "value"},
            knowledge_filters={"other_topic": "run"},
        )

        assert agent.stream == original_stream
        assert agent.metadata == original_metadata
        assert agent.dependencies == original_deps

    def test_dependencies_defensive_copy(self):
        agent = _make_agent(dependencies={"key": "original"})
        opts = resolve_run_options(agent)
        opts.dependencies["key"] = "mutated"  # type: ignore[index]
        assert agent.dependencies == {"key": "original"}

    def test_callsite_dependencies_defensive_copy(self):
        agent = _make_agent()
        callsite_deps = {"key": "original"}
        opts = resolve_run_options(agent, dependencies=callsite_deps)
        opts.dependencies["key"] = "mutated"  # type: ignore[index]
        assert callsite_deps == {"key": "original"}


# ---------------------------------------------------------------------------
# Functions exist and are importable
# ---------------------------------------------------------------------------


class TestFunctionsImportable:
    def test_run_dispatch_importable(self):
        from agno.agent._run import run_dispatch

        assert callable(run_dispatch)

    def test_run_importable(self):
        from agno.agent._run import _run

        assert callable(_run)

    def test_run_stream_importable(self):
        from agno.agent._run import _run_stream

        assert callable(_run_stream)

    def test_arun_dispatch_importable(self):
        from agno.agent._run import arun_dispatch

        assert callable(arun_dispatch)

    def test_arun_importable(self):
        from agno.agent._run import _arun

        assert callable(_arun)

    def test_arun_stream_importable(self):
        from agno.agent._run import _arun_stream

        assert callable(_arun_stream)


# ---------------------------------------------------------------------------
# Agent.run / Agent.arun dispatch to the correct names
# ---------------------------------------------------------------------------


class TestAgentWrappersDelegateCorrectly:
    def test_agent_run_delegates_to_run_dispatch(self, monkeypatch):
        from agno.agent import _run as run_module

        captured = {}

        def fake_dispatch(agent, input, **kwargs):
            captured["called"] = True
            captured["input"] = input
            return None

        monkeypatch.setattr(run_module, "run_dispatch", fake_dispatch)

        agent = _make_agent()
        agent.run(input="hello")
        assert captured["called"] is True
        assert captured["input"] == "hello"

    def test_agent_arun_delegates_to_arun_dispatch(self, monkeypatch):
        from agno.agent import _run as run_module

        captured = {}

        def fake_dispatch(agent, input, **kwargs):
            captured["called"] = True
            captured["input"] = input
            return None

        monkeypatch.setattr(run_module, "arun_dispatch", fake_dispatch)

        agent = _make_agent()
        agent.arun(input="hello")
        assert captured["called"] is True
        assert captured["input"] == "hello"
