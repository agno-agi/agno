"""Vercel sandbox commands and runtime requests against a fake Vercel service.

The fake mirrors only calls the Vercel Python SDK (0.9.0) is known to offer: a client with
``get_sandbox`` and ``aclose``, a sandbox with ``current_session``, and a runtime session with
``run_process``, ``fs.write_bytes`` and ``stop``. It has no sandbox-level ``stop``, ``destroy`` or
``run_process``, so a provider that reached for one (which can resume and replay a command, or delete
by name) fails here instead of passing.
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import inspect
import io
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import types
from dataclasses import asdict
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

import pytest

import agno
from agno.sandbox._exec import _execute
from agno.sandbox.base import ExecResult, Sandbox, SandboxError, SandboxHandle
from agno.sandbox.checkpoint import CheckpointArchive, CheckpointLimits, FileCheckpointStore
from agno.sandbox.transfer import DEFAULT_NATIVE_EXCLUSIONS
from agno.sandbox.vercel import guard
from agno.sandbox.vercel import sandbox as vercel_sandbox
from agno.sandbox.vercel.sandbox import VercelSandbox
from agno.sandbox.vercel.transfer import VERCEL_NATIVE_EXCLUSIONS


class FakeApiError(Exception):
    """Has the ``status_code`` the SDK's ``SandboxApiError`` carries."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class FakeWriter:
    def __init__(self, world: "World", path: str, size: Optional[int], permissions: Optional[int]) -> None:
        self.world, self.path, self.size, self.permissions = world, path, size, permissions
        self.data = bytearray()

    async def __aenter__(self) -> "FakeWriter":
        return self

    async def write(self, data: bytes, /) -> int:
        if "upload" in self.world.fail:
            raise self.world.fail["upload"]
        self.data += data
        return len(data)

    async def __aexit__(self, kind: Any, error: Any, trace: Any) -> None:
        if error is None:
            assert self.size is None or self.size == len(self.data)
            self.world.store_file(self.path, bytes(self.data), self.permissions)


class FakeReader:
    def __init__(self, data: bytes) -> None:
        self.data, self.offset = data, 0

    async def __aenter__(self) -> "FakeReader":
        return self

    async def read(self, size: int = -1) -> bytes:
        end = len(self.data) if size < 0 else self.offset + size
        chunk, self.offset = self.data[self.offset : end], min(end, len(self.data))
        return chunk

    async def __aexit__(self, kind: Any, error: Any, trace: Any) -> None:
        return None


class FakeFs:
    def __init__(self, world: "World") -> None:
        self.world = world

    async def write_bytes(
        self, path: str, data: bytes, *, cwd: Optional[str] = None, mode: Optional[int] = None
    ) -> None:
        self.world.events.append("fs.write_bytes")
        self.world.writes.append((path, data, mode))
        if "write" in self.world.fail:
            raise self.world.fail["write"]
        self.world.store_file(path, data, mode)

    def open(
        self, path: str, mode: str = "r", *, size: Optional[int] = None, permissions: Optional[int] = None, **kw: Any
    ) -> Any:
        self.world.events.append(f"fs.open {mode}")
        if mode == "wb":
            return FakeWriter(self.world, path, size, permissions)
        assert mode == "rb"
        if "download" in self.world.fail:
            raise self.world.fail["download"]
        return FakeReader(self.world.read_file(path))

    async def mkdir(self, path: str, *, cwd: Optional[str] = None, recursive: bool = True) -> None:
        self.world.events.append("fs.mkdir")
        self.world.directories.append(path)


_UNSET = object()


class FakeSession:
    def __init__(self, world: "World", session_id: str, status: str = "running") -> None:
        self.world, self.id, self.status = world, session_id, status
        self.sandbox_name = ""
        self.fs = FakeFs(world)
        # None until the bootstrap writes its marker; the unset default is the world's shared marker.
        self.ready_marker: Any = _UNSET

    async def run_process(
        self,
        command: str,
        args: Optional[List[str]] = None,
        *,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        sudo: bool = False,
        kill_after: Any = None,
        check: bool = False,
        stdout: Any = None,
        stderr: Any = None,
        capture_output: bool = False,
    ) -> "FakeProcess":
        self.world.events.append("run_process")
        call = dict(command=command, args=list(args or []), cwd=cwd, sudo=sudo, kill_after=kill_after)
        self.world.runs.append(call)
        returncode = await self.world.guest(self, call, stdout, stderr)
        return FakeProcess(returncode)

    async def stop(self) -> "FakeSession":
        self.world.events.append("session.stop")
        await self.world.wait_at_gate()
        await asyncio.sleep(self.world.stop_delay)
        self.world.stopped.append(self.id)
        if "stop" in self.world.fail:
            raise self.world.fail["stop"]
        self.status = "stopped"
        return self


class FakeProcess:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout = None
        self.stderr = None


class FakeSandbox:
    def __init__(
        self,
        name: str,
        session: Optional[FakeSession],
        tags: Optional[Dict[str, str]] = None,
        *,
        created_at: float = 0,
        persistent: bool = False,
        world: Optional["World"] = None,
    ) -> None:
        self.name, self.current_session, self.tags = name, session, tags
        self.status = None if session is None else session.status
        self._session_id = "" if session is None else session.id
        self.created_at, self.persistent, self.world = created_at, persistent, world

    async def destroy(self, *, delete_orphan_snapshots: bool = False) -> "FakeSandbox":
        assert self.world is not None
        self.world.events.append("sandbox.destroy")
        await self.world.wait_at_gate()
        if "destroy" in self.world.fail:
            raise self.world.fail["destroy"]
        if self.world.sandboxes.pop(self.name, None) is None:
            raise FakeApiError(404)
        self.world.destroyed.append(self.name)
        return self

    @property
    def current_session_id(self) -> str:
        return self.current_session.id if self.current_session is not None else self._session_id


class FakeClient:
    def __init__(self, world: "World", options: Any) -> None:
        self.world, self.options = world, options
        self.loop = asyncio.get_running_loop()
        world.events.append("client.create")
        world.clients.append(self)
        self.closed_in: Optional[asyncio.AbstractEventLoop] = None
        self.closed = False

    async def get_sandbox(self, *, name: str, include_system_routes: Optional[bool] = None) -> FakeSandbox:
        self.world.events.append("get_sandbox")
        if self.closed:
            raise RuntimeError("SDK session is closed")
        if "get" in self.world.fail:
            raise self.world.fail["get"]
        if name not in self.world.sandboxes:
            raise FakeApiError(404)
        return self.world.sandboxes[name]

    def create_sandbox(self, **kwargs: Any) -> "FakeCreate":
        return FakeCreate(self, kwargs)

    async def query_sandboxes(
        self, *, query: Any = None, page_size: Optional[int] = None, cursor: Optional[str] = None
    ) -> Any:
        self.world.events.append("query_sandboxes")
        self.world.queries.append(query)
        if "query" in self.world.fail:
            raise self.world.fail["query"]
        prefix = query.name_prefix if query is not None else ""
        # Delivered a page at a time, as the SDK's iterator does; the caller must read them all.
        names = sorted(name for name in self.world.sandboxes if name.startswith(prefix))
        for start in range(0, len(names), self.world.page_size):
            self.world.pages_read += 1
            for name in names[start : start + self.world.page_size]:
                if name in self.world.sandboxes:
                    yield self.world.sandboxes[name]

    async def aclose(self) -> None:
        self.world.events.append("client.aclose")
        self.closed = True
        self.closed_in = asyncio.get_running_loop()
        if "close" in self.world.fail:
            raise self.world.fail["close"]


class FakeCreate:
    """What ``create_sandbox`` returns: awaiting it makes the box."""

    def __init__(self, client: FakeClient, kwargs: Dict[str, Any]) -> None:
        self.client, self.kwargs = client, kwargs

    def __await__(self) -> Any:
        return self._create().__await__()

    async def _create(self) -> FakeSandbox:
        world = self.client.world
        world.events.append("create_sandbox")
        world.creates.append(self.kwargs)
        if "create" in world.fail:
            raise world.fail["create"]
        name = self.kwargs["name"]
        if name in world.sandboxes:
            raise FakeApiError(400)
        world.serial += 1
        session = FakeSession(world, f"sess-new-{world.serial}")
        session.ready_marker = None
        session.sandbox_name = name
        box = FakeSandbox(name, session, dict(self.kwargs.get("tags") or {}), created_at=world.serial, world=world)
        if world.created_without_session:
            box.current_session, box._session_id = None, None  # type: ignore[assignment]
        world.sandboxes[name] = box
        if world.create_reply_gate is not None:
            await world.create_reply_gate.wait()  # the box exists; its acknowledgement is still on the way
        if "create_reply" in world.fail:
            raise world.fail["create_reply"]  # the box exists, but the caller never hears so
        return box


GuestFn = Callable[["FakeSession", Dict[str, Any], Any, Any], Awaitable[int]]


class World:
    def __init__(self) -> None:
        self.events: List[str] = []
        self.writes: List[Any] = []
        self.runs: List[Dict[str, Any]] = []
        self.files: Dict[str, bytes] = {}
        self.directories: List[str] = []
        self.sandboxes: Dict[str, FakeSandbox] = {}
        self.clients: List[FakeClient] = []
        self.stopped: List[str] = []
        self.destroyed: List[str] = []
        self.creates: List[Dict[str, Any]] = []
        self.queries: List[Any] = []
        self.pages_read = 0
        self.page_size = 50
        self.serial = 0
        self.fail: Dict[str, BaseException] = {}
        self.fail_steps: Dict[str, int] = {}
        self.ready: Optional[Dict[str, Any]] = {"config_digest": "cfg", "source_digest": HOST_DIGEST}
        self.script: Optional[GuestFn] = None
        self.stop_delay = 0.0
        # When set, a stop (or a delete) waits here: the test decides when cleanup may finish.
        self.create_reply_gate: Optional[asyncio.Event] = None
        self.gate: Optional[asyncio.Event] = None
        self.gate_entered: Optional[asyncio.Event] = None
        # What the guest reports for the installed package, and what the bootstrap reported back.
        self.guest_digest = HOST_DIGEST
        self.installed: Dict[str, Any] = {"claude-agent-sdk": "0.2.165", "git": False}
        self.finished: List[Dict[str, Any]] = []
        self.finish_marker: Optional[Dict[str, Any]] = None
        self.created_without_session = False
        self.root_commands: List[Dict[str, Any]] = []
        # When set, the guest is a real directory tree and the guard's own code answers capture and restore.
        self.layout: Optional[guard.Layout] = None
        self.runs_of_the_guard: List[str] = []

    def _on_tree(self, path: str) -> Optional[Path]:
        if self.layout is None:
            return None
        for prefix, directory in ((guard.INBOX, self.layout.inbox), (guard.EXPORT, self.layout.export)):
            if path.startswith(prefix + "/"):
                return directory / path[len(prefix) + 1 :]
        return None

    def store_file(self, path: str, data: bytes, mode: Optional[int]) -> None:
        target = self._on_tree(path)
        if target is None:
            self.files[path] = data
            return
        target.write_bytes(data)
        target.chmod(mode if mode is not None else 0o600)

    def read_file(self, path: str) -> bytes:
        target = self._on_tree(path)
        if target is None:
            return self.files[path]
        return target.read_bytes()

    def _guard(self, command: str, name: str, stdout: Any, stderr: Any) -> int:
        """Run the guard's own entry point on the temporary tree, as the guest would."""
        import contextlib

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            return guard.main(["guard", command, name])

    def hold_cleanup(self) -> None:
        """From now on a stop or a delete waits until ``gate`` is set. Call inside the running loop."""
        self.gate, self.gate_entered = asyncio.Event(), asyncio.Event()

    async def wait_at_gate(self) -> None:
        if self.gate is not None and self.gate_entered is not None:
            self.gate_entered.set()
            await self.gate.wait()

    @staticmethod
    def label(call: Dict[str, Any]) -> str:
        """A short name for a bootstrap step: the command after any ``env NAME=value`` prefix."""
        command, args = call["command"], list(call["args"])
        if command == guard.PYTHON:
            return args[-1] if args[-1] == "digest" else args[-2]
        if command == "env":
            while args and "=" in args[0]:
                args.pop(0)
            command, args = args[0], args[1:]
        return f"{command} {args[0]}" if command == "uv" and args else command

    async def guest(self, session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        if self.script is not None:
            return await self.script(session, call, stdout, stderr)
        args = call["args"]
        if call["command"] != guard.PYTHON:
            self.root_commands.append(call)
            code = self.fail_steps.get(self.label(call), 0)
            if code:
                stderr.write("step failed\n")
            return code
        if args[-2] == "exec":
            request_path = f"{guard.INBOX}/{args[-1]}.json"
            request = json.loads(self.files.pop(request_path))
            stdout.write(json.dumps(_execute(request)))
            return 0
        if args[-1] == "ready":
            marker = self.ready if session.ready_marker is _UNSET else session.ready_marker
            if marker is None:
                stderr.write(guard.REFUSAL_PREFIX + "guest is not ready\n")
                return guard.REFUSED
            stdout.write(json.dumps(marker))
            return 0
        if self.layout is not None and args[-2] in ("capture", "restore", "remove"):
            self.runs_of_the_guard.append(args[-2])
            return self._guard(args[-2], args[-1], stdout, stderr)
        self.root_commands.append(call)
        if args[-1] == "digest":
            stdout.write(json.dumps({"source_digest": self.guest_digest}))
            return self.fail_steps.get("digest", 0)
        if args[-2] == "finish":
            spec = json.loads(self.files.pop(f"{guard.INBOX}/{args[-1]}.json"))
            if self.fail_steps.get("finish"):
                stderr.write("finish failed\n")
                return self.fail_steps["finish"]
            self.finished.append(spec)
            session.ready_marker = self.finish_marker or {**spec["marker"], "installed": self.installed}
            return 0
        raise AssertionError(f"unexpected guest command {call}")


TAGS = {
    "agno_ns": "default",
    "agno_agent": "coder",
    "agno_session": "s",
    "agno_gen": "1",
    "agno_cfg": "cfg",
}


class FakeResources:
    """Stands in for the SDK's ``SandboxResources``, which the tests do not need installed."""

    def __init__(self, *, vcpus: Optional[int] = None, memory: Optional[int] = None) -> None:
        self.vcpus, self.memory = vcpus, memory


class FakeNamePrefix:
    """Stands in for the SDK's ``SandboxQueryByName``."""

    def __init__(self, *, sort_order: str = "desc", name_prefix: Optional[str] = None, tag: Any = None) -> None:
        self.sort_order, self.name_prefix, self.tag = sort_order, name_prefix, tag


FAKE_SDK = types.SimpleNamespace(SandboxResources=FakeResources, SandboxQueryByName=FakeNamePrefix)
# The digest of the host's installed package is fixed here: hashing the real package is tested on its own.
HOST_DIGEST = "d" * 64


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    value = World()
    value.sandboxes["ag-1"] = FakeSandbox("ag-1", FakeSession(value, "sess-1"), dict(TAGS), world=value)
    monkeypatch.setattr(vercel_sandbox, "_new_client", lambda options: FakeClient(value, options))
    monkeypatch.setattr(vercel_sandbox, "_sdk", lambda: FAKE_SDK)
    monkeypatch.setattr(vercel_sandbox, "_host_digest", lambda: HOST_DIGEST)
    monkeypatch.setattr(vercel_sandbox, "_HOST_GRACE", 0.2)
    return value


@pytest.fixture
def sandbox(world: World) -> VercelSandbox:
    return VercelSandbox(execution_timeout=30)


@pytest.fixture
def handle() -> SandboxHandle:
    return SandboxHandle(
        provider_ref="ag-1",
        name="ag-1/sess-1",
        agent_id="coder",
        session_id="s",
        generation=1,
        state="running",
        config_digest="cfg",
    )


PY = [sys.executable, "-c"]
NOT_SENT = ["client.create", "get_sandbox", "client.aclose"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"namespace": ""},
        {"namespace": "a\x00b"},
        {"lifetime": 59},
        {"lifetime": 86401},
        {"lifetime": True},
        {"lifetime": 600.0},
        {"lifetime": 600, "execution_timeout": 600},
        {"lifetime": 600, "execution_timeout": 0},
        {"lifetime": 600, "execution_timeout": float("nan")},
        {"vcpus": 0},
        {"vcpus": 9},
        {"vcpus": True},
        {"vcpus": 1.5},
        {"wheel": 5},
    ],
)
def test_invalid_configuration_is_rejected(kwargs: Dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        VercelSandbox(**kwargs)


def test_defaults_leave_room_for_the_turn_inside_the_lifetime() -> None:
    sandbox = VercelSandbox()
    assert sandbox.lifetime == 1800 and sandbox.execution_timeout == 900
    assert VercelSandbox(lifetime=600).execution_timeout == 300
    assert VercelSandbox(env={"A": "b"}).env == {"A": "b"}


def test_rpc_does_not_inherit_the_destructive_default() -> None:
    assert VercelSandbox.arpc is not Sandbox.arpc


def test_importing_the_package_loads_neither_the_sdk_nor_the_provider() -> None:
    code = "import sys, agno.sandbox.vercel.guard; print('vercel' in sys.modules, 'agno.sandbox.vercel.sandbox' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out == "False False\n"


def test_a_missing_sdk_is_named_when_a_client_is_first_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "vercel", None)
    monkeypatch.setitem(sys.modules, "vercel.sandbox", None)
    with pytest.raises(ImportError, match="vercel-sandbox"):
        vercel_sandbox._new_client(None)


