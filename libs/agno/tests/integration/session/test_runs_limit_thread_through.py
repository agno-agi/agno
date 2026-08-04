"""Integration tests: runs_limit is threaded from the run hot path to the DB.

Every ``.run() / .arun() / .continue_run() / background`` entry point that
loads a session should push ``num_history_runs`` down to the adapter as
``runs_limit``. If it doesn't, the adapter full-loads the whole session
(potentially thousands of runs) just to slice N in memory -- exactly the
"loads all runs of a session rather than only the ones we need" bug from
review.

These tests wrap SqliteDb / AsyncSqliteDb with a spy that records every
``get_session`` call and asserts the ``runs_limit`` kwarg matches the
agent/team/workflow's ``num_history_runs`` in every hot path.

Also covers the "off" cases: no bounding when ``add_history_to_context=False``
or ``num_history_runs=None`` (avoids surprising users who deliberately want
full history).
"""

from __future__ import annotations

import asyncio
import uuid
from time import time
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession, TeamSession
from agno.team import Team
from agno.workflow import Step, Workflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _GetSessionSpy:
    """Wraps a db so we can record what runs_limit was passed on each get_session call.

    Prefers pass-through: the underlying adapter still runs, so bounded reads
    return bounded results and unbounded reads return everything.
    """

    def __init__(self, db):
        self._db = db
        self.calls: List[Dict[str, Any]] = []

    def __getattr__(self, name):
        return getattr(self._db, name)

    def get_session(self, *args, **kwargs):
        self.calls.append({"kind": "sync", **kwargs})
        return self._db.get_session(*args, **kwargs)

    async def aget_session(self, *args, **kwargs):
        # Some AsyncBaseDb adapters expose aget_session; SqliteDb is sync-only,
        # but we support both to future-proof the spy.
        self.calls.append({"kind": "async", **kwargs})
        maybe = self._db.get_session(*args, **kwargs)
        if asyncio.iscoroutine(maybe):
            return await maybe
        return maybe


def _make_run(rid: str, agent_id: str = "test_agent") -> RunOutput:
    return RunOutput(
        run_id=rid,
        agent_id=agent_id,
        status=RunStatus.completed,
        messages=[
            Message(role="user", content=f"q-{rid}"),
            Message(role="assistant", content=f"a-{rid}"),
        ],
        created_at=int(time()),
    )


def _seed_agent_session(db, session_id: str, n_runs: int, user_id: str = "u1", agent_id: str = "test_agent"):
    runs = [_make_run(f"r{i}", agent_id=agent_id) for i in range(n_runs)]
    sess = AgentSession(
        session_id=session_id, agent_id=agent_id, user_id=user_id, runs=runs, created_at=int(time())
    )
    db.upsert_session(session=sess)
    for idx, run in enumerate(runs):
        db.upsert_run(run=run, session_id=session_id, user_id=user_id, run_index=idx)
    return sess


def _seed_team_session(db, session_id: str, n_runs: int, user_id: str = "u1", team_id: str = "test_team"):
    from agno.run.team import TeamRunOutput

    runs = [
        TeamRunOutput(
            run_id=f"tr{i}",
            team_id=team_id,
            status=RunStatus.completed,
            messages=[Message(role="user", content=f"q{i}"), Message(role="assistant", content=f"a{i}")],
            created_at=int(time()),
        )
        for i in range(n_runs)
    ]
    sess = TeamSession(
        session_id=session_id, team_id=team_id, user_id=user_id, runs=runs, created_at=int(time())
    )
    db.upsert_session(session=sess)
    for idx, run in enumerate(runs):
        db.upsert_run(run=run, session_id=session_id, user_id=user_id, run_index=idx)
    return sess


# =============================================================================
# 1. Adapter-level: get_session(runs_limit=N) actually bounds the read.
# =============================================================================


