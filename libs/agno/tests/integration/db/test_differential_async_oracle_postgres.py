"""Async differential conformance harness: AsyncOracleDb vs AsyncPostgresDb.

Ticket 13's own acceptance criterion: the same scenario run against both
ASYNC adapters, compared directly -- mirroring
test_differential_oracle_postgres.py's sync harness, but scoped to exactly
the domains ticket 13 delivers (schema versions, sessions, runs, memory,
metrics, knowledge, eval runs, traces, spans). Parity is measured against
the async Postgres adapter, not the sync one, since the async base class
carries less (no batch upserts, no components, no MCP OAuth) -- comparing
against AsyncPostgresDb is what actually pins the right contract.

Both modules skip cleanly (not error) when their server is unreachable,
matching the sync harness's own convention (ADR 0009: no Oracle container in
public CI).
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text

from agno.db.oracle import AsyncOracleDb
from agno.db.postgres import AsyncPostgresDb
from agno.db.schemas.evals import EvalRunRecord
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.run.agent import RunOutput
from agno.session import AgentSession
from agno.tracing.schemas import Span, Trace

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
PG_ASYNC_URL = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"
ORACLE_SYNC_URL = "oracle+oracledb://ai:ai@localhost:1523/?service_name=FREEPDB1"
ORACLE_ASYNC_URL = "oracle+oracledb_async://ai:ai@localhost:1523/?service_name=FREEPDB1"


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
    if not _reachable(ORACLE_SYNC_URL):
        pytest.skip(f"Oracle server not reachable at {ORACLE_SYNC_URL}")


@pytest_asyncio.fixture
async def pg_db(_servers_up):
    schema = f"adiff_{uuid.uuid4().hex[:8]}"
    database = AsyncPostgresDb(db_url=PG_ASYNC_URL, db_schema=schema, id=f"adiff-pg-{schema}")
    yield database
    async with database.db_engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await database.close()


@pytest_asyncio.fixture
async def oracle_db(_servers_up):
    suffix = uuid.uuid4().hex[:8]
    tables = {
        "session_table": f"adiff_sess_{suffix}",
        "runs_table": f"adiff_runs_{suffix}",
        "memory_table": f"adiff_mem_{suffix}",
        "metrics_table": f"adiff_metrics_{suffix}",
        "knowledge_table": f"adiff_know_{suffix}",
        "eval_table": f"adiff_eval_{suffix}",
        "traces_table": f"adiff_trace_{suffix}",
        "spans_table": f"adiff_span_{suffix}",
        "versions_table": f"adiff_ver_{suffix}",
    }
    database = AsyncOracleDb(db_url=ORACLE_ASYNC_URL, id=f"adiff-oracle-{suffix}", **tables)
    yield database
    # Table cleanup via a plain sync engine: simpler than awaiting DDL through
    # run_sync for a one-off teardown, and this file already needs a sync
    # engine for the reachability probe above.
    sync_engine = create_engine(ORACLE_SYNC_URL)
    with sync_engine.begin() as conn:
        for t in tables.values():
            exists = conn.execute(text(f"select count(*) from user_tables where table_name = upper('{t}')")).scalar()
            if exists:
                conn.execute(text(f"DROP TABLE {t} CASCADE CONSTRAINTS"))
    sync_engine.dispose()
    await database.close()


async def _run_session_and_run_scenario(db) -> Dict[str, Any]:
    """Sessions + runs: the five run methods ticket 13 overrides rather than
    inherits, plus owner scoping across all three states.
    """
    session_id = "adiff-session-1"
    session = AgentSession(
        session_id=session_id,
        agent_id="adiff-agent",
        user_id="adiff-user",
        session_data={"session_name": "before rename"},
        created_at=1700000000,
    )
    upserted = await db.upsert_session(session, deserialize=False)

    for i in range(3):
        run = RunOutput(run_id=f"adiff-run-{i}", agent_id="adiff-agent", status="COMPLETED")
        await db.upsert_run(run, session_id=session_id, user_id="adiff-user", run_index=i)

    runs, run_total = await db.get_runs(session_id=session_id, deserialize=False)
    single_run = await db.get_run("adiff-run-1", deserialize=False)

    renamed = await db.rename_session(session_id, None, "after rename", deserialize=False)

    session2 = AgentSession(
        session_id="adiff-session-2", agent_id="adiff-agent", user_id="adiff-user", created_at=1700000001
    )
    await db.upsert_session(session2, deserialize=False)
    sessions, session_total = await db.get_sessions(user_id="adiff-user", deserialize=False)

    deleted_single = await db.delete_run("adiff-run-0")
    _, remaining_after_single = await db.get_runs(session_id=session_id, deserialize=False)

    deleted = await db.delete_session(session_id)
    _, remaining_run_total = await db.get_runs(session_id=session_id, deserialize=False)

    # Owner scoping: all three states.
    for uid in ("adiff-owner", "", None):
        await db.upsert_session(
            AgentSession(session_id=f"adiff-owner-{uid!r}", agent_id="adiff-agent", user_id=uid, created_at=1700000002)
        )
    owned = await db.get_session(f"adiff-owner-{'adiff-owner'!r}")
    unowned_bucket = await db.get_session(f"adiff-owner-{''!r}")
    shared = await db.get_session(f"adiff-owner-{None!r}")

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
        "deleted_single": deleted_single,
        "remaining_after_single": remaining_after_single,
        "deleted": deleted,
        "remaining_run_total_after_delete": remaining_run_total,
        "owned_user_id": owned.user_id if owned else None,
        "unowned_bucket_user_id": unowned_bucket.user_id if unowned_bucket else None,
        "shared_user_id": shared.user_id if shared else None,
    }


async def test_async_session_and_run_lifecycle_matches_postgres(pg_db, oracle_db):
    pg_result = await _run_session_and_run_scenario(pg_db)
    oracle_result = await _run_session_and_run_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"AsyncOracleDb diverged from AsyncPostgresDb.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )


async def _run_memory_metrics_knowledge_scenario(db) -> Dict[str, Any]:
    for uid in ("alice", "", None):
        await db.upsert_user_memory(UserMemory(memory=f"memory for {uid!r}", user_id=uid, agent_id="adiff-agent"))

    memories_by_state = {}
    for uid in ("alice", ""):
        _, total = await db.get_user_memories(user_id=uid, deserialize=False)
        memories_by_state[repr(uid)] = total

    topics = await db.get_all_memory_topics()
    stats, stats_total = await db.get_user_memory_stats()

    session = AgentSession(session_id="adiff-mm-session", agent_id="adiff-agent", user_id="bob", created_at=1700000000)
    await db.upsert_session(session)
    run = RunOutput(run_id="adiff-mm-run", agent_id="adiff-agent", status="COMPLETED")
    await db.upsert_run(run, session_id="adiff-mm-session", user_id="bob", run_index=0)
    calculated = await db.calculate_metrics()
    metrics_rows, _ = await db.get_metrics()

    row = KnowledgeRow(id="adiff-k1", name="doc1", description="test", metadata={}, user_id="alice")
    await db.upsert_knowledge_content(row)
    fetched_k = await db.get_knowledge_content("adiff-k1")
    _, k_total = await db.get_knowledge_contents()
    deleted_k = await db.delete_knowledge_content("adiff-k1")
    after_delete_k = await db.get_knowledge_content("adiff-k1")

    return {
        "memories_by_state": memories_by_state,
        "topics_is_list": isinstance(topics, list),
        "stats_total_at_least_one": stats_total >= 1,
        "calculated_metrics_present": calculated is not None and len(calculated) > 0,
        "metrics_rows_present": len(metrics_rows) > 0,
        "fetched_k_name": fetched_k.name if fetched_k else None,
        "k_total_at_least_one": k_total >= 1,
        "deleted_k": deleted_k,
        "after_delete_k": after_delete_k,
    }


async def test_async_memory_metrics_knowledge_matches_postgres(pg_db, oracle_db):
    pg_result = await _run_memory_metrics_knowledge_scenario(pg_db)
    oracle_result = await _run_memory_metrics_knowledge_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"AsyncOracleDb diverged from AsyncPostgresDb.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )


async def _run_eval_trace_span_scenario(db) -> Dict[str, Any]:
    eval_run = EvalRunRecord(
        run_id="adiff-e1",
        eval_type="accuracy",
        eval_data={"score": 1.0},
        eval_input={"query": "2+2"},
        agent_id="adiff-agent",
        name="eval1",
    )
    await db.create_eval_run(eval_run)
    await db.update_eval_run_user_id("adiff-e1", "alice")
    fetched_eval = await db.get_eval_run("adiff-e1", deserialize=False)
    renamed_eval = await db.rename_eval_run("adiff-e1", "eval1-renamed")
    _, eval_total = await db.get_eval_runs(deserialize=False)
    await db.delete_eval_run("adiff-e1")
    eval_after_delete = await db.get_eval_run("adiff-e1")

    t_start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    t_end = datetime(2024, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
    trace_a = Trace(
        trace_id="adiff-t1",
        name="agent.run",
        status="OK",
        start_time=t_start,
        end_time=t_end,
        duration_ms=1000,
        total_spans=0,
        error_count=0,
        run_id="adiff-run-trace",
        session_id="adiff-sess-trace",
        user_id="alice",
        agent_id="adiff-agent",
        team_id=None,
        workflow_id=None,
        created_at=t_start,
    )
    await db.upsert_trace(trace_a)
    # A second upsert of the same trace_id merges (earliest start, latest end).
    trace_b = Trace(
        trace_id="adiff-t1",
        name="child.step",
        status="OK",
        start_time=t_end,
        end_time=datetime(2024, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
        duration_ms=1000,
        total_spans=0,
        error_count=0,
        run_id=None,
        session_id=None,
        user_id=None,
        agent_id=None,
        team_id=None,
        workflow_id=None,
        created_at=t_start,
    )
    await db.upsert_trace(trace_b)
    merged = await db.get_trace(trace_id="adiff-t1")

    span = Span(
        span_id="adiff-s1",
        trace_id="adiff-t1",
        parent_span_id=None,
        name="tool_call",
        span_kind="tool",
        status_code="OK",
        status_message=None,
        start_time=t_start,
        end_time=t_end,
        duration_ms=500,
        attributes={},
        created_at=t_start,
    )
    await db.create_span(span)
    fetched_span = await db.get_span("adiff-s1")
    spans = await db.get_spans(trace_id="adiff-t1")

    traces, trace_total = await db.get_traces(user_id="alice")
    trace_stats, stats_total = await db.get_trace_stats(group_by="agent")

    return {
        "fetched_eval_user_id": fetched_eval["user_id"] if fetched_eval else None,
        "renamed_eval_name": renamed_eval.name if renamed_eval else None,
        "eval_total_at_least_one": eval_total >= 1,
        "eval_after_delete": eval_after_delete,
        "merged_trace_name": merged.name if merged else None,
        "merged_trace_duration_ms": merged.duration_ms if merged else None,
        "fetched_span_name": fetched_span.name if fetched_span else None,
        "spans_count": len(spans),
        "trace_total_at_least_one": trace_total >= 1,
        "stats_total_at_least_one": stats_total >= 1,
    }


async def test_async_eval_trace_span_matches_postgres(pg_db, oracle_db):
    pg_result = await _run_eval_trace_span_scenario(pg_db)
    oracle_result = await _run_eval_trace_span_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"AsyncOracleDb diverged from AsyncPostgresDb.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )
