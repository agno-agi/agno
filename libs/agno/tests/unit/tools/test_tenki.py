import asyncio
import base64
import json
import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier, Lock
from time import sleep
from types import SimpleNamespace
from typing import Any

import pytest

from agno.run import RunContext
from agno.tools.tenki import BOUNDED_COMMAND_RUNNER, TenkiTools


class SessionNotFoundError(Exception):
    pass


@dataclass
class FakeCommandResult:
    exit_code: int = 0
    stdout_text: str = "hello from tenki\n"
    stderr_text: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class FakeFileSystem:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.directories: set[str] = {"/home/tenki"}
        self.read_stream_calls: list[dict[str, Any]] = []

    def mkdir(self, path: str, *, recursive: bool = True) -> None:
        if path == "/home/tenki":
            raise PermissionError("guest_error: path outside workdir: /home/tenki")
        self.directories.add(path)

    def write_text(self, path: str, text: str) -> None:
        self.files[path] = text

    def read_text(self, path: str) -> str:
        return self.files[path]

    def read_stream(self, path: str, *, offset: int = 0, length: int = 0, chunk_bytes: int = 0):
        self.read_stream_calls.append(
            {
                "path": path,
                "offset": offset,
                "length": length,
                "chunk_bytes": chunk_bytes,
            }
        )
        data = self.files[path].encode()[offset:]
        if length:
            data = data[:length]
        size = chunk_bytes or len(data) or 1
        for index in range(0, len(data), size):
            yield data[index : index + size]

    def stat(self, path: str):
        if path in self.directories:
            return SimpleNamespace(path=path, is_dir=True, size=0)
        if path in self.files:
            return SimpleNamespace(path=path, is_dir=False, size=len(self.files[path].encode()))
        raise FileNotFoundError(path)

    def list(self, path: str, *, include_hidden: bool = False):
        prefix = f"{path.rstrip('/')}/"
        entries = []
        for file_path, content in self.files.items():
            relative_path = file_path.removeprefix(prefix)
            if file_path.startswith(prefix) and "/" not in relative_path:
                entries.append(
                    SimpleNamespace(
                        path=file_path,
                        size=len(content),
                        mode=0o644,
                        is_dir=False,
                        modified_unix_ns=1,
                        is_symlink=False,
                        symlink_target="",
                    )
                )
        return entries

    def remove(self, path: str, *, recursive: bool = True) -> None:
        if recursive and path in self.directories:
            prefix = f"{path.rstrip('/')}/"
            self.files = {
                file_path: content for file_path, content in self.files.items() if not file_path.startswith(prefix)
            }
            self.directories = {
                directory for directory in self.directories if directory != path and not directory.startswith(prefix)
            }
            return
        del self.files[path]


class FakeAsyncFileSystem:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.directories: set[str] = {"/home/tenki"}
        self.read_stream_calls: list[dict[str, Any]] = []

    async def mkdir(self, path: str, *, recursive: bool = True) -> None:
        if path == "/home/tenki":
            raise PermissionError("guest_error: path outside workdir: /home/tenki")
        self.directories.add(path)

    async def write_text(self, path: str, text: str) -> None:
        self.files[path] = text

    async def read_text(self, path: str) -> str:
        return self.files[path]

    async def read_stream(self, path: str, *, offset: int = 0, length: int = 0, chunk_bytes: int = 0):
        self.read_stream_calls.append(
            {
                "path": path,
                "offset": offset,
                "length": length,
                "chunk_bytes": chunk_bytes,
            }
        )
        data = self.files[path].encode()[offset:]
        if length:
            data = data[:length]
        size = chunk_bytes or len(data) or 1
        for index in range(0, len(data), size):
            yield data[index : index + size]

    async def stat(self, path: str):
        if path in self.directories:
            return SimpleNamespace(path=path, is_dir=True, size=0)
        if path in self.files:
            return SimpleNamespace(path=path, is_dir=False, size=len(self.files[path].encode()))
        raise FileNotFoundError(path)

    async def list(self, path: str, *, include_hidden: bool = False):
        prefix = f"{path.rstrip('/')}/"
        entries = []
        for file_path, content in self.files.items():
            relative_path = file_path.removeprefix(prefix)
            if file_path.startswith(prefix) and "/" not in relative_path:
                entries.append(
                    SimpleNamespace(
                        path=file_path,
                        size=len(content),
                        mode=0o644,
                        is_dir=False,
                        modified_unix_ns=1,
                        is_symlink=False,
                        symlink_target="",
                    )
                )
        return entries

    async def remove(self, path: str, *, recursive: bool = True) -> None:
        if recursive and path in self.directories:
            prefix = f"{path.rstrip('/')}/"
            self.files = {
                file_path: content for file_path, content in self.files.items() if not file_path.startswith(prefix)
            }
            self.directories = {
                directory for directory in self.directories if directory != path and not directory.startswith(prefix)
            }
            return
        del self.files[path]


class FakeSandbox:
    def __init__(
        self,
        sandbox_id: str = "sandbox-1",
        *,
        tags: list[str] | None = None,
        python_result: FakeCommandResult | None = None,
        shell_result: FakeCommandResult | None = None,
    ) -> None:
        self.id = sandbox_id
        self.state = "RUNNING"
        self.info = SimpleNamespace(name="agno-tenki", tags=tuple(tags or ()))
        self.fs = FakeFileSystem()
        self.exec_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.resume_calls = 0
        self.wait_ready_calls: list[float] = []
        self.close_calls = 0
        self.python_result = python_result or FakeCommandResult()
        self.shell_result = shell_result or FakeCommandResult(
            exit_code=2,
            stdout_text="partial output\n",
            stderr_text="command failed\n",
        )

    def exec(self, *args, **kwargs):
        self.exec_calls.append((args, kwargs))
        if len(args) >= 7 and args[:2] == ("python3", "-c"):
            mode = args[3]
            result = self.python_result if mode == "python" else self.shell_result
            limit = int(args[6])
            stdout = result.stdout_text.encode()
            stderr = result.stderr_text.encode()
            payload = {
                "exit_code": result.exit_code,
                "stdout": base64.b64encode(stdout if limit < 0 else stdout[:limit]).decode(),
                "stderr": base64.b64encode(stderr if limit < 0 else stderr[:limit]).decode(),
                "stdout_bytes": len(stdout),
                "stderr_bytes": len(stderr),
            }
            return FakeCommandResult(stdout_text=json.dumps(payload))
        return self.python_result

    def shell(self, command: str, **kwargs):
        return FakeCommandResult(exit_code=2, stdout_text="partial output\n", stderr_text="command failed\n")

    def resume(self) -> None:
        self.resume_calls += 1
        self.state = "RESUMING"

    def wait_ready(self, timeout: float = 180) -> None:
        self.wait_ready_calls.append(timeout)
        self.state = "RUNNING"

    def close(self) -> None:
        self.close_calls += 1
        self.state = "TERMINATED"