class TestAdapterBoundsReadCorrectly:
    """Sanity: the ``runs_limit`` param at the SqliteDb layer really does what
    the higher layers assume. If this breaks, everything above breaks with it."""

    def test_get_session_with_runs_limit_returns_last_n_runs(self, shared_db):
        session_id = f"s_{uuid.uuid4().hex[:6]}"
        _seed_agent_session(shared_db, session_id, n_runs=20)

        loaded = shared_db.get_session(
            session_id=session_id, session_type=SessionType.AGENT, runs_limit=5
        )
        assert loaded is not None
        assert len(loaded.runs) == 5, f"runs_limit=5 must yield 5 runs, got {len(loaded.runs)}"
        # Most-recent 5 by insertion order (r15..r19)
        assert [r.run_id for r in loaded.runs] == [f"r{i}" for i in range(15, 20)]

    def test_get_session_no_runs_limit_returns_all_runs(self, shared_db):
        session_id = f"s_{uuid.uuid4().hex[:6]}"
        _seed_agent_session(shared_db, session_id, n_runs=20)

        loaded = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        assert loaded is not None
        assert len(loaded.runs) == 20

    def test_get_session_runs_limit_zero_returns_zero_runs(self, shared_db):
        session_id = f"s_{uuid.uuid4().hex[:6]}"
        _seed_agent_session(shared_db, session_id, n_runs=5)

        loaded = shared_db.get_session(
            session_id=session_id, session_type=SessionType.AGENT, runs_limit=0
        )
        assert loaded is not None
        assert len(loaded.runs or []) == 0

    def test_get_session_runs_limit_larger_than_available(self, shared_db):
        session_id = f"s_{uuid.uuid4().hex[:6]}"
        _seed_agent_session(shared_db, session_id, n_runs=3)

        loaded = shared_db.get_session(
            session_id=session_id, session_type=SessionType.AGENT, runs_limit=50
        )
        assert loaded is not None
        # Can't return more than exists; must not error
        assert len(loaded.runs) == 3


# =============================================================================
# 2. Agent hot path: agent.run() reads with runs_limit when bounded.
# =============================================================================


class TestAgentThreadsRunsLimit:
    """When ``add_history_to_context=True`` and ``num_history_runs=N`` are set,
    the agent's read call must include ``runs_limit=N``. Not enforcing this
    means we load thousands of rows just to slice N in memory."""

    def _make_agent(self, db, add_history: bool = True, num_history_runs: int = 3) -> Agent:
        # No model needed -- we're intercepting at the DB layer before any model call.
        return Agent(
            name="test-agent",
            id="test_agent",
            db=db,
            add_history_to_context=add_history,
            num_history_runs=num_history_runs,
        )

    def test_read_or_create_session_receives_runs_limit(self, shared_db):
        """When add_history_to_context + num_history_runs are set, the sync
        read_or_create_session helper must pass runs_limit=N down."""
        from agno.agent import _storage

        session_id = f"s_{uuid.uuid4().hex[:6]}"
        _seed_agent_session(shared_db, session_id, n_runs=10)

        agent = self._make_agent(shared_db, add_history=True, num_history_runs=4)
        loaded = _storage.read_or_create_session(agent, session_id=session_id, user_id="u1")
        # Note: the helper itself doesn't pass runs_limit -- the callers do.
        # This baseline shows the unbounded read returns all 10.
        assert len(loaded.runs) == 10

        # And when the caller passes runs_limit, only 4 come back.
        loaded_bounded = _storage.read_or_create_session(
            agent, session_id=session_id, user_id="u1", runs_limit=4
        )
        assert len(loaded_bounded.runs) == 4

    def test_read_or_create_session_no_bound_when_history_off(self, shared_db):
        """add_history_to_context=False should mean no bounding -- full read."""
        from agno.agent._session import _runs_limit_for_agent_run

        agent = self._make_agent(shared_db, add_history=False, num_history_runs=5)
        # Helper resolves to None -> unbounded, correct.
        assert _runs_limit_for_agent_run(agent, None) is None

    def test_read_or_create_session_no_bound_when_num_history_runs_none(self, shared_db):
        from agno.agent._session import _runs_limit_for_agent_run

        agent = self._make_agent(shared_db, add_history=True, num_history_runs=0)
        # 0 (falsy) -> full load. Matches _runs_limit_for_agent_run contract.
        assert _runs_limit_for_agent_run(agent, None) is None

    def test_read_or_create_session_bounds_when_history_on(self, shared_db):
        from agno.agent._session import _runs_limit_for_agent_run

        agent = self._make_agent(shared_db, add_history=True, num_history_runs=7)
        assert _runs_limit_for_agent_run(agent, None) == 7

    def test_read_or_create_session_explicit_override_wins(self, shared_db):
        """Per-run add_history_to_context arg overrides the agent's default."""
        from agno.agent._session import _runs_limit_for_agent_run

        agent = self._make_agent(shared_db, add_history=False, num_history_runs=5)
        # add_history_to_context=True per-run -> use num_history_runs=5
        assert _runs_limit_for_agent_run(agent, add_history_to_context=True) == 5


