"""Full Docker + Postgres recovery boundary, using a credential-free runtime."""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field, replace
from typing import Dict
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.run.agent import RunCompletedEvent, RunInput, RunOutput
from agno.run.base import RunStatus
from agno.sandbox import SandboxError
from agno.sandbox.checkpoint import CheckpointRef
from agno.sandbox.coordinator import SandboxCoordinator
from agno.sandbox.docker import DockerCheckpointTransfer, DockerSandbox
from agno.sandbox.postgres import SandboxSessionBusy

URL, IMAGE = os.environ.get("AGNO_TEST_SANDBOX_DB_URL"), os.environ.get("AGNO_TEST_RUNTIME_IMAGE")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not URL or not IMAGE, reason="Enable real Postgres and runtime image"),
]


@dataclass(frozen=True)
class Target:
    agent_id: str
    session_id: str
    env: Dict[str, str] = field(default_factory=dict)


@pytest_asyncio.fixture(params=[PostgresDb, AsyncPostgresDb])
async def system(request, tmp_path, checkpoint_store):
    suffix = uuid4().hex[:12]
    db = request.param(
        db_url=URL,
        session_table="co_sessions_" + suffix,
        runs_table="co_runs_" + suffix,
        sandbox_table="co_bindings_" + suffix,
    )
    provider = DockerSandbox(IMAGE, namespace="coordinator-" + suffix, memory_mb=512, workspace_mb=32)
    transfer = DockerCheckpointTransfer(provider, checkpoint_store)
    # Cold replacement every turn, which most of these tests rely on; warm reuse has its own tests.
    coordinator = SandboxCoordinator(db, provider, transfer, poll_wait=1, warm_computer_seconds=0)
    spec = Target("agent", "session", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"})
    handles = []
    original = provider.acreate

    async def create(session_id, **kwargs):
        handle = await original(session_id, **kwargs)
        handles.append(handle)
        return handle

    provider.acreate = create
    coordinator._test_handles = handles  # type: ignore[attr-defined]
    yield coordinator, spec, tmp_path
    for handle in handles:
        await provider.adestroy(handle)
    store = coordinator.store
    await store._transaction(lambda c: [t.drop(c) for t in (store.bindings, store.runs, store.sessions)])
    if isinstance(db, AsyncPostgresDb):
        await db.db_engine.dispose()
    else:
        db.db_engine.dispose()


def handles_of(coordinator):
    """Every computer the provider created for this coordinator, in order."""
    return coordinator._test_handles


async def run(coordinator, spec, run_id="first", **kwargs):
    return await coordinator.arun(
        spec.session_id,
        agent_id=spec.agent_id,
        env=spec.env,
        run_id=run_id,
        input=run_id,
        sdk="fixture",
        user_id="user",
        **kwargs,
    )


async def binding(coordinator):
    return await coordinator.store._transaction(
        lambda c: dict(c.execute(select(coordinator.store.bindings)).mappings().one())
    )


async def recovered_effects(coordinator, tmp_path):
    record = (await binding(coordinator))["record"]
    target = tmp_path / uuid4().hex
    state = await coordinator.transfer.store.arestore(CheckpointRef(**record["checkpoint"]), target)
    assert state["binding"] == record["checkpoint_identity"]
    return (target / "workspace/fixture-effects.txt").read_text().splitlines()


async def test_two_turns_replace_compute_and_restore_files_with_conversation(system):
    coordinator, spec, root = system
    first = await run(coordinator, spec)
    assert first.status == RunStatus.completed
    previous = (await binding(coordinator))["record"]
    assert previous["computer"] is None and previous["phase"] == "idle"
    second = await run(coordinator, spec, "second")
    assert second.status == RunStatus.completed
    assert await recovered_effects(coordinator, root) == ["first", "second"]
    assert (await binding(coordinator))["record"]["generation"] > previous["generation"]
    again = await run(coordinator, spec, "second")
    assert again.to_dict() == second.to_dict()


async def test_checkpoint_failure_retries_finalization_without_repeating_tools(system, monkeypatch):
    coordinator, spec, root = system
    capture = coordinator.transfer.acapture

    async def unavailable(*args, **kwargs):
        raise OSError("checkpoint store unavailable")

    monkeypatch.setattr(coordinator.transfer, "acapture", unavailable)
    with pytest.raises(OSError, match="unavailable"):
        await run(coordinator, spec)
    record = (await binding(coordinator))["record"]
    assert record["phase"] == "finalizing" and record["result"]["run"]["status"] == "COMPLETED"
    monkeypatch.setattr(coordinator.transfer, "acapture", capture)
    fresh = SandboxCoordinator(
        coordinator.store.db, coordinator.provider, coordinator.transfer, poll_wait=1, warm_computer_seconds=0
    )
    assert (await run(fresh, spec)).status == RunStatus.completed
    assert await recovered_effects(coordinator, root) == ["first"]


async def test_lost_start_ack_reconnects_to_same_execution(system, monkeypatch):
    coordinator, spec, root = system
    start = coordinator.client.astart

    async def lost_ack(*args, **kwargs):
        await start(*args, **kwargs)
        raise SandboxError("lost start acknowledgement")

    monkeypatch.setattr(coordinator.client, "astart", lost_ack)
    with pytest.raises(SandboxError, match="lost start"):
        await run(coordinator, spec)
    monkeypatch.setattr(coordinator.client, "astart", start)
    assert (await run(coordinator, spec)).status == RunStatus.completed
    assert await recovered_effects(coordinator, root) == ["first"]


async def test_lost_commit_ack_returns_stored_output_without_compute(system, monkeypatch):
    coordinator, spec, root = system
    commit = coordinator.store.acommit

    async def lost_ack(*args, **kwargs):
        await commit(*args, **kwargs)
        raise OSError("lost commit acknowledgement")

    monkeypatch.setattr(coordinator.store, "acommit", lost_ack)
    with pytest.raises(OSError, match="lost commit"):
        await run(coordinator, spec)
    monkeypatch.setattr(coordinator.store, "acommit", commit)
    assert (await run(coordinator, spec)).status == RunStatus.completed
    assert await recovered_effects(coordinator, root) == ["first"]


async def test_terminal_event_follows_atomic_database_commit(system):
    coordinator, spec, _ = system
    terminal_seen = False
    async for value in coordinator.astream(
        spec.session_id,
        agent_id=spec.agent_id,
        env=spec.env,
        run_id="first",
        input="first",
        sdk="fixture",
        user_id="user",
    ):
        if not isinstance(value, RunOutput) and value.event == "RunCompleted":
            terminal_seen = True
            state = await binding(coordinator)
            assert state["record"]["phase"] == "idle" and state["record"]["checkpoint"]
            row = await coordinator.store._transaction(
                lambda c: c.execute(select(coordinator.store.runs)).mappings().one()
            )
            assert row["status"] == "COMPLETED"
    assert terminal_seen


async def test_same_session_contention_and_independent_sessions(system):
    coordinator, spec, _ = system
    capture = coordinator.transfer.acapture
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause_capture(*args, **kwargs):
        entered.set()
        await release.wait()
        return await capture(*args, **kwargs)

    coordinator.transfer.acapture = pause_capture
    first = asyncio.create_task(run(coordinator, spec))
    await asyncio.wait_for(entered.wait(), 20)
    second = asyncio.create_task(run(coordinator, spec, "second"))
    # Capture holds the database operation fence; admission must wait for it.
    await asyncio.sleep(0.1)
    assert not second.done()
    release.set()
    outcomes = await asyncio.gather(first, second, return_exceptions=True)
    assert outcomes[0].status == RunStatus.completed
    if isinstance(outcomes[1], SandboxSessionBusy):
        assert (await run(coordinator, spec, "second")).status == RunStatus.completed
    else:
        assert outcomes[1].status == RunStatus.completed
    other = replace(spec, session_id="independent")
    assert (await run(coordinator, other, "independent")).status == RunStatus.completed


async def test_lost_destroy_ack_finalizes_without_restore_or_execution(system, monkeypatch):
    coordinator, spec, root = system
    destroy = coordinator.provider.adestroy

    async def lost_ack(handle):
        await destroy(handle)
        raise OSError("lost destroy acknowledgement")

    monkeypatch.setattr(coordinator.provider, "adestroy", lost_ack)
    with pytest.raises(OSError, match="lost destroy"):
        await run(coordinator, spec)
    assert (await binding(coordinator))["record"]["staged_checkpoint"]
    monkeypatch.setattr(coordinator.provider, "adestroy", destroy)
    assert (await run(coordinator, spec)).status == RunStatus.completed
    assert await recovered_effects(coordinator, root) == ["first"]


async def test_lost_compute_before_checkpoint_fails_without_model_replay(system, monkeypatch):
    coordinator, spec, _ = system
    capture = coordinator.transfer.acapture

    async def lose_computer(handle, **kwargs):
        await coordinator.provider.adestroy(handle)
        raise OSError("host lost before checkpoint")

    monkeypatch.setattr(coordinator.transfer, "acapture", lose_computer)
    with pytest.raises(OSError, match="host lost"):
        await run(coordinator, spec)
    monkeypatch.setattr(coordinator.transfer, "acapture", capture)
    output = await run(coordinator, spec)
    assert output.status == RunStatus.error and "will not be repeated" in output.content
    assert output.metadata["retryable"] is False
    assert (await binding(coordinator))["record"]["checkpoint"] is None


async def test_restore_manifest_mismatch_is_rejected_before_execution(system, monkeypatch):
    coordinator, spec, root = system
    await run(coordinator, spec)
    restore = coordinator.transfer.arestore

    async def wrong_identity(*args, **kwargs):
        state = await restore(*args, **kwargs)
        state["binding"]["session_id"] = "other"
        return state

    monkeypatch.setattr(coordinator.transfer, "arestore", wrong_identity)
    with pytest.raises(SandboxError, match="manifest"):
        await run(coordinator, spec, "second")
    assert await recovered_effects(coordinator, root) == ["first"]
    monkeypatch.setattr(coordinator.transfer, "arestore", restore)
    assert (await run(coordinator, spec, "second")).status == RunStatus.completed
    assert await recovered_effects(coordinator, root) == ["first", "second"]


async def test_cancellation_discards_current_files_and_keeps_previous_boundary(system, monkeypatch):
    from agno.run import cancel

    coordinator, spec, root = system
    await run(coordinator, spec)

    async def cancelled(run_id):
        return run_id == "second"

    monkeypatch.setattr(cancel, "ais_cancelled", cancelled)

    async def must_not_allocate(*args, **kwargs):
        pytest.fail("Cancelled turn allocated compute")

    monkeypatch.setattr(coordinator.provider, "acreate", must_not_allocate)
    result = await run(coordinator, spec, "second", config={"delay": 2})
    assert result.status == RunStatus.cancelled
    assert await recovered_effects(coordinator, root) == ["first"]
    assert (await binding(coordinator))["record"]["phase"] == "idle"


async def test_changed_input_and_configuration_cannot_reuse_active_execution(system, monkeypatch):
    coordinator, spec, _ = system
    start = coordinator.client.astart

    async def lost_ack(*args, **kwargs):
        await start(*args, **kwargs)
        raise OSError("detach")

    monkeypatch.setattr(coordinator.client, "astart", lost_ack)
    with pytest.raises(OSError):
        await run(coordinator, spec)
    monkeypatch.setattr(coordinator.client, "astart", start)
    with pytest.raises(SandboxError, match="different input"):
        await coordinator.arun(
            spec.session_id,
            agent_id=spec.agent_id,
            env=spec.env,
            run_id="first",
            input="changed",
            sdk="fixture",
            user_id="user",
        )
    with pytest.raises(SandboxError, match="configuration changed"):
        await run(coordinator, spec, config={"delay": 1})
    assert (await run(coordinator, spec)).status == RunStatus.completed


async def test_cancelled_admission_does_not_strand_its_lease(system, monkeypatch):
    coordinator, spec, root = system
    claim = coordinator.store.aclaim
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_ack(**kwargs):
        state = await claim(**kwargs)
        entered.set()
        await release.wait()
        return state

    monkeypatch.setattr(coordinator.store, "aclaim", delayed_ack)
    task = asyncio.create_task(run(coordinator, spec))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.setattr(coordinator.store, "aclaim", claim)
    assert (await run(coordinator, spec)).status == RunStatus.completed
    assert await recovered_effects(coordinator, root) == ["first"]


async def test_crash_after_provision_replaces_unbound_computer_before_execution(system, monkeypatch):
    coordinator, spec, root = system
    write = coordinator.store._write_record
    failed = []

    def fail_binding(connection, lease, record, **kwargs):
        if record.get("computer") and not failed:
            failed.append(True)
            raise OSError("lost provisioning commit")
        return write(connection, lease, record, **kwargs)

    monkeypatch.setattr(coordinator.store, "_write_record", fail_binding)
    with pytest.raises(OSError, match="provisioning"):
        await run(coordinator, spec)
    state = await binding(coordinator)
    orphan = await coordinator.provider.afind(
        spec.session_id, agent_id=spec.agent_id, generation=state["record"]["generation"], env=spec.env
    )
    assert orphan is not None and state["record"]["computer"] is None
    monkeypatch.setattr(coordinator.store, "_write_record", write)
    assert (await run(coordinator, spec)).status == RunStatus.completed
    assert await coordinator.provider.aget(orphan.provider_ref) is None
    assert await recovered_effects(coordinator, root) == ["first"]


async def test_native_mirror_failure_cannot_publish_success(system, monkeypatch):
    coordinator, spec, _ = system
    poll = coordinator.client.apoll

    async def warning(*args, **kwargs):
        page = await poll(*args, **kwargs)
        if page.result is not None and page.result["type"] == "execution_finished":
            page.result["run"]["metadata"] = {"warnings": [{"type": "transcript_persistence_failed"}]}
            page.result["run"]["tools"] = [{"tool_name": "fixture", "tool_call_id": "effect", "result": "already ran"}]
        return page

    monkeypatch.setattr(coordinator.client, "apoll", warning)
    output = await run(coordinator, spec)
    assert output.status == RunStatus.error and "transcript persistence" in output.content
    assert output.tools[0].result == "already ran"
    assert output.metadata["retryable"] is False
    assert (await binding(coordinator))["record"]["checkpoint"] is None


async def test_next_turn_requires_the_committed_native_conversation(system, monkeypatch):
    coordinator, spec, _ = system
    await run(coordinator, spec)
    native = (await binding(coordinator))["record"]["native"]
    assert native["fixture_session_id"]
    sent = []
    start = coordinator.client.astart

    async def recording(*args, **kwargs):
        sent.append(kwargs.get("native_session_id"))
        return await start(*args, **kwargs)

    monkeypatch.setattr(coordinator.client, "astart", recording)
    assert (await run(coordinator, spec, "second")).status == RunStatus.completed
    assert sent == [native["fixture_session_id"]]
    assert (await binding(coordinator))["record"]["native"] == native


async def test_restore_missing_native_state_fails_before_the_turn_runs(system, monkeypatch):
    coordinator, spec, root = system
    await run(coordinator, spec)
    restore = coordinator.transfer.arestore

    async def lose_native(handle, reference):
        state = await restore(handle, reference)
        removed = await coordinator.provider.aexec(handle, ["rm", "-f", "/runtime/native/fixture-session"])
        assert removed.exit_code == 0
        return state

    monkeypatch.setattr(coordinator.transfer, "arestore", lose_native)
    second = await run(coordinator, spec, "second")
    assert second.status == RunStatus.error
    # The model never ran, so this one is safe to retry.
    assert second.metadata["retryable"] is True
    record = (await binding(coordinator))["record"]
    assert record["phase"] == "idle" and record["native"]["fixture_session_id"]
    # The model never ran: the recovery point still holds only the first turn.
    assert await recovered_effects(coordinator, root) == ["first"]


async def test_completion_without_native_conversation_cannot_publish(system, monkeypatch):
    coordinator, spec, _ = system
    poll = coordinator.client.apoll

    async def lost_native_id(*args, **kwargs):
        page = await poll(*args, **kwargs)
        if page.result is not None and page.result["type"] == "execution_finished":
            page.result["session"]["session_data"].pop("fixture_session_id")
        return page

    monkeypatch.setattr(coordinator.client, "apoll", lost_native_id)
    output = await run(coordinator, spec)
    # Publishing it would leave the next turn with no conversation to require.
    assert output.status == RunStatus.error and "native conversation" in output.content
    assert output.metadata["retryable"] is False
    record = (await binding(coordinator))["record"]
    assert record["checkpoint"] is None and not record.get("native")


async def test_completion_by_another_writer_releases_the_session(system, monkeypatch):
    coordinator, spec, _ = system
    commit = coordinator.store.acommit

    async def finished_elsewhere(lease, **kwargs):
        def complete(connection):
            runs = coordinator.store.runs
            run_data = connection.execute(select(runs.c.run_data).where(runs.c.run_id == lease.run_id)).scalar_one()
            connection.execute(
                runs.update()
                .where(runs.c.run_id == lease.run_id)
                .values(status="COMPLETED", run_data={**run_data, "status": "COMPLETED", "content": "elsewhere"})
            )

        await coordinator.store._transaction(complete)
        return await commit(lease)

    monkeypatch.setattr(coordinator.store, "acommit", finished_elsewhere)
    output = await run(coordinator, spec)
    assert output.status == RunStatus.completed and output.content == "elsewhere"
    record = (await binding(coordinator))["record"]
    assert record["phase"] == "idle" and record["checkpoint"] is None
    monkeypatch.setattr(coordinator.store, "acommit", commit)
    assert (await run(coordinator, spec, "second")).status == RunStatus.completed


async def test_runtime_failure_is_not_retried(system, monkeypatch):
    coordinator, spec, _ = system
    poll = coordinator.client.apoll

    async def crashed(*args, **kwargs):
        page = await poll(*args, **kwargs)
        if page.result is not None:
            page.result.clear()
            page.result.update(type="execution_error", error="harness crashed after its tools ran")
        return page

    monkeypatch.setattr(coordinator.client, "apoll", crashed)
    output = await run(coordinator, spec)
    assert output.status == RunStatus.error and output.metadata["retryable"] is False


async def test_retry_during_finalization_must_match_the_original_request(system, monkeypatch):
    coordinator, spec, _ = system
    capture = coordinator.transfer.acapture

    async def unavailable(*args, **kwargs):
        raise OSError("checkpoint store unavailable")

    monkeypatch.setattr(coordinator.transfer, "acapture", unavailable)
    with pytest.raises(OSError):
        await run(coordinator, spec)
    monkeypatch.setattr(coordinator.transfer, "acapture", capture)
    with pytest.raises(SandboxError, match="configuration changed"):
        await coordinator.arun(
            spec.session_id,
            agent_id=spec.agent_id,
            env=spec.env,
            run_id="first",
            input="first",
            sdk="claude",
            user_id="user",
        )
    assert (await binding(coordinator))["record"]["phase"] == "finalizing"


async def test_repeated_cancellation_during_admission_does_not_strand_its_lease(system, monkeypatch):
    coordinator, spec, root = system
    claim = coordinator.store.aclaim
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_ack(**kwargs):
        state = await claim(**kwargs)
        entered.set()
        await release.wait()
        return state

    monkeypatch.setattr(coordinator.store, "aclaim", delayed_ack)
    task = asyncio.create_task(run(coordinator, spec))
    await entered.wait()
    # A timeout followed by shutdown: the second cancel must not reach the committed claim.
    task.cancel()
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.setattr(coordinator.store, "aclaim", claim)
    # An unreleased lease would refuse this re-claim as busy for the whole lease.
    assert (await run(coordinator, spec)).status == RunStatus.completed
    assert await recovered_effects(coordinator, root) == ["first"]


async def test_large_structured_result_still_checkpoints(system, monkeypatch):
    coordinator, spec, root = system
    poll = coordinator.client.apoll

    async def large(*args, **kwargs):
        page = await poll(*args, **kwargs)
        if page.result is not None and page.result["type"] == "execution_finished":
            # Structure-heavy, like messages and tool calls: under the runtime's 1 MiB limit as compact
            # JSON, but about a quarter larger with the default separators the manifest is written with.
            page.result["run"]["metadata"] = {"items": [{"k": 1}] * 110_000}
            assert len(json.dumps(page.result, separators=(",", ":")).encode()) < 1024 * 1024
        return page

    monkeypatch.setattr(coordinator.client, "apoll", large)
    output = await run(coordinator, spec)
    assert output.status == RunStatus.completed
    record = (await binding(coordinator))["record"]
    target = root / uuid4().hex
    state = await coordinator.transfer.store.arestore(CheckpointRef(**record["checkpoint"]), target)
    assert "result" not in state and len(state["result_sha256"]) == 64


async def test_switching_sdk_mid_session_is_refused_before_compute(system, monkeypatch):
    coordinator, spec, root = system
    await run(coordinator, spec)
    created = []
    create = coordinator.provider.acreate

    async def counting(*args, **kwargs):
        created.append(True)
        return await create(*args, **kwargs)

    monkeypatch.setattr(coordinator.provider, "acreate", counting)
    output = await coordinator.arun(
        spec.session_id,
        agent_id=spec.agent_id,
        env=spec.env,
        run_id="second",
        input="second",
        sdk="claude",
        user_id="user",
    )
    assert output.status == RunStatus.error and "belongs to fixture" in output.content
    assert output.metadata["retryable"] is False and created == []
    record = (await binding(coordinator))["record"]
    assert record["phase"] == "idle" and await recovered_effects(coordinator, root) == ["first"]


async def test_invalid_start_request_retires_the_turn_and_releases_the_session(system, monkeypatch):
    coordinator, spec, root = system
    start = coordinator.client.astart

    async def rejected(*args, **kwargs):
        raise ValueError("Runtime request exceeds 1 MiB")

    monkeypatch.setattr(coordinator.client, "astart", rejected)
    first = await run(coordinator, spec)
    assert first.status == RunStatus.error and "exceeds 1 MiB" in str(first.content)
    row = await binding(coordinator)
    # Nothing executed: the session is released and the provisioned computer is gone.
    assert row["run_id"] is None and row["record"]["phase"] == "idle" and row["record"].get("computer") is None
    assert (
        await coordinator.provider.afind(
            spec.session_id, agent_id=spec.agent_id, generation=row["record"]["generation"], env=spec.env
        )
        is None
    )
    monkeypatch.setattr(coordinator.client, "astart", start)
    assert (await run(coordinator, spec, "second")).status == RunStatus.completed
    assert await recovered_effects(coordinator, root) == ["second"]


async def test_request_near_the_limit_is_refused_before_the_claim(system):
    coordinator, spec, root = system
    # Sized so the fingerprint form of the request is exactly 1 MiB; the real start request is larger.
    shape = dict(
        version=1,
        execution_id="validate",
        run_id="first",
        agent_id=spec.agent_id,
        session_id=spec.session_id,
        user_id="user",
        input="",
        sdk="fixture",
        config={},
        execution_timeout=900,
    )
    text = "x" * (1024 * 1024 - len(json.dumps(shape).encode()))
    with pytest.raises(ValueError, match="exceeds"):
        await coordinator.arun(
            spec.session_id,
            agent_id=spec.agent_id,
            env=spec.env,
            run_id="first",
            input=text,
            sdk="fixture",
            user_id="user",
        )
    assert await coordinator.store._transaction(lambda c: c.execute(select(coordinator.store.bindings)).first()) is None


async def test_finished_turn_does_not_relinquish_a_released_lease(system, monkeypatch):
    coordinator, spec, root = system
    relinquish, calls = coordinator.store.arelinquish, []

    async def counted(lease):
        calls.append(lease)
        await relinquish(lease)

    monkeypatch.setattr(coordinator.store, "arelinquish", counted)
    assert (await run(coordinator, spec)).status == RunStatus.completed
    assert calls == []
    # A caller that leaves mid-turn still detaches.
    task = asyncio.create_task(run(coordinator, spec, "second", config={"delay": 5}))
    await asyncio.sleep(1.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) == 1


async def test_repeated_cancellation_still_releases_the_lease(system, monkeypatch):
    coordinator, spec, _ = system
    relinquish, released, entered = coordinator.store.arelinquish, [], asyncio.Event()

    async def slow(lease):
        entered.set()
        await asyncio.sleep(0.5)
        await relinquish(lease)
        released.append(lease)

    monkeypatch.setattr(coordinator.store, "arelinquish", slow)
    task = asyncio.create_task(run(coordinator, spec, config={"delay": 20, "steps": 20}))
    await asyncio.sleep(6)
    task.cancel()
    await asyncio.wait_for(entered.wait(), 10)
    # A second cancel, say shutdown after a timeout, lands while the release is in flight.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released


async def test_cancellation_does_not_overwrite_a_recorded_stop(system, monkeypatch):
    coordinator, spec, _ = system
    store = coordinator.store
    prepared = RunOutput(
        run_id="first",
        agent_id=spec.agent_id,
        session_id=spec.session_id,
        user_id="user",
        input=RunInput(input_content="first"),
        status=RunStatus.running,
    ).to_dict()
    prepared["queue_attempt"] = None
    state = await store.aclaim(
        agent_id=spec.agent_id,
        session_id=spec.session_id,
        user_id="user",
        run_id="first",
        owner="crashed",
        prepared_run=prepared,
    )
    # An earlier attempt recorded an error stop and then died before cleanup finished.
    await store.abegin_stop(state.lease, status="ERROR", reason="original failure")
    await store._transaction(lambda c: c.execute(store.bindings.update().values(expires_at=None)))

    async def cancelled(run_id):
        return True

    monkeypatch.setattr("agno.run.cancel.ais_cancelled", cancelled)
    output = await run(coordinator, spec)
    assert output.status == RunStatus.error and output.content == "original failure"


async def test_retryable_restore_failure_runs_again_on_the_next_queue_attempt(system, monkeypatch):
    coordinator, spec, root = system
    store = coordinator.store
    await run(coordinator, spec)
    restore = coordinator.transfer.arestore

    async def lose_native(handle, reference):
        state = await restore(handle, reference)
        await coordinator.provider.aexec(handle, ["rm", "-f", "/runtime/native/fixture-session"])
        return state

    monkeypatch.setattr(coordinator.transfer, "arestore", lose_native)
    failed = await run(coordinator, spec, "second", queue_attempt=1)
    assert failed.status == RunStatus.error and failed.metadata["retryable"] is True
    monkeypatch.setattr(coordinator.transfer, "arestore", restore)

    # The durable queue stamps attempt 2 on the run row, then re-drives the same run id.
    def stamp(connection):
        data = connection.execute(select(store.runs.c.run_data).where(store.runs.c.run_id == "second")).scalar_one()
        connection.execute(
            store.runs.update().where(store.runs.c.run_id == "second").values(run_data={**data, "queue_attempt": 2})
        )

    await store._transaction(stamp)
    retried = await run(coordinator, spec, "second", queue_attempt=2)
    assert retried.status == RunStatus.completed
    assert await recovered_effects(coordinator, root) == ["first", "second"]


async def test_sync_stream_yields_events_then_the_committed_output(system):
    coordinator, spec, root = system
    if isinstance(coordinator.store.db, AsyncPostgresDb):
        pytest.skip("stream() is the synchronous variant; AsyncPostgresDb uses astream")
    values = await asyncio.to_thread(
        lambda: list(
            coordinator.stream(
                spec.session_id,
                agent_id=spec.agent_id,
                env=spec.env,
                run_id="first",
                input="first",
                sdk="fixture",
                user_id="user",
                config={"steps": 2},
            )
        )
    )
    assert isinstance(values[-1], RunOutput) and values[-1].status == RunStatus.completed
    assert any(isinstance(value, RunCompletedEvent) for value in values[:-1])
    assert await recovered_effects(coordinator, root) == ["first"]


async def test_next_turn_resumes_the_warm_computer(system, monkeypatch):
    coordinator, spec, root = system
    coordinator.warm_computer_seconds = 300
    restores = []
    restore = coordinator.transfer.arestore

    async def counted(*args, **kwargs):
        restores.append(args)
        return await restore(*args, **kwargs)

    monkeypatch.setattr(coordinator.transfer, "arestore", counted)
    await run(coordinator, spec)
    first = (await binding(coordinator))["record"]
    assert first["warm_until"] and first["computer"] and not first["computer_stopped"]
    assert (await coordinator.provider.aget(handles_of(coordinator)[0].provider_ref)).state == "paused"
    # The checkpoint is still the recovery point, captured after the turn.
    assert await recovered_effects(coordinator, root) == ["first"]

    result = await run(coordinator, spec, "second")
    assert result.status == RunStatus.completed and result.metadata["sandbox"]["resumed"] is True
    second = (await binding(coordinator))["record"]
    assert second["generation"] == first["generation"] and restores == []
    assert len(handles_of(coordinator)) == 1
    assert await recovered_effects(coordinator, root) == ["first", "second"]


async def test_a_lost_warm_computer_is_replaced_from_the_checkpoint(system):
    coordinator, spec, root = system
    coordinator.warm_computer_seconds = 300
    assert (await run(coordinator, spec)).metadata["sandbox"]["resumed"] is False
    first = (await binding(coordinator))["record"]
    await coordinator.provider.adestroy(handles_of(coordinator)[0])
    replaced = await run(coordinator, spec, "second")
    assert replaced.status == RunStatus.completed and replaced.metadata["sandbox"]["resumed"] is False
    second = (await binding(coordinator))["record"]
    assert second["generation"] == first["generation"] + 1
    assert len(handles_of(coordinator)) == 2
    assert await recovered_effects(coordinator, root) == ["first", "second"]


async def test_an_expired_warm_window_retires_the_computer(system):
    coordinator, spec, root = system
    coordinator.warm_computer_seconds = 1
    await run(coordinator, spec)
    kept = handles_of(coordinator)[0]
    await asyncio.sleep(1.5)
    assert (await run(coordinator, spec, "second")).status == RunStatus.completed
    assert len(handles_of(coordinator)) == 2
    assert await coordinator.provider.aget(kept.provider_ref) is None
    assert await recovered_effects(coordinator, root) == ["first", "second"]


async def test_a_cancelled_warm_turn_retires_the_computer_and_keeps_the_boundary(system, monkeypatch):
    from agno.run import cancel

    coordinator, spec, root = system
    coordinator.warm_computer_seconds = 300
    await run(coordinator, spec)
    kept = handles_of(coordinator)[0]

    async def cancelled(run_id):
        return run_id == "second"

    monkeypatch.setattr(cancel, "ais_cancelled", cancelled)
    assert (await run(coordinator, spec, "second", config={"delay": 2})).status == RunStatus.cancelled
    assert await coordinator.provider.aget(kept.provider_ref) is None
    assert await recovered_effects(coordinator, root) == ["first"]
    assert (await binding(coordinator))["record"].get("warm_until") is None


async def test_retire_computer_removes_the_warm_computer_and_keeps_the_checkpoint(system):
    coordinator, spec, root = system
    coordinator.warm_computer_seconds = 300
    await run(coordinator, spec)
    kept = handles_of(coordinator)[0]
    assert await coordinator.aretire_computer(spec.session_id, agent_id=spec.agent_id, user_id="user") is True
    assert await coordinator.provider.aget(kept.provider_ref) is None
    assert await coordinator.aretire_computer(spec.session_id, agent_id=spec.agent_id, user_id="user") is False
    record = (await binding(coordinator))["record"]
    assert record["phase"] == "idle" and record["computer"] is None and record.get("warm_until") is None
    # The next turn restores from the checkpoint on a fresh generation.
    assert (await run(coordinator, spec, "second")).status == RunStatus.completed
    assert len(handles_of(coordinator)) == 2
    assert await recovered_effects(coordinator, root) == ["first", "second"]


async def test_sweep_retires_only_expired_warm_computers(system):
    coordinator, spec, root = system
    coordinator.warm_computer_seconds = 300
    await run(coordinator, spec)
    kept = handles_of(coordinator)[0]
    assert await coordinator.asweep_warm() == 0
    assert (await coordinator.provider.aget(kept.provider_ref)).state == "paused"
    # Move the window into the past, as time would.
    await coordinator.store._transaction(
        lambda c: c.execute(
            update(coordinator.store.bindings).values(
                record=coordinator.store.bindings.c.record.op("||")({"warm_until": time.time() - 1})
            )
        )
    )
    assert await coordinator.asweep_warm() == 1
    assert await coordinator.provider.aget(kept.provider_ref) is None
    assert await coordinator.asweep_warm() == 0


async def restored_workspace(coordinator, tmp_path):
    record = (await binding(coordinator))["record"]
    target = tmp_path / uuid4().hex
    await coordinator.transfer.store.arestore(CheckpointRef(**record["checkpoint"]), target)
    return target / "workspace"


async def test_attachments_are_staged_checkpointed_and_restored_on_new_compute(system):
    from agno.media import File, Image

    coordinator, spec, root = system
    first_bytes, second_bytes = b"first attachment\n", b"second attachment, different bytes\n"
    first = await run(
        coordinator,
        spec,
        files=[File(content=first_bytes, filename="same.txt")],
        images=[Image(content=b"\x89PNG-fixture", format="png")],
    )
    assert first.status == RunStatus.completed
    assert [file.get_content_bytes() for file in first.input.files] == [first_bytes]
    workspace = await restored_workspace(coordinator, root)
    assert (workspace / ".agno/uploads/first/same.txt").read_bytes() == first_bytes
    # Files keep their sanitised name; the harness adapter numbers images from 1 as image-<n>.<format>.
    assert sorted(path.name for path in (workspace / ".agno/uploads/first").iterdir()) == ["image-1.png", "same.txt"]
    assert (workspace / ".agno/uploads/first/image-1.png").read_bytes() == b"\x89PNG-fixture"
    previous = (await binding(coordinator))["record"]
    second = await run(coordinator, spec, "second", files=[File(content=second_bytes, filename="same.txt")])
    assert second.status == RunStatus.completed
    assert (await binding(coordinator))["record"]["generation"] > previous["generation"]
    third = await run(coordinator, spec, "third")
    assert third.status == RunStatus.completed
    workspace = await restored_workspace(coordinator, root)
    assert (workspace / ".agno/uploads/first/same.txt").read_bytes() == first_bytes
    assert (workspace / ".agno/uploads/second/same.txt").read_bytes() == second_bytes
    assert not (workspace / ".agno/uploads/third").exists()
    assert await recovered_effects(coordinator, root) == ["first", "second", "third"]
    again = await run(coordinator, spec, "second", files=[File(content=second_bytes, filename="same.txt")])
    assert again.to_dict() == second.to_dict()
    assert (await restored_workspace(coordinator, root) / ".agno/uploads/second/same.txt").read_bytes() == second_bytes


async def test_rejected_attachments_allocate_no_compute_and_keep_the_last_checkpoint(system):
    from agno.media import File

    coordinator, spec, root = system
    assert (await run(coordinator, spec)).status == RunStatus.completed
    before = (await binding(coordinator))["record"]
    with pytest.raises(ValueError):
        await run(coordinator, spec, "second", files=[File(url="https://example.com/a.txt")])
    assert (await binding(coordinator))["record"] == before
    assert await recovered_effects(coordinator, root) == ["first"]


async def test_failed_staging_ends_the_turn_in_error_and_keeps_the_previous_checkpoint(system):
    from agno.media import File

    coordinator, spec, root = system
    assert (await run(coordinator, spec)).status == RunStatus.completed
    before = (await binding(coordinator))["record"]
    # A run id the upload folder cannot be named after: the runtime refuses to stage it.
    failed = await run(coordinator, spec, "bad:id", files=[File(content=b"abc", filename="a.txt")])
    assert failed.status == RunStatus.error
    after = (await binding(coordinator))["record"]
    assert after["checkpoint"] == before["checkpoint"] and after["checkpoint_identity"] == before["checkpoint_identity"]
    assert await recovered_effects(coordinator, root) == ["first"]
    assert not list((await restored_workspace(coordinator, root)).glob(".agno/uploads/*"))


async def test_sync_stream_carries_attachments_into_the_checkpoint(system):
    from agno.media import File

    coordinator, spec, root = system
    if isinstance(coordinator.store.db, AsyncPostgresDb):
        pytest.skip("stream() is the synchronous variant; AsyncPostgresDb uses astream")
    values = await asyncio.to_thread(
        lambda: list(
            coordinator.stream(
                spec.session_id,
                agent_id=spec.agent_id,
                env=spec.env,
                run_id="first",
                input="first",
                sdk="fixture",
                user_id="user",
                files=[File(content=b"streamed bytes", filename="s.txt")],
            )
        )
    )
    assert isinstance(values[-1], RunOutput) and values[-1].status == RunStatus.completed
    assert (await restored_workspace(coordinator, root) / ".agno/uploads/first/s.txt").read_bytes() == b"streamed bytes"


async def test_cancelling_a_running_attachment_turn_discards_its_files_and_keeps_the_previous_checkpoint(
    system, monkeypatch
):
    from agno.media import File
    from agno.run import cancel

    coordinator, spec, root = system
    await run(coordinator, spec)
    before = (await binding(coordinator))["record"]
    started = asyncio.Event()
    start = coordinator.client.astart

    async def astart(*args, **kwargs):
        result = await start(*args, **kwargs)
        started.set()
        return result

    async def cancelled(run_id):
        return run_id == "second" and started.is_set()

    monkeypatch.setattr(coordinator.client, "astart", astart)
    monkeypatch.setattr(cancel, "ais_cancelled", cancelled)
    result = await run(
        coordinator, spec, "second", files=[File(content=b"abc", filename="a.txt")], config={"delay": 30}
    )
    assert started.is_set(), "the turn was cancelled before it reached the runtime"
    assert result.status == RunStatus.cancelled
    after = (await binding(coordinator))["record"]
    assert after["checkpoint"] == before["checkpoint"] and after["phase"] == "idle"
    assert await recovered_effects(coordinator, root) == ["first"]
    assert not list((await restored_workspace(coordinator, root)).glob(".agno/uploads/*"))


async def test_repository_preparation_failure_is_retryable(system):
    coordinator, spec, _ = system
    # This computer has no network: Git fails before the fixture can run.
    output = await run(
        coordinator, spec, config={"repository": {"url": "https://github.com/example/application", "branch": "main"}}
    )
    assert output.status == RunStatus.error
    assert output.metadata["retryable"] is True
    assert "Repository preparation failed" in output.content
    record = (await binding(coordinator))["record"]
    assert not record.get("checkpoint") and not record.get("native")


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("AGNO_TEST_LIVE_REPOSITORY") != "1", reason="Set AGNO_TEST_LIVE_REPOSITORY=1")
async def test_live_repository_pin_warm_resume_and_replacement(system):
    coordinator, spec, tmp_path = system
    coordinator.provider.network = "isolated"
    coordinator.warm_computer_seconds = 300
    config = {"repository": {"url": "https://github.com/octocat/Hello-World", "branch": "master"}}
    first = await run(coordinator, spec, config=config)
    assert first.status == RunStatus.completed, first.content
    pin = first.metadata["sandbox"]["repository"]
    handle = handles_of(coordinator)[-1]
    await coordinator.provider.aresume(handle)
    edited = await coordinator.provider.aexec(
        handle, ["sh", "-c", "printf 'engineer edit' > /workspace/repository/extra.txt"]
    )
    assert edited.exit_code == 0
    second = await run(coordinator, spec, "second", config=config)
    assert second.status == RunStatus.completed, second.content
    assert second.metadata["sandbox"]["resumed"] is True
    assert second.metadata["sandbox"]["repository"] == pin
    await coordinator.provider.adestroy(handle)
    third = await run(coordinator, spec, "third", config=config)
    assert third.status == RunStatus.completed, third.content
    assert third.metadata["sandbox"]["resumed"] is False
    assert third.metadata["sandbox"]["repository"] == pin
    restored = tmp_path / "repository-checkpoint"
    await coordinator.transfer.store.arestore(CheckpointRef(**third.metadata["sandbox"]["checkpoint"]), restored)
    assert json.loads((restored / "native/repository.json").read_text()) == pin
    assert (restored / "workspace/repository/extra.txt").read_text() == "engineer edit"
    mismatch = await run(
        coordinator, spec, "mismatch", config={"repository": {**config["repository"], "branch": "other"}}
    )
    assert mismatch.status == RunStatus.error and "pinned source" in mismatch.content
    assert mismatch.metadata["retryable"] is False
    missing = await run(coordinator, spec, "missing", config={})
    assert missing.status == RunStatus.error and "agent.repository" in missing.content


