"""Attachments over real AgentOS routes, the durable queue, and checkpoint recovery, with the credential-free fixture runtime.

Uploads and JSON items are validated before anything is queued; the accepted bytes are stored once, as the canonical
wire in the queue payload, and every later copy (running run row, workspace, checkpoint) is produced from it.
"""

import asyncio
import base64
import json
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from agno.media import File
from agno.sandbox import _harness
from agno.sandbox.checkpoint import CheckpointRef
from tests.integration.sandbox.test_agentos import IMAGE, REDIS, URL, settled
from tests.integration.sandbox.test_agentos import service as _service_fixture

service = _service_fixture
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not URL or not IMAGE or not REDIS, reason="Enable dedicated Docker, Postgres and Redis"),
]

PNG = b"\x89PNG\r\n\x1a\nfixture"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def all_rows(agent):
    table = agent.db._get_table("jobs")
    with agent.db.db_engine.begin() as connection:
        return connection.execute(select(func.count()).select_from(table)).scalar_one()


def queued_rows(agent, key):
    table = agent.db._get_table("jobs")
    with agent.db.db_engine.begin() as connection:
        return connection.execute(
            select(func.count()).select_from(table).where(table.c.idempotency_key == key)
        ).scalar_one()


async def post(client, *, message="look", session="session", files=None, headers=None, **form):
    data = {"message": message, "session_id": session, "stream": "false", **form}
    return await client.post("/agents/coder/runs", data=data, files=files, headers=headers)


async def workspace_after(agent, tmp_path):
    """The workspace of the session's last completed checkpoint, restored into a fresh directory."""
    coordinator = _harness.coordinator(agent)
    row = await coordinator.store._transaction(
        lambda c: dict(c.execute(select(coordinator.store.bindings)).mappings().one())
    )
    target = tmp_path / uuid4().hex
    await coordinator.transfer.store.arestore(CheckpointRef(**row["record"]["checkpoint"]), target)
    return target / "workspace"


async def test_multipart_upload_reaches_the_run_input_the_workspace_and_the_checkpoint(service, tmp_path):
    client, agent, _, handles = service
    response = await post(
        client,
        files=[("files", ("notes.txt", b"uploaded bytes", "text/plain")), ("files", ("photo.png", PNG, "image/png"))],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "COMPLETED", body
    stored = await agent.aget_run_output(body["run_id"], "session")
    assert [file.get_content_bytes() for file in stored.input.files] == [b"uploaded bytes"]
    assert [image.get_content_bytes() for image in stored.input.images] == [PNG]
    folder = (await workspace_after(agent, tmp_path)) / ".agno/uploads" / body["run_id"]
    assert (folder / "notes.txt").read_bytes() == b"uploaded bytes"
    assert (folder / "image-1.png").read_bytes() == PNG
    assert len(handles) == 1


async def test_json_images_and_input_files_are_accepted_with_the_same_result(service, tmp_path):
    client, agent, _, _ = service
    response = await post(
        client,
        images=json.dumps([{"content": b64(PNG), "format": "png"}]),
        input_files=json.dumps([{"content": b64(b"json bytes"), "filename": "j.txt"}]),
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    folder = (await workspace_after(agent, tmp_path)) / ".agno/uploads" / run_id
    assert (folder / "j.txt").read_bytes() == b"json bytes" and (folder / "image-1.png").read_bytes() == PNG


REJECTED = {
    "audio upload": dict(files=[("files", ("a.wav", b"RIFF", "audio/wav"))]),
    "video upload": dict(files=[("files", ("v.mp4", b"data", "video/mp4"))]),
    "empty upload": dict(files=[("files", ("empty.txt", b"", "text/plain"))]),
    "unknown upload type": dict(files=[("files", ("x.bin", b"data", "application/x-unknown"))]),
    "one unreadable upload among good ones": dict(
        files=[("files", ("ok.txt", b"ok", "text/plain")), ("files", ("empty.txt", b"", "text/plain"))]
    ),
    "service path": dict(input_files=json.dumps([{"content": b64(b"x"), "filepath": "/etc/passwd"}])),
    "remote reference": dict(input_files=json.dumps([{"content": b64(b"x"), "url": "https://example.com/a"}])),
    "media reference": dict(input_files=json.dumps([{"content": b64(b"x"), "media_reference": {"storage_key": "k"}}])),
    "unknown key": dict(input_files=json.dumps([{"content": b64(b"x"), "surprise": 1}])),
    "invalid base64": dict(input_files=json.dumps([{"content": "not base64!"}])),
    "empty content": dict(input_files=json.dumps([{"content": ""}])),
    "image filename": dict(images=json.dumps([{"content": b64(PNG), "format": "png", "filename": "p.png"}])),
    "json audio": dict(audio=json.dumps([{"content": b64(b"x")}])),
    "retired ticket key as a field": dict(sandbox_media=json.dumps([])),
    "reserved media field": dict(media="{}"),
    "seventeen attachments": dict(
        input_files=json.dumps([{"content": b64(b"x"), "filename": f"{i}.txt"} for i in range(17)])
    ),
    "over the decoded total": dict(
        input_files=json.dumps([{"content": b64(b"a" * 300_000), "filename": f"{i}.txt"} for i in range(2)])
    ),
}


@pytest.mark.parametrize("name", list(REJECTED))
async def test_rejected_input_leaves_no_queue_row_run_or_compute(service, name):
    client, agent, _, handles = service
    response = await post(client, **REJECTED[name])
    assert response.status_code in (400, 422), (name, response.status_code, response.text)
    assert all_rows(agent) == 0 and handles == []
    assert await agent.aget_session("session") is None


async def test_rejection_detail_never_echoes_the_content(service):
    client, _, _, _ = service
    secret = b64(b"top secret attachment bytes")
    response = await post(client, input_files=json.dumps([{"content": secret, "mime_type": "not/valid"}]))
    assert response.status_code in (400, 422) and secret not in response.text


async def test_background_and_streamed_uploads_run_the_same_path(service, tmp_path):
    client, agent, app, _ = service
    background = await post(
        client, session="bg", background="true", files=[("files", ("bg.txt", b"background", "text/plain"))]
    )
    assert background.status_code == 202, background.text
    assert (await settled(app, background.json()["run_id"]))["status"] == "completed"
    stored = await agent.aget_run_output(background.json()["run_id"], "bg")
    assert [file.get_content_bytes() for file in stored.input.files] == [b"background"]
    streamed = await post(client, session="st", stream="true", files=[("files", ("st.txt", b"streamed", "text/plain"))])
    assert streamed.status_code == 200 and "RunCompleted" in streamed.text


@pytest.mark.parametrize("replace_computer", [True, False], ids=["replacement_compute", "resumed_warm_compute"])
async def test_two_turns_keep_each_turns_bytes_under_the_same_filename(service, tmp_path, replace_computer):
    # The harness keeps a turn's computer warm (paused) for the next turn. Removing it between turns forces the
    # next turn to restore from the checkpoint onto a new computer, as the coordinator tests do for a lost one.
    client, agent, _, handles = service

    async def turn(**kwargs):
        response = await post(client, **kwargs)
        if replace_computer:
            await _harness.coordinator(agent).provider.adestroy(handles[-1])
        return response

    first = await turn(files=[("files", ("same.txt", b"turn one", "text/plain"))])
    second = await turn(files=[("files", ("same.txt", b"turn two, different bytes", "text/plain"))])
    third = await turn(message="no attachment")
    for response in (first, second, third):
        assert response.status_code == 200 and response.json()["status"] == "COMPLETED", response.text
    uploads = (await workspace_after(agent, tmp_path)) / ".agno/uploads"
    one, two = first.json()["run_id"], second.json()["run_id"]
    assert (uploads / one / "same.txt").read_bytes() == b"turn one"
    assert (uploads / two / "same.txt").read_bytes() == b"turn two, different bytes"
    assert not (uploads / third.json()["run_id"]).exists()
    assert len({handle.provider_ref for handle in handles}) == (3 if replace_computer else 1)


# --- idempotency with attachments ----------------------------------------------------------------------


async def test_an_identical_retry_returns_the_original_run_and_a_changed_one_is_refused_keeping_the_accepted_bytes(
    service,
):
    client, agent, app, handles = service
    headers = {"Idempotency-Key": "upload"}
    original = await post(
        client, background="true", headers=headers, files=[("files", ("a.txt", b"original", "text/plain"))]
    )
    assert original.status_code == 202, original.text
    run_id = original.json()["run_id"]
    assert (await settled(app, run_id))["status"] == "completed"
    same = await post(
        client, background="true", headers=headers, files=[("files", ("a.txt", b"original", "text/plain"))]
    )
    changed = await post(
        client, background="true", headers=headers, files=[("files", ("a.txt", b"CHANGED", "text/plain"))]
    )
    other_session = await post(
        client,
        session="elsewhere",
        background="true",
        headers=headers,
        files=[("files", ("a.txt", b"original", "text/plain"))],
    )
    assert same.status_code == 202 and same.json()["run_id"] == run_id, same.text
    # A retry that changes the attachments or the session is a different submission under the same key.
    assert (changed.status_code, other_session.status_code) == (409, 409), (changed.text, other_session.text)
    stored = await agent.aget_run_output(run_id, "session")
    assert [file.get_content_bytes() for file in stored.input.files] == [b"original"]
    assert queued_rows(agent, "upload") == 1 and len(handles) == 1


async def test_concurrent_identical_uploads_create_and_execute_one_run(service):
    client, agent, app, handles = service

    def upload():
        return post(
            client,
            background="true",
            headers={"Idempotency-Key": "burst-upload"},
            files=[("files", ("b.txt", b"burst", "text/plain"))],
        )

    responses = await asyncio.gather(*(upload() for _ in range(5)))
    assert {response.status_code for response in responses} == {202}, [r.text for r in responses]
    run_ids = {response.json()["run_id"] for response in responses}
    assert len(run_ids) == 1
    assert (await settled(app, run_ids.pop()))["status"] == "completed"
    assert queued_rows(agent, "burst-upload") == 1 and len(handles) == 1


async def test_the_same_key_and_upload_under_two_users_are_two_independent_runs(service):
    client, agent, app, handles = service
    runs = {}
    for user in ("alice", "bob"):
        response = await post(
            client,
            session=f"{user}-session",
            user_id=user,
            background="true",
            headers={"Idempotency-Key": "shared-upload"},
            files=[("files", ("u.txt", f"{user}'s bytes".encode(), "text/plain"))],
        )
        assert response.status_code == 202, response.text
        runs[user] = response.json()["run_id"]
        assert (await settled(app, runs[user]))["status"] == "completed"
    assert runs["alice"] != runs["bob"] and queued_rows(agent, "shared-upload") == 2 and len(handles) == 2
    alice = await agent.aget_run_output(runs["alice"], "alice-session", user_id="alice")
    assert [file.get_content_bytes() for file in alice.input.files] == [b"alice's bytes"]
    assert await agent.aget_run_output(runs["alice"], "alice-session", user_id="bob") is None


# --- Python callers --------------------------------------------------------------------------------------------


async def test_a_python_background_run_reads_the_local_file_once_and_survives_its_removal(service, tmp_path):
    _, agent, app, _ = service
    source = tmp_path / "local.txt"
    source.write_bytes(b"local file bytes")
    pending = await agent.arun("read it", session_id="py", background=True, files=[File(filepath=source)])
    source.unlink()
    assert (await settled(app, pending.run_id))["status"] == "completed"
    stored = await agent.aget_run_output(pending.run_id, "py")
    assert [file.get_content_bytes() for file in stored.input.files] == [b"local file bytes"]


async def test_a_direct_python_run_carries_attachments_to_the_checkpoint(service, tmp_path):
    _, agent, _, _ = service
    run = await agent.arun("read it", session_id="direct", files=[File(content=b"direct bytes", filename="d.txt")])
    assert run.status == "COMPLETED"
    folder = (await workspace_after(agent, tmp_path)) / ".agno/uploads" / run.run_id
    assert (folder / "d.txt").read_bytes() == b"direct bytes"


# --- a second process: reconstruction from the ticket, and a real local server ----------------------------------------


def _start_service(agent, app, tmp_path, **queue):
    import os
    import socket
    import subprocess
    import sys
    from pathlib import Path

    import agno

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    db = agent.db
    config = {
        "db_url": URL,
        "redis_url": REDIS,
        "image": IMAGE,
        "prefix": app.state.queue_worker.config.redis.key_prefix,
        "checkpoints": str(agent.sandbox.checkpoints.root),
        "port": port,
        "queue": queue,
        "tables": {
            "session_table": db.session_table_name,
            "runs_table": db.runs_table_name,
            "job_table": db.job_table_name,
            "sandbox_table": db.sandbox_table_name,
        },
    }
    env = {**os.environ, "PYTHONPATH": str(Path(agno.__file__).resolve().parents[1])}
    script = Path(__file__).with_name("service_process.py")
    process = subprocess.Popen(
        [sys.executable, str(script), json.dumps(config)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    return process, port


async def _wait_ready(process, port):
    import httpx

    async with httpx.AsyncClient(timeout=2) as probe:
        for _ in range(240):
            if process.poll() is not None:
                raise AssertionError("service process exited: " + process.stdout.read().decode()[-2000:])
            try:
                if (await probe.get(f"http://127.0.0.1:{port}/health")).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.25)
    raise AssertionError("service process never became ready")


async def test_a_replacement_process_rebuilds_the_attachments_from_the_ticket_alone(service, tmp_path):
    import httpx

    client, agent, app, handles = service
    await app.state.queue_worker.stop()
    source = tmp_path / "gone.txt"
    source.write_bytes(b"python local file")
    uploaded = await post(client, background="true", files=[("files", ("up.txt", b"uploaded bytes", "text/plain"))])
    local = await agent.arun("read it", session_id="session", background=True, files=[File(filepath=source)])
    assert uploaded.status_code == 202, uploaded.text
    source.unlink()
    store = app.state.queue_worker.store
    queued = [uploaded.json()["run_id"], local.run_id]
    assert [(await store.get_job(run_id))["status"] for run_id in queued] == ["queued", "queued"]
    process, port = _start_service(agent, app, tmp_path)
    try:
        await _wait_ready(process, port)
        for run_id in queued:
            assert (await settled(app, run_id))["status"] == "completed"
        # A real request over a real socket to the second process.
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=60) as remote:
            over_tcp = await remote.post(
                "/agents/coder/runs",
                data={"message": "over tcp", "session_id": "session", "stream": "false"},
                files=[("files", ("tcp.txt", b"sent over tcp", "text/plain"))],
            )
        assert over_tcp.status_code == 200 and over_tcp.json()["status"] == "COMPLETED", over_tcp.text
    finally:
        process.terminate()
        process.wait(timeout=30)
    assert handles == []  # this process never ran a turn: everything below was executed elsewhere
    expected = {
        queued[0]: ("up.txt", b"uploaded bytes"),
        queued[1]: ("gone.txt", b"python local file"),
        over_tcp.json()["run_id"]: ("tcp.txt", b"sent over tcp"),
    }
    uploads = (await workspace_after(agent, tmp_path)) / ".agno/uploads"
    for run_id, (name, content) in expected.items():
        stored = await agent.aget_run_output(run_id, "session")
        assert [file.get_content_bytes() for file in stored.input.files] == [content]
        assert (uploads / run_id / name).read_bytes() == content


DAMAGE = {
    "path traversal in a name": lambda wire: wire[0].update(name="../escape"),
    "content that is not base64": lambda wire: wire[0].update(content="not base64!"),
    "a field the wire does not have": lambda wire: wire[0].update(host_path="/etc/passwd"),
    "an unknown kind": lambda wire: wire[0].update(kind="audio"),
}


# What a ticket stores is always the wire list; any other stored value is damage too.
NOT_A_LIST = {"a string": "not a list", "an object": {"images": ["x"]}}


@pytest.mark.parametrize("damage", [*DAMAGE, *NOT_A_LIST])
async def test_a_ticket_whose_attachments_cannot_be_replayed_fails_once_and_keeps_the_previous_checkpoint(
    service, tmp_path, damage
):
    from sqlalchemy import update

    client, agent, app, _ = service
    first = await post(client, files=[("files", ("kept.txt", b"first turn", "text/plain"))])
    assert first.status_code == 200 and first.json()["status"] == "COMPLETED", first.text
    coordinator = _harness.coordinator(agent)

    async def checkpoint():
        row = await coordinator.store._transaction(
            lambda c: dict(c.execute(select(coordinator.store.bindings)).mappings().one())
        )
        return row["record"]["checkpoint"], row["record"]["phase"]

    before = await checkpoint()
    await app.state.queue_worker.stop()
    queued = await post(client, background="true", files=[("files", ("lost.txt", b"never staged", "text/plain"))])
    run_id = queued.json()["run_id"]
    # The ticket is damaged after acceptance: the wire no longer passes the validation every replay repeats.
    store = app.state.queue_worker.store
    payload = (await store.get_job(run_id))["payload"]
    if damage in NOT_A_LIST:
        payload["kwargs"]["media"] = NOT_A_LIST[damage]
    else:
        DAMAGE[damage](payload["kwargs"]["media"])
    table = agent.db._get_table("jobs")
    with agent.db.db_engine.begin() as connection:
        connection.execute(update(table).where(table.c.id == run_id).values(payload=payload))
    process, port = _start_service(agent, app, tmp_path)
    try:
        await _wait_ready(process, port)
        job = await settled(app, run_id)
    finally:
        process.terminate()
        process.wait(timeout=30)
    # Rejected input cannot be cured by a retry: one attempt, failed on the ticket, ERROR on the run, nothing executed.
    assert job["status"] == "failed" and job["attempt"] == 1 and job["error"].startswith("permanent:"), job
    stored = await agent.aget_run_output(run_id, "session")
    assert stored.status == "ERROR" and stored.content
    assert await checkpoint() == before
    uploads = (await workspace_after(agent, tmp_path)) / ".agno/uploads"
    assert sorted(path.name for path in uploads.iterdir()) == [first.json()["run_id"]]


async def test_another_user_cannot_attach_files_to_someone_elses_session(service):
    client, agent, app, handles = service
    mine = await post(
        client,
        session="alice-only",
        user_id="alice",
        files=[("files", ("a.txt", b"alice", "text/plain"))],
    )
    assert mine.status_code == 200 and mine.json()["status"] == "COMPLETED", mine.text
    rows, computers = all_rows(agent), len(handles)
    intruder = await post(
        client,
        session="alice-only",
        user_id="bob",
        files=[("files", ("b.txt", b"bob", "text/plain"))],
    )
    assert intruder.status_code in (403, 404), intruder.text
    assert all_rows(agent) == rows and len(handles) == computers


async def test_a_damaged_ticket_whose_run_row_is_missing_still_ends_in_error_on_a_run(service, tmp_path):
    from sqlalchemy import delete, update

    client, agent, app, _ = service
    await app.state.queue_worker.stop()
    queued = await post(client, background="true", files=[("files", ("lost.txt", b"never staged", "text/plain"))])
    run_id = queued.json()["run_id"]
    store = app.state.queue_worker.store
    payload = (await store.get_job(run_id))["payload"]
    payload["kwargs"]["media"][0]["name"] = "../escape"
    jobs, runs = agent.db._get_table("jobs"), agent.db._get_table("runs")
    with agent.db.db_engine.begin() as connection:
        connection.execute(update(jobs).where(jobs.c.id == run_id).values(payload=payload))
        # The submitter died between accepting the ticket and writing its run row.
        connection.execute(delete(runs).where(runs.c.run_id == run_id))
    assert await agent.aget_run_output(run_id, "session") is None
    process, port = _start_service(agent, app, tmp_path)
    try:
        await _wait_ready(process, port)
        job = await settled(app, run_id)
    finally:
        process.terminate()
        process.wait(timeout=30)
    assert job["status"] == "failed" and job["attempt"] == 1 and job["error"].startswith("permanent:"), job
    stored = await agent.aget_run_output(run_id, "session")
    assert stored.status == "ERROR" and stored.content


# --- the request body is bounded by the bytes received ------------------------------------------------------------


class _Counting:
    """Wrap the app and count the request-body bytes it actually pulls, and how many it had pulled when it answered."""

    def __init__(self, app):
        self.app, self.received, self.at_response = app, 0, None

    async def __call__(self, scope, receive, send):
        async def counted():
            message = await receive()
            if message["type"] == "http.request":
                self.received += len(message.get("body", b""))
            return message

        async def watched(message):
            if message["type"] == "http.response.start" and self.at_response is None:
                self.at_response = self.received
            await send(message)

        await self.app(scope, counted, watched)


def _multipart(megabytes, *, filename="big.txt"):
    """A lazily generated multipart body with one file of ``megabytes`` MiB, never held in memory."""
    boundary = "agnoBoundary7MA4YWxk"
    fields = {"message": "look", "session_id": "session", "stream": "false"}
    head = "".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        for name, value in fields.items()
    )
    head += f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\n'
    head += "Content-Type: text/plain\r\n\r\n"
    chunk = b"a" * (1024 * 1024)

    async def body():
        yield head.encode()
        for _ in range(megabytes):
            yield chunk
        yield f"\r\n--{boundary}--\r\n".encode()

    return body(), {"content-type": f"multipart/form-data; boundary={boundary}"}


async def _send(app, megabytes, **headers):
    import httpx

    counting = _Counting(app)
    content, base = _multipart(megabytes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=counting), base_url="http://test") as client:
        response = await client.post("/agents/coder/runs", content=content, headers={**base, **headers})
    return response, counting


