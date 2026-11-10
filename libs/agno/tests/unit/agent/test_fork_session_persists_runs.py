"""Regression tests for reviewer comment #17 on PR #8350.

Under v3 storage, ``save_session()`` no longer writes runs — the whole point
of the denormalization is that runs live in ``agno_runs``, not in the
sessions blob. But ``fork_session_dispatch`` still only called
``save_session(new_session)``, so the forked session's inherited history
never made it into the runs table. The user saw an empty session.

These tests reproduce the loss (with SQLite as a real DB so the split-write
semantics kick in end-to-end) for both sync and async agent variants, plus
the sync + async team variants. Each asserts:

1. ``db.get_session(new_id)`` returns the forked runs.
2. ``db.get_runs(session_id=new_id)`` returns rows in the runs table
   (the raw persistence check — separate from the merge path).
"""

from __future__ import annotations

import tempfile
from typing import List

import pytest

from agno.agent._run import (
    afork_session_dispatch as agent_afork,
)
from agno.agent._run import (
    fork_session_dispatch as agent_fork,
)
from agno.agent.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team._run import (
    afork_session_dispatch as team_afork,
)
from agno.team._run import (
    fork_session_dispatch as team_fork,
)
from agno.team.team import Team


def _make_sqlite() -> SqliteDb:
    tmp = tempfile.mkdtemp()
    return SqliteDb(
        db_file=f"{tmp}/fork_test.db",
        session_table="s",
        memory_table="m",
        metrics_table="mt",
        eval_table="e",
        knowledge_table="k",
    )


def _agent_run(run_id: str, content: str) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        agent_id="a1",
        session_id="src",
        status=RunStatus.completed,
        content=content,
        messages=[
            Message(role="user", content=f"q-{content}"),
            Message(role="assistant", content=f"a-{content}"),
        ],
    )


def _team_run(run_id: str, content: str) -> TeamRunOutput:
    return TeamRunOutput(
        run_id=run_id,
        team_id="t1",
        session_id="src",
        status=RunStatus.completed,
        content=content,
        messages=[Message(role="assistant", content=content)],
    )


def _seed_agent_source(db: SqliteDb, run_ids: List[str]) -> AgentSession:
    src = AgentSession(session_id="src", agent_id="a1", user_id="u1")
    for rid in run_ids:
        src.upsert_run(_agent_run(rid, content=rid))
    db.upsert_session(src)
    for r in src.runs or []:
        db.upsert_run(run=r, session_id="src", user_id="u1")
    return src


def _seed_team_source(db: SqliteDb, run_ids: List[str]) -> TeamSession:
    src = TeamSession(session_id="src", team_id="t1", user_id="u1")
    for rid in run_ids:
        src.upsert_run(_team_run(rid, content=rid))
    db.upsert_session(src)
    for r in src.runs or []:
        db.upsert_run(run=r, session_id="src", user_id="u1")
    return src


def _agno_runs_count(db: SqliteDb, session_id: str) -> int:
    result = db.get_runs(session_id=session_id, deserialize=False)
    if isinstance(result, tuple):
        _, total = result
        return total
    return len(result)  # pragma: no cover — defensive


# ---------------------------------------------------------------------------
# Agent — sync
# ---------------------------------------------------------------------------


