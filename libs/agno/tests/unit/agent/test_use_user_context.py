"""Tests for the per-run ``use_user_context`` flag (incognito runs).

A run with ``use_user_context=False`` must not touch anything keyed to the user,
on either side of the run: no memories injected, no memories written, no
user-keyed tools exposed, and no user-scoped learning stores consulted. Every
other kind of context -- session history, session summaries, namespace-scoped
learnings -- is unaffected.
"""

from typing import Any, AsyncIterator, Iterator, List, Optional

import pytest

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.db.in_memory import InMemoryDb
from agno.memory.manager import MemoryManager
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.base import RunContext
from agno.session.agent import AgentSession


class MockModel(Model):
    """Offline model that records the system message each run was given."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self.seen_system_messages: List[str] = []
        self._mock_response = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def _record(self, *args, **kwargs) -> None:
        messages = kwargs.get("messages") or (args[0] if args else None)
        for message in messages or []:
            if getattr(message, "role", None) == "system":
                self.seen_system_messages.append(str(message.content or ""))

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
        self._record(*args, **kwargs)
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        self._record(*args, **kwargs)
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        self._record(*args, **kwargs)
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        self._record(*args, **kwargs)
        yield self._mock_response

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


class RecordingMemoryManager(MemoryManager):
    """Memory manager that reports one memory and records every write attempt."""

    def __init__(self, db):
        super().__init__(db=db)
        self.write_calls = 0

    def get_user_memories(self, user_id: Optional[str] = None, **kwargs):
        from agno.memory import UserMemory

        return [UserMemory(memory_id="m1", memory="The user is allergic to peanuts", user_id=user_id)]

    async def aget_user_memories(self, user_id: Optional[str] = None, **kwargs):
        return self.get_user_memories(user_id=user_id)

    def create_user_memories(self, *args, **kwargs):
        self.write_calls += 1
        return []

    async def acreate_user_memories(self, *args, **kwargs):
        self.write_calls += 1
        return []


MEMORY_MARKER = "allergic to peanuts"
DESCRIPTION = "You are a careful assistant."


def _make_agent(db: InMemoryDb, model: MockModel, **kwargs) -> Agent:
    return Agent(
        id="incognito-test-agent",
        model=model,
        db=db,
        description=DESCRIPTION,
        memory_manager=RecordingMemoryManager(db=db),
        update_memory_on_run=True,
        add_memories_to_context=True,
        **kwargs,
    )


class TestRunContextDefault:
    def test_defaults_to_using_user_context(self):
        assert RunContext(run_id="r1", session_id="s1").use_user_context is True


class TestMemoryRecall:
    def test_memories_injected_by_default(self):
        model = MockModel()
        agent = _make_agent(InMemoryDb(), model)
        agent.run("hello", user_id="u1", session_id="s1")
        assert any(MEMORY_MARKER in message for message in model.seen_system_messages)

    def test_memories_withheld_when_incognito(self):
        model = MockModel()
        agent = _make_agent(InMemoryDb(), model)
        agent.run("hello", user_id="u1", session_id="s1", use_user_context=False)
        assert any(DESCRIPTION in message for message in model.seen_system_messages)
        assert not any(MEMORY_MARKER in message for message in model.seen_system_messages)

    def test_incognito_omits_the_no_memories_fallback_too(self):
        """The fallback still advertises the capability, so it must be skipped as well."""
        model = MockModel()
        agent = _make_agent(InMemoryDb(), model)
        agent.run("hello", user_id="u1", session_id="s1", use_user_context=False)
        assert not any("retain memories from previous interactions" in m for m in model.seen_system_messages)

    @pytest.mark.asyncio
    async def test_memories_withheld_when_incognito_async(self):
        model = MockModel()
        agent = _make_agent(InMemoryDb(), model)
        await agent.arun("hello", user_id="u1", session_id="s1", use_user_context=False)
        assert any(DESCRIPTION in message for message in model.seen_system_messages)
        assert not any(MEMORY_MARKER in message for message in model.seen_system_messages)


class TestMemoryWrites:
    def test_memories_written_by_default(self):
        agent = _make_agent(InMemoryDb(), MockModel())
        agent.run("I moved to Berlin", user_id="u1", session_id="s1")
        assert agent.memory_manager.write_calls > 0  # type: ignore[union-attr]

    def test_no_memories_written_when_incognito(self):
        agent = _make_agent(InMemoryDb(), MockModel())
        agent.run("I moved to Berlin", user_id="u1", session_id="s1", use_user_context=False)
        assert agent.memory_manager.write_calls == 0  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_no_memories_written_when_incognito_async(self):
        agent = _make_agent(InMemoryDb(), MockModel())
        await agent.arun("I moved to Berlin", user_id="u1", session_id="s1", use_user_context=False)
        assert agent.memory_manager.write_calls == 0  # type: ignore[union-attr]


class TestUserKeyedTools:
    def _tool_names(self, agent: Agent, use_user_context: bool) -> List[str]:
        from agno.agent import _tools
        from agno.run.agent import RunOutput

        run_context = RunContext(run_id="r1", session_id="s1", user_id="u1", use_user_context=use_user_context)
        tools = _tools.get_tools(
            agent,
            run_response=RunOutput(run_id="r1", session_id="s1"),
            run_context=run_context,
            session=AgentSession(session_id="s1", agent_id=agent.id),
            user_id="u1",
        )
        return [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]

    def test_past_session_tools_present_by_default(self):
        agent = _make_agent(InMemoryDb(), MockModel(), search_past_sessions=True)
        agent.initialize_agent()
        assert "search_past_sessions" in self._tool_names(agent, use_user_context=True)

    def test_past_session_tools_withheld_when_incognito(self):
        agent = _make_agent(InMemoryDb(), MockModel(), search_past_sessions=True)
        agent.initialize_agent()
        names = self._tool_names(agent, use_user_context=False)
        assert "search_past_sessions" not in names
        assert "read_past_session" not in names

    def test_agentic_memory_tool_withheld_when_incognito(self):
        agent = _make_agent(InMemoryDb(), MockModel(), enable_agentic_memory=True)
        agent.initialize_agent()
        assert "update_user_memory" in self._tool_names(agent, use_user_context=True)
        assert "update_user_memory" not in self._tool_names(agent, use_user_context=False)


class TestPrivacyOptOutOnlyTightens:
    def test_call_site_flag_cannot_be_widened_by_run_context(self):
        """An incognito call-site argument wins over a permissive run_context."""
        model = MockModel()
        agent = _make_agent(InMemoryDb(), model)
        run_context = RunContext(run_id="r1", session_id="s1", user_id="u1", use_user_context=True)
        agent.run("hello", user_id="u1", session_id="s1", run_context=run_context, use_user_context=False)
        assert run_context.use_user_context is False
        assert not any(MEMORY_MARKER in message for message in model.seen_system_messages)

    def test_incognito_run_context_survives_a_permissive_call_site(self):
        """A run_context that arrived incognito is not re-granted user context."""
        model = MockModel()
        agent = _make_agent(InMemoryDb(), model)
        run_context = RunContext(run_id="r1", session_id="s1", user_id="u1", use_user_context=False)
        agent.run("hello", user_id="u1", session_id="s1", run_context=run_context)
        assert run_context.use_user_context is False
        assert not any(MEMORY_MARKER in message for message in model.seen_system_messages)


class TestSessionIsUnaffected:
    def test_incognito_run_is_still_saved_to_the_session(self):
        """use_user_context governs user-keyed recall only -- the run still persists."""
        db = InMemoryDb()
        agent = _make_agent(db, MockModel())
        agent.run("hello", user_id="u1", session_id="s1", use_user_context=False)
        session = db.get_session(session_id="s1", session_type=SessionType.AGENT)
        assert session is not None
        assert len(session.runs or []) == 1
