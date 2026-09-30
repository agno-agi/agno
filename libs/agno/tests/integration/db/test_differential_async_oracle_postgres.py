"""Async differential conformance harness: AsyncOracleDb vs AsyncPostgresDb.

Ticket 13's own acceptance criterion: the same scenario run against both
ASYNC adapters, compared directly -- mirroring
test_differential_oracle_postgres.py's sync harness, but scoped to exactly
the domains ticket 13 delivers (schema versions, sessions, runs, memory,
metrics, knowledge, eval runs, traces, spans). Parity is measured against
the async Postgres adapter, not the sync one, since the async base class
carries less (no batch upserts, no components, no MCP OAuth) -- comparing
against AsyncPostgresDb is what actually pins the right contract.

Ticket 14 extends this file with its own domains (learnings, schedules and
schedule runs, tool results, approvals, auth tokens, service accounts),
mirroring the sync harness's own scenarios for tickets 06-08 and 11 --
concurrent claim's exactly-one-winner property is proven separately (see
validate_ticket14.py's genuine ``asyncio.gather`` check), not here, for the
same reason the sync harness excludes it: a differential comparison says
nothing about a race, only about whether both backends agree on a
deterministic scenario.

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
from agno.run.base import RunStatus
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
        "learnings_table": f"adiff_learn_{suffix}",
        "schedules_table": f"adiff_sched_{suffix}",
        "schedule_runs_table": f"adiff_schedrun_{suffix}",
        "approvals_table": f"adiff_appr_{suffix}",
        "auth_tokens_table": f"adiff_auth_{suffix}",
        "service_accounts_table": f"adiff_svcacct_{suffix}",
    }
    database = AsyncOracleDb(db_url=ORACLE_ASYNC_URL, id=f"adiff-oracle-{suffix}", **tables)
    yield database
    # Table cleanup via a plain sync engine: simpler than awaiting DDL through
    # run_sync for a one-off teardown, and this file already needs a sync
    # engine for the reachability probe above.
    sync_engine = create_engine(ORACLE_SYNC_URL)
    with sync_engine.begin() as conn:
        for t in [*tables.values(), database.tool_results_table_name]:
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


async def _run_learnings_scenario(db) -> Dict[str, Any]:
    """Ticket 06/14's domain: search matching (Python-side regex translation
    of Postgres's CAST+ILIKE) and per-owner listing/stats.
    """
    await db.upsert_learning(
        id="adiff-learning-1",
        learning_type="user_profile",
        content={"summary": "alice_chen likes tea"},
        user_id="alice",
    )
    await db.upsert_learning(
        id="adiff-learning-2",
        learning_type="session_context",
        content={"note": "bob prefers dark mode"},
        user_id="bob",
    )
    await db.upsert_learning(
        id="adiff-learning-3", learning_type="user_profile", content={"summary": "shared note"}, user_id=None
    )

    space_underscore_match = sorted(r["learning_id"] for r in await db.search_learnings(query="alice chen"))
    case_insensitive_match = sorted(r["learning_id"] for r in await db.search_learnings(query="DARK MODE"))
    no_match = await db.search_learnings(query="nonexistent-zzz")

    alice_learnings = sorted(r["learning_id"] for r in await db.get_learnings(user_id="alice"))
    _, list_total = await db.list_learnings(user_id="alice", include_global=True)

    stats, stats_total = await db.get_learnings_user_stats()
    stats_user_ids = sorted(s["user_id"] for s in stats)

    await db.update_learning("adiff-learning-1", content={"summary": "updated"})
    updated = await db.get_learning_by_id("adiff-learning-1")

    deleted_count = await db.delete_user_learnings("bob")
    _, remaining_total = await db.list_learnings()

    return {
        "space_underscore_match": space_underscore_match,
        "case_insensitive_match": case_insensitive_match,
        "no_match": no_match,
        "alice_learnings": alice_learnings,
        "list_total": list_total,
        "stats_total": stats_total,
        "stats_user_ids": stats_user_ids,
        "updated_summary": updated["content"]["summary"],
        "deleted_count": deleted_count,
        "remaining_total": remaining_total,
    }


async def test_async_learnings_match_postgres(pg_db, oracle_db):
    """One scenario covering ticket 14's learnings domain, compared directly."""
    pg_result = await _run_learnings_scenario(pg_db)
    oracle_result = await _run_learnings_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"AsyncOracleDb diverged from AsyncPostgresDb.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )


