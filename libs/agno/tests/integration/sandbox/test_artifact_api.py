"""Ownership-scoped checkpoint inspection and downloads through real AgentOS."""

import asyncio

import pytest
from sqlalchemy import delete, select, update

from agno.sandbox import _harness
from agno.sandbox.artifacts import SandboxArtifactNotFound, SandboxArtifacts, SandboxSessionNotFound
from agno.sandbox.base import SandboxError
from agno.sandbox.checkpoint import CheckpointRef
from tests.integration.sandbox.test_agentos import IMAGE, REDIS, URL
from tests.integration.sandbox.test_agentos import service as _service_fixture

service = _service_fixture

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not URL or not IMAGE or not REDIS, reason="Enable dedicated local sandbox services"),
]


async def completed(service):
    client, agent, _, _ = service
    response = await client.post(
        "/agents/coder/runs",
        data={"message": "artifact", "session_id": "session", "stream": "false", "user_id": "owner"},
    )
    assert response.status_code == 200, response.text
    coordinator = _harness.coordinator(agent)
    return response.json()["run_id"], SandboxArtifacts(coordinator.store, coordinator.transfer.store)


async def test_download_after_compute_is_destroyed(service):
    client, agent, _, handles = service
    run_id, artifacts = await completed(service)
    coordinator = _harness.coordinator(agent)
    # A completed turn leaves its computer paused for the warm-reuse window, so a checkpoint
    # already exists while compute is still allocated.
    warm = await artifacts.astatus(agent_id="coder", session_id="session", user_id="owner")
    assert warm["phase"] == "idle" and warm["has_checkpoint"] and warm["compute_allocated"]
    # Retiring it is what makes compute genuinely gone, leaving the committed checkpoint as
    # the only place these bytes still exist.
    assert await coordinator.aretire_computer("session", agent_id="coder", user_id="owner") is True
    assert await coordinator.provider.aget(handles[0].provider_ref) is None
    state = await artifacts.astatus(agent_id="coder", session_id="session", user_id="owner")
    assert state["phase"] == "idle" and state["has_checkpoint"] and not state["compute_allocated"]
    listing = await client.get("/agents/coder/sessions/session/sandbox/artifacts")
    assert listing.status_code == 200 and listing.json()["run_id"] == run_id, listing.text
    assert any(value["path"] == "fixture-effects.txt" for value in listing.json()["files"])
    response = await client.get(
        "/agents/coder/sessions/session/sandbox/artifact", params={"path": "fixture-effects.txt"}
    )
    assert response.status_code == 200 and response.text == run_id + "\n", response.text
    assert response.headers["x-agno-checkpoint"] and response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    # Pins the runtime media type against the route's OpenAPI declaration.
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["cache-control"] == "private, no-store"
    sync = await asyncio.to_thread(
        artifacts.read, "fixture-effects.txt", agent_id="coder", session_id="session", user_id="owner"
    )
    assert sync.content == response.content


async def test_exact_owner_and_agent_required(service):
    _, artifacts = await completed(service)
    for agent_id, user_id in (("coder", None), ("coder", "attacker"), ("different", "owner")):
        with pytest.raises(SandboxSessionNotFound):
            await artifacts.aread("fixture-effects.txt", agent_id=agent_id, session_id="session", user_id=user_id)
    client, _, _, _ = service
    assert (await client.get("/agents/other/sessions/session/sandbox")).status_code == 404


async def test_paths_native_state_and_limits(service):
    _, artifacts = await completed(service)
    for path in ("../native/session.db", "/runtime/native/session.db", "a/../fixture-effects.txt", "a\\b", ""):
        with pytest.raises(SandboxError):
            await artifacts.aread(path, agent_id="coder", session_id="session", user_id="owner")
    with pytest.raises(SandboxArtifactNotFound):
        await artifacts.aread("native/session.db", agent_id="coder", session_id="session", user_id="owner")
    artifacts.max_file_bytes = 1
    with pytest.raises(SandboxError, match="limit"):
        await artifacts.aread("fixture-effects.txt", agent_id="coder", session_id="session", user_id="owner")


