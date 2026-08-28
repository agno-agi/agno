"""Tests for centralized run option resolution."""

import dataclasses
import time
from typing import Any, AsyncIterator, Dict, Iterator

import pytest

from agno.agent._run_options import ResolvedRunOptions, resolve_run_options
from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.session import AgentSession


def _make_agent(**kwargs) -> Agent:
    """Create a minimal Agent instance for testing."""
    return Agent(**kwargs)


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


def _seed_session(db: InMemoryDb, session_id: str, agent_id: str, metadata: Dict[str, Any]) -> None:
    """Insert a session record with the given metadata, as if written by an earlier deployment."""
    db.upsert_session(
        AgentSession(session_id=session_id, agent_id=agent_id, metadata=metadata, created_at=int(time.time()))
    )


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

    def test_dependencies_merge_callsite_over_agent(self):
        # Call-site dependencies merge with agent.dependencies (call-site keys win on conflict);
        # agent-level keys (e.g. prompt-template vars) are preserved, not clobbered.
        agent = _make_agent(dependencies={"a": 1})
        opts = resolve_run_options(agent, dependencies={"b": 2})
        assert opts.dependencies == {"a": 1, "b": 2}

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

    def test_merge_callsite_takes_precedence(self):
        # Metadata resolves like dependencies: call-site keys win on conflict.
        agent = _make_agent(metadata={"shared": "agent_value", "agent_only": "a"})
        opts = resolve_run_options(agent, metadata={"shared": "run_value", "run_only": "r"})
        assert opts.metadata["shared"] == "run_value"
        assert opts.metadata["agent_only"] == "a"
        assert opts.metadata["run_only"] == "r"

    def test_only_session(self):
        agent = _make_agent()
        opts = resolve_run_options(agent, session_metadata={"session": "value"})
        assert opts.metadata == {"session": "value"}

    def test_session_beats_agent(self):
        agent = _make_agent(metadata={"shared": "agent_value", "agent_only": "a"})
        opts = resolve_run_options(agent, session_metadata={"shared": "session_value", "session_only": "s"})
        assert opts.metadata["shared"] == "session_value"
        assert opts.metadata["agent_only"] == "a"
        assert opts.metadata["session_only"] == "s"

    def test_callsite_beats_session(self):
        agent = _make_agent()
        opts = resolve_run_options(
            agent,
            metadata={"shared": "run_value", "run_only": "r"},
            session_metadata={"shared": "session_value", "session_only": "s"},
        )
        assert opts.metadata["shared"] == "run_value"
        assert opts.metadata["session_only"] == "s"
        assert opts.metadata["run_only"] == "r"

    def test_three_layer_merge_non_conflicting_keys(self):
        agent = _make_agent(metadata={"agent_only": "a", "shared": "agent_value"})
        opts = resolve_run_options(
            agent,
            metadata={"run_only": "r", "shared": "run_value"},
            session_metadata={"session_only": "s"},
        )
        assert opts.metadata == {
            "agent_only": "a",
            "session_only": "s",
            "run_only": "r",
            "shared": "run_value",
        }

    def test_merge_does_not_mutate_callsite(self):
        # Includes a nested dict: the recursive in-place merge must never write
        # other layers' values into the caller's nested dicts.
        agent = _make_agent(metadata={"a": 1, "nested": {"agent": True}})
        callsite_meta = {"b": 2, "nested": {"call": True}}
        resolve_run_options(agent, metadata=callsite_meta)
        assert callsite_meta == {"b": 2, "nested": {"call": True}}

    def test_merge_does_not_mutate_agent_nested_dicts(self):
        # merge_dictionaries recurses in place: a shallow copy of agent.metadata
        # would let call-site values contaminate the agent's nested dicts.
        agent = _make_agent(metadata={"policy": {"read_only": True}, "flat": "agent_value"})
        opts = resolve_run_options(
            agent,
            metadata={"policy": {"read_only": False}, "flat": "run_value"},
            session_metadata={"policy": {"source": "session"}},
        )
        assert opts.metadata["policy"] == {"read_only": False, "source": "session"}
        assert agent.metadata == {"policy": {"read_only": True}, "flat": "agent_value"}

    def test_merge_does_not_mutate_session_nested_dicts(self):
        agent = _make_agent(metadata={"policy": {"read_only": True}})
        session_meta = {"policy": {"source": "session"}}
        resolve_run_options(agent, metadata={"policy": {"read_only": False}}, session_metadata=session_meta)
        assert session_meta == {"policy": {"source": "session"}}

    def test_resolved_metadata_mutation_does_not_reach_agent(self):
        agent = _make_agent(metadata={"policy": {"read_only": True}})
        opts = resolve_run_options(agent)
        opts.metadata["policy"]["read_only"] = False  # type: ignore[index]
        assert agent.metadata == {"policy": {"read_only": True}}

    def test_resolved_metadata_does_not_alias_callsite_nested_dicts(self):
        # Every layer is deep-copied, so a later mutation of the resolved metadata
        # cannot reach the caller's nested dict (a shared module-level default).
        agent = _make_agent()
        callsite = {"labels": {"team": "ops"}}
        opts = resolve_run_options(agent, metadata=callsite)
        opts.metadata["labels"]["team"] = "sre"  # type: ignore[index]
        assert callsite == {"labels": {"team": "ops"}}

    def test_resolved_metadata_does_not_alias_session_nested_dicts(self):
        agent = _make_agent()
        session_meta = {"labels": {"tenant": "acme"}}
        opts = resolve_run_options(agent, session_metadata=session_meta)
        opts.metadata["labels"]["tenant"] = "other"  # type: ignore[index]
        assert session_meta == {"labels": {"tenant": "acme"}}


