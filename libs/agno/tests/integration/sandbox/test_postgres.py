"""Real PostgreSQL fencing and atomic recovery publication; no model calls."""

import asyncio
import os
import threading
import time
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, delete, event, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from agno.db.base import SessionType
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.sandbox.base import SandboxError, SandboxHandle
from agno.sandbox.checkpoint import CheckpointRef
from agno.sandbox.postgres import (
    SandboxLeaseLost,
    SandboxRunFinished,
    SandboxSessionBusy,
    _SandboxStore,
)
from agno.session import AgentSession

URL = os.environ.get("AGNO_TEST_SANDBOX_DB_URL")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="Set AGNO_TEST_SANDBOX_DB_URL")]
REF = CheckpointRef("a" * 64, 10240)


@pytest_asyncio.fixture(params=[PostgresDb, AsyncPostgresDb])
async def store(request):
    db = new_db(request.param, uuid4().hex[:12])
    store = _SandboxStore(db)
    yield store
    await store._transaction(lambda c: [table.drop(c) for table in (store.bindings, store.runs, store.sessions)])
    await dispose(db)


def new_db(adapter, suffix):
    return adapter(
        db_url=URL,
        session_table="sb_sessions_" + suffix,
        runs_table="sb_runs_" + suffix,
        sandbox_table="sb_bindings_" + suffix,
    )


async def dispose(db):
    if isinstance(db, AsyncPostgresDb):
        await db.db_engine.dispose()
    else:
        db.db_engine.dispose()


async def seed(store, run_id="run", session_id="session", attempt=None, created_at=1):
    def write(c):
        if c.execute(select(store.sessions).where(store.sessions.c.session_id == session_id)).first() is None:
            c.execute(
                store.sessions.insert().values(
                    session_id=session_id,
                    session_type="agent",
                    agent_id="agent",
                    user_id="user",
                    session_data={"trusted": "keep"},
                    created_at=created_at,
                )
            )
        c.execute(
            store.runs.insert().values(
                run_id=run_id,
                session_id=session_id,
                run_type="agent",
                agent_id="agent",
                user_id="user",
                status="RUNNING",
                created_at=1,
                run_data={
                    "run_id": run_id,
                    "session_id": session_id,
                    "agent_id": "agent",
                    "user_id": "user",
                    "status": "RUNNING",
                    "queue_attempt": attempt,
                    "input": {"input_content": "hello"},
                    "metadata": {"service": "keep"},
                },
            )
        )

    await store._transaction(write)


async def claim(store, **kwargs):
    return await store.aclaim(
        **{"agent_id": "agent", "session_id": "session", "user_id": "user", "run_id": "run", "owner": "owner", **kwargs}
    )


def computer(state):
    return SandboxHandle("ref", "name", "agent", "session", state.record["generation"], "running", "digest")


def result(lease):
    return {
        "type": "execution_finished",
        "run": {
            "run_id": lease.run_id,
            "session_id": lease.session_id,
            "agent_id": lease.agent_id,
            "user_id": lease.user_id,
            "status": "COMPLETED",
            "content": "done",
        },
        "session": {
            "session_id": lease.session_id,
            "user_id": lease.user_id,
            "session_data": {"trusted": "replace", "native_id": "native"},
        },
    }


async def staged(store):
    await seed(store)
    state = await claim(store)
    await store.aset_computer(state.lease, computer(state))
    await store.astage_result(state.lease, result(state.lease))
    return state.lease


async def rows(store):
    return await store._transaction(
        lambda c: tuple(
            dict(c.execute(select(t)).mappings().one()) for t in (store.runs, store.sessions, store.bindings)
        )
    )


async def test_independent_instances_have_one_owner(store):
    await seed(store)
    other_db = new_db(type(store.db), store.db.session_table_name.removeprefix("sb_sessions_"))
    other = _SandboxStore(other_db)
    outcomes = await asyncio.gather(claim(store), claim(other, owner="other"), return_exceptions=True)
    assert sum(isinstance(x, SandboxSessionBusy) for x in outcomes) == 1
    winner = next(x for x in outcomes if not isinstance(x, Exception))
    again = await claim(store, owner=winner.lease.owner)
    assert again.lease == winner.lease
    assert again.record["execution_id"] == winner.record["execution_id"]
    await seed(store, run_id="second")
    with pytest.raises(SandboxSessionBusy):
        await claim(store, run_id="second")
    await seed(store, run_id="parallel", session_id="parallel")
    assert (await claim(store, run_id="parallel", session_id="parallel")).record["phase"] == "executing"
    await dispose(other_db)


@pytest.mark.parametrize("adapter", [PostgresDb, AsyncPostgresDb])
async def test_tables_are_created_on_first_use_by_racing_processes(adapter):
    suffix = uuid4().hex[:12]
    dbs = [new_db(adapter, suffix) for _ in range(4)]
    stores = [_SandboxStore(db) for db in dbs]
    try:
        await asyncio.gather(*(store._ensure_tables() for store in stores))
        await seed(stores[0])
        state = await claim(stores[1])
        assert (await stores[2].aget(state.lease)).lease == state.lease
    finally:
        await stores[0]._transaction(
            lambda c: [table.drop(c) for table in (stores[0].bindings, stores[0].runs, stores[0].sessions)]
        )
        for db in dbs:
            await dispose(db)


async def test_generation_survives_json_number_precision(store):
    await seed(store)
    state = await claim(store)
    # JavaScript readers round integers above 2**53, so two generations could compare equal.
    assert 0 < state.record["generation"] < 2**53


async def test_bindings_table_serves_one_session_table(store):
    await store._ensure_tables()
    # A second session table pointed at the same bindings table, whose foreign key names the first.
    other = type(store.db)(
        db_url=URL, session_table=store.db.session_table_name + "_other", sandbox_table=store.db.sandbox_table_name
    )
    second = _SandboxStore(other)
    try:
        with pytest.raises(SandboxError, match="session table"):
            await second._ensure_tables()
    finally:
        runs = await second._table("runs", other.runs_table_name)
        sessions = await second._table("sessions", other.session_table_name)
        await store._transaction(lambda c: [table.drop(c) for table in (runs, sessions)])
        await dispose(other)


async def test_wrong_owner_rolls_back_first_binding(store):
    await seed(store)
    with pytest.raises(SandboxLeaseLost):
        await claim(store, user_id="attacker")
    assert await store._transaction(lambda c: c.execute(select(store.bindings)).first()) is None
    state = await claim(store)
    with pytest.raises(SandboxLeaseLost):
        await store.aget(replace(state.lease, agent_id="wrong"))


async def test_expiry_takeover_preserves_execution_and_fences_old_owner(store):
    await seed(store)
    old = await claim(store)
    await store._transaction(
        lambda c: c.execute(update(store.bindings).values(expires_at=func.clock_timestamp() - timedelta(seconds=1)))
    )
    with pytest.raises(SandboxLeaseLost):
        await store.arenew(old.lease)
    new = await claim(store, owner="new")
    assert new.lease.epoch == old.lease.epoch + 1
    assert new.record == old.record
    with pytest.raises(SandboxLeaseLost):
        await store.aset_computer(old.lease, computer(old))
    with pytest.raises(SandboxLeaseLost):
        await store.abegin_stop(old.lease, status="CANCELLED", reason="late")