async def test_an_oversized_upload_is_cut_off_instead_of_being_read_and_spooled_whole(service):
    _, agent, app, handles = service
    response, counting = await _send(app, 24)  # 24 MiB of file, delivered lazily
    assert response.status_code == 413, response.text
    assert counting.received <= 5 * 1024 * 1024, counting.received
    assert all_rows(agent) == 0 and handles == [] and await agent.aget_session("session") is None


async def test_a_content_length_that_understates_the_upload_does_not_bypass_the_bound(service):
    _, agent, app, handles = service
    response, counting = await _send(app, 24, **{"content-length": "200"})
    assert response.status_code == 413 and counting.received <= 5 * 1024 * 1024
    assert all_rows(agent) == 0 and handles == []


async def test_an_upload_at_the_attachment_limit_is_still_accepted_and_one_byte_over_is_refused_as_an_attachment(
    service,
):
    client, agent, _, handles = service
    limit = 512 * 1024
    ok = await post(client, files=[("files", ("edge.bin", b"a" * limit, "text/plain"))])
    assert ok.status_code == 200 and ok.json()["status"] == "COMPLETED", ok.text
    over = await post(client, files=[("files", ("over.bin", b"a" * (limit + 1), "text/plain"))])
    assert over.status_code == 400 and "512 KiB" in over.text, over.text
    assert len(handles) == 1