class FakeClient:
    def __init__(
        self,
        identity=None,
        *,
        python_result: FakeCommandResult | None = None,
        shell_result: FakeCommandResult | None = None,
    ) -> None:
        self.sandboxes: dict[str, FakeSandbox] = {}
        self.created_ids: list[str] = []
        self.create_options: list[dict[str, Any]] = []
        self.list_options: list[dict[str, Any]] = []
        self.identity = identity or SimpleNamespace(owner_type="SERVICE", owner_id="service-1", workspaces=())
        self.who_am_i_calls = 0
        self.python_result = python_result
        self.shell_result = shell_result

    def who_am_i(self):
        self.who_am_i_calls += 1
        return self.identity

    def create(self, **kwargs):
        self.create_options.append(kwargs)
        sandbox_id = f"sandbox-{len(self.created_ids) + 1}"
        sandbox = FakeSandbox(
            sandbox_id,
            tags=kwargs.get("tags"),
            python_result=self.python_result,
            shell_result=self.shell_result,
        )
        if kwargs.get("wait") is False:
            sandbox.state = "CREATING"
        self.sandboxes[sandbox_id] = sandbox
        self.created_ids.append(sandbox_id)
        return sandbox

    def get(self, sandbox_id: str):
        try:
            return self.sandboxes[sandbox_id]
        except KeyError as error:
            raise SessionNotFoundError(sandbox_id) from error

    def list(self, *, workspace_id: str | None = None, tags: list[str] | None = None):
        self.list_options.append({"workspace_id": workspace_id, "tags": tags})
        requested_tags = set(tags or ())
        return [sandbox for sandbox in self.sandboxes.values() if requested_tags.issubset(set(sandbox.info.tags))]


class FakeAsyncSandbox:
    def __init__(
        self,
        sandbox_id: str = "async-sandbox-1",
        *,
        tags: list[str] | None = None,
        python_result: FakeCommandResult | None = None,
        shell_result: FakeCommandResult | None = None,
    ) -> None:
        self.id = sandbox_id
        self.state = "RUNNING"
        self.info = SimpleNamespace(name="agno-tenki", tags=tuple(tags or ()))
        self.fs = FakeAsyncFileSystem()
        self.exec_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.resume_calls = 0
        self.wait_ready_calls: list[float] = []
        self.close_calls = 0
        self.python_result = python_result or FakeCommandResult(stdout_text="hello async\n")
        self.shell_result = shell_result or FakeCommandResult(
            exit_code=2,
            stdout_text="partial output\n",
            stderr_text="command failed\n",
        )

    async def exec(self, *args, **kwargs):
        self.exec_calls.append((args, kwargs))
        if len(args) >= 7 and args[:2] == ("python3", "-c"):
            mode = args[3]
            result = self.python_result if mode == "python" else self.shell_result
            limit = int(args[6])
            stdout = result.stdout_text.encode()
            stderr = result.stderr_text.encode()
            payload = {
                "exit_code": result.exit_code,
                "stdout": base64.b64encode(stdout if limit < 0 else stdout[:limit]).decode(),
                "stderr": base64.b64encode(stderr if limit < 0 else stderr[:limit]).decode(),
                "stdout_bytes": len(stdout),
                "stderr_bytes": len(stderr),
            }
            return FakeCommandResult(stdout_text=json.dumps(payload))
        return self.python_result

    async def shell(self, command: str, **kwargs):
        return FakeCommandResult(exit_code=2, stdout_text="partial output\n", stderr_text="command failed\n")

    async def resume(self) -> None:
        self.resume_calls += 1
        self.state = "RESUMING"

    async def wait_ready(self, timeout: float = 180) -> None:
        self.wait_ready_calls.append(timeout)
        self.state = "RUNNING"

    async def close(self) -> None:
        self.close_calls += 1
        self.state = "TERMINATED"


class FakeAsyncClient:
    def __init__(
        self,
        identity=None,
        *,
        python_result: FakeCommandResult | None = None,
        shell_result: FakeCommandResult | None = None,
    ) -> None:
        self.sandboxes: dict[str, FakeAsyncSandbox] = {}
        self.created_ids: list[str] = []
        self.create_options: list[dict[str, Any]] = []
        self.list_options: list[dict[str, Any]] = []
        self.identity = identity or SimpleNamespace(owner_type="SERVICE", owner_id="service-1", workspaces=())
        self.who_am_i_calls = 0
        self.python_result = python_result
        self.shell_result = shell_result

    async def who_am_i(self):
        self.who_am_i_calls += 1
        return self.identity

    async def create(self, **kwargs):
        self.create_options.append(kwargs)
        sandbox_id = f"async-sandbox-{len(self.created_ids) + 1}"
        sandbox = FakeAsyncSandbox(
            sandbox_id,
            tags=kwargs.get("tags"),
            python_result=self.python_result,
            shell_result=self.shell_result,
        )
        if kwargs.get("wait") is False:
            sandbox.state = "CREATING"
        self.sandboxes[sandbox_id] = sandbox
        self.created_ids.append(sandbox_id)
        return sandbox

    async def get(self, sandbox_id: str):
        try:
            return self.sandboxes[sandbox_id]
        except KeyError as error:
            raise SessionNotFoundError(sandbox_id) from error

    async def list(self, *, workspace_id: str | None = None, tags: list[str] | None = None):
        self.list_options.append({"workspace_id": workspace_id, "tags": tags})
        requested_tags = set(tags or ())
        return [sandbox for sandbox in self.sandboxes.values() if requested_tags.issubset(set(sandbox.info.tags))]


class SlowFakeClient(FakeClient):
    def create(self, **kwargs):
        sleep(0.05)
        return super().create(**kwargs)


class SlowFakeAsyncClient(FakeAsyncClient):
    async def create(self, **kwargs):
        await asyncio.sleep(0.05)
        return await super().create(**kwargs)


class CoordinatedFakeClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.create_barrier = Barrier(2)
        self._create_lock = Lock()

    def create(self, **kwargs):
        with self._create_lock:
            sandbox = super().create(**kwargs)
        self.create_barrier.wait()
        return sandbox

    def list(self, *, workspace_id: str | None = None, tags: list[str] | None = None):
        if len(self.created_ids) < 2:
            return []
        return super().list(workspace_id=workspace_id, tags=tags)


class CoordinatedFakeAsyncClient(FakeAsyncClient):
    def __init__(self) -> None:
        super().__init__()
        self.created_event = asyncio.Event()

    async def create(self, **kwargs):
        sandbox = await super().create(**kwargs)
        if len(self.created_ids) == 2:
            self.created_event.set()
        await self.created_event.wait()
        return sandbox

    async def list(self, *, workspace_id: str | None = None, tags: list[str] | None = None):
        if len(self.created_ids) < 2:
            return []
        return await super().list(workspace_id=workspace_id, tags=tags)