class TestAgentForkSessionPersistsRuns:
    def test_sync_fork_writes_all_runs_to_runs_table(self):
        db = _make_sqlite()
        _seed_agent_source(db, ["r1", "r2", "r3"])

        agent = Agent(db=db, id="a1", session_id="src", user_id="u1")
        agent.initialize_agent()

        new_sid = agent_fork(agent, source_session_id="src", user_id="u1")

        # 1. Every run made it into agno_runs (was 0 before the fix)
        assert _agno_runs_count(db, new_sid) == 3, (
            "fork must persist each inherited run to the runs table — "
            "save_session alone no longer writes runs under v3 storage"
        )

        # 2. get_session round-trips the runs (which is what a user actually sees)
        forked = db.get_session(session_id=new_sid, deserialize=False)
        assert forked is not None
        assert len(forked.get("runs") or []) == 3

    def test_sync_fork_preserves_run_content_and_order(self):
        db = _make_sqlite()
        _seed_agent_source(db, ["r1", "r2", "r3"])

        agent = Agent(db=db, id="a1", session_id="src", user_id="u1")
        agent.initialize_agent()
        new_sid = agent_fork(agent, source_session_id="src", user_id="u1")

        rows, _ = db.get_runs(session_id=new_sid, deserialize=False)
        rows_sorted = sorted(rows, key=lambda r: r["run_index"])
        assert [r["run_index"] for r in rows_sorted] == [0, 1, 2]
        # Content survives the fork
        contents = [r.get("run_data", {}).get("content") for r in rows_sorted]
        assert contents == ["r1", "r2", "r3"]

    def test_sync_fork_assigns_fresh_run_ids(self):
        db = _make_sqlite()
        _seed_agent_source(db, ["r1", "r2"])
        agent = Agent(db=db, id="a1", session_id="src", user_id="u1")
        agent.initialize_agent()

        new_sid = agent_fork(agent, source_session_id="src", user_id="u1")

        rows, _ = db.get_runs(session_id=new_sid, deserialize=False)
        new_ids = {r["run_id"] for r in rows}
        # None of the new run_ids collide with the source's
        assert new_ids.isdisjoint({"r1", "r2"})
        assert len(new_ids) == 2


# ---------------------------------------------------------------------------
# Agent — async
# ---------------------------------------------------------------------------


class TestAgentAforkSessionPersistsRuns:
    @pytest.mark.asyncio
    async def test_async_fork_writes_all_runs_to_runs_table(self):
        db = _make_sqlite()
        _seed_agent_source(db, ["r1", "r2"])

        agent = Agent(db=db, id="a1", session_id="src", user_id="u1")
        agent.initialize_agent()
        new_sid = await agent_afork(agent, source_session_id="src", user_id="u1")

        assert _agno_runs_count(db, new_sid) == 2


# ---------------------------------------------------------------------------
# Team — sync
# ---------------------------------------------------------------------------


class TestTeamForkSessionPersistsRuns:
    def test_sync_team_fork_writes_all_runs_to_runs_table(self):
        db = _make_sqlite()
        _seed_team_source(db, ["r1", "r2", "r3"])

        team = Team(id="t1", members=[], db=db, session_id="src", user_id="u1")
        team.initialize_team()
        new_sid = team_fork(team, source_session_id="src", user_id="u1")

        assert _agno_runs_count(db, new_sid) == 3, "team fork must persist each inherited run to the runs table"
        forked = db.get_session(session_id=new_sid, deserialize=False)
        assert forked is not None
        assert len(forked.get("runs") or []) == 3


# ---------------------------------------------------------------------------
# Team — async
# ---------------------------------------------------------------------------


class TestTeamAforkSessionPersistsRuns:
    @pytest.mark.asyncio
    async def test_async_team_fork_writes_all_runs_to_runs_table(self):
        db = _make_sqlite()
        _seed_team_source(db, ["r1", "r2"])

        team = Team(id="t1", members=[], db=db, session_id="src", user_id="u1")
        team.initialize_team()
        new_sid = await team_afork(team, source_session_id="src", user_id="u1")

        assert _agno_runs_count(db, new_sid) == 2


class TestForkEmptySourceStillRejects:
    """Sanity check the pre-existing guard still fires — a source with no runs
    can't be forked, regardless of our persistence changes."""

    def test_agent_fork_raises_on_source_without_runs(self):
        db = _make_sqlite()
        # Session exists but has no runs
        db.upsert_session(AgentSession(session_id="src", agent_id="a1", user_id="u1"))

        agent = Agent(db=db, id="a1", session_id="src", user_id="u1")
        agent.initialize_agent()
        with pytest.raises(ValueError, match="no runs"):
            agent_fork(agent, source_session_id="src", user_id="u1")
