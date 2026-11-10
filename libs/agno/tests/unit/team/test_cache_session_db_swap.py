"""Regression tests: with ``cache_session=True`` the cached session must not survive
a reassignment of ``team.db``.

Sibling of ``tests/unit/agent/test_cache_session_db_swap.py`` — the same hazard exists
on Team: a cached TeamSession kept being served (and growing) after ``team.db`` was
pointed at a fresh database, leaking runs across databases.
"""

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.team.team import Team


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


def _make_team(**kwargs) -> Team:
    return Team(
        name="test-team",
        members=[],
        model=MockModel(),
        cache_session=True,
        add_history_to_context=True,
        **kwargs,
    )


class TestTeamCacheHitWithinOneDb:
    def test_second_run_reuses_cached_session_object(self):
        team = _make_team(db=InMemoryDb())

        team.run("first", session_id="conv")
        first_cached = team.cached_session
        assert first_cached is not None
        assert len(first_cached.runs) == 1

        team.run("second", session_id="conv")
        assert team.cached_session is first_cached
        assert len(first_cached.runs) == 2


class TestTeamDbSwapInvalidation:
    def test_db_swap_drops_cached_session(self):
        team = _make_team(db=InMemoryDb())
        team.run("first", session_id="conv")
        old_cached = team.cached_session
        assert old_cached is not None

        team.db = InMemoryDb()
        team.run("second", session_id="conv")

        new_cached = team.cached_session
        assert new_cached is not None
        assert new_cached is not old_cached
        assert len(new_cached.runs) == 1
        # The old cached session keeps only its own conversation
        assert len(old_cached.runs) == 1

    def test_no_cross_db_leakage_of_runs(self):
        db1 = InMemoryDb()
        team = _make_team(db=db1)
        team.run("first", session_id="conv")

        db2 = InMemoryDb()
        team.db = db2
        team.run("second", session_id="conv")

        # Each db holds exactly the runs produced while it was assigned
        assert len(db1.get_runs(session_id="conv")) == 1
        assert len(db2.get_runs(session_id="conv")) == 1

        # A fresh read from each db yields that db's conversation only
        team.db = db1
        session_from_db1 = team.get_session(session_id="conv")
        assert session_from_db1 is not None
        assert len(session_from_db1.runs) == 1

    @pytest.mark.asyncio
    async def test_db_swap_drops_cached_session_async(self):
        team = _make_team(db=InMemoryDb())
        await team.arun("first", session_id="conv")
        old_cached = team.cached_session
        assert old_cached is not None

        team.db = InMemoryDb()
        await team.arun("second", session_id="conv")

        new_cached = team.cached_session
        assert new_cached is not None
        assert new_cached is not old_cached
        assert len(new_cached.runs) == 1


class TestTeamSessionIdSwitch:
    def test_session_id_switch_does_not_serve_stale_cache(self):
        team = _make_team(db=InMemoryDb())

        team.run("first", session_id="conv-a")
        cached_a = team.cached_session
        assert cached_a is not None

        team.run("second", session_id="conv-b")
        cached_b = team.cached_session
        assert cached_b is not None
        assert cached_b is not cached_a
        assert cached_b.session_id == "conv-b"
        assert len(cached_b.runs) == 1
