"""Regression tests for a bug found while auditing PR #8350.

Under v3 storage, ``save_session()`` writes only the session row — runs are
persisted independently via ``save_run()``. When ``continue_run(regenerate=True)``
mutated the parent run's status to ``REGENERATED`` in memory (so the history
builder would skip it), it never called ``save_run`` for that mutation, so the
DB row kept its old (COMPLETED) status. Result: the regenerated parent still
appeared in ``get_messages_for_session()``, producing duplicate content in
the LLM's conversation history.

These tests exercise the new ``_mark_run_regenerated`` /
``_amark_run_regenerated`` helpers directly (they're where the mutation +
persist now happen) against real SQLite, so the split-write semantics of
``upsert_session`` vs ``upsert_run`` are actually exercised end-to-end.
"""

from __future__ import annotations

import tempfile

import pytest

from agno.agent._run import _amark_run_regenerated, _mark_run_regenerated
from agno.agent.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team._run import _amark_team_run_regenerated, _mark_team_run_regenerated
from agno.team.team import Team


def _sqlite_db() -> SqliteDb:
    tmp = tempfile.mkdtemp()
    return SqliteDb(
        db_file=f"{tmp}/x.db",
        session_table="s",
        memory_table="m",
        metrics_table="mt",
        eval_table="e",
        knowledge_table="k",
    )


def _agent_run(run_id: str, status: RunStatus = RunStatus.completed) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        agent_id="a1",
        session_id="s1",
        status=status,
        messages=[Message(role="user", content=f"q-{run_id}"), Message(role="assistant", content=f"a-{run_id}")],
    )


def _team_run(run_id: str, status: RunStatus = RunStatus.completed) -> TeamRunOutput:
    return TeamRunOutput(
        run_id=run_id,
        team_id="t1",
        session_id="s1",
        status=status,
    )


class TestAgentMarkRunRegenerated:
    def test_persists_status_to_db(self):
        db = _sqlite_db()
        agent = Agent(db=db, id="a1", session_id="s1", user_id="u1")
        agent.initialize_agent()

        session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
        r0 = _agent_run("r0")
        session.upsert_run(r0)
        db.upsert_session(session)
        db.upsert_run(run=r0, session_id="s1", user_id="u1", run_index=0)

        _mark_run_regenerated(agent, session, original_run_id="r0")

        row = db.get_run("r0", deserialize=False)
        assert row.get("status") == "REGENERATED", (
            f"parent must be REGENERATED in the DB after mark, got {row.get('status')}. "
            "Without persistence, history builders would still surface the parent — "
            "the LLM would see the regenerated turn twice."
        )

    def test_preserves_run_index_on_status_flip(self):
        """The adapter's upsert excludes run_index from UPDATE; this test
        makes that guarantee explicit as a regression fence."""
        db = _sqlite_db()
        agent = Agent(db=db, id="a1", session_id="s1", user_id="u1")
        agent.initialize_agent()

        session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
        r0 = _agent_run("r0")
        r1 = _agent_run("r1")
        session.upsert_run(r0)
        session.upsert_run(r1)
        db.upsert_session(session)
        db.upsert_run(run=r0, session_id="s1", user_id="u1", run_index=0)
        db.upsert_run(run=r1, session_id="s1", user_id="u1", run_index=1)

        _mark_run_regenerated(agent, session, original_run_id="r0")

        row0 = db.get_run("r0", deserialize=False)
        row1 = db.get_run("r1", deserialize=False)
        assert row0.get("run_index") == 0
        assert row1.get("run_index") == 1
        assert row0.get("status") == "REGENERATED"
        assert row1.get("status") == "COMPLETED"

    def test_unknown_run_id_is_a_noop(self):
        """If the caller passes a run_id not in session.runs, nothing should
        crash and nothing should be written."""
        db = _sqlite_db()
        agent = Agent(db=db, id="a1", session_id="s1", user_id="u1")
        agent.initialize_agent()

        session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
        r0 = _agent_run("r0")
        session.upsert_run(r0)
        db.upsert_session(session)
        db.upsert_run(run=r0, session_id="s1", user_id="u1", run_index=0)

        _mark_run_regenerated(agent, session, original_run_id="ghost")

        # r0 untouched
        assert db.get_run("r0", deserialize=False).get("status") == "COMPLETED"

    def test_in_memory_status_also_flipped(self):
        """Symmetry: the in-memory session must also reflect the flip so
        callers that iterate ``session.runs`` after this helper see it."""
        db = _sqlite_db()
        agent = Agent(db=db, id="a1", session_id="s1", user_id="u1")
        agent.initialize_agent()

        session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
        r0 = _agent_run("r0")
        session.upsert_run(r0)
        db.upsert_session(session)
        db.upsert_run(run=r0, session_id="s1", user_id="u1", run_index=0)

        _mark_run_regenerated(agent, session, original_run_id="r0")

        in_mem = next(r for r in session.runs if r.run_id == "r0")
        assert in_mem.status == RunStatus.regenerated


class TestAgentAmarkRunRegenerated:
    @pytest.mark.asyncio
    async def test_async_persists_status_to_db(self):
        db = _sqlite_db()
        agent = Agent(db=db, id="a1", session_id="s1", user_id="u1")
        agent.initialize_agent()

        session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
        r0 = _agent_run("r0")
        session.upsert_run(r0)
        db.upsert_session(session)
        db.upsert_run(run=r0, session_id="s1", user_id="u1", run_index=0)

        await _amark_run_regenerated(agent, session, original_run_id="r0")

        row = db.get_run("r0", deserialize=False)
        assert row.get("status") == "REGENERATED"


class TestTeamMarkRunRegenerated:
    def test_persists_status_to_db(self):
        db = _sqlite_db()
        team = Team(id="t1", members=[], db=db, session_id="s1", user_id="u1")
        team.initialize_team()

        session = TeamSession(session_id="s1", team_id="t1", user_id="u1")
        r0 = _team_run("r0")
        session.upsert_run(r0)
        db.upsert_session(session)
        db.upsert_run(run=r0, session_id="s1", user_id="u1", run_index=0)

        _mark_team_run_regenerated(team, session, original_run_id="r0")

        row = db.get_run("r0", deserialize=False)
        assert row.get("status") == "REGENERATED"


class TestTeamAmarkRunRegenerated:
    @pytest.mark.asyncio
    async def test_async_persists_status_to_db(self):
        db = _sqlite_db()
        team = Team(id="t1", members=[], db=db, session_id="s1", user_id="u1")
        team.initialize_team()

        session = TeamSession(session_id="s1", team_id="t1", user_id="u1")
        r0 = _team_run("r0")
        session.upsert_run(r0)
        db.upsert_session(session)
        db.upsert_run(run=r0, session_id="s1", user_id="u1", run_index=0)

        await _amark_team_run_regenerated(team, session, original_run_id="r0")

        row = db.get_run("r0", deserialize=False)
        assert row.get("status") == "REGENERATED"
