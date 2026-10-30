"""E2B sandbox contracts against a fake E2B cloud and the real command runner."""

import asyncio
import json
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("e2b")

import e2b
from e2b import CommandExitException, SandboxNotFoundException

from agno.sandbox._exec import _execute
from agno.sandbox.base import SandboxError
from agno.sandbox.checkpoint import CheckpointArchive, FileCheckpointStore
from agno.sandbox.e2b import E2BCheckpointTransfer, E2BSandbox
from agno.sandbox.e2b import _archive
from agno.sandbox.e2b import sandbox as e2b_sandbox
from agno.sandbox.e2b.sandbox import _HARDEN as _HARDEN_COMMAND

_RUNNER = re.compile(r"^python -I -m agno\.sandbox\._exec < (\S+); ")
_JOB = re.compile(r"^python -I -m agno\.sandbox\.e2b\._archive (capture|restore) (\S+) '(.*)'$")


class Files:
    def __init__(self, computer):
        self.computer = computer

    async def write(self, path, data, user=None, request_timeout=None):
        await asyncio.sleep(0)
        self.computer.files[path] = data if isinstance(data, bytes) else data.read()
        self.computer.writes.append((path, user))

    async def read(self, path, format="text", user=None, request_timeout=None):
        data = self.computer.files[path]

        async def stream():
            for offset in range(0, len(data), 4):
                yield data[offset : offset + 4]

        return stream()

    async def remove(self, path, user=None):
        self.computer.files.pop(path, None)


class Commands:
    def __init__(self, cloud, computer):
        self.cloud, self.computer = cloud, computer

    async def run(self, command, **kwargs):
        await asyncio.sleep(0)
        self.computer.commands.append((command, kwargs))
        if self.cloud.command_error is not None:
            raise self.cloud.command_error
        if kwargs.get("background"):
            return SimpleNamespace(pid=1)
        if command.startswith("find / -xdev -perm -4000"):
            if self.cloud.harden_fails:
                raise CommandExitException(stderr="chmod: read-only", stdout="", exit_code=1, error=None)
            return SimpleNamespace(exit_code=0, stdout="", stderr="")
        runner = _RUNNER.match(command)
        if runner:
            request = json.loads(self.computer.files.pop(runner.group(1)))
            stdout = self.cloud.runner_stdout or json.dumps(_execute(request))
            return SimpleNamespace(exit_code=0, stdout=stdout, stderr="")
        job = _JOB.match(command)
        if job:
            return self.cloud.job(self.computer, job.group(1), job.group(2), json.loads(job.group(3)))
        raise AssertionError("Unexpected command " + command)