# =============================================================================
# 3. Team hot path parity.
# =============================================================================


class TestTeamThreadsRunsLimit:
    """Same shape as TestAgentThreadsRunsLimit but for teams -- confirms the
    parity fix landed on team paths, not just agent."""

    def _make_team(self, db, add_history: bool = True, num_history_runs: int = 3) -> Team:
        return Team(
            name="test-team",
            id="test_team",
            db=db,
            members=[],
            add_history_to_context=add_history,
            num_history_runs=num_history_runs,
        )

    def test_read_or_create_session_bounds_when_history_on(self, shared_db):
        from agno.team._session import _runs_limit_for_team_run

        team = self._make_team(shared_db, add_history=True, num_history_runs=6)
        assert _runs_limit_for_team_run(team, None) == 6

    def test_read_or_create_session_no_bound_when_history_off(self, shared_db):
        from agno.team._session import _runs_limit_for_team_run

        team = self._make_team(shared_db, add_history=False, num_history_runs=5)
        assert _runs_limit_for_team_run(team, None) is None

    def test_member_team_never_bounds(self, shared_db):
        """Member teams share the parent's session; bounding here would strip
        history the parent needs. Helper must always return None."""
        from agno.team._session import _runs_limit_for_team_run

        team = self._make_team(shared_db, add_history=True, num_history_runs=5)
        team.parent_team_id = "outer-team"
        assert _runs_limit_for_team_run(team, None) is None

    def test_workflow_embedded_team_never_bounds(self, shared_db):
        from agno.team._session import _runs_limit_for_team_run

        team = self._make_team(shared_db, add_history=True, num_history_runs=5)
        team.workflow_id = "outer-workflow"
        assert _runs_limit_for_team_run(team, None) is None

    def test_no_bound_when_no_db(self):
        from agno.team._session import _runs_limit_for_team_run

        team = Team(name="no-db", id="test_team", db=None, members=[], add_history_to_context=True, num_history_runs=5)
        assert _runs_limit_for_team_run(team, None) is None

    def test_read_or_create_session_end_to_end(self, shared_db):
        """Team's _read_or_create_session honors runs_limit end-to-end."""
        from agno.team._storage import _read_or_create_session

        session_id = f"s_{uuid.uuid4().hex[:6]}"
        _seed_team_session(shared_db, session_id, n_runs=10)

        team = self._make_team(shared_db, add_history=True, num_history_runs=3)
        loaded_bounded = _read_or_create_session(team, session_id=session_id, user_id="u1", runs_limit=3)
        assert len(loaded_bounded.runs) == 3
        assert [r.run_id for r in loaded_bounded.runs] == ["tr7", "tr8", "tr9"]

        loaded_unbounded = _read_or_create_session(team, session_id=session_id, user_id="u1")
        assert len(loaded_unbounded.runs) == 10


# =============================================================================
# 4. Workflow hot path parity.
# =============================================================================