async def test_rewriting_session_data_does_not_hide_the_artifacts(service):
    """A session edit must not strand the artifacts of a completed turn.

    PATCH /sessions/{id} rewrites session_data wholesale, so anything the read depends
    on living there would disappear on an ordinary edit. The checkpoint is read from the
    binding row, which an edit cannot touch.
    """
    _, artifacts = await completed(service)
    store = artifacts.store
    await store._transaction(lambda c: c.execute(update(store.sessions).values(session_data={})))
    listing = await artifacts.alist(agent_id="coder", session_id="session", user_id="owner")
    assert "fixture-effects.txt" in [entry["path"] for entry in listing["files"]]


async def test_a_deleted_session_takes_its_artifacts_with_it(service):
    """Deleting the session cascades its binding away, so the checkpoint is unreachable.

    This is what stops a recreated session from inheriting the previous one's files: the
    replacement starts from a fresh binding with its own incarnation and no checkpoint.
    """
    _, artifacts = await completed(service)
    store = artifacts.store
    before = await artifacts._record("coder", "session", "owner")
    await store._transaction(
        lambda c: (
            c.execute(delete(store.runs).where(store.runs.c.session_id == "session")),
            c.execute(delete(store.sessions).where(store.sessions.c.session_id == "session")),
        )
    )
    assert await store._transaction(lambda c: c.execute(select(store.bindings)).first()) is None
    with pytest.raises(SandboxSessionNotFound):
        await artifacts.alist(agent_id="coder", session_id="session", user_id="owner")
    client, _, _, _ = service
    assert (await client.get("/agents/coder/sessions/session/sandbox")).status_code == 404
    assert before["incarnation"]


async def test_checkpoint_identity_and_bytes_are_verified(service):
    _, artifacts = await completed(service)
    record = await artifacts._record("coder", "session", "owner")
    wrong = dict(record)
    wrong["checkpoint_identity"] = {**record["checkpoint_identity"], "session_id": "other"}
    with pytest.raises(SandboxError, match="match"):
        await asyncio.to_thread(artifacts._inspect, wrong, "fixture-effects.txt", 0, 1)
    (artifacts.objects.root / record["checkpoint"]["sha256"]).write_bytes(b"corrupt")
    with pytest.raises(SandboxError, match="size"):
        await artifacts.alist(agent_id="coder", session_id="session", user_id="owner")


async def test_http_user_isolation_and_missing_identity(service):
    import httpx

    await completed(service)
    _, _, app, _ = service

    # Exercise the endpoint against identity already verified by auth middleware;
    # JWT signature verification belongs to the existing middleware test suite.
    async def scoped(scope, receive, send):
        scope.setdefault("state", {}).update(user_id="attacker", user_isolation_enabled=True)
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scoped), base_url="http://test") as client:
        response = await client.get(
            "/agents/coder/sessions/session/sandbox/artifact",
            params={"path": "fixture-effects.txt", "user_id": "owner"},
        )
        assert response.status_code == 404, response.text


async def test_artifacts_remain_at_last_completed_turn_during_new_execution(service):
    client, agent, app, _ = service
    first, artifacts = await completed(service)
    agent.runtime_config = {"delay": 10}
    response = await client.post(
        "/agents/coder/runs",
        data={
            "message": "pending",
            "session_id": "session",
            "user_id": "owner",
            "stream": "false",
            "background": "true",
        },
    )
    run_id = response.json()["run_id"]

    async def running():
        while (await artifacts.astatus(agent_id="coder", session_id="session", user_id="owner"))["phase"] == "idle":
            await asyncio.sleep(0.05)

    await asyncio.wait_for(running(), 10)
    result = await artifacts.aread("fixture-effects.txt", agent_id="coder", session_id="session", user_id="owner")
    assert result.run_id == first and result.content == (first + "\n").encode()
    # The same selection through the registered route: the live workspace has
    # already been changed by the running turn, so different bytes exist.
    served = await client.get("/agents/coder/sessions/session/sandbox/artifact", params={"path": "fixture-effects.txt"})
    assert served.status_code == 200, served.text
    assert served.content == (first + "\n").encode()
    assert served.headers["x-agno-run-id"] == first
    await client.post(f"/agents/coder/runs/{run_id}/cancel", params={"session_id": "session"})


