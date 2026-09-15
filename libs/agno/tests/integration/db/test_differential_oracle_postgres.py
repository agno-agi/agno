"""Differential conformance harness: OracleDb vs PostgresDb.

The central testing decision for the Oracle integration effort: run an
identical scenario against both adapters and compare results directly,
rather than asserting against each independently. A test that only checks
"Oracle behaves reasonably" can pass even when Oracle quietly diverges from
the reference adapter in a way that would surprise a team switching backends;
comparing the two outputs to each other catches that.

This sits on the highest available seam -- the BaseDb public contract -- and
introduces no new production boundary. Both modules skip cleanly (not error)
when their server is unreachable, since no Oracle container exists in public
CI (ADR 0009).

Coverage in this file: the domains tickets 03 and 04 deliver (sessions, runs,
memory, metrics, knowledge). Later tickets extend this file with their own
domains as they land, rather than each inventing a separate differential
suite.
"""

import uuid
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine, text

from agno.db.oracle import OracleDb
from agno.db.postgres import PostgresDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.run.agent import RunOutput
from agno.session import AgentSession

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
ORACLE_URL = "oracle+oracledb://ai:ai@localhost:1523/?service_name=FREEPDB1"


def _reachable(url: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1 from dual") if "oracle" in url else text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _servers_up():
    if not _reachable(PG_URL):
        pytest.skip(f"Postgres server not reachable at {PG_URL}")
    if not _reachable(ORACLE_URL):
        pytest.skip(f"Oracle server not reachable at {ORACLE_URL}")


@pytest.fixture
def pg_db(_servers_up):
    schema = f"diff_{uuid.uuid4().hex[:8]}"
    database = PostgresDb(db_url=PG_URL, db_schema=schema, id=f"diff-pg-{schema}")
    yield database
    database.Session.remove()
    with database.db_engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()
    database.db_engine.dispose()


@pytest.fixture
def oracle_db(_servers_up):
    suffix = uuid.uuid4().hex[:8]
    tables = {
        "session_table": f"diff_sess_{suffix}",
        "runs_table": f"diff_runs_{suffix}",
        "memory_table": f"diff_mem_{suffix}",
        "metrics_table": f"diff_metrics_{suffix}",
        "knowledge_table": f"diff_know_{suffix}",
    }
    database = OracleDb(db_url=ORACLE_URL, id=f"diff-oracle-{suffix}", **tables)
    yield database
    database.Session.remove()
    with database.db_engine.begin() as conn:
        for t in tables.values():
            if database.table_exists(t):
                conn.execute(text(f"DROP TABLE {t} CASCADE CONSTRAINTS"))
    database.db_engine.dispose()


def _run_scenario(db) -> Dict[str, Any]:
    """The identical sequence of operations, run against whichever adapter is passed.

    Returns every observable outcome the differential test compares.
    """
    session_id = "diff-session-1"
    session = AgentSession(
        session_id=session_id,
        agent_id="diff-agent",
        user_id="diff-user",
        session_data={"session_name": "before rename"},
        created_at=1700000000,
    )
    upserted = db.upsert_session(session, deserialize=False)

    for i in range(3):
        run = RunOutput(run_id=f"diff-run-{i}", agent_id="diff-agent", status="COMPLETED")
        db.upsert_run(run, session_id=session_id, user_id="diff-user", run_index=i)

    runs, run_total = db.get_runs(session_id=session_id, deserialize=False)
    single_run = db.get_run("diff-run-1", deserialize=False)

    renamed = db.rename_session(session_id, None, "after rename", deserialize=False)

    session2 = AgentSession(
        session_id="diff-session-2", agent_id="diff-agent", user_id="diff-user", created_at=1700000001
    )
    db.upsert_session(session2, deserialize=False)
    sessions, session_total = db.get_sessions(user_id="diff-user", deserialize=False)

    deleted = db.delete_session(session_id)
    _, remaining_run_total = db.get_runs(session_id=session_id, deserialize=False)

    return {
        "upserted_session_type": upserted.get("session_type") if upserted else None,
        "upserted_agent_id": upserted.get("agent_id") if upserted else None,
        "run_ids_in_order": [r["run_id"] for r in runs],
        "run_total": run_total,
        "single_run_type": single_run.get("run_type") if single_run else None,
        "single_run_status": single_run.get("status") if single_run else None,
        "renamed_session_name": (renamed or {}).get("session_data", {}).get("session_name"),
        "session_total": session_total,
        "session_ids": sorted(s["session_id"] for s in sessions),
        "deleted": deleted,
        "remaining_run_total_after_delete": remaining_run_total,
    }


def test_session_and_run_lifecycle_matches_postgres(pg_db, oracle_db):
    """One scenario, two backends, one comparison.

    Every field asserted here is an observable outcome of the public
    interface -- returned values and counts -- never a generated SQL string
    or a private helper's internals.
    """
    pg_result = _run_scenario(pg_db)
    oracle_result = _run_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"Oracle diverged from Postgres.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )


def test_owner_collision_guard_matches_postgres(pg_db, oracle_db):
    """A second owner's upsert must not silently steal a session id, on either backend."""
    for db in (pg_db, oracle_db):
        session = AgentSession(session_id="diff-owner-collision", agent_id="a", user_id="alice", created_at=1700000002)
        db.upsert_session(session)
        theft_attempt = AgentSession(
            session_id="diff-owner-collision", agent_id="a", user_id="bob", created_at=1700000003
        )
        result = db.upsert_session(theft_attempt)
        assert result is None, f"{type(db).__name__} allowed a different owner to overwrite the session"
        still_alice = db.get_session("diff-owner-collision")
        assert still_alice.user_id == "alice", f"{type(db).__name__} lost the original owner"


def _run_memory_metrics_knowledge_scenario(db) -> Dict[str, Any]:
    """All three owner states (None, "", a name), across memory, metrics and
    knowledge -- the domains where the owner-scoping sentinel decision
    (ADR 0005) is actually exercised, per ticket 04's own DoD.
    """
    for uid in ("alice", "", None):
        db.upsert_user_memory(UserMemory(memory=f"memory for {uid!r}", user_id=uid, agent_id="diff-agent"))

    memories_by_state = {}
    for uid in ("alice", ""):
        rows, total = db.get_user_memories(user_id=uid, deserialize=False)
        memories_by_state[repr(uid)] = total
    # user_id=None means "every owner": all three memories, unfiltered.
    _, memories_by_state["None"] = db.get_user_memories(user_id=None, deserialize=False)

    stats, stats_total = db.get_user_memory_stats()
    stats_user_ids = sorted((s["user_id"] for s in stats), key=lambda v: (v is None, v))

    # Metrics: one session per owner state, then calculate and read back.
    for i, uid in enumerate(("alice", "", None)):
        session = AgentSession(
            session_id=f"diff-metrics-{i}", agent_id="diff-agent", user_id=uid, created_at=1700000010 + i
        )
        db.upsert_session(session, deserialize=False)
        db.upsert_run(
            RunOutput(run_id=f"diff-metrics-run-{i}", agent_id="diff-agent", status="COMPLETED"),
            session_id=f"diff-metrics-{i}",
            user_id=uid,
            run_index=0,
        )
    db.calculate_metrics()
    metrics_rows, _ = db.get_metrics()
    metrics_user_ids = sorted((r["user_id"] for r in metrics_rows), key=lambda v: (v is None, v))

    # Knowledge: None means shared (visible to everyone), unlike memory/metrics
    # where "" is the unowned-but-distinct bucket -- this is the one domain
    # where the two states are NOT symmetric, and the harness checks that
    # asymmetry holds identically on both backends.
    db.upsert_knowledge_content(KnowledgeRow(name="diff-doc-alice", description="d", user_id="alice"))
    db.upsert_knowledge_content(KnowledgeRow(name="diff-doc-shared", description="d", user_id=None))
    _, alice_knowledge_total = db.get_knowledge_contents(user_id="alice")
    _, bob_knowledge_total = db.get_knowledge_contents(user_id="bob")

    return {
        "memories_by_state": memories_by_state,
        "memory_stats_total": stats_total,
        "memory_stats_user_ids": stats_user_ids,
        "metrics_user_ids": metrics_user_ids,
        "alice_knowledge_total": alice_knowledge_total,
        "bob_knowledge_total": bob_knowledge_total,
    }


def test_memory_metrics_knowledge_owner_states_match_postgres(pg_db, oracle_db):
    """One scenario exercising every owner state across the three domains
    ticket 04 delivers, run against both backends with the results compared
    directly -- the same design as the sessions/runs scenario above.
    """
    pg_result = _run_memory_metrics_knowledge_scenario(pg_db)
    oracle_result = _run_memory_metrics_knowledge_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"Oracle diverged from Postgres.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )
