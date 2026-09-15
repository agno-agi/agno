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

Coverage in this file: the domains tickets 03-09 deliver (sessions, runs,
memory, metrics, knowledge, eval runs, traces, learnings, schedules,
approvals, auth tokens, the component catalog). Later tickets extend this
file with their own domains as they land, rather than each inventing a
separate differential suite.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine, text

from agno.db.base import (
    ComponentArchivedError,
    ComponentCycleError,
    ComponentDependencyError,
    ComponentDraftRequiredError,
    ComponentLastConfigError,
    ComponentType,
    ComponentVersionConflictError,
)
from agno.db.oracle import OracleDb
from agno.db.postgres import PostgresDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession
from agno.tracing.schemas import Trace

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
        "eval_table": f"diff_eval_{suffix}",
        "traces_table": f"diff_trace_{suffix}",
        "learnings_table": f"diff_learn_{suffix}",
        "schedules_table": f"diff_sched_{suffix}",
        "schedule_runs_table": f"diff_sched_runs_{suffix}",
        "approvals_table": f"diff_appr_{suffix}",
        "auth_tokens_table": f"diff_auth_{suffix}",
        "components_table": f"diff_comp_{suffix}",
        "component_configs_table": f"diff_comp_cfg_{suffix}",
        "component_links_table": f"diff_comp_link_{suffix}",
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


def _run_eval_trace_scenario(db) -> Dict[str, Any]:
    """Ticket 05's domains: eval runs (filtering, rename, ownership transfer)
    and a merged trace (the one path with real cross-backend merge logic --
    Postgres does it in one SQL statement, Oracle in Python; this is where a
    divergence between the two approaches would actually show up).
    """
    from agno.db.schemas.evals import EvalRunRecord, EvalType

    for i, (uid, eval_type) in enumerate(
        [("alice", EvalType.ACCURACY), ("alice", EvalType.RELIABILITY), (None, EvalType.ACCURACY)]
    ):
        run = EvalRunRecord(
            run_id=f"diff-eval-{i}", eval_type=eval_type, eval_data={"score": i}, eval_input={}, agent_id="diff-agent"
        )
        db.create_eval_run(run)
        if uid is not None:
            db.update_eval_run_user_id(f"diff-eval-{i}", uid)

    _, alice_total = db.get_eval_runs(user_id="alice", deserialize=False)
    db.rename_eval_run("diff-eval-0", "renamed")
    renamed = db.get_eval_run("diff-eval-0", deserialize=False)
    db.delete_eval_run("diff-eval-2")
    _, remaining_total = db.get_eval_runs(deserialize=False)

    trace_id = "diff-trace-1"
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trace_a = Trace(
        trace_id=trace_id,
        name="agent.run",
        status="OK",
        start_time=base,
        end_time=base + timedelta(seconds=2),
        duration_ms=2000,
        total_spans=0,
        error_count=0,
        run_id="diff-run-a",
        session_id=None,
        user_id="alice",
        agent_id="diff-agent",
        team_id=None,
        workflow_id=None,
        created_at=base,
    )
    db.upsert_trace(trace_a)
    # A wider, lower-priority (no agent/team/workflow) update: must widen the
    # window and recompute duration, but not rename or clobber context.
    trace_b = Trace(
        trace_id=trace_id,
        name="child.span",
        status="OK",
        start_time=base - timedelta(seconds=1),
        end_time=base + timedelta(seconds=5),
        duration_ms=1,
        total_spans=0,
        error_count=0,
        run_id=None,
        session_id=None,
        user_id=None,
        agent_id=None,
        team_id=None,
        workflow_id=None,
        created_at=base,
    )
    db.upsert_trace(trace_b)
    merged = db.get_trace(trace_id=trace_id)

    return {
        "alice_eval_total": alice_total,
        "renamed_name": renamed["name"],
        "remaining_eval_total": remaining_total,
        "merged_trace_name": merged.name,
        "merged_trace_run_id": merged.run_id,
        "merged_trace_duration_ms": merged.duration_ms,
    }