async def test_malformed_artifact_paths_are_client_errors(service):
    client, _, _, _ = service
    await completed(service)
    for path in (
        "../native/session.db",
        "/runtime/native/session.db",
        "a/../fixture-effects.txt",
        "a\\b",
        "",
        "fixture-effects.txt/",
    ):
        response = await client.get("/agents/coder/sessions/session/sandbox/artifact", params={"path": path})
        assert response.status_code == 400, (path, response.status_code, response.text)


async def test_addressable_artifact_paths_with_no_content_are_not_found(service):
    client, _, _, _ = service
    await completed(service)
    # Native state is unaddressable rather than forbidden: the workspace prefix
    # makes it a path the archive does not contain.
    for path in ("native/session.db", "absent.txt"):
        response = await client.get("/agents/coder/sessions/session/sandbox/artifact", params={"path": path})
        assert response.status_code == 404, (path, response.status_code, response.text)


async def test_resolution_precedes_path_validation(service):
    client, _, _, _ = service
    await completed(service)
    response = await client.get(
        "/agents/coder/sessions/absent-session/sandbox/artifact", params={"path": "../native/session.db"}
    )
    assert response.status_code == 404, response.text


async def test_omitted_artifact_path_stays_a_validation_error(service):
    client, _, _, _ = service
    await completed(service)
    response = await client.get("/agents/coder/sessions/session/sandbox/artifact")
    assert response.status_code == 422, response.text


class _Recorded:
    """Delegates to the real object, recording which attributes were used."""

    def __init__(self, target, log, label):
        self._target, self._log, self._label = target, log, label

    def __getattr__(self, name):
        value = getattr(self._target, name)
        if callable(value):

            def recorded(*args, **kwargs):
                self._log.append(self._label + "." + name + "()")
                return value(*args, **kwargs)

            return recorded
        self._log.append(self._label + "." + name)
        return value


async def test_reads_never_reach_the_compute_provider(service):
    """Status, listing and download are persisted-state reads.

    Warm reuse makes this load-bearing: a read must not create, resume, execute
    on or otherwise mutate compute, so the provider must not be called at all.
    """
    client, agent, _, _ = service
    await completed(service)
    log: list = []
    coordinator = _harness.coordinator(agent)
    rows = await _rows(coordinator.store)
    provider, transfer = coordinator.provider, coordinator.transfer
    coordinator.provider = _Recorded(provider, log, "provider")
    coordinator.transfer = _Recorded(transfer, log, "transfer")
    try:
        status = await client.get("/agents/coder/sessions/session/sandbox")
        listing = await client.get("/agents/coder/sessions/session/sandbox/artifacts")
        download = await client.get(
            "/agents/coder/sessions/session/sandbox/artifact", params={"path": "fixture-effects.txt"}
        )
    finally:
        coordinator.provider, coordinator.transfer = provider, transfer
    assert (status.status_code, listing.status_code, download.status_code) == (200, 200, 200)
    assert [entry for entry in log if entry.endswith("()")] == [], log
    assert [entry for entry in log if entry.startswith("provider")] == [], log
    assert await _rows(coordinator.store) == rows


