import asyncio
import json
import os
import threading

import pytest

from agno.sandbox import ExecResult, SandboxError, SandboxHandle, runtime
from agno.sandbox.client import RuntimeExecution, SandboxRuntimeClient


@pytest.fixture
def request_data(monkeypatch):
    monkeypatch.setenv("AGNO_SANDBOX_TEST_RUNTIME", "1")
    return {
        "version": 1,
        "execution_id": "e",
        "run_id": "r",
        "session_id": "s",
        "agent_id": "a",
        "sdk": "fixture",
        "input": "hello",
        "config": {},
        "execution_timeout": 2,
    }


@pytest.fixture
def dispatch(tmp_path, monkeypatch, request_data):
    calls = []
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(runtime, "_process_start", lambda pid: "start")
    monkeypatch.setenv("AGNO_SANDBOX_WORKSPACE", str(tmp_path / "workspace"))
    return tmp_path, calls, request_data


def test_duplicate_start_does_not_repeat_execution(dispatch):
    root, calls, request = dispatch
    first = runtime._start(root, request)
    assert runtime._start(root, request) == first
    assert len(calls) == 1
    with pytest.raises(SandboxError, match="different input"):
        runtime._start(root, {**request, "input": "different"})
    with pytest.raises(SandboxError, match="exactly one"):
        runtime._start(root, {**request, "session_id": "other"})
    assert len(calls) == 1


def test_runtime_writer_lock_is_exclusive(tmp_path):
    with runtime._lock(tmp_path / "lock"):
        with pytest.raises(SandboxError, match="already has a writer"):
            with runtime._lock(tmp_path / "lock"):
                pytest.fail("two writers")


@pytest.mark.parametrize("confirmed", [True, False])
def test_native_decision_is_bound_to_live_execution(dispatch, monkeypatch, confirmed):
    import time

    from agno.agents._hitl import KEY
    from agno.db.sqlite import SqliteDb
    from agno.models.response import ToolExecution
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus
    from agno.run.requirement import RunRequirement
    from agno.session import AgentSession

    root, calls, request = dispatch
    runtime._start(root, request)
    directory = runtime._job(root, "e")
    (root / "native").mkdir(exist_ok=True)
    db = SqliteDb(db_file=str(root / "native" / "history.db"))
    # The runtime's paused run, as its waiting native execution persisted it.
    tool = ToolExecution(tool_call_id="tool", tool_name="Bash", tool_args={"command": "x"}, requires_confirmation=True)
    paused = RunOutput(
        run_id="r",
        session_id="s",
        agent_id="a",
        status=RunStatus.paused,
        requirements=[RunRequirement(tool_execution=tool)],
        metadata={
            KEY: {
                "owner": "owner",
                "pending": ["tool"],
                "requests": {"tool": {"digest": "digest", "native": {}, "expires_at": int(time.time()) + 60}},
                "decisions": {},
            }
        },
    )
    db.upsert_session(AgentSession(session_id="s", agent_id="a", runs=[paused]))
    db.upsert_run(paused, session_id="s", run_index=0)
    runtime._atomic(directory / "status.json", runtime._encode({"phase": "running", "pid": 123, "start": "start"}))
    decision = {**request, "tool_call_id": "tool", "confirmed": confirmed, "digest": "digest", "owner": "owner"}
    for field in ("run_id", "session_id", "agent_id"):
        with pytest.raises(SandboxError, match="identity"):
            runtime._resolve(root, {**decision, field: "other"})
    monkeypatch.setattr(runtime, "_process_start", lambda pid: "start")
    with pytest.raises(SandboxError, match="does not answer"):
        runtime._resolve(root, {**decision, "digest": "other"})
    monkeypatch.setattr(runtime, "_process_start", lambda pid: "different-process")
    with pytest.raises(SandboxError, match="no longer available"):
        runtime._resolve(root, decision)
    assert db.get_run("r").status == RunStatus.paused
    monkeypatch.setattr(runtime, "_process_start", lambda pid: "start")
    assert runtime._resolve(root, decision)["accepted"]
    assert runtime._resolve(root, decision)["accepted"], "A repeated delivery of the same decision is accepted"
    with pytest.raises(SandboxError, match="decided differently"):
        runtime._resolve(root, {**decision, "confirmed": not confirmed})
    stored = db.get_run("r")
    assert stored.status == RunStatus.running
    assert stored.metadata[KEY]["decisions"]["tool"]["confirmed"] is confirmed
    assert len(calls) == 1, "Decision delivery must never spawn a replacement process"
    db.db_engine.dispose()