def test_run_code_creates_a_session_and_returns_command_output() -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=SimpleNamespace())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    result = json.loads(tools.run_code(run_context, "print('hello from tenki')"))

    assert result == {
        "status": "success",
        "exit_code": 0,
        "stdout": "hello from tenki\n",
        "stderr": "",
    }
    assert run_context.session_state == {
        "tenki_sandbox_id": "sandbox-1",
        "tenki_sandbox_owned": True,
        "tenki_working_directory": "/home/tenki",
    }


def test_run_code_reuses_the_session_recorded_in_run_context() -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=SimpleNamespace())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    tools.run_code(run_context, "print('first')")
    tools.run_code(run_context, "print('second')")

    assert client.created_ids == ["sandbox-1"]
    session_state = run_context.session_state
    assert session_state is not None
    assert session_state["tenki_sandbox_id"] == "sandbox-1"


def test_parallel_sync_calls_single_flight_sandbox_creation_per_session() -> None:
    client = SlowFakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    first_context = RunContext(run_id="run-1", session_id="shared-session", session_state={})
    second_context = RunContext(run_id="run-2", session_id="shared-session", session_state={})

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda item: tools.run_code(item[0], item[1]),
                (
                    (first_context, "print('first')"),
                    (second_context, "print('second')"),
                ),
            )
        )

    assert len(results) == 2
    assert client.created_ids == ["sandbox-1"]
    assert first_context.session_state is not None
    assert second_context.session_state is not None
    assert first_context.session_state["tenki_sandbox_id"] == "sandbox-1"
    assert second_context.session_state["tenki_sandbox_id"] == "sandbox-1"


async def test_parallel_async_calls_single_flight_sandbox_creation_per_session() -> None:
    async_client = SlowFakeAsyncClient()
    tools = TenkiTools(client=FakeClient(), async_client=async_client)
    first_context = RunContext(run_id="run-1", session_id="shared-session", session_state={})
    second_context = RunContext(run_id="run-2", session_id="shared-session", session_state={})

    results = await asyncio.gather(
        tools.arun_code(first_context, "print('first')"),
        tools.arun_code(second_context, "print('second')"),
    )

    assert len(results) == 2
    assert async_client.created_ids == ["async-sandbox-1"]
    assert first_context.session_state is not None
    assert second_context.session_state is not None
    assert first_context.session_state["tenki_sandbox_id"] == "async-sandbox-1"
    assert second_context.session_state["tenki_sandbox_id"] == "async-sandbox-1"


def test_separate_toolkits_converge_on_one_server_claimed_sandbox() -> None:
    client = CoordinatedFakeClient()
    first_tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    second_tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    first_context = RunContext(run_id="run-1", session_id="shared-session", session_state={})
    second_context = RunContext(run_id="run-2", session_id="shared-session", session_state={})

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda item: item[0].run_code(item[1], "print('shared')"),
                (
                    (first_tools, first_context),
                    (second_tools, second_context),
                ),
            )
        )

    assert len(results) == 2
    assert client.created_ids == ["sandbox-1", "sandbox-2"]
    assert client.sandboxes["sandbox-1"].close_calls == 0
    assert client.sandboxes["sandbox-2"].close_calls == 1
    assert first_context.session_state is not None
    assert second_context.session_state is not None
    assert first_context.session_state["tenki_sandbox_id"] == "sandbox-1"
    assert second_context.session_state["tenki_sandbox_id"] == "sandbox-1"
    claim_tags = [set(options["tags"]) for options in client.create_options]
    assert claim_tags[0] == claim_tags[1]
    assert any(tag.startswith("agno-session:") for tag in claim_tags[0])


async def test_separate_async_toolkits_converge_on_one_server_claimed_sandbox() -> None:
    async_client = CoordinatedFakeAsyncClient()
    first_tools = TenkiTools(client=FakeClient(), async_client=async_client)
    second_tools = TenkiTools(client=FakeClient(), async_client=async_client)
    first_context = RunContext(run_id="run-1", session_id="shared-session", session_state={})
    second_context = RunContext(run_id="run-2", session_id="shared-session", session_state={})

    results = await asyncio.gather(
        first_tools.arun_code(first_context, "print('shared')"),
        second_tools.arun_code(second_context, "print('shared')"),
    )

    assert len(results) == 2
    assert async_client.created_ids == ["async-sandbox-1", "async-sandbox-2"]
    assert async_client.sandboxes["async-sandbox-1"].close_calls == 0
    assert async_client.sandboxes["async-sandbox-2"].close_calls == 1
    assert first_context.session_state is not None
    assert second_context.session_state is not None
    assert first_context.session_state["tenki_sandbox_id"] == "async-sandbox-1"
    assert second_context.session_state["tenki_sandbox_id"] == "async-sandbox-1"


def test_claim_reconciliation_retries_until_created_sandbox_is_visible(monkeypatch) -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    original_list = client.list
    post_create_list_calls = 0

    def eventually_consistent_list(*, workspace_id=None, tags=None):
        nonlocal post_create_list_calls
        if client.created_ids:
            post_create_list_calls += 1
            if post_create_list_calls < 3:
                return []
        return original_list(workspace_id=workspace_id, tags=tags)

    monkeypatch.setattr(client, "list", eventually_consistent_list)
    monkeypatch.setattr("agno.tools.tenki.CLAIM_RECONCILIATION_DELAYS", (0.0, 0.0, 0.0))

    tools.run_code(run_context, "print('eventually visible')")

    assert post_create_list_calls == 3
    assert client.sandboxes["sandbox-1"].close_calls == 0
    assert run_context.session_state is not None
    assert run_context.session_state["tenki_sandbox_id"] == "sandbox-1"


def test_claim_reconciliation_list_failure_keeps_healthy_created_sandbox(monkeypatch) -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    def failing_list(*, workspace_id=None, tags=None):
        if client.created_ids:
            raise RuntimeError("temporary list failure")
        return []

    monkeypatch.setattr(client, "list", failing_list)
    monkeypatch.setattr("agno.tools.tenki.CLAIM_RECONCILIATION_DELAYS", (0.0, 0.0))

    result = json.loads(tools.run_code(run_context, "print('still usable')"))

    assert result["status"] == "success"
    assert client.sandboxes["sandbox-1"].close_calls == 0
    assert run_context.session_state is not None
    assert run_context.session_state["tenki_sandbox_id"] == "sandbox-1"


def test_duplicate_cleanup_failure_does_not_discard_claim_winner(monkeypatch) -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="shared-session", session_state={})
    winner = FakeSandbox("sandbox-0", tags=[tools._claim_tag(run_context)])
    client.sandboxes[winner.id] = winner
    original_create = client.create
    original_list = client.list

    def create_with_failed_cleanup(**kwargs):
        sandbox = original_create(**kwargs)

        def fail_close() -> None:
            sandbox.close_calls += 1
            raise RuntimeError("temporary close failure")

        sandbox.close = fail_close
        return sandbox

    def hide_winner_until_creation(*, workspace_id=None, tags=None):
        if not client.created_ids:
            return []
        return original_list(workspace_id=workspace_id, tags=tags)

    monkeypatch.setattr(client, "create", create_with_failed_cleanup)
    monkeypatch.setattr(client, "list", hide_winner_until_creation)

    result = json.loads(tools.run_code(run_context, "print('winner remains usable')"))

    assert result["status"] == "success"
    assert client.sandboxes["sandbox-1"].close_calls == 1
    assert winner.exec_calls
    assert run_context.session_state is not None
    assert run_context.session_state["tenki_sandbox_id"] == winner.id