class Cloud:
    """Answers like the E2B control plane and the envd of each computer."""

    def __init__(self):
        self.computers = {}
        self.created = 0
        self.calls = []
        self.lose_create_reply = False
        self.fail_create = False
        self.command_error = None
        self.runner_stdout = None
        self.job_reply = None
        self.harden_fails = False
        self.limit = None
        # Listings omit a new computer for this many listings after its create.
        self.list_lag = 0
        self.connect_options = []
        # Listings fail once any computer exists, as after a create whose follow-up listing times out.
        self.fail_list_after_create = False
        # Computers listings leave out, as an inconsistent listing can.
        self.unlisted = set()
        self.clock = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def add(self, metadata, state="running"):
        self.clock += timedelta(seconds=1)
        self.created += 1
        sandbox_id = "sbx%03d" % self.created
        computer = SimpleNamespace(
            sandbox_id=sandbox_id,
            sandbox_domain="e2b.app",
            metadata=dict(metadata),
            state=state,
            started_at=self.clock,
            files={},
            writes=[],
            commands=[],
        )
        self.computers[sandbox_id] = computer
        return computer

    def job(self, computer, operation, path, job):
        if self.job_reply is not None:
            return SimpleNamespace(exit_code=0, stdout=json.dumps(self.job_reply), stderr="")
        if operation == "capture":
            workspace = Path(self.scratch) / "workspace"
            native = Path(self.scratch) / "native"
            workspace.mkdir(exist_ok=True)
            native.mkdir(exist_ok=True)
            (workspace / "hello.py").write_text("print('hello')\n")
            output = Path(self.scratch) / "out.tar"
            output.unlink(missing_ok=True)
            CheckpointArchive().capture(
                {"workspace": workspace, "native": native}, output, state=job["state"], exclude=job["exclude"]
            )
            computer.files[path] = output.read_bytes()
            return SimpleNamespace(exit_code=0, stdout=json.dumps({"size": output.stat().st_size}), stderr="")
        source = Path(self.scratch) / "restore.tar"
        source.write_bytes(computer.files.pop(path))
        state = CheckpointArchive().validate(source)
        return SimpleNamespace(exit_code=0, stdout=json.dumps({"state": state}), stderr="")

    # The AsyncSandbox class methods the provider calls.
    async def get_info(self, sandbox_id, **options):
        self.calls.append(("get_info", sandbox_id))
        await asyncio.sleep(0)
        if sandbox_id not in self.computers:
            raise SandboxNotFoundException(sandbox_id)
        return self.computers[sandbox_id]

    def list(self, query=None, **options):
        self.calls.append(("list", dict(query.metadata)))
        if self.fail_list_after_create and self.computers:
            raise e2b.TimeoutException("listing timed out")
        found = []
        for computer in self.computers.values():
            if all(computer.metadata.get(key) == value for key, value in query.metadata.items()):
                if computer.sandbox_id in self.unlisted:
                    continue
                if getattr(computer, "hidden", 0):
                    computer.hidden -= 1
                else:
                    found.append(computer)
        return OnePage(found)

    async def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        await asyncio.sleep(0)
        if self.fail_create:
            raise e2b.SandboxException("quota exceeded")
        if self.limit is not None and len(self.computers) >= self.limit:
            raise e2b.RateLimitException("concurrent sandbox limit reached")
        computer = self.add(kwargs["metadata"])
        computer.create = kwargs
        computer.hidden = self.list_lag
        if self.lose_create_reply:
            raise e2b.TimeoutException("create reply lost")
        return computer

    async def kill(self, sandbox_id, **options):
        self.calls.append(("kill", sandbox_id))
        await asyncio.sleep(0)
        return self.computers.pop(sandbox_id, None) is not None

    async def pause(self, sandbox_id, **options):
        self.calls.append(("pause", sandbox_id))
        self.computers[sandbox_id].state = "paused"
        return True

    async def connect(self, sandbox_id, timeout=None, **options):
        self.calls.append(("connect", sandbox_id))
        self.connect_options.append(options)
        await asyncio.sleep(0)
        computer = self.computers[sandbox_id]
        computer.state = "running"
        return SimpleNamespace(files=Files(computer), commands=Commands(self, computer))

    def count(self, name):
        return sum(1 for call in self.calls if call[0] == name)


class OnePage:
    def __init__(self, found):
        self.found, self.has_next = found, True

    async def next_items(self):
        await asyncio.sleep(0)
        self.has_next = False
        return self.found


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    fake = Cloud()
    fake.scratch = str(tmp_path)

    class FakeAsyncSandbox:
        get_info = staticmethod(fake.get_info)
        list = staticmethod(fake.list)
        create = staticmethod(fake.create)
        kill = staticmethod(fake.kill)
        pause = staticmethod(fake.pause)
        connect = staticmethod(fake.connect)

    monkeypatch.setattr(e2b, "AsyncSandbox", FakeAsyncSandbox)
    monkeypatch.setattr(e2b_sandbox, "_LISTING_SECONDS", 0.0)
    monkeypatch.setattr(e2b_sandbox, "_LISTING_POLL_SECONDS", 0.0)
    return fake


@pytest.fixture
def sandbox():
    return E2BSandbox("agno-sandbox", namespace="test", api_key="e2b_test")


def test_constructor_validates_lifetime_and_timeouts():
    for kwargs in ({"lifetime": 30}, {"lifetime": 90000}, {"runtime_port": 0}, {"request_timeout": 0}):
        with pytest.raises(ValueError):
            E2BSandbox("agno-sandbox", **kwargs)
    with pytest.raises(ValueError, match="shorter than the lifetime"):
        E2BSandbox("agno-sandbox", lifetime=600, execution_timeout=600)
    with pytest.raises(ValueError):
        E2BSandbox("")
    assert E2BSandbox("agno-sandbox", lifetime=600).execution_timeout == 300


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"session_id": ""},
        {"session_id": "s", "agent_id": ""},
        {"session_id": "s", "generation": 0},
        {"session_id": "s", "env": {"A=B": "x"}},
        {"session_id": "s", "env": {"AGNO_SANDBOX_RUNTIME_TOKEN": "x"}},
    ],
)
async def test_invalid_create_arguments_are_rejected_before_e2b(cloud, sandbox, kwargs):
    with pytest.raises(ValueError):
        await sandbox.acreate(**kwargs)
    assert cloud.calls == []