def test_native_answers_are_bound_to_the_asked_questions(dispatch, monkeypatch):
    import time

    from agno.agents._hitl import KEY
    from agno.db.sqlite import SqliteDb
    from agno.models.response import ToolExecution
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus
    from agno.run.requirement import RunRequirement
    from agno.session import AgentSession
    from agno.tools.function import UserFeedbackOption, UserFeedbackQuestion

    root, calls, request = dispatch
    runtime._start(root, request)
    directory = runtime._job(root, "e")
    (root / "native").mkdir(exist_ok=True)
    db = SqliteDb(db_file=str(root / "native" / "history.db"))
    question = UserFeedbackQuestion(question="Which color?", options=[UserFeedbackOption(label="Blue")])
    tool = ToolExecution(
        tool_call_id="tool",
        tool_name="AskUserQuestion",
        tool_args={},
        requires_user_input=True,
        user_feedback_schema=[question],
    )
    paused = RunOutput(
        run_id="r",
        session_id="s",
        agent_id="a",
        status=RunStatus.paused,
        requirements=[RunRequirement(tool_execution=tool)],
        metadata={
            KEY: {
                "owner": "owner",
                "pending": ["tool"],
                "requests": {"tool": {"digest": "digest", "native": {}, "expires_at": int(time.time()) + 60}},
                "decisions": {},
            }
        },
    )
    db.upsert_session(AgentSession(session_id="s", agent_id="a", runs=[paused]))
    db.upsert_run(paused, session_id="s", run_index=0)
    runtime._atomic(directory / "status.json", runtime._encode({"phase": "running", "pid": 123, "start": "start"}))
    monkeypatch.setattr(runtime, "_process_start", lambda pid: "start")
    decision = {**request, "tool_call_id": "tool", "digest": "digest", "owner": "owner"}
    with pytest.raises(SandboxError, match="does not answer"):
        runtime._resolve(root, {**decision, "confirmed": True})
    with pytest.raises(ValueError, match="lists of selections"):
        runtime._resolve(root, {**decision, "answers": "Blue"})
    with pytest.raises(SandboxError, match="does not answer"):
        runtime._resolve(root, {**decision, "answers": [["Blue"], ["extra"]]})
    assert runtime._resolve(root, {**decision, "answers": [["Blue"]]})["accepted"]
    stored = db.get_run("r")
    assert stored.status == RunStatus.running
    assert stored.metadata[KEY]["decisions"]["tool"]["answers"] == [["Blue"]]
    assert stored.requirements[0].user_feedback_schema[0].selected_options == ["Blue"]
    assert len(calls) == 1
    db.db_engine.dispose()


def test_execution_journal_replays_without_service_completion(dispatch):
    root, calls, request = dispatch
    runtime._start(root, request)
    runtime._worker(runtime._job(root, "e"))
    first = runtime._poll(root, "e", 0)
    assert first["result"]["type"] == "execution_finished"
    assert first["frames"][0]["event"]["content"] == "hello"
    assert all(frame["event"]["event"] != "RunCompleted" for frame in first["frames"])
    second = runtime._poll(root, "e", first["cursor"])
    assert second["frames"] == [] and second["result"] == first["result"]
    runtime._start(root, request)
    assert len(calls) == 1
    assert (root / "workspace/fixture-effects.txt").read_text() == "r\n"


def test_disappeared_worker_is_unknown_not_automatically_reexecuted(dispatch, monkeypatch):
    root, calls, request = dispatch
    runtime._start(root, request)
    directory = runtime._job(root, "e")
    runtime._atomic(directory / "status.json", runtime._encode({"phase": "running", "pid": 123, "start": "old"}))
    monkeypatch.setattr(runtime, "_process_start", lambda pid: "new")
    result = runtime._poll(root, "e", 0)["result"]
    assert result["type"] == "execution_unknown"
    runtime._start(root, request)
    assert len(calls) == 1


def test_partial_event_is_not_exposed(dispatch):
    root, _, request = dispatch
    runtime._start(root, request)
    directory = runtime._job(root, "e")
    (directory / "events.jsonl").write_bytes(b'{"partial":')
    assert runtime._poll(root, "e", 0)["frames"] == []
    assert runtime._poll(root, "e", 0)["cursor"] == 0


def test_runtime_rejects_invalid_config_and_disabled_fixture(request_data, monkeypatch):
    with pytest.raises(ValueError, match="configuration"):
        runtime._validate({**request_data, "config": {"db": "secret"}})
    with pytest.raises(ValueError, match="configuration"):
        runtime._validate({**request_data, "config": {"options_kwargs": {"cwd": "/tmp"}}})
    with pytest.raises(ValueError, match="timeout"):
        runtime._validate({**request_data, "execution_timeout": float("nan")})
    monkeypatch.delenv("AGNO_SANDBOX_TEST_RUNTIME")
    with pytest.raises(ValueError, match="disabled"):
        runtime._validate(request_data)


def test_runtime_timeout_is_execution_error(dispatch):
    root, _, request = dispatch
    request.update(config={"delay": 1}, execution_timeout=0.01)
    runtime._start(root, request)
    runtime._worker(runtime._job(root, "e"))
    result = runtime._poll(root, "e", 0)["result"]
    assert result["type"] == "execution_error" and result["error"] == "TimeoutError"


def test_frame_and_journal_limits(dispatch, monkeypatch):
    root, _, request = dispatch
    runtime._start(root, request)
    directory = runtime._job(root, "e")
    monkeypatch.setattr(runtime, "_MAX_FRAME", 10)
    with pytest.raises(SandboxError, match="frame limit"):
        runtime._append(directory, {"content": "too large"})
    monkeypatch.setattr(runtime, "_MAX_FRAME", 1000)
    monkeypatch.setattr(runtime, "_MAX_JOURNAL", 10)
    with pytest.raises(SandboxError, match="journal"):
        runtime._append(directory, {"content": "too large"})


HANDLE = SandboxHandle("id", "name", "a", "s", 1, "running", "digest")


class Provider:
    def __init__(self):
        self.requests = []
        self.stopped = False
        self.response = {"version": 1, "execution_id": "e", "accepted": True}
        self.release = None
        self.entered = threading.Event()

    async def arpc(self, computer, operation, payload):
        self.requests.append(json.loads(payload))
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        return ExecResult(0, json.dumps(self.response), "")

    async def astop(self, computer):
        self.stopped = True


@pytest.mark.asyncio
async def test_old_runtime_is_refused_before_starting_a_confirming_harness():
    provider = Provider()
    client = SandboxRuntimeClient(provider)
    with pytest.raises(SandboxError, match="Rebuild the sandbox image"):
        await client.astart(
            HANDLE, execution_id="e", run_id="r", sdk="claude", input="work", config={"_native_hitl": True}
        )
    assert len(provider.requests) == 1
    assert "input" not in provider.requests[0], "Old runtime received a start request"


@pytest.mark.asyncio
async def test_client_start_uses_rpc_transport_and_explicit_cancel():
    provider = Provider()
    client = SandboxRuntimeClient(provider)
    execution = await client.astart(HANDLE, execution_id="e", run_id="r", sdk="claude", input="secret prompt")
    assert execution == RuntimeExecution(HANDLE, "e", "r")
    assert provider.requests[0]["input"] == "secret prompt"
    assert provider.requests[0]["session_id"] == "s"
    await client.acancel(execution)
    assert provider.stopped


@pytest.mark.asyncio
async def test_poll_cancellation_drains_rpc_without_cancelling_execution():
    provider = Provider()
    provider.release = asyncio.Event()
    provider.response = {"version": 1, "execution_id": "e", "cursor": 0, "frames": [], "result": None}
    client = SandboxRuntimeClient(provider)
    task = asyncio.create_task(client.apoll(RuntimeExecution(HANDLE, "e", "r")))
    assert await asyncio.to_thread(provider.entered.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    provider.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not provider.stopped


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"version": 2, "execution_id": "e"},
        {"version": 1, "execution_id": "other"},
        {"version": 1, "execution_id": "e", "cursor": -1, "frames": []},
        {"version": 1, "execution_id": "e", "cursor": 1, "frames": [{"type": "event", "event": {"run_id": "other"}}]},
        {
            "version": 1,
            "execution_id": "e",
            "cursor": 1,
            "frames": [{"type": "event", "event": {"event": "RunCompleted"}}],
        },
        {
            "version": 1,
            "execution_id": "e",
            "cursor": 1,
            "frames": [],
            "result": {"type": "execution_finished", "run": {}, "session": {}},
        },
    ],
)
async def test_client_rejects_invalid_identity_and_terminal_frames(response):
    provider = Provider()
    provider.response = response
    with pytest.raises(SandboxError):
        await SandboxRuntimeClient(provider).apoll(RuntimeExecution(HANDLE, "e", "r"))


def test_sync_client_wrappers():
    provider = Provider()
    client = SandboxRuntimeClient(provider)
    execution = client.start(HANDLE, execution_id="e", run_id="r", sdk="claude", input="hello")
    provider.response = {
        "version": 1,
        "execution_id": "e",
        "cursor": 0,
        "frames": [],
        "result": {"type": "execution_error", "error": "fixture"},
    }
    assert client.poll(execution).result["error"] == "fixture"
    assert client.wait_result(execution)["error"] == "fixture"
    assert len(list(client.pages(execution))) == 1
    client.cancel(execution)
    assert provider.stopped


@pytest.mark.asyncio
@pytest.mark.parametrize("retained", [True, False])
async def test_sdk_adapter_terminal_event_is_only_an_execution_result(tmp_path, monkeypatch, retained):
    from agno.run.agent import RunCompletedEvent, RunContentEvent, RunOutput
    from agno.run.base import RunStatus
    from agno.session import AgentSession

    disposed = []
    output = RunOutput(run_id="r", session_id="s", agent_id="a", content="hello", status=RunStatus.completed)

    class Engine:
        def dispose(self):
            disposed.append(True)

    class Db:
        db_engine = Engine()

        def get_run(self, run_id):
            return output if retained else None

    class Agent:
        db = Db()

        async def arun(self, prompt, **kwargs):
            yield RunContentEvent(run_id="r", session_id="s", agent_id="a", content="hello")
            yield RunCompletedEvent(run_id="r", session_id="s", agent_id="a", content="hello")
            yield output

        def get_session(self, *args, **kwargs):
            return AgentSession(session_id="s", agent_id="a", session_data={"native_id": "n"})

    monkeypatch.setenv("HOME", os.environ.get("HOME", ""))
    monkeypatch.setenv("CODEX_HOME", "unused")
    monkeypatch.setattr(runtime, "_agent", lambda *args: Agent())
    directory = tmp_path / "jobs/e"
    directory.mkdir(parents=True)
    if not retained:
        with pytest.raises(SandboxError, match="durably retain"):
            await runtime._execute(directory, {"sdk": "claude", "run_id": "r", "session_id": "s", "input": "hello"})
        assert disposed == [True]
        return
    result = await runtime._execute(directory, {"sdk": "claude", "run_id": "r", "session_id": "s", "input": "hello"})
    assert result["type"] == "execution_finished"
    frames = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    assert len(frames) == 1 and frames[0]["event"]["event"] == "RunContent"
    assert disposed == [True]