def test_eval_and_trace_merge_matches_postgres(pg_db, oracle_db):
    """The trace-merge comparison matters more than most: Postgres computes
    the merge in one SQL statement (GREATEST/LEAST/EXTRACT EPOCH), Oracle
    replicates it in Python under a row lock. Comparing the two backends'
    actual merged output is what proves the two approaches agree, not just
    that each one runs without error.
    """
    pg_result = _run_eval_trace_scenario(pg_db)
    oracle_result = _run_eval_trace_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"Oracle diverged from Postgres.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )


def _run_learnings_scenario(db) -> Dict[str, Any]:
    """Ticket 06's domain: search matching (the one path Oracle implements
    via Python-side regex translation of Postgres's CAST+ILIKE, per that
    ticket's own design decision) and per-owner listing/stats.
    """
    db.upsert_learning(
        id="diff-learning-1", learning_type="user_profile", content={"summary": "alice_chen likes tea"}, user_id="alice"
    )
    db.upsert_learning(
        id="diff-learning-2", learning_type="session_context", content={"note": "bob prefers dark mode"}, user_id="bob"
    )
    db.upsert_learning(
        id="diff-learning-3", learning_type="user_profile", content={"summary": "shared note"}, user_id=None
    )

    space_underscore_match = sorted(r["learning_id"] for r in db.search_learnings(query="alice chen"))
    case_insensitive_match = sorted(r["learning_id"] for r in db.search_learnings(query="DARK MODE"))
    no_match = db.search_learnings(query="nonexistent-zzz")

    alice_learnings = sorted(r["learning_id"] for r in db.get_learnings(user_id="alice"))
    _, list_total = db.list_learnings(user_id="alice", include_global=True)

    stats, stats_total = db.get_learnings_user_stats()
    stats_user_ids = sorted(s["user_id"] for s in stats)

    db.update_learning("diff-learning-1", content={"summary": "updated"})
    updated = db.get_learning_by_id("diff-learning-1")

    deleted_count = db.delete_user_learnings("bob")
    _, remaining_total = db.list_learnings()

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


def test_learnings_match_postgres(pg_db, oracle_db):
    """One scenario covering ticket 06's domain, compared directly."""
    pg_result = _run_learnings_scenario(pg_db)
    oracle_result = _run_learnings_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"Oracle diverged from Postgres.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )


def _run_schedules_scenario(db) -> Dict[str, Any]:
    """Ticket 07's domain: schedules and schedule runs -- uniqueness across
    the three owner-bucket states, generic update, provenance stamping,
    target-cascade disable, claim/release, and cascade delete into
    schedule_runs.

    Concurrent claim's exactly-one-winner property is proven separately
    (threaded, against a live Oracle server only, in
    tests/integration/db/test_run_index_race.py's sibling script) since it
    says nothing about cross-backend equivalence -- it doesn't belong in a
    differential comparison. Wall-clock-derived fields the adapters set
    internally (claim/release's own ``locked_at``/``updated_at`` via
    ``int(time.time())``) are deliberately excluded from the comparison
    below: they are not guaranteed to land on the identical second across
    two sequential backend runs, and comparing them would test the clock,
    not the adapter.
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
    # Each schedule gets its own endpoint: disable_schedules_for_target also
    # matches generically by endpoint (across owners, by design), and a
    # shared endpoint across these rows would disable more than the
    # provenance-tagged one the test below means to exercise.
    db.create_schedule(
        {"id": "diff-sched-1", "name": "daily-report", "user_id": "alice", "endpoint": "/agents/sched-1/runs", **base}
    )
    db.create_schedule(
        {"id": "diff-sched-2", "name": "daily-report", "user_id": "bob", "endpoint": "/agents/sched-2/runs", **base}
    )
    db.create_schedule(
        {"id": "diff-sched-3", "name": "daily-report", "user_id": None, "endpoint": "/agents/sched-3/runs", **base}
    )
    db.create_schedule(
        {"id": "diff-sched-4", "name": "other-name", "user_id": "alice", "endpoint": "/agents/sched-4/runs", **base}
    )

    by_name_alice = db.get_schedule_by_name("daily-report", user_id="alice")["id"]
    by_name_unowned = db.get_schedule_by_name("daily-report", user_id=None)["id"]

    same_owner_collision = False
    try:
        db.create_schedule({"id": "diff-sched-1-dup", "name": "daily-report", "user_id": "alice", **base})
    except Exception:
        same_owner_collision = True

    unowned_collision = False
    try:
        db.create_schedule({"id": "diff-sched-3-dup", "name": "daily-report", "user_id": None, **base})
    except Exception:
        unowned_collision = True

    _, alice_total = db.get_schedules(user_id="alice")
    _, all_total = db.get_schedules()

    updated = db.update_schedule("diff-sched-1", cron_expr="0 0 * * *")

    rename_collision = False
    try:
        db.update_schedule("diff-sched-4", name="daily-report", user_id="alice")
    except Exception:
        rename_collision = True

    db.stamp_schedule_provenance("diff-sched-2", managed_by="system", target_type="agent", target_id="diff-agent")
    disabled_count = db.disable_schedules_for_target("agent", "diff-agent")
    after_disable = db.get_schedule("diff-sched-2")

    claimed = db.claim_due_schedule("diff-worker-1")
    claimed_locked_by = claimed["locked_by"] if claimed else None
    claimed_has_lock_timestamp = claimed is not None and claimed["locked_at"] is not None
    db.release_schedule(claimed["id"], next_run_at=1800000000)
    after_release = db.get_schedule(claimed["id"])

    db.create_schedule_run(
        {
            "id": "diff-run-1",
            "schedule_id": "diff-sched-3",
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
    updated_run = db.update_schedule_run("diff-run-1", status="completed", output={"ok": True})
    runs, run_total = db.get_schedule_runs("diff-sched-3")

    deleted = db.delete_schedule("diff-sched-3")
    remaining_run = db.get_schedule_run("diff-run-1")

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


def test_schedules_match_postgres(pg_db, oracle_db):
    """One scenario covering ticket 07's domain, compared directly."""
    pg_result = _run_schedules_scenario(pg_db)
    oracle_result = _run_schedules_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"Oracle diverged from Postgres.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )


def _run_approvals_auth_tokens_scenario(db) -> Dict[str, Any]:
    """Ticket 08's domain: the compare-and-swap update guard on approvals,
    and the owner-scoping sentinel exercised for real on auth_tokens.user_id
    -- a NOT NULL column where Postgres itself already stores "" for the
    unowned case (to satisfy its own unique constraint), which is exactly
    the value Oracle's empty-string-is-null folding would otherwise destroy.
    """

    def _approval(id_, **overrides):
        d = {
            "id": id_,
            "run_id": "diff-run-1",
            "session_id": "diff-session-1",
            "status": "pending",
            "source_type": "tool_call",
            "approval_type": "confirmation",
            "pause_type": "before_call",
            "tool_name": "delete_file",
            "tool_args": {"path": "/tmp/x"},
            "expires_at": None,
            "agent_id": "diff-agent",
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

    db.create_approval(_approval("diff-appr-1"))
    db.create_approval(_approval("diff-appr-2", user_id="bob", run_id="diff-run-2"))

    _, pending_total = db.get_approvals(status="pending")
    pending_count = db.get_pending_approval_count()

    matched_update = db.update_approval("diff-appr-1", expected_status="pending", status="approved")
    diverged_update = db.update_approval("diff-appr-1", expected_status="pending", status="rejected")
    after_cas = db.get_approval("diff-appr-1")

    run_status_count = db.update_approval_run_status("diff-run-1", RunStatus.completed)
    after_run_status = db.get_approval("diff-appr-1")

    deleted = db.delete_approval("diff-appr-2")
    _, remaining_total = db.get_approvals()

    # auth_tokens: None owner, a named owner, and an upsert-in-place that must
    # not create a second row nor change the stored id.
    db.upsert_auth_token(
        {"provider": "github", "user_id": None, "service": "oauth", "token_data": {"access_token": "tok-1"}}
    )
    db.upsert_auth_token(
        {"provider": "github", "user_id": "alice", "service": "oauth", "token_data": {"access_token": "tok-alice"}}
    )
    unowned_token = db.get_auth_token("github", None, "oauth")
    alice_token = db.get_auth_token("github", "alice", "oauth")
    alice_token_id_before = alice_token["id"]

    db.upsert_auth_token(
        {"provider": "github", "user_id": "alice", "service": "oauth", "token_data": {"access_token": "tok-alice-v2"}}
    )
    alice_token_after = db.get_auth_token("github", "alice", "oauth")

    deleted_token = db.delete_auth_token("github", "alice", "oauth")
    alice_token_after_delete = db.get_auth_token("github", "alice", "oauth")
    unowned_token_after_delete = db.get_auth_token("github", None, "oauth")

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
    }