@pytest.mark.asyncio
async def test_create_labels_the_generation_and_finds_it_again(cloud, sandbox):
    handle = await sandbox.acreate("s1", agent_id="coder", env={"A": "1"})
    create = cloud.computers[handle.provider_ref].create
    assert create["template"] == "agno-sandbox" and create["envs"] == {"A": "1"}
    assert create["lifecycle"] == {"on_timeout": "kill", "auto_resume": False}
    assert create["metadata"]["session"] == "s1" and create["metadata"]["namespace"] == "test"
    assert (handle.session_id, handle.agent_id, handle.generation, handle.state) == ("s1", "coder", 1, "running")
    assert handle.runtime_url is None and handle.runtime_token is None
    again = await sandbox.acreate("s1", agent_id="coder", env={"A": "1"})
    assert again == handle and cloud.count("create") == 1
    assert await sandbox.afind("s1", agent_id="coder", env={"A": "1"}) == handle
    assert await sandbox.afind("s1", agent_id="coder", generation=2) is None
    # The coordinator looks a generation up this way before every cold create.
    assert await sandbox.afind("s1", agent_id="coder", env={"A": "1"}, for_create=True) == handle


@pytest.mark.asyncio
async def test_create_strips_setuid_as_root_before_anything_runs(cloud, sandbox):
    handle = await sandbox.acreate("s1")
    command, options = cloud.computers[handle.provider_ref].commands[0]
    assert command.startswith("find / -xdev -perm -4000") and options["user"] == "root"
    cloud.harden_fails = True
    with pytest.raises(SandboxError, match="privilege escalation"):
        await sandbox.acreate("s2")
    assert [c.metadata["session"] for c in cloud.computers.values()] == ["s1"]


@pytest.mark.asyncio
async def test_a_lost_create_reply_is_found_by_metadata(cloud, sandbox):
    cloud.lose_create_reply = True
    handle = await sandbox.acreate("s1")
    assert handle.provider_ref in cloud.computers and cloud.count("create") == 1


@pytest.mark.asyncio
async def test_a_create_waits_for_listings_to_show_the_new_computer(cloud, sandbox, monkeypatch):
    monkeypatch.setattr(e2b_sandbox, "_LISTING_SECONDS", 5.0)
    cloud.list_lag = 3
    handle = await sandbox.acreate("s1")
    assert list(cloud.computers) == [handle.provider_ref] and cloud.count("create") == 1


@pytest.mark.asyncio
async def test_a_computer_that_never_appears_in_listings_is_killed(cloud, sandbox):
    cloud.list_lag = 100
    with pytest.raises(SandboxError, match="did not appear in listings"):
        await sandbox.acreate("s1")
    assert cloud.computers == {} and cloud.count("kill") == 1


@pytest.mark.asyncio
async def test_a_create_decides_from_the_listing_that_showed_its_computer(cloud, sandbox, monkeypatch):
    monkeypatch.setattr(e2b_sandbox, "_LISTING_SECONDS", 5.0)
    listed = []
    original = cloud.list

    def flickering(query=None, **options):
        page = original(query=query, **options)
        listed.append(page)
        # Successive listings can disagree: every listing after the one that first shows it misses it.
        if len(listed) > 2:
            page.found = []
        return page

    monkeypatch.setattr(e2b.AsyncSandbox, "list", staticmethod(flickering))
    handle = await sandbox.acreate("s1")
    assert list(cloud.computers) == [handle.provider_ref]


@pytest.mark.asyncio
async def test_racing_creates_with_lagging_listings_share_one_computer(cloud, sandbox, monkeypatch):
    monkeypatch.setattr(e2b_sandbox, "_LISTING_SECONDS", 5.0)
    cloud.list_lag = 2
    handles = await asyncio.gather(*(sandbox.acreate("s1") for _ in range(3)))
    assert len({handle.provider_ref for handle in handles}) == 1 and cloud.count("create") == 1
    assert list(cloud.computers) == [handles[0].provider_ref] and sandbox._create_locks == {}


@pytest.mark.asyncio
async def test_a_listing_failure_after_create_kills_the_new_computer(cloud, sandbox):
    cloud.fail_list_after_create = True
    with pytest.raises(e2b.TimeoutException):
        await sandbox.acreate("s1")
    assert cloud.computers == {} and cloud.count("kill") == 1