async def _run_schedules_scenario(db) -> Dict[str, Any]:
    """Ticket 07/14's domain: schedules and schedule runs -- uniqueness
    across the three owner-bucket states, generic update, provenance
    stamping, target-cascade disable, claim/release, and cascade delete into
    schedule_runs.

    Concurrent claim's exactly-one-winner property is proven separately
    (validate_ticket14.py's own genuine asyncio.gather check against a live
    server), not here -- a differential comparison says nothing about a
    race. Wall-clock-derived fields the adapters set internally are
    deliberately excluded from the comparison below, for the same reason the
    sync scenario excludes them.
    """
    base = {
        "description": None,
        "method": "POST",
        "payload": {"message": "hi"},
        "cron_expr": "0 * * * *",
        "timezone": "UTC",
        "timeout_seconds": 60,
        "max_retries": 0,
        "retry_delay_seconds": 0,
        "enabled": True,
        "next_run_at": 1700000000,
        "locked_by": None,
        "locked_at": None,
        "managed_by": None,
        "target_type": None,
        "target_id": None,
        "created_by_run_id": None,
        "created_by_session_id": None,
        "updated_by_run_id": None,
        "updated_by_session_id": None,
        "disabled_reason": None,
        "created_at": 1700000000,
        "updated_at": 1700000000,
    }
    await db.create_schedule(
        {"id": "adiff-sched-1", "name": "daily-report", "user_id": "alice", "endpoint": "/agents/sched-1/runs", **base}
    )
    await db.create_schedule(
        {"id": "adiff-sched-2", "name": "daily-report", "user_id": "bob", "endpoint": "/agents/sched-2/runs", **base}
    )
    await db.create_schedule(
        {"id": "adiff-sched-3", "name": "daily-report", "user_id": None, "endpoint": "/agents/sched-3/runs", **base}
    )
    await db.create_schedule(
        {"id": "adiff-sched-4", "name": "other-name", "user_id": "alice", "endpoint": "/agents/sched-4/runs", **base}
    )

    by_name_alice = (await db.get_schedule_by_name("daily-report", user_id="alice"))["id"]
    by_name_unowned = (await db.get_schedule_by_name("daily-report", user_id=None))["id"]

    same_owner_collision = False
    try:
        await db.create_schedule({"id": "adiff-sched-1-dup", "name": "daily-report", "user_id": "alice", **base})
    except Exception:
        same_owner_collision = True

    unowned_collision = False
    try:
        await db.create_schedule({"id": "adiff-sched-3-dup", "name": "daily-report", "user_id": None, **base})
    except Exception:
        unowned_collision = True

    _, alice_total = await db.get_schedules(user_id="alice")
    _, all_total = await db.get_schedules()

    updated = await db.update_schedule("adiff-sched-1", cron_expr="0 0 * * *")

    rename_collision = False
    try:
        await db.update_schedule("adiff-sched-4", name="daily-report", user_id="alice")
    except Exception:
        rename_collision = True

    await db.stamp_schedule_provenance(
        "adiff-sched-2", managed_by="system", target_type="agent", target_id="adiff-agent"
    )
    disabled_count = await db.disable_schedules_for_target("agent", "adiff-agent")
    after_disable = await db.get_schedule("adiff-sched-2")

    claimed = await db.claim_due_schedule("adiff-worker-1")
    claimed_locked_by = claimed["locked_by"] if claimed else None
    claimed_has_lock_timestamp = claimed is not None and claimed["locked_at"] is not None
    await db.release_schedule(claimed["id"], next_run_at=1800000000)
    after_release = await db.get_schedule(claimed["id"])

    await db.create_schedule_run(
        {
            "id": "adiff-run-1",
            "schedule_id": "adiff-sched-3",
            "attempt": 1,
            "triggered_at": 1700000000,
            "completed_at": None,
            "status": "pending",
            "status_code": None,
            "run_id": None,
            "session_id": None,
            "error": None,
            "input": {"a": 1},
            "output": None,
            "requirements": None,
            "user_id": None,
            "created_at": 1700000000,
        }
    )
    updated_run = await db.update_schedule_run("adiff-run-1", status="completed", output={"ok": True})
    runs, run_total = await db.get_schedule_runs("adiff-sched-3")

    deleted = await db.delete_schedule("adiff-sched-3")
    remaining_run = await db.get_schedule_run("adiff-run-1")

    return {
        "by_name_alice": by_name_alice,
        "by_name_unowned": by_name_unowned,
        "same_owner_collision": same_owner_collision,
        "unowned_collision": unowned_collision,
        "alice_total": alice_total,
        "all_total": all_total,
        "updated_cron_expr": updated["cron_expr"],
        "rename_collision": rename_collision,
        "disabled_count": disabled_count,
        "after_disable_enabled": after_disable["enabled"],
        "after_disable_disabled_reason": after_disable["disabled_reason"],
        "claimed_id": claimed["id"] if claimed else None,
        "claimed_locked_by": claimed_locked_by,
        "claimed_has_lock_timestamp": claimed_has_lock_timestamp,
        "after_release_locked_by": after_release["locked_by"],
        "after_release_next_run_at": after_release["next_run_at"],
        "updated_run_status": updated_run["status"],
        "updated_run_output": updated_run["output"],
        "run_total": run_total,
        "runs_ids": sorted(r["id"] for r in runs),
        "deleted": deleted,
        "remaining_run_after_cascade": remaining_run,
    }


