"""Tests for centralized team run option resolution and renamed run functions."""

import dataclasses

import pytest

from agno.team._run_options import ResolvedRunOptions, resolve_run_options
from agno.team.team import Team


def _make_team(**kwargs) -> Team:
    """Create a minimal Team instance for testing."""
    return Team(members=[], **kwargs)


# ---------------------------------------------------------------------------
# ResolvedRunOptions immutability
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Default resolution
# ---------------------------------------------------------------------------


class TestDefaultResolution:
    def test_all_defaults_from_team(self):
        team = _make_team(
            stream=True,
            stream_events=True,
            add_history_to_context=True,
            add_dependencies_to_context=True,
            add_session_state_to_context=True,
            dependencies={"db": "postgres"},
            knowledge_filters={"topic": "test"},
            metadata={"env": "test"},
        )
        opts = resolve_run_options(team)
        assert opts.stream is True
        assert opts.stream_events is True
        assert opts.add_history_to_context is True
        assert opts.add_dependencies_to_context is True
        assert opts.add_session_state_to_context is True
        assert opts.dependencies == {"db": "postgres"}
        assert opts.knowledge_filters == {"topic": "test"}
        assert opts.metadata == {"env": "test"}

    def test_bare_team_defaults(self):
        team = _make_team()
        opts = resolve_run_options(team)
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


# ---------------------------------------------------------------------------
# Call-site overrides
# ---------------------------------------------------------------------------


class TestCallSiteOverrides:
    def test_stream_override(self):
        team = _make_team(stream=False)
        opts = resolve_run_options(team, stream=True)
        assert opts.stream is True

    def test_stream_events_override(self):
        team = _make_team(stream=True, stream_events=False)
        opts = resolve_run_options(team, stream_events=True)
        assert opts.stream_events is True

    def test_yield_run_output_override(self):
        team = _make_team()
        opts = resolve_run_options(team, yield_run_output=True)
        assert opts.yield_run_output is True

    def test_context_flags_override(self):
        team = _make_team(
            add_history_to_context=False,
            add_dependencies_to_context=False,
            add_session_state_to_context=False,
        )
        opts = resolve_run_options(
            team,
            add_history_to_context=True,
            add_dependencies_to_context=True,
            add_session_state_to_context=True,
        )
        assert opts.add_history_to_context is True
        assert opts.add_dependencies_to_context is True
        assert opts.add_session_state_to_context is True

    def test_dependencies_override(self):
        team = _make_team(dependencies={"a": 1})
        opts = resolve_run_options(team, dependencies={"b": 2})
        assert opts.dependencies == {"b": 2}

    def test_output_schema_override(self):
        from pydantic import BaseModel

        class MySchema(BaseModel):
            name: str

        team = _make_team()
        opts = resolve_run_options(team, output_schema=MySchema)
        assert opts.output_schema is MySchema


# ---------------------------------------------------------------------------
# Stream + stream_events coupling
# ---------------------------------------------------------------------------


class TestStreamEventsCoupling:
    def test_stream_false_forces_stream_events_false(self):
        team = _make_team(stream_events=True)
        opts = resolve_run_options(team, stream=False, stream_events=True)
        assert opts.stream is False
        assert opts.stream_events is False

    def test_stream_none_team_none_defaults_both_false(self):
        team = _make_team()
        opts = resolve_run_options(team)
        assert opts.stream is False
        assert opts.stream_events is False

    def test_stream_true_allows_stream_events(self):
        team = _make_team()
        opts = resolve_run_options(team, stream=True, stream_events=True)
        assert opts.stream is True
        assert opts.stream_events is True


# ---------------------------------------------------------------------------
# Metadata merge
# ---------------------------------------------------------------------------


class TestMetadataMerge:
    def test_both_none(self):
        team = _make_team()
        opts = resolve_run_options(team)
        assert opts.metadata is None

    def test_only_callsite(self):
        team = _make_team()
        opts = resolve_run_options(team, metadata={"run": "value"})
        assert opts.metadata == {"run": "value"}

    def test_only_team(self):
        team = _make_team(metadata={"team": "value"})
        opts = resolve_run_options(team)
        assert opts.metadata == {"team": "value"}

    def test_merge_team_takes_precedence(self):
        team = _make_team(metadata={"shared": "team_wins", "team_only": "t"})
        opts = resolve_run_options(team, metadata={"shared": "run_value", "run_only": "r"})
        assert opts.metadata["shared"] == "team_wins"
        assert opts.metadata["team_only"] == "t"
        assert opts.metadata["run_only"] == "r"

    def test_merge_does_not_mutate_callsite(self):
        team = _make_team(metadata={"a": 1})
        callsite_meta = {"b": 2}
        resolve_run_options(team, metadata=callsite_meta)
        assert callsite_meta == {"b": 2}


# ---------------------------------------------------------------------------
# Knowledge filter merge
# ---------------------------------------------------------------------------


class TestKnowledgeFilterMerge:
    def test_no_filters(self):
        team = _make_team()
        opts = resolve_run_options(team)
        assert opts.knowledge_filters is None

    def test_only_team_filters(self):
        team = _make_team(knowledge_filters={"topic": "test"})
        opts = resolve_run_options(team)
        assert opts.knowledge_filters == {"topic": "test"}

    def test_only_callsite_filters(self):
        team = _make_team()
        opts = resolve_run_options(team, knowledge_filters={"topic": "run"})
        assert opts.knowledge_filters == {"topic": "run"}

    def test_dict_merge_callsite_takes_precedence(self):
        team = _make_team(knowledge_filters={"topic": "team", "team_key": "t"})
        opts = resolve_run_options(team, knowledge_filters={"topic": "run", "run_key": "r"})
        assert opts.knowledge_filters["topic"] == "run"
        assert opts.knowledge_filters["team_key"] == "t"
        assert opts.knowledge_filters["run_key"] == "r"

    def test_list_merge(self):
        from agno.filters import EQ

        team_filters = [EQ("a", "1")]
        run_filters = [EQ("b", "2")]
        team = _make_team(knowledge_filters=team_filters)
        opts = resolve_run_options(team, knowledge_filters=run_filters)
        assert len(opts.knowledge_filters) == 2