async def test_new_queue_attempt_fences_live_lease_and_preserves_finalization(store):
    await seed(store, attempt=1)
    old = await claim(store, queue_attempt=1)
    await store.aset_computer(old.lease, computer(old))
    await store.astage_result(old.lease, result(old.lease))
    await store._transaction(
        lambda c: c.execute(
            update(store.runs).values(run_data={**result(old.lease)["run"], "status": "RUNNING", "queue_attempt": 2})
        )
    )
    new = await claim(store, owner="new", queue_attempt=2)
    assert new.record["phase"] == "finalizing"
    assert new.record["execution_id"] == old.record["execution_id"]
    with pytest.raises(SandboxLeaseLost):
        await store.astage_checkpoint(old.lease, REF)
    await store.astage_checkpoint(new.lease, REF)
    await store.aconfirm_stopped(new.lease, "ref")
    assert (await store.acommit(new.lease))["queue_attempt"] == 2


async def test_staging_is_not_completion_and_commit_is_atomic(store):
    lease = await staged(store)
    run, session, binding = await rows(store)
    assert run["status"] == "RUNNING"
    assert "sandbox" not in session["session_data"]
    with pytest.raises(SandboxError, match="recovery bytes"):
        await store.acommit(lease)
    with pytest.raises(SandboxError, match="checkpoint"):
        await store.aconfirm_stopped(lease, "ref")
    await store.astage_checkpoint(lease, REF)
    with pytest.raises(SandboxError, match="cleanup"):
        await store.acommit(lease)
    await store.aconfirm_stopped(lease, "ref")
    await store.acommit(lease)
    run, session, binding = await rows(store)
    assert run["status"] == "COMPLETED"
    assert session["session_data"]["trusted"] == "keep"
    assert session["session_data"]["sandbox"]["native"]["native_id"] == "native"
    assert session["session_data"]["sandbox"]["checkpoint"] == binding["record"]["checkpoint"]
    assert binding["owner"] is None and binding["record"]["phase"] == "idle"
    with pytest.raises(SandboxRunFinished) as caught:
        await claim(store)
    assert caught.value.run == run["run_data"]  # lost commit acknowledgement


async def test_durable_completion_walkthrough(store):
    """One session, two turns, the way the coordinator drives the store.

    Turn 1 finishes in the sandbox, but its run stays RUNNING until the checkpoint is staged
    and the computer is confirmed stopped; one transaction then completes the run and points
    the session at the checkpoint. During turn 2 the session is renamed mid-turn (what the
    AgentOS session PATCH does) without touching the lease, the coordinator stops renewing,
    a second coordinator takes the turn over and the first one's late write is refused, and
    cancelling the turn keeps turn 1's checkpoint as the recovery point.
    """
    await seed(store)
    state = await claim(store, owner="first")
    await store.aset_computer(state.lease, computer(state))
    state = await store.astage_result(state.lease, result(state.lease))
    run, session, _ = await rows(store)
    assert run["status"] == "RUNNING" and "sandbox" not in session["session_data"], "staged is not completed"
    state = await store.astage_checkpoint(state.lease, REF)
    state = await store.aconfirm_stopped(state.lease, "ref")
    assert (await store.acommit(state.lease))["status"] == "COMPLETED"
    run, session, binding = await rows(store)
    assert run["status"] == "COMPLETED"
    assert session["session_data"]["sandbox"]["checkpoint"]["sha256"] == REF.sha256
    assert binding["record"]["checkpoint"]["sha256"] == REF.sha256

    await seed(store, run_id="run-2")
    stalled = await claim(store, run_id="run-2", owner="stalled")
    # The session PATCH route reads the session, edits it and upserts the whole row back.
    if isinstance(store.db, AsyncPostgresDb):
        renamed = await store.db.get_session(session_id="session", session_type=SessionType.AGENT)
    else:
        renamed = await asyncio.to_thread(store.db.get_session, session_id="session", session_type=SessionType.AGENT)
    renamed.session_data = {**(renamed.session_data or {}), "session_name": "renamed"}
    if isinstance(store.db, AsyncPostgresDb):
        await store.db.upsert_session(renamed)
    else:
        await asyncio.to_thread(store.db.upsert_session, renamed)
    assert (await store.aget(stalled.lease)).lease == stalled.lease, "a session edit mid-turn keeps the lease"
    await store._transaction(
        lambda c: c.execute(update(store.bindings).values(expires_at=func.clock_timestamp() - timedelta(seconds=1)))
    )
    takeover = await claim(store, run_id="run-2", owner="second")
    assert takeover.lease.epoch == stalled.lease.epoch + 1
    with pytest.raises(SandboxLeaseLost):
        await store.aset_computer(stalled.lease, computer(stalled))

    state = await store.abegin_stop(takeover.lease, status="CANCELLED", reason="Cancelled by the user")
    assert state.record["phase"] == "stopping", "the stop intent is recorded before compute is touched"
    assert (await store.afinish_stop(state.lease))["status"] == "CANCELLED"
    statuses, session, binding = await store._transaction(
        lambda c: (
            dict(c.execute(select(store.runs.c.run_id, store.runs.c.status)).all()),
            dict(c.execute(select(store.sessions)).mappings().one()),
            dict(c.execute(select(store.bindings)).mappings().one()),
        )
    )
    assert statuses == {"run": "COMPLETED", "run-2": "CANCELLED"}
    assert session["session_data"]["session_name"] == "renamed"
    assert session["session_data"]["sandbox"]["checkpoint"]["sha256"] == REF.sha256, "turn 1 stays the recovery point"
    assert binding["record"]["checkpoint"]["sha256"] == REF.sha256 and binding["record"]["phase"] == "idle"