def test_completion_racing_poll_cannot_skip_final_events(dispatch, monkeypatch):
    from pathlib import Path

    root, _, request = dispatch
    runtime._start(root, request)
    directory = runtime._job(root, "e")
    path = directory / "events.jsonl"
    path.touch()
    original_open = Path.open
    raced = []

    class RaceStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def __getattr__(self, key):
            return getattr(self.stream, key)

        def read(self, count):
            value = self.stream.read(count)
            if count == 1 and not value and not raced:
                raced.append(True)
                runtime._append(directory, {"event": "RunContent", "content": "last"})
                runtime._atomic(
                    directory / "result.json", runtime._encode({"type": "execution_error", "error": "finished"})
                )
            return value

    def open_with_race(self, *args, **kwargs):
        stream = original_open(self, *args, **kwargs)
        return RaceStream(stream) if self == path and args == ("rb",) else stream

    monkeypatch.setattr(Path, "open", open_with_race)
    first = runtime._poll(root, "e", 0)
    assert first["result"] is None and first["cursor"] == 0
    second = runtime._poll(root, "e", first["cursor"])
    assert second["frames"][0]["event"]["content"] == "last"
    assert second["result"]["error"] == "finished"


# ---------------------------------------------------------------------------
# The runtime as an HTTP server inside the container
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime_server(tmp_path, monkeypatch, request_data):
    """The real server on a loopback port, with the fixture harness and a fake worker start."""
    import threading

    monkeypatch.setattr(runtime, "_process_start", lambda pid: "start")
    calls = []
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    server = runtime._serve(tmp_path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", tmp_path, calls, request_data
    finally:
        server.shutdown()
        server.server_close()


def test_server_health_start_and_poll_match_the_stdin_protocol(runtime_server):
    import httpx

    url, root, calls, request_data = runtime_server
    assert httpx.get(url + "/health").json() == {"version": 1, "ok": True}
    accepted = httpx.post(url + "/start", json=request_data)
    assert accepted.status_code == 200 and accepted.json()["accepted"] is True
    # The same request again attaches; a different one is refused with a conflict.
    assert httpx.post(url + "/start", json=request_data).status_code == 200
    assert len(calls) == 1
    conflict = httpx.post(url + "/start", json={**request_data, "input": "other"})
    assert conflict.status_code == 409 and "different input" in conflict.json()["error"]
    page = httpx.post(url + "/poll", json={"execution_id": "e", "cursor": 0}).json()
    assert page == {"version": 1, "execution_id": "e", "cursor": 0, "frames": [], "result": None}
    assert httpx.post(url + "/poll", json={"execution_id": "e", "cursor": -1}).status_code == 400
    assert httpx.post(url + "/nope", json={}).status_code == 404
    assert httpx.get(url + "/poll").status_code == 404


def test_server_long_poll_returns_as_soon_as_the_journal_grows(runtime_server):
    import threading
    import time

    import httpx

    url, root, calls, request_data = runtime_server
    httpx.post(url + "/start", json=request_data)
    directory = runtime._job(root, "e")

    def append_later():
        time.sleep(0.3)
        runtime._append(directory, {"event": "RunContent", "content": "late"})

    threading.Thread(target=append_later, daemon=True).start()
    started = time.monotonic()
    page = httpx.post(url + "/poll", json={"execution_id": "e", "cursor": 0, "wait": 5}, timeout=10).json()
    elapsed = time.monotonic() - started
    assert [frame["event"]["content"] for frame in page["frames"]] == ["late"]
    assert 0.2 < elapsed < 3, "the poll should return when the event lands, not after the full wait"
    # Nothing new: the wait runs out and an empty page comes back.
    started = time.monotonic()
    idle = httpx.post(url + "/poll", json={"execution_id": "e", "cursor": page["cursor"], "wait": 0.3}, timeout=10)
    assert idle.json()["frames"] == [] and time.monotonic() - started >= 0.25


def test_server_requires_its_token_when_one_is_configured(tmp_path, monkeypatch, request_data):
    import threading

    import httpx

    monkeypatch.setattr(runtime, "_process_start", lambda pid: "start")
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **kw: None)
    server = runtime._serve(tmp_path, 0, "secret-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert httpx.get(url + "/health").status_code == 401
        assert httpx.post(url + "/start", json=request_data).status_code == 401
        assert httpx.get(url + "/health", headers={"Authorization": "Bearer nope"}).status_code == 401
        good = {"Authorization": "Bearer secret-token"}
        assert httpx.get(url + "/health", headers=good).status_code == 200
        assert httpx.post(url + "/start", json=request_data, headers=good).json()["accepted"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_server_rejects_oversized_and_malformed_requests(runtime_server):
    import httpx

    url, *_ = runtime_server
    assert httpx.post(url + "/start", content=b"[]", headers={"Content-Type": "application/json"}).status_code == 400
    assert httpx.post(url + "/start", content=b"{", headers={"Content-Type": "application/json"}).status_code == 400
    assert httpx.post(url + "/start", content=b"", headers={"Content-Type": "application/json"}).status_code == 413


def test_stdin_poll_honours_wait(dispatch, monkeypatch, capsys):
    import sys
    import time

    root, calls, request_data = dispatch
    runtime._start(root, request_data)
    monkeypatch.setenv("AGNO_SANDBOX_RUNTIME_DIR", str(root))
    from io import BytesIO
    from types import SimpleNamespace

    monkeypatch.setattr(sys, "argv", ["runtime", "poll"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=BytesIO(b'{"execution_id":"e","cursor":0,"wait":0.3}')))
    started = time.monotonic()
    runtime.main()
    assert time.monotonic() - started >= 0.25
    assert json.loads(capsys.readouterr().out)["frames"] == []


@pytest.mark.asyncio
async def test_client_long_poll_does_not_sleep_between_pages():
    """With wait, the container holds the request; the client must not add its own delay."""
    provider = Provider()
    client = SandboxRuntimeClient(provider)
    execution = await client.astart(HANDLE, execution_id="e", run_id="r", sdk="claude", input="hello")
    provider.response = {"version": 1, "execution_id": "e", "cursor": 0, "frames": [], "result": None}
    pages = client.apages(execution, timeout=5, poll_interval=5, wait=0.2)
    assert (await pages.__anext__()).events == []
    provider.response = {
        "version": 1,
        "execution_id": "e",
        "cursor": 0,
        "frames": [],
        "result": {"type": "execution_error", "error": "done"},
    }
    assert (await pages.__anext__()).result["error"] == "done"
    assert [request.get("wait") for request in provider.requests[1:]] == [0.2, 0.2]


# ---------------------------------------------------------------------------
# The control token stays with the server; the supervisor keeps the server a child
# ---------------------------------------------------------------------------


def test_worker_is_spawned_without_the_control_token(dispatch, monkeypatch):
    root, calls, request_data = dispatch
    monkeypatch.setenv("AGNO_SANDBOX_RUNTIME_TOKEN", "secret")
    monkeypatch.setenv("AGNO_SANDBOX_OTHER", "kept")
    runtime._start(root, request_data)
    [(args, kwargs)] = calls
    assert args[0][-3:-1] == ["agno.sandbox.runtime", "worker"]
    assert "AGNO_SANDBOX_RUNTIME_TOKEN" not in kwargs["env"]
    assert kwargs["env"]["AGNO_SANDBOX_OTHER"] == "kept", "only the token is withheld"


def test_server_takes_the_token_out_of_its_own_environment(monkeypatch, capsys):
    monkeypatch.setenv("AGNO_SANDBOX_RUNTIME_TOKEN", "secret")
    assert runtime._take_token() == "secret"
    assert "AGNO_SANDBOX_RUNTIME_TOKEN" not in __import__("os").environ
    assert runtime._take_token() is None
    assert "no token" in capsys.readouterr().err


def test_supervisor_restarts_a_crashed_server_and_stops_on_sigterm(monkeypatch):
    import signal
    import threading

    spawned = []

    class Child:
        def __init__(self, code):
            self.code, self._done, self.terminated = code, threading.Event(), False

        def poll(self):
            return self.code if self._done.is_set() else None

        def wait(self):
            self._done.wait()
            return self.code

        def terminate(self):
            self.terminated = True
            self._done.set()

    plan = [Child(1), Child(0)]  # the first server crashes at once; the second runs until stopped

    def popen(args, **kwargs):
        assert args[-3:] == ["serve", "--port", "8765"]
        child = plan[len(spawned)]
        spawned.append(child)
        if child.code == 1:
            child._done.set()
        return child

    handlers = {}
    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    monkeypatch.setattr(signal, "signal", lambda s, h: handlers.__setitem__(s, h))
    sleeps = []
    monkeypatch.setattr(runtime.time, "sleep", lambda s: sleeps.append(s))

    def stop_soon():
        while len(spawned) < 2:
            pass
        handlers[signal.SIGTERM](signal.SIGTERM, None)

    threading.Thread(target=stop_soon, daemon=True).start()
    runtime._supervise(8765)
    assert len(spawned) == 2, "the crashed server was restarted once, then the stop signal ended the loop"
    assert sleeps == [0.4], "a crash backs off before the restart"
    assert spawned[1].terminated, "SIGTERM terminates the running server child"


def test_server_reads_the_token_from_stdin_when_the_supervisor_hands_it_over(monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("secret\n"))
    assert runtime._take_token(from_stdin=True) == "secret"
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert runtime._take_token(from_stdin=True) is None


def test_supervisor_passes_the_token_on_stdin_and_not_in_the_environment(monkeypatch):
    import signal

    monkeypatch.setenv("AGNO_SANDBOX_RUNTIME_TOKEN", "secret")
    spawned = []

    class Stdin:
        def __init__(self):
            self.data = b""

        def write(self, data):
            self.data += data

        def close(self):
            pass

    class Child:
        def __init__(self):
            self.stdin = Stdin()

        def poll(self):
            return 0

        def wait(self):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            return 0

        def terminate(self):
            pass

    def popen(args, **kwargs):
        child = Child()
        spawned.append((args, kwargs, child))
        return child

    handlers = {}
    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    monkeypatch.setattr(signal, "signal", lambda s, h: handlers.__setitem__(s, h))
    runtime._supervise(8765)
    [(args, kwargs, child)] = spawned
    assert args[-4:] == ["serve", "--port", "8765", "--token-stdin"]
    assert "AGNO_SANDBOX_RUNTIME_TOKEN" not in kwargs["env"], "the server is spawned without the token in its env"
    assert child.stdin.data == b"secret\n", "the token travels on the server's stdin"
    assert "AGNO_SANDBOX_RUNTIME_TOKEN" not in __import__("os").environ, "the supervisor drops its own copy"


@pytest.mark.asyncio
async def test_runtime_validates_real_sqlite_result_before_checkpoint(tmp_path, monkeypatch):
    from dataclasses import dataclass

    from agno.agents.base import BaseExternalAgent
    from agno.db.sqlite import SqliteDb
    from agno.run.agent import RunContentEvent

    @dataclass
    class Echo(BaseExternalAgent):
        async def _arun_adapter_stream(self, input, **kwargs):
            yield RunContentEvent(content="durable", run_id=kwargs["run_id"])

    def make_agent(request, native):
        return Echo(id="a", db=SqliteDb(db_file=str(native / "history.db")), strict_persistence=True)

    monkeypatch.setenv("HOME", os.environ.get("HOME", ""))
    monkeypatch.setenv("CODEX_HOME", "unused")
    monkeypatch.setattr(runtime, "_agent", make_agent)
    directory = tmp_path / "jobs/e"
    directory.mkdir(parents=True)
    output = await runtime._execute(directory, {"sdk": "claude", "run_id": "r", "session_id": "s", "input": "hello"})
    assert output["run"]["content"] == "durable"
    assert (tmp_path / "native/history.db").exists()


# ---------------------------------------------------------------------------
# The caller's expectation of native state is checked before the model runs
# ---------------------------------------------------------------------------


def _expecting_agent(native_id, calls):
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus
    from agno.session import AgentSession

    output = RunOutput(run_id="r", session_id="s", agent_id="a", content="hello", status=RunStatus.completed)

    class Engine:
        def dispose(self):
            pass

    class Db:
        db_engine = Engine()

        def get_run(self, run_id):
            return output

    class Agent:
        db = Db()

        async def arun(self, prompt, **kwargs):
            calls.append("model")
            yield output

        def get_session(self, *args, **kwargs):
            # A first turn has no session row until the model has run and the adapter stored one.
            if native_id is None:
                return AgentSession(session_id="s", agent_id="a", session_data={}) if "model" in calls else None
            return AgentSession(session_id="s", agent_id="a", session_data={"claude_sdk_session_id": native_id})

    return Agent()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored, expected, outcome",
    [
        ("native-1", "native-1", "runs"),
        (None, None, "runs"),
        ("native-1", None, "runs"),
        (None, "native-1", "refused"),
        ("native-2", "native-1", "refused"),
    ],
)
async def test_native_session_id_is_checked_before_the_model_runs(tmp_path, monkeypatch, stored, expected, outcome):
    calls = []
    monkeypatch.setattr(runtime, "_agent", lambda *args: _expecting_agent(stored, calls))
    monkeypatch.setenv("HOME", str(tmp_path))
    directory = tmp_path / "jobs/e"
    directory.mkdir(parents=True)
    request = {"sdk": "claude", "run_id": "r", "session_id": "s", "input": "hello", "native_session_id": expected}
    if outcome == "runs":
        result = await runtime._execute(directory, request)
        assert result["type"] == "execution_finished" and calls == ["model"]
    else:
        with pytest.raises(runtime.NativeStateMissing, match="does not match the session"):
            await runtime._execute(directory, request)
        assert calls == [], "the model is never invoked on mismatched state"


def test_worker_reports_missing_native_state_with_a_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "_process_start", lambda pid: "start")
    monkeypatch.setattr(runtime, "_agent", lambda *args: _expecting_agent(None, []))
    monkeypatch.setenv("AGNO_SANDBOX_TEST_RUNTIME", "1")
    directory = tmp_path / "jobs" / "e"
    directory.mkdir(parents=True)
    request = {
        "version": 1,
        "execution_id": "e",
        "run_id": "r",
        "session_id": "s",
        "agent_id": "a",
        "sdk": "claude",
        "input": "x",
        "native_session_id": "native-1",
    }
    (directory / "request.json").write_bytes(runtime._encode(request))
    runtime._worker(directory)
    result = json.loads((directory / "result.json").read_bytes())
    assert result["type"] == "execution_error" and result["reason"] == "native_state_missing"
    assert "expected the native conversation native-1, found none" in result["error"]


