import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from agno.run import RunContext
from agno.tools.tenki import TenkiTools


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

    def mkdir(self, path: str, *, recursive: bool = True) -> None:
        if path == "/home/tenki":
            raise PermissionError("guest_error: path outside workdir: /home/tenki")
        self.directories.add(path)

    def write_text(self, path: str, text: str) -> None:
        self.files[path] = text

    def read_text(self, path: str) -> str:
        return self.files[path]

    def stat(self, path: str):
        if path in self.directories:
            return SimpleNamespace(path=path, is_dir=True)
        if path in self.files:
            return SimpleNamespace(path=path, is_dir=False)
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
        del self.files[path]


class FakeAsyncFileSystem:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.directories: set[str] = {"/home/tenki"}

    async def mkdir(self, path: str, *, recursive: bool = True) -> None:
        if path == "/home/tenki":
            raise PermissionError("guest_error: path outside workdir: /home/tenki")
        self.directories.add(path)

    async def write_text(self, path: str, text: str) -> None:
        self.files[path] = text

    async def read_text(self, path: str) -> str:
        return self.files[path]

    async def stat(self, path: str):
        if path in self.directories:
            return SimpleNamespace(path=path, is_dir=True)
        if path in self.files:
            return SimpleNamespace(path=path, is_dir=False)
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
        del self.files[path]


class FakeSandbox:
    def __init__(self, sandbox_id: str = "sandbox-1") -> None:
        self.id = sandbox_id
        self.state = "RUNNING"
        self.info = SimpleNamespace(name="agno-tenki")
        self.fs = FakeFileSystem()
        self.exec_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.resume_calls = 0
        self.wait_ready_calls: list[float] = []
        self.close_calls = 0

    def exec(self, *args, **kwargs):
        self.exec_calls.append((args, kwargs))
        return FakeCommandResult()

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
    def __init__(self, identity=None) -> None:
        self.sandboxes: dict[str, FakeSandbox] = {}
        self.created_ids: list[str] = []
        self.create_options: list[dict[str, Any]] = []
        self.identity = identity or SimpleNamespace(owner_type="SERVICE", owner_id="service-1", workspaces=())
        self.who_am_i_calls = 0

    def who_am_i(self):
        self.who_am_i_calls += 1
        return self.identity

    def create(self, **kwargs):
        self.create_options.append(kwargs)
        sandbox_id = f"sandbox-{len(self.created_ids) + 1}"
        sandbox = FakeSandbox(sandbox_id)
        self.sandboxes[sandbox_id] = sandbox
        self.created_ids.append(sandbox_id)
        return sandbox

    def get(self, sandbox_id: str):
        return self.sandboxes[sandbox_id]


class FakeAsyncSandbox:
    def __init__(self, sandbox_id: str = "async-sandbox-1") -> None:
        self.id = sandbox_id
        self.state = "RUNNING"
        self.info = SimpleNamespace(name="agno-tenki")
        self.fs = FakeAsyncFileSystem()
        self.exec_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.resume_calls = 0
        self.wait_ready_calls: list[float] = []
        self.close_calls = 0

    async def exec(self, *args, **kwargs):
        self.exec_calls.append((args, kwargs))
        return FakeCommandResult(stdout_text="hello async\n")

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
    def __init__(self, identity=None) -> None:
        self.sandboxes: dict[str, FakeAsyncSandbox] = {}
        self.created_ids: list[str] = []
        self.create_options: list[dict[str, Any]] = []
        self.identity = identity or SimpleNamespace(owner_type="SERVICE", owner_id="service-1", workspaces=())
        self.who_am_i_calls = 0

    async def who_am_i(self):
        self.who_am_i_calls += 1
        return self.identity

    async def create(self, **kwargs):
        self.create_options.append(kwargs)
        sandbox_id = f"async-sandbox-{len(self.created_ids) + 1}"
        sandbox = FakeAsyncSandbox(sandbox_id)
        self.sandboxes[sandbox_id] = sandbox
        self.created_ids.append(sandbox_id)
        return sandbox

    async def get(self, sandbox_id: str):
        return self.sandboxes[sandbox_id]


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
            "name": "agno-example",
            "timeout": 180,
        }
    ]


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


def test_get_sandbox_status_reports_session_details() -> None:
    tools = TenkiTools(client=FakeClient(), async_client=FakeAsyncClient())
    run_context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    status = json.loads(tools.get_sandbox_status(run_context))

    assert status == {
        "status": "success",
        "sandbox_id": "sandbox-1",
        "name": "agno-tenki",
        "state": "RUNNING",
        "working_directory": "/home/tenki",
    }


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