async def test_inbound_metadata_persists_without_overriding_runtime_status(system):
    coordinator, spec, _ = system
    spec = replace(spec, env={**spec.env, "GITHUB_TOKEN": "non-repository-token"})
    metadata = {"trace_id": "request-trace", "sandbox": {"repository": "forged"}, "retryable": True}
    first = await run(coordinator, spec, metadata=metadata)
    assert first.status == RunStatus.completed, first.content
    assert first.metadata["trace_id"] == "request-trace"
    assert "repository" not in first.metadata["sandbox"]
    assert "retryable" not in first.metadata
    again = await run(coordinator, spec, metadata=metadata)
    assert again.to_dict() == first.to_dict()
    later = await run(coordinator, spec, "later")
    assert later.status == RunStatus.completed, later.content
    assert "trace_id" not in later.metadata
    failed = await run(coordinator, spec, "timeout", metadata=metadata, config={"delay": 10}, execution_timeout=0.2)
    assert failed.status == RunStatus.error
    assert failed.metadata["trace_id"] == "request-trace"
    assert failed.metadata["retryable"] is False
    assert "repository" not in failed.metadata["sandbox"]


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("AGNO_TEST_LIVE_REPOSITORY") != "1", reason="Set AGNO_TEST_LIVE_REPOSITORY=1")
@pytest.mark.parametrize("lost", ["native", "marker", "checkout"])
async def test_repository_state_loss_retries_from_committed_checkpoint(system, lost):
    coordinator, spec, root = system
    coordinator.provider.network = "isolated"
    coordinator.warm_computer_seconds = 300
    config = {"repository": {"url": "https://github.com/octocat/Hello-World", "branch": "master"}}
    first = await run(coordinator, spec, config=config)
    assert first.status == RunStatus.completed, first.content
    pin = first.metadata["sandbox"]["repository"]
    checkpoint = first.metadata["sandbox"]["checkpoint"]
    handle = handles_of(coordinator)[-1]
    await coordinator.provider.aresume(handle)
    path = {
        "native": "/runtime/native",
        "marker": "/runtime/native/repository.json",
        "checkout": "/workspace/repository",
    }[lost]
    removed = await coordinator.provider.aexec(handle, ["rm", "-rf", path])
    assert removed.exit_code == 0
    failed = await run(coordinator, spec, "lost-state", config=config)
    assert failed.status == RunStatus.error, failed.content
    assert failed.metadata["retryable"] is True
    assert "Repository checkpoint is missing" in failed.content
    assert (await binding(coordinator))["record"]["checkpoint"] == checkpoint
    recovered = await run(coordinator, spec, "retry", config=config)
    assert recovered.status == RunStatus.completed, recovered.content
    assert recovered.metadata["sandbox"]["repository"] == pin
    assert await recovered_effects(coordinator, root) == ["first", "retry"]