def test_native_session_id_is_validated_and_optional(request_data):
    runtime._validate({**request_data, "native_session_id": None})
    runtime._validate({**request_data, "native_session_id": "abc"})
    for bad in ("", 5, "x" * 257):
        with pytest.raises(ValueError, match="native_session_id"):
            runtime._validate({**request_data, "native_session_id": bad})


def test_codex_home_must_be_a_directory(tmp_path):
    asyncio.run(runtime._prepare_codex(tmp_path))
    assert (tmp_path / "codex").is_dir()
    other = tmp_path / "other"
    other.mkdir()
    (other / "codex").write_text("notes the agent saved")
    with pytest.raises(SandboxError, match="must be a directory"):
        asyncio.run(runtime._prepare_codex(other))


def test_codex_login_never_reports_the_key():
    calls = []

    class Agent:
        async def alogin_api_key(self, key):
            calls.append(key)

    asyncio.run(runtime._login_codex(Agent(), "sk-secret"))
    asyncio.run(runtime._login_codex(Agent(), "sk-secret"))
    assert calls == ["sk-secret", "sk-secret"]

    class Failing:
        async def alogin_api_key(self, key):
            raise RuntimeError("login rejected for key " + key)

    with pytest.raises(SandboxError) as raised:
        asyncio.run(runtime._login_codex(Failing(), "sk-secret"))
    assert "sk-secret" not in str(raised.value) and "[redacted]" in str(raised.value)