async def test_a_reference_whose_object_is_gone_is_storage_unavailable(service):
    """Retention or storage loss leaves a published reference with no object.

    That is storage being unavailable, not a servable conflict, so it must not be
    answered as a 409 by the generic SandboxError clause.
    """
    client, _, _, _ = service
    _, artifacts = await completed(service)
    record = await artifacts._record("coder", "session", "owner")
    await artifacts.objects.adelete(CheckpointRef(**record["checkpoint"]))

    download = await client.get(
        "/agents/coder/sessions/session/sandbox/artifact", params={"path": "fixture-effects.txt"}
    )
    assert download.status_code == 503, (download.status_code, download.text)
    assert download.json()["detail"] == "Checkpoint storage is unavailable"
    listing = await client.get("/agents/coder/sessions/session/sandbox/artifacts")
    assert listing.status_code == 503, (listing.status_code, listing.text)
    # Status reads the persisted record only, so it still answers and still reports
    # the checkpoint the session committed.
    status = await client.get("/agents/coder/sessions/session/sandbox")
    assert status.status_code == 200 and status.json()["has_checkpoint"] is True
    # A malformed client path is still a client error in this state.
    malformed = await client.get("/agents/coder/sessions/session/sandbox/artifact", params={"path": "../escape"})
    assert malformed.status_code == 400, malformed.text


async def _rows(store):
    """The binding and run rows a read must leave exactly as it found them."""

    def read(connection):
        binding = dict(connection.execute(select(store.bindings)).mappings().one())
        runs = [dict(row) for row in connection.execute(select(store.runs)).mappings().all()]
        return binding, runs

    return await store._transaction(read)


class _Refuses:
    """Fails on any compute or transfer operation, so a read that needs one cannot pass."""

    _FORBIDDEN = (
        "create",
        "acreate",
        "find",
        "afind",
        "get",
        "aget",
        "exec",
        "aexec",
        "rpc",
        "arpc",
        "pause",
        "apause",
        "resume",
        "aresume",
        "stop",
        "astop",
        "destroy",
        "adestroy",
        "capture",
        "acapture",
        "restore",
        "arestore",
    )

    def __init__(self, target, label):
        self._target, self._label = target, label

    def __getattr__(self, name):
        if name in self._FORBIDDEN:
            raise AssertionError(f"An artifact read called {self._label}.{name}")
        return getattr(self._target, name)


async def test_reads_still_succeed_when_every_compute_operation_refuses(service):
    """The counting test above proves nothing was called; this one would break if it were.

    A read resolves its coordinator the same way a turn does, so the provider and the
    transfer are reachable from the request. Only the checkpoint store may be touched.
    """
    client, agent, _, _ = service
    await completed(service)
    coordinator = _harness.coordinator(agent)
    provider, transfer = coordinator.provider, coordinator.transfer
    coordinator.provider = _Refuses(provider, "provider")
    coordinator.transfer = _Refuses(transfer, "transfer")
    try:
        status = await client.get("/agents/coder/sessions/session/sandbox")
        listing = await client.get("/agents/coder/sessions/session/sandbox/artifacts")
        download = await client.get(
            "/agents/coder/sessions/session/sandbox/artifact", params={"path": "fixture-effects.txt"}
        )
    finally:
        coordinator.provider, coordinator.transfer = provider, transfer
    assert (status.status_code, listing.status_code, download.status_code) == (200, 200, 200)
    assert download.content and download.headers["content-type"] == "application/octet-stream"


async def test_a_read_resolves_the_same_checkpoint_store_a_turn_would(service):
    """Reading from a different store than execution wrote to would serve nothing, or worse.

    The route asks the harness for the agent's coordinator rather than choosing storage
    itself, so the explicit checkpoints= of this fixture is what the read uses.
    """
    client, agent, _, _ = service
    _, artifacts = await completed(service)
    coordinator = _harness.coordinator(agent)
    assert artifacts.objects is coordinator.transfer.store is agent.sandbox.checkpoints
    assert _harness.coordinator(agent) is coordinator
    status = await client.get("/agents/coder/sessions/session/sandbox")
    assert status.status_code == 200 and status.json()["has_checkpoint"] is True


def _unconfigured(suffix):
    """A sandbox-backed agent with no checkpoints= of its own."""
    from agno.db.postgres import PostgresDb
    from agno.sandbox.docker import DockerSandbox
    from agno.sandbox.fixture import FixtureAgent

    agent = FixtureAgent(
        id="unconfigured-" + suffix,
        sandbox=DockerSandbox(IMAGE, namespace="unconfigured-" + suffix, env={"AGNO_SANDBOX_TEST_RUNTIME": "1"}),
        db=PostgresDb(
            db_url=URL,
            session_table="unconfigured_sessions_" + suffix,
            sandbox_table="unconfigured_bindings_" + suffix,
        ),
    )
    assert agent.sandbox.checkpoints is None
    return agent