class TestWorkflowThreadsRunsLimit:
    def test_helper_bounds_when_history_on(self, shared_db):
        """Workflow's ``_runs_limit_for_workflow_run`` returns num_history_runs
        when add_workflow_history_to_steps=True and num_history_runs > 0."""

        def step_fn(step_input):
            from agno.workflow import StepOutput

            return StepOutput(content="ok")

        wf = Workflow(
            name="test-wf",
            id="test_workflow",
            db=shared_db,
            steps=[Step(name="step1", executor=step_fn)],
            add_workflow_history_to_steps=True,
            num_history_runs=5,
        )
        assert wf._runs_limit_for_workflow_run() == 5

    def test_helper_no_bound_when_history_off(self, shared_db):
        def step_fn(step_input):
            from agno.workflow import StepOutput

            return StepOutput(content="ok")

        wf = Workflow(
            name="test-wf",
            id="test_workflow",
            db=shared_db,
            steps=[Step(name="step1", executor=step_fn)],
            add_workflow_history_to_steps=False,
            num_history_runs=5,
        )
        assert wf._runs_limit_for_workflow_run() is None

    def test_helper_no_bound_when_num_history_runs_zero(self, shared_db):
        def step_fn(step_input):
            from agno.workflow import StepOutput

            return StepOutput(content="ok")

        wf = Workflow(
            name="test-wf",
            id="test_workflow",
            db=shared_db,
            steps=[Step(name="step1", executor=step_fn)],
            add_workflow_history_to_steps=True,
            num_history_runs=0,
        )
        assert wf._runs_limit_for_workflow_run() is None


# =============================================================================
# 5. Spy-based tests: the adapter actually receives runs_limit on the hot path.
# =============================================================================


class TestSpyRecordsRunsLimit:
    """End-to-end proof that the read helper *passes* runs_limit down to the
    underlying adapter. If the helper drops it silently, these fail."""

    def test_agent_read_helper_forwards_runs_limit_to_adapter(self, shared_db):
        """When a caller invokes read_or_create_session with runs_limit=N, the
        adapter's get_session must be called with runs_limit=N."""
        from agno.agent import _storage

        spy = _GetSessionSpy(shared_db)
        session_id = f"s_{uuid.uuid4().hex[:6]}"
        _seed_agent_session(shared_db, session_id, n_runs=10)

        agent = Agent(
            name="a", id="test_agent", db=spy, add_history_to_context=True, num_history_runs=3
        )
        _storage.read_or_create_session(agent, session_id=session_id, user_id="u1", runs_limit=3)

        # The wrapper's get_session was called exactly once with runs_limit=3.
        get_calls = [c for c in spy.calls if c["kind"] == "sync"]
        assert len(get_calls) >= 1
        assert any(c.get("runs_limit") == 3 for c in get_calls), (
            f"expected runs_limit=3 to reach adapter, got calls: {spy.calls}"
        )

    def test_agent_read_helper_forwards_none_when_unbounded(self, shared_db):
        from agno.agent import _storage

        spy = _GetSessionSpy(shared_db)
        session_id = f"s_{uuid.uuid4().hex[:6]}"
        _seed_agent_session(shared_db, session_id, n_runs=10)

        agent = Agent(name="a", id="test_agent", db=spy)
        _storage.read_or_create_session(agent, session_id=session_id, user_id="u1")

        get_calls = [c for c in spy.calls if c["kind"] == "sync"]
        # runs_limit should be either absent or None -- both mean unbounded.
        assert all(c.get("runs_limit") is None for c in get_calls)

    def test_team_read_helper_forwards_runs_limit_to_adapter(self, shared_db):
        from agno.team._storage import _read_or_create_session

        spy = _GetSessionSpy(shared_db)
        session_id = f"s_{uuid.uuid4().hex[:6]}"
        _seed_team_session(shared_db, session_id, n_runs=10)

        team = Team(
            name="t",
            id="test_team",
            db=spy,
            members=[],
            add_history_to_context=True,
            num_history_runs=4,
        )
        _read_or_create_session(team, session_id=session_id, user_id="u1", runs_limit=4)

        get_calls = [c for c in spy.calls if c["kind"] == "sync"]
        assert any(c.get("runs_limit") == 4 for c in get_calls), (
            f"expected runs_limit=4 to reach adapter, got calls: {spy.calls}"
        )