# ---------------------------------------------------------------------------
# Defensive copy (dependencies not mutated on team)
# ---------------------------------------------------------------------------


class TestTeamNotMutated:
    def test_resolve_does_not_mutate_team(self):
        team = _make_team(
            stream=True,
            metadata={"a": 1},
            dependencies={"db": "test"},
            knowledge_filters={"topic": "test"},
        )
        original_stream = team.stream
        original_metadata = team.metadata.copy()
        original_deps = team.dependencies.copy()

        resolve_run_options(
            team,
            stream=False,
            metadata={"b": 2},
            dependencies={"other": "value"},
            knowledge_filters={"other_topic": "run"},
        )

        assert team.stream == original_stream
        assert team.metadata == original_metadata
        assert team.dependencies == original_deps

    def test_dependencies_defensive_copy(self):
        team = _make_team(dependencies={"key": "original"})
        opts = resolve_run_options(team)
        # Mutating the resolved deps should not affect the team
        opts.dependencies["key"] = "mutated"  # type: ignore[index]
        assert team.dependencies == {"key": "original"}

    def test_callsite_dependencies_defensive_copy(self):
        team = _make_team()
        callsite_deps = {"key": "original"}
        opts = resolve_run_options(team, dependencies=callsite_deps)
        opts.dependencies["key"] = "mutated"  # type: ignore[index]
        assert callsite_deps == {"key": "original"}


# ---------------------------------------------------------------------------
# Renamed functions exist and are importable
# ---------------------------------------------------------------------------


class TestRenamedFunctionsImportable:
    def test_run_dispatch_importable(self):
        from agno.team._run import run_dispatch

        assert callable(run_dispatch)

    def test_run_importable(self):
        from agno.team._run import _run

        assert callable(_run)

    def test_run_stream_importable(self):
        from agno.team._run import _run_stream

        assert callable(_run_stream)

    def test_arun_dispatch_importable(self):
        from agno.team._run import arun_dispatch

        assert callable(arun_dispatch)

    def test_arun_importable(self):
        from agno.team._run import _arun

        assert callable(_arun)

    def test_arun_stream_importable(self):
        from agno.team._run import _arun_stream

        assert callable(_arun_stream)

    def test_asetup_session_importable(self):
        from agno.team._run import _asetup_session

        assert callable(_asetup_session)

    def test_old_names_not_present(self):
        """Old _impl-suffixed names should not exist on the module."""
        from agno.team import _run

        assert not hasattr(_run, "run_impl")
        assert not hasattr(_run, "run_stream_impl")
        assert not hasattr(_run, "arun_impl")
        assert not hasattr(_run, "arun_stream_impl")
        assert not hasattr(_run, "asetup_session")
        assert not hasattr(_run, "run")
        assert not hasattr(_run, "arun")


# ---------------------------------------------------------------------------
# Team.run / Team.arun dispatch to the new names
# ---------------------------------------------------------------------------


class TestTeamWrappersDelegateCorrectly:
    def test_team_run_delegates_to_run_dispatch(self, monkeypatch):
        """Verify Team.run() calls _run.run_dispatch under the hood."""
        from agno.team import _run as run_module

        captured = {}

        def fake_dispatch(team, *, input, **kwargs):
            captured["called"] = True
            captured["input"] = input
            return None

        monkeypatch.setattr(run_module, "run_dispatch", fake_dispatch)

        team = _make_team()
        team.run(input="hello")
        assert captured["called"] is True
        assert captured["input"] == "hello"

    def test_team_arun_delegates_to_arun_dispatch(self, monkeypatch):
        """Verify Team.arun() calls _run.arun_dispatch under the hood."""
        from agno.team import _run as run_module

        captured = {}

        def fake_dispatch(team, *, input, **kwargs):
            captured["called"] = True
            captured["input"] = input
            return None

        monkeypatch.setattr(run_module, "arun_dispatch", fake_dispatch)

        team = _make_team()
        team.arun(input="hello")
        assert captured["called"] is True
        assert captured["input"] == "hello"


# ---------------------------------------------------------------------------
# Parity: team and agent ResolvedRunOptions have the same fields
# ---------------------------------------------------------------------------


class TestParityWithAgent:
    def test_same_fields_as_agent_run_options(self):
        from agno.agent._run_options import ResolvedRunOptions as AgentOpts
        from agno.team._run_options import ResolvedRunOptions as TeamOpts

        agent_fields = {f.name for f in dataclasses.fields(AgentOpts)}
        team_fields = {f.name for f in dataclasses.fields(TeamOpts)}
        assert agent_fields == team_fields

    def test_same_field_types_as_agent_run_options(self):
        from agno.agent._run_options import ResolvedRunOptions as AgentOpts
        from agno.team._run_options import ResolvedRunOptions as TeamOpts

        agent_types = {f.name: f.type for f in dataclasses.fields(AgentOpts)}
        team_types = {f.name: f.type for f in dataclasses.fields(TeamOpts)}
        assert agent_types == team_types