async def test_write_failure_rolls_back_run_and_checkpoint_publication(store):
    lease = await staged(store)
    await store.astage_checkpoint(lease, REF)
    await store.aconfirm_stopped(lease, "ref")
    engine = store.db.db_engine.sync_engine if isinstance(store.db, AsyncPostgresDb) else store.db.db_engine

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE") and store.sessions.name in statement:
            raise RuntimeError("injected terminal persistence failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            await store.acommit(lease)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    run, session, binding = await rows(store)
    assert run["status"] == "RUNNING" and "sandbox" not in session["session_data"]
    assert binding["record"]["phase"] == "finalizing"
    assert (await store.acommit(lease))["status"] == "COMPLETED"


async def test_stale_previous_turn_cannot_overwrite_new_turn(store):
    lease = await staged(store)
    await store.astage_checkpoint(lease, REF)
    await store.aconfirm_stopped(lease, "ref")
    await store.acommit(lease)
    await seed(store, run_id="second")
    new = await claim(store, run_id="second")
    assert new.record["stopped_ref"] is None
    with pytest.raises(SandboxLeaseLost):
        await store.acommit(lease)
    assert new.record["checkpoint"]["sha256"] == REF.sha256


async def test_recreated_session_starts_a_fresh_binding(store):
    lease = await staged(store)
    await store.astage_checkpoint(lease, REF)
    await store._transaction(lambda c: c.execute(delete(store.sessions)))
    bindings = await store._transaction(lambda c: c.execute(select(store.bindings)).all())
    assert bindings == []
    with pytest.raises(SandboxLeaseLost):
        await claim(store)
    # Same session id, created_at, run id and owner: nothing but the binding row tells them apart.
    await seed(store)
    fresh = await claim(store)
    assert fresh.record["phase"] == "executing" and fresh.record["result"] is None
    assert fresh.record["checkpoint"] is None and fresh.record["staged_checkpoint"] is None
    with pytest.raises(SandboxLeaseLost):
        await store.aget(lease)
    with pytest.raises(SandboxLeaseLost):
        await store.abegin_stop(lease, status="CANCELLED", reason="stale coordinator")


async def test_cancelled_call_waits_for_its_sync_transaction(store):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("AsyncPostgresDb runs the transaction on the event loop and rolls it back on cancellation")
    finished = []

    def slow(connection):
        time.sleep(0.5)
        finished.append(True)

    await store._ensure_tables()
    task = asyncio.create_task(store._transaction(slow))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished


async def test_shutdown_intent_is_durable_and_requires_cleanup(store):
    await seed(store)
    state = await claim(store)
    await store.aset_computer(state.lease, computer(state))
    with pytest.raises(SandboxError, match="intent"):
        await store.aconfirm_stopped(state.lease, "ref")
    await store.abegin_stop(state.lease, status="CANCELLED", reason="requested")
    with pytest.raises(SandboxError, match="cleanup"):
        await store.afinish_stop(state.lease)
    with pytest.raises(SandboxError):
        await store.astage_result(state.lease, result(state.lease))
    await store.aconfirm_stopped(state.lease, "ref")
    assert (await store.afinish_stop(state.lease))["status"] == "CANCELLED"
    _, session, binding = await rows(store)
    assert "sandbox" not in session["session_data"] and binding["record"]["checkpoint"] is None


@pytest.mark.parametrize("stored", [None, "PAUSED"])
async def test_cancelled_stop_records_the_executing_stage(store, stored):
    await seed(store, attempt=1)
    if stored is not None:
        run_data = await store._transaction(lambda c: c.execute(select(store.runs.c.run_data)).scalar_one())
        await store._transaction(
            lambda c: c.execute(update(store.runs).values(run_data={**run_data, "cancellation_stage": stored}))
        )
    await claim(store, queue_attempt=1)
    # The queue's active path and the coordinator's own cancel both end in afinish_stop.
    stopping = await store._aclaim_stop(
        agent_id="agent",
        session_id="session",
        user_id="user",
        run_id="run",
        queue_attempt=1,
        status="CANCELLED",
        reason="cancelled",
    )
    run = await store.afinish_stop(stopping.lease)
    assert run["cancellation_stage"] == (stored or "EXECUTING")
    assert (await rows(store))[0]["run_data"]["cancellation_stage"] == (stored or "EXECUTING")


async def test_errored_stop_records_no_cancellation_stage(store):
    await seed(store)
    state = await claim(store)
    await store.abegin_stop(state.lease, status="ERROR", reason="failed")
    assert "cancellation_stage" not in await store.afinish_stop(state.lease)


async def test_external_cancellation_wins_over_staged_success(store):
    lease = await staged(store)
    await store.astage_checkpoint(lease, REF)
    await store.aconfirm_stopped(lease, "ref")
    await store._transaction(
        lambda c: c.execute(
            update(store.runs).values(status="CANCELLED", run_data={**result(lease)["run"], "status": "CANCELLED"})
        )
    )
    with pytest.raises(SandboxRunFinished) as caught:
        await store.acommit(lease)
    assert caught.value.run["status"] == "CANCELLED"
    # Cleanup was already confirmed, so the commit itself released the session.
    run, _, binding = await rows(store)
    assert run["status"] == "CANCELLED" and binding["record"]["phase"] == "idle" and binding["owner"] is None
    assert binding["record"]["checkpoint"] is None
    with pytest.raises(SandboxRunFinished):
        await claim(store)


async def test_commit_after_external_completion_releases_the_session(store):
    lease = await staged(store)
    await store.astage_checkpoint(lease, REF)
    await store.aconfirm_stopped(lease, "ref")
    await finish_elsewhere(store, "COMPLETED")
    with pytest.raises(SandboxRunFinished) as caught:
        await store.acommit(lease)
    # The stored completion stands, and the staged checkpoint is not promoted.
    assert caught.value.run["content"] == "finished elsewhere"
    binding = (await rows(store))[2]
    assert binding["record"]["phase"] == "idle" and binding["record"]["checkpoint"] is None
    await seed(store, run_id="second")
    assert (await claim(store, run_id="second")).record["phase"] == "executing"


async def test_staged_result_is_immutable_and_identity_bound(store):
    lease = await staged(store)
    changed = result(lease)
    changed["session"]["session_data"]["native_id"] = "other"
    with pytest.raises(SandboxError, match="immutable"):
        await store.astage_result(lease, changed)
    with pytest.raises(SandboxError, match="identity"):
        await store.astage_result(lease, result(replace(lease, user_id="other")))


async def test_core_session_upsert_does_not_strand_active_lease(store):
    await seed(store)
    # AgentOS PATCH /sessions reads the session, edits it, and upserts the whole session_data blob.
    stale = AgentSession(
        session_id="session", agent_id="agent", user_id="user", session_data={"session_name": "x"}, created_at=1
    )
    state = await claim(store)
    if isinstance(store.db, AsyncPostgresDb):
        await store.db.upsert_session(stale)
    else:
        await asyncio.to_thread(store.db.upsert_session, stale)
    await store.aset_computer(state.lease, computer(state))
    await store.astage_result(state.lease, result(state.lease))
    await store.astage_checkpoint(state.lease, REF)
    await store.aconfirm_stopped(state.lease, "ref")
    assert (await store.acommit(state.lease))["status"] == "COMPLETED"


async def test_runtime_result_cannot_rewrite_service_fields(store):
    await seed(store)
    state = await claim(store)
    await store.aset_computer(state.lease, computer(state))
    forged = result(state.lease)
    forged["run"].update(
        input={"input_content": "forged"},
        created_at=0,
        parent_run_id="other",
        session_state={"admin": True},
        metadata={"native": "value", "service": "forged"},
    )
    await store.astage_result(state.lease, forged)
    await store.astage_checkpoint(state.lease, REF)
    await store.aconfirm_stopped(state.lease, "ref")
    run = await store.acommit(state.lease)
    assert run["content"] == "done" and run["status"] == "COMPLETED"
    assert run["input"] == {"input_content": "hello"}
    assert "created_at" not in run and "parent_run_id" not in run and "session_state" not in run
    assert run["metadata"]["service"] == "keep"
    assert run["metadata"]["sandbox"]["native_metadata"] == {"native": "value", "service": "forged"}


async def test_cancelled_result_keeps_its_cancellation_stage(store):
    await seed(store)
    state = await claim(store)
    await store.aset_computer(state.lease, computer(state))
    cancelled = result(state.lease)
    cancelled["run"].update(status="CANCELLED", cancellation_stage="tool_call")
    await store.astage_result(state.lease, cancelled)
    await store.astage_checkpoint(state.lease, REF)
    await store.aconfirm_stopped(state.lease, "ref")
    run = await store.acommit(state.lease)
    assert run["status"] == "CANCELLED" and run["cancellation_stage"] == "tool_call"


async def test_stop_keeps_existing_content_and_staged_output(store):
    lease = await staged(store)
    run_data = (await rows(store))[0]["run_data"]
    await store._transaction(
        lambda c: c.execute(update(store.runs).values(run_data={**run_data, "content": "partial"}))
    )
    await store.abegin_stop(lease, status="CANCELLED", reason="Cancelled by the user")
    await store.aconfirm_stopped(lease, "ref")
    run = await store.afinish_stop(lease)
    assert run["status"] == "CANCELLED" and run["content"] == "partial"
    assert run["metadata"]["sandbox"]["runtime_content"] == "done"
    assert run["metadata"]["service"] == "keep"


async def test_sync_api_contract(store):
    if isinstance(store.db, AsyncPostgresDb):
        with pytest.raises(TypeError, match="async"):
            store.claim(agent_id="agent", session_id="session", user_id="user", run_id="run", owner="owner")
    else:
        await seed(store)
        state = await asyncio.to_thread(
            store.claim, agent_id="agent", session_id="session", user_id="user", run_id="run", owner="owner"
        )
        assert (await asyncio.to_thread(store.get, state.lease)).lease == state.lease
        await asyncio.to_thread(store.begin_stop, state.lease, status="ERROR", reason="no compute")
        stopped = await asyncio.to_thread(store.finish_stop, state.lease)
        assert stopped["status"] == "ERROR" and stopped["content"] == "no compute"


async def finish_elsewhere(store, status, content="finished elsewhere"):
    run_data = (await rows(store))[0]["run_data"]
    await store._transaction(
        lambda c: c.execute(
            update(store.runs).values(status=status, run_data={**run_data, "status": status, "content": content})
        )
    )


async def test_stop_after_external_completion_releases_the_session(store):
    lease = await staged(store)
    await store.astage_checkpoint(lease, REF)
    await finish_elsewhere(store, "COMPLETED")
    await store.abegin_stop(lease, status="ERROR", reason="Service run was finished elsewhere")
    await store.aconfirm_stopped(lease, "ref")
    run = await store.afinish_stop(lease)
    # The stored completion stands; the staged checkpoint is not promoted, since nothing ties it to that result.
    assert run["status"] == "COMPLETED" and run["content"] == "finished elsewhere"
    binding = (await rows(store))[2]
    assert binding["record"]["phase"] == "idle" and binding["record"]["checkpoint"] is None
    await seed(store, run_id="second")
    assert (await claim(store, run_id="second")).record["phase"] == "executing"


async def test_regenerated_run_counts_as_finished(store):
    lease = await staged(store)
    await store.astage_checkpoint(lease, REF)
    await store.aconfirm_stopped(lease, "ref")
    await finish_elsewhere(store, "REGENERATED")
    with pytest.raises(SandboxRunFinished):
        await store.acommit(lease)
    assert (await rows(store))[0]["status"] == "REGENERATED"


async def test_regenerated_run_is_not_reopened(store):
    lease = await staged(store)
    await store.astage_checkpoint(lease, REF)
    await store.aconfirm_stopped(lease, "ref")
    await store.acommit(lease)
    await finish_elsewhere(store, "REGENERATED")
    with pytest.raises(SandboxRunFinished):
        await claim(store)


async def test_cancelled_claim_releases_the_session(store):
    await seed(store)
    await store._ensure_tables()
    task = asyncio.create_task(claim(store))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # The claim committed, but its caller never saw the lease: the turn it opened is undone.
    _, _, binding = await rows(store)
    assert binding["owner"] is None and binding["run_id"] is None and binding["expires_at"] is None
    assert binding["record"]["phase"] == "idle"
    state = await claim(store, owner="other")
    assert state.record["phase"] == "executing"


async def test_cancelled_reclaim_keeps_the_run(store):
    lease = await staged(store)
    await store._transaction(
        lambda c: c.execute(update(store.bindings).values(expires_at=func.clock_timestamp() - timedelta(seconds=1)))
    )
    task = asyncio.create_task(claim(store, owner="other"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # A re-claimed turn already ran: only the lease is released, the run stays with the session.
    _, _, binding = await rows(store)
    assert binding["owner"] is None and binding["expires_at"] is None and binding["run_id"] == "run"
    assert binding["record"]["phase"] == "finalizing" and binding["record"]["result"] is not None
    await seed(store, run_id="other-run")
    with pytest.raises(SandboxSessionBusy):
        await claim(store, run_id="other-run", owner="other")
    state = await claim(store, owner="other")
    assert state.lease.epoch > lease.epoch and state.record["result"] is not None


async def test_repeated_cancellation_still_waits_for_its_sync_transaction(store):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("AsyncPostgresDb runs the transaction on the event loop and rolls it back on cancellation")
    finished = []

    def slow(connection):
        time.sleep(0.6)
        finished.append(True)

    await store._ensure_tables()
    task = asyncio.create_task(store._transaction(slow))
    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished


async def test_deleting_a_run_under_an_active_turn_is_refused(store):
    lease = await staged(store)
    delete = store.db.delete_run
    if isinstance(store.db, AsyncPostgresDb):
        assert await delete("run") is False
        assert await store.db.delete_runs(["run"]) is None
    else:
        assert await asyncio.to_thread(delete, "run") is False
        assert await asyncio.to_thread(store.db.delete_runs, ["run"]) is None
    run, _, binding = await rows(store)
    assert run["run_id"] == "run" and binding["run_id"] == "run"
    await store.astage_checkpoint(lease, REF)
    await store.aconfirm_stopped(lease, "ref")
    await store.acommit(lease)
    # Once the turn is committed the binding no longer holds the run.
    if isinstance(store.db, AsyncPostgresDb):
        assert await delete("run")
    else:
        assert await asyncio.to_thread(delete, "run")


async def test_cancelled_first_use_waits_for_table_setup(store, monkeypatch):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("AsyncPostgresDb resolves tables on the event loop")
    finished = []
    get_table = store.db._get_table

    def slow(*args, **kwargs):
        time.sleep(0.5)
        table = get_table(*args, **kwargs)
        finished.append(True)
        return table

    monkeypatch.setattr(store.db, "_get_table", slow)
    task = asyncio.create_task(store._ensure_tables())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished


async def test_session_deletion_waits_for_a_sandbox_operation(store, monkeypatch):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("Interleaves a blocking database call with the store's worker thread")
    await seed(store)
    state = await claim(store)
    service_run = store._service_run
    holding = threading.Event()

    def pause_after_binding(*args, **kwargs):
        # The binding is locked; give a session deletion time to issue its DELETE before the run is.
        holding.set()
        time.sleep(2)
        return service_run(*args, **kwargs)

    monkeypatch.setattr(store, "_service_run", pause_after_binding)
    operation = asyncio.create_task(store.aget(state.lease))
    await asyncio.to_thread(holding.wait, 5)
    deleted = await asyncio.to_thread(store.db.delete_session, "session")
    assert (await operation).lease == state.lease
    assert deleted


async def test_run_deletion_racing_a_sandbox_operation_is_refused_not_deadlocked(store, monkeypatch):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("Interleaves a blocking database call with the store's worker thread")
    await seed(store)
    state = await claim(store)
    service_run = store._service_run
    holding = threading.Event()

    def pause(*args, **kwargs):
        # The store's first locks are held; give the run deletion time to issue its DELETE.
        holding.set()
        time.sleep(2)
        return service_run(*args, **kwargs)

    monkeypatch.setattr(store, "_service_run", pause)
    operation = asyncio.create_task(store.aget(state.lease))
    await asyncio.to_thread(holding.wait, 5)
    # Refused (False) once the store's transaction commits; a deadlock would raise instead.
    assert await asyncio.to_thread(store.db.delete_run, "run") is False
    assert (await operation).lease == state.lease
    assert (await rows(store))[0]["run_id"] == "run"


async def test_bindings_table_in_another_schema_is_refused(store):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("Schema setup uses the sync engine")
    other_schema = "sbx_" + uuid4().hex[:8]
    other = PostgresDb(
        db_url=URL,
        db_schema=other_schema,
        session_table=store.db.session_table_name,
        runs_table=store.db.runs_table_name,
        sandbox_table=store.db.sandbox_table_name,
    )
    await _SandboxStore(other)._ensure_tables()
    await store._table("sessions", store.db.session_table_name)
    await store._table("runs", store.db.runs_table_name)
    # A same-named bindings table in this schema whose keys point at the other schema's tables.
    b, s, r, home = (
        store.db.sandbox_table_name,
        store.db.session_table_name,
        store.db.runs_table_name,
        store.db.db_schema,
    )
    with store.db.db_engine.begin() as connection:
        connection.execute(text(f'CREATE TABLE "{home}"."{b}" (LIKE "{other_schema}"."{b}" INCLUDING DEFAULTS)'))
        connection.execute(text(f'ALTER TABLE "{home}"."{b}" ADD PRIMARY KEY (namespace, session_id)'))
        connection.execute(
            text(
                f'ALTER TABLE "{home}"."{b}" ADD FOREIGN KEY (session_id) REFERENCES "{other_schema}"."{s}" (session_id)'
            )
        )
        connection.execute(
            text(f'ALTER TABLE "{home}"."{b}" ADD FOREIGN KEY (run_id) REFERENCES "{other_schema}"."{r}" (run_id)')
        )
    try:
        with pytest.raises(SandboxError, match="session table"):
            await store._ensure_tables()
    finally:
        with store.db.db_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{other_schema}" CASCADE'))
            connection.execute(text(f'DROP TABLE "{home}"."{b}"'))
        # The fixture's teardown recreates a correct bindings table and drops it.
        store.db._invalidate_table_cache(b)
        other.db_engine.dispose()


async def test_bindings_table_without_its_key_is_refused(store):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("Table setup uses the sync engine")
    sessions = await store._table("sessions", store.db.session_table_name)
    runs = await store._table("runs", store.db.runs_table_name)
    b, home = store.db.sandbox_table_name, store.db.db_schema
    # Right columns and foreign keys, but nothing that makes (namespace, session_id) unique.
    with store.db.db_engine.begin() as connection:
        connection.execute(
            text(
                f'CREATE TABLE "{home}"."{b}" (namespace varchar NOT NULL, session_id varchar NOT NULL '
                f'REFERENCES "{home}"."{sessions.name}" (session_id) ON DELETE CASCADE, agent_id varchar NOT NULL, '
                f'user_id varchar, epoch bigint NOT NULL, owner varchar, run_id varchar REFERENCES "{home}"."{runs.name}" '
                "(run_id), queue_attempt bigint, expires_at timestamptz, record jsonb NOT NULL)"
            )
        )
    try:
        with pytest.raises(SandboxError, match="key"):
            await store._ensure_tables()
    finally:
        with store.db.db_engine.begin() as connection:
            connection.execute(text(f'DROP TABLE "{home}"."{b}"'))
        store.db._invalidate_table_cache(b)


async def test_store_operation_does_not_wait_for_an_ordinary_session_update(store):
    await seed(store)
    state = await claim(store)
    engine = create_engine(URL)
    writer = await asyncio.to_thread(engine.connect)
    transaction = await asyncio.to_thread(writer.begin)
    # An ordinary non-key session write, held open; KEY SHARE must not conflict with it.
    await asyncio.to_thread(
        lambda: writer.execute(
            store.sessions.update().where(store.sessions.c.session_id == "session").values(updated_at=2)
        )
    )
    try:
        operation = asyncio.create_task(store.aget(state.lease))
        await asyncio.sleep(1)
        finished_while_held = operation.done()
    finally:
        await asyncio.to_thread(transaction.commit)
        await asyncio.to_thread(writer.close)
        engine.dispose()
    assert (await operation).lease == state.lease
    assert finished_while_held


async def test_bindings_table_cascading_run_deletes_is_refused(store):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("Table setup uses the sync engine")
    sessions = await store._table("sessions", store.db.session_table_name)
    runs = await store._table("runs", store.db.runs_table_name)
    b, home = store.db.sandbox_table_name, store.db.db_schema
    # Correct key and targets, but deleting a run would silently remove the binding of its active turn.
    with store.db.db_engine.begin() as connection:
        connection.execute(
            text(
                f'CREATE TABLE "{home}"."{b}" (namespace varchar NOT NULL, session_id varchar NOT NULL '
                f'REFERENCES "{home}"."{sessions.name}" (session_id) ON DELETE CASCADE, agent_id varchar NOT NULL, '
                f'user_id varchar, epoch bigint NOT NULL, owner varchar, run_id varchar REFERENCES "{home}"."{runs.name}" '
                "(run_id) ON DELETE CASCADE, queue_attempt bigint, expires_at timestamptz, record jsonb NOT NULL, "
                "PRIMARY KEY (namespace, session_id))"
            )
        )
    try:
        with pytest.raises(SandboxError, match="cascade"):
            await store._ensure_tables()
    finally:
        with store.db.db_engine.begin() as connection:
            connection.execute(text(f'DROP TABLE "{home}"."{b}"'))
        store.db._invalidate_table_cache(b)


async def test_bindings_table_not_cascading_session_deletes_is_refused(store):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("Table setup uses the sync engine")
    sessions = await store._table("sessions", store.db.session_table_name)
    runs = await store._table("runs", store.db.runs_table_name)
    b, home = store.db.sandbox_table_name, store.db.db_schema
    # Correct key and targets, but an idle binding would make deleting its session fail.
    with store.db.db_engine.begin() as connection:
        connection.execute(
            text(
                f'CREATE TABLE "{home}"."{b}" (namespace varchar NOT NULL, session_id varchar NOT NULL '
                f'REFERENCES "{home}"."{sessions.name}" (session_id), agent_id varchar NOT NULL, '
                f'user_id varchar, epoch bigint NOT NULL, owner varchar, run_id varchar REFERENCES "{home}"."{runs.name}" '
                "(run_id), queue_attempt bigint, expires_at timestamptz, record jsonb NOT NULL, "
                "PRIMARY KEY (namespace, session_id))"
            )
        )
    try:
        with pytest.raises(SandboxError, match="cascade"):
            await store._ensure_tables()
    finally:
        with store.db.db_engine.begin() as connection:
            connection.execute(text(f'DROP TABLE "{home}"."{b}"'))
        store.db._invalidate_table_cache(b)


async def test_bindings_table_from_an_earlier_build_names_its_remedy(store):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("Table setup uses the sync engine")
    sessions = await store._table("sessions", store.db.session_table_name)
    await store._table("runs", store.db.runs_table_name)
    b, home = store.db.sandbox_table_name, store.db.db_schema
    # The shape an earlier build of this package created: no foreign key from run_id to the run table.
    with store.db.db_engine.begin() as connection:
        connection.execute(
            text(
                f'CREATE TABLE "{home}"."{b}" (namespace varchar NOT NULL, session_id varchar NOT NULL '
                f'REFERENCES "{home}"."{sessions.name}" (session_id) ON DELETE CASCADE, agent_id varchar NOT NULL, '
                "user_id varchar, epoch bigint NOT NULL, owner varchar, run_id varchar, queue_attempt bigint, "
                "expires_at timestamptz, record jsonb NOT NULL, PRIMARY KEY (namespace, session_id))"
            )
        )
    try:
        with pytest.raises(SandboxError) as refused:
            await store._ensure_tables()
        message = str(refused.value)
        assert f"{home}.{b} does not reference run table {home}.{store.db.runs_table_name}" in message
        assert "drop or rename that table, or pass PostgresDb(sandbox_table=...)" in message
        # Every later call refuses again; nothing was cached as ready.
        with pytest.raises(SandboxError, match="sandbox_table"):
            await store.aprepare({"run_id": "r", "session_id": "s", "agent_id": "agent", "status": "PENDING"})
    finally:
        with store.db.db_engine.begin() as connection:
            connection.execute(text(f'DROP TABLE "{home}"."{b}"'))
        store.db._invalidate_table_cache(b)


async def test_bindings_table_missing_a_column_names_the_same_remedy(store):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("Table setup uses the sync engine")
    sessions = await store._table("sessions", store.db.session_table_name)
    runs = await store._table("runs", store.db.runs_table_name)
    b, home = store.db.sandbox_table_name, store.db.db_schema
    # Right keys, but no queue_attempt column: the adapter's own schema check refuses it.
    with store.db.db_engine.begin() as connection:
        connection.execute(
            text(
                f'CREATE TABLE "{home}"."{b}" (namespace varchar NOT NULL, session_id varchar NOT NULL '
                f'REFERENCES "{home}"."{sessions.name}" (session_id) ON DELETE CASCADE, agent_id varchar NOT NULL, '
                f'user_id varchar, epoch bigint NOT NULL, owner varchar, run_id varchar REFERENCES "{home}"."{runs.name}" '
                "(run_id), expires_at timestamptz, record jsonb NOT NULL, PRIMARY KEY (namespace, session_id))"
            )
        )
    try:
        with pytest.raises(SandboxError, match="does not have the columns") as refused:
            await store._ensure_tables()
        assert "pass PostgresDb(sandbox_table=...)" in str(refused.value)
    finally:
        with store.db.db_engine.begin() as connection:
            connection.execute(text(f'DROP TABLE "{home}"."{b}"'))
        store.db._invalidate_table_cache(b)


async def test_cancelled_duplicate_claim_keeps_the_live_lease(store, monkeypatch):
    if isinstance(store.db, AsyncPostgresDb):
        pytest.skip("AsyncPostgresDb runs the claim on the event loop; a cancel cannot land mid-transaction")
    await seed(store)
    held = await claim(store)
    to_state = store._state

    def slow(row):
        # Inside the duplicate claim's transaction, so the cancel lands before it commits and returns.
        time.sleep(0.5)
        return to_state(row)

    monkeypatch.setattr(store, "_state", slow)
    # Same owner and attempt while the lease is alive: the claim reuses the lease the caller already holds.
    duplicate = asyncio.create_task(claim(store))
    await asyncio.sleep(0.1)
    duplicate.cancel()
    with pytest.raises(asyncio.CancelledError):
        await duplicate
    monkeypatch.setattr(store, "_state", to_state)
    assert (await store.aget(held.lease)).lease == held.lease


async def test_atomic_admission_does_not_leave_a_rejected_run(store):
    await seed(store)
    await claim(store)
    value = {
        **result((await claim(store)).lease)["run"],
        "run_id": "rejected",
        "status": "RUNNING",
        "input": {"input_content": "new"},
    }
    with pytest.raises(SandboxSessionBusy):
        await claim(store, run_id="rejected", prepared_run=value)
    assert await store._transaction(lambda c: c.execute(select(store.runs.c.run_id)).scalars().all()) == ["run"]


async def test_existing_non_sandbox_history_requires_explicit_migration(store):
    await seed(store)
    await store._transaction(lambda c: c.execute(update(store.runs).values(status="COMPLETED")))
    value = {"run_id": "new", "session_id": "session", "agent_id": "agent", "user_id": "user", "status": "RUNNING"}
    with pytest.raises(SandboxError, match="migrate explicitly"):
        await claim(store, run_id="new", prepared_run=value)
    assert await store._transaction(lambda c: c.execute(select(store.bindings)).first()) is None
    assert await store._transaction(lambda c: c.execute(select(store.runs.c.run_id)).scalars().all()) == ["run"]


async def test_cancelled_provider_operation_drains_before_releasing_ownership_rows(store):
    await seed(store)
    state = await claim(store)
    entered, release = asyncio.Event(), asyncio.Event()

    async def operation(record):
        entered.set()
        await release.wait()
        record["drained"] = True
        return record

    active = asyncio.create_task(store._aoperation(state.lease, operation))
    await entered.wait()
    active.cancel()
    contender = asyncio.create_task(claim(store, owner="other"))
    await asyncio.sleep(0.05)
    assert not active.done() and not contender.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await active
    with pytest.raises(SandboxSessionBusy):
        await contender
    assert (await store.aget(state.lease)).record["drained"] is True


async def test_compute_cannot_replace_service_input_or_metadata(store):
    await seed(store)
    initial = await store._transaction(lambda c: dict(c.execute(select(store.runs.c.run_data)).scalar_one()))
    initial.update(input={"input_content": "original"}, metadata={"tenant": "trusted"})
    await store._transaction(lambda c: c.execute(update(store.runs).values(run_data=initial)))
    state = await claim(store)
    await store.aset_computer(state.lease, computer(state))
    output = result(state.lease)
    output["run"].update(input={"input_content": "forged"}, metadata={"tenant": "forged", "warnings": []})
    await store.astage_result(state.lease, output)
    await store.astage_checkpoint(state.lease, REF)
    await store.aconfirm_stopped(state.lease, "ref")
    committed = await store.acommit(state.lease)
    assert committed["input"] == {"input_content": "original"}
    assert committed["metadata"]["tenant"] == "trusted"
    assert committed["metadata"]["sandbox"]["native_metadata"]["tenant"] == "forged"


async def test_long_provider_operation_keeps_its_lease(store):
    await seed(store)
    state = await claim(store, lease_seconds=1)

    async def slow(record):
        # Longer than the lease; the heartbeat cannot renew while this holds the row.
        await asyncio.sleep(1.5)
        return record

    await store._aoperation(state.lease, slow)
    assert (await store.aget(state.lease)).lease == state.lease


@pytest.mark.parametrize("status", ["RUNNING", "PAUSED"])
async def test_first_binding_waits_for_a_turn_running_outside_the_sandbox(store, status):
    await seed(store)
    await store._transaction(lambda c: c.execute(update(store.runs).values(status=status)))
    await seed(store, run_id="second")
    with pytest.raises(SandboxSessionBusy) as busy:
        await claim(store, run_id="second")
    assert busy.value.run_id == "run"
    assert await store._transaction(lambda c: c.execute(select(store.bindings)).first()) is None


async def test_first_binding_ignores_runs_still_queued(store):
    await seed(store)
    await store._transaction(lambda c: c.execute(update(store.runs).values(status="PENDING")))
    await seed(store, run_id="second")
    assert (await claim(store, run_id="second")).record["phase"] == "executing"


async def test_admission_takes_the_core_run_index_lock(store):
    await seed(store)
    value = {**result((await claim(store)).lease)["run"], "run_id": "queued", "status": "PENDING"}
    engine = create_engine(URL)
    holder = await asyncio.to_thread(engine.connect)
    key = "SELECT pg_advisory_lock(hashtext('agno_run_index'), hashtext('session'))"
    await asyncio.to_thread(lambda: holder.exec_driver_sql(key))
    try:
        admission = asyncio.create_task(store.aprepare(value))
        await asyncio.sleep(0.5)
        # Core run saves hold this lock while picking the next index; admission must wait for it too.
        assert not admission.done()

        # Core takes the lock before writing the run row. Admission must not hold that row while it waits,
        # or a core save of the same run waits on admission while holding the lock admission needs.
        def core_save_of_the_same_run():
            with engine.connect() as connection:
                transaction = connection.begin()
                connection.exec_driver_sql("SET LOCAL lock_timeout = '500ms'")
                connection.execute(
                    store.runs.insert().values(
                        run_id="queued",
                        session_id="session",
                        run_type="agent",
                        agent_id="agent",
                        user_id="user",
                        status="PENDING",
                        created_at=1,
                        run_data=value,
                    )
                )
                transaction.rollback()

        await asyncio.to_thread(core_save_of_the_same_run)
    finally:
        await asyncio.to_thread(
            lambda: holder.exec_driver_sql("SELECT pg_advisory_unlock(hashtext('agno_run_index'), hashtext('session'))")
        )
    await admission
    await asyncio.to_thread(holder.close)
    engine.dispose()
    indexes = await store._transaction(lambda c: c.execute(select(store.runs.c.run_index)).scalars().all())
    assert len(set(indexes)) == len(indexes)


async def test_later_claim_waits_for_a_run_outside_the_sandbox(store):
    lease = await staged(store)
    await store.astage_checkpoint(lease, REF)
    await store.aconfirm_stopped(lease, "ref")
    await store.acommit(lease)
    # A normal run in the same session, after the session's first sandbox turn.
    await seed(store, run_id="outside")
    await seed(store, run_id="second")
    with pytest.raises(SandboxSessionBusy) as caught:
        await claim(store, run_id="second")
    assert caught.value.run_id == "outside"


async def test_paused_run_is_not_restarted_in_a_sandbox(store):
    await seed(store)
    # Paused for a continuation: running it again would discard the pending requirements.
    await store._transaction(lambda c: c.execute(update(store.runs).values(status="PAUSED")))
    with pytest.raises(SandboxError, match="paused"):
        await claim(store)
    assert await store._transaction(lambda c: c.execute(select(store.bindings)).first()) is None


async def stamp_attempt(store, attempt, run_id="run"):
    # What the durable queue does before re-driving a run: record the new attempt on its row.
    def write(connection):
        data = connection.execute(select(store.runs.c.run_data).where(store.runs.c.run_id == run_id)).scalar_one()
        connection.execute(
            store.runs.update().where(store.runs.c.run_id == run_id).values(run_data={**data, "queue_attempt": attempt})
        )

    await store._transaction(write)


async def failed_attempt(store, retryable):
    await seed(store, attempt=1)
    state = await claim(store, queue_attempt=1)
    await store.abegin_stop(state.lease, status="ERROR", reason="restore did not land", retryable=retryable)
    await store.afinish_stop(state.lease)
    await stamp_attempt(store, 2)


async def test_retryable_error_reopens_on_a_newer_queue_attempt(store):
    await failed_attempt(store, retryable=True)
    state = await claim(store, owner="retry", queue_attempt=2)
    assert state.record["phase"] == "executing"
    run = (await rows(store))[0]
    assert run["status"] == "RUNNING" and run["run_data"]["status"] == "RUNNING"
    assert "retryable" not in (run["run_data"].get("metadata") or {}) and run["run_data"].get("content") is None


async def test_error_stays_final_without_a_retryable_newer_attempt(store):
    await failed_attempt(store, retryable=False)
    with pytest.raises(SandboxRunFinished):
        await claim(store, owner="retry", queue_attempt=2)
    assert (await rows(store))[0]["status"] == "ERROR"


async def test_retryable_error_is_not_reopened_by_the_failed_attempt(store):
    await failed_attempt(store, retryable=True)
    # Undo the stamp: the attempt that failed asks again, e.g. after a lost acknowledgement.
    await stamp_attempt(store, 1)
    with pytest.raises(SandboxRunFinished):
        await claim(store, owner="retry", queue_attempt=1)


async def test_pending_prepare_after_claim_keeps_attempt_and_binding(store):
    from agno.run.agent import RunInput, RunOutput
    from agno.run.base import RunStatus

    pending = RunOutput(
        run_id="run",
        session_id="session",
        agent_id="agent",
        user_id="user",
        input=RunInput(input_content="input"),
        status=RunStatus.pending,
    ).to_dict()
    await store.aprepare(pending)
    await store._transaction(
        lambda c: c.execute(
            update(store.runs).values(run_data={**pending, "status": "RUNNING", "queue_attempt": 2}, status="RUNNING")
        )
    )
    state = await claim(store, queue_attempt=2)
    await store.aprepare(pending)
    assert (await store.aget(state.lease)).record["phase"] == "executing"
    assert (await rows(store))[0]["run_data"]["queue_attempt"] == 2


async def test_never_started_cancel_allows_next_turn(store):
    from agno.run.agent import RunInput, RunOutput
    from agno.run.base import RunStatus
    from agno.run.status_persist import RunPersistOutcome

    pending = RunOutput(
        run_id="run",
        session_id="session",
        agent_id="agent",
        user_id="user",
        input=RunInput(input_content="input"),
        status=RunStatus.pending,
    ).to_dict()
    await store.aprepare(pending)
    outcome = await store._aclaim_stop(
        agent_id="agent",
        session_id="session",
        user_id="user",
        run_id="run",
        queue_attempt=0,
        status="CANCELLED",
        reason="cancelled",
    )
    assert outcome == RunPersistOutcome.UPDATED
    await seed(store, run_id="next")
    assert (await claim(store, run_id="next")).record["phase"] == "executing"


async def test_stale_event_writer_cannot_rewrite_new_attempt(store):
    from copy import deepcopy

    lease = await staged(store)
    await store.astage_checkpoint(lease, REF)
    await store.aconfirm_stopped(lease, "ref")
    run = await store.acommit(lease)
    events = [{"event": "RunCompleted", "event_index": 3, "run_id": "run"}]
    await store._apublish_events(run, events)
    stale = deepcopy(run)
    stale["metadata"]["sandbox"]["epoch"] -= 1
    with pytest.raises(SandboxLeaseLost):
        await store._apublish_events(stale, [{"event": "RunCompleted", "event_index": 4}])
    assert (await rows(store))[0]["run_data"]["events"] == events


async def test_queue_termination_fences_owner_and_rejects_stale_attempt(store):
    from agno.run.status_persist import RunPersistOutcome

    await seed(store, attempt=2)
    old = await claim(store, queue_attempt=2)
    stale = await store._aclaim_stop(
        agent_id="agent",
        session_id="session",
        user_id="user",
        run_id="run",
        queue_attempt=1,
        status="ERROR",
        reason="stale",
    )
    assert stale == RunPersistOutcome.STALE_ATTEMPT
    assert (await store.aget(old.lease)).record["phase"] == "executing"
    stopping = await store._aclaim_stop(
        agent_id="agent",
        session_id="session",
        user_id="user",
        run_id="run",
        queue_attempt=2,
        status="CANCELLED",
        reason="cancelled",
    )
    assert stopping.record["phase"] == "stopping"
    with pytest.raises(SandboxLeaseLost):
        await store.aget(old.lease)
    assert (await store.afinish_stop(stopping.lease))["status"] == "CANCELLED"


@pytest.mark.parametrize("seeded", [False, True])
async def test_queue_termination_without_a_run_row_is_final(store, seeded):
    from agno.run.status_persist import RunPersistOutcome

    if seeded:
        await seed(store)
    outcome = await store._aclaim_stop(
        agent_id="agent",
        session_id="session",
        user_id="user",
        run_id="deleted",
        queue_attempt=1,
        status="ERROR",
        reason="swept",
    )
    assert outcome == RunPersistOutcome.MISSING


async def test_queue_termination_for_another_owner_leaves_the_row(store):
    from agno.run.status_persist import RunPersistOutcome

    await seed(store, attempt=1)
    await claim(store, queue_attempt=1)
    outcome = await store._aclaim_stop(
        agent_id="agent",
        session_id="session",
        user_id="other",
        run_id="run",
        queue_attempt=1,
        status="CANCELLED",
        reason="cancelled",
    )
    assert outcome == RunPersistOutcome.MISSING
    assert (await rows(store))[0]["status"] == "RUNNING"


async def test_interrupted_cancel_is_not_rewritten_as_error(store):
    await seed(store, attempt=1)
    await claim(store, queue_attempt=1)
    first = await store._aclaim_stop(
        agent_id="agent",
        session_id="session",
        user_id="user",
        run_id="run",
        queue_attempt=1,
        status="CANCELLED",
        reason="cancelled",
    )
    assert first.record["stop_status"] == "CANCELLED"
    # Cleanup never finished; the sweeper later retries the terminal write as an error.
    second = await store._aclaim_stop(
        agent_id="agent",
        session_id="session",
        user_id="user",
        run_id="run",
        queue_attempt=1,
        status="ERROR",
        reason="worker lost",
    )
    assert second.record["stop_status"] == "CANCELLED"
    assert (await store.afinish_stop(second.lease))["status"] == "CANCELLED"


async def test_queue_termination_racing_a_claim_does_not_deadlock(store):
    from agno.run.status_persist import RunPersistOutcome

    await seed(store, attempt=1)
    engine = create_engine(URL)
    claimer = await asyncio.to_thread(engine.connect)
    transaction = await asyncio.to_thread(claimer.begin)

    def lock(statement):
        return lambda: claimer.execute(statement)

    try:
        # A claim's lock order: session (KEY SHARE), then run, then binding.
        await asyncio.to_thread(lock(text("SET LOCAL lock_timeout = '10s'")))
        await asyncio.to_thread(
            lock(
                select(store.sessions.c.session_id)
                .where(store.sessions.c.session_id == "session")
                .with_for_update(read=True, key_share=True)
            )
        )
        await asyncio.to_thread(lock(select(store.runs.c.run_id).where(store.runs.c.run_id == "run").with_for_update()))
        stop = asyncio.create_task(
            store._aclaim_stop(
                agent_id="agent",
                session_id="session",
                user_id="user",
                run_id="run",
                queue_attempt=1,
                status="CANCELLED",
                reason="cancelled",
            )
        )
        await asyncio.sleep(1)
        await asyncio.to_thread(
            lock(
                insert(store.bindings)
                .values(
                    namespace=store.namespace,
                    session_id="session",
                    agent_id="agent",
                    user_id="user",
                    epoch=0,
                    record={"phase": "idle", "generation": 1, "checkpoint": None, "incarnation": "claim"},
                )
                .on_conflict_do_nothing()
            )
        )
        await asyncio.to_thread(transaction.commit)
    finally:
        await asyncio.to_thread(claimer.close)
        engine.dispose()
    assert await stop == RunPersistOutcome.UPDATED
    assert (await rows(store))[0]["status"] == "CANCELLED"


@pytest.mark.parametrize("override_kind", [None, "commit", "branch"])
async def test_repository_marker_pin_published_at_commit(store, tmp_path, monkeypatch, override_kind):
    import json
    import subprocess

    from agno.sandbox import runtime
    from agno.sandbox.checkpoint import CheckpointArchive

    source = tmp_path / "source"
    source.mkdir()
    real_run = subprocess.run

    def git(*args):
        return real_run(["git", *args], cwd=source, check=True, capture_output=True, text=True).stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (source / "file.txt").write_text("initial")
    git("add", ".")
    git("commit", "-m", "initial")
    sha = git("rev-parse", "HEAD")
    git("branch", "chosen")
    if override_kind is not None:
        (source / "file.txt").write_text("advanced default")
        git("commit", "-am", "advance default")

    def local_run(args, **kwargs):
        if "fetch" in args or "ls-remote" in args:
            args = [str(source) if value == "origin" else value for value in args]
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", local_run)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    root = tmp_path / "computer"
    directory = root / "jobs/first"
    directory.mkdir(parents=True)
    workspace, native = root / "workspace", root / "native"
    monkeypatch.setenv("AGNO_SANDBOX_WORKSPACE", str(workspace))
    configured = {"url": "https://github.com/example/application", "branch": "main"}
    request = {
        "sdk": "fixture",
        "input": "inspect",
        "agent_id": "agent",
        "session_id": "session",
        "run_id": "run",
        "config": {"repository": configured},
        "user_id": "user",
    }
    if override_kind is not None:
        request["metadata"] = {"repository": {override_kind: sha if override_kind == "commit" else "chosen"}}
    runtime_result = await runtime._execute(directory, request)
    raw_marker = json.loads((native / "repository.json").read_text())
    marker = {key: raw_marker[key] for key in ("url", "branch", "commit")}
    assert (
        marker
        == {**configured, "branch": "chosen" if override_kind == "branch" else "main", "commit": sha}
        == runtime_result["repository"]
    )
    (workspace / "repository/file.txt").write_text("engineer edit")
    checkpoint = tmp_path / "checkpoint.tar"
    archive = CheckpointArchive()
    archive.capture({"workspace": workspace, "native": native}, checkpoint, state={})
    replacement = tmp_path / "replacement"
    archive.restore(checkpoint, replacement)
    monkeypatch.setenv("AGNO_SANDBOX_WORKSPACE", str(replacement / "workspace"))
    second = replacement / "jobs/second"
    second.mkdir(parents=True)
    request["native_session_id"] = runtime_result["session"]["session_data"]["fixture_session_id"]
    runtime_result = await runtime._execute(second, request)
    assert (replacement / "workspace/repository/file.txt").read_text() == "engineer edit"
    assert runtime_result["repository"] == marker
    await seed(store)
    state = await claim(store)
    await store.aset_computer(state.lease, computer(state))
    await store.astage_result(state.lease, runtime_result)
    await store.astage_checkpoint(state.lease, REF)
    await store.aconfirm_stopped(state.lease, "ref")
    committed = await store.acommit(state.lease)
    assert committed["metadata"]["sandbox"]["repository"] == marker
    assert committed["metadata"]["sandbox"]["checkpoint"]
    persisted, _, _ = await rows(store)
    assert persisted["run_data"]["metadata"]["sandbox"]["repository"] == marker
