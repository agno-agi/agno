"""Tests for centralized team run option resolution and renamed run functions."""

import dataclasses
import time
from typing import Any, AsyncIterator, Dict, Iterator

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.session import TeamSession
from agno.team._run_options import ResolvedRunOptions, resolve_run_options
from agno.team.team import Team


def _make_team(**kwargs) -> Team:
    """Create a minimal Team instance for testing."""
    return Team(members=[], **kwargs)


class MockModel(Model):
    """Minimal offline model: returns a canned text response without any network call."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(
            content="ok",
            role="assistant",
            response_usage=MessageMetrics(),
        )

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def _seed_team_session(db: InMemoryDb, session_id: str, team_id: str, metadata: Dict[str, Any]) -> None:
    """Insert a session record with the given metadata, as if written by an earlier deployment."""
    db.upsert_session(
        TeamSession(session_id=session_id, team_id=team_id, metadata=metadata, created_at=int(time.time()))
    )


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

    def test_dependencies_merge_callsite_over_team(self):
        # Call-site dependencies merge with team.dependencies (call-site keys win on conflict);
        # team-level keys (e.g. prompt-template vars) are preserved, not clobbered.
        team = _make_team(dependencies={"a": 1})
        opts = resolve_run_options(team, dependencies={"b": 2})
        assert opts.dependencies == {"a": 1, "b": 2}

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
# Dependencies merge
# ---------------------------------------------------------------------------


class TestDependenciesMerge:
    """Call-site dependencies merge with team.dependencies instead of replacing them.

    Regression: interfaces (Slack/WhatsApp) always pass a non-None call-site
    ``dependencies`` (channel/thread ids). The old replacement behavior discarded the
    team's own dependencies, dropping prompt-template variables on those surfaces.
    """

    def test_both_none(self):
        team = _make_team()
        opts = resolve_run_options(team)
        assert opts.dependencies is None

    def test_only_callsite(self):
        team = _make_team()
        opts = resolve_run_options(team, dependencies={"run": "value"})
        assert opts.dependencies == {"run": "value"}

    def test_only_team(self):
        team = _make_team(dependencies={"team": "value"})
        opts = resolve_run_options(team)
        assert opts.dependencies == {"team": "value"}

    def test_merge_preserves_team_keys(self):
        team = _make_team(dependencies={"owner_name": "Ash", "caller_information": "resolver"})
        opts = resolve_run_options(team, dependencies={"channel": "C123", "thread": "T1"})
        assert opts.dependencies == {
            "owner_name": "Ash",
            "caller_information": "resolver",
            "channel": "C123",
            "thread": "T1",
        }

    def test_merge_callsite_takes_precedence(self):
        team = _make_team(dependencies={"x": "team", "team_only": "t"})
        opts = resolve_run_options(team, dependencies={"x": "call", "run_only": "r"})
        # call-site wins on conflict; runtime context overrides static config
        assert opts.dependencies["x"] == "call"
        assert opts.dependencies["team_only"] == "t"
        assert opts.dependencies["run_only"] == "r"

    def test_merge_does_not_mutate_callsite(self):
        team = _make_team(dependencies={"a": 1})
        callsite_deps = {"b": 2}
        resolve_run_options(team, dependencies=callsite_deps)
        assert callsite_deps == {"b": 2}

    def test_merge_does_not_mutate_team(self):
        team = _make_team(dependencies={"a": 1})
        resolve_run_options(team, dependencies={"b": 2})
        assert team.dependencies == {"a": 1}


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

    def test_merge_callsite_takes_precedence(self):
        # Metadata resolves like dependencies: call-site keys win on conflict.
        team = _make_team(metadata={"shared": "team_value", "team_only": "t"})
        opts = resolve_run_options(team, metadata={"shared": "run_value", "run_only": "r"})
        assert opts.metadata["shared"] == "run_value"
        assert opts.metadata["team_only"] == "t"
        assert opts.metadata["run_only"] == "r"

    def test_only_session(self):
        team = _make_team()
        opts = resolve_run_options(team, session_metadata={"session": "value"})
        assert opts.metadata == {"session": "value"}

    def test_session_beats_team(self):
        team = _make_team(metadata={"shared": "team_value", "team_only": "t"})
        opts = resolve_run_options(team, session_metadata={"shared": "session_value", "session_only": "s"})
        assert opts.metadata["shared"] == "session_value"
        assert opts.metadata["team_only"] == "t"
        assert opts.metadata["session_only"] == "s"

    def test_callsite_beats_session(self):
        team = _make_team()
        opts = resolve_run_options(
            team,
            metadata={"shared": "run_value", "run_only": "r"},
            session_metadata={"shared": "session_value", "session_only": "s"},
        )
        assert opts.metadata["shared"] == "run_value"
        assert opts.metadata["session_only"] == "s"
        assert opts.metadata["run_only"] == "r"

    def test_three_layer_merge_non_conflicting_keys(self):
        team = _make_team(metadata={"team_only": "t", "shared": "team_value"})
        opts = resolve_run_options(
            team,
            metadata={"run_only": "r", "shared": "run_value"},
            session_metadata={"session_only": "s"},
        )
        assert opts.metadata == {
            "team_only": "t",
            "session_only": "s",
            "run_only": "r",
            "shared": "run_value",
        }

    def test_merge_does_not_mutate_callsite(self):
        # Includes a nested dict: the recursive in-place merge must never write
        # other layers' values into the caller's nested dicts.
        team = _make_team(metadata={"a": 1, "nested": {"team": True}})
        callsite_meta = {"b": 2, "nested": {"call": True}}
        resolve_run_options(team, metadata=callsite_meta)
        assert callsite_meta == {"b": 2, "nested": {"call": True}}

    def test_merge_does_not_mutate_team_nested_dicts(self):
        # merge_dictionaries recurses in place: a shallow copy of team.metadata
        # would let call-site values contaminate the team's nested dicts.
        team = _make_team(metadata={"policy": {"read_only": True}, "flat": "team_value"})
        opts = resolve_run_options(
            team,
            metadata={"policy": {"read_only": False}, "flat": "run_value"},
            session_metadata={"policy": {"source": "session"}},
        )
        assert opts.metadata["policy"] == {"read_only": False, "source": "session"}
        assert team.metadata == {"policy": {"read_only": True}, "flat": "team_value"}

    def test_merge_does_not_mutate_session_nested_dicts(self):
        # merge_dictionaries recurses in place: a shallow copy of session_metadata
        # would let call-site values contaminate the caller's nested dicts.
        team = _make_team(metadata={"policy": {"read_only": True}})
        session_meta = {"policy": {"source": "session"}}
        resolve_run_options(team, metadata={"policy": {"read_only": False}}, session_metadata=session_meta)
        assert session_meta == {"policy": {"source": "session"}}

    def test_resolved_metadata_mutation_does_not_reach_team(self):
        team = _make_team(metadata={"policy": {"read_only": True}})
        opts = resolve_run_options(team)
        opts.metadata["policy"]["read_only"] = False  # type: ignore[index]
        assert team.metadata == {"policy": {"read_only": True}}

    def test_resolved_metadata_does_not_alias_callsite_nested_dicts(self):
        team = _make_team()
        callsite = {"labels": {"team": "ops"}}
        opts = resolve_run_options(team, metadata=callsite)
        opts.metadata["labels"]["team"] = "sre"  # type: ignore[index]
        assert callsite == {"labels": {"team": "ops"}}


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


# ---------------------------------------------------------------------------
# Singleton isolation: session reads never mutate the shared Team instance
# ---------------------------------------------------------------------------


class TestTeamSingletonIsolation:
    def _seed_session(self, db, session_id: str, team_id: str, metadata) -> None:
        import time

        from agno.session import TeamSession

        db.upsert_session(
            TeamSession(session_id=session_id, team_id=team_id, metadata=metadata, created_at=int(time.time()))
        )

    def test_team_metadata_not_aliased_to_session(self):
        from agno.db.in_memory import InMemoryDb
        from agno.team._storage import _read_or_create_session, _update_metadata

        db = InMemoryDb()
        self._seed_session(db, "session-a", "team-1", {"k": "v"})
        team = _make_team(id="team-1", db=db, metadata={"env": "test"})
        session = _read_or_create_session(team, session_id="session-a")
        _update_metadata(team, session=session)
        assert team.metadata is not session.metadata
        assert team.metadata == {"env": "test"}
        # Session side: team metadata fills keys the session does not set
        assert session.metadata == {"k": "v", "env": "test"}

    def test_new_session_seeding_not_aliased(self):
        from agno.db.in_memory import InMemoryDb
        from agno.team._storage import _read_or_create_session

        team = _make_team(id="team-1", db=InMemoryDb(), metadata={"env": "test"})
        session = _read_or_create_session(team, session_id="fresh")
        assert session.metadata == {"env": "test"}
        assert session.metadata is not team.metadata

    @pytest.mark.asyncio
    async def test_new_session_seeding_not_aliased_async(self):
        from agno.db.in_memory import InMemoryDb
        from agno.team._storage import _aread_or_create_session

        team = _make_team(id="team-1", db=InMemoryDb(), metadata={"env": "test"})
        session = await _aread_or_create_session(team, session_id="fresh")
        assert session.metadata == {"env": "test"}
        assert session.metadata is not team.metadata


# ---------------------------------------------------------------------------
# Session metadata precedence on the full run() path
# ---------------------------------------------------------------------------


class TestTeamRunSessionMetadataPrecedence:
    """Run-level twin of the agent's TestRunSessionMetadataPrecedence."""

    def _make_run_team(self, db: InMemoryDb, **kwargs) -> Team:
        member = Agent(name="member", model=MockModel(), telemetry=False)
        return Team(id="team-1", members=[member], model=MockModel(), db=db, telemetry=False, **kwargs)

    def test_session_beats_team_on_run(self):
        db = InMemoryDb()
        _seed_team_session(db, "s1", "team-1", {"shared": "session_value", "session_only": "s"})
        team = self._make_run_team(db, metadata={"shared": "team_value", "team_only": "t"})
        out = team.run(input="hi", session_id="s1")
        assert out.metadata["shared"] == "session_value"
        assert out.metadata["team_only"] == "t"
        assert out.metadata["session_only"] == "s"

    def test_callsite_beats_session_and_team_on_run(self):
        db = InMemoryDb()
        _seed_team_session(db, "s1", "team-1", {"shared": "session_value"})
        team = self._make_run_team(db, metadata={"shared": "team_value"})
        out = team.run(input="hi", session_id="s1", metadata={"shared": "call_value", "run_only": "r"})
        assert out.metadata["shared"] == "call_value"
        assert out.metadata["run_only"] == "r"

    def test_run_does_not_mutate_team_metadata(self):
        db = InMemoryDb()
        _seed_team_session(db, "s1", "team-1", {"leak": "from_session"})
        team = self._make_run_team(db, metadata={"env": "test"})
        out = team.run(input="hi", session_id="s1")
        assert out.metadata["leak"] == "from_session"
        assert team.metadata == {"env": "test"}

    def test_session_beats_team_stays_stable_across_runs(self):
        # The session value must survive persistence: _update_metadata merges team
        # defaults as the losing layer, so the session's own value is not clobbered
        # in the record and every subsequent run resolves it identically.
        db = InMemoryDb()
        _seed_team_session(db, "s1", "team-1", {"tier": "gold"})
        team = self._make_run_team(db, metadata={"tier": "standard"})
        first = team.run(input="hi", session_id="s1").metadata["tier"]
        record = db.get_session(session_id="s1").metadata["tier"]
        second = team.run(input="hi", session_id="s1").metadata["tier"]
        assert (first, record, second) == ("gold", "gold", "gold")

    def test_continue_run_sees_session_metadata(self):
        db = InMemoryDb()
        _seed_team_session(db, "s1", "team-1", {"policy": "capture-only"})
        team = self._make_run_team(db, metadata={"env": "test"})
        run_out = team.run(input="hi", session_id="s1")
        cont = team.continue_run(run_id=run_out.run_id, session_id="s1", requirements=[])
        assert cont.metadata["policy"] == "capture-only"
        assert cont.metadata["env"] == "test"

    @pytest.mark.asyncio
    async def test_arun_sync_db_matches_async_db_path(self):
        # Unlike agent.arun, team.arun does NOT pre-read the session even with a
        # sync DB (arun_dispatch resolves options before the session id is known),
        # so session metadata does not reach the resolved options. Pinned so a
        # future change to either side is a conscious decision, not a silent drift.
        db = InMemoryDb()
        _seed_team_session(db, "s1", "team-1", {"shared": "session_value"})
        team = self._make_run_team(db, metadata={"shared": "team_value"})
        out = await team.arun(input="hi", session_id="s1", metadata={"run_only": "r"})
        assert out.metadata["shared"] == "team_value"
        assert out.metadata["run_only"] == "r"
        assert "session_value" not in out.metadata.values()