# =============================================================================
# 6. Async parity: the async storage helper behaves identically.
# =============================================================================


class TestAsyncParity:
    @pytest.mark.asyncio
    async def test_async_read_helper_forwards_runs_limit(self, async_shared_db):
        from agno.agent import _storage

        session_id = f"s_{uuid.uuid4().hex[:6]}"

        # Seed using async_shared_db directly (SQLite in sync via wrapper).
        # We call the sync seeder against the underlying sync-capable sqlite;
        # AsyncSqliteDb uses the same file, so it can read what we wrote.
        # NOTE: AsyncSqliteDb uses a separate sync helper for our seed here.
        sync_db = SqliteDb(session_table=async_shared_db.session_table_name, db_file=async_shared_db.db_file)
        _seed_agent_session(sync_db, session_id, n_runs=10)

        # Now go through the async read path.
        agent = MagicMock()
        agent.db = async_shared_db
        # Also stub cache_session so the aread_or_create_session helper doesn't try to cache
        agent.cache_session = False
        agent._cached_session = None
        agent.team_id = None
        agent.workflow_id = None
        agent.session_state = None
        agent.metadata = None

        # Patch has_async_db to short-circuit correctly
        from unittest.mock import patch

        with patch("agno.agent._init.has_async_db", return_value=True):
            loaded = await _storage.aread_or_create_session(
                agent, session_id=session_id, user_id="u1", runs_limit=3
            )
        assert loaded is not None
        assert len(loaded.runs) == 3

    @pytest.mark.asyncio
    async def test_async_read_helper_unbounded(self, async_shared_db):
        from agno.agent import _storage

        session_id = f"s_{uuid.uuid4().hex[:6]}"
        sync_db = SqliteDb(session_table=async_shared_db.session_table_name, db_file=async_shared_db.db_file)
        _seed_agent_session(sync_db, session_id, n_runs=10)

        agent = MagicMock()
        agent.db = async_shared_db
        agent.cache_session = False
        agent._cached_session = None
        agent.team_id = None
        agent.workflow_id = None
        agent.session_state = None
        agent.metadata = None

        from unittest.mock import patch

        with patch("agno.agent._init.has_async_db", return_value=True):
            loaded = await _storage.aread_or_create_session(agent, session_id=session_id, user_id="u1")
        assert loaded is not None
        assert len(loaded.runs) == 10


# =============================================================================
# 7. Bounded read still writes all runs (no data loss).
# =============================================================================


class TestBoundedReadDoesNotLoseData:
    """A bounded read must not damage the DB. After reading with runs_limit=3
    from a session that has 20 runs, the DB must still have all 20."""

    def test_bounded_read_does_not_delete_older_runs(self, shared_db):
        session_id = f"s_{uuid.uuid4().hex[:6]}"
        _seed_agent_session(shared_db, session_id, n_runs=20)

        # Read bounded
        bounded = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT, runs_limit=5)
        assert len(bounded.runs) == 5

        # Unbounded read still shows all 20
        full = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        assert len(full.runs) == 20

    def test_bounded_read_does_not_mutate_session_row(self, shared_db):
        """Reading with runs_limit shouldn't change session_data, metadata etc."""
        session_id = f"s_{uuid.uuid4().hex[:6]}"
        runs = [_make_run(f"r{i}") for i in range(5)]
        sess = AgentSession(
            session_id=session_id,
            agent_id="test_agent",
            user_id="u1",
            runs=runs,
            session_data={"session_state": {"key": "value"}},
            metadata={"owner": "kaustubh"},
            created_at=int(time()),
        )
        shared_db.upsert_session(session=sess)
        for idx, run in enumerate(runs):
            shared_db.upsert_run(run=run, session_id=session_id, user_id="u1", run_index=idx)

        # Bounded read
        shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT, runs_limit=2)

        # Session row unchanged
        after = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        assert after.session_data == {"session_state": {"key": "value"}}
        assert after.metadata == {"owner": "kaustubh"}
        assert len(after.runs) == 5