class TestDependenciesMerge:
    """Call-site dependencies merge with agent.dependencies instead of replacing them.

    Regression: interfaces (Slack/WhatsApp) always pass a non-None call-site
    ``dependencies`` (channel/thread ids). The old replacement behavior discarded the
    agent's own dependencies, dropping prompt-template variables on those surfaces.
    """

    def test_both_none(self):
        agent = _make_agent()
        opts = resolve_run_options(agent)
        assert opts.dependencies is None

    def test_only_callsite(self):
        agent = _make_agent()
        opts = resolve_run_options(agent, dependencies={"run": "value"})
        assert opts.dependencies == {"run": "value"}

    def test_only_agent(self):
        agent = _make_agent(dependencies={"agent": "value"})
        opts = resolve_run_options(agent)
        assert opts.dependencies == {"agent": "value"}

    def test_merge_preserves_agent_keys(self):
        # The core bug: agent template vars must survive a call-site that only adds runtime context.
        agent = _make_agent(dependencies={"owner_name": "Ash", "caller_information": "resolver"})
        opts = resolve_run_options(agent, dependencies={"channel": "C123", "thread": "T1"})
        assert opts.dependencies == {
            "owner_name": "Ash",
            "caller_information": "resolver",
            "channel": "C123",
            "thread": "T1",
        }

    def test_merge_callsite_takes_precedence(self):
        agent = _make_agent(dependencies={"x": "agent", "agent_only": "a"})
        opts = resolve_run_options(agent, dependencies={"x": "call", "run_only": "r"})
        # call-site wins on conflict; runtime context overrides static config
        assert opts.dependencies["x"] == "call"
        assert opts.dependencies["agent_only"] == "a"
        assert opts.dependencies["run_only"] == "r"

    def test_merge_does_not_mutate_callsite(self):
        agent = _make_agent(dependencies={"a": 1})
        callsite_deps = {"b": 2}
        resolve_run_options(agent, dependencies=callsite_deps)
        assert callsite_deps == {"b": 2}

    def test_merge_does_not_mutate_agent(self):
        agent = _make_agent(dependencies={"a": 1})
        resolve_run_options(agent, dependencies={"b": 2})
        assert agent.dependencies == {"a": 1}


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


# ---------------------------------------------------------------------------
# Session metadata precedence on the full run() path
# ---------------------------------------------------------------------------