async def test_an_unconfigured_sandbox_is_refused_while_a_queue_worker_runs(service):
    """A durable queue hands retries to any replica, and none can read this host's default directory.

    The harness refuses that configuration instead of letting recovery fail later, so there is no
    effective store for a read to resolve either. An artifact read must not invent one.
    """
    _, existing, _, _ = service
    unconfigured = _unconfigured("queued")
    try:
        with pytest.raises(ValueError, match="other queue replicas cannot read"):
            _harness.coordinator(unconfigured)
        # The configured agent in the same process is unaffected.
        assert _harness.coordinator(existing).transfer.store is existing.sandbox.checkpoints
    finally:
        unconfigured.db.db_engine.dispose()


async def test_without_a_queue_worker_the_default_store_is_the_harness_default(tmp_path, monkeypatch):
    """With no checkpoints= and no queue, the harness uses its own default; a read must use that one.

    This covers the default branch of the existing configuration, not a second mechanism of our
    own. It takes no `service`, because that fixture runs a queue worker, which the branch above
    covers. The default directory is redirected so the run never touches a real home directory.
    """
    from agno.os.job_queue import get_active_queue_worker
    from agno.sandbox.checkpoint import FileCheckpointStore

    assert get_active_queue_worker() is None, "this branch requires no active queue worker"
    monkeypatch.setattr(_harness, "_DEFAULT_CHECKPOINTS", tmp_path / "harness-default")
    unconfigured = _unconfigured("solo")
    try:
        coordinator = _harness.coordinator(unconfigured)
        store = coordinator.transfer.store
        assert isinstance(store, FileCheckpointStore)
        assert store.root == _harness._DEFAULT_CHECKPOINTS
        # The read uses the coordinator the agent already has, so it opens this same object.
        assert _harness.coordinator(unconfigured).transfer.store is store
        assert SandboxArtifacts(coordinator.store, store).objects is store
    finally:
        unconfigured.db.db_engine.dispose()


async def test_corrupted_checkpoint_bytes_are_a_conflict_not_missing_storage(service):
    """A published object that no longer matches its reference is a conflict, not absent storage.

    Both map to SandboxError, so without the ordering in the route they would collapse into
    one response. Status does not open the archive, so it keeps answering.
    """
    client, _, _, _ = service
    _, artifacts = await completed(service)
    record = await artifacts._record("coder", "session", "owner")
    (artifacts.objects.root / record["checkpoint"]["sha256"]).write_bytes(b"corrupt")

    status = await client.get("/agents/coder/sessions/session/sandbox")
    listing = await client.get("/agents/coder/sessions/session/sandbox/artifacts")
    download = await client.get(
        "/agents/coder/sessions/session/sandbox/artifact", params={"path": "fixture-effects.txt"}
    )
    assert status.status_code == 200 and status.json()["has_checkpoint"] is True
    assert (listing.status_code, download.status_code) == (409, 409), (listing.text, download.text)


async def test_a_successful_second_turn_switches_the_served_checkpoint(service):
    """The visible artifact moves only once a new checkpoint is committed.

    The fixture runtime appends its run id to the file, and the second turn restores the
    first turn's workspace before running, so the committed bytes grow by one line. That
    is the switch: the same path now serves the newer checkpoint's content and run id.
    """
    client, _, _, _ = service
    first, _ = await completed(service)
    served = await client.get("/agents/coder/sessions/session/sandbox/artifact", params={"path": "fixture-effects.txt"})
    assert served.status_code == 200 and served.content == (first + "\n").encode()
    assert served.headers["x-agno-run-id"] == first

    second, _ = await completed(service)
    assert second != first
    served = await client.get("/agents/coder/sessions/session/sandbox/artifact", params={"path": "fixture-effects.txt"})
    assert served.status_code == 200, served.text
    assert served.content == (first + "\n" + second + "\n").encode()
    assert served.headers["x-agno-run-id"] == second
    status = await client.get("/agents/coder/sessions/session/sandbox")
    assert status.json()["last_completed_run_id"] == second