def test_failed_readiness_terminates_registered_allocation_and_clears_state(monkeypatch) -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    registered_ids = []

    def fail_readiness(sandbox):
        assert run_context.session_state is not None
        registered_ids.append(run_context.session_state["tenki_sandbox_id"])
        raise TimeoutError("sandbox readiness timed out")

    monkeypatch.setattr(tools, "_prepare_sandbox", fail_readiness)

    with pytest.raises(TimeoutError, match="sandbox readiness timed out"):
        tools.run_code(run_context, "print('never runs')")

    assert registered_ids == ["sandbox-1"]
    assert client.create_options[0]["wait"] is False
    assert client.sandboxes["sandbox-1"].close_calls == 1
    assert run_context.session_state is not None
    assert "tenki_sandbox_id" not in run_context.session_state
    assert "tenki_sandbox_owned" not in run_context.session_state


async def test_async_failed_readiness_terminates_registered_allocation_and_clears_state(monkeypatch) -> None:
    async_client = FakeAsyncClient()
    tools = TenkiTools(client=FakeClient(), async_client=async_client)
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    registered_ids = []

    async def fail_readiness(sandbox):
        assert run_context.session_state is not None
        registered_ids.append(run_context.session_state["tenki_sandbox_id"])
        raise TimeoutError("sandbox readiness timed out")

    monkeypatch.setattr(tools, "_aprepare_sandbox", fail_readiness)

    with pytest.raises(TimeoutError, match="sandbox readiness timed out"):
        await tools.arun_code(run_context, "print('never runs')")

    assert registered_ids == ["async-sandbox-1"]
    assert async_client.create_options[0]["wait"] is False
    assert async_client.sandboxes["async-sandbox-1"].close_calls == 1
    assert run_context.session_state is not None
    assert "tenki_sandbox_id" not in run_context.session_state
    assert "tenki_sandbox_owned" not in run_context.session_state


def test_creation_lock_storage_is_fixed_size() -> None:
    tools = TenkiTools(client=FakeClient(), async_client=FakeAsyncClient())

    for index in range(1_000):
        run_context = RunContext(
            run_id=f"run-{index}",
            session_id=f"session-{index}",
            session_state={},
        )
        tools._creation_lock(run_context)

    assert len(tools._creation_locks) == 64
    assert not hasattr(tools, "_session_sandbox_ids")


def test_new_sandboxes_disable_inbound_network_access_by_default() -> None:
    client = FakeClient()
    tools = TenkiTools(
        client=client,
        async_client=FakeAsyncClient(),
        sandbox_options={"name": "agno-example"},
    )
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    tools.run_code(run_context, "print('network defaults')")

    assert client.create_options == [
        {
            "allow_inbound": False,
            "allow_outbound": True,
            "max_duration": 900,
            "name": "agno-example",
            "tags": [tools._claim_tag(run_context)],
            "timeout": 180,
            "wait": False,
        }
    ]


def test_sandbox_max_duration_can_be_overridden() -> None:
    client = FakeClient()
    tools = TenkiTools(
        client=client,
        async_client=FakeAsyncClient(),
        sandbox_max_duration=300,
        sandbox_options={"max_duration": 600},
    )
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    tools.run_code(run_context, "print('bounded sandbox')")

    assert client.create_options[0]["max_duration"] == 600


def test_auto_created_sandboxes_require_a_bounded_lifetime() -> None:
    with pytest.raises(ValueError, match="require a bounded max duration"):
        TenkiTools(
            client=FakeClient(),
            async_client=FakeAsyncClient(),
            sandbox_max_duration=None,
        )

    tools = TenkiTools(
        client=FakeClient(),
        async_client=FakeAsyncClient(),
        auto_create_sandbox=False,
        sandbox_max_duration=None,
    )

    assert tools.auto_create_sandbox is False


def test_workspace_resolution_is_delegated_to_the_sdk() -> None:
    identity = SimpleNamespace(
        owner_type="USER",
        owner_id="user-1",
        workspaces=(
            SimpleNamespace(id="workspace-2", name="Beta"),
            SimpleNamespace(id="workspace-1", name="Acme"),
        ),
    )
    client = FakeClient(identity)
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    tools.run_code(run_context, "print('sdk scope')")

    assert client.who_am_i_calls == 0
    assert "workspace_id" not in client.create_options[0]


def test_explicit_workspace_id_is_passed_to_the_sdk(monkeypatch) -> None:
    monkeypatch.setenv("TENKI_WORKSPACE_ID", "workspace-from-env")
    client = FakeClient()
    tools = TenkiTools(
        client=client,
        async_client=FakeAsyncClient(),
        workspace_id="workspace-1",
    )
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    tools.run_code(run_context, "print('explicit scope')")

    assert client.who_am_i_calls == 0
    assert client.create_options[0]["workspace_id"] == "workspace-1"


def test_workspace_id_falls_back_to_environment_variable(monkeypatch) -> None:
    monkeypatch.setenv("TENKI_WORKSPACE_ID", "workspace-from-env")
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    tools.run_code(run_context, "print('environment scope')")

    assert client.who_am_i_calls == 0
    assert client.create_options[0]["workspace_id"] == "workspace-from-env"


@pytest.mark.asyncio
async def test_async_workspace_resolution_is_delegated_to_the_sdk() -> None:
    identity = SimpleNamespace(
        owner_type="USER",
        owner_id="user-1",
        workspaces=(
            SimpleNamespace(id="workspace-2", name="Beta"),
            SimpleNamespace(id="workspace-1", name="Acme"),
        ),
    )
    async_client = FakeAsyncClient(identity)
    tools = TenkiTools(client=FakeClient(), async_client=async_client)
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    await tools.arun_code(run_context, "print('async sdk scope')")

    assert async_client.who_am_i_calls == 0
    assert "workspace_id" not in async_client.create_options[0]


def test_explicit_sandbox_id_is_reused_without_creating_a_sandbox() -> None:
    client = FakeClient()
    client.sandboxes["existing-sandbox"] = FakeSandbox("existing-sandbox")
    tools = TenkiTools(
        client=client,
        async_client=FakeAsyncClient(),
        sandbox_id="existing-sandbox",
    )
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    tools.run_code(run_context, "print('existing')")

    assert client.created_ids == []
    session_state = run_context.session_state
    assert session_state is not None
    assert session_state["tenki_sandbox_id"] == "existing-sandbox"


def test_paused_session_sandbox_is_resumed_before_use() -> None:
    client = FakeClient()
    sandbox = FakeSandbox("paused-sandbox")
    sandbox.state = "PAUSED"
    client.sandboxes[sandbox.id] = sandbox
    tools = TenkiTools(client=client, async_client=FakeAsyncClient(), timeout=42)
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={"tenki_sandbox_id": sandbox.id},
    )

    tools.run_code(run_context, "print('resumed')")

    assert sandbox.resume_calls == 1
    assert sandbox.wait_ready_calls == [42]
    assert sandbox.exec_calls


def test_failed_resume_replaces_an_owned_session_sandbox(monkeypatch) -> None:
    client = FakeClient()
    paused = FakeSandbox("paused-sandbox")
    paused.state = "PAUSED"
    client.sandboxes[paused.id] = paused
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={
            "tenki_sandbox_id": paused.id,
            "tenki_sandbox_owned": True,
        },
    )

    def fail_resume() -> None:
        paused.resume_calls += 1
        raise RuntimeError("resume failed")

    monkeypatch.setattr(paused, "resume", fail_resume)

    tools.run_code(run_context, "print('replacement')")

    assert paused.resume_calls == 1
    assert paused.close_calls == 1
    assert client.created_ids == ["sandbox-1"]
    assert run_context.session_state is not None
    assert run_context.session_state["tenki_sandbox_id"] == "sandbox-1"


async def test_async_failed_resume_replaces_an_owned_session_sandbox(monkeypatch) -> None:
    async_client = FakeAsyncClient()
    paused = FakeAsyncSandbox("paused-sandbox")
    paused.state = "PAUSED"
    async_client.sandboxes[paused.id] = paused
    tools = TenkiTools(client=FakeClient(), async_client=async_client)
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={
            "tenki_sandbox_id": paused.id,
            "tenki_sandbox_owned": True,
        },
    )

    async def fail_resume() -> None:
        paused.resume_calls += 1
        raise RuntimeError("resume failed")

    monkeypatch.setattr(paused, "resume", fail_resume)

    await tools.arun_code(run_context, "print('replacement')")

    assert paused.resume_calls == 1
    assert paused.close_calls == 1
    assert async_client.created_ids == ["async-sandbox-1"]
    assert run_context.session_state is not None
    assert run_context.session_state["tenki_sandbox_id"] == "async-sandbox-1"


def test_retryable_resume_failure_preserves_the_owned_sandbox(monkeypatch) -> None:
    class RetryableResumeError(Exception):
        retryable = True

    client = FakeClient()
    paused = FakeSandbox("paused-sandbox")
    paused.state = "PAUSED"
    client.sandboxes[paused.id] = paused
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={
            "tenki_sandbox_id": paused.id,
            "tenki_sandbox_owned": True,
        },
    )

    def fail_resume() -> None:
        raise RetryableResumeError("temporary resume failure")

    monkeypatch.setattr(paused, "resume", fail_resume)

    with pytest.raises(RetryableResumeError, match="temporary resume failure"):
        tools.run_code(run_context, "print('retry later')")

    assert paused.close_calls == 0
    assert client.created_ids == []
    assert run_context.session_state is not None
    assert run_context.session_state["tenki_sandbox_id"] == paused.id


def test_terminated_session_sandbox_is_replaced_automatically() -> None:
    client = FakeClient()
    expired = FakeSandbox("expired-sandbox")
    expired.state = "TERMINATED"
    client.sandboxes[expired.id] = expired
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={
            "tenki_sandbox_id": expired.id,
            "tenki_working_directory": "/home/tenki/old-project",
        },
    )

    tools.run_code(run_context, "print('replacement')")

    assert client.created_ids == ["sandbox-1"]
    session_state = run_context.session_state
    assert session_state is not None
    assert session_state["tenki_sandbox_id"] == "sandbox-1"
    assert session_state["tenki_working_directory"] == "/home/tenki"
    assert client.sandboxes["sandbox-1"].exec_calls[-1][1]["cwd"] == "/home/tenki"


def test_missing_session_sandbox_is_replaced_automatically() -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={"tenki_sandbox_id": "missing-sandbox"},
    )

    tools.run_code(run_context, "print('replacement')")

    assert client.created_ids == ["sandbox-1"]
    session_state = run_context.session_state
    assert session_state is not None
    assert session_state["tenki_sandbox_id"] == "sandbox-1"


def test_unrelated_key_error_is_not_treated_as_a_missing_sandbox(monkeypatch) -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={"tenki_sandbox_id": "existing-sandbox"},
    )

    def fail_get(sandbox_id: str):
        raise KeyError("unrelated SDK bug")

    monkeypatch.setattr(client, "get", fail_get)

    with pytest.raises(KeyError, match="unrelated SDK bug"):
        tools.run_code(run_context, "print('must not replace')")

    assert client.created_ids == []


def test_auto_create_can_be_disabled() -> None:
    client = FakeClient()
    tools = TenkiTools(
        client=client,
        async_client=FakeAsyncClient(),
        auto_create_sandbox=False,
    )
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    with pytest.raises(RuntimeError, match="No Tenki sandbox is associated with this session"):
        tools.run_code(run_context, "print('not created')")

    assert client.created_ids == []


def test_get_sandbox_status_does_not_create_a_sandbox() -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    status = json.loads(tools.get_sandbox_status(run_context))

    assert status == {
        "status": "success",
        "sandbox_id": None,
        "name": None,
        "state": "ABSENT",
        "owned": False,
        "working_directory": "/home/tenki",
    }
    assert client.created_ids == []
    assert run_context.session_state == {}


def test_get_sandbox_status_does_not_resume_a_paused_sandbox() -> None:
    client = FakeClient()
    sandbox = FakeSandbox("paused-sandbox")
    sandbox.state = "PAUSED"
    client.sandboxes[sandbox.id] = sandbox
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={
            "tenki_sandbox_id": sandbox.id,
            "tenki_sandbox_owned": True,
            "tenki_working_directory": "/home/tenki/project",
        },
    )

    status = json.loads(tools.get_sandbox_status(run_context))

    assert status == {
        "status": "success",
        "sandbox_id": "paused-sandbox",
        "name": "agno-tenki",
        "state": "PAUSED",
        "owned": True,
        "working_directory": "/home/tenki/project",
    }
    assert sandbox.resume_calls == 0
    assert client.created_ids == []


async def test_async_get_sandbox_status_does_not_create_a_sandbox() -> None:
    async_client = FakeAsyncClient()
    tools = TenkiTools(client=FakeClient(), async_client=async_client)
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    status = json.loads(await tools.aget_sandbox_status(run_context))

    assert status["state"] == "ABSENT"
    assert async_client.created_ids == []
    assert run_context.session_state == {}