async def test_a_command_is_staged_then_run_by_the_guard_as_root(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    result = await sandbox.aexec(handle, [*PY, "print('hi')"], timeout=5, stdin=b"")
    assert result == ExecResult(exit_code=0, stdout="hi\n", stderr="", timed_out=False, output_limited=False)
    assert world.events == [*NOT_SENT[:2], "fs.write_bytes", "run_process", "client.aclose"]
    ((path, data, mode),) = world.writes
    name = Path(path).stem
    assert Path(path).parent == Path(guard.INBOX) and len(name) == 32 and mode == 0o600
    assert json.loads(data) == {"argv": [*PY, "print('hi')"], "timeout": 5, "max_output_bytes": 1048576, "stdin": ""}
    (run,) = world.runs
    assert run["command"] == guard.PYTHON and run["sudo"] is True and run["cwd"] == "/"
    assert run["args"] == ["-I", "-m", "agno.sandbox.vercel.guard", "exec", name]
    assert run["kill_after"] == 15


async def test_stdin_and_limits_travel_in_the_runners_own_framing(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    code = "import sys; sys.stdout.write(sys.stdin.read().upper()); sys.stdout.write('x' * 400)"
    result = await sandbox.aexec(handle, [*PY, code], timeout=5, max_output_bytes=100, stdin=b"abc")
    assert result.stdout.startswith("ABC") and len(result.stdout) == 100 and result.output_limited
    assert json.loads(world.writes[0][1])["stdin"] == "YWJj"
    assert world.stopped == ["sess-1"]


async def test_a_nonzero_exit_is_a_result_not_a_failure(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    result = await sandbox.aexec(handle, [*PY, "raise SystemExit(3)"], timeout=5)
    assert result.exit_code == 3 and world.stopped == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"argv": []},
        {"argv": "ls"},
        {"argv": ["ls", 1]},
        {"argv": ["a\x00"]},
        {"argv": ["ls"], "timeout": 0},
        {"argv": ["ls"], "timeout": float("inf")},
        {"argv": ["ls"], "max_output_bytes": 0},
        {"argv": ["ls"], "max_output_bytes": 4 * 1024 * 1024 + 1},
        {"argv": ["ls"], "stdin": "text"},
        {"argv": ["ls"], "stdin": b"x" * (8 * 1024 * 1024 + 1)},
    ],
)
async def test_invalid_commands_never_reach_vercel(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, kwargs: Dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        await sandbox.aexec(handle, **kwargs)
    assert world.events == []


async def test_a_request_the_guard_would_refuse_is_rejected_before_sending(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guard, "MAX_STAGED", 200)
    monkeypatch.setattr(vercel_sandbox, "MAX_STAGED", 200)
    with pytest.raises(ValueError, match="staged"):
        await sandbox.aexec(handle, ["ls"], stdin=b"x" * 200)
    assert world.events == []


@pytest.mark.parametrize("name", ["ag-1", "ag-1/", "/sess-1", "ag-2/sess-1", "ag-1/sess/1", "ag-1/ sess-1"])
async def test_a_handle_that_does_not_name_its_session_is_rejected_before_vercel(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, name: str
) -> None:
    bad = SandboxHandle(**{**handle.__dict__, "name": name})
    with pytest.raises(ValueError, match="handle"):
        await sandbox.aexec(bad, ["ls"])
    assert world.events == []


async def test_a_missing_sandbox_raises_without_stopping_anything(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    del world.sandboxes["ag-1"]
    with pytest.raises(SandboxError, match="not running"):
        await sandbox.aexec(handle, ["ls"])
    assert world.events == NOT_SENT and world.runs == []


@pytest.mark.parametrize("replacement", [None, "other-session"])
async def test_a_replaced_or_missing_session_is_not_run_on(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, replacement: Optional[str]
) -> None:
    world.sandboxes["ag-1"].current_session = None if replacement is None else FakeSession(world, replacement)
    with pytest.raises(SandboxError, match="not running"):
        await sandbox.aexec(handle, ["ls"])
    assert world.events == NOT_SENT and world.stopped == []


@pytest.mark.parametrize("status", ["stopped", "stopping", "pending", "failed", "aborted", "snapshotting"])
async def test_only_a_running_session_takes_commands(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, status: str
) -> None:
    world.sandboxes["ag-1"].current_session.status = status  # type: ignore[union-attr]
    with pytest.raises(SandboxError, match="not running"):
        await sandbox.aexec(handle, ["ls"])
    assert world.events == NOT_SENT


async def test_a_service_failure_while_looking_up_is_an_error_not_an_absence(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    world.fail["get"] = FakeApiError(401)
    with pytest.raises(SandboxError, match="401"):
        await sandbox.aexec(handle, ["ls"])
    assert world.events == NOT_SENT and world.runs == []


async def test_a_staging_failure_raises_without_running_or_stopping(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    world.fail["write"] = ConnectionError("upload dropped")
    with pytest.raises(SandboxError, match="stag") as raised:
        await sandbox.aexec(handle, ["ls"])
    assert isinstance(raised.value.__cause__, ConnectionError)
    assert world.events == [*NOT_SENT[:2], "fs.write_bytes", "client.aclose"]
    assert world.runs == [] and world.stopped == []


async def test_an_error_after_submission_stops_the_exact_session_and_never_replays(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def lost(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        raise ConnectionError("reply lost")

    world.script = lost
    with pytest.raises(SandboxError, match="transport failed") as raised:
        await sandbox.aexec(handle, ["ls"])
    assert isinstance(raised.value.__cause__, ConnectionError)
    assert world.events == [
        "client.create",
        "get_sandbox",
        "fs.write_bytes",
        "run_process",
        "client.create",
        "get_sandbox",
        "session.stop",
        "client.aclose",
        "client.aclose",
    ]
    assert len(world.runs) == 1 and world.stopped == ["sess-1"]


async def test_a_host_timeout_stops_the_session(world: World, sandbox: VercelSandbox, handle: SandboxHandle) -> None:
    async def hang(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        await asyncio.sleep(30)
        return 0

    world.script = hang
    with pytest.raises(SandboxError, match="timed out"):
        await sandbox.aexec(handle, ["sleep", "30"], timeout=0.05)
    assert world.stopped == ["sess-1"] and len(world.runs) == 1
    assert world.events[-3:] == ["session.stop", "client.aclose", "client.aclose"]


async def test_cancellation_stops_the_session_then_propagates(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    started = asyncio.Event()

    async def hang(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        started.set()
        await asyncio.sleep(30)
        return 0

    world.script = hang
    task = asyncio.create_task(sandbox.aexec(handle, ["sleep", "30"], timeout=60))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert world.stopped == ["sess-1"] and len(world.runs) == 1
    assert world.events[-3:] == ["session.stop", "client.aclose", "client.aclose"]


@pytest.mark.parametrize(
    "stdout",
    [
        "not json",
        "[]",
        json.dumps({"exit_code": 0}),
        json.dumps({"exit_code": True, "stdout": "", "stderr": "", "timed_out": False, "output_limited": False}),
        json.dumps(
            {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False, "output_limited": False, "extra": 1}
        ),
        json.dumps({"exit_code": 0, "stdout": 1, "stderr": "", "timed_out": False, "output_limited": False}),
    ],
)
async def test_an_invalid_result_stops_the_session(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, stdout: str
) -> None:
    async def reply(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        out.write(stdout)
        return 0

    world.script = reply
    with pytest.raises(SandboxError, match="transport failed"):
        await sandbox.aexec(handle, ["ls"])
    assert world.stopped == ["sess-1"]


async def test_a_runner_that_exits_nonzero_is_a_transport_failure(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def crash(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        err.write("Traceback: boom")
        return 1

    world.script = crash
    with pytest.raises(SandboxError, match="boom"):
        await sandbox.aexec(handle, ["ls"])
    assert world.stopped == ["sess-1"]


async def test_a_guard_refusal_means_nothing_ran_and_nothing_is_stopped(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def refuse(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        err.write(guard.REFUSAL_PREFIX + "guest is not ready\n")
        return guard.REFUSED

    world.script = refuse
    with pytest.raises(SandboxError, match="refused.*not ready"):
        await sandbox.aexec(handle, ["ls"])
    assert world.stopped == [] and len(world.runs) == 1


async def test_exit_75_without_the_guards_message_is_not_a_refusal(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def odd(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        err.write("something else")
        return guard.REFUSED

    world.script = odd
    with pytest.raises(SandboxError, match="transport failed"):
        await sandbox.aexec(handle, ["ls"])
    assert world.stopped == ["sess-1"]


@pytest.mark.parametrize("flag", ["timed_out", "output_limited"])
async def test_a_runner_timeout_or_output_limit_stops_the_session_and_returns_the_result(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, flag: str
) -> None:
    async def limited(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        out.write(
            json.dumps(
                {"exit_code": -9, "stdout": "", "stderr": "", "timed_out": False, "output_limited": False, flag: True}
            )
        )
        return 0

    world.script = limited
    result = await sandbox.aexec(handle, ["ls"])
    assert getattr(result, flag) is True and world.stopped == ["sess-1"]


async def test_a_failed_stop_never_turns_an_uncertain_result_into_success(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def limited(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        out.write(json.dumps({"exit_code": -9, "stdout": "", "stderr": "", "timed_out": True, "output_limited": False}))
        return 0

    world.script = limited
    world.fail["stop"] = FakeApiError(500)
    with pytest.raises(SandboxError, match="could not be stopped.*500"):
        await sandbox.aexec(handle, ["ls"])


async def test_a_failed_stop_keeps_the_primary_error(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def lost(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        raise ConnectionError("reply lost")

    world.script = lost
    world.fail["stop"] = FakeApiError(500)
    with pytest.raises(SandboxError) as raised:
        await sandbox.aexec(handle, ["ls"])
    assert "reply lost" in str(raised.value) and "500" in str(raised.value)
    assert isinstance(raised.value.__cause__, ConnectionError)


async def test_a_second_cancel_cannot_close_the_client_under_the_stop(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    started = asyncio.Event()

    async def hang(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        started.set()
        await asyncio.sleep(30)
        return 0

    world.script = hang
    world.stop_delay = 0.1
    task = asyncio.create_task(sandbox.aexec(handle, ["sleep", "30"], timeout=60))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # The caller does not return until the stop is done, on a client of its own; the fake refuses closed clients.
    assert world.stopped == ["sess-1"]
    assert world.events.index("session.stop") < len(world.events) - 1
    assert world.events.count("client.aclose") == 2 and world.clients[0].closed and world.clients[1].closed


async def _cancel_twice_while_cleanup_is_held(world: World, task: "asyncio.Task[Any]") -> None:
    """Cancel a caller whose cleanup is waiting at the gate, then cancel it again, and let the loop run."""
    assert world.gate_entered is not None
    await asyncio.wait_for(world.gate_entered.wait(), 5)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    for _ in range(10):  # the loop turns over; nothing releases the cleanup
        await asyncio.sleep(0)


async def test_a_caller_cancelled_again_waits_for_its_cleanup_before_returning(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    started = asyncio.Event()

    async def hang(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        started.set()
        await asyncio.sleep(30)
        return 0

    world.script = hang
    world.hold_cleanup()
    task = asyncio.create_task(sandbox.aexec(handle, ["sleep", "30"], timeout=60))
    await started.wait()
    task.cancel()  # the first cancellation starts the stop, which waits at the gate
    try:
        await _cancel_twice_while_cleanup_is_held(world, task)
        assert not task.done(), "the caller returned while its stop was still pending"
        assert world.stopped == []
    finally:
        assert world.gate is not None
        world.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert world.stopped == ["sess-1"] and world.events.count("client.aclose") == 2


def test_cleanup_finishes_before_a_short_lived_event_loop_shuts_down(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def scenario() -> None:
        started = asyncio.Event()

        async def hang(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
            started.set()
            await asyncio.sleep(30)
            return 0

        world.script = hang
        world.hold_cleanup()
        task = asyncio.create_task(sandbox.aexec(handle, ["sleep", "30"], timeout=60))
        await started.wait()
        task.cancel()
        assert world.gate_entered is not None and world.gate is not None
        await asyncio.wait_for(world.gate_entered.wait(), 5)
        task.cancel()
        # The cleanup is released only after the caller has been cancelled twice; the loop then ends with the caller.
        asyncio.get_running_loop().call_later(0.05, world.gate.set)
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert world.stopped == ["sess-1"]


async def test_a_failed_cleanup_after_repeated_cancellation_is_retrieved_not_left_as_a_stray_exception(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, caplog: pytest.LogCaptureFixture
) -> None:
    started = asyncio.Event()
    stray: List[Any] = []
    asyncio.get_running_loop().set_exception_handler(lambda loop, context: stray.append(context))

    async def hang(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        started.set()
        await asyncio.sleep(30)
        return 0

    world.script = hang
    world.hold_cleanup()
    world.fail["stop"] = FakeApiError(500)
    task = asyncio.create_task(sandbox.aexec(handle, ["sleep", "30"], timeout=60))
    await started.wait()
    task.cancel()
    try:
        await _cancel_twice_while_cleanup_is_held(world, task)
    finally:
        assert world.gate is not None
        world.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    gc.collect()
    await asyncio.sleep(0)
    assert stray == []


async def test_a_bootstrap_cleanup_survives_repeated_cancellation_of_its_caller(
    world: World, sandbox: VercelSandbox
) -> None:
    entered = asyncio.Event()

    async def hang(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        entered.set()
        await asyncio.sleep(30)
        return 0

    world.script = hang
    world.hold_cleanup()
    task = asyncio.create_task(sandbox.acreate("s", agent_id="coder"))
    await entered.wait()
    task.cancel()
    try:
        await _cancel_twice_while_cleanup_is_held(world, task)
        assert not task.done(), "create returned while its computer was still being removed"
    finally:
        assert world.gate is not None
        world.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert world.stopped == ["sess-new-1"] and len(world.destroyed) == 1


async def test_a_restore_stop_survives_repeated_cancellation_of_its_caller(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, tmp_path: Path
) -> None:
    store = FileCheckpointStore(tmp_path / "objects")
    reference = await store.aput(_source_tree(tmp_path, {"binding": "b"}))
    entered = asyncio.Event()

    async def hang(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        entered.set()
        await asyncio.sleep(30)
        return 0

    world.script = hang
    world.hold_cleanup()
    task = asyncio.create_task(sandbox.checkpoint_transfer(store).arestore(handle, reference))
    await entered.wait()
    task.cancel()
    try:
        await _cancel_twice_while_cleanup_is_held(world, task)
        assert not task.done(), "restore returned while the computer was still being stopped"
    finally:
        assert world.gate is not None
        world.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert world.stopped == ["sess-1"]


async def test_cancellation_survives_a_failed_stop(world: World, sandbox: VercelSandbox, handle: SandboxHandle) -> None:
    started = asyncio.Event()

    async def hang(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        started.set()
        await asyncio.sleep(30)
        return 0

    world.script = hang
    world.fail["stop"] = FakeApiError(500)
    task = asyncio.create_task(sandbox.aexec(handle, ["sleep", "30"], timeout=60))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_output_beyond_what_the_runner_can_produce_is_a_protocol_failure(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def flood(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        for _ in range(100):
            out.write("x" * 4096)
        return 0

    world.script = flood
    with pytest.raises(SandboxError, match="transport failed"):
        await sandbox.aexec(handle, ["ls"], max_output_bytes=100)
    assert world.stopped == ["sess-1"]


async def test_a_runtime_replacement_session_is_never_stopped(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def swapped(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        world.sandboxes["ag-1"].current_session = FakeSession(world, "sess-2")
        raise ConnectionError("lost")

    world.script = swapped
    with pytest.raises(SandboxError):
        await sandbox.aexec(handle, ["ls"])
    assert world.stopped == []


async def test_each_operation_owns_and_closes_its_client(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    await sandbox.aexec(handle, [*PY, "pass"])
    with pytest.raises(SandboxError):
        await sandbox.aexec(SandboxHandle(**{**handle.__dict__, "name": "ag-1/nope"}), ["ls"])
    assert len(world.clients) == 2
    assert world.events.count("client.create") == world.events.count("client.aclose") == 2


def test_repeated_sync_calls_use_a_client_per_event_loop_and_close_each(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    for _ in range(3):
        assert sandbox.exec(handle, [*PY, "print(1)"]).stdout == "1\n"
    sandbox.stop(handle)
    assert len(world.clients) == 4
    assert all(client.closed_in is client.loop for client in world.clients)
    assert len({id(client.loop) for client in world.clients}) == 4


async def test_a_failing_close_does_not_replace_the_primary_error(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    world.fail["close"] = RuntimeError("close failed")
    del world.sandboxes["ag-1"]
    with pytest.raises(SandboxError, match="not running"):
        await sandbox.aexec(handle, ["ls"])


async def test_a_failing_close_does_not_fail_a_completed_command(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    world.fail["close"] = RuntimeError("close failed")
    assert (await sandbox.aexec(handle, [*PY, "print(2)"])).stdout == "2\n"


@pytest.mark.parametrize(
    "operation,payload", [("poll!", b"{}"), ("stop", b"{}"), ("start", "text"), ("start", b"x" * (1024 * 1024 + 1))]
)
async def test_rpc_accepts_only_start_and_poll_within_the_limit(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, operation: str, payload: Any
) -> None:
    with pytest.raises(ValueError):
        await sandbox.arpc(handle, operation, payload)
    assert world.events == []


async def test_rpc_runs_the_fixed_runtime_command_with_the_payload_as_stdin(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    seen: List[Dict[str, Any]] = []

    async def runtime(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        request = json.loads(world.files.pop(f"{guard.INBOX}/{call['args'][-1]}.json"))
        seen.append(request)
        out.write(
            json.dumps(
                {"exit_code": 0, "stdout": '{"version": 1}', "stderr": "", "timed_out": False, "output_limited": False}
            )
        )
        return 0

    world.script = runtime
    result = await sandbox.arpc(handle, "poll", json.dumps({"wait": 10}).encode())
    assert result == ExecResult(exit_code=0, stdout='{"version": 1}', stderr="")
    (request,) = seen
    assert request["argv"] == ["python", "-I", "-m", "agno.sandbox.runtime", "poll"]
    assert request["timeout"] == 25 and request["max_output_bytes"] == 4 * 1024 * 1024
    assert request["stdin"] == "eyJ3YWl0IjogMTB9"


async def test_rpc_wait_is_capped_and_defaults_safely(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    timeouts: List[float] = []

    async def runtime(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        timeouts.append(json.loads(world.files.pop(f"{guard.INBOX}/{call['args'][-1]}.json"))["timeout"])
        out.write(
            json.dumps({"exit_code": 0, "stdout": "{}", "stderr": "", "timed_out": False, "output_limited": False})
        )
        return 0

    world.script = runtime
    for payload in (b'{"wait": 99}', b'{"wait": -4}', b"not json", b"[]", b'{"wait": NaN}', b'{"wait": Infinity}'):
        await sandbox.arpc(handle, "poll", payload)
    assert timeouts == [45, 15, 15, 15, 15, 15]


async def test_a_lost_rpc_reply_leaves_compute_running(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def lost(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        raise ConnectionError("reply lost")

    world.script = lost
    with pytest.raises(SandboxError, match="Runtime request failed") as raised:
        await sandbox.arpc(handle, "start", b"{}")
    assert isinstance(raised.value.__cause__, ConnectionError)
    assert world.stopped == [] and world.events[-1] == "client.aclose"
    assert "session.stop" not in world.events and world.events.count("get_sandbox") == 1


async def test_an_rpc_timeout_leaves_compute_running(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hang(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        await asyncio.sleep(30)
        return 0

    monkeypatch.setattr(vercel_sandbox, "_RPC_BASE_SECONDS", 0.05)
    world.script = hang
    with pytest.raises(SandboxError, match="timed out"):
        await sandbox.arpc(handle, "poll", b"{}")
    assert world.stopped == []


async def test_rpc_cancellation_propagates_without_stopping(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    started = asyncio.Event()

    async def hang(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        started.set()
        await asyncio.sleep(30)
        return 0

    world.script = hang
    task = asyncio.create_task(sandbox.arpc(handle, "poll", b"{}"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert world.stopped == [] and world.events[-1] == "client.aclose"


async def test_an_rpc_the_guard_refuses_raises_and_leaves_compute_running(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def refuse(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        err.write(guard.REFUSAL_PREFIX + "guest is not ready\n")
        return guard.REFUSED

    world.script = refuse
    with pytest.raises(SandboxError, match="refused"):
        await sandbox.arpc(handle, "start", b"{}")
    assert world.stopped == []


async def test_an_rpc_runner_failure_never_stops_compute(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def crash(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        out.write("garbage")
        return 0

    world.script = crash
    with pytest.raises(SandboxError, match="Runtime request failed"):
        await sandbox.arpc(handle, "poll", b"{}")
    assert world.stopped == []


async def test_an_rpc_runner_timeout_flag_is_returned_for_the_client_to_report(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def slow(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        out.write(json.dumps({"exit_code": -9, "stdout": "", "stderr": "", "timed_out": True, "output_limited": False}))
        return 0

    world.script = slow
    result = await sandbox.arpc(handle, "poll", b"{}")
    assert result.timed_out and world.stopped == []


async def test_stop_stops_only_the_exact_bound_session(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    await sandbox.astop(handle)
    assert world.events == ["client.create", "get_sandbox", "session.stop", "client.aclose"]
    assert world.stopped == ["sess-1"]


@pytest.mark.parametrize("status", ["stopped", "stopping", "failed", "aborted"])
async def test_stop_of_an_already_ended_session_does_nothing(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, status: str
) -> None:
    world.sandboxes["ag-1"].current_session.status = status  # type: ignore[union-attr]
    await sandbox.astop(handle)
    assert world.stopped == []


@pytest.mark.parametrize("replacement", [None, "sess-2"])
async def test_stop_leaves_a_different_or_missing_current_session_alone(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, replacement: Optional[str]
) -> None:
    world.sandboxes["ag-1"].current_session = None if replacement is None else FakeSession(world, replacement)
    await sandbox.astop(handle)
    assert world.stopped == []


async def test_stop_of_a_deleted_sandbox_is_a_no_op(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    del world.sandboxes["ag-1"]
    await sandbox.astop(handle)
    assert world.stopped == []


async def test_stop_treats_a_session_that_vanished_between_lookup_and_stop_as_gone(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    world.fail["stop"] = FakeApiError(404)
    await sandbox.astop(handle)


async def test_stop_reports_service_failures(world: World, sandbox: VercelSandbox, handle: SandboxHandle) -> None:
    world.fail["get"] = FakeApiError(503)
    with pytest.raises(SandboxError, match="503"):
        await sandbox.astop(handle)
    world.fail.clear()
    world.fail["stop"] = FakeApiError(500)
    with pytest.raises(SandboxError, match="500"):
        await sandbox.astop(handle)


async def test_stop_that_leaves_the_session_running_is_an_error(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    async def still_running(self: FakeSession) -> FakeSession:
        return self

    session = world.sandboxes["ag-1"].current_session
    session.stop = still_running.__get__(session)  # type: ignore[union-attr,method-assign]
    with pytest.raises(SandboxError, match="did not stop"):
        await sandbox.astop(handle)


async def test_a_running_verified_guest_is_running(world: World, sandbox: VercelSandbox, handle: SandboxHandle) -> None:
    got = await sandbox.aget("ag-1")
    assert got == SandboxHandle(
        provider_ref="ag-1",
        name="ag-1/sess-1",
        agent_id="coder",
        session_id="s",
        generation=1,
        state="running",
        config_digest="cfg",
    )
    assert world.events == ["client.create", "get_sandbox", "run_process", "client.aclose"]
    (run,) = world.runs
    assert run["args"] == ["-I", "-m", "agno.sandbox.vercel.guard", "ready"] and run["sudo"] is True


async def test_inspection_writes_nothing_and_stops_nothing(world: World, sandbox: VercelSandbox) -> None:
    await sandbox.aget("ag-1")
    assert world.writes == [] and world.stopped == [] and world.files == {}


@pytest.mark.parametrize("ready", [None, {"config_digest": "other"}, {}, {"config_digest": 3}])
async def test_a_running_guest_without_verified_ready_is_not_usable(
    world: World, sandbox: VercelSandbox, ready: Any
) -> None:
    world.ready = ready
    assert (await sandbox.aget("ag-1")).state == "created"  # type: ignore[union-attr]


async def test_a_ready_marker_that_is_not_json_is_not_ready(world: World, sandbox: VercelSandbox) -> None:
    async def junk(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        out.write("not json")
        return 0

    world.script = junk
    assert (await sandbox.aget("ag-1")).state == "created"  # type: ignore[union-attr]


async def test_a_guest_that_cannot_run_the_guard_yet_is_not_ready(world: World, sandbox: VercelSandbox) -> None:
    async def missing(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        err.write("No module named agno")
        return 1

    world.script = missing
    assert (await sandbox.aget("ag-1")).state == "created"  # type: ignore[union-attr]


async def test_a_failure_to_ask_the_guest_is_an_error_not_a_verdict(world: World, sandbox: VercelSandbox) -> None:
    async def down(session: FakeSession, call: Dict[str, Any], out: Any, err: Any) -> int:
        raise ConnectionError("service down")

    world.script = down
    with pytest.raises(SandboxError, match="service down"):
        await sandbox.aget("ag-1")


@pytest.mark.parametrize(
    "status,state",
    [
        ("stopped", "exited"),
        ("failed", "exited"),
        ("aborted", "exited"),
        ("stopping", "exited"),
        ("pending", "created"),
        ("snapshotting", "created"),
    ],
)
async def test_service_states_map_to_the_planned_states_without_asking_the_guest(
    world: World, sandbox: VercelSandbox, status: str, state: str
) -> None:
    world.sandboxes["ag-1"].current_session.status = status  # type: ignore[union-attr]
    assert (await sandbox.aget("ag-1")).state == state  # type: ignore[union-attr]
    assert world.runs == []


async def test_an_unknown_status_is_never_treated_as_running(world: World, sandbox: VercelSandbox) -> None:
    world.sandboxes["ag-1"].current_session.status = "teleporting"  # type: ignore[union-attr]
    with pytest.raises(SandboxError, match="status"):
        await sandbox.aget("ag-1")


async def test_a_sandbox_without_a_session_reports_its_own_status(world: World, sandbox: VercelSandbox) -> None:
    world.sandboxes["ag-1"].current_session = None
    world.sandboxes["ag-1"].status = "stopped"
    got = await sandbox.aget("ag-1")
    assert got is not None and got.state == "exited" and got.name == "ag-1/sess-1"


async def test_a_missing_sandbox_is_absent(world: World, sandbox: VercelSandbox) -> None:
    assert await sandbox.aget("ag-9") is None


@pytest.mark.parametrize("status_code", [401, 403, 429, 500])
async def test_authentication_and_service_failures_are_not_absence(
    world: World, sandbox: VercelSandbox, status_code: int
) -> None:
    world.fail["get"] = FakeApiError(status_code)
    with pytest.raises(SandboxError, match=str(status_code)):
        await sandbox.aget("ag-1")


async def test_a_failure_with_no_status_code_is_not_absence(world: World, sandbox: VercelSandbox) -> None:
    world.fail["get"] = RuntimeError("boom")
    with pytest.raises(SandboxError, match="boom"):
        await sandbox.aget("ag-1")


@pytest.mark.parametrize("ref", ["", "a/b", "a\x00", None, 3])
async def test_an_invalid_reference_is_rejected_before_vercel(world: World, sandbox: VercelSandbox, ref: Any) -> None:
    with pytest.raises(ValueError):
        await sandbox.aget(ref)
    assert world.events == []


@pytest.mark.parametrize(
    "tags",
    [
        None,
        {},
        {**TAGS, "agno_gen": "x"},
        {**TAGS, "agno_gen": "0"},
        {k: v for k, v in TAGS.items() if k != "agno_cfg"},
        {**TAGS, "agno_ns": "elsewhere"},
    ],
)
async def test_a_sandbox_without_this_providers_identity_is_refused(
    world: World, sandbox: VercelSandbox, tags: Any
) -> None:
    world.sandboxes["ag-1"].tags = tags
    with pytest.raises(SandboxError, match="identity|namespace"):
        await sandbox.aget("ag-1")


async def test_a_missing_agent_is_none(world: World, sandbox: VercelSandbox) -> None:
    world.sandboxes["ag-1"].tags = {**TAGS, "agno_agent": ""}
    assert (await sandbox.aget("ag-1")).agent_id is None  # type: ignore[union-attr]


def test_the_sync_wrapper_forwards_to_the_async_inspection(world: World, sandbox: VercelSandbox) -> None:
    assert sandbox.get("ag-1").state == "running"  # type: ignore[union-attr]
    assert world.events.count("client.create") == world.events.count("client.aclose") == 1


def _prefix(namespace: str, agent: Optional[str], session: str, generation: int) -> str:
    identity = json.dumps([namespace, agent, session, generation])
    return "ag-" + hashlib.sha256(identity.encode()).hexdigest()[:10]


def _add(
    world: World,
    name: str,
    *,
    session: str = "s",
    agent: Optional[str] = "coder",
    generation: int = 1,
    digest: str = "cfg",
    status: str = "running",
    ready: Any = _UNSET,
    created: float = 1,
    namespace: str = "default",
    persistent: bool = False,
    tags: Optional[Dict[str, str]] = None,
) -> FakeSandbox:
    box = FakeSandbox(
        name,
        FakeSession(world, f"sess-{name[-4:]}", status),
        tags
        if tags is not None
        else {
            "agno_ns": namespace,
            "agno_agent": agent or "",
            "agno_session": session,
            "agno_gen": str(generation),
            "agno_cfg": digest,
        },
        created_at=created,
        persistent=persistent,
        world=world,
    )
    assert box.current_session is not None
    box.current_session.ready_marker = (
        {"config_digest": digest, "source_digest": HOST_DIGEST} if ready is _UNSET else ready
    )
    world.sandboxes[name] = box
    return box


def _digest_for(sandbox: VercelSandbox, session: str = "s", agent: Optional[str] = "coder", generation: int = 1) -> str:
    return sandbox._digest(session, agent, generation, {})


def test_afind_has_the_signature_the_base_declares() -> None:
    assert inspect.signature(VercelSandbox.afind) == inspect.signature(Sandbox.afind)
    assert inspect.signature(VercelSandbox.find) == inspect.signature(Sandbox.find)
    assert "for_create" in inspect.signature(VercelSandbox.afind).parameters


def test_the_name_prefix_is_a_short_hash_of_the_full_identity(sandbox: VercelSandbox) -> None:
    assert sandbox._prefix("s", "coder", 1) == _prefix("default", "coder", "s", 1)
    others = {
        sandbox._prefix("s2", "coder", 1),
        sandbox._prefix("s", "other", 1),
        sandbox._prefix("s", None, 1),
        sandbox._prefix("s", "coder", 2),
        VercelSandbox(namespace="x")._prefix("s", "coder", 1),
    }
    assert len(others | {sandbox._prefix("s", "coder", 1)}) == 6


async def test_afind_returns_none_when_nothing_was_created(world: World, sandbox: VercelSandbox) -> None:
    assert await sandbox.afind("s", agent_id="coder") is None
    assert world.queries[0].name_prefix == _prefix("default", "coder", "s", 1) + "-"
    assert world.stopped == [] and world.destroyed == [] and world.creates == []


async def test_afind_returns_the_computer_by_prefix_with_its_exact_session(
    world: World, sandbox: VercelSandbox
) -> None:
    name = _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa"
    _add(world, name, digest=_digest_for(sandbox))
    found = await sandbox.afind("s", agent_id="coder")
    assert found == SandboxHandle(
        provider_ref=name,
        name=f"{name}/sess-aaaa",
        agent_id="coder",
        session_id="s",
        generation=1,
        state="running",
        config_digest=_digest_for(sandbox),
    )


async def test_for_create_changes_nothing_about_what_afind_does(world: World, sandbox: VercelSandbox) -> None:
    _add(world, _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa", digest=_digest_for(sandbox))
    plain = await sandbox.afind("s", agent_id="coder")
    events = list(world.events)
    world.events.clear()
    forced = await sandbox.afind("s", agent_id="coder", for_create=True)
    assert forced == plain and world.events == events
    assert world.stopped == [] and world.destroyed == [] and world.creates == []


def test_the_sync_find_forwards_every_keyword(world: World, sandbox: VercelSandbox) -> None:
    _add(
        world,
        _prefix("default", "coder", "s", 2) + "-aaaaaaaaaaaa",
        generation=2,
        digest=_digest_for(sandbox, generation=2),
    )
    found = sandbox.find("s", agent_id="coder", generation=2, env=None, for_create=True)
    assert found is not None and found.generation == 2


async def test_afind_reads_every_page_of_the_listing(world: World, sandbox: VercelSandbox) -> None:
    world.page_size = 10
    prefix = _prefix("default", "coder", "s", 1)
    for index in range(35):  # same prefix, other sessions' tags: listed but not this allocation's
        _add(world, f"{prefix}-{index:012x}", session=f"someone-else-{index}", digest=_digest_for(sandbox))
    wanted = f"{prefix}-fffffffffff9"
    _add(world, wanted, digest=_digest_for(sandbox), created=99)
    found = await sandbox.afind("s", agent_id="coder")
    assert found is not None and found.provider_ref == wanted and world.pages_read == 4


async def test_afind_accepts_only_what_this_providers_naming_and_tags_describe(
    world: World, sandbox: VercelSandbox
) -> None:
    prefix = _prefix("default", "coder", "s", 1)
    digest = _digest_for(sandbox)
    _add(world, f"{prefix}-aaaaaaaaaaaa", digest=digest, namespace="other-namespace")
    _add(world, f"{prefix}-bbbbbbbbbbbb", digest=digest, persistent=True)
    _add(world, f"{prefix}-cccccccccccc", digest=digest, agent="somebody")
    _add(world, f"{prefix}-dddddddddddd", digest=digest, generation=2)
    _add(world, f"{prefix}-not-a-hex-name", digest=digest)
    _add(world, f"{prefix}-eeeeeeeeeeeeee", digest=digest)  # a longer suffix than this provider mints
    _add(world, f"{prefix}-ffffffffffff", digest=digest, tags={"agno_ns": "default"})
    assert await sandbox.afind("s", agent_id="coder") is None


async def test_afind_returns_the_newest_attempt_and_deletes_none(world: World, sandbox: VercelSandbox) -> None:
    prefix = _prefix("default", "coder", "s", 1)
    digest = _digest_for(sandbox)
    _add(world, f"{prefix}-aaaaaaaaaaaa", digest=digest, status="stopped", created=1)
    _add(world, f"{prefix}-bbbbbbbbbbbb", digest=digest, created=3)
    _add(world, f"{prefix}-cccccccccccc", digest=digest, created=2)
    found = await sandbox.afind("s", agent_id="coder")
    assert found is not None and found.provider_ref == f"{prefix}-bbbbbbbbbbbb"
    assert world.stopped == [] and world.destroyed == [] and len(world.sandboxes) == 4


async def test_afind_reports_an_ended_computer_so_the_coordinator_can_destroy_it(
    world: World, sandbox: VercelSandbox
) -> None:
    name = _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa"
    _add(world, name, digest=_digest_for(sandbox), status="stopped")
    found = await sandbox.afind("s", agent_id="coder")
    assert found is not None and found.state == "exited"


async def test_a_running_computer_without_its_marker_is_not_usable(world: World, sandbox: VercelSandbox) -> None:
    name = _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa"
    _add(world, name, digest=_digest_for(sandbox), ready=None)
    found = await sandbox.afind("s", agent_id="coder")
    assert found is not None and found.state == "created"


async def test_a_computer_made_for_another_configuration_is_refused(world: World, sandbox: VercelSandbox) -> None:
    _add(world, _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa", digest="a different configuration")
    with pytest.raises(SandboxError, match="different compute configuration"):
        await sandbox.afind("s", agent_id="coder")


async def test_a_different_environment_is_a_different_configuration(world: World, sandbox: VercelSandbox) -> None:
    _add(world, _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa", digest=_digest_for(sandbox))
    with pytest.raises(SandboxError, match="different compute configuration"):
        await sandbox.afind("s", agent_id="coder", env={"MODEL_KEY": "k"})


async def test_a_listing_failure_is_an_error_not_an_absence(world: World, sandbox: VercelSandbox) -> None:
    world.fail["query"] = FakeApiError(500)
    with pytest.raises(SandboxError, match="list"):
        await sandbox.afind("s", agent_id="coder")
    assert world.events[-1] == "client.aclose"


async def test_a_computer_deleted_between_listing_and_reading_is_absent(world: World, sandbox: VercelSandbox) -> None:
    name = _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa"
    box = _add(world, name, digest=_digest_for(sandbox))
    original = FakeClient.query_sandboxes

    async def listing_then_gone(self: FakeClient, **kwargs: Any) -> Any:
        async for item in original(self, **kwargs):
            yield item
        world.sandboxes.pop(box.name)

    FakeClient.query_sandboxes = listing_then_gone  # type: ignore[method-assign]
    try:
        assert await sandbox.afind("s", agent_id="coder") is None
    finally:
        FakeClient.query_sandboxes = original  # type: ignore[method-assign]


@pytest.mark.parametrize("env", [{"PATH": "/x"}, {"HOME": "/x"}, {"A=B": "c"}, {"A": 1}])
async def test_a_computer_environment_the_guard_would_not_honor_is_rejected_before_vercel(
    world: World, sandbox: VercelSandbox, env: Dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        await sandbox.afind("s", env=env)
    with pytest.raises(ValueError):
        await sandbox.acreate("s", env=env)
    assert world.events == []


STALE = {"source_digest": "an older host's source"}


@pytest.mark.parametrize(
    "difference",
    [STALE, {"source_digest": None}, {"source_digest": 7}],
    ids=["other-source", "no-source-recorded", "not-a-digest"],
)
async def test_a_computer_bootstrapped_from_other_source_is_found_but_not_usable(
    world: World, sandbox: VercelSandbox, difference: Dict[str, Any]
) -> None:
    name = _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa"
    marker = {"config_digest": _digest_for(sandbox), "source_digest": HOST_DIGEST, **difference}
    if difference["source_digest"] is None:
        del marker["source_digest"]
    _add(world, name, digest=_digest_for(sandbox), ready=marker)
    found = await sandbox.afind("s", agent_id="coder")
    assert found is not None and found.provider_ref == name and found.state == "created"
    inspected = await sandbox.aget(name)
    assert inspected is not None and inspected.state == "created"
    assert world.stopped == [] and world.destroyed == [] and world.creates == []


async def test_a_computer_from_other_source_is_not_adopted_and_stays_deletable_by_its_own_handle(
    world: World, sandbox: VercelSandbox
) -> None:
    name = _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa"
    _add(world, name, digest=_digest_for(sandbox), ready={"config_digest": _digest_for(sandbox), **STALE})
    created = await sandbox.acreate("s", agent_id="coder")
    assert created.provider_ref != name and len(world.creates) == 1
    assert name in world.sandboxes and world.destroyed == [] and world.stopped == []
    old = await sandbox.aget(name)
    assert old is not None
    await sandbox.adestroy(old)
    assert world.destroyed == [name] and created.provider_ref in world.sandboxes


async def test_a_computer_from_matching_source_is_still_found_and_adopted(world: World, sandbox: VercelSandbox) -> None:
    name = _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa"
    _add(world, name, digest=_digest_for(sandbox))
    found = await sandbox.afind("s", agent_id="coder")
    assert found is not None and found.state == "running"
    assert (await sandbox.acreate("s", agent_id="coder")).provider_ref == name and world.creates == []


async def test_a_failure_to_read_the_marker_is_still_an_error_not_a_source_verdict(
    world: World, sandbox: VercelSandbox
) -> None:
    _add(world, _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa", digest=_digest_for(sandbox))

    async def broken(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        raise ConnectionError("lost")

    world.script = broken
    with pytest.raises(SandboxError, match="Could not check whether"):
        await sandbox.afind("s", agent_id="coder")


def _steps(world: World) -> List[str]:
    return [World.label(call) for call in world.root_commands]


BOOTSTRAP = ["uv --version", "mkdir", "uv venv", "uv pip", "chmod", "digest", "install", "finish"]


async def test_create_makes_one_attempt_under_a_fresh_name_and_bootstraps_it(
    world: World, sandbox: VercelSandbox
) -> None:
    handle = await sandbox.acreate("s", agent_id="coder", generation=2, env={"MODEL_KEY": "k"})
    [call] = world.creates
    prefix = _prefix("default", "coder", "s", 2)
    assert re.fullmatch(prefix + r"-[0-9a-f]{12}", call["name"]) and call["name"] in world.sandboxes
    assert call["persistent"] is False and call["execution_time_limit"] == sandbox.lifetime
    assert call["image"] == vercel_sandbox.IMAGE and call.get("env") is None
    assert (call["resources"].vcpus, call["resources"].memory) == (1, 2048)
    assert call["tags"] == {
        "agno_ns": "default",
        "agno_agent": "coder",
        "agno_session": "s",
        "agno_gen": "2",
        "agno_cfg": handle.config_digest,
    }
    assert handle == SandboxHandle(
        provider_ref=call["name"],
        name=f"{call['name']}/sess-new-1",
        agent_id="coder",
        session_id="s",
        generation=2,
        state="running",
        config_digest=_digest_for(sandbox, generation=2).replace(
            _digest_for(sandbox, generation=2), handle.config_digest
        ),
    )
    assert handle.config_digest == sandbox._digest("s", "coder", 2, {"MODEL_KEY": "k"})
    assert _steps(world) == BOOTSTRAP
    assert world.events[-1] == "client.aclose" and world.stopped == [] and world.destroyed == []


async def test_every_attempt_gets_its_own_name(world: World, sandbox: VercelSandbox) -> None:
    first = await sandbox.acreate("s", agent_id="coder")
    await sandbox.adestroy(first)
    second = await sandbox.acreate("s", agent_id="coder")
    assert first.provider_ref != second.provider_ref
    assert first.provider_ref.rsplit("-", 1)[0] == second.provider_ref.rsplit("-", 1)[0]


async def test_the_bootstrap_installs_the_pinned_natives_into_a_venv_the_agent_can_read(
    world: World, sandbox: VercelSandbox
) -> None:
    await sandbox.acreate("s", agent_id="coder")
    by_step = {World.label(call): call for call in world.root_commands}
    assert all(call["sudo"] for call in world.root_commands)
    venv = ["uv", "venv", "--python", vercel_sandbox.GUEST_PYTHON, "/opt/agno/venv"]
    assert by_step["uv venv"]["command"] == "env" and by_step["uv venv"]["args"][-5:] == venv
    install = by_step["uv pip"]["args"]
    assert install[install.index("pip") :][:4] == ["pip", "install", "--python", guard.PYTHON]
    assert (
        tuple(install[-3:]) == vercel_sandbox.NATIVE_PINS and install[-4] == f"agno[claude,codex]=={agno.__version__}"
    )
    variables = [a for a in by_step["uv venv"]["args"] if "=" in a]
    assert "UV_PYTHON_INSTALL_DIR=/opt/agno/python" in variables and "HOME=/root" in variables
    assert by_step["chmod"]["args"][:2] == ["-R", "go+rX"]
    assert all(call["kill_after"] is not None for call in world.root_commands)


async def test_the_wheel_route_uploads_the_wheel_and_installs_it(world: World, tmp_path: Path) -> None:
    wheel = tmp_path / "agno-3.1.5-py3-none-any.whl"
    wheel.write_bytes(b"wheel bytes")
    await VercelSandbox(wheel=wheel).acreate("s", agent_id="coder")
    [(path, data, mode)] = [w for w in world.writes if w[0].endswith(".whl")]
    assert path == "/tmp/agno-bootstrap/agno-3.1.5-py3-none-any.whl" and data == b"wheel bytes" and mode == 0o644
    install = next(c["args"] for c in world.root_commands if World.label(c) == "uv pip")
    assert f"{path}[claude,codex]" in install and not any(a.startswith("agno[") for a in install)


@pytest.mark.parametrize("wheel", ["missing.whl", "notawheel.txt"])
async def test_a_wheel_that_cannot_be_used_is_refused_before_anything_is_created(
    world: World, tmp_path: Path, wheel: str
) -> None:
    (tmp_path / "notawheel.txt").write_bytes(b"x")
    with pytest.raises(ValueError, match="wheel"):
        VercelSandbox(wheel=tmp_path / wheel).create("s")
    assert world.creates == [] and world.events == []


async def test_a_source_that_differs_from_the_hosts_is_refused_and_cleaned_up(
    world: World, sandbox: VercelSandbox
) -> None:
    world.guest_digest = "e" * 64
    with pytest.raises(SandboxError, match="wheel"):
        await sandbox.acreate("s", agent_id="coder")
    assert "finish" not in _steps(world)
    [name] = world.destroyed
    assert world.stopped == ["sess-new-1"] and name not in world.sandboxes


async def test_the_environment_reaches_only_the_guards_staged_request(world: World, sandbox: VercelSandbox) -> None:
    secret = "sk-very-secret-value"
    await sandbox.acreate("s", agent_id="coder", env={"MODEL_KEY": secret})
    assert world.finished[0]["env"] == {"MODEL_KEY": secret}
    assert world.finished[0]["marker"]["config_digest"] == sandbox._digest("s", "coder", 1, {"MODEL_KEY": secret})
    assert secret not in json.dumps(world.runs) and secret not in json.dumps(world.creates, default=str)
    assert f"{guard.INBOX}" not in "".join(world.files)  # the staged request was consumed
    [(path, _, mode)] = [w for w in world.writes if "bootstrap" not in w[0] and w[0].endswith(".json")]
    assert mode == 0o600


async def test_the_marker_is_written_last_and_names_what_was_installed(world: World, sandbox: VercelSandbox) -> None:
    await sandbox.acreate("s", agent_id="coder")
    marker = world.finished[0]["marker"]
    assert marker["source_digest"] == HOST_DIGEST and marker["guest_python"] == vercel_sandbox.GUEST_PYTHON
    assert marker["pins"] == list(vercel_sandbox.NATIVE_PINS) and marker["route"] == "release"
    assert _steps(world)[-1] == "finish"


async def test_a_computer_that_does_not_report_ready_after_its_bootstrap_is_removed(
    world: World, sandbox: VercelSandbox
) -> None:
    world.finish_marker = {"config_digest": "a marker for somebody else's configuration"}
    with pytest.raises(SandboxError, match="did not report ready"):
        await sandbox.acreate("s", agent_id="coder")
    assert world.stopped == ["sess-new-1"] and len(world.destroyed) == 1


@pytest.mark.parametrize("step", ["uv --version", "mkdir", "uv venv", "uv pip", "chmod", "digest", "install", "finish"])
async def test_a_bootstrap_failure_stops_the_exact_session_deletes_the_box_and_is_not_retried(
    world: World, sandbox: VercelSandbox, step: str
) -> None:
    world.fail_steps[step] = 3
    with pytest.raises(SandboxError, match="bootstrap"):
        await sandbox.acreate("s", agent_id="coder")
    assert len(world.creates) == 1 and world.stopped == ["sess-new-1"] and len(world.destroyed) == 1
    assert world.destroyed[0] == world.creates[0]["name"] and not world.sandboxes.get(world.creates[0]["name"])
    assert _steps(world).count(step) == 1  # nothing was retried
    assert world.events.count("client.create") == world.events.count("client.aclose")


async def test_a_failed_bootstrap_that_cannot_be_cleaned_up_still_reports_not_ready(
    world: World, sandbox: VercelSandbox
) -> None:
    world.fail_steps["uv pip"] = 1
    world.fail["destroy"] = FakeApiError(500)
    with pytest.raises(SandboxError, match="could not be removed"):
        await sandbox.acreate("s", agent_id="coder")
    name = world.creates[0]["name"]
    found = await sandbox.afind("s", agent_id="coder")
    assert found is not None and found.provider_ref == name and found.state == "exited"


async def test_a_cancelled_create_cleans_up_then_propagates(world: World, sandbox: VercelSandbox) -> None:
    started = asyncio.Event()

    async def hang(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        started.set()
        await asyncio.sleep(30)
        return 0

    world.script = hang
    task = asyncio.create_task(sandbox.acreate("s", agent_id="coder"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert world.stopped == ["sess-new-1"] and len(world.destroyed) == 1


async def test_a_rejected_create_is_an_error_and_is_never_retried(world: World, sandbox: VercelSandbox) -> None:
    world.fail["create"] = FakeApiError(400)
    with pytest.raises(SandboxError, match="Could not create"):
        await sandbox.acreate("s", agent_id="coder")
    assert len(world.creates) == 1 and world.stopped == [] and world.destroyed == []


async def test_a_lost_create_reply_is_recovered_by_finding_the_box_and_destroying_it(
    world: World, sandbox: VercelSandbox
) -> None:
    world.fail["create_reply"] = ConnectionError("reply lost")
    with pytest.raises(SandboxError, match="Could not create"):
        await sandbox.acreate("s", agent_id="coder")
    assert len(world.creates) == 1 and world.destroyed == []
    del world.fail["create_reply"]
    found = await sandbox.afind("s", agent_id="coder")
    assert found is not None and found.state == "created"  # running, never bootstrapped
    await sandbox.adestroy(found)
    assert found.provider_ref in world.destroyed and found.provider_ref not in world.sandboxes
    replacement = await sandbox.acreate("s", agent_id="coder")
    assert replacement.provider_ref != found.provider_ref and len(world.creates) == 2


async def test_create_adopts_exactly_one_usable_computer_of_the_same_configuration(
    world: World, sandbox: VercelSandbox
) -> None:
    name = _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa"
    _add(world, name, digest=_digest_for(sandbox))
    handle = await sandbox.acreate("s", agent_id="coder")
    assert handle.provider_ref == name and handle.state == "running" and world.creates == []


async def test_create_refuses_two_usable_computers_and_deletes_neither(world: World, sandbox: VercelSandbox) -> None:
    prefix = _prefix("default", "coder", "s", 1)
    _add(world, f"{prefix}-aaaaaaaaaaaa", digest=_digest_for(sandbox))
    _add(world, f"{prefix}-bbbbbbbbbbbb", digest=_digest_for(sandbox))
    with pytest.raises(SandboxError, match="more than one"):
        await sandbox.acreate("s", agent_id="coder")
    assert world.creates == [] and world.destroyed == [] and world.stopped == []


async def test_an_incomplete_sibling_is_neither_adopted_nor_deleted(world: World, sandbox: VercelSandbox) -> None:
    name = _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa"
    _add(world, name, digest=_digest_for(sandbox), ready=None)
    handle = await sandbox.acreate("s", agent_id="coder")
    assert handle.provider_ref != name and name in world.sandboxes and len(world.creates) == 1
    assert world.destroyed == [] and world.stopped == []


async def test_a_sibling_of_another_configuration_is_left_alone(world: World, sandbox: VercelSandbox) -> None:
    name = _prefix("default", "coder", "s", 1) + "-aaaaaaaaaaaa"
    _add(world, name, digest="another configuration")
    handle = await sandbox.acreate("s", agent_id="coder")
    assert handle.provider_ref != name and name in world.sandboxes and world.destroyed == []


async def test_the_resources_follow_the_requested_vcpus(world: World) -> None:
    await VercelSandbox(vcpus=4).acreate("s")
    assert (world.creates[0]["resources"].vcpus, world.creates[0]["resources"].memory) == (4, 8192)


def test_the_configuration_digest_covers_everything_a_created_computer_depends_on() -> None:
    base = VercelSandbox()._digest("s", "coder", 1, {})
    assert base == VercelSandbox()._digest("s", "coder", 1, {})
    changed = {
        VercelSandbox(vcpus=2)._digest("s", "coder", 1, {}),
        VercelSandbox(lifetime=600)._digest("s", "coder", 1, {}),
        VercelSandbox()._digest("s", "coder", 2, {}),
        VercelSandbox()._digest("s", None, 1, {}),
        VercelSandbox()._digest("t", "coder", 1, {}),
        VercelSandbox()._digest("s", "coder", 1, {"A": "b"}),
    }
    assert base not in changed and len(changed) == 6


async def test_a_guard_reply_larger_than_a_marker_is_read_whole(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    big = json.dumps({"state": {"note": "x" * 300_000}})

    async def reply(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        stdout.write(big)
        return 0

    world.script = reply
    assert (await sandbox._guard_call(handle, "restore", "a" * 32, timeout=5))["state"]["note"] == "x" * 300_000


async def test_a_box_the_service_created_without_a_session_is_removed_not_stranded(
    world: World, sandbox: VercelSandbox
) -> None:
    world.created_without_session = True
    with pytest.raises(SandboxError, match="no running session"):
        await sandbox.acreate("s", agent_id="coder")
    assert len(world.destroyed) == 1 and world.destroyed[0] not in world.sandboxes


async def _created(world: World, sandbox: VercelSandbox) -> SandboxHandle:
    handle = await sandbox.acreate("s", agent_id="coder")
    world.stopped.clear()
    world.events.clear()
    return handle


async def test_destroy_stops_the_exact_session_then_deletes_the_boxs_own_name(
    world: World, sandbox: VercelSandbox
) -> None:
    handle = await _created(world, sandbox)
    await sandbox.adestroy(handle)
    assert world.stopped == ["sess-new-1"] and world.destroyed == [handle.provider_ref]
    assert handle.provider_ref not in world.sandboxes
    assert world.events.index("session.stop") < world.events.index("sandbox.destroy")
    assert world.events.count("client.create") == world.events.count("client.aclose") == 1


async def test_destroy_is_idempotent(world: World, sandbox: VercelSandbox) -> None:
    handle = await _created(world, sandbox)
    await sandbox.adestroy(handle)
    await sandbox.adestroy(handle)
    assert world.destroyed == [handle.provider_ref]
    assert await sandbox.aget(handle.provider_ref) is None


async def test_destroy_of_an_already_stopped_box_still_deletes_it(world: World, sandbox: VercelSandbox) -> None:
    handle = await _created(world, sandbox)
    world.sandboxes[handle.provider_ref].current_session.status = "stopped"  # type: ignore[union-attr]
    await sandbox.adestroy(handle)
    assert world.stopped == [] and world.destroyed == [handle.provider_ref]


async def test_destroy_never_touches_a_box_that_is_no_longer_this_handles(world: World, sandbox: VercelSandbox) -> None:
    handle = await _created(world, sandbox)
    world.sandboxes[handle.provider_ref].tags["agno_session"] = "somebody-elses"  # type: ignore[index]
    with pytest.raises(SandboxError, match="no longer belongs"):
        await sandbox.adestroy(handle)
    assert world.stopped == [] and world.destroyed == [] and handle.provider_ref in world.sandboxes


async def test_destroy_with_a_stale_session_does_not_stop_or_delete_the_current_one(
    world: World, sandbox: VercelSandbox
) -> None:
    handle = await _created(world, sandbox)
    stale = SandboxHandle(**{**handle.__dict__, "name": f"{handle.provider_ref}/an-older-session"})
    with pytest.raises(SandboxError, match="no longer belongs"):
        await sandbox.adestroy(stale)
    assert world.stopped == [] and world.destroyed == []


async def test_destroy_reports_a_stop_that_failed_and_does_not_delete(world: World, sandbox: VercelSandbox) -> None:
    handle = await _created(world, sandbox)
    world.fail["stop"] = FakeApiError(500)
    with pytest.raises(SandboxError):
        await sandbox.adestroy(handle)
    assert world.destroyed == []


async def test_destroy_reports_a_delete_that_failed(world: World, sandbox: VercelSandbox) -> None:
    handle = await _created(world, sandbox)
    world.fail["destroy"] = FakeApiError(500)
    with pytest.raises(SandboxError, match="delete"):
        await sandbox.adestroy(handle)
    assert handle.provider_ref in world.sandboxes


async def test_a_box_deleted_between_the_read_and_the_delete_is_gone(world: World, sandbox: VercelSandbox) -> None:
    handle = await _created(world, sandbox)
    box = world.sandboxes[handle.provider_ref]
    original = box.destroy

    async def already_gone(**kwargs: Any) -> Any:
        world.sandboxes.pop(handle.provider_ref)
        raise FakeApiError(404)

    box.destroy = already_gone  # type: ignore[method-assign]
    await sandbox.adestroy(handle)
    box.destroy = original  # type: ignore[method-assign]


def test_the_provider_addresses_boxes_by_exact_name_and_session_and_never_resumes_or_forks() -> None:
    source = inspect.getsource(vercel_sandbox)
    for forbidden in ("resume_sandbox", "get_or_create_sandbox", "fork_sandbox", "update_network_policy"):
        assert forbidden not in source
    # A box is removed in one place, after the exact session was stopped and ownership was read again.
    assert source.count(".destroy(") == 1 and "stop_quietly" in source


NAME = "a" * 32


@pytest.fixture
def guest(tmp_path: Path) -> Dict[str, Any]:
    inbox = tmp_path / "inbox"
    inbox.mkdir(mode=0o700)
    ready = tmp_path / "READY"
    ready.write_text(json.dumps({"config_digest": "cfg"}))
    ready.chmod(0o644)
    request = inbox / f"{NAME}.json"
    request.write_bytes(b'{"argv": ["true"]}')
    request.chmod(0o600)
    return dict(inbox=inbox, ready=ready, request=request, trusted_uid=os.getuid(), staged_uid=os.getuid())


def _run(guest: Dict[str, Any], spawn: Optional[Callable[..., int]] = None, name: str = NAME) -> int:
    seen: Dict[str, Any] = {}

    def record(descriptor: int, environment: Dict[str, str]) -> int:
        seen["body"] = os.read(descriptor, 100)
        seen["gone"] = not guest["request"].exists()
        seen["environment"] = environment
        return 0

    status = guard.run_exec(
        name,
        inbox=guest["inbox"],
        ready=guest["ready"],
        trusted_uid=guest["trusted_uid"],
        staged_uid=guest["staged_uid"],
        spawn=spawn or record,
    )
    guest["seen"] = seen
    return status


def test_the_guard_hands_the_request_to_the_runner_and_deletes_it_first(guest: Dict[str, Any]) -> None:
    assert _run(guest) == 0
    assert guest["seen"]["body"] == b'{"argv": ["true"]}' and guest["seen"]["gone"] is True
    assert not guest["request"].exists()


def test_the_guards_environment_is_a_small_base_not_the_sudo_environment(
    guest: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUDO_USER", "x")
    monkeypatch.setenv("SECRET_FROM_THE_BOX", "1")
    monkeypatch.setenv("LANG", "C.UTF-8")
    # The permitted locale variables are forwarded when present, so the invoking shell must not decide this result.
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("TZ", raising=False)
    _run(guest)
    environment = guest["seen"]["environment"]
    assert set(environment) == {"LANG", "HOME", "PATH"} and environment["HOME"] == guard.HOME
    assert environment["PATH"].startswith(os.path.dirname(guard.PYTHON) + ":")


def test_the_guard_forwards_only_the_permitted_locale_variables(
    guest: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUDO_USER", "x")
    monkeypatch.setenv("SECRET_FROM_THE_BOX", "1")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("LC_MESSAGES", "not-permitted")
    _run(guest)
    environment = guest["seen"]["environment"]
    assert set(environment) == {"LANG", "LC_ALL", "TZ", "HOME", "PATH"}
    assert (environment["LANG"], environment["LC_ALL"], environment["TZ"]) == ("C.UTF-8", "C.UTF-8", "UTC")


@pytest.mark.parametrize("name", ["", "a" * 31, "a" * 33, "A" * 32, "../" + "a" * 29, "a" * 31 + "/", "a" * 32 + "\n"])
def test_the_guard_refuses_a_malformed_request_name(
    guest: Dict[str, Any], name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(guest, name=name) == guard.REFUSED
    assert capsys.readouterr().err.startswith(guard.REFUSAL_PREFIX)


def test_the_guard_refuses_an_unready_guest_and_removes_the_request(
    guest: Dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    guest["ready"].unlink()
    assert _run(guest) == guard.REFUSED and "not ready" in capsys.readouterr().err
    assert not guest["request"].exists() and "seen" in guest and guest["seen"] == {}


@pytest.mark.parametrize("how", ["writable", "foreign", "directory", "symlink"])
def test_the_guard_only_trusts_a_marker_only_root_could_have_written(guest: Dict[str, Any], how: str) -> None:
    ready: Path = guest["ready"]
    if how == "writable":
        ready.chmod(0o666)
    elif how == "foreign":
        guest["trusted_uid"] = os.getuid() + 1
    elif how == "directory":
        ready.unlink()
        ready.mkdir()
    else:
        target = ready.with_name("elsewhere")
        target.write_text("{}")
        ready.unlink()
        ready.symlink_to(target)
    assert _run(guest) == guard.REFUSED and guest["seen"] == {}


def test_the_guard_refuses_a_request_somebody_else_owns(guest: Dict[str, Any]) -> None:
    guest["staged_uid"] = os.getuid() + 1
    assert _run(guest) == guard.REFUSED and guest["seen"] == {}
    assert not guest["request"].exists()


def test_the_guard_refuses_a_request_the_agent_could_have_written(
    guest: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guard, "AGENT_UID", os.getuid())
    assert _run(guest) == guard.REFUSED and guest["seen"] == {}


def test_the_guard_refuses_a_request_others_can_read(guest: Dict[str, Any]) -> None:
    guest["request"].chmod(0o644)
    assert _run(guest) == guard.REFUSED and guest["seen"] == {}


@pytest.mark.parametrize("how", ["missing", "symlink", "fifo", "hardlink", "oversize", "directory"])
def test_the_guard_refuses_what_is_not_one_regular_staged_file(
    guest: Dict[str, Any], how: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    request: Path = guest["request"]
    if how == "missing":
        request.unlink()
    elif how == "symlink":
        target = request.with_name("elsewhere")
        target.write_bytes(b"{}")
        target.chmod(0o600)
        request.unlink()
        request.symlink_to(target)
    elif how == "fifo":
        request.unlink()
        os.mkfifo(request, 0o600)
    elif how == "hardlink":
        os.link(request, request.with_name("alias"))
    elif how == "oversize":
        monkeypatch.setattr(guard, "MAX_STAGED", 4)
    else:
        request.unlink()
        request.mkdir()
    assert _run(guest) == guard.REFUSED and guest["seen"] == {}


def test_a_request_is_never_run_twice(guest: Dict[str, Any]) -> None:
    assert _run(guest) == 0
    assert _run(guest) == guard.REFUSED


@pytest.mark.parametrize("code,status", [(0, 0), (3, 3), (guard.REFUSED, 1), (-9, 137), (-15, 143)])
def test_only_the_guard_can_exit_with_the_refusal_status(guest: Dict[str, Any], code: int, status: int) -> None:
    assert _run(guest, spawn=lambda descriptor, environment: code) == status


def test_the_runner_launch_drops_privileges_and_reads_the_request_from_the_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: Dict[str, Any] = {}

    def fake_run(argv: List[str], **kwargs: Any) -> Any:
        calls.update(argv=argv, **kwargs)
        return subprocess.CompletedProcess(argv, 5)

    monkeypatch.setattr(guard.subprocess, "run", fake_run)
    monkeypatch.setattr(guard, "_no_new_privileges", lambda: calls.setdefault("nnp", True))
    assert guard._spawn(7, {"A": "b"}) == 5
    assert calls["argv"] == [guard.PYTHON, "-I", "-m", "agno.sandbox._exec"]
    assert calls["nnp"] is True and calls["stdin"] == 7 and calls["env"] == {"A": "b"}
    assert (calls["user"], calls["group"], calls["extra_groups"], calls["cwd"]) == (
        guard.AGENT_UID,
        guard.AGENT_GID,
        [],
        guard.WORKSPACE,
    )


def test_ready_prints_the_marker_only_for_a_trusted_one(
    guest: Dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert guard.run_ready(ready=guest["ready"], trusted_uid=guest["trusted_uid"]) == 0
    assert json.loads(capsys.readouterr().out) == {"config_digest": "cfg"}
    guest["ready"].chmod(0o666)
    assert guard.run_ready(ready=guest["ready"], trusted_uid=guest["trusted_uid"]) == guard.REFUSED
    assert capsys.readouterr().out == ""


def test_the_guard_command_line() -> None:
    assert guard.main(["guard"]) == 2
    assert guard.main(["guard", "exec"]) == 2
    assert guard.main(["guard", "launch", NAME]) == 2


def test_the_guard_imports_only_the_standard_library_at_module_level() -> None:
    import ast

    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib is None:
        pytest.skip("needs Python 3.10+")
    tree = ast.parse(Path(guard.__file__).read_text())

    def names(node: ast.AST) -> set:
        if isinstance(node, ast.Import):
            return {alias.name.split(".")[0] for alias in node.names}
        return {(node.module or "").split(".")[0]} if isinstance(node, ast.ImportFrom) else set()

    top = set().union(*(names(node) for node in tree.body))
    lazy = set().union(
        *(names(inner) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) for inner in ast.walk(node))
    )
    assert top and top <= set(stdlib)
    # Inside functions only the shared package, which the guest's own interpreter has installed.
    assert lazy <= set(stdlib) | {"agno"}


class FakeOps:
    """The agent's processes as a table: SIGSTOP and SIGCONT change the state the guard then observes."""

    def __init__(self) -> None:
        self.procs: Dict[int, Dict[str, Any]] = {}
        self.sent: List[Any] = []
        self.refuse_stop: set = set()
        self.unsupported = False
        self.on_select: Optional[Callable[[], None]] = None
        self.reuse_before_signal: Optional[int] = None
        # A SIGSTOP the kernel accepted whose effect has not happened yet (a process in uninterruptible sleep).
        self.delay_stop: set = set()
        self.pending_stop: set = set()
        self.unsupported_signals: set = set()  # signals whose pidfd cannot be opened right now (EMFILE, say)

    def add(self, pid: int, state: str = "S", uid: Optional[int] = None) -> None:
        self.procs[pid] = {"state": state, "start": f"{pid}0", "uid": os.getuid() if uid is None else uid}

    def identity(self, pid: int) -> Optional[str]:
        proc = self.procs.get(pid)
        return None if proc is None else f"boot:{proc['start']}"

    def state(self, pid: int) -> str:
        proc = self.procs.get(pid)
        return "" if proc is None else str(proc["state"])

    def ancestors(self, pid: int) -> List[int]:
        return [pid]

    def select(self, uid: int, exclude: set) -> List[int]:
        if self.on_select is not None:
            self.on_select()
        return sorted(p for p, v in self.procs.items() if v["uid"] == uid and p not in exclude)

    def signal(self, pid: int, ident: str, sig: int) -> bool:
        if self.unsupported or sig in self.unsupported_signals:
            raise guard.Unsupported("no pidfd")
        if pid == self.reuse_before_signal:
            self.procs[pid]["start"] = "reused"  # the pid now belongs to a different process
            self.reuse_before_signal = None
        proc = self.procs.get(pid)
        if proc is None or self.identity(pid) != ident:
            return False
        self.sent.append((pid, sig))
        if sig == signal.SIGSTOP and pid not in self.refuse_stop:
            if pid in self.delay_stop:
                self.pending_stop.add(pid)  # accepted and queued; the process stops only when it gets to run
            else:
                proc["state"] = "T"
        if sig == signal.SIGCONT:
            # Generating SIGCONT discards the stop signals still pending, stopped or not (as the kernel does).
            self.pending_stop.discard(pid)
            if proc["state"] == "T":
                proc["state"] = "S"
        return True

    def settle(self) -> None:
        """Let every queued stop take effect, as it does once the process is back in user space."""
        for pid in sorted(self.pending_stop):
            if pid in self.procs:
                self.procs[pid]["state"] = "T"
        self.pending_stop.clear()


@pytest.fixture
def box(tmp_path: Path) -> Dict[str, Any]:
    layout = guard.Layout(
        control=tmp_path / "opt/control",
        inbox=tmp_path / "opt/inbox",
        export=tmp_path / "opt/export",
        stage=tmp_path / "opt/stage",
        ready=tmp_path / "opt/READY",
        env_file=tmp_path / "opt/ENV",
        workspace=tmp_path / "workspace",
        runtime=tmp_path / "runtime",
        agent_uid=os.getuid(),
        agent_gid=os.getgid(),
        staged_uid=os.getuid(),
        trusted_uid=os.getuid(),
    )
    layout.inbox.mkdir(parents=True, mode=0o700)
    layout.export.mkdir(mode=0o700)
    layout.workspace.mkdir()
    layout.native.mkdir(parents=True)
    ops = FakeOps()
    return {"layout": layout, "ops": ops, "guard": guard.Guard(layout, ops=ops, admission_wait=0.2, idle_wait=0.0)}


CHECKPOINT_NAME = "c" * 32
JOB: Dict[str, Any] = {
    "state": {"binding": "b1"},
    "exclude": list(DEFAULT_NATIVE_EXCLUSIONS),
    "limits": asdict(CheckpointLimits()),
}


def _archiver(layout: guard.Layout, *, compress: bool = True) -> Callable[[int, Any], None]:
    """What the dropped archive child does, without the drop: the shared capture, written to the descriptor."""

    def run(descriptor: int, job: Any) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "checkpoint.tar"
            CheckpointArchive(CheckpointLimits(**job["limits"]), compress=compress).capture(
                layout.roots, output, state=job["state"], exclude=job["exclude"]
            )
            os.write(descriptor, output.read_bytes())

    return run


def _fill(layout: guard.Layout) -> None:
    (layout.workspace / "notes.txt").write_text("hello")
    (layout.workspace / "deep").mkdir()
    (layout.workspace / "deep" / "b.txt").write_text("b")
    (layout.native / "session.json").write_text("{}")
    (layout.native / "codex").mkdir()
    (layout.native / "codex" / "auth.json").write_text("secret")


def _ready(layout: guard.Layout) -> None:
    layout.ready.write_text(json.dumps({"config_digest": "cfg"}))
    layout.ready.chmod(0o644)


def _force_state(g: guard.Guard, value: str) -> None:
    with g._admission():
        g._write_state(value)


def test_the_source_digest_covers_python_source_and_nothing_else(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    for root in (first, second):
        (root / "pkg").mkdir(parents=True)
        (root / "pkg" / "m.py").write_text("x = 1\n")
    (second / "pkg" / "__pycache__").mkdir()
    (second / "pkg" / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"\0")
    (second / "data.json").write_text("{}")
    assert guard.source_digest(first) == guard.source_digest(second)
    (second / "pkg" / "m.py").write_text("x = 2\n")
    assert guard.source_digest(first) != guard.source_digest(second)
    (second / "pkg" / "m.py").write_text("x = 1\n")
    (second / "pkg" / "n.py").write_text("")
    assert guard.source_digest(first) != guard.source_digest(second)
    (first / "pkg" / "n.py").write_text("")
    assert guard.source_digest(first) == guard.source_digest(second)
    (first / "pkg" / "n.py").rename(first / "pkg" / "o.py")
    assert guard.source_digest(first) != guard.source_digest(second)


def test_the_host_and_the_guest_hash_the_same_installed_package() -> None:
    import agno

    digest = guard.source_digest(Path(agno.__file__).parent)
    assert len(digest) == 64 and digest == guard.source_digest(Path(agno.__file__).parent)


def test_the_agents_environment_is_the_installed_file_over_a_small_base(box: Dict[str, Any]) -> None:
    layout = box["layout"]
    assert guard._read_environment(layout) == {}
    layout.env_file.write_text(json.dumps({"OPENAI_API_KEY": "k", "PATH": "/evil", "HOME": "/evil", "X": "1"}))
    layout.env_file.chmod(0o600)
    extra = guard._read_environment(layout)
    assert extra == {"OPENAI_API_KEY": "k", "X": "1"}
    environment = guard._child_environment({"LANG": "C", "SUDO_USER": "u", "OTHER": "o"}, extra)
    assert environment["OPENAI_API_KEY"] == "k" and environment["LANG"] == "C" and "OTHER" not in environment
    assert environment["HOME"] == guard.HOME and environment["PATH"].startswith(os.path.dirname(guard.PYTHON))


@pytest.mark.parametrize("damage", ["writable", "malformed", "not-strings", "link"])
def test_an_untrustworthy_environment_file_refuses_the_command(box: Dict[str, Any], damage: str) -> None:
    layout = box["layout"]
    _ready(layout)
    layout.env_file.write_text(json.dumps({"A": "b"}))
    layout.env_file.chmod(0o600)
    if damage == "writable":
        layout.env_file.chmod(0o666)
    elif damage == "malformed":
        layout.env_file.write_text("{")
    elif damage == "not-strings":
        layout.env_file.write_text(json.dumps({"A": 1}))
    else:
        layout.env_file.unlink()
        layout.env_file.symlink_to(layout.ready)
    request = layout.inbox / f"{NAME}.json"
    request.write_bytes(b"{}")
    request.chmod(0o600)
    ran: List[int] = []
    status = guard.run_exec(
        NAME,
        inbox=layout.inbox,
        ready=layout.ready,
        trusted_uid=layout.trusted_uid,
        staged_uid=layout.staged_uid,
        spawn=lambda descriptor, environment: ran.append(1) or 0,
        guard=box["guard"],
    )
    assert status == guard.REFUSED and ran == [] and not request.exists()


def _exec(box: Dict[str, Any], spawn: Callable[[int, Dict[str, str]], int]) -> int:
    layout = box["layout"]
    _ready(layout)
    request = layout.inbox / f"{NAME}.json"
    request.write_bytes(b"{}")
    request.chmod(0o600)
    return guard.run_exec(
        NAME,
        inbox=layout.inbox,
        ready=layout.ready,
        trusted_uid=layout.trusted_uid,
        staged_uid=layout.staged_uid,
        spawn=spawn,
        guard=box["guard"],
    )


def test_a_command_gets_the_installed_environment_and_marks_the_computer_used(box: Dict[str, Any]) -> None:
    box["layout"].env_file.write_text(json.dumps({"MODEL_KEY": "k"}))
    box["layout"].env_file.chmod(0o600)
    seen: Dict[str, Any] = {}
    assert box["guard"].state() == "fresh"
    status = _exec(box, lambda descriptor, environment: seen.update(environment=environment) or 0)
    assert status == 0 and seen["environment"]["MODEL_KEY"] == "k" and box["guard"].state() == "used"


@pytest.mark.parametrize("state", ["restoring", "failed"])
def test_a_command_is_refused_on_a_computer_that_is_restoring_or_failed(box: Dict[str, Any], state: str) -> None:
    _force_state(box["guard"], state)
    ran: List[int] = []
    assert _exec(box, lambda descriptor, environment: ran.append(1) or 0) == guard.REFUSED and ran == []


def test_concurrent_first_commands_are_all_admitted_and_publish_one_consistent_state(box: Dict[str, Any]) -> None:
    import threading

    layout, admitted, failures = box["layout"], [], []

    def command() -> None:
        try:
            with guard.Guard(layout, ops=box["ops"], admission_wait=10.0).admit():
                admitted.append(1)
                time.sleep(0.05)
        except BaseException as error:  # the assertion below reports it
            failures.append(error)

    threads = [threading.Thread(target=command) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == [] and len(admitted) == 8
    assert guard.Guard(layout).state() == "used" and not list(layout.control.glob("state.json.*.tmp"))


def test_a_state_write_that_dies_before_publishing_leaves_the_computer_fresh_and_is_cleaned_up(
    box: Dict[str, Any],
) -> None:
    layout = box["layout"]

    def die(point: str) -> None:
        if point == "state_before_replace":
            raise RuntimeError("died before the replace")

    dying = guard.Guard(layout, ops=box["ops"], hook=die)
    with pytest.raises(RuntimeError, match="died"):
        with dying.admit():
            pass
    assert list(layout.control.glob("state.json.*.tmp")) and guard.Guard(layout).state() == "fresh"
    with guard.Guard(layout, ops=box["ops"]).admit():
        pass
    assert guard.Guard(layout).state() == "used" and not list(layout.control.glob("state.json.*.tmp"))


def test_a_capture_cannot_start_while_a_command_runs(box: Dict[str, Any]) -> None:
    outcome: Dict[str, Any] = {}

    def command(descriptor: int, environment: Dict[str, str]) -> int:
        with pytest.raises(guard.Refused) as refused:
            box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(box["layout"]))
        with pytest.raises(guard.Refused) as restoring:
            box["guard"].restore(CHECKPOINT_NAME, {"limits": JOB["limits"]}, extract=lambda a, d: {})
        outcome.update(capture=refused.value.code, restore=restoring.value.code)
        return 0

    assert _exec(box, command) == 0
    assert outcome == {"capture": "busy", "restore": "busy"}
    assert box["ops"].sent == []


def test_a_command_cannot_start_while_a_capture_holds_the_computer(box: Dict[str, Any]) -> None:
    outcome: Dict[str, Any] = {}

    def archive(descriptor: int, job: Any) -> None:
        outcome["status"] = _exec(box, lambda d, e: 0)
        _archiver(box["layout"])(descriptor, job)

    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=archive)
    assert outcome["status"] == guard.REFUSED


def test_a_runner_still_running_is_not_hidden_by_a_completed_check(box: Dict[str, Any]) -> None:
    # The refusal status belongs to the guard alone: a runner exiting 75 reads as 1.
    assert _exec(box, lambda descriptor, environment: guard.REFUSED) == 1


def test_capture_stops_the_agents_processes_for_the_archive_and_resumes_the_ones_it_stopped(
    box: Dict[str, Any],
) -> None:
    layout, ops = box["layout"], box["ops"]
    _fill(layout)
    ops.add(101)
    ops.add(102, state="T")  # stopped by someone else before the capture
    seen: Dict[str, Any] = {}

    def archive(descriptor: int, job: Any) -> None:
        seen["states"] = {pid: ops.state(pid) for pid in (101, 102)}
        _archiver(layout)(descriptor, job)

    size = box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=archive)
    target = layout.export / f"{CHECKPOINT_NAME}.tar"
    assert seen["states"] == {101: "T", 102: "T"}
    assert (
        ops.state(101) == "S" and ops.state(102) == "T" and ops.sent == [(101, signal.SIGSTOP), (101, signal.SIGCONT)]
    )
    assert target.stat().st_size == size and stat.S_IMODE(target.stat().st_mode) == 0o600
    assert CheckpointArchive().validate(target) == JOB["state"]
    assert not (layout.control / "freeze.journal").exists()


def test_capture_archives_the_roots_as_they_were_and_leaves_out_the_exclusions(
    box: Dict[str, Any], tmp_path: Path
) -> None:
    layout = box["layout"]
    _fill(layout)
    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    restored = tmp_path / "restored"
    CheckpointArchive().restore(layout.export / f"{CHECKPOINT_NAME}.tar", restored)
    assert (restored / "workspace/notes.txt").read_text() == "hello"
    assert (restored / "workspace/deep/b.txt").read_text() == "b"
    assert (restored / "native/session.json").exists() and not (restored / "native/codex/auth.json").exists()


def test_capture_is_refused_while_a_runtime_turn_is_in_flight_and_nothing_is_stopped(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    job = layout.runtime / "jobs" / "abc"
    job.mkdir(parents=True)
    (job / "request.json").write_text("{}")
    with pytest.raises(guard.Refused) as refused:
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert refused.value.code == "active-execution" and ops.sent == [] and not list(layout.export.iterdir())
    (job / "result.json").write_text("{}")
    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))


def test_capture_is_refused_while_the_runtimes_execution_lock_is_held(box: Dict[str, Any]) -> None:
    import fcntl

    layout = box["layout"]
    with (layout.runtime / "execution.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(guard.Refused) as refused:
            box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert refused.value.code == "active-execution"


def test_a_turn_that_is_still_winding_down_is_waited_for_a_moment_before_capture_refuses(
    box: Dict[str, Any],
) -> None:
    import threading

    layout, ops = box["layout"], box["ops"]
    _fill(layout)
    ops.add(101)
    job = layout.runtime / "jobs" / "abc"
    job.mkdir(parents=True)
    (job / "request.json").write_text("{}")  # the result is written a moment later
    threading.Timer(0.3, lambda: (job / "result.json").write_text("{}")).start()
    waiting = guard.Guard(layout, ops=ops, admission_wait=0.2, idle_wait=3.0)
    waiting.capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert ops.sent == [(101, signal.SIGSTOP), (101, signal.SIGCONT)]
    # The wait is bounded: a turn that never finishes is still refused.
    (job / "result.json").unlink()
    with pytest.raises(guard.Refused) as refused:
        guard.Guard(layout, ops=ops, admission_wait=0.2, idle_wait=0.3).capture(
            CHECKPOINT_NAME, JOB, run_archive=_archiver(layout)
        )
    assert refused.value.code == "active-execution"


def _job(layout: guard.Layout, status: Optional[Dict[str, Any]]) -> Path:
    job = layout.runtime / "jobs" / "abc"
    job.mkdir(parents=True)
    (job / "request.json").write_text("{}")
    if status is not None:
        (job / "status.json").write_text(json.dumps(status))
    return job


def test_a_worker_that_died_without_a_result_does_not_block_capture_forever(box: Dict[str, Any]) -> None:
    layout = box["layout"]
    _fill(layout)
    _job(layout, {"phase": "running", "pid": 4242, "start": "999"})  # no such process any more
    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))


def test_a_worker_that_is_alive_blocks_capture(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    _job(layout, {"phase": "running", "pid": 101, "start": "1010"})  # FakeOps: start is pid * 10, as text
    with pytest.raises(guard.Refused) as refused:
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert refused.value.code == "active-execution"
    # A pid that now belongs to a different process is a worker that is gone.
    ops.procs[101]["start"] = "other"
    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))


@pytest.mark.parametrize(
    "status,blocks",
    [
        ({"phase": "starting", "created_at": time.time()}, True),
        ({"phase": "starting", "created_at": time.time() - 3600}, False),
        (None, True),  # unreadable state is not evidence that nothing runs
        ({"phase": "unheard-of"}, True),
    ],
    ids=["just-dispatched", "dispatch-long-lost", "no-status", "unknown-phase"],
)
def test_a_job_without_a_result_blocks_capture_only_while_its_worker_may_still_be_coming(
    box: Dict[str, Any], status: Optional[Dict[str, Any]], blocks: bool
) -> None:
    layout = box["layout"]
    _fill(layout)
    _job(layout, status)
    if blocks:
        with pytest.raises(guard.Refused) as refused:
            box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
        assert refused.value.code == "active-execution"
    else:
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))


def test_a_timestamp_set_in_the_future_cannot_hold_the_agent_stopped(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    _fill(layout)
    ops.add(101)
    far_future = time.time() + 3 * 365 * 86400
    os.utime(layout.workspace / "notes.txt", (far_future, far_future))
    started = time.monotonic()
    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert time.monotonic() - started < 5 and ops.state(101) == "S"


def test_a_tree_that_never_settles_refuses_within_the_settle_limit_and_resumes_the_agent(
    box: Dict[str, Any],
) -> None:
    layout, ops = box["layout"], box["ops"]
    _fill(layout)
    ops.add(101)
    box["guard"].settle_ns = 600 * 10**9  # every change is "too recent" for ten minutes
    box["guard"].settle_limit = 0.3
    started = time.monotonic()
    with pytest.raises(guard.Refused) as refused:
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert refused.value.code == "unstable" and time.monotonic() - started < 3
    assert ops.state(101) == "S" and not list(layout.export.iterdir())


def test_a_jobs_directory_that_holds_a_link_is_refused_not_followed(box: Dict[str, Any], tmp_path: Path) -> None:
    layout = box["layout"]
    (layout.runtime / "jobs").mkdir()
    (layout.runtime / "jobs" / "x").symlink_to(tmp_path)
    with pytest.raises(guard.Refused) as refused:
        guard.runtime_idle(layout.runtime, lambda pid, start: False)
    assert refused.value.code == "active-execution"


@pytest.mark.parametrize("state", ["restoring", "failed"])
def test_capture_is_refused_on_a_computer_that_cannot_run(box: Dict[str, Any], state: str) -> None:
    _force_state(box["guard"], state)
    with pytest.raises(guard.Refused) as refused:
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(box["layout"]))
    assert refused.value.code == state


def test_a_process_that_appears_during_the_freeze_is_stopped_too(box: Dict[str, Any]) -> None:
    ops = box["ops"]
    ops.add(101)
    calls: List[int] = []

    def late_arrival() -> None:
        calls.append(1)
        if len(calls) == 2:
            ops.add(103)

    ops.on_select = late_arrival
    seen: Dict[str, Any] = {}

    def archive(descriptor: int, job: Any) -> None:
        seen["states"] = {pid: ops.state(pid) for pid in (101, 103)}
        _archiver(box["layout"])(descriptor, job)

    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=archive)
    assert seen["states"] == {101: "T", 103: "T"} and ops.state(103) == "S"


def test_a_process_that_will_not_stop_refuses_the_capture_and_everything_is_resumed(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    ops.add(102)
    ops.refuse_stop = {102}
    box["guard"].stop_wait = 0.05
    with pytest.raises(guard.Refused) as refused:
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert refused.value.code == "unstable-freeze"
    assert ops.state(101) == "S" and not list(layout.export.iterdir())
    assert not (layout.control / "freeze.journal").exists()


def test_a_reused_pid_is_never_signalled_as_the_process_it_replaced(box: Dict[str, Any]) -> None:
    ops = box["ops"]
    ops.add(101)
    ops.reuse_before_signal = 101
    seen: Dict[str, Any] = {}

    def archive(descriptor: int, job: Any) -> None:
        seen["state"] = ops.state(101)
        _archiver(box["layout"])(descriptor, job)

    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=archive)
    # The recorded process was gone; the process now holding the pid was found on the next pass and stopped.
    assert seen["state"] == "T" and ops.sent[0] == (101, signal.SIGSTOP) and ops.state(101) == "S"


#
# Controlled process model (``FakeOps``), not a real Linux process: a SIGSTOP the kernel accepted can take effect
# after the freeze wait has given up. The cleanup must cancel such a stop, not forget it with the journal.


def test_a_stop_that_is_still_pending_when_the_capture_gives_up_is_cancelled_by_the_cleanup(
    box: Dict[str, Any],
) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    ops.delay_stop = {101}
    box["guard"].stop_wait = 0.05
    with pytest.raises(guard.Refused) as refused:
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert refused.value.code == "unstable-freeze"
    ops.settle()  # the stop that was pending takes effect now, after the journal was dropped
    assert ops.state(101) == "S", "the pending stop outlived the capture"
    assert (101, signal.SIGCONT) in ops.sent and not (layout.control / "freeze.journal").exists()


def test_the_next_operation_cancels_a_stop_that_was_pending_when_a_capture_died(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    ops.pending_stop = {101}  # the dead capture's SIGSTOP was accepted but has not taken effect
    _journal(layout, [{"op": "intent", "pid": 101, "id": ops.identity(101)}])
    assert _exec(box, lambda descriptor, environment: 0) == 0
    ops.settle()
    assert ops.state(101) == "S", "the pending stop outlived the recovery"
    assert ops.sent == [(101, signal.SIGCONT)] and not (layout.control / "freeze.journal").exists()


def test_recovery_after_a_pending_stop_is_safe_to_repeat(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    ops.delay_stop = {101}
    box["guard"].stop_wait = 0.05
    with pytest.raises(guard.Refused):
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    ops.settle()
    sent = list(ops.sent)
    assert _exec(box, lambda descriptor, environment: 0) == 0 and _exec(box, lambda descriptor, environment: 0) == 0
    assert ops.sent == sent and ops.state(101) == "S", "a later admission must find nothing left to undo"


def test_a_process_that_stopped_promptly_is_still_resumed_exactly_once(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert ops.sent == [(101, signal.SIGSTOP), (101, signal.SIGCONT)] and ops.state(101) == "S"


def test_a_process_stopped_by_someone_else_before_the_capture_is_never_resumed(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101, state="T")
    ops.add(102)
    ops.delay_stop = {102}
    box["guard"].stop_wait = 0.05
    with pytest.raises(guard.Refused):
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    ops.settle()
    assert ops.state(101) == "T" and all(pid != 101 for pid, _ in ops.sent)
    assert ops.state(102) == "S"


def test_a_failure_to_cancel_a_pending_stop_keeps_the_journal_so_the_next_operation_can(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    ops.delay_stop = {101}
    ops.unsupported_signals = {signal.SIGCONT}  # the stop was sent; the cancel cannot get a handle this time
    box["guard"].stop_wait = 0.05
    with pytest.raises(Exception) as raised:
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert (layout.control / "freeze.journal").exists(), "the journal was dropped while a stop was still pending"
    assert isinstance(raised.value, guard.Unsupported)
    ops.unsupported_signals = set()
    assert _exec(box, lambda descriptor, environment: 0) == 0
    ops.settle()
    assert ops.state(101) == "S" and not (layout.control / "freeze.journal").exists()


def test_a_stopped_process_that_cannot_be_resumed_is_still_an_error_on_recovery(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101, state="T")
    ops.unsupported = True
    _journal(layout, [{"op": "intent", "pid": 101, "id": ops.identity(101)}])
    with pytest.raises(guard.Unsupported):
        with box["guard"].admit():
            pass
    assert ops.state(101) == "T" and (layout.control / "freeze.journal").exists(), "the journal must stay for a retry"


def test_a_recorded_process_that_has_vanished_or_been_replaced_is_never_signalled_on_recovery(
    box: Dict[str, Any],
) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(103)  # the recorded identity belongs to another process now
    _journal(
        layout,
        [
            {"op": "intent", "pid": 103, "id": "boot:somebody-else"},
            {"op": "intent", "pid": 104, "id": "boot:gone"},  # nothing runs under this pid any more
        ],
    )
    assert _exec(box, lambda descriptor, environment: 0) == 0
    assert ops.sent == [] and not (layout.control / "freeze.journal").exists()


def _fail_journal_io(
    monkeypatch: pytest.MonkeyPatch,
    layout: guard.Layout,
    ops: FakeOps,
    *,
    writes: Sequence[Any] = (),
    fsync_error: Optional[OSError] = None,
) -> Dict[str, Any]:
    """Script the freeze journal's own writes (and fsync) in order; every other descriptor is untouched.

    A write step is None (pass through), an int (write only that many bytes and report that count), or an
    exception to raise. When the script runs out, writes pass through. ``at_stop`` records, at each SIGSTOP, whether
    the journal already holds a complete intent record for that process.
    """
    journal = layout.control / "freeze.journal"
    real_write, real_fsync, real_signal = os.write, os.fsync, ops.signal
    script, seen = list(writes), {"calls": 0, "at_stop": {}}

    def is_journal(descriptor: int) -> bool:
        try:
            return os.path.samestat(os.fstat(descriptor), os.stat(journal))
        except OSError:
            return False

    def write(descriptor: int, data: Any) -> int:
        if not is_journal(descriptor):
            return real_write(descriptor, data)
        seen["calls"] += 1
        assert seen["calls"] < 50, "the journal write loop did not stop"
        step = script.pop(0) if script else None
        if isinstance(step, BaseException):
            raise step
        if step is None:
            return real_write(descriptor, data)
        return real_write(descriptor, bytes(data)[:step]) if step else 0

    def fsync(descriptor: int) -> None:
        if fsync_error is not None and is_journal(descriptor):
            raise fsync_error
        real_fsync(descriptor)

    def signal_(pid: int, ident: str, sig: int) -> bool:
        if sig == signal.SIGSTOP:
            intents = [e for e in box_entries() if e.get("op") == "intent" and e.get("pid") == pid]
            seen["at_stop"][pid] = bool(intents)
        return real_signal(pid, ident, sig)

    def box_entries() -> List[Dict[str, Any]]:
        out = []
        for line in journal.read_text().split("\n"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(ops, "signal", signal_)
    return seen


def test_a_short_journal_write_is_completed_before_the_process_is_stopped(
    box: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    # The export record passes through; the intent record is accepted 22 bytes at a time, then the rest.
    seen = _fail_journal_io(monkeypatch, layout, ops, writes=[None, 22])
    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert seen["at_stop"] == {101: True}
    assert ops.sent == [(101, signal.SIGSTOP), (101, signal.SIGCONT)] and ops.state(101) == "S"
    assert not (layout.control / "freeze.journal").exists()


def test_a_short_journal_write_that_then_fails_never_stops_the_process(
    box: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    _fail_journal_io(monkeypatch, layout, ops, writes=[None, 22, OSError(28, "No space left on device")])
    with pytest.raises(OSError):
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert ops.sent == [] and ops.state(101) == "S" and not list(layout.export.iterdir())
    assert not (layout.control / "freeze.journal").exists()


def test_a_journal_write_that_makes_no_progress_fails_instead_of_looping(
    box: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    _fail_journal_io(monkeypatch, layout, ops, writes=[None, 0])
    with pytest.raises(OSError):
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert ops.sent == [] and ops.state(101) == "S"
    assert not (layout.control / "freeze.journal").exists()


def test_a_journal_that_cannot_be_synced_never_stops_the_process(
    box: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    _fail_journal_io(monkeypatch, layout, ops, fsync_error=OSError(5, "Input/output error"))
    with pytest.raises(OSError):
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert ops.sent == [] and ops.state(101) == "S"


def test_a_journal_failure_after_earlier_intents_still_resumes_the_processes_already_stopped(
    box: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    ops.add(102)
    # export record, then 101's intent pass through; 102's intent is accepted in part and then fails.
    _fail_journal_io(monkeypatch, layout, ops, writes=[None, None, 22, OSError(5, "Input/output error")])
    with pytest.raises(OSError):
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert ops.sent == [(101, signal.SIGSTOP), (101, signal.SIGCONT)]
    assert ops.state(101) == "S" and ops.state(102) == "S"
    assert not (layout.control / "freeze.journal").exists()


def test_a_kernel_without_stable_process_handles_is_an_explicit_refusal(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)
    ops.unsupported = True
    with pytest.raises(guard.Refused) as refused:
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert refused.value.code == "unsupported" and ops.state(101) == "S" and not list(layout.export.iterdir())


def test_roots_that_change_during_the_archive_refuse_the_capture(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    _fill(layout)
    ops.add(101)

    def archive(descriptor: int, job: Any) -> None:
        _archiver(layout)(descriptor, job)
        (layout.workspace / "late.txt").write_text("written by something that was not stopped")

    with pytest.raises(guard.Refused) as refused:
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=archive)
    assert refused.value.code == "unstable" and ops.state(101) == "S" and not list(layout.export.iterdir())


def test_a_failed_archive_removes_the_export_and_resumes_the_processes(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101)

    def archive(descriptor: int, job: Any) -> None:
        os.write(descriptor, b"partial")
        raise RuntimeError("archive failed")

    with pytest.raises(RuntimeError, match="archive failed"):
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=archive)
    assert ops.state(101) == "S" and not list(layout.export.iterdir())
    assert not (layout.control / "freeze.journal").exists()
    # The computer takes the next capture and the next command as if nothing had happened.
    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))


def _journal(layout: guard.Layout, records: List[Dict[str, Any]], torn: str = "") -> None:
    text = "".join(json.dumps(record) + "\n" for record in records) + torn
    (layout.control / "freeze.journal").write_text(text)


def test_a_capture_that_died_while_the_agent_was_stopped_is_recovered_by_the_next_command(
    box: Dict[str, Any],
) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101, state="T")  # stopped by the dead capture
    ops.add(102, state="T")  # stopped by someone else, which the capture skipped
    ops.add(103, state="T")  # recorded, but the pid now belongs to another process
    partial = layout.export / f"{CHECKPOINT_NAME}.tar"
    partial.write_bytes(b"half an archive")
    _journal(
        layout,
        [
            {"op": "export", "path": str(partial)},
            {"op": "intent", "pid": 101, "id": ops.identity(101)},
            {"op": "skip", "pid": 102, "id": ops.identity(102)},
            {"op": "intent", "pid": 103, "id": "boot:somebody-else"},
        ],
        torn='{"op": "intent", "pid": 10',
    )
    assert _exec(box, lambda descriptor, environment: 0) == 0
    assert ops.state(101) == "S" and ops.state(102) == "T" and ops.state(103) == "T"
    assert not partial.exists() and not (layout.control / "freeze.journal").exists()
    assert ops.sent == [(101, signal.SIGCONT)]


def test_the_next_operation_recovers_before_a_second_capture(box: Dict[str, Any]) -> None:
    layout, ops = box["layout"], box["ops"]
    ops.add(101, state="T")
    _journal(layout, [{"op": "intent", "pid": 101, "id": ops.identity(101)}])
    box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert ops.state(101) == "S"


def _source_tree(tmp_path: Path, state: Dict[str, Any], extra: Optional[Callable[[Path, Path], None]] = None) -> Path:
    workspace, native = tmp_path / "src/workspace", tmp_path / "src/native"
    workspace.mkdir(parents=True)
    native.mkdir()
    (workspace / "a.txt").write_text("a")
    (workspace / "d").mkdir()
    (workspace / "d" / "b.txt").write_text("b")
    (workspace / "link").symlink_to("a.txt")
    (native / "n.txt").write_text("n")
    if extra is not None:
        extra(workspace, native)
    archive = tmp_path / "checkpoint.tar"
    CheckpointArchive().capture({"workspace": workspace, "native": native}, archive, state=state)
    return archive


def _stage_archive(layout: guard.Layout, source: Path) -> Path:
    staged = layout.inbox / f"{CHECKPOINT_NAME}.tar"
    staged.write_bytes(source.read_bytes())
    staged.chmod(0o600)
    return staged


def _restore(box: Dict[str, Any]) -> Dict[str, Any]:
    result = box["guard"].restore(CHECKPOINT_NAME, {"limits": JOB["limits"]}, extract=guard._extract(JOB["limits"]))
    assert isinstance(result, dict)
    return result


def test_restore_fills_the_roots_for_the_agent_user_and_marks_the_computer_used(
    box: Dict[str, Any], tmp_path: Path
) -> None:
    layout = box["layout"]
    staged = _stage_archive(layout, _source_tree(tmp_path, {"binding": "b9"}))
    assert _restore(box) == {"binding": "b9"}
    assert (layout.workspace / "a.txt").read_text() == "a" and (layout.workspace / "d/b.txt").read_text() == "b"
    assert (layout.workspace / "link").is_symlink() and os.readlink(layout.workspace / "link") == "a.txt"
    assert (layout.native / "n.txt").read_text() == "n"
    assert layout.workspace.stat().st_uid == layout.agent_uid and stat.S_IMODE(layout.workspace.stat().st_mode) == 0o700
    assert box["guard"].state() == "used" and not staged.exists() and not list(layout.stage.iterdir())


def test_a_second_restore_is_refused(box: Dict[str, Any], tmp_path: Path) -> None:
    layout = box["layout"]
    source = _source_tree(tmp_path, {"binding": "b9"})
    _stage_archive(layout, source)
    _restore(box)
    _stage_archive(layout, source)
    with pytest.raises(guard.Refused) as refused:
        _restore(box)
    assert refused.value.code == "not-fresh"


def test_restore_is_refused_on_a_computer_that_already_ran(box: Dict[str, Any], tmp_path: Path) -> None:
    layout = box["layout"]
    assert _exec(box, lambda descriptor, environment: 0) == 0
    _stage_archive(layout, _source_tree(tmp_path, {}))
    with pytest.raises(guard.Refused) as refused:
        _restore(box)
    assert refused.value.code == "not-fresh" and not any(layout.workspace.iterdir())


def test_restore_needs_empty_roots(box: Dict[str, Any], tmp_path: Path) -> None:
    layout = box["layout"]
    (layout.native / "left-over").write_text("x")
    _stage_archive(layout, _source_tree(tmp_path, {}))
    with pytest.raises(guard.Refused) as refused:
        _restore(box)
    assert refused.value.code == "not-empty" and box["guard"].state() == "fresh"


def test_restore_is_refused_while_an_agent_process_exists(box: Dict[str, Any], tmp_path: Path) -> None:
    layout = box["layout"]
    box["ops"].add(101)
    _stage_archive(layout, _source_tree(tmp_path, {}))
    with pytest.raises(guard.Refused) as refused:
        _restore(box)
    assert refused.value.code == "agent-processes" and box["guard"].state() == "fresh"


@pytest.mark.parametrize("damage", ["missing", "mode", "owner", "link", "oversize"])
def test_a_staged_archive_the_agent_could_have_written_is_refused_before_anything_changes(
    box: Dict[str, Any], tmp_path: Path, damage: str
) -> None:
    layout = box["layout"]
    source = _source_tree(tmp_path, {})
    staged = _stage_archive(layout, source)
    job: Dict[str, Any] = {"limits": JOB["limits"]}
    if damage == "missing":
        staged.unlink()
    elif damage == "mode":
        staged.chmod(0o644)
    elif damage == "owner":
        layout = guard.Layout(**{**layout.__dict__, "staged_uid": os.getuid() + 1})
        box["guard"].layout = layout
    elif damage == "link":
        staged.unlink()
        staged.symlink_to(source)
    else:
        job["max_bytes"] = 10
    with pytest.raises(guard.Refused) as refused:
        box["guard"].restore(CHECKPOINT_NAME, job, extract=guard._extract(JOB["limits"]))
    assert refused.value.code == "not-staged" and box["guard"].state() == "fresh"
    assert not any(box["layout"].workspace.iterdir())


def test_a_bad_archive_fails_the_computer_and_leaves_the_roots_empty(box: Dict[str, Any]) -> None:
    layout = box["layout"]
    staged = layout.inbox / f"{CHECKPOINT_NAME}.tar"
    staged.write_bytes(b"this is not a checkpoint" * 100)
    staged.chmod(0o600)
    with pytest.raises(SandboxError):
        _restore(box)
    assert box["guard"].state() == "failed" and not any(layout.workspace.iterdir()) and not any(layout.native.iterdir())
    assert not list(layout.stage.iterdir())
    assert _exec(box, lambda descriptor, environment: 0) == guard.REFUSED


def _hostile(tmp_path: Path, build: Callable[[tarfile.TarFile], None]) -> Path:
    archive = tmp_path / "hostile.tar"
    with tarfile.open(archive, "w") as tar:
        manifest = json.dumps({"version": 1, "state": {}, "excluded": []}).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))
        for root in ("workspace", "native"):
            directory = tarfile.TarInfo(root)
            directory.type = tarfile.DIRTYPE
            tar.addfile(directory)
        build(tar)
    return archive


def _link(name: str, target: str) -> Callable[[tarfile.TarFile], None]:
    def build(tar: tarfile.TarFile) -> None:
        info = tarfile.TarInfo(name)
        info.type, info.linkname = tarfile.SYMTYPE, target
        tar.addfile(info)

    return build


def _file(name: str) -> Callable[[tarfile.TarFile], None]:
    def build(tar: tarfile.TarFile) -> None:
        info = tarfile.TarInfo(name)
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))

    return build


@pytest.mark.parametrize(
    "build",
    [
        _link("workspace/out", "../../../outside"),
        _file("../escaped.txt"),
        _file("/etc/escaped.txt"),
        _file("elsewhere/file.txt"),
    ],
    ids=["escaping-symlink", "parent-traversal", "absolute-path", "outside-roots"],
)
def test_a_hostile_archive_fails_the_restore_and_writes_nothing_outside(
    box: Dict[str, Any], tmp_path: Path, build: Callable[[tarfile.TarFile], None]
) -> None:
    layout = box["layout"]
    staged = layout.inbox / f"{CHECKPOINT_NAME}.tar"
    staged.write_bytes(_hostile(tmp_path, build).read_bytes())
    staged.chmod(0o600)
    outside = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(SandboxError):
        _restore(box)
    assert box["guard"].state() == "failed" and not any(layout.workspace.iterdir())
    assert not any(layout.native.iterdir()) and sorted(p.name for p in tmp_path.iterdir()) == outside
    for planted in ("escaped.txt", "outside", "passwd"):
        assert not list(tmp_path.rglob(planted))


def test_a_link_to_a_file_is_handed_over_without_following_it(
    box: Dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("not the agent's")
    outside.chmod(0o640)
    tree = tmp_path / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / "sub" / "link").symlink_to(outside)
    (tree / "sub" / "file").write_text("x")
    calls: List[Any] = []
    real = os.chown
    monkeypatch.setattr(
        guard.os, "chown", lambda path, uid, gid, **kw: (calls.append((str(path), kw)), real(path, uid, gid, **kw))[1]
    )
    guard._hand_over(tree, os.getuid(), os.getgid())
    assert {path for path, _ in calls} == {str(tree), str(tree / "sub"), str(tree / "sub/link"), str(tree / "sub/file")}
    assert all(kw == {"follow_symlinks": False} for _, kw in calls)
    assert stat.S_IMODE(outside.stat().st_mode) == 0o640 and stat.S_IMODE(tree.stat().st_mode) == 0o700


def test_a_process_that_appears_while_the_archive_is_extracted_fails_the_restore(
    box: Dict[str, Any], tmp_path: Path
) -> None:
    layout = box["layout"]
    _stage_archive(layout, _source_tree(tmp_path, {}))
    box["guard"].hook = lambda point: box["ops"].add(101) if point == "restore_extracted" else None
    with pytest.raises(guard.Refused) as refused:
        _restore(box)
    assert refused.value.code == "agent-processes" and box["guard"].state() == "failed"
    assert not any(layout.workspace.iterdir())


@pytest.mark.parametrize("point", ["restore_begin", "restore_extracted", "restore_moved_one"])
def test_a_restore_interrupted_at_any_step_never_leaves_a_usable_computer(
    box: Dict[str, Any], tmp_path: Path, point: str
) -> None:
    layout = box["layout"]
    _stage_archive(layout, _source_tree(tmp_path, {}))

    def interrupt(where: str) -> None:
        if where == point:
            raise RuntimeError("interrupted")

    box["guard"].hook = interrupt
    with pytest.raises(RuntimeError, match="interrupted"):
        _restore(box)
    assert box["guard"].state() == "failed" and not (layout.stage.exists() and list(layout.stage.iterdir()))
    assert _exec(box, lambda descriptor, environment: 0) == guard.REFUSED
    _stage_archive(layout, _source_tree(tmp_path / "again", {}))
    with pytest.raises(guard.Refused):
        _restore(box)


def test_a_rename_across_filesystems_fails_the_restore_closed(
    box: Dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    layout = box["layout"]
    _stage_archive(layout, _source_tree(tmp_path, {}))

    def cross_device(source: Any, destination: Any) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(guard.os, "rename", cross_device)
    with pytest.raises(OSError, match="cross-device"):
        _restore(box)
    assert box["guard"].state() == "failed" and not any(layout.native.iterdir())
    assert _exec(box, lambda descriptor, environment: 0) == guard.REFUSED


def test_a_failure_writing_the_final_state_never_leaves_a_usable_computer(
    box: Dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = box["layout"]
    _stage_archive(layout, _source_tree(tmp_path, {"binding": "b"}))
    original = guard.Guard._write_state

    def failing(self: guard.Guard, value: str) -> None:
        if value in ("used", "failed"):
            raise OSError("disk full")  # the final write and the fallback write both fail
        original(self, value)

    monkeypatch.setattr(guard.Guard, "_write_state", failing)
    with pytest.raises(OSError, match="disk full"):
        _restore(box)
    monkeypatch.setattr(guard.Guard, "_write_state", original)
    # Both roots were already in place, but the state still says restoring: nothing may run on it.
    assert box["guard"].state() == "restoring"
    assert _exec(box, lambda descriptor, environment: 0) == guard.REFUSED


def test_a_restore_that_died_leaves_the_computer_refusing_until_it_is_replaced(box: Dict[str, Any]) -> None:
    layout = box["layout"]
    _force_state(box["guard"], "restoring")  # what a guard killed mid-restore leaves behind
    (layout.stage / "x").mkdir(parents=True)
    assert _exec(box, lambda descriptor, environment: 0) == guard.REFUSED
    with pytest.raises(guard.Refused) as refused:
        box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
    assert refused.value.code == "restoring" and not layout.stage.exists()


def test_no_command_or_capture_starts_while_a_restore_runs(box: Dict[str, Any], tmp_path: Path) -> None:
    layout = box["layout"]
    _stage_archive(layout, _source_tree(tmp_path, {}))
    outcome: Dict[str, Any] = {}

    def extract(archive: Path, destination: Path) -> Dict[str, Any]:
        outcome["exec"] = _exec(box, lambda d, e: 0)
        with pytest.raises(guard.Refused) as refused:
            box["guard"].capture(CHECKPOINT_NAME, JOB, run_archive=_archiver(layout))
        outcome["capture"] = refused.value.code
        return guard._extract(JOB["limits"])(archive, destination)

    box["guard"].restore(CHECKPOINT_NAME, {"limits": JOB["limits"]}, extract=extract)
    assert outcome == {"exec": guard.REFUSED, "capture": "busy"}


def test_the_archive_child_is_the_shared_capture_run_as_the_agent_user(
    box: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = box["layout"]
    calls: Dict[str, Any] = {}

    def fake_run(argv: List[str], **kwargs: Any) -> Any:
        calls.update(argv=argv, **kwargs)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(guard.subprocess, "run", fake_run)
    monkeypatch.setattr(guard, "_no_new_privileges", lambda: calls.setdefault("nnp", True))
    guard._run_archive(layout)(5, JOB)
    assert calls["argv"] == [guard.PYTHON, "-I", "-m", "agno.sandbox.vercel.guard", "archive"]
    assert calls["stdout"] == 5 and calls["nnp"] is True and calls["cwd"] == "/"
    assert (calls["user"], calls["group"], calls["extra_groups"]) == (layout.agent_uid, layout.agent_gid, [])
    request = json.loads(calls["input"])
    assert request["roots"] == {name: str(path) for name, path in layout.roots.items()}
    assert request["state"] == JOB["state"] and request["exclude"] == JOB["exclude"]
    assert calls["env"]["HOME"] == guard.HOME and "SUDO_USER" not in calls["env"]


def test_the_archive_childs_real_entry_point_streams_a_valid_archive_to_standard_output(
    box: Dict[str, Any], tmp_path: Path
) -> None:
    layout = box["layout"]
    _fill(layout)
    job = json.dumps(
        {
            "roots": {name: str(path) for name, path in layout.roots.items()},
            "state": {"binding": "b1"},
            "exclude": list(DEFAULT_NATIVE_EXCLUSIONS),
            "limits": asdict(CheckpointLimits()),
        }
    )
    # The same function the guest runs as the agent user, in a real process with real standard streams.
    code = "import sys; from agno.sandbox.vercel import guard; sys.exit(guard.main(['guard', 'archive']))"
    source = str(Path(guard.__file__).parents[3])
    child = subprocess.run(
        [sys.executable, "-c", code],
        input=job.encode(),
        capture_output=True,
        env={**os.environ, "PYTHONPATH": source},
    )
    assert child.returncode == 0, child.stderr.decode()
    archive = tmp_path / "streamed.tar"
    archive.write_bytes(child.stdout)
    assert CheckpointArchive().validate(archive) == {"binding": "b1"}
    restored = tmp_path / "restored"
    CheckpointArchive().restore(archive, restored)
    assert (restored / "workspace/notes.txt").read_text() == "hello"
    assert not (restored / "native/codex/auth.json").exists()


def test_a_failing_archive_child_is_an_error_with_its_message(
    box: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guard, "_no_new_privileges", lambda: None)
    monkeypatch.setattr(
        guard.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, b"", b"Workspace changed")
    )
    with pytest.raises(RuntimeError, match="Workspace changed"):
        guard._run_archive(box["layout"])(5, JOB)


def test_finish_builds_the_layout_for_the_agent_and_writes_the_marker_last(
    box: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = box["layout"]
    monkeypatch.setattr(guard, "_ensure_agent", lambda layout: None)
    spec = layout.inbox / f"{NAME}.json"
    spec.write_text(json.dumps({"env": {"MODEL_KEY": "k"}, "marker": {"config_digest": "cfg", "source_digest": "s"}}))
    spec.chmod(0o600)
    seen: Dict[str, Any] = {}

    def check(where: guard.Layout) -> Dict[str, Any]:
        seen["ready_yet"] = where.ready.exists()
        seen["env"] = json.loads(where.env_file.read_text())
        return {"claude-agent-sdk": "1", "git": False}

    assert guard.run_finish(NAME, layout, check=check) == 0
    assert seen == {"ready_yet": False, "env": {"MODEL_KEY": "k"}}
    marker = json.loads(layout.ready.read_text())
    assert marker == {
        "config_digest": "cfg",
        "source_digest": "s",
        "installed": {"claude-agent-sdk": "1", "git": False},
    }
    assert stat.S_IMODE(layout.ready.stat().st_mode) == 0o644 and stat.S_IMODE(layout.env_file.stat().st_mode) == 0o600
    for directory in (layout.control, layout.stage, layout.inbox, layout.export, layout.workspace, layout.native):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert not spec.exists()


def test_a_failed_readiness_check_leaves_no_marker(box: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    layout = box["layout"]
    monkeypatch.setattr(guard, "_ensure_agent", lambda layout: None)
    spec = layout.inbox / f"{NAME}.json"
    spec.write_text(json.dumps({"env": {}, "marker": {"config_digest": "cfg"}}))
    spec.chmod(0o600)

    def check(where: guard.Layout) -> Dict[str, Any]:
        raise RuntimeError("no sqlalchemy")

    with pytest.raises(RuntimeError, match="no sqlalchemy"):
        guard.run_finish(NAME, layout, check=check)
    assert not layout.ready.exists()


@pytest.mark.parametrize("body", ['{"env": {}}', '{"env": [], "marker": {}}', "[]", "{"])
def test_finish_refuses_a_malformed_request_and_an_already_ready_computer(box: Dict[str, Any], body: str) -> None:
    layout = box["layout"]
    spec = layout.inbox / f"{NAME}.json"
    spec.write_text(body)
    spec.chmod(0o600)
    status = guard._guarded(lambda: guard.run_finish(NAME, layout))
    assert status == guard.REFUSED and not layout.ready.exists()


def test_finish_never_bootstraps_a_computer_twice(box: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    layout = box["layout"]
    _ready(layout)
    spec = layout.inbox / f"{NAME}.json"
    spec.write_text(json.dumps({"env": {}, "marker": {}}))
    spec.chmod(0o600)
    assert guard.run_finish(NAME, layout) == guard.REFUSED


def test_every_command_but_the_bootstrap_needs_the_marker(box: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    layout = box["layout"]
    monkeypatch.setattr(guard, "Layout", lambda: layout)
    called: List[str] = []
    monkeypatch.setattr(guard, "run_capture", lambda name, where: called.append("capture") or 0)
    monkeypatch.setattr(guard, "run_restore", lambda name, where: called.append("restore") or 0)
    monkeypatch.setattr(guard, "run_remove", lambda name, where: called.append("remove") or 0)
    for command in ("capture", "restore", "remove"):
        assert guard.main(["guard", command, CHECKPOINT_NAME]) == guard.REFUSED
    assert called == []
    _ready(layout)
    for command in ("capture", "restore", "remove"):
        assert guard.main(["guard", command, CHECKPOINT_NAME]) == 0
    assert called == ["capture", "restore", "remove"]
    assert guard.main(["guard", "capture", "not-a-name"]) == 2


def test_a_refusal_is_the_refusal_status_and_any_other_failure_is_status_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def refuse() -> int:
        raise guard.Refused("busy", "a command holds the computer")

    def fail() -> int:
        raise ValueError("boom")

    assert guard._guarded(refuse) == guard.REFUSED
    assert guard.REFUSAL_PREFIX + "busy: a command holds the computer" in capsys.readouterr().err
    assert guard._guarded(fail) == 1
    assert "ValueError: boom" in capsys.readouterr().err


def test_remove_deletes_an_export_and_ignores_a_missing_one(box: Dict[str, Any]) -> None:
    layout = box["layout"]
    target = layout.export / f"{CHECKPOINT_NAME}.tar"
    target.write_bytes(b"x")
    assert guard.run_remove(CHECKPOINT_NAME, layout) == 0 and not target.exists()
    assert guard.run_remove(CHECKPOINT_NAME, layout) == 0


def _proc(tmp_path: Path, processes: Dict[int, Dict[str, Any]]) -> Path:
    proc = tmp_path / "proc"
    (proc / "sys/kernel/random").mkdir(parents=True)
    (proc / "sys/kernel/random/boot_id").write_text("boot-1\n")
    for pid, fields in processes.items():
        (proc / str(pid)).mkdir()
        rest = " ".join(["0"] * 17 + [str(fields["start"])])
        (proc / str(pid) / "stat").write_text(
            f"{pid} ({fields.get('comm', 'cmd')}) {fields.get('state', 'S')} {fields['ppid']} {rest} 0 0\n"
        )
        (proc / str(pid) / "status").write_text(f"Name:\tx\nUid:\t{fields['uid']}\t{fields['uid']}\t0\t0\n")
    return proc


def test_linux_ops_reads_identity_state_and_ancestors(tmp_path: Path) -> None:
    ops = guard.LinuxOps(
        str(_proc(tmp_path, {1: {"ppid": 0, "uid": 0, "start": 1}, 50: {"ppid": 1, "uid": 5, "start": 777}}))
    )
    assert ops.identity(50) == "boot-1:777" and ops.state(50) == "S" and ops.ancestors(50) == [50, 1]
    assert ops.identity(99) is None and ops.state(99) == ""


def test_the_stat_parser_survives_a_command_name_with_parentheses_and_skips_zombies() -> None:
    assert guard.parse_stat("12 (a ) b (c) S 3 " + " ".join(["0"] * 17 + ["42"]) + " 0")["start"] == "42"
    assert guard.parse_stat("12 (x) Z 3 " + " ".join(["0"] * 17 + ["42"])) is None
    assert guard.parse_stat("garbage") is None


def test_the_selector_takes_the_agents_processes_and_nothing_else(tmp_path: Path) -> None:
    ops = guard.LinuxOps(
        str(
            _proc(
                tmp_path,
                {
                    10: {"ppid": 1, "uid": 2001, "start": 1},
                    11: {"ppid": 10, "uid": 2001, "start": 2},
                    12: {"ppid": 1, "uid": 2002, "start": 3},
                    13: {"ppid": 2, "uid": 2001, "start": 4},  # a kernel thread
                    14: {"ppid": 1, "uid": 2001, "start": 5, "state": "Z"},
                    15: {"ppid": 1, "uid": 2001, "start": 6},
                },
            )
        )
    )
    assert ops.select(2001, {15}) == [10, 11]


def test_signalling_is_refused_where_the_kernel_has_no_process_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = guard.LinuxOps(str(_proc(tmp_path, {50: {"ppid": 1, "uid": 5, "start": 7}})))
    monkeypatch.delattr(os, "pidfd_open", raising=False)
    with pytest.raises(guard.Unsupported):
        ops.signal(50, "boot-1:7", signal.SIGSTOP)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="process handles are Linux")
def test_linux_ops_stops_and_resumes_a_real_process_by_handle() -> None:
    if not hasattr(os, "pidfd_open"):
        pytest.skip("needs a kernel and Python with pidfd")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        ops = guard.LinuxOps()
        ident = ops.identity(child.pid)
        assert ident is not None and ops.signal(child.pid, ident, signal.SIGSTOP)
        for _ in range(200):
            if ops.state(child.pid).startswith("T"):
                break
            time.sleep(0.01)
        assert ops.state(child.pid).startswith("T")
        assert not ops.signal(child.pid, "boot:someone-else", signal.SIGCONT)
        assert ops.signal(child.pid, ident, signal.SIGCONT)
    finally:
        child.kill()
        child.wait()


class ProtocolOnlyStore:
    """Exposes only the CheckpointStore protocol, so the transfer cannot lean on FileCheckpointStore's internals."""

    def __init__(self, inner: FileCheckpointStore) -> None:
        for name in ("put", "aput", "verify", "averify", "open_archive", "aopen_archive", "delete", "adelete"):
            setattr(self, name, getattr(inner, name))


REAL_LAYOUT = guard.Layout
REAL_EXTRACT = guard._extract


def _new_guest(world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> Dict[str, Any]:
    root = tmp_path / name
    layout = REAL_LAYOUT(
        control=root / "opt/control",
        inbox=root / "opt/inbox",
        export=root / "opt/export",
        stage=root / "opt/stage",
        ready=root / "opt/READY",
        env_file=root / "opt/ENV",
        workspace=root / "workspace",
        runtime=root / "runtime",
        agent_uid=os.getuid(),
        agent_gid=os.getgid(),
        staged_uid=os.getuid(),
        trusted_uid=os.getuid(),
    )
    layout.inbox.mkdir(parents=True, mode=0o700)
    layout.export.mkdir(mode=0o700)
    layout.workspace.mkdir()
    layout.native.mkdir(parents=True)
    _ready(layout)
    ops = FakeOps()
    monkeypatch.setattr(guard, "LinuxOps", lambda: ops)
    monkeypatch.setattr(guard, "_run_archive", _archiver)
    monkeypatch.setattr(guard, "Layout", lambda: layout)
    world.layout = layout
    return {"layout": layout, "ops": ops, "guard": guard.Guard(layout, ops=ops)}


@pytest.fixture
def gtree(world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    return _new_guest(world, tmp_path, monkeypatch, "guest-a")


@pytest.fixture
def store(tmp_path: Path) -> FileCheckpointStore:
    return FileCheckpointStore(tmp_path / "objects")


def _restored(store: FileCheckpointStore, reference: Any, tmp_path: Path) -> Path:
    destination = tmp_path / "restored"
    with store.open_archive(reference) as archive:
        CheckpointArchive().restore(archive, destination)
    return destination


def test_the_provider_returns_a_transfer_for_its_store(sandbox: VercelSandbox, store: FileCheckpointStore) -> None:
    from agno.sandbox.transfer import CheckpointTransfer
    from agno.sandbox.vercel.transfer import VercelCheckpointTransfer

    transfer = sandbox.checkpoint_transfer(store)
    assert isinstance(transfer, VercelCheckpointTransfer) and isinstance(transfer, CheckpointTransfer)
    assert transfer.store is store and transfer.provider is sandbox


def test_the_transfer_is_exported_lazily_beside_the_provider() -> None:
    import agno.sandbox.vercel as package

    assert package.VercelCheckpointTransfer.__name__ == "VercelCheckpointTransfer"
    assert "VercelCheckpointTransfer" in package.__all__


def test_archive_limits_beyond_what_the_guard_moves_are_refused(
    sandbox: VercelSandbox, store: FileCheckpointStore
) -> None:
    from agno.sandbox.vercel.transfer import VercelCheckpointTransfer

    with pytest.raises(ValueError, match="2 GiB"):
        VercelCheckpointTransfer(sandbox, store, archive=CheckpointArchive(CheckpointLimits(max_bytes=3 * 1024**3)))


async def test_capture_moves_the_guests_archive_into_the_store_and_cleans_up(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
) -> None:
    layout = gtree["layout"]
    _fill(layout)
    gtree["ops"].add(101)
    reference = await sandbox.checkpoint_transfer(ProtocolOnlyStore(store)).acapture(handle, state={"binding": "b1"})
    restored = _restored(store, reference, tmp_path)
    assert (restored / "workspace/notes.txt").read_text() == "hello" and (restored / "native/session.json").exists()
    assert not (restored / "native/codex/auth.json").exists()
    assert world.runs_of_the_guard == ["capture", "remove"]
    assert not list(layout.export.iterdir()) and not list(layout.inbox.iterdir())
    assert gtree["ops"].state(101) == "S" and world.stopped == []
    assert world.events.count("client.create") == world.events.count("client.aclose")


async def test_capture_asks_the_guard_for_the_shared_limits_and_exclusions(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, gtree: Dict[str, Any], store: FileCheckpointStore
) -> None:
    seen: Dict[str, Any] = {}
    original = guard.Guard.capture

    def spy(self: guard.Guard, name: str, job: Any, **kwargs: Any) -> int:
        seen.update(job)
        return original(self, name, job, **kwargs)

    guard.Guard.capture = spy  # type: ignore[method-assign]
    try:
        _fill(gtree["layout"])
        await sandbox.checkpoint_transfer(store).acapture(handle, state={"binding": "b1"})
    finally:
        guard.Guard.capture = original  # type: ignore[method-assign]
    assert seen["state"] == {"binding": "b1"} and seen["exclude"] == list(VERCEL_NATIVE_EXCLUSIONS)
    assert seen["limits"] == asdict(CheckpointLimits())


CODEX_ROLLOUT = "sessions/2026/10/21/rollout-thread-1.jsonl"


def _codex_home(layout: guard.Layout, *, clone_bytes: int) -> None:
    """A Codex home: what a thread needs to resume, plus the plugin clone the CLI rebuilds when it starts."""
    codex = layout.native / "codex"
    (codex / "sessions/2026/10/21").mkdir(parents=True)
    (codex / CODEX_ROLLOUT).write_text('{"thread": "thread-1", "turn": 2}\n')
    (codex / "config.toml").write_text('model = "m"\n')
    (codex / "auth.json").write_text("secret")
    (codex / ".tmp/marketplaces").mkdir(parents=True)
    (codex / ".tmp/marketplaces/added.json").write_text("{}")
    (codex / ".tmp/plugins/plugins/demo").mkdir(parents=True)
    for index in range(4):
        (codex / f".tmp/plugins/plugins/demo/asset-{index}.bin").write_bytes(os.urandom(clone_bytes // 4))
    (codex / ".tmp/plugins.sha").write_text("0" * 40)


def _small_limit_transfer(sandbox: VercelSandbox, store: FileCheckpointStore) -> Any:
    from agno.sandbox.vercel.transfer import VercelCheckpointTransfer

    return VercelCheckpointTransfer(sandbox, store, archive=CheckpointArchive(CheckpointLimits(max_bytes=1024 * 1024)))


async def test_capture_leaves_out_codexs_rebuildable_plugin_clone_and_keeps_the_session_state(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fill(gtree["layout"])
    _codex_home(gtree["layout"], clone_bytes=2 * 1024 * 1024)  # twice the limit, all of it the clone
    transfer = _small_limit_transfer(sandbox, store)
    reference = await transfer.acapture(handle, state={"binding": "b1"})
    codex = _restored(store, reference, tmp_path) / "native/codex"
    assert (codex / CODEX_ROLLOUT).read_text() == '{"thread": "thread-1", "turn": 2}\n'
    assert (codex / "config.toml").exists() and (codex / ".tmp/marketplaces/added.json").exists()
    assert not (codex / "auth.json").exists()
    assert not (codex / ".tmp/plugins").exists() and not (codex / ".tmp/plugins.sha").exists()
    second = _new_guest(world, tmp_path, monkeypatch, "guest-b")
    assert await transfer.arestore(handle, reference) == {"binding": "b1"}
    restored = second["layout"].native / "codex"
    assert (restored / CODEX_ROLLOUT).read_text() == '{"thread": "thread-1", "turn": 2}\n'
    assert (second["layout"].workspace / "notes.txt").read_text() == "hello" and not (
        restored / ".tmp/plugins"
    ).exists()


@pytest.mark.parametrize(
    "big", [f"native/codex/{CODEX_ROLLOUT}", "native/codex/.tmp/marketplaces/big.bin", "workspace/big.bin"]
)
async def test_capture_still_refuses_state_over_the_limit_that_is_not_the_plugin_clone(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    big: str,
) -> None:
    layout = gtree["layout"]
    _fill(layout)
    _codex_home(layout, clone_bytes=4096)
    target = {"native": layout.native, "workspace": layout.workspace}[big.split("/", 1)[0]] / big.split("/", 1)[1]
    with target.open("ab") as stream:
        stream.write(os.urandom(2 * 1024 * 1024))
    with pytest.raises(SandboxError, match="exceeds its limit"):
        await _small_limit_transfer(sandbox, store).acapture(handle, state={"binding": "b1"})


async def test_exclusions_a_caller_names_are_used_as_given_not_merged_with_the_defaults(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, gtree: Dict[str, Any], store: FileCheckpointStore
) -> None:
    _fill(gtree["layout"])
    _codex_home(gtree["layout"], clone_bytes=2 * 1024 * 1024)
    with pytest.raises(SandboxError, match="exceeds its limit"):
        await _small_limit_transfer(sandbox, store).acapture(
            handle, state={"binding": "b1"}, exclude=DEFAULT_NATIVE_EXCLUSIONS
        )


@pytest.mark.parametrize("exclude", [("manifest.json",), ("workspace",), ("../x",), ("/abs",)])
async def test_an_exclusion_the_archive_would_reject_is_refused_before_anything_is_sent(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    exclude: Any,
) -> None:
    with pytest.raises((ValueError, SandboxError)):
        await sandbox.checkpoint_transfer(store).acapture(handle, state={}, exclude=exclude)
    assert world.events == [] and world.runs_of_the_guard == []


async def test_capture_while_a_turn_is_running_is_refused_and_leaves_compute_alone(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, gtree: Dict[str, Any], store: FileCheckpointStore
) -> None:
    job = gtree["layout"].runtime / "jobs" / "abc"
    job.mkdir(parents=True)
    (job / "request.json").write_text("{}")
    gtree["ops"].add(101)
    with pytest.raises(SandboxError, match="refused to capture.*active-execution"):
        await sandbox.checkpoint_transfer(store).acapture(handle, state={})
    assert world.stopped == [] and gtree["ops"].sent == [] and not list(store.root.rglob("*.tar"))
    assert world.runs_of_the_guard[-1] == "remove"


async def test_a_lost_reply_to_a_capture_leaves_compute_running_and_asks_for_cleanup(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, gtree: Dict[str, Any], store: FileCheckpointStore
) -> None:
    original = world._guard
    calls: List[str] = []

    def lose_the_first(command: str, name: str, stdout: Any, stderr: Any) -> int:
        calls.append(command)
        if command == "capture":
            original(command, name, stdout, stderr)
            raise ConnectionError("reply lost")
        return original(command, name, stdout, stderr)

    world._guard = lose_the_first  # type: ignore[method-assign]
    _fill(gtree["layout"])
    with pytest.raises(SandboxError, match="capture"):
        await sandbox.checkpoint_transfer(store).acapture(handle, state={})
    assert calls == ["capture", "remove"] and world.stopped == [] and not list(gtree["layout"].export.iterdir())


def _forged_export(
    excluded: List[str], member: str, directories: Sequence[str] = ("workspace", "native", "native/codex")
) -> Callable[[guard.Layout], Callable[[int, Any], None]]:
    """A guest that writes an archive whose manifest claims ``excluded`` but which holds ``member`` anyway."""

    def factory(where: guard.Layout) -> Callable[[int, Any], None]:
        def run(descriptor: int, job: Any) -> None:
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w") as tar:
                manifest = json.dumps({"version": 1, "state": job["state"], "excluded": excluded}).encode()
                info = tarfile.TarInfo("manifest.json")
                info.size = len(manifest)
                tar.addfile(info, io.BytesIO(manifest))
                for directory in directories:
                    entry = tarfile.TarInfo(directory)
                    entry.type = tarfile.DIRTYPE
                    tar.addfile(entry)
                data = tarfile.TarInfo(member)
                data.size = 6
                tar.addfile(data, io.BytesIO(b"secret"))
            os.write(descriptor, buffer.getvalue())

        return run

    return factory


async def test_an_export_that_holds_an_excluded_file_is_never_stored(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guard, "_run_archive", _forged_export(list(VERCEL_NATIVE_EXCLUSIONS), "native/codex/auth.json"))
    with pytest.raises(SandboxError, match="contains excluded path"):
        await sandbox.checkpoint_transfer(store).acapture(handle, state={})
    assert not list(store.root.rglob("*.tar")) and world.runs_of_the_guard[-1] == "remove"


async def test_an_export_that_is_not_a_valid_checkpoint_is_never_stored(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Well formed and honest about its exclusions, but one of the two durable roots is missing.
    monkeypatch.setattr(
        guard, "_run_archive", _forged_export(list(VERCEL_NATIVE_EXCLUSIONS), "workspace/ok.txt", ("workspace",))
    )
    with pytest.raises(SandboxError, match="missing durable roots"):
        await sandbox.checkpoint_transfer(store).acapture(handle, state={})
    assert not list(store.root.rglob("*.tar"))


async def test_an_export_that_does_not_record_the_requested_exclusions_is_never_stored(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guard, "_run_archive", _forged_export([], "workspace/ok.txt"))
    with pytest.raises(SandboxError, match="does not record the requested exclusions"):
        await sandbox.checkpoint_transfer(store).acapture(handle, state={})
    assert not list(store.root.rglob("*.tar"))


async def test_an_export_with_data_after_its_end_marker_is_never_stored(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fill(gtree["layout"])

    def appending(where: guard.Layout) -> Callable[[int, Any], None]:
        def run(descriptor: int, job: Any) -> None:
            _archiver(where, compress=False)(descriptor, job)
            os.write(descriptor, b"\x01smuggled second archive")

        return run

    monkeypatch.setattr(guard, "_run_archive", appending)
    with pytest.raises(SandboxError, match="after the end"):
        await sandbox.checkpoint_transfer(store).acapture(handle, state={})
    assert not list(store.root.rglob("*.tar"))


async def test_an_export_whose_size_the_guest_misreports_is_an_error(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fill(gtree["layout"])
    original = guard.Guard.capture
    monkeypatch.setattr(guard.Guard, "capture", lambda self, name, job, **kw: original(self, name, job, **kw) + 7)
    with pytest.raises(SandboxError, match="ended before its reported size"):
        await sandbox.checkpoint_transfer(store).acapture(handle, state={})
    monkeypatch.setattr(guard.Guard, "capture", lambda self, name, job, **kw: original(self, name, job, **kw) - 7)
    with pytest.raises(SandboxError, match="changed size"):
        await sandbox.checkpoint_transfer(store).acapture(handle, state={})
    assert not list(store.root.rglob("*.tar"))


async def test_an_export_larger_than_the_archive_limit_is_not_downloaded(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, gtree: Dict[str, Any], store: FileCheckpointStore
) -> None:
    from agno.sandbox.vercel.transfer import VercelCheckpointTransfer

    _fill(gtree["layout"])
    transfer = VercelCheckpointTransfer(sandbox, store, archive=CheckpointArchive(CheckpointLimits(max_bytes=1000)))
    with pytest.raises(SandboxError):
        await transfer.acapture(handle, state={})
    assert "fs.open rb" not in world.events


async def test_capture_of_a_replaced_session_is_not_sent(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, gtree: Dict[str, Any], store: FileCheckpointStore
) -> None:
    stale = SandboxHandle(**{**handle.__dict__, "name": "ag-1/an-older-session"})
    with pytest.raises(SandboxError, match="not running"):
        await sandbox.checkpoint_transfer(store).acapture(stale, state={})
    assert world.runs_of_the_guard == [] and world.stopped == []


def test_the_sync_wrappers_run_the_async_transfer(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fill(gtree["layout"])
    transfer = sandbox.checkpoint_transfer(store)
    reference = transfer.capture(handle, state={"binding": "b1"})
    _new_guest(world, tmp_path, monkeypatch, "guest-b")
    assert transfer.restore(handle, reference) == {"binding": "b1"}


async def test_a_checkpoint_restores_onto_a_fresh_computer_with_the_same_state(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fill(gtree["layout"])
    transfer = sandbox.checkpoint_transfer(store)
    reference = await transfer.acapture(handle, state={"binding": "b7"})
    second = _new_guest(world, tmp_path, monkeypatch, "guest-b")
    world.runs_of_the_guard.clear()
    assert await transfer.arestore(handle, reference) == {"binding": "b7"}
    layout = second["layout"]
    assert (layout.workspace / "notes.txt").read_text() == "hello" and (
        layout.native / "session.json"
    ).read_text() == "{}"
    assert world.runs_of_the_guard == ["restore"] and world.stopped == []
    assert not list(layout.inbox.iterdir()) and not list(layout.stage.iterdir())
    assert guard.Guard(layout).state() == "used"


async def test_the_same_checkpoint_restores_twice_onto_two_fresh_computers(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fill(gtree["layout"])
    transfer = sandbox.checkpoint_transfer(store)
    reference = await transfer.acapture(handle, state={"binding": "b1"})
    await transfer.acapture(handle, state={"binding": "b2"})  # a second capture on the same computer works
    for name in ("guest-b", "guest-c"):
        copy = _new_guest(world, tmp_path, monkeypatch, name)
        assert await transfer.arestore(handle, reference) == {"binding": "b1"}
        assert (copy["layout"].workspace / "deep/b.txt").read_text() == "b"


async def test_a_checkpoint_the_host_cannot_validate_never_reaches_the_computer(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
) -> None:
    garbage = tmp_path / "garbage.tar"
    garbage.write_bytes(b"not a checkpoint" * 100)
    reference = await store.aput(garbage)
    with pytest.raises(SandboxError):
        await sandbox.checkpoint_transfer(store).arestore(handle, reference)
    assert world.events == [] and world.stopped == []


async def test_a_checkpoint_missing_from_storage_leaves_the_computer_alone(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, gtree: Dict[str, Any], store: FileCheckpointStore
) -> None:
    from agno.sandbox.checkpoint import CheckpointObjectNotFound, CheckpointRef

    with pytest.raises(CheckpointObjectNotFound):
        await sandbox.checkpoint_transfer(store).arestore(handle, CheckpointRef(sha256="0" * 64, size=1))
    assert world.events == [] and world.stopped == []


async def test_restore_onto_a_replaced_session_is_not_sent_and_stops_nothing(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
) -> None:
    source = _source_tree(tmp_path, {"binding": "b"})
    reference = await store.aput(source)
    stale = SandboxHandle(**{**handle.__dict__, "name": "ag-1/an-older-session"})
    with pytest.raises(SandboxError, match="not running"):
        await sandbox.checkpoint_transfer(store).arestore(stale, reference)
    assert world.runs_of_the_guard == [] and world.stopped == []


async def test_restore_onto_a_computer_that_already_ran_fails_and_stops_it(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
) -> None:
    reference = await store.aput(_source_tree(tmp_path, {"binding": "b"}))
    assert _exec(gtree, lambda d, e: 0) == 0  # the computer has run a command
    with pytest.raises(SandboxError, match="not-fresh"):
        await sandbox.checkpoint_transfer(store).arestore(handle, reference)
    assert world.stopped == ["sess-1"]


async def test_a_restore_that_fails_inside_the_guard_stops_the_computer(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = await store.aput(_source_tree(tmp_path, {"binding": "b"}))

    def broken(limits: Any) -> Callable[[Path, Path], Dict[str, Any]]:
        def extract(archive: Path, destination: Path) -> Dict[str, Any]:
            raise SandboxError("disk full")

        return extract

    monkeypatch.setattr(guard, "_extract", broken)
    with pytest.raises(SandboxError, match="disk full"):
        await sandbox.checkpoint_transfer(store).arestore(handle, reference)
    assert world.stopped == ["sess-1"] and guard.Guard(gtree["layout"]).state() == "failed"
    assert not any(gtree["layout"].workspace.iterdir())


async def test_a_manifest_the_guest_reports_differently_is_an_error_and_stops_the_computer(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = await store.aput(_source_tree(tmp_path, {"binding": "b"}))
    monkeypatch.setattr(
        guard,
        "_extract",
        lambda limits: lambda archive, destination: {**REAL_EXTRACT(limits)(archive, destination), "binding": "other"},
    )
    with pytest.raises(SandboxError, match="differs"):
        await sandbox.checkpoint_transfer(store).arestore(handle, reference)
    assert world.stopped == ["sess-1"]


async def test_a_failed_upload_leaves_the_computer_untouched_and_running(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
) -> None:
    reference = await store.aput(_source_tree(tmp_path, {"binding": "b"}))
    world.fail["upload"] = ConnectionError("upload broke")
    with pytest.raises(SandboxError, match="stage"):
        await sandbox.checkpoint_transfer(store).arestore(handle, reference)
    assert world.runs_of_the_guard == [] and world.stopped == [] and guard.Guard(gtree["layout"]).state() == "fresh"


async def test_a_credentials_error_raised_before_the_restore_is_sent_stops_nothing(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
) -> None:
    sdk = pytest.importorskip("vercel.sandbox")
    reference = await store.aput(_source_tree(tmp_path, {"binding": "b"}))
    unresolved = sdk.SandboxCredentialsError("OIDC token expired")

    async def not_sent(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        raise unresolved  # the SDK resolves credentials before it sends the command

    world.script = not_sent
    with pytest.raises(SandboxError) as raised:
        await sandbox.checkpoint_transfer(store).arestore(handle, reference)
    assert world.stopped == [] and "session.stop" not in world.events, (
        "a restore that never started stopped the computer"
    )
    assert world.runs_of_the_guard == [] and guard.Guard(gtree["layout"]).state() == "fresh"
    assert raised.value.__cause__ is unresolved and "credentials" in str(raised.value)
    assert world.events.count("client.create") == world.events.count("client.aclose")


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("reset after the command was sent"),
        asyncio.TimeoutError(),
        type("SandboxCredentialsError", (Exception,), {})("a look-alike, not the SDK's class"),
        RuntimeError("could not resolve credentials"),
    ],
    ids=["connection", "timeout", "lookalike-class-name", "plain-text"],
)
async def test_any_other_failure_of_the_restore_command_still_stops_the_computer(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
    error: BaseException,
) -> None:
    if type(error).__name__ == "SandboxCredentialsError":
        pytest.importorskip("vercel.sandbox")  # the look-alike is only tested against the SDK's class being loaded
    reference = await store.aput(_source_tree(tmp_path, {"binding": "b"}))

    async def ambiguous(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        raise error

    world.script = ambiguous
    with pytest.raises(SandboxError):
        await sandbox.checkpoint_transfer(store).arestore(handle, reference)
    assert world.stopped == ["sess-1"]
    assert world.events.count("client.create") == world.events.count("client.aclose")


async def test_without_the_sdk_loaded_no_restore_failure_is_taken_for_a_credentials_error(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = await store.aput(_source_tree(tmp_path, {"binding": "b"}))
    monkeypatch.setitem(sys.modules, "vercel.sandbox", None)  # the SDK is not loaded: nothing is imported to look

    async def failed(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        raise ConnectionError("lost")

    world.script = failed
    with pytest.raises(SandboxError):
        await sandbox.checkpoint_transfer(store).arestore(handle, reference)
    assert world.stopped == ["sess-1"]


async def test_a_cancelled_restore_stops_the_computer_then_propagates(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    tmp_path: Path,
) -> None:
    reference = await store.aput(_source_tree(tmp_path, {"binding": "b"}))
    started = asyncio.Event()

    async def hang(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        started.set()
        await asyncio.sleep(30)
        return 0

    world.script = hang
    task = asyncio.create_task(sandbox.checkpoint_transfer(store).arestore(handle, reference))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert world.stopped == ["sess-1"]


#
# The live tests drive a real computer through a few helpers in the integration file. These tests run those
# helpers against fakes, to show that the orchestration cannot report success without having done what it
# claims. They validate the test code, not Vercel's Linux behavior or the guard's.


def _acceptance() -> Any:
    import importlib.util

    name = "vercel_acceptance_orchestration"
    if name not in sys.modules:
        path = Path(__file__).parents[2] / "integration/sandbox/test_vercel.py"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


class FakeComputers:
    """A provider that returns the handles it is given, and counts what is destroyed."""

    def __init__(self, *handles: SandboxHandle) -> None:
        self.handles, self.destroyed, self.calls = list(handles), [], 0

    async def acreate(self, session_id: str, **kwargs: Any) -> SandboxHandle:
        self.calls += 1
        return self.handles[min(self.calls, len(self.handles)) - 1]

    async def adestroy(self, handle: SandboxHandle) -> None:
        self.destroyed.append(handle.provider_ref)

    async def aget(self, ref: str) -> Optional[SandboxHandle]:
        return None


def _handle(ref: str) -> SandboxHandle:
    return SandboxHandle(
        provider_ref=ref,
        name=f"{ref}/s1",
        agent_id="coder",
        session_id="s",
        generation=1,
        state="running",
        config_digest="c",
    )


async def test_adoption_is_two_calls_but_one_computer() -> None:
    acceptance = _acceptance()
    tracker, same = acceptance.Tracker(), FakeComputers(_handle("box-1"))
    provider = tracker.watch(same)
    first, second = await provider.acreate("s"), await provider.acreate("s")
    assert len(tracker.created) == 2 and len(tracker.computers) == 1
    acceptance.assert_adopted(tracker, first, second)
    await tracker.cleanup()
    assert same.destroyed == ["box-1"]  # each physical computer is destroyed once


async def test_a_provider_that_makes_a_second_computer_cannot_pass_the_adoption_check() -> None:
    acceptance = _acceptance()
    tracker, other = acceptance.Tracker(), FakeComputers(_handle("box-1"), _handle("box-2"))
    provider = tracker.watch(other)
    first, second = await provider.acreate("s"), await provider.acreate("s")
    assert len(tracker.computers) == 2
    with pytest.raises(acceptance.AcceptanceFailure, match="another computer"):
        acceptance.assert_adopted(tracker, first, second)
    same_handle_but_two_computers = acceptance.Tracker()
    same_handle_but_two_computers.computers.update({"a": (other, first), "b": (other, second)})
    with pytest.raises(acceptance.AcceptanceFailure, match="2 computers"):
        acceptance.assert_adopted(same_handle_but_two_computers, first, first)
    await tracker.cleanup()
    assert sorted(other.destroyed) == ["box-1", "box-2"]


async def test_a_create_is_cancelled_at_bootstrap_entry_for_a_known_computer(
    world: World, sandbox: VercelSandbox
) -> None:
    acceptance = _acceptance()
    owned = await acceptance.cancel_at_bootstrap_entry(sandbox, "s", agent_id="coder", deadline=5)
    assert owned.name in world.destroyed and owned.name not in world.sandboxes
    assert world.stopped == [owned.session_id] and owned.session_id.startswith("sess-new-")
    assert world.root_commands == []  # cancelled at entry: no install command had run
    assert await sandbox.aget(owned.name) is None


async def test_a_create_whose_acknowledgement_is_still_pending_is_not_a_bootstrap_cancellation(
    world: World, sandbox: VercelSandbox
) -> None:
    acceptance = _acceptance()
    world.create_reply_gate = asyncio.Event()  # the service made the box; the reply has not come back
    with pytest.raises(acceptance.AcceptanceFailure, match="bootstrap was not entered"):
        await acceptance.cancel_at_bootstrap_entry(sandbox, "s", agent_id="coder", deadline=0.3)
    assert world.root_commands == []  # nothing was bootstrapped, and nothing claims cleanup of the unacknowledged box


async def test_a_cleanup_that_leaves_the_computer_behind_fails_the_cancellation_check(
    world: World, sandbox: VercelSandbox
) -> None:
    acceptance = _acceptance()
    world.fail["destroy"] = FakeApiError(500)
    with pytest.raises((acceptance.AcceptanceFailure, SandboxError)):
        await acceptance.cancel_at_bootstrap_entry(sandbox, "s", agent_id="coder", deadline=5)
    assert len(world.sandboxes) == 2  # the pre-existing one and the one cleanup could not remove


class ScriptedRun:
    def __init__(self, guest: "ScriptedGuest") -> None:
        self.guest, self.closed = guest, False
        guest.runs.append(self)

    async def close(self) -> None:
        self.closed = True

    async def finished(self) -> bool:
        return self.guest.outcome is not None

    async def outcome(self) -> Any:
        while self.guest.outcome is None:
            await asyncio.sleep(0.005)
        return self.guest.outcome


class ScriptedGuest:
    """A computer that follows a script, to check that the orchestration notices each way the script can go wrong."""

    GUARD_PID = 900

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.acceptance = _acceptance()
        self.writer = self.acceptance.Writer(321, "777")
        self.state, self.start, self.tick = "S", "777", 0
        self.outcome: Any = None
        self.requests: List[Any] = []
        self.staged: set = set()
        self.killed: List[int] = []
        self.journal: List[Any] = []
        self.polls = 0
        self.cleaned: List[Any] = []
        self.runs: List[ScriptedRun] = []
        self.next_ran = False
        self._frozen = False

    async def start_writer(self) -> Any:
        return self.writer

    async def stage_capture_request(self, name: str, request: Dict[str, Any]) -> None:
        self.requests.append(request)
        if self.mode != "no_request":
            self.staged.add(name)

    async def start_capture(self, name: str) -> Any:
        out = self.acceptance.CaptureOutcome
        if name not in self.staged:
            self.outcome = out(75, guard.REFUSAL_PREFIX + "not-staged: staged capture request is missing")
        elif self.mode == "unexpected_error":
            self.outcome = out(1, "Traceback: something else broke")
        elif self.mode == "finishes_first":
            self.outcome = out(0, "")
        return ScriptedRun(self)

    async def guard_pid(self, name: str) -> Optional[int]:
        return None if self.mode == "no_guard" else self.GUARD_PID

    async def journal_intents(self) -> List[Any]:
        self.polls += 1
        if self.mode != "no_freeze" and self.polls >= 2 and not self._frozen and self.outcome is None:
            self._frozen = True
            if self.mode != "journal_only":
                self.state = "T"
            if self.mode != "stopped_without_journal":
                self.journal.append((self.writer.pid, f"boot:{self.writer.start}"))
        return list(self.journal)

    async def process(self, pid: int) -> Optional[Any]:
        if self.mode == "stopped_without_journal" and self._frozen and not self.next_ran:
            return ("T", self.start)
        if self.mode == "other_writer" and self.next_ran:
            return (self.state, "888")
        return (self.state, self.start)

    async def kill(self, pid: int) -> None:
        self.killed.append(pid)
        if pid == self.GUARD_PID and self.outcome is None:
            code, text = (75, guard.REFUSAL_PREFIX + "busy") if self.mode == "refused_at_the_end" else (137, "")
            self.outcome = self.acceptance.CaptureOutcome(code, text)

    async def next_operation(self) -> None:
        self.next_ran = True
        if self.mode != "stays_stopped":
            self.state = "S"

    async def ticks(self) -> str:
        if self.state != "T" and self.mode != "resumes_without_progress":
            self.tick += 1
        return str(self.tick)

    async def cleanup(self, name: str, writer: Any) -> None:
        self.cleaned.append((name, writer))


async def _orchestrate(guest: Any, **kwargs: Any) -> Any:
    return await _acceptance().recover_a_capture_killed_while_frozen(
        guest, deadline=kwargs.pop("deadline", 2), poll=0.005, resume_deadline=kwargs.pop("resume_deadline", 0.3)
    )


async def test_a_capture_killed_while_frozen_is_recovered_and_the_same_writer_resumes() -> None:
    guest = ScriptedGuest()
    writer = await _orchestrate(guest)
    assert writer == guest.writer and guest.killed == [ScriptedGuest.GUARD_PID] and guest.next_ran
    assert guest.state == "S" and len(guest.cleaned) == 1 and guest.cleaned[0][1] == writer
    assert [run.closed for run in guest.runs] == [True]
    [request] = guest.requests  # the production request: the same keys and values the transfer sends
    assert set(request) == {"state", "exclude", "limits"} and request["exclude"] == list(VERCEL_NATIVE_EXCLUSIONS)
    assert request["limits"] == asdict(CheckpointLimits())


@pytest.mark.parametrize(
    "mode,message",
    [
        ("no_request", "ended \\(exit 75\\) before the frozen window"),
        ("unexpected_error", "ended \\(exit 1\\) before the frozen window"),
        ("finishes_first", "ended \\(exit 0\\) before the frozen window"),
        ("no_freeze", "never seen stopped"),
        ("journal_only", "never seen stopped"),
        ("stopped_without_journal", "never seen stopped"),
        ("resumes_without_progress", "did not resume"),
        ("no_guard", "guard process for this request was not found"),
        ("refused_at_the_end", "did not end by the kill"),
        ("stays_stopped", "did not resume"),
        ("other_writer", "different process"),
    ],
)
async def test_the_orchestration_fails_unless_it_actually_froze_killed_and_recovered(mode: str, message: str) -> None:
    guest = ScriptedGuest(mode)
    with pytest.raises(guest.acceptance.AcceptanceFailure, match=message):
        await _orchestrate(guest, deadline=0.3)
    assert len(guest.cleaned) == 1  # the writer and the staged files are cleaned up on every outcome
    assert all(run.closed for run in guest.runs)  # and so is every capture that was started
    assert guest.killed in ([], [ScriptedGuest.GUARD_PID])  # only the exact guard process is ever killed


async def test_a_create_that_returns_in_spite_of_its_cancellation_is_not_a_cancelled_create() -> None:
    acceptance = _acceptance()

    class Stubborn:
        async def acreate(self, session_id: str, **kwargs: Any) -> SandboxHandle:
            try:
                await self._bootstrap(types.SimpleNamespace(sandbox_name="box-1", id="s1"))
            except asyncio.CancelledError:
                return _handle("box-1")  # swallows the cancellation
            raise AssertionError("unreachable")

        async def aget(self, ref: str) -> Optional[SandboxHandle]:
            return None

    with pytest.raises(acceptance.AcceptanceFailure, match="returned although it was cancelled"):
        await acceptance.cancel_at_bootstrap_entry(Stubborn(), "s", agent_id="coder", deadline=2)  # type: ignore[arg-type]


async def test_a_missing_staged_request_is_the_old_tests_silent_success_and_is_now_a_failure() -> None:
    # The refusal the old test swallowed: the guard exits 75 before freezing anything.
    guest = ScriptedGuest("no_request")
    with pytest.raises(guest.acceptance.AcceptanceFailure):
        await _orchestrate(guest)
    assert guest.state == "S" and guest.journal == [] and guest.killed == []


#
# SdkGuest is what the hosted recovery test drives. These tests run the real adapter and the real orchestration
# against a fake SDK whose process methods are coroutines, as they are in the SDK; they check the host side
# only (the awaits, the process handle and the client lifetime), not Vercel or the guard.


class SdkWorld:
    """One computer as the recovery adapter sees it, and every SDK client opened against it."""

    PID, START, GUARD_PID = 321, "777", 900

    def __init__(self) -> None:
        self.clients: List["SdkClient"] = []
        self.create_calls: List[Any] = []
        self.root_calls: List[List[str]] = []
        self.exec_calls: List[List[str]] = []
        self.waits = 0
        self.state, self.tick, self.frozen = "S", 0, False
        self.ended = asyncio.Event()
        self.polling = asyncio.Event()
        self.lookup_error: Optional[BaseException] = None
        self.create_error: Optional[BaseException] = None
        self.poll_error: Optional[BaseException] = None
        self.poll_block: Optional[asyncio.Event] = None
        self.close_error: Optional[BaseException] = None
        self.never_freeze = False

    def new_client(self, options: Any) -> "SdkClient":
        client = SdkClient(self)
        self.clients.append(client)
        return client

    def open_clients(self) -> int:
        return sum(1 for client in self.clients if client.closes == 0)

    def root(self, argv: List[str]) -> str:
        self.root_calls.append(argv)
        if argv[:2] == ["cat", f"/proc/{self.PID}/stat"]:
            rest = " ".join(["0"] * 17 + [self.START])
            return f"{self.PID} (python) {self.state} 1 {rest}"
        if argv[0] == "cat" and argv[1].endswith("freeze.journal"):
            if not self.never_freeze and not self.frozen:
                self.frozen, self.state = True, "T"
            line = {"op": "intent", "pid": self.PID, "id": f"boot:{self.START}"}
            return json.dumps(line) + "\n" if self.frozen else ""
        if argv[0] == "sh":
            return f"{self.GUARD_PID}\n" if not self.ended.is_set() else ""
        if argv == ["kill", "-9", str(self.GUARD_PID)]:
            self.ended.set()
        if argv == ["cat", "/workspace/tick"]:
            self.tick += self.state != "T"
            return str(self.tick)
        return ""


class SdkProcess:
    """A started process: refresh, wait and communicate are coroutines, as in the SDK."""

    def __init__(self, world: SdkWorld) -> None:
        self.world = world

    @property
    def status(self) -> str:
        return "exited" if self.world.ended.is_set() else "running"

    async def refresh(self) -> "SdkProcess":
        self.world.polling.set()
        if self.world.poll_block is not None:
            await self.world.poll_block.wait()
        if self.world.poll_error is not None:
            raise self.world.poll_error
        return self

    async def wait(self) -> int:
        self.world.waits += 1
        await self.world.ended.wait()
        return 137

    async def communicate(self) -> Any:
        return None, ""


class SdkSession:
    def __init__(self, world: SdkWorld, client: "SdkClient") -> None:
        self.world, self.client = world, client
        self.fs = types.SimpleNamespace(write_bytes=self._write_bytes)

    async def _write_bytes(self, path: str, data: bytes, mode: Optional[int] = None) -> None:
        return None

    async def run_process(self, command: str, args: Sequence[str] = (), **kwargs: Any) -> Any:
        return types.SimpleNamespace(returncode=0, stdout=self.world.root([command, *args]))

    async def create_process(self, command: str, args: Sequence[str] = (), **kwargs: Any) -> SdkProcess:
        self.world.create_calls.append((command, list(args), kwargs))
        if self.world.create_error is not None:
            raise self.world.create_error
        self.client.owns_capture = True
        return SdkProcess(self.world)


class SdkClient:
    def __init__(self, world: SdkWorld) -> None:
        self.world, self.closes, self.owns_capture = world, 0, False

    async def get_sandbox(self, name: str) -> Any:
        if self.world.lookup_error is not None:
            raise self.world.lookup_error
        return types.SimpleNamespace(current_session=SdkSession(self.world, self))

    async def aclose(self) -> None:
        self.closes += 1
        if self.world.close_error is not None and self.owns_capture:  # only the capture's client fails to close
            raise self.world.close_error


class SdkProvider:
    """What SdkGuest needs of the provider: its options, and ordinary commands as the agent."""

    options = None

    def __init__(self, world: SdkWorld) -> None:
        self.world = world

    async def aexec(self, handle: SandboxHandle, argv: List[str], stdin: Optional[bytes] = None) -> Any:
        self.world.exec_calls.append(argv)
        if "nohup" in argv[-1]:
            return types.SimpleNamespace(stdout=f"{self.world.PID}\n")
        if argv == ["true"]:
            self.world.frozen, self.world.state = False, "S"  # admission recovers the interrupted capture
        return types.SimpleNamespace(stdout="")


@pytest.fixture
def sdk_world(monkeypatch: pytest.MonkeyPatch) -> SdkWorld:
    world = SdkWorld()
    monkeypatch.setattr(vercel_sandbox, "_new_client", world.new_client)
    return world


def _sdk_guest(world: SdkWorld) -> Any:
    return _acceptance().SdkGuest(SdkProvider(world), _handle("box-1"))


async def test_the_capture_process_is_created_awaited_and_is_what_gets_polled(sdk_world: SdkWorld) -> None:
    guest = _sdk_guest(sdk_world)
    run = await guest.start_capture("req")
    assert sdk_world.create_calls == [  # an un-awaited async create_process never runs its body, so records nothing
        (guard.PYTHON, ["-I", "-m", "agno.sandbox.vercel.guard", "capture", "req"], {"sudo": True})
    ]
    assert await run.finished() is False  # polled on the process the awaited call returned
    sdk_world.ended.set()
    assert await run.finished() is True
    assert (await run.outcome()).code == 137


@pytest.mark.parametrize(
    "where,error",
    [
        ("lookup", RuntimeError("no such sandbox")),
        ("create", RuntimeError("create refused")),
        ("create", asyncio.CancelledError()),
    ],
)
async def test_a_capture_that_cannot_start_closes_its_client(
    sdk_world: SdkWorld, where: str, error: BaseException
) -> None:
    setattr(sdk_world, f"{where}_error", error)
    with pytest.raises(type(error)):
        await _sdk_guest(sdk_world).start_capture("req")
    assert len(sdk_world.clients) == 1 and sdk_world.open_clients() == 0


async def test_a_failure_while_polling_closes_the_capture_client_and_stays_the_error(sdk_world: SdkWorld) -> None:
    guest = _sdk_guest(sdk_world)
    sdk_world.poll_error = OSError("poll broke")
    with pytest.raises(OSError, match="poll broke"):
        await _orchestrate(guest)
    assert sdk_world.open_clients() == 0
    assert sdk_world.waits == 0  # closing the client never waited for the remote process
    assert ["kill", "-9", str(sdk_world.PID)] in sdk_world.root_calls  # the writer is still cleaned up


async def test_a_frozen_window_that_never_opens_closes_the_capture_client(sdk_world: SdkWorld) -> None:
    sdk_world.never_freeze = True
    with pytest.raises(_acceptance().AcceptanceFailure, match="never seen stopped"):
        await _orchestrate(_sdk_guest(sdk_world), deadline=0.05)
    assert sdk_world.open_clients() == 0 and sdk_world.waits == 0


async def test_a_cancellation_before_the_outcome_closes_the_capture_client_and_propagates(sdk_world: SdkWorld) -> None:
    sdk_world.poll_block = asyncio.Event()  # the poll never answers
    task = asyncio.ensure_future(_orchestrate(_sdk_guest(sdk_world)))
    await asyncio.wait_for(sdk_world.polling.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sdk_world.open_clients() == 0 and sdk_world.waits == 0
    assert ["kill", "-9", str(sdk_world.PID)] in sdk_world.root_calls


async def test_a_client_that_fails_to_close_does_not_replace_the_error(sdk_world: SdkWorld) -> None:
    sdk_world.poll_error, sdk_world.close_error = OSError("poll broke"), RuntimeError("close broke")
    with pytest.raises(OSError, match="poll broke"):
        await _orchestrate(_sdk_guest(sdk_world))


async def test_the_writer_is_still_cleaned_up_when_closing_the_client_is_cancelled(sdk_world: SdkWorld) -> None:
    sdk_world.poll_error, sdk_world.close_error = OSError("poll broke"), asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await _orchestrate(_sdk_guest(sdk_world))
    assert ["kill", "-9", str(sdk_world.PID)] in sdk_world.root_calls


async def test_a_recovered_capture_closes_every_client_exactly_once(sdk_world: SdkWorld) -> None:
    guest = _sdk_guest(sdk_world)
    writer = await _orchestrate(guest)
    assert (writer.pid, writer.start) == (sdk_world.PID, sdk_world.START)
    assert len(sdk_world.create_calls) == 1 and sdk_world.waits == 1
    assert sdk_world.clients and all(client.closes == 1 for client in sdk_world.clients)


async def test_the_progress_probe_does_not_enter_the_guard(sdk_world: SdkWorld) -> None:
    # A probe through the provider would run the guard's admission and could itself recover the capture.
    guest = _sdk_guest(sdk_world)
    assert await guest.ticks() == "1" and await guest.ticks() == "2"
    assert sdk_world.exec_calls == [] and sdk_world.open_clients() == 0


def test_the_fake_service_matches_the_installed_sdk_signatures() -> None:
    """Skipped unless ``vercel-sandbox`` is importable: keeps the fake from drifting from the SDK."""
    pytest.importorskip("vercel.sandbox")
    from vercel.sandbox import SandboxClient
    from vercel.sandbox._internal.async_runtime import Sandbox, SandboxFilesystem, SandboxRuntimeSession

    def parameters(function: Any) -> Dict[str, Any]:
        return {name: p.default for name, p in inspect.signature(function).parameters.items() if name != "self"}

    assert parameters(FakeClient.get_sandbox).keys() == parameters(SandboxClient.get_sandbox).keys() - {
        "private_parameters"
    }
    assert parameters(FakeSession.run_process).keys() == parameters(SandboxRuntimeSession.run_process).keys()
    assert parameters(FakeFs.write_bytes) == parameters(SandboxFilesystem.write_bytes) | {}
    assert parameters(FakeSession.stop).keys() == parameters(SandboxRuntimeSession.stop).keys()
    assert "current_session" in dir(Sandbox) and "tags" in dir(Sandbox)
    assert inspect.signature(SandboxClient.create).parameters.keys() >= {"options"}
    assert not inspect.iscoroutinefunction(SandboxClient.create)

    # Creation, discovery, deletion and file transfer: the calls the lifecycle and the transfer make.
    import vercel.sandbox as sdk
    from vercel.sandbox._internal.async_filesystem_handle import SandboxBinaryReader, SandboxBinaryWriter

    assert {"name", "image", "persistent", "execution_time_limit", "resources", "tags"} <= parameters(
        SandboxClient.create_sandbox
    ).keys()
    assert not inspect.iscoroutinefunction(SandboxClient.create_sandbox) and hasattr(
        sdk.CreateSandboxOperation, "__await__"
    )
    # Both are used as ``async for`` over the call's result: the SDK's returns an iterator, the fake's is one.
    assert not inspect.iscoroutinefunction(SandboxClient.query_sandboxes) and inspect.isasyncgenfunction(
        FakeClient.query_sandboxes
    )
    assert parameters(FakeClient.query_sandboxes).keys() == parameters(SandboxClient.query_sandboxes).keys()
    assert parameters(FakeSandbox.destroy).keys() == parameters(Sandbox.destroy).keys()
    assert parameters(FakeFs.mkdir).keys() == parameters(SandboxFilesystem.mkdir).keys()
    assert {"size", "permissions"} <= parameters(SandboxFilesystem.open).keys()
    assert parameters(FakeResources.__init__).keys() == inspect.signature(sdk.SandboxResources).parameters.keys()
    assert parameters(FakeNamePrefix.__init__).keys() == inspect.signature(sdk.SandboxQueryByName).parameters.keys()
    assert "read" in dir(SandboxBinaryReader) and "write" in dir(SandboxBinaryWriter)
    assert {"name", "tags", "persistent", "created_at", "current_session_id", "status"} <= set(dir(Sandbox))
    # What the live crash-recovery orchestration calls on a started process and on the session.
    from vercel.sandbox._internal.async_runtime import Process

    assert {"create_process", "sandbox_name"} <= set(dir(SandboxRuntimeSession))
    assert {"refresh", "wait", "communicate", "status", "returncode"} <= set(dir(Process))
    # Starting a process and following it are coroutines: a call that is not awaited does nothing.
    for coroutine_function in (
        SandboxRuntimeSession.create_process,
        SandboxRuntimeSession.run_process,
        Process.refresh,
        Process.wait,
        Process.communicate,
    ):
        assert inspect.iscoroutinefunction(coroutine_function), coroutine_function
    assert {"capture_output", "kill_after", "sudo"} <= parameters(SandboxRuntimeSession.run_process).keys()
    # The real types accept what the provider builds from them.
    assert vercel_sandbox._sdk().SandboxQueryByName(name_prefix="ag-0123456789-").name_prefix == "ag-0123456789-"
    assert vercel_sandbox._sdk().SandboxResources(vcpus=2, memory=4096).vcpus == 2


async def test_a_credentials_failure_before_sending_raises_without_stopping_the_session(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle
) -> None:
    sdk = pytest.importorskip("vercel.sandbox")

    async def unresolved(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        raise sdk.SandboxCredentialsError("OIDC token expired")

    world.script = unresolved
    with pytest.raises(SandboxError) as raised:
        await sandbox.aexec(handle, ["ls"])
    assert world.stopped == [] and "session.stop" not in world.events
    assert world.events == [*NOT_SENT[:2], "fs.write_bytes", "run_process", "client.aclose"]
    assert isinstance(raised.value.__cause__, sdk.SandboxCredentialsError)
    assert "credentials" in str(raised.value)


#
# The SDK marks its session closed and the pool empties its connection list before either finishes closing,
# so a close that is abandoned part-way cannot be repeated. These tests use the real client and pool, with two
# controlled connection objects in the pool and a stubbed lookup; nothing connects anywhere.


class _PoolConnection:
    """A connection in the real pool: its close can be held open, made to fail, or never finish."""

    def __init__(self, gate: Optional[asyncio.Event] = None, fail: Optional[BaseException] = None) -> None:
        self.gate, self.fail = gate, fail
        self.entered = asyncio.Event()
        self.closed = False
        self.interrupted = False

    async def aclose(self) -> None:
        self.entered.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
            if self.fail is not None:
                raise self.fail
        except asyncio.CancelledError:
            self.interrupted = True
            raise
        finally:
            self.closed = True


def _real_client_world(
    monkeypatch: pytest.MonkeyPatch, connections: List[_PoolConnection], *, then: Optional[BaseException] = None
) -> VercelSandbox:
    pytest.importorskip("vercel.sandbox")
    sandbox = VercelSandbox()

    async def read(client: Any, physical: str) -> None:
        # The lookup the provider makes, answered as a 404 would be, with the real pool holding the connections.
        pool = client._session._client_for_running_loop()._transport._pool
        pool._connections = list(connections)
        if then is not None:
            raise then
        return None

    monkeypatch.setattr(sandbox, "_read", read)
    return sandbox


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_a_normal_teardown_closes_every_connection_of_the_real_client(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = _PoolConnection(), _PoolConnection()
    sandbox = _real_client_world(monkeypatch, [first, second])
    assert await sandbox.aget("ag-0123456789-abcdef") is None
    assert first.closed and second.closed and not first.interrupted


@pytest.mark.parametrize("cancellations", [1, 2], ids=["single-cancel", "repeated-cancel"])
async def test_cancelling_during_teardown_still_closes_every_connection_and_stays_a_cancellation(
    monkeypatch: pytest.MonkeyPatch, cancellations: int
) -> None:
    gate = asyncio.Event()
    first, second = _PoolConnection(gate), _PoolConnection()
    sandbox = _real_client_world(monkeypatch, [first, second])
    task = asyncio.ensure_future(sandbox.aget("ag-0123456789-abcdef"))
    await asyncio.wait_for(first.entered.wait(), 5)
    for _ in range(cancellations):
        task.cancel()
        await _settle()
    assert not task.done(), "the cancellation abandoned the close that was in progress"
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert first.closed and second.closed and not first.interrupted


async def test_a_failed_teardown_does_not_replace_the_operation_error_that_is_unwinding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = _PoolConnection(fail=RuntimeError("close failed")), _PoolConnection()
    sandbox = _real_client_world(monkeypatch, [first, second], then=ValueError("the lookup failed"))
    with pytest.raises(ValueError, match="the lookup failed"):
        await sandbox.aget("ag-0123456789-abcdef")
    assert first.closed


async def test_a_failed_teardown_after_a_finished_operation_is_logged_and_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: List[str] = []
    monkeypatch.setattr(vercel_sandbox, "log_warning", warnings.append)
    sandbox = _real_client_world(monkeypatch, [_PoolConnection(fail=RuntimeError("close failed"))])
    assert await sandbox.aget("ag-0123456789-abcdef") is None
    assert any("Could not close the Vercel SDK client" in line and "close failed" in line for line in warnings)


async def test_a_teardown_that_never_finishes_is_given_up_after_a_bound_and_the_cancellation_still_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vercel_sandbox, "_CLOSE_GRACE", 0.2)
    warnings: List[str] = []
    monkeypatch.setattr(vercel_sandbox, "log_warning", warnings.append)
    loop = asyncio.get_running_loop()
    unobserved: List[Dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, context: unobserved.append(context))
    gate = asyncio.Event()
    stuck = _PoolConnection(gate, fail=RuntimeError("late failure"))
    sandbox = _real_client_world(monkeypatch, [stuck])
    task = asyncio.ensure_future(sandbox.aget("ag-0123456789-abcdef"))
    await asyncio.wait_for(stuck.entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert any("still closing" in line for line in warnings)
    gate.set()  # the abandoned close now fails; nobody is waiting for it
    await _settle()
    gc.collect()
    await _settle()
    assert unobserved == [], "the abandoned close left an exception nobody retrieved"


#
# The first live smoke run reported "the agent can read /opt/agno/ENV" for a 0600 root-owned file. The probe
# was `ls P || cat P`: for a regular file under a traversable parent, ls succeeds from a stat alone, so cat never
# ran. These tests run the live test's real probe on synthetic local paths. A same-user chmod shows that the
# probe classifies a denial correctly; it is not evidence about root-versus-agent isolation in the guest, which
# only a live run can show.

_SECRET = "SYNTHETIC-SECRET-9f3a41"
_needs_unprivileged = pytest.mark.skipif(os.geteuid() == 0, reason="chmod does not deny a privileged user")


class _LocalComputer:
    """Runs the argv the live test builds, for real, on this machine."""

    def __init__(self) -> None:
        self.calls: List[List[str]] = []

    async def aexec(self, handle: Any, argv: Sequence[str], **kwargs: Any) -> Any:
        argv = [sys.executable if argv[0] == "python" else argv[0], *argv[1:]]
        self.calls.append(list(argv))
        done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        return ExecResult(stdout=done.stdout, stderr=done.stderr, exit_code=done.returncode, timed_out=False)


class _ProtectedTree:
    """A synthetic /opt/agno: a traversable parent with one unreadable file and four unlistable directories."""

    def __init__(self, root: Path) -> None:
        self.parent = root / "agno"
        self.parent.mkdir(mode=0o755)
        self.env = self.parent / "ENV"
        self.env.write_text(_SECRET)
        self.env.chmod(0o000)
        self.dirs = {name: self.parent / name for name in ("control", "inbox", "export", "stage")}
        for directory in self.dirs.values():
            directory.mkdir()
            (directory / "entry").write_text(_SECRET)
            directory.chmod(0o000)
        self.paths = tuple(
            str(p) for p in (self.dirs["control"], self.env, *[self.dirs[n] for n in ("inbox", "export", "stage")])
        )

    def restore(self) -> None:
        for target in (*self.dirs.values(), self.env):
            if target.exists():
                target.chmod(0o755)


@pytest.fixture
def protected_tree(tmp_path: Path):
    tree = _ProtectedTree(tmp_path)
    yield tree
    tree.restore()


@_needs_unprivileged
async def test_a_file_that_lists_but_cannot_be_opened_is_a_denial(protected_tree: _ProtectedTree) -> None:
    acceptance = _acceptance()
    seen = await acceptance.assert_control_paths_denied(_LocalComputer(), None, protected_tree.paths)
    assert sorted(seen) == sorted(protected_tree.paths)


@_needs_unprivileged
async def test_a_readable_file_fails_and_its_content_is_never_emitted(protected_tree: _ProtectedTree) -> None:
    acceptance = _acceptance()
    protected_tree.env.chmod(0o644)
    with pytest.raises(acceptance.AcceptanceFailure, match="open for reading .*ENV") as failure:
        await acceptance.assert_control_paths_denied(_LocalComputer(), None, protected_tree.paths)
    assert _SECRET not in str(failure.value)
    protected_tree.env.write_text("")  # an empty file is just as reachable
    with pytest.raises(acceptance.AcceptanceFailure, match="open for reading .*ENV"):
        await acceptance.assert_control_paths_denied(_LocalComputer(), None, protected_tree.paths)


@_needs_unprivileged
@pytest.mark.parametrize("mode,words", [(0o755, "list"), (0o111, "traverse"), (0o444, "list")])
async def test_listing_and_entering_a_directory_are_tested_separately(
    protected_tree: _ProtectedTree, mode: int, words: str
) -> None:
    acceptance = _acceptance()
    protected_tree.dirs["export"].chmod(mode)
    with pytest.raises(acceptance.AcceptanceFailure, match=f"{words} .*export"):
        await acceptance.assert_control_paths_denied(_LocalComputer(), None, protected_tree.paths)


@_needs_unprivileged
async def test_a_missing_or_wrong_kind_of_target_is_a_failure_not_a_denial(protected_tree: _ProtectedTree) -> None:
    acceptance = _acceptance()
    protected_tree.env.unlink()
    with pytest.raises(acceptance.AcceptanceFailure, match="ENV is missing"):
        await acceptance.assert_control_paths_denied(_LocalComputer(), None, protected_tree.paths)
    protected_tree.env.mkdir(mode=0o000)
    with pytest.raises(acceptance.AcceptanceFailure, match="ENV is a directory"):
        await acceptance.assert_control_paths_denied(_LocalComputer(), None, protected_tree.paths)


async def test_the_live_test_does_not_pass_when_the_protected_paths_do_not_exist() -> None:
    acceptance = _acceptance()
    assert not Path("/opt/agno").exists()  # this machine is not a bootstrapped computer

    class Computer(_LocalComputer):
        async def aexec(self, handle: Any, argv: Sequence[str], **kwargs: Any) -> Any:
            if argv[:2] == ["sh", "-c"] and "NoNewPrivs" in argv[2]:  # the guest-only part of the same test
                return ExecResult(
                    stdout="NoNewPrivs:\t1\nCapEff:\t0000000000000000\n", stderr="", exit_code=0, timed_out=False
                )
            return await super().aexec(handle, argv, **kwargs)

    with pytest.raises(acceptance.AcceptanceFailure, match="missing"):
        await acceptance.test_the_agent_cannot_reach_the_control_state_or_the_staging_directories((Computer(), None))


@pytest.mark.parametrize(
    "stdout,exit_code,timed_out",
    [("", 1, False), ("not json", 0, False), ("[]", 0, False), ("{}", 0, False), ("", 0, True)],
)
async def test_a_probe_that_fails_to_run_or_answers_badly_is_a_failure(
    stdout: str, exit_code: int, timed_out: bool
) -> None:
    acceptance = _acceptance()

    class Broken:
        async def aexec(self, handle: Any, argv: Sequence[str], **kwargs: Any) -> Any:
            return ExecResult(stdout=stdout, stderr="", exit_code=exit_code, timed_out=timed_out)

    with pytest.raises(acceptance.AcceptanceFailure):
        await acceptance.assert_control_paths_denied(Broken(), None, ("/x/control", "/x/ENV"))


@pytest.mark.parametrize(
    "answer",
    [
        {"kind": "file", "ops": {"read_open": "error:EIO"}},
        {"kind": "file", "ops": {"read_open": "allowed"}},
        {"kind": "file", "ops": {}},
        {"kind": "file"},
        {"kind": "missing"},
        {"kind": "dir", "ops": {"list": "denied", "traverse": "denied"}},
        "denied",
        None,
    ],
)
async def test_only_a_clean_denial_of_the_environment_file_passes(answer: Any) -> None:
    acceptance = _acceptance()
    good_dir = {"kind": "dir", "ops": {"list": "denied", "traverse": "denied"}}

    class Scripted:
        async def aexec(self, handle: Any, argv: Sequence[str], **kwargs: Any) -> Any:
            return ExecResult(
                stdout=json.dumps({"/x/control": good_dir, "/x/ENV": answer}), stderr="", exit_code=0, timed_out=False
            )

    with pytest.raises(acceptance.AcceptanceFailure):
        await acceptance.assert_control_paths_denied(Scripted(), None, ("/x/control", "/x/ENV"))


@_needs_unprivileged
async def test_an_unexpected_io_error_in_the_guest_probe_is_reported_by_name(
    protected_tree: _ProtectedTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    acceptance = _acceptance()
    namespace: Dict[str, Any] = {"__name__": "probe"}
    exec(compile(acceptance.CONTROL_PROBE, "probe", "exec"), namespace)

    def broken(path: Any, flags: Any, *args: Any) -> Any:
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(os, "open", broken)
    answer = namespace["probe"]([str(protected_tree.env)])
    assert answer[str(protected_tree.env)]["ops"]["read_open"] == "error:EIO"


def _example() -> Any:
    import importlib.util

    path = Path(__file__).parents[5] / "cookbook" / "frameworks" / "sandbox" / "vercel" / "vercel_session.py"
    spec = importlib.util.spec_from_file_location("vercel_session_example", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _StopAfterProvider(Exception):
    pass


@pytest.fixture
def evict_modules_imported_under_a_stub() -> Any:
    """Modules first imported while a test stubs ``sys.modules`` would keep the stub's names for the whole session."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.startswith("agno."):
            del sys.modules[name]


@pytest.mark.parametrize(
    "harness,variables,expected",
    [
        (
            "claude",
            {"ANTHROPIC_API_KEY": "k1", "CLAUDE_CODE_OAUTH_TOKEN": "k2", "OTHER": "x"},
            {"ANTHROPIC_API_KEY": "k1", "CLAUDE_CODE_OAUTH_TOKEN": "k2"},
        ),
        ("codex", {"OPENAI_API_KEY": "k3", "ANTHROPIC_API_KEY": "no"}, {"OPENAI_API_KEY": "k3"}),
        ("fixture", {"ANTHROPIC_API_KEY": "no"}, {"AGNO_SANDBOX_TEST_RUNTIME": "1"}),
    ],
)
def test_public_mode_puts_only_the_harnesss_model_key_in_the_computers_environment(
    evict_modules_imported_under_a_stub: None,
    monkeypatch: pytest.MonkeyPatch,
    harness: str,
    variables: Dict[str, str],
    expected: Dict[str, str],
) -> None:
    example = _example()
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    seen: Dict[str, Any] = {}

    def provider(**kwargs: Any) -> Any:
        seen.update(kwargs)
        raise _StopAfterProvider

    monkeypatch.setattr(example, "VercelSandbox", provider)
    stub = types.ModuleType("agno.db.postgres")
    stub.PostgresDb = lambda **kwargs: object()  # type: ignore[attr-defined]
    stub.__getattr__ = lambda name: object  # type: ignore[attr-defined]  # anything else the importers ask for
    monkeypatch.setitem(sys.modules, "agno.db.postgres", stub)
    args = types.SimpleNamespace(harness=harness, model=None)
    with pytest.raises(_StopAfterProvider):
        example.run_public(args, None)
    assert seen["env"] == expected


class _ExampleComputer:
    def __init__(self, ref: str) -> None:
        self.provider_ref = ref


class _ExampleSandbox:
    """The provider calls the example's direct mode makes; ``destroy_errors`` maps a ref to errors for its calls."""

    def __init__(self, destroy_errors: Optional[Dict[str, List[Optional[BaseException]]]] = None) -> None:
        self.destroy_errors = {ref: list(errors) for ref, errors in (destroy_errors or {}).items()}
        self.created = 0
        self.destroy_attempts: List[str] = []

    def create(self, session_id: str, **kwargs: Any) -> _ExampleComputer:
        if kwargs.get("generation", 1) == 1 and self.created:
            return _ExampleComputer("ref-0")  # a repeated create of the same session finds the same computer
        ref = f"ref-{self.created}"
        self.created += 1
        return _ExampleComputer(ref)

    def destroy(self, handle: _ExampleComputer) -> None:
        self.destroy_attempts.append(handle.provider_ref)
        errors = self.destroy_errors.get(handle.provider_ref)
        error = errors.pop(0) if errors else None
        if error is not None:
            raise error

    def exec(self, handle: Any, argv: Any) -> Any:
        return types.SimpleNamespace(stdout="notes.txt\n")


def _direct_example(monkeypatch: pytest.MonkeyPatch, sandbox: _ExampleSandbox, *, work: Any = None) -> Any:
    example = _example()
    monkeypatch.setattr(example, "VercelSandbox", lambda **kwargs: sandbox)
    monkeypatch.setattr(example, "SandboxRuntimeClient", lambda provider: object())
    monkeypatch.setattr(example, "FileCheckpointStore", lambda path: object())

    class Transfer:
        def __init__(self, provider: Any, store: Any) -> None:
            pass

        def capture(self, handle: Any, state: Any) -> Any:
            return types.SimpleNamespace(sha256="a" * 64, size=1)

        def restore(self, handle: Any, reference: Any) -> Dict[str, int]:
            return {"turn": 1}

    monkeypatch.setattr(example, "VercelCheckpointTransfer", Transfer)
    monkeypatch.setattr(example, "run_turn", work or (lambda *args, **kwargs: "ok"))
    return example


_DIRECT_ARGS = types.SimpleNamespace(harness="fixture", model=None, replace=True)


def test_the_example_still_destroys_the_other_computer_when_one_destroy_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The source was destroyed during --replace; the final cleanup visits it again and it fails that time.
    sandbox = _ExampleSandbox({"ref-0": [None, RuntimeError("transient")]})
    example = _direct_example(monkeypatch, sandbox)
    with pytest.raises(RuntimeError) as raised:
        example.run_direct(_DIRECT_ARGS, None)
    assert sandbox.destroy_attempts == ["ref-0", "ref-0", "ref-1"], "the destination was never attempted"
    assert "ref-0" in str(raised.value)
    output = capsys.readouterr()
    assert "Destroyed ref-1" in output.out and "Destroyed ref-0" not in output.out
    assert "ref-0" in output.err and "transient" in output.err


def test_the_example_reports_every_failed_destroy_and_claims_none_it_did_not_do(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sandbox = _ExampleSandbox({"ref-0": [None, RuntimeError("first")], "ref-1": [RuntimeError("second")]})
    example = _direct_example(monkeypatch, sandbox)
    with pytest.raises(RuntimeError) as raised:
        example.run_direct(_DIRECT_ARGS, None)
    assert sandbox.destroy_attempts == ["ref-0", "ref-0", "ref-1"], "a computer was never attempted"
    assert "ref-0" in str(raised.value) and "ref-1" in str(raised.value)
    assert "Destroyed ref-1" not in capsys.readouterr().out


def test_the_example_keeps_the_work_failure_when_cleanup_also_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class WorkFailed(Exception):
        pass

    def work(client: Any, computer: Any, number: int, *args: Any) -> str:
        if number == 2:
            raise WorkFailed("turn 2 failed")
        return "ok"

    sandbox = _ExampleSandbox({"ref-1": [RuntimeError("cleanup failed")]})
    example = _direct_example(monkeypatch, sandbox, work=work)
    with pytest.raises(WorkFailed, match="turn 2 failed"):
        example.run_direct(_DIRECT_ARGS, None)
    assert "ref-1" in capsys.readouterr().err


def test_the_example_destroys_everything_and_raises_nothing_when_cleanup_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sandbox = _ExampleSandbox()
    example = _direct_example(monkeypatch, sandbox)
    example.run_direct(_DIRECT_ARGS, None)
    assert sandbox.destroy_attempts == ["ref-0", "ref-0", "ref-1"]
    assert capsys.readouterr().err == ""


def _live_test_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The live acceptance module, imported for its cleanup helper only; no hosted test is collected or run."""
    import importlib.util

    for name in ("AGNO_TEST_VERCEL", "AGNO_TEST_VERCEL_WHEEL", "AGNO_TEST_SANDBOX_DB_URL"):
        monkeypatch.delenv(name, raising=False)
    path = Path(__file__).parents[2] / "integration" / "sandbox" / "test_vercel.py"
    spec = importlib.util.spec_from_file_location("vercel_live_acceptance_for_cleanup", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as error:  # the live module needs the database extras only to be imported
        pytest.skip(f"the live acceptance module cannot be imported here: {error}")
    return module


class _TrackedProvider:
    def __init__(
        self, destroy_errors: Optional[Dict[str, BaseException]] = None, lingering: Sequence[str] = ()
    ) -> None:
        self.destroy_errors = destroy_errors or {}
        self.lingering = set(lingering)
        self.destroyed: List[str] = []

    async def adestroy(self, handle: Any) -> None:
        self.destroyed.append(handle.provider_ref)
        if handle.provider_ref in self.destroy_errors:
            raise self.destroy_errors[handle.provider_ref]

    async def aget(self, ref: str) -> Any:
        return object() if ref in self.lingering else None


def _tracked(module: Any, provider: _TrackedProvider, *refs: str) -> Any:
    tracker = module.Tracker()
    for ref in refs:
        tracker.computers[ref] = (provider, types.SimpleNamespace(provider_ref=ref))
    return tracker


async def test_the_live_tracker_destroys_the_second_computer_when_the_first_destroy_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _live_test_module(monkeypatch)
    provider = _TrackedProvider({"ref-a": RuntimeError("transient")})
    with pytest.raises(AssertionError) as raised:
        await _tracked(module, provider, "ref-a", "ref-b").cleanup()
    assert provider.destroyed == ["ref-a", "ref-b"], "the second computer was never attempted"
    assert "ref-a" in str(raised.value) and "transient" in str(raised.value)


async def test_the_live_tracker_continues_after_a_computer_that_is_still_there_after_its_destroy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _live_test_module(monkeypatch)
    provider = _TrackedProvider(lingering=["ref-a"])
    with pytest.raises(AssertionError) as raised:
        await _tracked(module, provider, "ref-a", "ref-b").cleanup()
    assert provider.destroyed == ["ref-a", "ref-b"], "the later computer was never attempted"
    assert "ref-a" in str(raised.value)


async def test_the_live_tracker_names_every_computer_that_could_not_be_cleaned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _live_test_module(monkeypatch)
    provider = _TrackedProvider({"ref-a": RuntimeError("one")}, lingering=["ref-c"])
    with pytest.raises(AssertionError) as raised:
        await _tracked(module, provider, "ref-a", "ref-b", "ref-c").cleanup()
    assert provider.destroyed == ["ref-a", "ref-b", "ref-c"], "a computer was never attempted"
    assert "ref-a" in str(raised.value) and "ref-c" in str(raised.value) and "ref-b" not in str(raised.value)


async def test_the_live_tracker_is_quiet_when_every_computer_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _live_test_module(monkeypatch)
    provider = _TrackedProvider()
    await _tracked(module, provider, "ref-a", "ref-b").cleanup()
    assert provider.destroyed == ["ref-a", "ref-b"]


#
# On current main, ``CheckpointArchive.capture`` keeps a symlink to an absolute path verbatim (a virtualenv's
# interpreter link, say) and ``CheckpointArchive.restore`` leaves it out unless ``absolute_links=True``, which is
# only right inside the computer the roots belong to. The guard's extraction runs there, as root, in staging the
# agent cannot reach. Targets below are synthetic paths inside the test's own temporary directory.


def _absolute_link_tree(tmp_path: Path, target: str) -> Path:
    def extra(workspace: Path, native: Path) -> None:
        (workspace / "abs").symlink_to(target)
        (native / "abs-native").symlink_to(target)

    return _source_tree(tmp_path, {"binding": "abs"}, extra)


def test_an_absolute_symlink_survives_capture_and_a_restore_through_the_guards_extraction(
    box: Dict[str, Any], tmp_path: Path
) -> None:
    layout = box["layout"]
    target = str(tmp_path / "synthetic-target-that-does-not-exist-on-the-host")
    _stage_archive(layout, _absolute_link_tree(tmp_path, target))
    assert _restore(box) == {"binding": "abs"}
    for link in (layout.workspace / "abs", layout.native / "abs-native"):
        assert link.is_symlink(), f"{link.name} was silently left out of the restore"
        assert os.readlink(link) == target
    assert (layout.workspace / "link").is_symlink() and os.readlink(layout.workspace / "link") == "a.txt"
    assert box["guard"].state() == "used"


def test_an_absolute_link_is_materialized_without_creating_or_touching_its_target(
    box: Dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = box["layout"]
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    (outside / "keep.txt").write_text("not the agent's")
    (outside / "keep.txt").chmod(0o640)
    before = sorted(p.name for p in outside.iterdir()), (outside / "keep.txt").stat().st_mode
    handed: List[Any] = []
    real = os.chown
    monkeypatch.setattr(
        os, "chown", lambda path, uid, gid, **kw: (handed.append((str(path), kw)), real(path, uid, gid, **kw))[1]
    )
    _stage_archive(layout, _absolute_link_tree(tmp_path, str(outside)))
    _restore(box)
    assert os.readlink(layout.workspace / "abs") == str(outside)
    assert sorted(p.name for p in outside.iterdir()) == before[0] and (outside / "keep.txt").stat().st_mode == before[1]
    linked = [entry for entry in handed if entry[0].endswith("/abs") or entry[0].endswith("/abs-native")]
    assert linked and all(kw.get("follow_symlinks") is False for _, kw in linked), "a link was followed by the handoff"
    assert not any(str(outside) in path for path, _ in handed)


def test_an_archive_cannot_write_through_an_absolute_link_to_a_directory_outside_staging(
    box: Dict[str, Any], tmp_path: Path
) -> None:
    layout = box["layout"]
    outside = tmp_path / "outside-dir"
    outside.mkdir()

    def build(tar: tarfile.TarFile) -> None:
        _link("workspace/d", str(outside))(tar)
        _file("workspace/d/planted.txt")(tar)

    staged = layout.inbox / f"{CHECKPOINT_NAME}.tar"
    staged.write_bytes(_hostile(tmp_path, build).read_bytes())
    staged.chmod(0o600)
    with pytest.raises(SandboxError):
        _restore(box)
    assert not list(outside.iterdir()) and not list(tmp_path.rglob("planted.txt"))
    assert box["guard"].state() == "failed" and not any(layout.workspace.iterdir())


def test_a_failed_extraction_with_absolute_links_exposes_no_partial_roots(box: Dict[str, Any], tmp_path: Path) -> None:
    layout = box["layout"]

    def build(tar: tarfile.TarFile) -> None:
        _link("workspace/abs", str(tmp_path / "somewhere"))(tar)
        _file("outside-roots/file.txt")(tar)  # refused: not under a declared root

    staged = layout.inbox / f"{CHECKPOINT_NAME}.tar"
    staged.write_bytes(_hostile(tmp_path, build).read_bytes())
    staged.chmod(0o600)
    with pytest.raises(SandboxError):
        _restore(box)
    assert box["guard"].state() == "failed"
    assert not any(layout.workspace.iterdir()) and not any(layout.native.iterdir())
    assert not list(layout.stage.iterdir())


def test_a_used_or_nonempty_computer_still_refuses_an_archive_with_absolute_links(
    box: Dict[str, Any], tmp_path: Path
) -> None:
    layout = box["layout"]
    _stage_archive(layout, _absolute_link_tree(tmp_path, str(tmp_path / "t")))
    (layout.workspace / "already.txt").write_text("x")
    with pytest.raises(guard.Refused) as refused:
        _restore(box)
    assert refused.value.code == "not-empty" and not (layout.workspace / "abs").exists()


def test_only_the_guards_extraction_enables_absolute_links(box: Dict[str, Any], tmp_path: Path) -> None:
    import ast

    calls: List[str] = []
    for path in Path(guard.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.keyword) and node.arg == "absolute_links":
                calls.append(path.name)
    assert calls == ["guard.py"], f"absolute_links is passed outside the guard's in-computer extraction: {calls}"
    host = CheckpointArchive()
    restored = tmp_path / "host-restore"
    host.restore(_absolute_link_tree(tmp_path, str(tmp_path / "t")), restored)
    assert not (restored / "workspace" / "abs").is_symlink(), "a host-side restore must still leave absolute links out"


#
# The coordinator reads ``sandbox.retain_checkpoints`` when it is built (``_harness.coordinator``) and validates it
# with the shared ``_retention``. Pruning itself is covered provider-independently by the shared coordinator tests;
# these tests cover only that Vercel accepts, validates and passes the same option the other providers do.


def _coordinator_for(sandbox: VercelSandbox) -> Any:
    from agno.agents.claude import ClaudeAgent
    from agno.db.postgres import PostgresDb
    from agno.sandbox import _harness

    db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:1/ai")  # built, never connected
    return _harness.coordinator(ClaudeAgent(id="coder", db=db, sandbox=sandbox))


def test_the_default_retention_is_the_shared_default_and_reaches_the_coordinator(tmp_path: Path) -> None:
    sandbox = VercelSandbox(checkpoints=FileCheckpointStore(tmp_path / "objects"))
    assert sandbox.retain_checkpoints == 3
    assert _coordinator_for(sandbox).retain_checkpoints == 3


@pytest.mark.parametrize("value", [1, 2, 10, None], ids=["one", "two", "ten", "keep-all"])
def test_a_retention_setting_is_accepted_and_reaches_the_coordinator(tmp_path: Path, value: Optional[int]) -> None:
    sandbox = VercelSandbox(checkpoints=FileCheckpointStore(tmp_path / "objects"), retain_checkpoints=value)
    assert sandbox.retain_checkpoints == value
    assert _coordinator_for(sandbox).retain_checkpoints == value


@pytest.mark.parametrize("invalid", [0, -1, 1.5, True, "3"], ids=["zero", "negative", "float", "bool", "text"])
def test_an_invalid_retention_fails_the_constructor_before_anything_is_touched(
    invalid: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def touched(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the SDK was reached before the retention was validated")

    monkeypatch.setattr(vercel_sandbox, "_new_client", touched)
    with pytest.raises(ValueError, match="retain_checkpoints"):
        VercelSandbox(retain_checkpoints=invalid)


def test_the_retention_option_is_keyword_only_like_the_rest_of_the_constructor() -> None:
    import inspect

    parameter = inspect.signature(VercelSandbox.__init__).parameters["retain_checkpoints"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default == 3


#
# Main's coordinator ends a turn whose files cannot be checkpointed when ``transfer.acapture`` raises
# ``CheckpointContentError`` (a retry would fail the same way and keep the session busy). Vercel's capture runs in a
# child process in the guest, so the type has to cross a process boundary as an exit status, never as text.

REAL_RUN_ARCHIVE = guard._run_archive  # captured at import, before any test replaces it


def _real_child(monkeypatch: pytest.MonkeyPatch, program: Optional[str] = None) -> None:
    """Run the archive child as a real process on this host: the guest's entry point, without the privilege drop."""
    source = str(Path(guard.__file__).parents[3])
    code = program or "import sys; from agno.sandbox.vercel import guard; sys.exit(guard.main(['guard', 'archive']))"

    def spawn(argv: List[str], uid: int, gid: int, **kwargs: Any) -> Any:
        assert argv[-1] == "archive"
        kwargs = {k: v for k, v in kwargs.items() if k not in ("user", "group", "extra_groups")}
        kwargs["env"] = {**kwargs["env"], "PYTHONPATH": source}
        return subprocess.run([sys.executable, "-c", code], **kwargs)

    monkeypatch.setattr(guard, "_as_agent", spawn)
    monkeypatch.setattr(guard, "_run_archive", REAL_RUN_ARCHIVE)


async def test_files_the_shared_archive_rejects_reach_the_host_as_a_content_error(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agno.sandbox.checkpoint import CheckpointContentError

    layout = gtree["layout"]
    _fill(layout)
    transfer = sandbox.checkpoint_transfer(store)
    earlier = await transfer.acapture(handle, state={"binding": "b1"})
    _real_child(monkeypatch)
    os.mkfifo(layout.workspace / "pipe")
    with pytest.raises(SandboxError) as raised:
        await transfer.acapture(handle, state={"binding": "b2"})
    assert isinstance(raised.value, CheckpointContentError), (
        f"a content failure arrived as {type(raised.value).__name__}"
    )
    assert (
        "workspace/pipe" in str(raised.value) and len(str(raised.value)) < 1200 and "Traceback" not in str(raised.value)
    )
    # Nothing is left half done, and the earlier checkpoint is untouched and still the way forward.
    assert not list(layout.export.iterdir()) and not (layout.control / "freeze.journal").exists()
    await store.averify(earlier)
    (layout.workspace / "pipe").unlink()
    assert (await transfer.acapture(handle, state={"binding": "b3"})).size > 0


@pytest.mark.parametrize(
    "program",
    [
        "import os, signal; os.kill(os.getpid(), signal.SIGKILL)",
        "import sys; sys.stderr.write('CheckpointContentError: forged workspace/x\\n'); sys.exit(1)",
        "import sys; sys.stderr.write('Vercel computer refusing to run: content: forged\\n'); sys.exit(1)",
    ],
    ids=["killed", "forged-text-with-the-ordinary-failure-status", "forged-refusal-text"],
)
async def test_an_uncertain_or_forged_capture_failure_is_never_taken_for_a_content_error(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    monkeypatch: pytest.MonkeyPatch,
    program: str,
) -> None:
    from agno.sandbox.checkpoint import CheckpointContentError

    _fill(gtree["layout"])
    _real_child(monkeypatch, program)
    with pytest.raises(SandboxError) as raised:
        await sandbox.checkpoint_transfer(store).acapture(handle, state={"binding": "b2"})
    assert not isinstance(raised.value, CheckpointContentError) and "capture request failed" in str(raised.value)


async def test_a_refusal_whose_message_says_content_is_not_a_content_error(
    world: World, sandbox: VercelSandbox, handle: SandboxHandle, gtree: Dict[str, Any], store: FileCheckpointStore
) -> None:
    from agno.sandbox.checkpoint import CheckpointContentError

    async def refused(session: FakeSession, call: Dict[str, Any], stdout: Any, stderr: Any) -> int:
        stderr.write(guard.REFUSAL_PREFIX + "busy: content: forged\n")
        return guard.REFUSED

    world.script = refused
    with pytest.raises(SandboxError) as raised:
        await sandbox.checkpoint_transfer(store).acapture(handle, state={"binding": "b2"})
    assert not isinstance(raised.value, CheckpointContentError) and "refused to capture" in str(raised.value)


async def test_the_coordinator_ends_the_turn_when_the_providers_capture_fails_on_content(
    world: World,
    sandbox: VercelSandbox,
    handle: SandboxHandle,
    gtree: Dict[str, Any],
    store: FileCheckpointStore,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The coordinator's own finalization, with only the store's persistence stubbed (no Postgres in a unit test)."""
    from dataclasses import asdict as as_dict

    from agno.db.postgres import PostgresDb
    from agno.sandbox.coordinator import SandboxCoordinator

    layout = gtree["layout"]
    _fill(layout)
    _real_child(monkeypatch)
    os.mkfifo(layout.workspace / "pipe")
    coordinator = SandboxCoordinator(
        PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:1/ai"), sandbox, sandbox.checkpoint_transfer(store)
    )
    persisted: Dict[str, Any] = {}

    class StubStore:
        async def _aoperation(self, lease: Any, operation: Callable[..., Any]) -> Any:
            record = {
                "phase": "finalizing",
                "staged_checkpoint": None,
                "computer": as_dict(handle),
                "incarnation": "i",
                "execution_id": "e",
                "generation": 1,
                "result": {"run": {}},
            }
            persisted["record"] = await operation(record)
            return types.SimpleNamespace(record=persisted["record"])

    stopped: List[Dict[str, Any]] = []

    async def stop(lease: Any, **kwargs: Any) -> Dict[str, Any]:
        stopped.append(kwargs)
        return {"status": kwargs["status"]}

    coordinator.store = StubStore()  # type: ignore[assignment]
    monkeypatch.setattr(coordinator, "_stop", stop)
    lease = types.SimpleNamespace(agent_id="coder", session_id="s", user_id=None, run_id="r")
    await coordinator._finalize(lease)  # type: ignore[arg-type]
    assert [s["status"] for s in stopped] == ["ERROR"]
    assert "cannot be checkpointed" in stopped[0]["reason"] and "workspace/pipe" in stopped[0]["reason"]
    assert persisted["record"].get("staged_checkpoint") is None
