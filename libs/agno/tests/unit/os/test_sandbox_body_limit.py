"""The body of a run submission to a sandboxed agent is bounded by the bytes actually received, before it is parsed.

Framework form parsing spools every uploaded file to disk and reads the whole body before an attachment limit can
reject it. These tests drive the ASGI middleware directly with chunked bodies that are never held in memory.
"""

import base64
import gc
import json
import weakref
from urllib.parse import urlencode

import pytest

from agno.os.middleware.sandbox_body_limit import MAX_SANDBOX_REQUEST_BODY, SandboxRunBodyLimit

CHUNK = 64 * 1024
LIMIT = 8 * CHUNK
MiB = 1024 * 1024


class Downstream:
    """An app that reads its whole request body, as the framework's form parser does."""

    def __init__(self, status=200):
        self.status, self.called, self.body_seen, self.disconnected = status, 0, 0, False

    async def __call__(self, scope, receive, send):
        self.called += 1
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                self.disconnected = True
                break
            self.body_seen += len(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": self.status, "headers": []})
        await send({"type": "http.response.body", "body": b"downstream"})


async def call(app, *, chunks, path="/agents/coder/runs", method="POST", headers=None):
    """Run the app with a body of ``chunks`` chunks, counting what the client was asked for."""
    pulled = 0
    sent = []

    async def receive():
        nonlocal pulled
        if pulled >= chunks:
            return {"type": "http.disconnect"}
        pulled += 1
        return {"type": "http.request", "body": b"x" * CHUNK, "more_body": pulled < chunks}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": method, "path": path, "headers": headers or []}
    await app(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body, pulled


def limited(downstream, ids=("coder",), limit=LIMIT):
    return SandboxRunBodyLimit(downstream, agent_ids=set(ids), max_bytes=limit)


@pytest.mark.asyncio
async def test_a_body_within_the_limit_reaches_the_app_untouched():
    downstream = Downstream()
    status, body, _ = await call(limited(downstream), chunks=LIMIT // CHUNK)
    assert (status, body) == (200, b"downstream") and downstream.body_seen == LIMIT


@pytest.mark.asyncio
async def test_a_body_over_the_limit_is_refused_after_reading_only_a_little_more_than_the_limit():
    downstream = Downstream()
    status, body, pulled = await call(limited(downstream), chunks=10_000)  # 640 MiB if it were all read
    assert status == 413 and "limit" in json.loads(body)["detail"]
    assert pulled * CHUNK <= LIMIT + CHUNK
    assert downstream.body_seen <= LIMIT and downstream.disconnected


@pytest.mark.asyncio
async def test_a_content_length_over_the_limit_is_refused_without_reading_the_body():
    downstream = Downstream()
    status, _, pulled = await call(
        limited(downstream), chunks=10_000, headers=[(b"content-length", str(LIMIT + 1).encode())]
    )
    assert status == 413 and pulled == 0 and downstream.called == 0


@pytest.mark.asyncio
async def test_a_content_length_that_understates_the_body_does_not_bypass_the_limit():
    downstream = Downstream()
    status, _, pulled = await call(limited(downstream), chunks=10_000, headers=[(b"content-length", b"10")])
    assert status == 413 and pulled * CHUNK <= LIMIT + CHUNK


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,method",
    [
        ("/agents/someone-else/runs", "POST"),
        ("/agents/coder/runs/abc/cancel", "POST"),
        ("/agents/coder/runs", "GET"),
        ("/teams/coder/runs", "POST"),
    ],
)
async def test_other_agents_routes_and_methods_are_not_limited(path, method):
    downstream = Downstream()
    status, _, _ = await call(limited(downstream), chunks=3 * LIMIT // CHUNK, path=path, method=method)
    assert status == 200 and downstream.body_seen == 3 * LIMIT


@pytest.mark.asyncio
async def test_a_trailing_slash_or_prefix_is_still_the_run_route():
    for path in ("/agents/coder/runs/", "/os/agents/coder/runs"):
        status, _, _ = await call(limited(Downstream()), chunks=10_000, path=path)
        assert status == 413


@pytest.mark.asyncio
async def test_an_app_that_fails_while_the_body_is_cut_off_still_answers_413():
    class Failing(Downstream):
        async def __call__(self, scope, receive, send):
            await super().__call__(scope, receive, send)
            raise RuntimeError("the form parser gave up on a truncated body")

    status, _, _ = await call(limited(Failing(status=400)), chunks=10_000)
    assert status == 413


@pytest.mark.asyncio
async def test_a_failure_unrelated_to_the_limit_is_not_hidden():
    class Failing(Downstream):
        async def __call__(self, scope, receive, send):
            raise RuntimeError("unrelated")

    with pytest.raises(RuntimeError, match="unrelated"):
        await call(limited(Failing()), chunks=1)


def test_the_default_limit_is_above_the_largest_canonical_request_and_below_a_padded_one():
    from agno.media import File
    from agno.sandbox.media import MAX_MEDIA_BYTES, encode_media

    # 512 KiB of bytes whose base64 is all '+', the character url-encoding triples, and a message of '!' (also tripled).
    chunks = [b"\xfb\xef\xbe" * 10922] * 16
    assert sum(len(c) for c in chunks) <= MAX_MEDIA_BYTES
    items = [{"content": base64.b64encode(c).decode(), "filename": f"f{i}.bin"} for i, c in enumerate(chunks)]
    wire = encode_media(files=[File(content=c, filename=f"f{i}.bin") for i, c in enumerate(chunks)])
    runtime = len(json.dumps({"input": "", "kwargs": {"media": wire}, "stream": True}).encode())
    message = "!" * (MiB - runtime - 128)  # fills the 1 MiB runtime request
    canonical = len(urlencode({"message": message, "input_files": json.dumps(items)}).encode())
    assert 3 * MiB - 128 * 1024 < canonical < MAX_SANDBOX_REQUEST_BODY
    # Whitespace inside the JSON array leaves the same sixteen attachments, in a body the limit refuses.
    from agno.os.routers.agents.sandbox import request_attachments

    padded = json.dumps(items).replace("[", "[" + " " * MAX_SANDBOX_REQUEST_BODY, 1)
    assert len(request_attachments({"input_files": padded})["files"]) == 16
    assert len(urlencode({"message": "m", "input_files": padded}).encode()) > MAX_SANDBOX_REQUEST_BODY


# --- what the mechanism counts, and what it does around the boundary ---------------------------------------------------


async def call_with(app, chunks, *, headers=None, path="/agents/coder/runs", disconnect_after=None):
    """Run the app with explicit body chunks; return every message sent and how many chunks were pulled."""
    pulled = 0
    sent = []

    async def receive():
        nonlocal pulled
        if pulled >= len(chunks) or pulled == disconnect_after:
            return {"type": "http.disconnect"}
        pulled += 1
        return {"type": "http.request", "body": chunks[pulled - 1], "more_body": pulled < len(chunks)}

    async def send(message):
        sent.append(message)

    await app({"type": "http", "method": "POST", "path": path, "headers": headers or []}, receive, send)
    return sent, pulled


def starts(sent):
    return [m["status"] for m in sent if m["type"] == "http.response.start"]


@pytest.mark.asyncio
@pytest.mark.parametrize("split", [[1] * 64 + [LIMIT - 64]])
async def test_a_body_of_exactly_the_limit_is_delivered_however_it_is_split(split):
    downstream = Downstream()
    sent, _ = await call_with(limited(downstream), [b"x" * size for size in split])
    assert starts(sent) == [200] and downstream.body_seen == LIMIT


@pytest.mark.asyncio
@pytest.mark.parametrize("split", [[LIMIT + 1], [LIMIT, 1], [LIMIT // 2, LIMIT // 2, 1]])
async def test_one_byte_over_the_limit_is_refused_however_it_is_split(split):
    downstream = Downstream()
    sent, _ = await call_with(limited(downstream), [b"x" * size for size in split])
    assert starts(sent) == [413]
    assert downstream.body_seen <= LIMIT


@pytest.mark.asyncio
async def test_one_chunk_far_beyond_the_limit_never_reaches_the_app_but_was_received_whole():
    # The transport hands over whole chunks, so what was received can exceed the limit by up to one chunk. The app
    # is never given a byte past the limit, and nothing more is pulled once it is passed.
    downstream = Downstream()
    sent, pulled = await call_with(limited(downstream), [b"x" * (4 * LIMIT), b"x" * LIMIT])
    assert starts(sent) == [413] and pulled == 1 and downstream.body_seen == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [str(LIMIT).encode(), b"nonsense", b"-5"])
async def test_a_declared_length_within_the_limit_never_admits_more_than_the_limit(declared):
    downstream = Downstream()
    sent, _ = await call_with(limited(downstream), [b"x" * CHUNK] * 40, headers=[(b"content-length", declared)])
    assert starts(sent) == [413]
    assert downstream.body_seen <= LIMIT


@pytest.mark.asyncio
async def test_a_client_that_disconnects_mid_upload_gets_no_response_from_the_limit_and_no_error():
    downstream = Downstream()
    sent, pulled = await call_with(limited(downstream), [b"x" * CHUNK] * 4, disconnect_after=2)
    assert 413 not in starts(sent) and downstream.disconnected and pulled == 2


@pytest.mark.asyncio
async def test_a_response_the_app_already_started_is_not_answered_twice():
    class Early:
        """Starts its response before it has read the whole body, as a streaming endpoint could."""

        async def __call__(self, scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            while (await receive())["type"] == "http.request":
                pass
            await send({"type": "http.response.body", "body": b"late"})

    sent, _ = await call_with(limited(Early()), [b"x" * CHUNK] * 40)
    assert len(starts(sent)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_type", ["websocket", "lifespan"])
async def test_other_scope_types_pass_straight_through(scope_type):
    seen = []

    async def downstream(scope, receive, send):
        seen.append(scope["type"])

    await limited(downstream)({"type": scope_type, "path": "/agents/coder/runs", "method": "POST"}, None, None)
    assert seen == [scope_type]


# --- with the framework's own form parser, which spools uploaded files to disk -------------------------------------------


def _form_app():
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    async def app(scope, receive, send):
        request = Request(scope, receive)
        try:
            async with request.form() as form:
                response = JSONResponse({"sizes": [v.size for v in form.values() if hasattr(v, "size")]})
        except Exception as error:  # the parser giving up on a truncated body
            response = JSONResponse({"error": type(error).__name__}, status_code=400)
        await response(scope, receive, send)

    return app


async def _post_file(app, size, *, disconnect_after=None):
    head = b'--B\r\nContent-Disposition: form-data; name="message"\r\n\r\nhi\r\n'
    head += b'--B\r\nContent-Disposition: form-data; name="files"; filename="big.bin"\r\n'
    head += b"Content-Type: application/octet-stream\r\n\r\n"
    tail = b"\r\n--B--\r\n"
    parts = [head] + [b"z" * CHUNK for _ in range(size // CHUNK)] + [tail]
    sent, pulled = await call_with(
        app, parts, headers=[(b"content-type", b"multipart/form-data; boundary=B")], disconnect_after=disconnect_after
    )
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return starts(sent), body, pulled


@pytest.fixture
def uploads(monkeypatch):
    """The framework's upload objects created during a test. Spill files are anonymous, so they are tracked here."""
    from starlette.datastructures import UploadFile

    created = []
    original = UploadFile.__init__

    def tracking(self, *args, **kwargs):
        original(self, *args, **kwargs)
        created.append(weakref.ref(self))

    monkeypatch.setattr(UploadFile, "__init__", tracking)
    return created


def _left_open(created):
    gc.collect()
    return [ref() for ref in created if ref() is not None and not ref().file.closed]


@pytest.mark.asyncio
async def test_an_upload_cut_off_by_the_limit_leaves_no_open_spooled_file_behind(uploads):
    status, _, pulled = await _post_file(limited(_form_app(), limit=2 * MiB), 6 * MiB)
    assert status == [413] and pulled * CHUNK <= 2 * MiB + 2 * CHUNK
    assert uploads and _left_open(uploads) == []


@pytest.mark.asyncio
async def test_an_upload_the_client_abandons_leaves_no_open_spooled_file_behind(uploads):
    status, _, _ = await _post_file(limited(_form_app(), limit=8 * MiB), 4 * MiB, disconnect_after=40)
    assert 413 not in status
    assert uploads and _left_open(uploads) == []


# --- in a real AgentOS app ----------------------------------------------------------------------------------------------


def _sandboxed_app(tmp_path, monkeypatch, **os_kwargs):
    from agno.db.postgres import PostgresDb
    from agno.os import AgentOS
    from agno.sandbox.checkpoint import FileCheckpointStore
    from agno.sandbox.docker import DockerSandbox
    from agno.sandbox.fixture import FixtureAgent

    monkeypatch.setenv("OS_SECURITY_KEY", "a-key-for-the-body-limit-tests")
    db = PostgresDb(db_url="postgresql+psycopg://nobody:nothing@127.0.0.1:1/none")  # never connected to here
    provider = DockerSandbox(
        "unused:image",
        namespace="limit-test",
        env={"AGNO_SANDBOX_TEST_RUNTIME": "1"},
        checkpoints=FileCheckpointStore(tmp_path / "objects"),
    )
    agents = [FixtureAgent(id="coder", sandbox=provider)]
    return AgentOS(id="limit-test", agents=agents, db=db, telemetry=False, **os_kwargs).get_app()


def test_an_unauthenticated_oversize_request_is_asked_to_authenticate_not_told_the_agent_is_sandboxed(
    tmp_path, monkeypatch
):
    from starlette.testclient import TestClient

    client = TestClient(_sandboxed_app(tmp_path, monkeypatch), raise_server_exceptions=False)
    big = {"files": ("a.bin", b"x" * (MAX_SANDBOX_REQUEST_BODY + 1024))}
    sandboxed = client.post("/agents/coder/runs", data={"message": "m"}, files=big)
    unknown = client.post("/agents/nobody/runs", data={"message": "m"}, files=big)
    assert sandboxed.status_code == unknown.status_code == 401


def test_an_authenticated_oversize_request_is_refused_with_413(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    client = TestClient(_sandboxed_app(tmp_path, monkeypatch), raise_server_exceptions=False)
    big = {"files": ("a.bin", b"x" * (MAX_SANDBOX_REQUEST_BODY + 1024))}
    response = client.post(
        "/agents/coder/runs",
        data={"message": "m"},
        files=big,
        headers={"Authorization": "Bearer a-key-for-the-body-limit-tests"},
    )
    assert response.status_code == 413


# --- only AgentOS's own run endpoint is limited -----------------------------------------------------------------------
# The limit is for the generated sandbox submission route. A route the application supplied on the same URL keeps its
# own semantics, whichever of the two the route table lets handle the request.

AUTH = {"Authorization": "Bearer a-key-for-the-body-limit-tests"}


def _custom_run_app(path="/agents/coder/runs"):
    from fastapi import FastAPI, Request

    base = FastAPI()

    @base.post(path)
    async def custom_run(request: Request):
        return {"custom_route_read_bytes": len(await request.body())}

    return base


def _post_oversize(app):
    from starlette.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)
    return client.post("/agents/coder/runs", content=b"x" * (MAX_SANDBOX_REQUEST_BODY + 1024), headers=AUTH)


@pytest.mark.parametrize("on_route_conflict", ["preserve_base_app", "preserve_agentos"])
def test_a_custom_route_on_the_same_url_is_not_limited(tmp_path, monkeypatch, on_route_conflict):
    # In both modes the table lets the application's route answer the request, so it keeps its own semantics.
    app = _sandboxed_app(tmp_path, monkeypatch, base_app=_custom_run_app(), on_route_conflict=on_route_conflict)
    response = _post_oversize(app)
    assert response.status_code == 200 and response.json() == {
        "custom_route_read_bytes": MAX_SANDBOX_REQUEST_BODY + 1024
    }


def test_a_custom_route_with_another_parameter_name_that_is_registered_first_is_not_limited(tmp_path, monkeypatch):
    # Not detected as a conflict (different pattern text), so both routes exist and the first one handles the request.
    app = _sandboxed_app(tmp_path, monkeypatch, base_app=_custom_run_app("/agents/{name}/runs"))
    assert _post_oversize(app).status_code == 200


def test_a_route_added_after_the_app_is_built_is_shadowed_by_the_limited_generated_route(tmp_path, monkeypatch):
    from fastapi import Request

    app = _sandboxed_app(tmp_path, monkeypatch)

    @app.post("/agents/coder/runs")
    async def late(request: Request):
        return {"late": True}

    assert _post_oversize(app).status_code == 413


def test_the_generated_route_beside_unrelated_custom_routes_is_limited(tmp_path, monkeypatch):
    app = _sandboxed_app(tmp_path, monkeypatch, base_app=_custom_run_app("/something/else"))
    assert _post_oversize(app).status_code == 413
