"""Smol tools must keep execution in one VM and respect VM ownership."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from agno.tools.smol import SmolTools


@pytest.fixture
def machines():
    created = []
    attached = []

    def make(name="vm-new"):
        vm = Mock()
        vm.id = name
        vm.state.return_value = "started"
        vm.exec.return_value = SimpleNamespace(exit_code=0, output="hello\n")
        vm.read_file.return_value = b"contents"
        return vm

    with (
        patch("agno.tools.smol.Machine.create", side_effect=lambda *args: created.append(args) or make()),
        patch("agno.tools.smol.Machine.connect", side_effect=lambda *args: attached.append(args) or make(args[0])),
    ):
        yield created, attached, make


def test_creates_lazily_and_reuses_one_owned_vm(machines):
    created, _, _ = machines
    tools = SmolTools(target="cloud", api_key="private-token", timeout=20)
    assert created == []
    assert tools.run_shell_command("echo hello") == "hello\n"
    assert tools.run_python_code("print(42)") == "hello\n"
    assert len(created) == 1
    config, conn = created[0]
    assert config.image == "python:3.12-alpine"
    assert config.resources.network is True
    assert config.resources.cpus == 2 and config.resources.memory_mb == 2048
    assert config.persistent is False
    assert config.ttl_seconds == 3600
    assert conn.target == "cloud" and conn.api_key == "private-token"
    assert tools.active_machine_id == "vm-new"
    machine = tools._machine
    tools.close()
    tools.close()
    machine.delete.assert_called_once_with()
    # Explicit cleanup is idempotent.
    assert tools._machine is None


def test_attached_vm_is_never_deleted_and_stopped_vm_is_started(machines):
    created, attached, vm = machines
    machine = vm("external")
    machine.state.return_value = "stopped"
    with patch("agno.tools.smol.Machine.connect", return_value=machine):
        tools = SmolTools(machine_id="external")
        assert tools.active_machine_id == "external"
        assert tools.run_shell_command("true") == "hello\n"
        machine.start.assert_called_once_with()
        machine.wait_until_ready.assert_called_once_with()
        tools.close()
        machine.delete.assert_not_called()
    assert not created and not attached


def test_commands_and_file_paths_stay_inside_vm(machines):
    _, _, _ = machines
    tools = SmolTools(workdir="/workspace/my-project", max_output_chars=6)
    with patch("agno.tools.smol.Machine.create") as create:
        vm = create.return_value
        vm.id = "vm-test"
        vm.exec.return_value = SimpleNamespace(exit_code=7, output="failed long output")
        vm.read_file.return_value = b"\xff"
        result = tools.run_shell_command("exit 7")
        assert result.startswith("Exit c") and result.endswith("[output truncated]")
        assert vm.exec.call_args.args[0] == ["sh", "-c", "exit 7"]
        assert vm.exec.call_args.args[1].workdir == "/workspace/my-project"
        assert "not UTF-8" in tools.read_file("bad.txt")
        assert vm.read_file.call_args.args == ("/workspace/my-project/bad.txt",)
        assert tools.write_file("../hello.txt", "hi") == "Wrote /workspace/hello.txt."
        vm.write_file.assert_called_once_with("/workspace/hello.txt", "hi")
        tools.close()
        vm.delete.assert_called_once_with()


def test_async_tools_use_worker_threads_and_share_the_same_machine(machines):
    _, _, _ = machines
    tools = SmolTools()
    main_thread = threading.get_ident()
    with patch("agno.tools.smol.Machine.create") as create:
        vm = create.return_value
        vm.id = "vm-async"
        vm.exec.side_effect = lambda *args: SimpleNamespace(exit_code=0, output=f"thread={threading.get_ident()}")

        async def exercise():
            assert await tools.arun_python_code("print('ok')") != f"thread={main_thread}"
            assert await tools.arun_shell_command("echo ok") != f"thread={main_thread}"
            assert await tools.awrite_file("result.txt", "ok") == "Wrote /workspace/result.txt."
            vm.read_file.return_value = b"ok"
            assert await tools.aread_file("result.txt") == "ok"

        asyncio.run(exercise())
        assert create.call_count == 1
        assert (
            set(tools.functions)
            == set(tools.async_functions)
            == {"run_shell_command", "run_python_code", "write_file", "read_file"}
        )
        asyncio.run(tools.aclose())
        vm.delete.assert_called_once_with()


def test_close_waits_for_inflight_command(machines):
    _, _, _ = machines
    tools = SmolTools()
    entered, release = threading.Event(), threading.Event()
    with patch("agno.tools.smol.Machine.create") as create:
        vm = create.return_value
        vm.id = "vm-busy"

        def execute(*args):
            entered.set()
            assert release.wait(3)
            return SimpleNamespace(exit_code=0, output="done")

        vm.exec.side_effect = execute
        first = threading.Thread(target=lambda: tools.run_shell_command("sleep 1"))
        first.start()
        assert entered.wait(3)
        cleanup = threading.Thread(target=tools.close)
        cleanup.start()
        assert not vm.delete.called
        release.set()
        first.join(3)
        cleanup.join(3)
        assert not first.is_alive() and not cleanup.is_alive()
        vm.delete.assert_called_once_with()