async def test_async_schedules_match_postgres(pg_db, oracle_db):
    """One scenario covering ticket 14's schedules domain, compared directly."""
    pg_result = await _run_schedules_scenario(pg_db)
    oracle_result = await _run_schedules_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"AsyncOracleDb diverged from AsyncPostgresDb.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )


async def _run_approvals_auth_tokens_scenario(db) -> Dict[str, Any]:
    """Ticket 08/14's domain: the compare-and-swap update guard on
    approvals, and the owner-scoping sentinel exercised for real on
    auth_tokens.user_id.
    """

    def _approval(id_, **overrides):
        d = {
            "id": id_,
            "run_id": "adiff-run-1",
            "session_id": "adiff-session-1",
            "status": "pending",
            "source_type": "tool_call",
            "approval_type": "confirmation",
            "pause_type": "before_call",
            "tool_name": "delete_file",
            "tool_args": {"path": "/tmp/x"},
            "expires_at": None,
            "agent_id": "adiff-agent",
            "team_id": None,
            "workflow_id": None,
            "user_id": "alice",
            "schedule_id": None,
            "schedule_run_id": None,
            "source_name": None,
            "requirements": None,
            "context": None,
            "resolution_data": None,
            "resolved_by": None,
            "resolved_at": None,
            "run_status": None,
        }
        d.update(overrides)
        return d

    await db.create_approval(_approval("adiff-appr-1"))
    await db.create_approval(_approval("adiff-appr-2", user_id="bob", run_id="adiff-run-2"))

    _, pending_total = await db.get_approvals(status="pending")
    pending_count = await db.get_pending_approval_count()

    matched_update = await db.update_approval("adiff-appr-1", expected_status="pending", status="approved")
    diverged_update = await db.update_approval("adiff-appr-1", expected_status="pending", status="rejected")
    after_cas = await db.get_approval("adiff-appr-1")

    run_status_count = await db.update_approval_run_status("adiff-run-1", RunStatus.completed)
    after_run_status = await db.get_approval("adiff-appr-1")

    deleted = await db.delete_approval("adiff-appr-2")
    _, remaining_total = await db.get_approvals()

    await db.upsert_auth_token(
        {"provider": "github", "user_id": None, "service": "oauth", "token_data": {"access_token": "tok-1"}}
    )
    await db.upsert_auth_token(
        {"provider": "github", "user_id": "alice", "service": "oauth", "token_data": {"access_token": "tok-alice"}}
    )
    unowned_token = await db.get_auth_token("github", None, "oauth")
    alice_token = await db.get_auth_token("github", "alice", "oauth")
    alice_token_id_before = alice_token["id"]

    await db.upsert_auth_token(
        {"provider": "github", "user_id": "alice", "service": "oauth", "token_data": {"access_token": "tok-alice-v2"}}
    )
    alice_token_after = await db.get_auth_token("github", "alice", "oauth")

    deleted_token = await db.delete_auth_token("github", "alice", "oauth")
    alice_token_after_delete = await db.get_auth_token("github", "alice", "oauth")
    unowned_token_after_delete = await db.get_auth_token("github", None, "oauth")

    # A second, independent provider exercised with a literal "" user_id
    # (not None) end to end -- the owner-scoping sentinel translation this
    # domain is actually supposed to prove, distinct from the None-input path
    # already covered above.
    await db.upsert_auth_token(
        {"provider": "gitlab", "user_id": "", "service": "oauth", "token_data": {"access_token": "tok-empty"}}
    )
    empty_string_token = await db.get_auth_token("gitlab", "", "oauth")
    deleted_empty_string_token = await db.delete_auth_token("gitlab", "", "oauth")
    empty_string_token_after_delete = await db.get_auth_token("gitlab", "", "oauth")

    return {
        "pending_total": pending_total,
        "pending_count": pending_count,
        "matched_update_status": matched_update["status"] if matched_update else None,
        "diverged_update": diverged_update,
        "after_cas_status": after_cas["status"],
        "run_status_count": run_status_count,
        "after_run_status": after_run_status["run_status"],
        "deleted_approval": deleted,
        "remaining_approval_total": remaining_total,
        "unowned_token_user_id": unowned_token["user_id"],
        "unowned_token_access": unowned_token["token_data"]["access_token"],
        "alice_token_access": alice_token["token_data"]["access_token"],
        "alice_token_id_stable": alice_token_after["id"] == alice_token_id_before,
        "alice_token_access_after_upsert": alice_token_after["token_data"]["access_token"],
        "deleted_token": deleted_token,
        "alice_token_after_delete": alice_token_after_delete,
        "unowned_token_survives_alice_delete": unowned_token_after_delete is not None,
        "empty_string_token_user_id": empty_string_token["user_id"],
        "empty_string_token_access": empty_string_token["token_data"]["access_token"],
        "deleted_empty_string_token": deleted_empty_string_token,
        "empty_string_token_after_delete": empty_string_token_after_delete,
    }