def test_approvals_and_auth_tokens_match_postgres(pg_db, oracle_db):
    """One scenario covering ticket 08's domain, compared directly."""
    pg_result = _run_approvals_auth_tokens_scenario(pg_db)
    oracle_result = _run_approvals_auth_tokens_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"Oracle diverged from Postgres.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )


def _run_components_scenario(db) -> Dict[str, Any]:
    """Ticket 09's domain: the component catalog's optimistic concurrency
    guard, all six typed exceptions, composite-key enforcement and cycle
    detection -- compared directly against PostgreSQL, the only reference
    implementation this domain has (no MySQL counterpart).
    """
    component_a, config_a = db.create_component_with_config(
        component_id="diff-agent-a",
        component_type=ComponentType.AGENT,
        name="Agent A",
        config={"model": "gpt-5.6-luna"},
        stage="draft",
    )
    published_v1 = db.upsert_config("diff-agent-a", version=1, stage="published")
    published_v2 = db.upsert_config("diff-agent-a", config={"model": "v2"}, stage="published")

    version_conflict = False
    try:
        db.set_current_version("diff-agent-a", version=1, expected_current_version=99)
    except ComponentVersionConflictError:
        version_conflict = True
    after_failed_cas = db.get_component("diff-agent-a")["current_version"]

    rolled_back = db.set_current_version("diff-agent-a", version=1, expected_current_version=2)
    after_rollback = db.get_component("diff-agent-a")["current_version"]

    component_b, _ = db.create_component_with_config(
        component_id="diff-agent-b", component_type=ComponentType.AGENT, name="B", config={"x": 1}, stage="draft"
    )
    db.delete_component("diff-agent-b", hard_delete=False)
    archived_error = False
    try:
        db.upsert_config("diff-agent-b", config={"y": 2}, stage="draft")
    except ComponentArchivedError:
        archived_error = True
    db.restore_component("diff-agent-b")
    restored_deleted_at = db.get_component("diff-agent-b")["deleted_at"]

    component_c, config_c = db.create_component_with_config(
        component_id="diff-team-c",
        component_type=ComponentType.TEAM,
        name="Team C",
        config={"members": ["diff-agent-a"]},
        stage="published",
        links=[
            {
                "link_kind": "member",
                "link_key": "m0",
                "child_component_id": "diff-agent-a",
                "child_version": 2,
                "position": 0,
            }
        ],
    )
    dependents = sorted(d["parent_component_id"] for d in db.get_dependents("diff-agent-a"))

    dependency_error = False
    try:
        db.delete_component("diff-agent-a", hard_delete=False)
    except ComponentDependencyError:
        dependency_error = True

    cycle_error = False
    try:
        db.upsert_config(
            "diff-agent-a",
            config={"model": "v3"},
            stage="draft",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "back",
                    "child_component_id": "diff-team-c",
                    "child_version": 1,
                    "position": 0,
                }
            ],
        )
    except ComponentCycleError:
        cycle_error = True

    draft_required_error = False
    try:
        db.delete_config("diff-agent-a", version=1)
    except ComponentDraftRequiredError:
        draft_required_error = True

    component_d, _ = db.create_component_with_config(
        component_id="diff-agent-d", component_type=ComponentType.AGENT, name="D", config={"x": 1}, stage="draft"
    )
    last_config_error = False
    try:
        db.delete_config("diff-agent-d", version=1)
    except ComponentLastConfigError:
        last_config_error = True

    db.upsert_config("diff-agent-d", config={"x": 2}, stage="draft")
    deleted_config = db.delete_config("diff-agent-d", version=1)
    remaining_configs = sorted(c["version"] for c in db.list_configs("diff-agent-d"))

    pk_violation = False
    try:
        configs_table = db._get_table(table_type="component_configs")
        with db.Session() as sess, sess.begin():
            sess.execute(
                configs_table.insert().values(
                    component_id="diff-agent-d",
                    version=2,
                    label=None,
                    stage="draft",
                    config={},
                    notes=None,
                    created_at=0,
                )
            )
    except Exception:
        pk_violation = True

    fk_violation = False
    try:
        links_table = db._get_table(table_type="component_links")
        with db.Session() as sess, sess.begin():
            sess.execute(
                links_table.insert().values(
                    parent_component_id="diff-agent-d",
                    parent_version=999,
                    link_kind="member",
                    link_key="bad",
                    child_component_id="diff-agent-a",
                    child_version=2,
                    position=0,
                    meta=None,
                    created_at=0,
                )
            )
    except Exception:
        fk_violation = True

    graph = db.load_component_graph("diff-team-c")
    graph_child_id = graph["children"][0]["graph"]["component"]["component_id"]

    _, list_total = db.list_components(component_type=ComponentType.AGENT)

    latest_bulk = db.get_latest_configs({"diff-agent-a", "diff-agent-d", "does-not-exist"})

    hard_deleted = db.delete_component("diff-team-c", hard_delete=True, require_no_dependents=False)
    team_c_gone = db.get_component("diff-team-c", include_deleted=True)

    return {
        "component_a_current_version": component_a["current_version"],
        "config_a_stage": config_a["stage"],
        "published_v1_stage": published_v1["stage"],
        "published_v2_version": published_v2["version"],
        "version_conflict_raised": version_conflict,
        "after_failed_cas": after_failed_cas,
        "rolled_back": rolled_back,
        "after_rollback": after_rollback,
        "archived_error_raised": archived_error,
        "restored_deleted_at": restored_deleted_at,
        "config_c_stage": config_c["stage"],
        "dependents": dependents,
        "dependency_error_raised": dependency_error,
        "cycle_error_raised": cycle_error,
        "draft_required_error_raised": draft_required_error,
        "last_config_error_raised": last_config_error,
        "deleted_config": deleted_config,
        "remaining_configs": remaining_configs,
        "pk_violation_raised": pk_violation,
        "fk_violation_raised": fk_violation,
        "graph_child_id": graph_child_id,
        "list_total_at_least_three": list_total >= 3,
        "latest_bulk_agent_a_version": latest_bulk["diff-agent-a"]["version"],
        "latest_bulk_agent_d_version": latest_bulk["diff-agent-d"]["version"],
        "latest_bulk_missing": latest_bulk["does-not-exist"],
        "hard_deleted": hard_deleted,
        "team_c_gone": team_c_gone,
    }


def test_components_match_postgres(pg_db, oracle_db):
    """One scenario covering ticket 09's domain, compared directly."""
    pg_result = _run_components_scenario(pg_db)
    oracle_result = _run_components_scenario(oracle_db)

    assert oracle_result == pg_result, (
        f"Oracle diverged from Postgres.\nPostgres: {pg_result}\nOracle:   {oracle_result}"
    )