@pytest.mark.asyncio
async def test_a_create_cancelled_while_waiting_for_listings_kills_the_new_computer(cloud, sandbox, monkeypatch):
    monkeypatch.setattr(e2b_sandbox, "_LISTING_SECONDS", 30.0)
    monkeypatch.setattr(e2b_sandbox, "_LISTING_POLL_SECONDS", 0.01)
    cloud.list_lag = 1000
    task = asyncio.create_task(sandbox.acreate("s1"))
    while cloud.count("list") < 3:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert cloud.computers == {} and sandbox._create_locks == {}


@pytest.mark.asyncio
async def test_a_computer_already_handed_out_is_kept_when_listings_omit_it(cloud, sandbox):
    first = await sandbox.acreate("s1")
    cloud.unlisted.add(first.provider_ref)
    assert (await sandbox.acreate("s1")).provider_ref == first.provider_ref
    assert (await sandbox.afind("s1")).provider_ref == first.provider_ref
    assert list(cloud.computers) == [first.provider_ref] and cloud.count("create") == 1


@pytest.mark.asyncio
async def test_a_known_computer_killed_elsewhere_is_forgotten(cloud, sandbox):
    first = await sandbox.acreate("s1")
    await cloud.kill(first.provider_ref)
    second = await sandbox.acreate("s1")
    assert second.provider_ref != first.provider_ref and list(cloud.computers) == [second.provider_ref]
    await sandbox.adestroy(second)
    assert sandbox._known == {}


@pytest.mark.asyncio
async def test_a_runtime_start_failure_kills_a_new_computer_but_not_an_existing_one(cloud, monkeypatch):
    sandbox = E2BSandbox("agno-sandbox", namespace="test", runtime_port=8765)
    failing = {"on": True}

    async def start_runtime(handle):
        if failing["on"]:
            raise SandboxError("Sandbox runtime server did not become ready")

    monkeypatch.setattr(sandbox, "_start_runtime", start_runtime)
    with pytest.raises(SandboxError, match="did not become ready"):
        await sandbox.acreate("s1")
    assert cloud.computers == {} and sandbox._known == {}
    failing["on"] = False
    existing = await sandbox.acreate("s1")
    failing["on"] = True
    with pytest.raises(SandboxError, match="did not become ready"):
        await sandbox.acreate("s1")
    assert list(cloud.computers) == [existing.provider_ref]


@pytest.mark.asyncio
async def test_a_lost_create_reply_waits_for_listings(cloud, sandbox, monkeypatch):
    monkeypatch.setattr(e2b_sandbox, "_LISTING_SECONDS", 5.0)
    cloud.lose_create_reply, cloud.list_lag = True, 2
    handle = await sandbox.acreate("s1")
    assert list(cloud.computers) == [handle.provider_ref]


@pytest.mark.asyncio
async def test_a_refused_create_does_not_wait_for_listings(cloud, sandbox, monkeypatch):
    monkeypatch.setattr(e2b_sandbox, "_LISTING_SECONDS", 60.0)
    cloud.limit = 0
    with pytest.raises(SandboxError, match="limit"):
        await asyncio.wait_for(sandbox.acreate("s1"), timeout=1)
    assert cloud.count("list") == 1


@pytest.mark.asyncio
async def test_a_failed_create_raises_sandbox_error(cloud, sandbox):
    cloud.fail_create = True
    with pytest.raises(SandboxError, match="quota exceeded"):
        await sandbox.acreate("s1")


@pytest.mark.asyncio
async def test_duplicate_computers_keep_the_oldest(cloud, sandbox):
    first = await sandbox.acreate("s1")
    duplicate = cloud.add(cloud.computers[first.provider_ref].metadata)
    assert (await sandbox.afind("s1")).provider_ref == first.provider_ref
    assert duplicate.sandbox_id not in cloud.computers and first.provider_ref in cloud.computers


@pytest.mark.asyncio
async def test_a_different_configuration_is_refused(cloud, sandbox):
    await sandbox.acreate("s1", env={"A": "1"})
    with pytest.raises(SandboxError, match="different configuration"):
        await sandbox.acreate("s1", env={"A": "2"})
    with pytest.raises(SandboxError, match="different compute configuration"):
        await sandbox.afind("s1", env={"A": "2"})


@pytest.mark.asyncio
async def test_lookup_rejects_other_namespaces_and_reports_missing(cloud, sandbox):
    other = cloud.add({"namespace": "someone-else"})
    with pytest.raises(SandboxError, match="namespace"):
        await sandbox.aget(other.sandbox_id)
    assert await sandbox.aget("missing") is None
    with pytest.raises(ValueError):
        await sandbox.aget("../x")


@pytest.mark.asyncio
async def test_commands_run_as_the_agent_user_with_staged_stdin(cloud, sandbox):
    handle = await sandbox.acreate("s1")
    code = "import sys; data = sys.stdin.read(); print(data.upper()); raise SystemExit(3)"
    result = await sandbox.aexec(handle, [sys.executable, "-c", code], stdin=b"hello")
    assert (result.exit_code, result.stdout.strip(), result.timed_out) == (3, "HELLO", False)
    computer = cloud.computers[handle.provider_ref]
    command, options = computer.commands[-1]
    assert options["user"] == "user" and options["cwd"] == "/workspace"
    staged = _RUNNER.match(command).group(1)
    assert staged.startswith("/tmp/agno-exec-") and f"rm -f {staged}" in command
    assert computer.writes[-1] == (staged, "user")


@pytest.mark.asyncio
async def test_invalid_commands_never_reach_e2b(cloud, sandbox):
    handle = await sandbox.acreate("s1")
    calls = len(cloud.calls)
    for argv in ("ls", [], ["a\x00"]):
        with pytest.raises(ValueError):
            await sandbox.aexec(handle, argv)
    with pytest.raises(ValueError):
        await sandbox.aexec(handle, ["ls"], stdin=b"x" * (8 * 1024 * 1024 + 1))
    assert len(cloud.calls) == calls


@pytest.mark.asyncio
async def test_an_uncertain_command_kills_the_computer(cloud, sandbox):
    handle = await sandbox.acreate("s1")
    cloud.command_error = e2b.TimeoutException("stream lost")
    with pytest.raises(SandboxError, match="stream lost"):
        await sandbox.aexec(handle, ["sleep", "1"])
    assert handle.provider_ref not in cloud.computers


@pytest.mark.asyncio
async def test_a_runtime_request_failure_leaves_compute_alone(cloud, sandbox):
    handle = await sandbox.acreate("s1")
    cloud.command_error = e2b.TimeoutException("stream lost")
    with pytest.raises(SandboxError):
        await sandbox.arpc(handle, "poll", json.dumps({"wait": 1}).encode())
    assert handle.provider_ref in cloud.computers


@pytest.mark.asyncio
async def test_a_runner_failure_or_timeout_kills_the_computer(cloud, sandbox):
    handle = await sandbox.acreate("s1")
    cloud.runner_stdout = json.dumps({"exit_code": -9, "stdout": "", "stderr": "", "timed_out": True})
    assert (await sandbox.aexec(handle, ["sleep", "100"])).timed_out
    assert handle.provider_ref not in cloud.computers
    handle = await sandbox.acreate("s2")
    cloud.runner_stdout = "not json"
    with pytest.raises(SandboxError, match="transport failed"):
        await sandbox.aexec(handle, ["true"])
    assert handle.provider_ref not in cloud.computers


@pytest.mark.asyncio
async def test_runner_exit_reports_failure(cloud, sandbox):
    handle = await sandbox.acreate("s1")

    async def exited(command, **kwargs):
        raise CommandExitException(stderr="python: No module named agno", stdout="", exit_code=1, error=None)

    connection = await sandbox._connection(handle)
    connection.commands.run = exited
    with pytest.raises(SandboxError, match="No module named agno"):
        await sandbox.aexec(handle, ["true"])
    assert handle.provider_ref not in cloud.computers


@pytest.mark.asyncio
async def test_pause_and_resume_keep_the_generation(cloud, sandbox):
    handle = await sandbox.acreate("s1")
    await sandbox.apause(handle)
    await sandbox.apause(handle)
    assert cloud.count("pause") == 1
    with pytest.raises(SandboxError, match="paused"):
        await sandbox.aexec(handle, ["true"])
    with pytest.raises(SandboxError, match="resume it or destroy it"):
        await sandbox.acreate("s1")
    resumed = await sandbox.aresume(handle)
    assert resumed.provider_ref == handle.provider_ref and resumed.state == "running"
    assert (await sandbox.aexec(handle, [sys.executable, "-c", "print(1)"])).stdout == "1\n"


@pytest.mark.asyncio
async def test_stop_and_destroy_kill_the_computer(cloud, sandbox):
    handle = await sandbox.acreate("s1")
    await sandbox.adestroy(handle)
    assert await sandbox.aget(handle.provider_ref) is None
    await sandbox.astop(handle)
    assert cloud.count("kill") == 1
    with pytest.raises(SandboxError, match="not running"):
        await sandbox.aexec(handle, ["true"])


@pytest.mark.asyncio
async def test_a_handle_never_acts_on_a_computer_with_another_identity(cloud, sandbox):
    handle = await sandbox.acreate("s1")
    cloud.computers[handle.provider_ref].metadata["config"] = "other"
    with pytest.raises(SandboxError, match="identity changed"):
        await sandbox.astop(handle)
    assert handle.provider_ref in cloud.computers


@pytest.mark.asyncio
async def test_runtime_port_starts_the_server_with_a_per_computer_token(cloud, monkeypatch):
    sandbox = E2BSandbox("agno-sandbox", namespace="test", runtime_port=8765)
    started = []

    async def healthy(handle):
        return bool(started)

    monkeypatch.setattr(sandbox, "_healthy", healthy)
    original = Commands.run

    async def run(self, command, **kwargs):
        if kwargs.get("background"):
            started.append((command, kwargs))
        return await original(self, command, **kwargs)

    monkeypatch.setattr(Commands, "run", run)
    handle = await sandbox.acreate("s1")
    assert handle.runtime_url == f"https://8765-{handle.provider_ref}.e2b.app"
    token = handle.runtime_token
    assert token and cloud.computers[handle.provider_ref].create["envs"] == {}
    command, options = started[0]
    assert "agno.sandbox.runtime supervise --port 8765" in command and command.startswith("flock -n ")
    assert options["envs"] == {"AGNO_SANDBOX_RUNTIME_TOKEN": token} and options["user"] == "user"
    assert "token" not in repr(handle)
    # A second create finds the server already answering and starts nothing.
    assert (await sandbox.acreate("s1")).runtime_token == token and len(started) == 1


@pytest.mark.asyncio
async def test_runtime_requests_carry_the_bearer_token(sandbox):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def do_POST(self):
            seen.append(
                (self.path, self.headers.get("Authorization"), self.rfile.read(int(self.headers["Content-Length"])))
            )
            body = b'{"version": 1}'
            self.send_response(200 if self.headers.get("Authorization") == "Bearer secret" else 401)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from agno.sandbox.base import SandboxHandle

        url = f"http://127.0.0.1:{server.server_address[1]}"
        handle = SandboxHandle("sbx", "agno-x", None, "s", 1, "running", "c", runtime_url=url, runtime_token="secret")
        result = await sandbox.arpc(handle, "poll", b'{"wait": 0}')
        assert (result.exit_code, result.stdout) == (0, '{"version": 1}')
        assert seen[0] == ("/poll", "Bearer secret", b'{"wait": 0}')
        wrong = SandboxHandle("sbx", "agno-x", None, "s", 1, "running", "c", runtime_url=url, runtime_token="other")
        assert (await sandbox.arpc(wrong, "start", b"{}")).exit_code == 1
        with pytest.raises(ValueError):
            await sandbox.arpc(handle, "cancel", b"{}")
    finally:
        # The test loop closes without cancelling the closer task, so close the pooled client here.
        await sandbox._http_client().aclose()
        server.shutdown()
        server.server_close()


def test_runtime_client_is_pooled_per_loop_and_closed_with_it(sandbox):
    async def clients():
        return sandbox._http_client(), sandbox._http_client()

    first, again = asyncio.run(clients())
    assert first is again and first.is_closed and sandbox._http == {}
    second, _ = asyncio.run(clients())
    assert second is not first and second.is_closed


@pytest.mark.asyncio
async def test_checkpoint_round_trip_through_the_file_api(cloud, sandbox, tmp_path):
    store = FileCheckpointStore(tmp_path / "objects")
    transfer = sandbox.checkpoint_transfer(store)
    assert isinstance(transfer, E2BCheckpointTransfer)
    handle = await sandbox.acreate("s1")
    reference = await transfer.acapture(handle, state={"turn": 1})
    computer = cloud.computers[handle.provider_ref]
    # E2B's HTTP/2 file stream is dropped after a few megabytes, so archives come out over HTTP/1.1.
    assert cloud.connect_options[-1].get("http_version") == "1.1"
    assert all("http_version" not in options for options in cloud.connect_options[:-1])
    command, options = computer.commands[-1]
    assert options["user"] == "root" and " capture /var/lib/agno-sandbox/" in command
    # The export is removed once stored.
    assert not [path for path in computer.files if path.startswith("/var/lib/agno-sandbox/")]
    fresh = await sandbox.acreate("s1", generation=2)
    assert await transfer.arestore(fresh, reference) == {"turn": 1}
    assert cloud.computers[fresh.provider_ref].writes[-1][1] == "root"


@pytest.mark.asyncio
async def test_capture_refuses_an_export_that_breaks_its_exclusions(cloud, sandbox, tmp_path):
    transfer = sandbox.checkpoint_transfer(FileCheckpointStore(tmp_path / "objects"))
    handle = await sandbox.acreate("s1")
    with pytest.raises(ValueError, match="entire durable root"):
        await transfer.acapture(handle, state={}, exclude=["workspace"])
    # An export recording other exclusions than requested never reaches the store.
    original = cloud.job

    def job(computer, operation, path, request):
        return original(computer, operation, path, dict(request, exclude=[]))

    cloud.job = job
    with pytest.raises(SandboxError, match="requested exclusions"):
        await transfer.acapture(handle, state={}, exclude=["native/secret"])
    assert list((tmp_path / "objects").rglob("*.tar*")) == []


@pytest.mark.asyncio
async def test_capture_refuses_an_export_whose_size_changed(cloud, sandbox, tmp_path):
    transfer = sandbox.checkpoint_transfer(FileCheckpointStore(tmp_path / "objects"))
    handle = await sandbox.acreate("s1")
    original = cloud.job

    def job(computer, operation, path, request):
        reply = original(computer, operation, path, request)
        size = json.loads(reply.stdout)["size"]
        return SimpleNamespace(exit_code=0, stdout=json.dumps({"size": size - 1}), stderr="")

    cloud.job = job
    with pytest.raises(SandboxError, match="larger than its reported size"):
        await transfer.acapture(handle, state={})


@pytest.mark.asyncio
async def test_a_failed_restore_kills_the_computer(cloud, sandbox, tmp_path):
    transfer = sandbox.checkpoint_transfer(FileCheckpointStore(tmp_path / "objects"))
    source = await sandbox.acreate("s1")
    reference = await transfer.acapture(source, state={"turn": 1})
    target = await sandbox.acreate("s1", generation=2)
    cloud.job_reply = {"state": {"turn": 2}}
    with pytest.raises(SandboxError, match="differs from the verified checkpoint"):
        await transfer.arestore(target, reference)
    assert target.provider_ref not in cloud.computers


@pytest.mark.asyncio
async def test_a_missing_checkpoint_leaves_the_computer_alone(cloud, sandbox, tmp_path):
    from agno.sandbox.checkpoint import CheckpointRef

    transfer = sandbox.checkpoint_transfer(FileCheckpointStore(tmp_path / "objects"))
    target = await sandbox.acreate("s1")
    with pytest.raises(Exception):
        await transfer.arestore(target, CheckpointRef(key="sha256/" + "0" * 64, sha256="0" * 64, size=10))
    assert target.provider_ref in cloud.computers


@pytest.mark.asyncio
async def test_concurrent_creates_of_one_generation_share_one_computer(cloud, sandbox):
    handles = await asyncio.gather(*(sandbox.acreate("s1", agent_id="coder") for _ in range(5)))
    assert len({handle.provider_ref for handle in handles}) == 1
    assert list(cloud.computers) == [handles[0].provider_ref]
    # Creates of one generation are serialized, so only the first one reaches E2B.
    assert cloud.count("create") == 1 and sandbox._create_locks == {}


@pytest.mark.asyncio
async def test_concurrent_creates_of_many_sessions_are_independent(cloud, sandbox):
    handles = await asyncio.gather(*(sandbox.acreate(f"s{i}") for i in range(20)))
    assert len({handle.provider_ref for handle in handles}) == 20 and cloud.count("create") == 20
    for handle in handles:
        computer = cloud.computers[handle.provider_ref]
        assert computer.metadata["session"] == handle.session_id
        assert [c for c, _ in computer.commands if c.startswith("find / -xdev")] == [_HARDEN_COMMAND]


@pytest.mark.asyncio
async def test_creates_past_the_concurrency_limit_fail_cleanly(cloud, sandbox):
    cloud.limit = 3
    results = await asyncio.gather(*(sandbox.acreate(f"s{i}") for i in range(5)), return_exceptions=True)
    handles = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(handles) == 3 and len(failures) == 2
    assert all(isinstance(error, SandboxError) and "limit" in str(error) for error in failures)
    assert sorted(cloud.computers) == sorted(handle.provider_ref for handle in handles)
    await asyncio.gather(*(sandbox.adestroy(handle) for handle in handles))
    assert cloud.computers == {}