async def test_async_approvals_and_auth_tokens_match_postgres(pg_db, oracle_db):
    """One scenario covering ticket 14's approvals/auth_tokens domain, compared directly."""
    pg_result = await _run_approvals_auth_tokens_scenario(pg_db)
    oracle_result = await _run_approvals_auth_tokens_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"AsyncOracleDb diverged from AsyncPostgresDb.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )


async def _run_tool_results_and_service_accounts_scenario(db) -> Dict[str, Any]:
    """Ticket 11/14's domain: the tool_results offloading index table and
    its session-delete cascade, and service accounts' active-name partial
    uniqueness (a revoked name frees itself for reuse).
    """

    def _tool_result(result_id, session_id, **overrides):
        d = {
            "result_id": result_id,
            "namespace": "adiff",
            "path": f"/{result_id}",
            "session_id": session_id,
            "run_id": "adiff-run-1",
            "tool_call_id": "call-1",
            "tool_name": "search",
            "args_hash": "abc123",
            "content_type": "text/plain",
            "size_bytes": 1000,
            "line_count": 10,
            "preview": "preview text",
            "user_id": None,
            "created_at": 1700000000,
            "expires_at": None,
        }
        d.update(overrides)
        return d

    await db.upsert_tool_result(_tool_result("adiff-r1", "adiff-tr-session"))
    await db.upsert_tool_result(_tool_result("adiff-r2", "adiff-tr-session", created_at=1700000001))
    await db.upsert_tool_result(_tool_result("adiff-r3", "adiff-tr-session-2"))
    await db.upsert_tool_result(_tool_result("adiff-r1", "adiff-tr-session", tool_name="updated"))
    fetched_after_update = await db.get_tool_result("adiff-r1")

    session_results = await db.get_tool_results_for_session("adiff-tr-session")
    session_result_ids = [r["result_id"] for r in session_results]

    deleted_count = await db.delete_tool_results(["adiff-r3"])

    await db.upsert_tool_result(_tool_result("adiff-r-expired", "adiff-tr-session", expires_at=1600000000))
    expired = await db.get_expired_tool_results(1650000000)
    expired_ids = sorted(r["result_id"] for r in expired)

    session = AgentSession(session_id="adiff-tr-session", agent_id="adiff-agent", created_at=1700000000)
    await db.upsert_session(session)
    pre_delete_results = await db.get_tool_results_for_session("adiff-tr-session")
    await db.delete_session("adiff-tr-session")
    post_delete_results = await db.get_tool_results_for_session("adiff-tr-session")

    sa1 = {
        "id": "adiff-sa-1",
        "name": "adiff-ci-bot",
        "user_id": "alice",
        "token_hash": "adiff-hash-1",
        "token_prefix": "sk_ab",
        "scopes": ["read", "write"],
        "created_at": 1700000000,
        "expires_at": None,
        "last_used_at": None,
        "revoked_at": None,
        "created_by": "alice",
    }
    await db.create_service_account(sa1)
    by_hash = await db.get_service_account_by_token_hash("adiff-hash-1")
    by_name = await db.get_service_account_by_name("adiff-ci-bot")

    same_name_rejected = False
    try:
        await db.create_service_account(
            {**sa1, "id": "adiff-sa-2", "token_hash": "adiff-hash-2", "user_id": "bob", "created_by": "bob"}
        )
    except Exception:
        same_name_rejected = True

    await db.update_service_account("adiff-sa-1", revoked_at=1700000100)
    reused_ok = False
    try:
        await db.create_service_account(
            {**sa1, "id": "adiff-sa-3", "token_hash": "adiff-hash-3", "user_id": "carol", "created_by": "carol"}
        )
        reused_ok = True
    except Exception:
        pass
    active_by_name = await db.get_service_account_by_name("adiff-ci-bot")

    all_accounts, all_total = await db.get_service_accounts(include_revoked=True)
    active_accounts, active_total = await db.get_service_accounts(include_revoked=False)
    all_ids = sorted(a["id"] for a in all_accounts)
    active_ids = sorted(a["id"] for a in active_accounts)

    deleted_sa = await db.delete_service_account("adiff-sa-1")

    return {
        "fetched_after_update_tool_name": fetched_after_update["tool_name"],
        "session_result_ids": sorted(session_result_ids),
        "deleted_tool_results_count": deleted_count,
        "expired_ids": expired_ids,
        "pre_delete_result_count": len(pre_delete_results),
        "post_delete_results": post_delete_results,
        "by_hash_id": by_hash["id"],
        "by_name_id": by_name["id"],
        "same_name_rejected": same_name_rejected,
        "reused_ok": reused_ok,
        "active_by_name_id": active_by_name["id"],
        "all_ids": all_ids,
        "all_total": all_total,
        "active_ids": active_ids,
        "active_total": active_total,
        "deleted_sa": deleted_sa,
    }


async def test_async_tool_results_and_service_accounts_match_postgres(pg_db, oracle_db):
    """One scenario covering ticket 14's tool_results/service_accounts domain, compared directly."""
    pg_result = await _run_tool_results_and_service_accounts_scenario(pg_db)
    oracle_result = await _run_tool_results_and_service_accounts_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"AsyncOracleDb diverged from AsyncPostgresDb.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )
