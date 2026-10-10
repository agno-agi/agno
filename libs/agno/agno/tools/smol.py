"""Run an agent's commands and file tools inside a local or cloud Smol microVM."""

from __future__ import annotations

import asyncio
import atexit
import posixpath
import threading
from typing import Literal

from pydantic import SecretStr

from agno.tools import Toolkit
from agno.utils.log import log_warning

try:
    from smol import ConnectOptions, ExecOptions, Machine, MachineConfig, ResourceSpec
except ImportError as exc:
    raise ImportError("SmolTools requires smolmachines: install 'agno[smol]'.") from exc


class SmolTools(Toolkit):
    """Run tools in one isolated VM, creating it on first use and reusing it.

    ``machine_id`` connects to an existing VM and never deletes it. A VM created
    by this toolkit is deleted by :meth:`close` or when the process exits.
    """

    def __init__(
        self,
        target: Literal["local", "cloud"] = "local",
        image: str = "python:3.12-alpine",
        network: bool = True,
        cpus: int = 2,
        memory_mb: int = 2048,
        machine_id: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        workdir: str = "/workspace",
        timeout: int = 60,
        ttl_seconds: int | None = 3600,
        max_output_chars: int = 12000,
        **kwargs,
    ):
        """Create a toolkit for local VMs or Smol Cloud.

        Args:
            target: ``local`` boots a VM on this host; ``cloud`` uses Smol Cloud.
            image: Container image with Python and a shell, or a local archive.
            network: Allow outbound network access from the guest.
            cpus: Virtual CPUs to allocate to a new VM.
            memory_mb: VM memory limit in MiB.
            machine_id: Connect to an existing VM without taking ownership.
            api_key: Optional Cloud token; defaults to SMOL_CLOUD_TOKEN.
            base_url: Optional Cloud API endpoint override.
            workdir: Working directory inside the VM for commands and files.
            timeout: Command timeout in seconds.
            ttl_seconds: Cloud VM expiry, including after an unclean host exit.
            max_output_chars: Maximum command output returned to the agent.
        """
        if target not in ("local", "cloud"):
            raise ValueError("target must be 'local' or 'cloud'")
        if cpus <= 0 or memory_mb <= 0:
            raise ValueError("cpus and memory_mb must be positive")
        if timeout <= 0 or max_output_chars <= 0:
            raise ValueError("timeout and max_output_chars must be positive")
        if not workdir.startswith("/"):
            raise ValueError("workdir must be an absolute guest path")
        self.target = target
        self.image = image
        self.network = network
        self.cpus = cpus
        self.memory_mb = memory_mb
        self.machine_id = machine_id
        self._api_key = SecretStr(api_key) if api_key is not None else None
        self.base_url = base_url
        self.workdir = posixpath.normpath(workdir)
        self.timeout = timeout
        self.ttl_seconds = ttl_seconds
        self.max_output_chars = max_output_chars
        self._machine: Machine | None = None
        self._owns_machine = False
        self._lock = threading.RLock()
        self._cleanup_registered = False

        super().__init__(
            name="smol_tools",
            tools=[self.run_shell_command, self.run_python_code, self.read_file, self.write_file],
            async_tools=[
                (self.arun_shell_command, "run_shell_command"),
                (self.arun_python_code, "run_python_code"),
                (self.aread_file, "read_file"),
                (self.awrite_file, "write_file"),
            ],
            **kwargs,
        )

    @property
    def active_machine_id(self) -> str | None:
        """ID of the running VM, for another toolkit or process to connect to."""
        with self._lock:
            return self._machine.id if self._machine is not None else self.machine_id

    def _connection(self) -> ConnectOptions:
        return ConnectOptions(
            target=self.target,
            api_key=self._api_key.get_secret_value() if self._api_key else None,
            base_url=self.base_url,
        )

    def _get_machine(self) -> Machine:
        # Callers hold _lock through each operation so close() cannot delete a
        # VM while a tool call is still using it.
        if self._machine is None:
            if self.machine_id is not None:
                machine = Machine.connect(self.machine_id, self._connection())
                if machine.state() == "stopped":
                    machine.start()
                machine.wait_until_ready()
                self._owns_machine = False
            else:
                machine = Machine.create(
                    MachineConfig(
                        image=self.image,
                        resources=ResourceSpec(cpus=self.cpus, memory_mb=self.memory_mb, network=self.network),
                        persistent=False,
                        ttl_seconds=self.ttl_seconds if self.target == "cloud" else None,
                    ),
                    self._connection(),
                )
                self._owns_machine = True
                if not self._cleanup_registered:
                    atexit.register(self._cleanup_at_exit)
                    self._cleanup_registered = True
            self._machine = machine
        return self._machine

    def _guest_path(self, path: str) -> str:
        return posixpath.normpath(path if path.startswith("/") else posixpath.join(self.workdir, path))

    def _format_result(self, result) -> str:
        output = result.output
        if result.exit_code != 0:
            output = f"Exit code {result.exit_code}" + (f"\n{output}" if output else "")
        if len(output) > self.max_output_chars:
            return output[: self.max_output_chars] + "\n[output truncated]"
        return output or "Command completed with no output."

    def run_shell_command(self, command: str) -> str:
        """Run a shell command inside the isolated VM and return its output."""
        try:
            with self._lock:
                result = self._get_machine().exec(
                    ["sh", "-c", command], ExecOptions(workdir=self.workdir, timeout=self.timeout)
                )
                return self._format_result(result)
        except Exception as exc:  # noqa: BLE001 - SDK transports may raise arbitrary I/O failures.
            log_warning(f"Smol VM command failed: {exc}")
            return f"Error running command in VM: {exc}"

    async def arun_shell_command(self, command: str) -> str:
        """Run a shell command inside the isolated VM without blocking the event loop."""
        return await asyncio.to_thread(self.run_shell_command, command)

    def run_python_code(self, code: str) -> str:
        """Run Python code inside the isolated VM and return its output."""
        try:
            with self._lock:
                result = self._get_machine().exec(
                    ["python3", "-c", code], ExecOptions(workdir=self.workdir, timeout=self.timeout)
                )
                return self._format_result(result)
        except Exception as exc:  # noqa: BLE001 - SDK transports may raise arbitrary I/O failures.
            log_warning(f"Smol VM Python execution failed: {exc}")
            return f"Error running Python in VM: {exc}"

    async def arun_python_code(self, code: str) -> str:
        """Run Python code inside the isolated VM without blocking the event loop."""
        return await asyncio.to_thread(self.run_python_code, code)

    def read_file(self, path: str) -> str:
        """Read a UTF-8 text file from the VM (relative paths use the working directory)."""
        try:
            with self._lock:
                data = self._get_machine().read_file(self._guest_path(path))
                text = data.decode("utf-8")
                if len(text) > self.max_output_chars:
                    return text[: self.max_output_chars] + "\n[output truncated]"
                return text
        except UnicodeDecodeError:
            return "Error: file is not UTF-8 text; use a shell command for binary files."
        except Exception as exc:  # noqa: BLE001 - SDK transports may raise arbitrary I/O failures.
            log_warning(f"Smol VM file read failed: {exc}")
            return f"Error reading file in VM: {exc}"

    async def aread_file(self, path: str) -> str:
        """Read a text file from the VM without blocking the event loop."""
        return await asyncio.to_thread(self.read_file, path)

    def write_file(self, path: str, content: str) -> str:
        """Write UTF-8 text to a file inside the VM (relative paths use the working directory)."""
        try:
            with self._lock:
                guest_path = self._guest_path(path)
                self._get_machine().write_file(guest_path, content)
                return f"Wrote {guest_path}."
        except Exception as exc:  # noqa: BLE001 - SDK transports may raise arbitrary I/O failures.
            log_warning(f"Smol VM file write failed: {exc}")
            return f"Error writing file in VM: {exc}"

    async def awrite_file(self, path: str, content: str) -> str:
        """Write text to a file in the VM without blocking the event loop."""
        return await asyncio.to_thread(self.write_file, path, content)

    def close(self) -> None:
        """Delete a VM created by this toolkit; leave an attached VM alone."""
        with self._lock:
            if self._machine is not None and self._owns_machine:
                try:
                    self._machine.delete()
                except Exception as exc:
                    if getattr(exc, "code", None) != "NOT_FOUND":
                        raise
            self._machine = None
            self._owns_machine = False
            if self._cleanup_registered:
                atexit.unregister(self._cleanup_at_exit)
                self._cleanup_registered = False

    def _cleanup_at_exit(self) -> None:
        try:
            self.close()
        except Exception as exc:  # noqa: BLE001 - SDK transports may raise arbitrary I/O failures.
            log_warning(f"Could not delete Smol VM at exit: {exc}")