@pytest.mark.asyncio
async def test_concurrent_commands_on_one_computer_stage_separate_requests(cloud, sandbox):
    handle = await sandbox.acreate("s1")
    results = await asyncio.gather(*(sandbox.aexec(handle, ["echo", str(i)]) for i in range(10)))
    assert [result.stdout for result in results] == [f"{i}\n" for i in range(10)]
    computer = cloud.computers[handle.provider_ref]
    staged = [path for path, _ in computer.writes]
    assert len(set(staged)) == 10 and not any(path in computer.files for path in staged)


@pytest.mark.asyncio
async def test_concurrent_checkpoints_use_separate_transfer_files(cloud, sandbox, tmp_path):
    transfer = sandbox.checkpoint_transfer(FileCheckpointStore(tmp_path / "objects"))
    sources = await asyncio.gather(*(sandbox.acreate(f"s{i}") for i in range(4)))
    references = await asyncio.gather(
        *(transfer.acapture(handle, state={"session": handle.session_id}) for handle in sources)
    )
    targets = await asyncio.gather(*(sandbox.acreate(handle.session_id, generation=2) for handle in sources))
    states = await asyncio.gather(
        *(transfer.arestore(target, reference) for target, reference in zip(targets, references))
    )
    assert states == [{"session": handle.session_id} for handle in sources]
    for computer in cloud.computers.values():
        assert not [path for path in computer.files if path.startswith("/var/lib/agno-sandbox/")]


@pytest.mark.asyncio
async def test_concurrent_pause_and_resume_keep_each_generation(cloud, sandbox):
    handles = await asyncio.gather(*(sandbox.acreate(f"s{i}") for i in range(5)))
    await asyncio.gather(*(sandbox.apause(handle) for handle in handles))
    assert {computer.state for computer in cloud.computers.values()} == {"paused"}
    resumed = await asyncio.gather(*(sandbox.aresume(handle) for handle in handles))
    assert [handle.provider_ref for handle in resumed] == [handle.provider_ref for handle in handles]
    assert {computer.state for computer in cloud.computers.values()} == {"running"}


def test_transfer_files_must_stay_in_the_root_only_directory():
    for path in ("/tmp/x.tar", "/var/lib/agno-sandbox/../x.tar", "/var/lib/agno-sandbox/x.json"):
        with pytest.raises(SystemExit):
            _archive._transfer_file(path)


def test_a_failed_freeze_resumes_every_process_it_stopped(monkeypatch):
    spawned = iter(range(1000, 2000))
    signals = []
    monkeypatch.setattr(_archive, "_agent_pids", lambda uid: [next(spawned)])
    monkeypatch.setattr(_archive.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(SystemExit, match="kept starting"):
        _archive._freeze(1000)
    stopped = [pid for pid, sig in signals if sig == _archive.signal.SIGSTOP]
    resumed = [pid for pid, sig in signals if sig == _archive.signal.SIGCONT]
    assert len(stopped) == 20 and resumed == stopped


def test_the_transfer_imports_without_unix_only_modules():
    # Windows has no pwd; the host side must import without it and build POSIX remote paths.
    code = (
        "import sys; sys.modules['pwd'] = None; "
        "from agno.sandbox.e2b.transfer import E2BCheckpointTransfer, _TRANSFER_DIR; print(_TRANSFER_DIR)"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert output == "/var/lib/agno-sandbox\n"


def test_importing_the_package_loads_neither_the_sdk_nor_the_provider():
    code = (
        "import sys, agno.sandbox.e2b._archive; "
        "print(any(m == 'e2b' or m.startswith('e2b.') for m in sys.modules), 'agno.sandbox.e2b.sandbox' in sys.modules)"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert output == "False False\n"


def test_harness_settings_travel_with_the_sandbox():
    from unittest.mock import MagicMock

    from agno.agents.claude import ClaudeAgent

    store = MagicMock()
    sandbox = E2BSandbox("agno-sandbox", checkpoints=store, env={"A": "1"}, execution_timeout=60)
    assert (sandbox.checkpoints, sandbox.env, sandbox.execution_timeout) == (store, {"A": "1"}, 60)
    assert ClaudeAgent(id="coder", sandbox=sandbox).sandbox is sandbox
