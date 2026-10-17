"""Real AgentOS HTTP/queue/Redis/Postgres/Docker execution, with a fixture harness."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text

from agno.db.postgres import PostgresDb
from agno.job_queue.config import QueueConfig, RedisCoordination
from agno.os import AgentOS
from agno.sandbox import _harness
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent

URL = os.environ.get("AGNO_TEST_SANDBOX_DB_URL")
IMAGE = os.environ.get("AGNO_TEST_RUNTIME_IMAGE")
REDIS = os.environ.get("AGNO_TEST_REDIS_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not URL or not IMAGE or not REDIS, reason="Enable dedicated Docker, Postgres and Redis"),
]


@pytest_asyncio.fixture
async def service(tmp_path, request, checkpoint_store):
    import redis
    import redis.asyncio

    import agno.os.event_streams as streams
    import agno.run.cancel as cancel
    from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager

    old = (
        streams._event_stream,
        streams._event_stream_explicitly_set,
        cancel._cancellation_manager,
        cancel._cancellation_manager_explicitly_set,
    )
    streams._event_stream, streams._event_stream_explicitly_set = None, False
    cancel._cancellation_manager, cancel._cancellation_manager_explicitly_set = InMemoryRunCancellationManager(), False
    suffix = uuid4().hex[:12]
    prefix = "sandbox-http-" + suffix
    redis_sync, redis_async = redis.Redis.from_url(REDIS), redis.asyncio.Redis.from_url(REDIS)
    db = PostgresDb(
        db_url=URL,
        session_table="http_sessions_" + suffix,
        runs_table="http_runs_" + suffix,
        job_table="http_jobs_" + suffix,
        sandbox_table="http_bindings_" + suffix,
    )
    provider = DockerSandbox(
        IMAGE,
        namespace=prefix,
        memory_mb=512,
        workspace_mb=32,
        env={"AGNO_SANDBOX_TEST_RUNTIME": "1"},
        checkpoints=checkpoint_store,
    )
    handles = []
    original = provider.acreate

    async def create(session_id, **kwargs):
        handle = await original(session_id, **kwargs)
        handles.append(handle)
        return handle

    provider.acreate = create  # type: ignore[method-assign]
    agent = FixtureAgent(id="coder", sandbox=provider)
    config = QueueConfig(
        durable=True,
        db=db,
        redis=RedisCoordination(sync_client=redis_sync, async_client=redis_async, key_prefix=prefix),
        poll_interval=0.05,
        max_attempts=2,
        retry_delay_seconds=0,
        stop_timeout_seconds=1,
        # Indirect parametrization overrides queue settings for one test.
        **getattr(request, "param", {}),
    )
    app = AgentOS(id=prefix, agents=[agent], db=db, queue=config, telemetry=False).get_app()
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=30
            ) as client:
                yield client, agent, app, handles
    finally:
        for handle in handles:
            await provider.adestroy(handle)
        with db.db_engine.begin() as connection:
            for table_type in ("sandbox_bindings", "jobs", "runs", "sessions"):
                table = db._get_table(table_type)
                if table is not None:
                    table.drop(connection, checkfirst=True)
        db.db_engine.dispose()
        keys = await redis_async.keys(prefix + "*")
        if keys:
            await redis_async.delete(*keys)
        await redis_async.aclose()
        redis_sync.close()
        (
            streams._event_stream,
            streams._event_stream_explicitly_set,
            cancel._cancellation_manager,
            cancel._cancellation_manager_explicitly_set,
        ) = old


async def settled(app, run_id):
    async def wait():
        while True:
            job = await app.state.queue_worker.store.get_job(run_id)
            if job["status"] in ("completed", "failed", "cancelled"):
                return job
            await asyncio.sleep(0.05)

    return await asyncio.wait_for(wait(), 25)


async def test_foreground_request_uses_durable_worker_and_committed_checkpoint(service):
    client, agent, app, handles = service
    response = await client.post(
        "/agents/coder/runs", data={"message": "first", "session_id": "session", "stream": "false"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "COMPLETED" and body["content"] == "first", body
    assert body["metadata"]["sandbox"]["checkpoint"]
    job = await app.state.queue_worker.store.get_job(body["run_id"])
    assert job["status"] == "completed" and job["attempt"] == 1
    assert job["payload"]["serialize_session"] is True
    assert handles
    # The AgentOS harness keeps the computer warm for the next turn: paused, not removed.
    computers = await asyncio.gather(*(_harness.coordinator(agent).provider.aget(h.provider_ref) for h in handles))
    assert all(value is not None and value.state == "paused" for value in computers), computers


async def test_background_acceptance_poll_and_idempotency(service):
    client, agent, app, _ = service
    data = {"message": "background", "session_id": "session", "stream": "false", "background": "true"}
    first = await client.post("/agents/coder/runs", data=data, headers={"Idempotency-Key": "one"})
    assert first.status_code == 202, first.text
    second = await client.post("/agents/coder/runs", data=data, headers={"Idempotency-Key": "one"})
    assert second.status_code == 202 and second.json()["run_id"] == first.json()["run_id"]
    job = await settled(app, first.json()["run_id"])
    assert job["status"] == "completed", str({k: v for k, v in job.items() if "err" in k})
    result = await agent.aget_run_output(job["id"], "session")
    assert result.content == "background" and result.metadata["sandbox"]["checkpoint"]
    conflict = await client.post(
        "/agents/coder/runs", data={**data, "message": "changed"}, headers={"Idempotency-Key": "one"}
    )
    assert conflict.status_code == 409


async def test_streaming_request_uses_indexed_queue_events(service):
    client, agent, _, _ = service
    response = await client.post(
        "/agents/coder/runs", data={"message": "stream", "session_id": "session", "stream": "true"}
    )
    assert response.status_code == 200, response.text
    assert "RunContent" in response.text and "RunCompleted" in response.text and "event_index" in response.text
    session = await agent.aget_session("session")
    assert session.session_data["sandbox"]["checkpoint"]


async def test_queued_same_session_turns_do_not_spend_attempts_on_contention(service):
    client, agent, app, _ = service
    agent.delay = 0.3

    async def submit(message):
        response = await client.post(
            "/agents/coder/runs",
            data={"message": message, "session_id": "session", "stream": "false", "background": "true"},
        )
        assert response.status_code == 202, response.text
        return response.json()["run_id"]

    ids = await asyncio.gather(submit("one"), submit("two"))
    jobs = await asyncio.gather(*(settled(app, run_id) for run_id in ids))
    assert all(job["status"] == "completed" and job["attempt"] == 1 for job in jobs), jobs
    assert len((await agent.aget_session("session")).runs) == 2


async def test_checkpoint_outage_retries_finalization_only(service, monkeypatch, tmp_path):
    client, agent, app, _ = service
    capture = _harness.coordinator(agent).transfer.acapture
    calls = []

    async def fail_once(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise OSError("injected storage outage")
        return await capture(*args, **kwargs)

    monkeypatch.setattr(_harness.coordinator(agent).transfer, "acapture", fail_once)
    response = await client.post(
        "/agents/coder/runs",
        data={"message": "retry", "session_id": "session", "stream": "false", "background": "true"},
    )
    assert response.status_code == 202, response.text
    job = await settled(app, response.json()["run_id"])
    assert job["status"] == "completed" and job["attempt"] == 2, job
    row = await _harness.coordinator(agent).store._transaction(
        lambda c: c.execute(select(_harness.coordinator(agent).store.bindings)).mappings().one()
    )
    from agno.sandbox.checkpoint import CheckpointRef

    destination = tmp_path / "verify"
    await _harness.coordinator(agent).transfer.store.arestore(CheckpointRef(**row["record"]["checkpoint"]), destination)
    assert (destination / "workspace/fixture-effects.txt").read_text().splitlines() == [job["id"]]


async def test_retained_events_replay_after_live_keys_expire(service):
    from agno.os.event_streams import get_event_stream

    client, agent, app, _ = service
    response = await client.post(
        "/agents/coder/runs", data={"message": "retain", "session_id": "session", "stream": "false"}
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    await settled(app, run_id)
    run = await agent.aget_run_output(run_id, "session")
    assert run.events and any(event.event == "RunCompleted" and event.event_index is not None for event in run.events)
    await get_event_stream().cleanup_run(run_id)
    replay = await client.post(f"/agents/coder/runs/{run_id}/resume", data={"session_id": "session"})
    assert replay.status_code == 200 and "RunCompleted" in replay.text and "event_index" in replay.text, replay.text


async def test_cancel_active_run_removes_compute_before_terminal(service):
    client, agent, app, handles = service
    agent.delay = 10
    response = await client.post(
        "/agents/coder/runs",
        data={"message": "cancel", "session_id": "session", "stream": "false", "background": "true"},
    )
    run_id = response.json()["run_id"]

    async def allocated():
        while not handles:
            await asyncio.sleep(0.05)

    await asyncio.wait_for(allocated(), 10)
    cancelled = await client.post(f"/agents/coder/runs/{run_id}/cancel", params={"session_id": "session"})
    assert cancelled.status_code == 200, cancelled.text
    job = await settled(app, run_id)
    assert job["status"] == "cancelled", job
    assert all(
        value is None
        for value in await asyncio.gather(*(_harness.coordinator(agent).provider.aget(h.provider_ref) for h in handles))
    )
    run = await agent.aget_run_output(run_id, "session")
    assert run.status == "CANCELLED"


async def test_exhausted_checkpoint_retries_clean_up_before_failing(service, monkeypatch):
    client, agent, app, handles = service

    async def unavailable(*args, **kwargs):
        raise OSError("checkpoint storage unavailable")

    monkeypatch.setattr(_harness.coordinator(agent).transfer, "acapture", unavailable)
    response = await client.post(
        "/agents/coder/runs",
        data={"message": "outage", "session_id": "session", "stream": "false", "background": "true"},
    )
    job = await settled(app, response.json()["run_id"])
    assert job["status"] == "failed" and job["attempt"] == 2, job
    assert len(handles) == 1
    assert await _harness.coordinator(agent).provider.aget(handles[0].provider_ref) is None
    row = await _harness.coordinator(agent).store._transaction(
        lambda c: c.execute(select(_harness.coordinator(agent).store.bindings)).mappings().one()
    )
    assert row["record"]["phase"] == "idle" and row["record"]["computer"] is None


async def test_cancel_between_attempts_cleans_up_before_ticket_settlement(service, monkeypatch):
    client, agent, app, handles = service
    monkeypatch.setattr(app.state.queue_worker, "_retry_delay", lambda attempt: 30)

    async def unavailable(*args, **kwargs):
        raise OSError("checkpoint storage unavailable")

    monkeypatch.setattr(_harness.coordinator(agent).transfer, "acapture", unavailable)
    response = await client.post(
        "/agents/coder/runs",
        data={"message": "cancel retry", "session_id": "session", "stream": "false", "background": "true"},
    )
    run_id = response.json()["run_id"]

    async def waiting():
        while True:
            job = await app.state.queue_worker.store.get_job(run_id)
            if job["status"] == "queued" and job["attempt"] == 1:
                return
            await asyncio.sleep(0.05)

    await asyncio.wait_for(waiting(), 15)
    assert await _harness.coordinator(agent).provider.aget(handles[0].provider_ref) is not None
    response = await client.post(f"/agents/coder/runs/{run_id}/cancel", params={"session_id": "session"})
    assert response.status_code == 200, response.text
    assert (await settled(app, run_id))["status"] == "cancelled"
    assert await _harness.coordinator(agent).provider.aget(handles[0].provider_ref) is None


async def test_sdk_background_uses_same_registered_queue(service):
    _, agent, app, _ = service
    pending = await agent.arun("sdk", session_id="session", background=True)
    assert pending.status == "PENDING"
    assert (await settled(app, pending.run_id))["status"] == "completed"


async def test_missing_durable_queue_rejects_before_allocating(service):
    _, agent, _, handles = service
    app = AgentOS(id="no-queue", agents=[agent], db=agent.db, telemetry=False).get_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/agents/coder/runs", data={"message": "no", "session_id": "session", "stream": "false"}
        )
    assert response.status_code == 400 and "durable queue" in response.text
    assert not handles


def _earlier_build_bindings_table(db):
    """Replace the bindings table with the shape an earlier build created: no run_id foreign key."""
    sessions, home, name = db.session_table_name, db.db_schema, db.sandbox_table_name
    with db.db_engine.begin() as connection:
        connection.execute(text(f'DROP TABLE IF EXISTS "{home}"."{name}"'))
        connection.execute(
            text(
                f'CREATE TABLE "{home}"."{name}" (namespace varchar NOT NULL, session_id varchar NOT NULL '
                f'REFERENCES "{home}"."{sessions}" (session_id) ON DELETE CASCADE, agent_id varchar NOT NULL, '
                "user_id varchar, epoch bigint NOT NULL, owner varchar, run_id varchar, queue_attempt bigint, "
                "expires_at timestamptz, record jsonb NOT NULL, PRIMARY KEY (namespace, session_id))"
            )
        )
    db._invalidate_table_cache(name)


async def test_outdated_bindings_table_fails_startup_with_its_remedy(service):
    _, agent, _, _ = service
    from agno.sandbox.base import SandboxError
    from agno.sandbox.postgres import _SandboxStore

    suffix = uuid4().hex[:12]
    db = PostgresDb(
        db_url=URL,
        session_table="startup_sessions_" + suffix,
        runs_table="startup_runs_" + suffix,
        sandbox_table="startup_bindings_" + suffix,
    )
    stale = FixtureAgent(id="stale", sandbox=agent.sandbox)
    try:
        await _SandboxStore(db)._ensure_tables()
        _earlier_build_bindings_table(db)
        for auto_provision_dbs in (True, False):
            app = AgentOS(
                id="stale-" + suffix, agents=[stale], db=db, telemetry=False, auto_provision_dbs=auto_provision_dbs
            ).get_app()
            with pytest.raises(SandboxError) as refused:
                async with app.router.lifespan_context(app):
                    pass
            assert "does not reference run table" in str(refused.value)
            assert "pass PostgresDb(sandbox_table=...)" in str(refused.value)
        # A deployment that provisions its own tables is validated, never provisioned, at startup.
        with db.db_engine.begin() as connection:
            connection.execute(text(f'DROP TABLE "{db.db_schema}"."{db.sandbox_table_name}"'))
        db._invalidate_table_cache(db.sandbox_table_name)
        app = AgentOS(id="unprovisioned-" + suffix, agents=[stale], db=db, telemetry=False, auto_provision_dbs=False)
        app = app.get_app()
        async with app.router.lifespan_context(app):
            pass
        assert not db.table_exists(db.sandbox_table_name), "startup did not create the bindings table"
    finally:
        with db.db_engine.begin() as connection:
            for table in ("startup_bindings_", "startup_runs_", "startup_sessions_"):
                connection.execute(text(f'DROP TABLE IF EXISTS "{db.db_schema}"."{table + suffix}"'))
        db.db_engine.dispose()


@pytest.mark.parametrize("service", [{"lock_grace_seconds": 3}], indirect=True)
async def test_outdated_bindings_table_refuses_submissions_and_fails_claimed_tickets(service):
    client, agent, app, handles = service
    worker = app.state.queue_worker
    _earlier_build_bindings_table(agent.db)
    for _, built in _harness._coordinators.get(agent.sandbox, []):
        built.store._tables_ready = False

    # A submission is refused before any ticket exists, with the remedy in the response.
    response = await client.post(
        "/agents/coder/runs", data={"message": "stale", "session_id": "session", "stream": "false"}
    )
    assert response.status_code == 500, response.text
    assert "does not reference run table" in response.text and "sandbox_table" in response.text
    assert await worker.store.count_queued_jobs() == 0 and not handles

    # A ticket that reached the queue anyway (a replica without the check) must still settle as
    # failed: the terminal persist cannot go through the bindings table it cannot use.
    from agno.db.schemas.jobs import QueuedJob

    job = QueuedJob(
        id="stale-" + uuid4().hex[:8],
        component_type="agent",
        component_id="coder",
        session_id="session",
        payload={"input": "stale", "kwargs": {}, "stream": True, "serialize_session": True},
        max_attempts=worker.config.max_attempts,
    ).to_dict()
    assert (await worker.store.enqueue_job(job, max_depth=10))["accepted"] is True
    settled_job = await settled(app, job["id"])
    assert settled_job["status"] == "failed", settled_job
    assert not handles, "no computer was ever created for the turn"


@pytest.mark.parametrize(("first_user", "second_user"), [(None, "someone"), ("owner", None), ("owner", "someone")])
async def test_submission_on_a_session_another_user_holds_is_refused_before_any_ticket(
    service, first_user, second_user
):
    client, agent, app, handles = service
    worker = app.state.queue_worker
    data = {"message": "mine", "session_id": "held", "stream": "false", "background": "true"}
    if first_user is not None:
        data["user_id"] = first_user
    first = await client.post("/agents/coder/runs", data=data)
    assert first.status_code == 202, first.text
    assert (await settled(app, first.json()["run_id"]))["status"] == "completed"
    created = len(handles)

    data["message"] = "theirs"
    data.pop("user_id", None)
    if second_user is not None:
        data["user_id"] = second_user
    second = await client.post("/agents/coder/runs", data=data)
    assert second.status_code == 404 and second.json()["detail"] == "Session not found", second.text
    assert len(handles) == created, "no computer was created for the refused turn"
    jobs, total = await worker.store.list_jobs(limit=50)
    assert total == 1 and jobs[0]["id"] == first.json()["run_id"], "the refused submission left no ticket"


async def test_cancel_detached_direct_sdk_run_retires_computer(service):
    _, agent, _, handles = service
    agent.delay = 10
    task = asyncio.create_task(agent.arun("detach", session_id="session", run_id="direct"))

    async def allocated():
        while not handles:
            await asyncio.sleep(0.05)

    await asyncio.wait_for(allocated(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await _harness.coordinator(agent).provider.aget(handles[0].provider_ref) is not None
    await agent.acancel_run("direct")
    assert await _harness.coordinator(agent).provider.aget(handles[0].provider_ref) is None
    assert (await agent.aget_run_output("direct", "session")).status == "CANCELLED"


async def test_timed_out_attempt_is_retried_on_new_compute(service, monkeypatch):
    client, agent, app, handles = service
    agent.delay = 4
    monkeypatch.setattr(app.state.queue_worker.config, "timeout_seconds", 2)
    response = await client.post(
        "/agents/coder/runs",
        data={"message": "slow", "session_id": "session", "stream": "false", "background": "true"},
    )
    job = await settled(app, response.json()["run_id"])
    # Both attempts time out; the second must have executed again, not replayed the first ERROR.
    assert job["status"] == "failed" and job["attempt"] == 2, job
    assert "timeout_seconds" in (job.get("error") or ""), job
    assert len(handles) == 2, handles
    assert all(
        value is None
        for value in await asyncio.gather(*(_harness.coordinator(agent).provider.aget(h.provider_ref) for h in handles))
    )


async def test_direct_run_keeps_the_agent_name(service):
    _, agent, _, _ = service
    agent.name = "Coder"
    result = await agent.arun("named", session_id="session", run_id="named")
    assert result.status == "COMPLETED" and result.agent_name == "Coder"
    assert (await agent.aget_run_output("named", "session")).agent_name == "Coder"


async def test_remote_cancel_fences_the_worker_without_failing_its_ticket(service):
    client, agent, app, handles = service
    agent.delay = 20
    app.state.queue_worker.config.max_attempts = 1
    response = await client.post(
        "/agents/coder/runs",
        data={"message": "cancel", "session_id": "session", "stream": "false", "background": "true"},
    )
    run_id = response.json()["run_id"]

    async def allocated():
        while not handles:
            await asyncio.sleep(0.05)

    await asyncio.wait_for(allocated(), 10)
    # No live handle here, so this takes the path a cancel on another replica takes: fence the
    # worker's lease and retire its computer. The worker's attempt then fails with a lost lease
    # or a dead transport, which must settle the ticket as cancelled, not failed.
    await agent.acancel_run(run_id)
    job = await settled(app, run_id)
    assert job["status"] == "cancelled", job
    assert (await agent.aget_run_output(run_id, "session")).status == "CANCELLED"
    for handle in handles:
        assert await _harness.coordinator(agent).provider.aget(handle.provider_ref) is None


PNG = b"\x89PNG\r\n\x1a\nfixture"


async def checkpointed_uploads(agent, result, run_id):
    from agno.sandbox.checkpoint import CheckpointRef

    target = Path(tempfile.mkdtemp()) / "restored"
    await _harness.coordinator(agent).transfer.store.arestore(
        CheckpointRef(**result.metadata["sandbox"]["checkpoint"]), target
    )
    folder = target / "workspace/.agno/uploads" / run_id
    return {path.name: path.read_bytes() for path in folder.iterdir()} if folder.exists() else {}


async def test_uploaded_images_and_files_reach_the_checkpoint(service):
    client, agent, app, _ = service
    response = await client.post(
        "/agents/coder/runs",
        data={"message": "look", "session_id": "session", "stream": "false"},
        files=[("files", ("photo.png", PNG, "image/png")), ("files", ("notes.txt", b"notes", "text/plain"))],
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    job = await app.state.queue_worker.store.get_job(run_id)
    assert response.json()["status"] == "COMPLETED", job.get("error")
    assert [item["kind"] for item in job["payload"]["kwargs"]["media"]] == ["image", "file"]
    result = await agent.aget_run_output(run_id, "session")
    assert [image.content for image in result.input.images] == [PNG]
    assert await checkpointed_uploads(agent, result, run_id) == {"image-1.png": PNG, "notes.txt": b"notes"}


async def test_unsupported_or_path_media_is_refused_before_any_job(service):
    client, _, app, handles = service
    audio = await client.post(
        "/agents/coder/runs",
        data={"message": "listen", "session_id": "session", "stream": "false"},
        files=[("files", ("clip.wav", b"RIFF0000WAVE", "audio/wav"))],
    )
    assert audio.status_code == 400 and "audio and video" in audio.text
    path = await client.post(
        "/agents/coder/runs",
        data={
            "message": "read",
            "session_id": "session",
            "stream": "false",
            "images": json.dumps([{"filepath": "/etc/hosts"}]),
        },
    )
    assert path.status_code == 400 and "file paths" in path.text, path.text
    assert not handles


async def test_a_reused_key_with_different_attachment_bytes_is_refused(service):
    client, _, app, _ = service
    data = {"message": "look", "session_id": "session", "stream": "false", "background": "true"}
    first = await client.post(
        "/agents/coder/runs",
        data=data,
        files=[("files", ("a.txt", b"one", "text/plain"))],
        headers={"Idempotency-Key": "k"},
    )
    assert first.status_code == 202, first.text
    again = await client.post(
        "/agents/coder/runs",
        data=data,
        files=[("files", ("a.txt", b"one", "text/plain"))],
        headers={"Idempotency-Key": "k"},
    )
    assert again.status_code == 202 and again.json()["run_id"] == first.json()["run_id"]
    changed = await client.post(
        "/agents/coder/runs",
        data=data,
        files=[("files", ("a.txt", b"two", "text/plain"))],
        headers={"Idempotency-Key": "k"},
    )
    assert changed.status_code == 409
    job = await settled(app, first.json()["run_id"])
    assert job["status"] == "completed", str({k: v for k, v in job.items() if "err" in k})


async def test_sdk_runs_carry_attachments_directly_and_through_the_queue(service):
    from agno.media import File, Image

    _, agent, app, _ = service
    direct = await agent.arun(
        "direct",
        session_id="direct",
        run_id="direct",
        images=[Image(content=PNG)],
        files=[File(content=b"d", filename="d.txt")],
    )
    assert direct.status == "COMPLETED"
    assert await checkpointed_uploads(agent, direct, "direct") == {"image-1.png": PNG, "d.txt": b"d"}
    pending = await agent.arun(
        "queued", session_id="queued", background=True, files=[File(content=b"q", filename="q.txt")]
    )
    job = await settled(app, pending.run_id)
    assert job["status"] == "completed", str({k: v for k, v in job.items() if "err" in k})
    queued = await agent.aget_run_output(pending.run_id, "queued")
    assert (await checkpointed_uploads(agent, queued, pending.run_id))["q.txt"] == b"q"


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("AGNO_TEST_LIVE_REPOSITORY") != "1", reason="Set AGNO_TEST_LIVE_REPOSITORY=1")
async def test_request_state_repository_override_reaches_runtime(service, tmp_path):
    from agno.sandbox import Repository
    from agno.sandbox.checkpoint import CheckpointRef

    _, agent, app, handles = service
    # The configured branch does not exist: only the inbound commit can prepare this turn.
    agent.repository = Repository("https://github.com/octocat/Hello-World", branch="configured-branch-not-present")
    agent.sandbox.network = "isolated"
    commit = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"
    metadata = {"repository": {"commit": commit}, "trace_id": "middleware-trace"}

    async def with_request_metadata(scope, receive, send):
        scope.setdefault("state", {})["metadata"] = metadata
        await app(scope, receive, send)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=with_request_metadata), base_url="http://test"
    ) as client:
        payload = {"message": "inspect", "session_id": "repository-session", "stream": "false"}
        first = await client.post("/agents/coder/runs", data=payload)
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["status"] == "COMPLETED", body
        assert body["metadata"]["trace_id"] == "middleware-trace"
        assert body["metadata"]["repository"] == metadata["repository"]
        pin = body["metadata"]["sandbox"]["repository"]
        assert pin == {"url": agent.repository.url, "branch": agent.repository.branch, "commit": commit}
        job = await app.state.queue_worker.store.get_job(body["run_id"])
        assert job["payload"]["kwargs"]["metadata"] == metadata
        for override in ({"commit": commit}, {"commit": "0" * 40}, {"branch": "nonexistent"}):
            metadata = {"repository": override}
            later = await client.post("/agents/coder/runs", data=payload)
            assert later.status_code == 200, later.text
            assert later.json()["status"] == "COMPLETED", later.text
            assert later.json()["metadata"]["sandbox"]["repository"] == pin
        saved = tmp_path / "metadata-checkpoint"
        await agent.sandbox.checkpoints.arestore(
            CheckpointRef(**later.json()["metadata"]["sandbox"]["checkpoint"]), saved
        )
        assert json.loads((saved / "native/repository.json").read_text()) == pin
        count = len(handles)
        metadata = {"repository": {"url": "https://github.com/other/repo", "commit": commit}}
        refused = await client.post("/agents/coder/runs", data={**payload, "session_id": "new-session"})
        assert refused.status_code == 400 and "url cannot be overridden" in refused.text
        assert len(handles) == count