def test_each_tenki_function_can_be_disabled() -> None:
    tools = TenkiTools(
        client=FakeClient(),
        async_client=FakeAsyncClient(),
        enable_run_code=False,
        enable_run_shell_command=False,
        enable_create_file=False,
        enable_read_file=False,
        enable_list_files=False,
        enable_delete_file=False,
        enable_change_directory=False,
        enable_get_sandbox_status=False,
    )

    assert tools.get_functions() == {}
    assert tools.get_async_functions() == {}
    assert isinstance(tools.instructions, str)
    for tool_name in (
        "run_code",
        "run_shell_command",
        "create_file",
        "read_file",
        "list_files",
        "delete_file",
        "change_directory",
        "get_sandbox_status",
        "terminate_sandbox",
    ):
        assert f"`{tool_name}`" not in tools.instructions


def test_default_instructions_only_name_registered_functions() -> None:
    tools = TenkiTools(
        client=FakeClient(),
        async_client=FakeAsyncClient(),
        enable_run_code=False,
        enable_terminate_sandbox=True,
        exclude_tools=["delete_file"],
    )

    assert isinstance(tools.instructions, str)
    assert "run_code" not in tools.get_functions()
    assert "delete_file" not in tools.get_functions()
    assert "`run_code`" not in tools.instructions
    assert "`delete_file`" not in tools.instructions
    assert "`read_file`" in tools.instructions
    assert "`terminate_sandbox`" in tools.instructions


def test_all_enables_every_tenki_function() -> None:
    tools = TenkiTools(
        client=FakeClient(),
        async_client=FakeAsyncClient(),
        enable_run_code=False,
        enable_run_shell_command=False,
        enable_create_file=False,
        enable_read_file=False,
        enable_list_files=False,
        enable_delete_file=False,
        enable_change_directory=False,
        enable_get_sandbox_status=False,
        enable_terminate_sandbox=False,
        all=True,
    )
    expected_function_names = {
        "run_code",
        "run_shell_command",
        "create_file",
        "read_file",
        "list_files",
        "delete_file",
        "change_directory",
        "get_sandbox_status",
        "terminate_sandbox",
    }

    assert set(tools.get_functions()) == expected_function_names
    assert set(tools.get_async_functions()) == expected_function_names
    assert tools.get_functions()["terminate_sandbox"].requires_confirmation is True
    assert tools.get_async_functions()["terminate_sandbox"].requires_confirmation is True
    assert isinstance(tools.instructions, str)
    for tool_name in expected_function_names:
        assert f"`{tool_name}`" in tools.instructions


def test_terminate_sandbox_is_opt_in_and_requires_confirmation() -> None:
    client = FakeClient()
    default_tools = TenkiTools(client=FakeClient(), async_client=FakeAsyncClient())
    tools = TenkiTools(
        client=client,
        async_client=FakeAsyncClient(),
        enable_terminate_sandbox=True,
    )
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    tools.run_code(run_context, "print('create')")

    result = json.loads(tools.terminate_sandbox(run_context))

    assert "terminate_sandbox" not in default_tools.get_functions()
    assert tools.get_functions()["terminate_sandbox"].requires_confirmation is True
    assert tools.get_async_functions()["terminate_sandbox"].requires_confirmation is True
    assert result == {"status": "success", "sandbox_id": "sandbox-1", "state": "TERMINATED"}
    session_state = run_context.session_state
    assert session_state is not None
    assert "tenki_sandbox_id" not in session_state
    assert "tenki_sandbox_owned" not in session_state


def test_terminate_sandbox_never_creates_or_resumes_a_sandbox() -> None:
    empty_client = FakeClient()
    empty_tools = TenkiTools(
        client=empty_client,
        async_client=FakeAsyncClient(),
        enable_terminate_sandbox=True,
    )
    empty_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    with pytest.raises(RuntimeError, match="No Tenki sandbox is associated with this session"):
        empty_tools.terminate_sandbox(empty_context)

    paused_client = FakeClient()
    paused = FakeSandbox("paused-sandbox")
    paused.state = "PAUSED"
    paused_client.sandboxes[paused.id] = paused
    paused_tools = TenkiTools(
        client=paused_client,
        async_client=FakeAsyncClient(),
        enable_terminate_sandbox=True,
    )
    paused_context = RunContext(
        run_id="run-2",
        session_id="session-2",
        session_state={"tenki_sandbox_id": paused.id},
    )

    paused_tools.terminate_sandbox(paused_context)

    assert empty_client.created_ids == []
    assert paused.resume_calls == 0
    assert paused.close_calls == 1


def test_terminating_a_pinned_sandbox_does_not_unpin_the_shared_toolkit() -> None:
    client = FakeClient()
    pinned = FakeSandbox("pinned-sandbox")
    client.sandboxes[pinned.id] = pinned
    tools = TenkiTools(
        client=client,
        async_client=FakeAsyncClient(),
        sandbox_id=pinned.id,
        enable_terminate_sandbox=True,
    )
    first_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    second_context = RunContext(run_id="run-2", session_id="session-2", session_state={})

    tools.terminate_sandbox(first_context)

    assert tools.sandbox_id == pinned.id
    with pytest.raises(RuntimeError, match="is in terminal state TERMINATED"):
        tools.run_code(second_context, "print('must not auto-create')")
    assert client.created_ids == []


async def test_async_run_code_uses_the_native_async_client() -> None:
    async_client = FakeAsyncClient()
    tools = TenkiTools(client=FakeClient(), async_client=async_client)
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    result = json.loads(await tools.arun_code(run_context, "print('hello async')"))

    assert result["status"] == "success"
    assert result["stdout"] == "hello async\n"
    session_state = run_context.session_state
    assert session_state is not None
    assert session_state["tenki_sandbox_id"] == "async-sandbox-1"
    assert tools.get_async_functions()["run_code"].entrypoint == tools.arun_code


async def test_async_terminate_uses_the_native_async_client() -> None:
    async_client = FakeAsyncClient()
    tools = TenkiTools(
        client=FakeClient(),
        async_client=async_client,
        enable_terminate_sandbox=True,
    )
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    await tools.arun_code(run_context, "print('create')")

    result = json.loads(await tools.aterminate_sandbox(run_context))

    assert result == {
        "status": "success",
        "sandbox_id": "async-sandbox-1",
        "state": "TERMINATED",
    }
    assert async_client.sandboxes["async-sandbox-1"].close_calls == 1
    session_state = run_context.session_state
    assert session_state is not None
    assert "tenki_sandbox_id" not in session_state
    assert "tenki_sandbox_owned" not in session_state