def test_codex_logs_in_only_when_no_stored_login_matches_the_key(tmp_path):
    home = tmp_path / "codex"
    home.mkdir()
    auth = home / "auth.json"
    # A restored computer has no auth.json, since checkpoints exclude it.
    assert runtime._codex_login_needed(tmp_path, "sk-new")
    auth.write_text("not json")
    assert runtime._codex_login_needed(tmp_path, "sk-new")
    auth.write_text(json.dumps({"OPENAI_API_KEY": "sk-old"}))
    assert runtime._codex_login_needed(tmp_path, "sk-new")
    auth.write_text(json.dumps({"OPENAI_API_KEY": "sk-new"}))
    assert not runtime._codex_login_needed(tmp_path, "sk-new")
    # A ChatGPT login the user set up is kept.
    auth.write_text(json.dumps({"OPENAI_API_KEY": None, "tokens": {"id_token": "x"}}))
    assert not runtime._codex_login_needed(tmp_path, "sk-new")


# --- attachments -------------------------------------------------------------------------------


def _wire(*files, images=()):
    from agno.media import File, Image
    from agno.sandbox.media import encode_media

    return encode_media(
        images=[Image(content=content, format="png") for content in images],
        files=[File(content=content, filename=name) for name, content in files],
    )


def test_protocol_validates_attachments_and_counts_them_in_the_request_limit(request_data):
    from agno.sandbox.media import MAX_MEDIA_BYTES
    from agno.sandbox.protocol import validate_request

    validate_request({**request_data, "media": _wire(("a.txt", b"abc"))})
    with pytest.raises(ValueError, match="canonical|base64|fields|kind|filename"):
        validate_request({**request_data, "media": [{"kind": "file", "name": "../a", "content": "YQ=="}]})
    with pytest.raises(ValueError, match="list"):
        validate_request({**request_data, "media": {"kind": "file"}})
    full = _wire(("a.bin", b"a" * MAX_MEDIA_BYTES))
    validate_request({**request_data, "media": full})
    with pytest.raises(ValueError, match="exceeds its limit"):
        validate_request({**request_data, "media": full, "input": "x" * 400_000})