async def test_a_failed_capture_leaves_the_previous_checkpoint_served(service):
    """Storage failing during capture must not advance or hide the recovery point.

    The turn cannot publish, so the previous committed checkpoint stays the one served.
    """
    client, agent, app, _ = service
    first, _ = await completed(service)
    store = agent.sandbox.checkpoints
    original = store.aput

    async def refuse(source):
        raise SandboxError("Checkpoint storage is unavailable for this test")

    store.aput = refuse  # type: ignore[method-assign]
    try:
        response = await client.post(
            "/agents/coder/runs",
            data={"message": "unpublishable", "session_id": "session", "user_id": "owner", "stream": "false"},
        )
        assert response.json()["status"] != "COMPLETED", response.text
    finally:
        store.aput = original  # type: ignore[method-assign]

    served = await client.get("/agents/coder/sessions/session/sandbox/artifact", params={"path": "fixture-effects.txt"})
    assert served.status_code == 200, served.text
    assert served.content == (first + "\n").encode()
    assert served.headers["x-agno-run-id"] == first
    status = await client.get("/agents/coder/sessions/session/sandbox")
    assert status.json()["last_completed_run_id"] == first and status.json()["phase"] == "idle"


async def test_an_unresolvable_checkpoint_store_is_reported_as_unavailable_storage(tmp_path):
    """A read whose agent has no store a queue replica could use must not answer as a server fault.

    The harness refuses a host-local default once a queue worker is active, so resolution raises
    for an authorized request on a real session. That is this session's checkpoint storage being
    unavailable, which this surface already reports, not an unhandled error.
    """
    from uuid import uuid4

    import httpx
    from sqlalchemy import select

    from agno.job_queue.config import QueueConfig, RedisCoordination
    from agno.os import AgentOS
    from agno.sandbox.postgres import _SandboxStore

    monkeypatched = tmp_path / "harness-default"
    original_default = _harness._DEFAULT_CHECKPOINTS
    _harness._DEFAULT_CHECKPOINTS = monkeypatched
    # Short: Postgres caps generated index names at 63 characters.
    suffix = uuid4().hex[:6]
    unconfigured = _unconfigured(suffix)
    db = unconfigured.db
    queue = QueueConfig(
        durable=True,
        db=db,
        poll_interval=0.05,
        redis=RedisCoordination(url=REDIS, key_prefix="unresolvable-" + suffix),
    )
    app = AgentOS(id="unresolvable-" + suffix, agents=[unconfigured], db=db, queue=queue, telemetry=False).get_app()
    store = _SandboxStore(db)

    def write(connection):
        if connection.execute(select(store.sessions)).first() is None:
            connection.execute(
                store.sessions.insert().values(
                    session_id="session",
                    session_type="agent",
                    agent_id=unconfigured.get_id(),
                    user_id="owner",
                    session_data={},
                    created_at=1,
                )
            )

    try:
        await store._transaction(write)
        async with app.router.lifespan_context(app):
            # raise_app_exceptions=False: observe the response a real client receives, since the
            # transport otherwise re-raises what the server already answered.
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                base = "/agents/" + unconfigured.get_id() + "/sessions/session/sandbox"
                for path, params in (
                    (base, None),
                    (base + "/artifacts", None),
                    (base + "/artifact", {"path": "a.txt"}),
                ):
                    response = await client.get(path, params=params)
                    assert response.status_code == 503, (path, response.status_code, response.text)
                    assert response.json()["detail"] == "Checkpoint storage is unavailable"
                # A session this caller does not own is still refused before any of that.
                missing = await client.get(base.replace("/session/", "/other-session/"))
                assert missing.status_code == 404, missing.text
    finally:
        _harness._DEFAULT_CHECKPOINTS = original_default
        db.db_engine.dispose()
    assert not monkeypatched.exists(), "resolution must not create a default store directory here"