def test_run_shell_command_preserves_failed_command_output() -> None:
    tools = TenkiTools(client=FakeClient(), async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    result = json.loads(tools.run_shell_command(run_context, "make test"))

    assert result == {
        "status": "error",
        "exit_code": 2,
        "stdout": "partial output\n",
        "stderr": "command failed\n",
    }


def test_command_output_is_bounded_during_remote_collection() -> None:
    client = FakeClient(
        python_result=FakeCommandResult(
            exit_code=1,
            stdout_text="a" * 100_000,
            stderr_text="b" * 80_000,
        )
    )
    tools = TenkiTools(
        client=client,
        async_client=FakeAsyncClient(),
        max_output_chars=10,
    )
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    result = json.loads(tools.run_code(run_context, "print('noisy')"))

    assert result["stdout"].startswith("a" * 10)
    assert result["stderr"].startswith("b" * 10)
    assert "[Output truncated after 10 characters; original size: 100000 bytes.]" in result["stdout"]
    assert "[Output truncated after 10 characters; original size: 80000 bytes.]" in result["stderr"]
    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True
    assert result["stdout_original_bytes"] == 100_000
    assert result["stderr_original_bytes"] == 80_000
    sandbox = client.sandboxes["sandbox-1"]
    assert sandbox.exec_calls[0][0][6] == "41"


def test_remote_command_runner_drains_but_does_not_retain_unbounded_output(tmp_path) -> None:
    command_path = tmp_path / "command.py"
    command_path.write_text(
        "import sys\nsys.stdout.write('a' * 100_000)\nsys.stderr.write('b' * 80_000)\nraise SystemExit(7)\n"
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            BOUNDED_COMMAND_RUNNER,
            "python",
            str(command_path),
            str(tmp_path),
            "41",
            "30",
            "2",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    collected = json.loads(completed.stdout)

    assert collected["exit_code"] == 7
    assert collected["stdout_bytes"] == 100_000
    assert collected["stderr_bytes"] == 80_000
    assert len(base64.b64decode(collected["stdout"])) == 41
    assert len(base64.b64decode(collected["stderr"])) == 41


def test_remote_command_runner_imports_files_from_the_working_directory(tmp_path) -> None:
    (tmp_path / "helper.py").write_text("VALUE = 42\n")
    command_directory = tmp_path / ".agno" / "commands" / "test"
    command_directory.mkdir(parents=True)
    command_path = command_directory / "command.py"
    command_path.write_text("import helper\nprint(helper.VALUE)\n")

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            BOUNDED_COMMAND_RUNNER,
            "python",
            str(command_path),
            str(tmp_path),
            "100",
            "30",
            "2",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    collected = json.loads(completed.stdout)

    assert collected["exit_code"] == 0
    assert base64.b64decode(collected["stdout"]).decode() == "42\n"
    assert base64.b64decode(collected["stderr"]).decode() == ""


def _write_sigterm_ignoring_descendant_command(tmp_path: Path) -> tuple[Path, Path]:
    child_pid_path = tmp_path / "child.pid"
    child_ready_path = tmp_path / "child.ready"
    command_path = tmp_path / "command.py"
    child_code = (
        "import pathlib\n"
        "import signal\n"
        "import time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"pathlib.Path({str(child_ready_path)!r}).write_text('ready')\n"
        "time.sleep(60)\n"
    )
    command_path.write_text(
        "import pathlib\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        f"ready_path = pathlib.Path({str(child_ready_path)!r})\n"
        "for _ in range(100):\n"
        "    if ready_path.exists():\n"
        "        break\n"
        "    time.sleep(0.01)\n"
        "else:\n"
        "    raise RuntimeError('child did not become ready')\n"
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid))\n"
        "print('done', flush=True)\n"
    )
    return command_path, child_pid_path


