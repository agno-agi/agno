"""Regression tests: with ``cache_session=True`` the cached session must not survive
a reassignment of ``agent.db``.

Bug: an agent with ``cache_session=True`` and a fixed ``session_id`` kept serving the
same cached session object after ``agent.db`` was pointed at a fresh database. The
cached session accumulated every prior conversation's runs, so history leaked across
databases and each turn re-serialized an ever-growing session into whichever db was
current (measured as ~31ms -> ~272ms per conversation over 11 conversations).

The cache is tagged with the db it was loaded from and is dropped when the tag no
longer matches ``agent.db``. Switching ``session_id`` was already handled by the
read-time session_id comparison; those semantics are pinned here too.
"""

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse


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


def _make_agent(**kwargs) -> Agent:
    return Agent(model=MockModel(), cache_session=True, add_history_to_context=True, **kwargs)


def _user_message_count(response) -> int:
    return len([m for m in response.messages if m.role == "user"])


class TestCacheHitWithinOneDb:
    def test_second_run_reuses_cached_session_object(self):
        agent = _make_agent(db=InMemoryDb())

        agent.run("first", session_id="conv")
        first_cached = agent.cached_session
        assert first_cached is not None
        assert len(first_cached.runs) == 1

        agent.run("second", session_id="conv")
        assert agent.cached_session is first_cached
        assert len(first_cached.runs) == 2

    def test_get_session_serves_cached_object(self):
        agent = _make_agent(db=InMemoryDb())

        agent.run("first", session_id="conv")
        cached = agent.cached_session
        assert agent.get_session(session_id="conv") is cached


class TestDbSwapInvalidation:
    def test_db_swap_drops_cached_session(self):
        agent = _make_agent(db=InMemoryDb())
        agent.run("first", session_id="conv")
        old_cached = agent.cached_session
        assert old_cached is not None

        agent.db = InMemoryDb()
        agent.run("second", session_id="conv")

        new_cached = agent.cached_session
        assert new_cached is not None
        assert new_cached is not old_cached
        assert len(new_cached.runs) == 1
        # The old cached session keeps only its own conversation
        assert len(old_cached.runs) == 1

    def test_history_does_not_leak_across_dbs(self):
        agent = _make_agent(db=InMemoryDb())
        for _ in range(3):
            agent.run("hi", session_id="conv")

        agent.db = InMemoryDb()
        response = agent.run("hi", session_id="conv")

        # First turn against the fresh db: no history from the old db's conversation
        assert _user_message_count(response) == 1

    def test_no_cross_db_leakage_of_runs(self):
        db1 = InMemoryDb()
        agent = _make_agent(db=db1)
        agent.run("first", session_id="conv")

        db2 = InMemoryDb()
        agent.db = db2
        agent.run("second", session_id="conv")

        # Each db holds exactly the runs produced while it was assigned
        assert len(db1.get_runs(session_id="conv")) == 1
        assert len(db2.get_runs(session_id="conv")) == 1

        # A fresh read from each db yields that db's conversation only
        agent.db = db1
        session_from_db1 = agent.get_session(session_id="conv")
        assert session_from_db1 is not None
        assert len(session_from_db1.runs) == 1
        assert session_from_db1.runs[0].messages is not None

    def test_swap_back_to_original_db_reloads_from_that_db(self):
        db1 = InMemoryDb()
        agent = _make_agent(db=db1)
        agent.run("first", session_id="conv")

        agent.db = InMemoryDb()
        agent.run("second", session_id="conv")

        agent.db = db1
        agent.run("third", session_id="conv")
        cached = agent.cached_session
        assert cached is not None
        # db1's conversation had 1 run; the new turn makes 2. The interleaved
        # db2 conversation must not appear.
        assert len(cached.runs) == 2

    @pytest.mark.asyncio
    async def test_db_swap_drops_cached_session_async(self):
        agent = _make_agent(db=InMemoryDb())
        await agent.arun("first", session_id="conv")
        old_cached = agent.cached_session
        assert old_cached is not None

        agent.db = InMemoryDb()
        response = await agent.arun("second", session_id="conv")

        new_cached = agent.cached_session
        assert new_cached is not None
        assert new_cached is not old_cached
        assert len(new_cached.runs) == 1
        assert _user_message_count(response) == 1


class TestSessionIdSwitch:
    def test_session_id_switch_does_not_serve_stale_cache(self):
        agent = _make_agent(db=InMemoryDb())

        agent.run("first", session_id="conv-a")
        cached_a = agent.cached_session
        assert cached_a is not None

        agent.run("second", session_id="conv-b")
        cached_b = agent.cached_session
        assert cached_b is not None
        assert cached_b is not cached_a
        assert cached_b.session_id == "conv-b"
        assert len(cached_b.runs) == 1

    def test_runs_do_not_leak_across_session_ids(self):
        agent = _make_agent(db=InMemoryDb())

        agent.run("first", session_id="conv-a")
        agent.run("second", session_id="conv-b")
        response = agent.run("third", session_id="conv-a")

        # conv-a's second turn sees only conv-a's history
        assert _user_message_count(response) == 2
        cached = agent.cached_session
        assert cached is not None
        assert cached.session_id == "conv-a"
        assert len(cached.runs) == 2