def test_runtime_start_rejects_a_forged_attachment_before_dispatch(dispatch):
    root, calls, request = dispatch
    with pytest.raises(ValueError):
        runtime._start(root, {**request, "media": [{"kind": "file", "name": "../escape", "content": "YQ=="}]})
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("with_media", [True, False])
async def test_client_sends_attachments_only_when_given(with_media):
    provider = Provider()
    client = SandboxRuntimeClient(provider)
    media = _wire(("a.txt", b"abc")) if with_media else None
    await client.astart(HANDLE, execution_id="e", run_id="r", sdk="claude", input="hi", media=media)
    assert ("media" in provider.requests[0]) is with_media
    if with_media:
        assert provider.requests[0]["media"] == media


def test_sync_client_forwards_attachments():
    provider = Provider()
    media = _wire(("a.txt", b"abc"))
    SandboxRuntimeClient(provider).start(HANDLE, execution_id="e", run_id="r", sdk="claude", input="hi", media=media)
    assert provider.requests[0]["media"] == media


def test_fixture_runtime_stages_attachments_in_the_workspace_per_run(dispatch, tmp_path):
    root, _, request = dispatch
    workspace = tmp_path / "workspace"
    first = {**request, "media": _wire(("same.txt", b"one"), ("same.txt", b"two"))}
    runtime._start(root, first)
    runtime._worker(runtime._job(root, "e"))
    assert runtime._poll(root, "e", 0)["result"]["type"] == "execution_finished"
    folder = workspace / ".agno/uploads/r"
    assert sorted(path.name for path in folder.iterdir()) == ["same-2.txt", "same.txt"]
    assert (folder / "same.txt").read_bytes() == b"one" and (folder / "same-2.txt").read_bytes() == b"two"
    second = {**request, "execution_id": "e2", "run_id": "r2", "media": _wire(("same.txt", b"three"))}
    runtime._start(root, second)
    runtime._worker(runtime._job(root, "e2"))
    assert (workspace / ".agno/uploads/r2/same.txt").read_bytes() == b"three"
    assert (folder / "same.txt").read_bytes() == b"one"