async def test_a_real_socket_upload_over_the_bound_is_refused_and_the_server_stays_healthy(service, tmp_path):
    import httpx

    _, agent, app, handles = service
    process, port = _start_service(agent, app, tmp_path)
    try:
        await _wait_ready(process, port)
        content, headers = _multipart(24)  # no Content-Length: sent chunked over TCP
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=60) as remote:
            try:
                response = await remote.post("/agents/coder/runs", content=content, headers=headers)
                status = response.status_code
            except httpx.TransportError:
                # The server answers 413 and closes before the client has finished sending, which a client may
                # observe as a reset rather than as the response.
                status = 413
            assert status == 413
            assert (await remote.get("/health")).status_code == 200
    finally:
        process.terminate()
        process.wait(timeout=30)
    assert all_rows(agent) == 0 and handles == []


async def _raw_request(port, declared, sent, *, read=True):
    """One POST over a plain socket declaring ``declared`` body bytes and sending only ``sent`` of them."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    head = (
        f"POST /agents/coder/runs HTTP/1.1\r\nHost: x\r\nContent-Length: {declared}\r\n"
        "Content-Type: multipart/form-data; boundary=B\r\n\r\n"
    )
    writer.write(head.encode() + b"x" * sent)
    await writer.drain()
    try:
        return (await asyncio.wait_for(reader.read(200), 5)).decode(errors="replace") if read else None
    finally:
        writer.close()


async def test_a_declared_length_over_the_bound_is_answered_without_waiting_for_the_body_and_a_dropped_upload_is_harmless(
    service, tmp_path
):
    import httpx

    _, agent, app, handles = service
    process, port = _start_service(agent, app, tmp_path)
    try:
        await _wait_ready(process, port)
        # The header alone decides: the answer comes while the client still owes almost all of the body.
        assert (await _raw_request(port, 5 * 1024 * 1024, 100)).startswith("HTTP/1.1 413")
        # A client that vanishes part-way through a body within the bound is not a server error.
        await _raw_request(port, 3 * 1024 * 1024, 1024 * 1024, read=False)
        await asyncio.sleep(1)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=30) as remote:
            assert (await remote.get("/health")).status_code == 200
    finally:
        process.terminate()
        process.wait(timeout=30)
    assert all_rows(agent) == 0 and handles == []


# --- retention and deletion: what the existing mechanisms actually do ------------------------------------------------


async def test_terminal_tickets_are_purged_by_the_queue_retention_but_pending_ones_keep_their_bytes(service):
    client, agent, app, _ = service
    done = await post(client, background="true", files=[("files", ("done.txt", b"done-marker-bytes", "text/plain"))])
    assert (await settled(app, done.json()["run_id"]))["status"] == "completed"
    await app.state.queue_worker.stop()
    waiting = await post(
        client, background="true", files=[("files", ("wait.txt", b"waiting-marker-bytes", "text/plain"))]
    )
    store = app.state.queue_worker.store
    assert (await store.get_job(done.json()["run_id"]))["payload"]["kwargs"]["media"]
    # The worker's hourly retention pass is this call with its retention_seconds; 0 makes every terminal ticket due.
    assert agent.db.cleanup_jobs(0) == 1
    assert await store.get_job(done.json()["run_id"]) is None
    assert (await store.get_job(waiting.json()["run_id"]))["payload"]["kwargs"]["media"]
    # The run's own input is a separate copy with its own lifetime.
    kept = await agent.aget_run_output(done.json()["run_id"], "session")
    assert [file.get_content_bytes() for file in kept.input.files] == [b"done-marker-bytes"]


async def test_deleting_a_session_removes_its_runs_and_binding_and_a_recreated_session_starts_clean(service, tmp_path):
    client, agent, _, _ = service
    first = await post(client, files=[("files", ("old.txt", b"old-marker-bytes", "text/plain"))])
    assert first.json()["status"] == "COMPLETED", first.text
    coordinator = _harness.coordinator(agent)

    def bindings(connection):
        return connection.execute(select(func.count()).select_from(coordinator.store.bindings)).scalar_one()

    assert await coordinator.store._transaction(bindings) == 1
    assert agent.db.delete_session("session") is True
    assert await agent.aget_run_output(first.json()["run_id"], "session") is None
    assert await coordinator.store._transaction(bindings) == 0
    # A new session under the same id restores nothing the deleted one held.
    second = await post(client, files=[("files", ("new.txt", b"new-marker-bytes", "text/plain"))])
    assert second.json()["status"] == "COMPLETED", second.text
    uploads = (await workspace_after(agent, tmp_path)) / ".agno/uploads"
    assert [path.name for path in uploads.iterdir()] == [second.json()["run_id"]]
    assert not any(uploads.rglob("old.txt"))


async def test_logs_never_contain_attachment_bytes(service):
    import logging

    client, _, app, _ = service
    marker = b"log-marker-bytes-that-must-never-be-logged"
    seen = []

    class Collect(logging.Handler):
        def emit(self, record):
            seen.append(self.format(record))

    handler = Collect(level=logging.DEBUG)
    loggers = [logging.getLogger(name) for name in ("", "agno", "agno-team")]
    for logger in loggers:
        logger.addHandler(handler)
    try:
        ok = await post(client, files=[("files", ("log.txt", marker, "text/plain"))])
        bad = await post(client, input_files=json.dumps([{"content": b64(marker), "surprise": 1}]))
        empty = await post(client, files=[("files", ("empty.txt", b"", "text/plain"))])
    finally:
        for logger in loggers:
            logger.removeHandler(handler)
    assert ok.status_code == 200 and bad.status_code == 400 and empty.status_code == 400
    text = "\n".join(seen)
    assert text, "the handler saw no log records, so the check below would prove nothing"
    assert marker.decode() not in text and b64(marker) not in text


async def test_a_purged_ticket_no_longer_deduplicates_its_key(service):
    client, agent, app, _ = service
    headers = {"Idempotency-Key": "ages-out"}
    files = [("files", ("a.txt", b"same upload", "text/plain"))]
    first = await post(client, background="true", headers=headers, files=files)
    assert (await settled(app, first.json()["run_id"]))["status"] == "completed"
    assert (await post(client, background="true", headers=headers, files=files)).json()["run_id"] == first.json()[
        "run_id"
    ]
    assert agent.db.cleanup_jobs(0) == 1
    again = await post(client, background="true", headers=headers, files=files)
    assert again.status_code == 202 and again.json()["run_id"] != first.json()["run_id"]
    assert queued_rows(agent, "ages-out") == 1


async def test_a_json_image_without_a_format_keeps_an_image_extension_through_the_queue(service, tmp_path):
    client, agent, _, _ = service
    response = await post(client, images=json.dumps([{"content": b64(PNG)}]), background="false")
    assert response.status_code == 200 and response.json()["status"] == "COMPLETED", response.text
    folder = (await workspace_after(agent, tmp_path)) / ".agno/uploads" / response.json()["run_id"]
    assert [path.name for path in folder.iterdir()] == ["image-1.png"]


# --- tickets whose session or run row changed after acceptance ----------------------------------------------------------


def _objects(agent):
    root = agent.sandbox.checkpoints.root
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


async def _damage(agent, app, run_id):
    from sqlalchemy import update

    payload = (await app.state.queue_worker.store.get_job(run_id))["payload"]
    payload["kwargs"]["media"][0]["name"] = "../escape"
    jobs = agent.db._get_table("jobs")
    with agent.db.db_engine.begin() as connection:
        connection.execute(update(jobs).where(jobs.c.id == run_id).values(payload=payload))


async def _run_fresh_worker(agent, app, tmp_path, *, idle=0):
    # ``idle`` keeps the worker polling after it is ready, long enough for several 0.05 s polls and a sweep to act.
    process, port = _start_service(agent, app, tmp_path)
    try:
        await _wait_ready(process, port)
        await asyncio.sleep(idle)
    finally:
        process.terminate()
        process.wait(timeout=30)


async def test_a_damaged_ticket_whose_session_was_deleted_still_fails_once_without_compute_or_a_new_checkpoint(
    service, tmp_path
):
    client, agent, app, handles = service
    first = await post(client, files=[("files", ("one.txt", b"first", "text/plain"))])
    assert first.json()["status"] == "COMPLETED", first.text
    await app.state.queue_worker.stop()
    queued = await post(client, background="true", files=[("files", ("two.txt", b"second", "text/plain"))])
    run_id = queued.json()["run_id"]
    await _damage(agent, app, run_id)
    assert agent.db.delete_session("session") is True
    computers, objects = len(handles), _objects(agent)
    await _run_fresh_worker(agent, app, tmp_path)
    job = await settled(app, run_id)
    # Whether the deleted session is recreated to hold the failure is the queue's existing behavior for any accepted
    # run; what matters here is that nothing ran and nothing was published.
    assert job["status"] == "failed" and job["attempt"] == 1 and job["error"].startswith("permanent:"), job
    assert len(handles) == computers and _objects(agent) == objects


async def test_a_damaged_ticket_whose_run_another_writer_already_ended_keeps_that_outcome(service, tmp_path):
    from sqlalchemy import select, update

    client, agent, app, handles = service
    await app.state.queue_worker.stop()
    queued = await post(client, background="true", files=[("files", ("two.txt", b"second", "text/plain"))])
    run_id = queued.json()["run_id"]
    await _damage(agent, app, run_id)
    runs = agent.db._get_table("runs")
    with agent.db.db_engine.begin() as connection:
        row = connection.execute(select(runs).where(runs.c.run_id == run_id)).mappings().one()
        data = {**row["run_data"], "status": "CANCELLED", "content": "ended elsewhere"}
        connection.execute(update(runs).where(runs.c.run_id == run_id).values(status="CANCELLED", run_data=data))
    await _run_fresh_worker(agent, app, tmp_path)
    job = await settled(app, run_id)
    stored = await agent.aget_run_output(run_id, "session")
    assert job["status"] == "cancelled" and stored.status == "CANCELLED" and stored.content == "ended elsewhere"
    assert handles == [] and _objects(agent) == []


async def test_a_failed_damaged_ticket_is_left_alone_by_a_second_worker(service, tmp_path):
    client, agent, app, handles = service
    await app.state.queue_worker.stop()
    queued = await post(client, background="true", files=[("files", ("two.txt", b"second", "text/plain"))])
    run_id = queued.json()["run_id"]
    await _damage(agent, app, run_id)
    await _run_fresh_worker(agent, app, tmp_path)
    before = await settled(app, run_id)
    await _run_fresh_worker(agent, app, tmp_path, idle=6)
    after = await app.state.queue_worker.store.get_job(run_id)
    stored = await agent.aget_run_output(run_id, "session")
    assert (after["status"], after["attempt"], after["error"]) == (before["status"], before["attempt"], before["error"])
    assert after["status"] == "failed" and after["attempt"] == 1 and stored.status == "ERROR"
    assert handles == [] and _objects(agent) == []


async def test_cancelling_a_queued_run_before_deleting_its_session_leaves_nothing_to_run_or_recreate(service, tmp_path):
    from sqlalchemy import func, select

    client, agent, app, handles = service
    await app.state.queue_worker.stop()
    queued = await post(client, background="true", files=[("files", ("two.txt", b"second", "text/plain"))])
    run_id = queued.json()["run_id"]
    assert (await client.post(f"/agents/coder/runs/{run_id}/cancel")).status_code == 200
    assert agent.db.delete_session("session") is True
    await _run_fresh_worker(agent, app, tmp_path, idle=4)
    job = await app.state.queue_worker.store.get_job(run_id)
    sessions = agent.db._get_table("sessions")
    with agent.db.db_engine.begin() as connection:
        remaining = connection.execute(select(func.count()).select_from(sessions)).scalar_one()
    assert job["status"] == "cancelled" and job["attempt"] == 0
    assert remaining == 0 and handles == [] and _objects(agent) == []