def test_remote_command_runner_terminates_the_user_process_group_on_timeout(tmp_path) -> None:
    child_pid_path = tmp_path / "child.pid"
    command_path = tmp_path / "command.py"
    command_path.write_text(
        "import pathlib\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid))\n"
    )
    child_pid = None
    runner = BOUNDED_COMMAND_RUNNER.replace(
        "os.killpg(process.pid, signal.SIGKILL)",
        "raise PermissionError('must not signal an exited process group leader')",
    )

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                runner,
                "python",
                str(command_path),
                str(tmp_path),
                "100",
                "0.2",
                "0.1",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        collected = json.loads(completed.stdout)
        child_pid = int(child_pid_path.read_text())

        assert collected["exit_code"] == 124
        assert collected["timed_out"] is True
        assert completed.stderr == ""
        for _ in range(100):
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            sleep(0.01)
        else:
            pytest.fail(f"timed-out child process {child_pid} is still running")
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_remote_command_runner_terminates_sigterm_ignoring_descendant_after_leader_exits(tmp_path) -> None:
    command_path, child_pid_path = _write_sigterm_ignoring_descendant_command(tmp_path)
    child_pid = None

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                BOUNDED_COMMAND_RUNNER,
                "python",
                str(command_path),
                str(tmp_path),
                "100",
                "1",
                "0.2",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        collected = json.loads(completed.stdout)
        child_pid = int(child_pid_path.read_text())

        assert collected["exit_code"] == 124
        assert collected["timed_out"] is True
        assert base64.b64decode(collected["stdout"]).decode() == "done\n"
        assert completed.stderr == ""
        for _ in range(100):
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            sleep(0.01)
        else:
            pytest.fail(f"SIGTERM-ignoring child process {child_pid} is still running")
    finally:
        if child_pid is None and child_pid_path.exists():
            child_pid = int(child_pid_path.read_text())
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_remote_command_runner_returns_when_process_group_signals_are_denied(tmp_path) -> None:
    command_path, child_pid_path = _write_sigterm_ignoring_descendant_command(tmp_path)
    child_pid = None
    runner = BOUNDED_COMMAND_RUNNER.replace(
        "os.killpg(process.pid, signal.SIGTERM)",
        "raise PermissionError('simulated SIGTERM permission error')",
    ).replace(
        "os.killpg(process.pid, signal.SIGKILL)",
        "raise PermissionError('simulated SIGKILL permission error')",
    )

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                runner,
                "python",
                str(command_path),
                str(tmp_path),
                "100",
                "1",
                "0.2",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        collected = json.loads(completed.stdout)
        child_pid = int(child_pid_path.read_text())

        assert collected["exit_code"] == 124
        assert collected["timed_out"] is True
        assert base64.b64decode(collected["stdout"]).decode() == "done\n"
        assert completed.stderr == ""
    finally:
        if child_pid is None and child_pid_path.exists():
            child_pid = int(child_pid_path.read_text())
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_remote_command_runner_tolerates_sigterm_permission_error(tmp_path) -> None:
    command_path = tmp_path / "command.py"
    command_path.write_text("import time\ntime.sleep(60)\n")
    runner = BOUNDED_COMMAND_RUNNER.replace(
        "os.killpg(process.pid, signal.SIGTERM)",
        "raise PermissionError('simulated SIGTERM permission error')",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            runner,
            "python",
            str(command_path),
            str(tmp_path),
            "100",
            "0.2",
            "0.1",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    collected = json.loads(completed.stdout)

    assert collected["exit_code"] == 124
    assert collected["timed_out"] is True
    assert completed.stderr == ""


def test_remote_command_runner_falls_back_when_sigkill_is_denied(tmp_path) -> None:
    command_path = tmp_path / "command.py"
    command_path.write_text(
        "import signal\nimport time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n"
    )
    runner = BOUNDED_COMMAND_RUNNER.replace(
        "os.killpg(process.pid, signal.SIGKILL)",
        "raise PermissionError('simulated SIGKILL permission error')",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            runner,
            "python",
            str(command_path),
            str(tmp_path),
            "100",
            "0.2",
            "0.1",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    collected = json.loads(completed.stdout)

    assert collected["exit_code"] == 124
    assert collected["timed_out"] is True
    assert completed.stderr == ""


def test_read_file_uses_a_bounded_stream() -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient(), max_output_chars=10)
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    tools.create_file(run_context, "large.txt", "x" * 100_000)

    content = tools.read_file(run_context, "large.txt")

    assert content.startswith("x" * 10)
    assert "[File content truncated after 10 characters.]" in content
    sandbox = client.sandboxes["sandbox-1"]
    assert sandbox.fs.read_stream_calls[-1]["length"] == 42


async def test_async_read_file_uses_a_bounded_stream() -> None:
    async_client = FakeAsyncClient()
    tools = TenkiTools(client=FakeClient(), async_client=async_client, max_output_chars=10)
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    await tools.acreate_file(run_context, "large.txt", "x" * 100_000)

    content = await tools.aread_file(run_context, "large.txt")

    assert content.startswith("x" * 10)
    assert "[File content truncated after 10 characters.]" in content
    sandbox = async_client.sandboxes["async-sandbox-1"]
    assert sandbox.fs.read_stream_calls[-1]["length"] == 42


def test_create_and_read_file_use_the_session_working_directory() -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    created = json.loads(tools.create_file(run_context, "reports/result.txt", "complete"))
    content = tools.read_file(run_context, "reports/result.txt")

    assert created == {
        "status": "success",
        "path": "/home/tenki/reports/result.txt",
    }
    assert content == "complete"


def test_create_file_does_not_try_to_create_the_working_directory_root() -> None:
    tools = TenkiTools(client=FakeClient(), async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    created = json.loads(tools.create_file(run_context, "scope-test.txt", "scope fallback works"))

    assert created == {
        "status": "success",
        "path": "/home/tenki/scope-test.txt",
    }


async def test_async_create_file_does_not_try_to_create_the_working_directory_root() -> None:
    tools = TenkiTools(client=FakeClient(), async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    created = json.loads(await tools.acreate_file(run_context, "scope-test.txt", "scope fallback works"))

    assert created == {
        "status": "success",
        "path": "/home/tenki/scope-test.txt",
    }


def test_file_paths_cannot_escape_the_tenki_working_directory() -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    with pytest.raises(ValueError, match="Path must remain within /home/tenki"):
        tools.create_file(run_context, "../../etc/passwd", "blocked")

    assert client.created_ids == []


def test_delete_file_cannot_delete_the_current_working_directory() -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    with pytest.raises(ValueError, match="Cannot delete the current Tenki working directory"):
        tools.delete_file(run_context, ".")

    assert client.created_ids == []


def test_delete_file_cannot_delete_an_ancestor_of_the_working_directory() -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    tools.run_code(run_context, "print('create sandbox')")
    sandbox = client.sandboxes["sandbox-1"]
    sandbox.fs.directories.update({"/home/tenki/project", "/home/tenki/project/nested"})
    tools.change_directory(run_context, "project/nested")

    with pytest.raises(ValueError, match="Cannot delete the current Tenki working directory"):
        tools.delete_file(run_context, "/home/tenki/project")

    assert "/home/tenki/project/nested" in sandbox.fs.directories


async def test_async_delete_file_cannot_delete_an_ancestor_of_the_working_directory() -> None:
    async_client = FakeAsyncClient()
    tools = TenkiTools(client=FakeClient(), async_client=async_client)
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    await tools.arun_code(run_context, "print('create sandbox')")
    sandbox = async_client.sandboxes["async-sandbox-1"]
    sandbox.fs.directories.update({"/home/tenki/project", "/home/tenki/project/nested"})
    await tools.achange_directory(run_context, "project/nested")

    with pytest.raises(ValueError, match="Cannot delete the current Tenki working directory"):
        await tools.adelete_file(run_context, "/home/tenki/project")

    assert "/home/tenki/project/nested" in sandbox.fs.directories


def test_change_directory_updates_the_cwd_used_by_commands() -> None:
    client = FakeClient()
    tools = TenkiTools(client=client, async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    tools.run_code(run_context, "print('create sandbox')")
    sandbox = client.sandboxes["sandbox-1"]
    sandbox.fs.directories.add("/home/tenki/project")

    result = json.loads(tools.change_directory(run_context, "project"))
    tools.run_code(run_context, "print('new cwd')")

    assert result == {
        "status": "success",
        "working_directory": "/home/tenki/project",
    }
    session_state = run_context.session_state
    assert session_state is not None
    assert session_state["tenki_working_directory"] == "/home/tenki/project"
    assert sandbox.exec_calls[-1][1]["cwd"] == "/home/tenki/project"


def test_list_and_delete_files_use_the_native_filesystem_api() -> None:
    tools = TenkiTools(client=FakeClient(), async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})
    tools.create_file(run_context, "one.txt", "one")
    tools.create_file(run_context, "two.txt", "second")

    listing = json.loads(tools.list_files(run_context))
    deleted = json.loads(tools.delete_file(run_context, "one.txt"))
    listing_after_delete = json.loads(tools.list_files(run_context))

    assert listing == {
        "status": "success",
        "path": "/home/tenki",
        "files": [
            {
                "path": "/home/tenki/one.txt",
                "size": 3,
                "mode": 0o644,
                "is_dir": False,
                "modified_unix_ns": 1,
                "is_symlink": False,
                "symlink_target": "",
            },
            {
                "path": "/home/tenki/two.txt",
                "size": 6,
                "mode": 0o644,
                "is_dir": False,
                "modified_unix_ns": 1,
                "is_symlink": False,
                "symlink_target": "",
            },
        ],
    }
    assert deleted == {"status": "success", "path": "/home/tenki/one.txt"}
    assert [entry["path"] for entry in listing_after_delete["files"]] == ["/home/tenki/two.txt"]


async def test_async_filesystem_tools_use_the_native_async_client() -> None:
    async_client = FakeAsyncClient()
    tools = TenkiTools(client=FakeClient(), async_client=async_client)
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    await tools.acreate_file(run_context, "project/result.txt", "complete")
    content = await tools.aread_file(run_context, "project/result.txt")
    listing = json.loads(await tools.alist_files(run_context, "project"))
    await tools.achange_directory(run_context, "project")
    deleted = json.loads(await tools.adelete_file(run_context, "result.txt"))

    assert content == "complete"
    assert [entry["path"] for entry in listing["files"]] == ["/home/tenki/project/result.txt"]
    assert deleted == {"status": "success", "path": "/home/tenki/project/result.txt"}
    assert tools.get_async_functions()["create_file"].entrypoint == tools.acreate_file