def test_text_only_fixture_turn_leaves_no_upload_folder(dispatch, tmp_path):
    root, _, request = dispatch
    runtime._start(root, request)
    runtime._worker(runtime._job(root, "e"))
    assert not (tmp_path / "workspace/.agno").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("sdk", ["claude", "codex"])
@pytest.mark.parametrize("with_media", [True, False])
async def test_sdk_adapter_receives_decoded_attachments_only_when_given(tmp_path, monkeypatch, sdk, with_media):
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus
    from agno.session import AgentSession

    received = {}
    output = RunOutput(run_id="r", session_id="s", agent_id="a", content="ok", status=RunStatus.completed)

    class Engine:
        def dispose(self):
            pass

    class Db:
        db_engine = Engine()

        def get_run(self, run_id):
            return output

    class Agent:
        db = Db()

        async def arun(self, prompt, **kwargs):
            received.update(kwargs)
            yield output

        def get_session(self, *args, **kwargs):
            return AgentSession(session_id="s", agent_id="a", session_data={})

    monkeypatch.setenv("CODEX_HOME", "unused")
    # A key in the environment would make the runtime log Codex in first; that path has its own test.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(runtime, "_agent", lambda *args: Agent())
    directory = tmp_path / "jobs/e"
    directory.mkdir(parents=True)
    request = {"sdk": sdk, "run_id": "r", "session_id": "s", "input": "hello"}
    if with_media:
        request["media"] = _wire(("a.txt", b"abc"), images=[b"png"])
    await runtime._execute(directory, request)
    assert ("files" in received) is with_media and ("images" in received) is with_media
    if with_media:
        assert received["files"][0].content == b"abc" and received["files"][0].filename == "a.txt"
        assert received["images"][0].content == b"png"


@pytest.mark.parametrize("sdk", ["claude", "codex"])
def test_each_real_adapter_accepts_decoded_images_and_files_and_rejects_the_rest(sdk):
    from agno.agents.claude import ClaudeAgent
    from agno.agents.codex import CodexAgent
    from agno.exceptions import UnsupportedMediaError
    from agno.media import Audio, File, Image
    from agno.sandbox.media import decode_media, encode_media

    agent = (ClaudeAgent if sdk == "claude" else CodexAgent)()
    wire = encode_media(images=[Image(content=b"png", format="png")], files=[File(content=b"abc", filename="a.txt")])
    accepted = agent._media_kwargs(**decode_media(wire))
    assert [item.content for item in accepted["media"]["images"]] == [b"png"]
    assert [item.content for item in accepted["media"]["files"]] == [b"abc"]
    with pytest.raises(UnsupportedMediaError):
        agent._media_kwargs(audio=[Audio(content=b"audio")])


def test_failed_staging_is_an_execution_error_and_no_turn_effects_are_recorded(dispatch, tmp_path):
    root, _, request = dispatch
    workspace = tmp_path / "workspace"
    (workspace / ".agno").mkdir(parents=True)
    (workspace / ".agno/uploads").write_text("a file where the upload folder belongs")
    runtime._start(root, {**request, "media": _wire(("a.txt", b"abc"))})
    runtime._worker(runtime._job(root, "e"))
    assert runtime._poll(root, "e", 0)["result"]["type"] == "execution_error"
    assert not (workspace / "fixture-effects.txt").exists()


def test_text_only_fixture_turn_never_touches_attachment_staging(dispatch, tmp_path):
    root, _, request = dispatch
    runtime._start(root, {**request, "run_id": "a:b"})
    runtime._worker(runtime._job(root, "e"))
    assert runtime._poll(root, "e", 0)["result"]["type"] == "execution_finished"
    assert (tmp_path / "workspace/fixture-effects.txt").read_text() == "a:b\n"