class TestRunSessionMetadataPrecedence:
    def test_session_beats_agent_on_run(self):
        db = InMemoryDb()
        _seed_session(db, "s1", "agent-1", {"shared": "session_value", "session_only": "s"})
        agent = Agent(id="agent-1", model=MockModel(), db=db, metadata={"shared": "agent_value", "agent_only": "a"})
        out = agent.run("hi", session_id="s1")
        assert out.metadata["shared"] == "session_value"
        assert out.metadata["agent_only"] == "a"
        assert out.metadata["session_only"] == "s"

    def test_callsite_beats_session_and_agent_on_run(self):
        db = InMemoryDb()
        _seed_session(db, "s1", "agent-1", {"shared": "session_value"})
        agent = Agent(id="agent-1", model=MockModel(), db=db, metadata={"shared": "agent_value"})
        out = agent.run("hi", session_id="s1", metadata={"shared": "call_value", "run_only": "r"})
        assert out.metadata["shared"] == "call_value"
        assert out.metadata["run_only"] == "r"

    @pytest.mark.asyncio
    async def test_arun_sync_db_session_metadata_visible(self):
        # arun_dispatch pre-reads the session when the DB is sync
        db = InMemoryDb()
        _seed_session(db, "s1", "agent-1", {"shared": "session_value"})
        agent = Agent(id="agent-1", model=MockModel(), db=db, metadata={"shared": "agent_value"})
        out = await agent.arun("hi", session_id="s1", metadata={"run_only": "r"})
        assert out.metadata["shared"] == "session_value"
        assert out.metadata["run_only"] == "r"

    def test_session_beats_agent_stays_stable_across_runs(self):
        # The session value must survive persistence: update_metadata merges agent
        # defaults as the losing layer, so the session's own value is not clobbered
        # in the record and every subsequent run resolves it identically.
        db = InMemoryDb()
        _seed_session(db, "s1", "agent-1", {"tier": "gold"})
        agent = Agent(id="agent-1", model=MockModel(), db=db, metadata={"tier": "standard"})
        first = agent.run("hi", session_id="s1").metadata["tier"]
        record = db.get_session(session_id="s1").metadata["tier"]
        second = agent.run("hi", session_id="s1").metadata["tier"]
        assert (first, record, second) == ("gold", "gold", "gold")

    def test_continue_run_sees_session_metadata(self):
        # continue_run resolves options through the same session_metadata layer as run.
        db = InMemoryDb()
        _seed_session(db, "s1", "agent-1", {"policy": "capture-only"})
        agent = Agent(id="agent-1", model=MockModel(), db=db, metadata={"env": "test"})
        run_out = agent.run("hi", session_id="s1")
        cont = agent.continue_run(run_id=run_out.run_id, session_id="s1", requirements=[])
        assert cont.metadata["policy"] == "capture-only"
        assert cont.metadata["env"] == "test"


# ---------------------------------------------------------------------------
# Singleton isolation: runs never mutate the shared Agent instance
# ---------------------------------------------------------------------------


class TestSingletonIsolation:
    def test_no_bleed_across_sessions(self):
        db = InMemoryDb()
        _seed_session(db, "session-a", "agent-1", {"leak": "from_a"})
        agent = Agent(id="agent-1", model=MockModel(), db=db, metadata={"env": "test"}, cache_session=True)

        out_a = agent.run("hi", session_id="session-a")
        assert out_a.metadata["leak"] == "from_a"
        assert agent.metadata == {"env": "test"}
        assert agent.metadata is not agent._cached_session.metadata

        out_b = agent.run("hi", session_id="session-b")
        assert "leak" not in (out_b.metadata or {})
        assert agent.metadata == {"env": "test"}
        assert agent.metadata is not agent._cached_session.metadata

        # Session B's persisted record carries agent defaults only, no session A values
        session_b = db.get_session(session_id="session-b")
        assert session_b.metadata == {"env": "test"}

    def test_agent_metadata_not_aliased_to_session(self):
        from agno.agent._storage import read_or_create_session, update_metadata

        db = InMemoryDb()
        _seed_session(db, "session-a", "agent-1", {"k": "v"})
        agent = Agent(id="agent-1", model=MockModel(), db=db, metadata={"env": "test"})
        session = read_or_create_session(agent, session_id="session-a")
        update_metadata(agent, session=session)
        assert agent.metadata is not session.metadata
        assert agent.metadata == {"env": "test"}
        # Session side: agent metadata fills keys the session does not set
        assert session.metadata == {"k": "v", "env": "test"}

    def test_new_session_seeding_not_aliased(self):
        from agno.agent._storage import read_or_create_session

        agent = Agent(id="agent-1", model=MockModel(), db=InMemoryDb(), metadata={"env": "test"})
        session = read_or_create_session(agent, session_id="fresh")
        assert session.metadata == {"env": "test"}
        assert session.metadata is not agent.metadata

    @pytest.mark.asyncio
    async def test_new_session_seeding_not_aliased_async(self):
        from agno.agent._storage import aread_or_create_session

        agent = Agent(id="agent-1", model=MockModel(), db=InMemoryDb(), metadata={"env": "test"})
        session = await aread_or_create_session(agent, session_id="fresh")
        assert session.metadata == {"env": "test"}
        assert session.metadata is not agent.metadata
