import asyncio
import atexit
import base64
import json
import posixpath
import shlex
import threading
from pathlib import PurePosixPath
from textwrap import dedent
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.code_execution import prepare_python_code
from agno.utils.log import log_debug, log_error, log_info

try:
    from boxlite import SimpleBox
except ImportError:
    raise ImportError("`boxlite` not installed. Please install using `pip install boxlite`")

DEFAULT_INSTRUCTIONS = dedent(
    """\
    You have access to a persistent BoxLite micro-VM sandbox for code execution. The sandbox
    maintains state (files, installed packages, working directory) across interactions.
    Available tools:
    - `run_code`: Execute Python code in the sandbox
    - `run_shell_command`: Execute shell commands (bash)
    - `create_file`: Create or update files
    - `read_file`: Read file contents
    - `list_files`: List directory contents
    - `delete_file`: Delete files or directories
    - `change_directory`: Change the working directory
    MANDATORY: When users ask for code, you MUST:
    1. Write the code
    2. Execute it using run_code (or run_shell_command)
    3. Show the actual output/results
    4. Never just provide code without executing it
    CRITICAL WORKFLOW:
    1. Before running scripts, install any required packages with: run_shell_command("pip install <packages>")
    2. When running scripts, capture both output AND errors
    3. If a script produces no output, check for errors or add print statements

    Remember: Your job is to provide working, executed code, not just code snippets!
    """
)


class BoxLiteTools(Toolkit):
    """Run agent-generated code and shell commands inside a BoxLite micro-VM sandbox.

    BoxLite (https://github.com/boxlite-ai/boxlite) boots a lightweight, isolated micro-VM
    from an OCI image locally in sub-second time, so untrusted code never touches the host.
    One box is created when the toolkit is constructed and reused across tool calls; call
    ``shutdown_sandbox`` (or let ``atexit`` fire) to tear it down.
    """

    def __init__(
        self,
        image: str = "python:slim",
        cpus: Optional[int] = None,
        memory_mib: Optional[int] = None,
        working_directory: str = "/root",
        timeout: int = 300,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        **kwargs,
    ):
        """Initialize the BoxLite toolkit and boot a sandbox.

        Args:
            image: OCI image the sandbox boots from (default: ``"python:slim"``).
            cpus: Number of vCPUs for the sandbox (default: BoxLite runtime default).
            memory_mib: Memory limit in MiB (default: BoxLite runtime default).
            working_directory: Directory commands and relative file paths resolve against.
            timeout: Seconds to allow each command to run before it is killed.
            instructions: Override the default agent instructions.
            add_instructions: Whether to add the instructions to the agent's system message.
        """
        self.image = image
        self.cpus = cpus
        self.memory_mib = memory_mib
        self.working_directory = working_directory
        self.timeout = timeout
        self._cwd = working_directory

        # BoxLite's synchronous API refuses to run inside an already-running asyncio loop,
        # and Agno invokes sync tool callables inline on the agent's loop during `arun()`.
        # So we drive the async SimpleBox on a private event loop in its own thread; bridging
        # via run_coroutine_threadsafe is safe from both sync and async agent runs.
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, name="boxlite-tools-loop", daemon=True
        )
        self._loop_thread.start()

        self._box: Optional[SimpleBox] = None
        try:
            self._box = SimpleBox(image=self.image, cpus=self.cpus, memory_mib=self.memory_mib)
            self._await(self._box.start(), timeout=max(self.timeout, 600))
            # The image's WORKDIR is not guaranteed to exist; bootstrap it before use.
            self._exec_shell(f"mkdir -p {_q(self.working_directory)}")
            log_info(f"Started BoxLite sandbox from image '{self.image}'")
        except Exception as e:
            self._teardown()
            log_error(f"Could not start BoxLite sandbox: {e}")
            raise

        atexit.register(self.shutdown_sandbox)

        tools: List[Any] = [
            self.run_code,
            self.run_shell_command,
            self.create_file,
            self.read_file,
            self.list_files,
            self.delete_file,
            self.change_directory,
            self.shutdown_sandbox,
        ]
        super().__init__(
            name="boxlite_tools",
            tools=tools,
            instructions=instructions or DEFAULT_INSTRUCTIONS,
            add_instructions=add_instructions,
            timeout=timeout,
            **kwargs,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _await(self, coro, timeout: Optional[float] = None):
        """Run a SimpleBox coroutine on the private loop and block for its result."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    def _exec_shell(self, command: str, cwd: Optional[str] = None):
        """Run a shell command string in the sandbox and return its ExecResult."""
        if self._box is None:
            raise RuntimeError("BoxLite sandbox has been shut down.")
        return self._await(
            self._box.exec("sh", "-c", command, cwd=cwd, timeout=self.timeout),
            timeout=self.timeout + 30,
        )

    @staticmethod
    def _combine(result) -> str:
        """Merge stdout and stderr so the agent sees tracebacks and diagnostics."""
        parts = [part for part in (result.stdout, result.stderr) if part]
        output = "".join(parts)
        if output:
            return output
        return f"(no output, exit code {result.exit_code})"

    def _teardown(self) -> None:
        """Stop the private event loop and join its thread. Idempotent."""
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread.is_alive():
            self._loop_thread.join(timeout=10)
        if not self._loop.is_closed():
            self._loop.close()

    # ── Tools ─────────────────────────────────────────────────────────────────
    def run_code(self, code: str) -> str:
        """Execute Python code in the sandbox.

        Args:
            code: Python code to execute.

        Returns:
            Combined stdout/stderr of the execution.
        """
        try:
            result = self._await(
                self._box.exec(
                    "python", "-c", prepare_python_code(code), cwd=self._cwd, timeout=self.timeout
                ),
                timeout=self.timeout + 30,
            )
            return self._combine(result)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error executing code: {str(e)}"})

    def run_shell_command(self, command: str) -> str:
        """Execute a shell command in the sandbox.

        Args:
            command: Shell command to execute.

        Returns:
            Combined stdout/stderr of the command.
        """
        try:
            stripped = command.strip()
            if stripped.startswith("cd ") and "&&" not in stripped and ";" not in stripped:
                return self.change_directory(stripped[3:].strip())
            return self._combine(self._exec_shell(command, cwd=self._cwd))
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error executing command: {str(e)}"})

    def create_file(self, file_path: str, content: str) -> str:
        """Create or overwrite a file in the sandbox.

        Args:
            file_path: File path, relative to the working directory or absolute.
            content: Content to write to the file.

        Returns:
            Success message or JSON error.
        """
        try:
            path = self._resolve(file_path)
            parent = posixpath.dirname(path)
            # base64 round-trip writes any content verbatim (quotes, newlines, the EOF
            # sentinel, binary) — avoiding the escaping pitfalls of a shell heredoc.
            encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
            command = f"mkdir -p {_q(parent)} && printf %s {_q(encoded)} | base64 -d > {_q(path)}"
            result = self._exec_shell(command)
            if result.exit_code != 0:
                return json.dumps(
                    {"status": "error", "message": f"Failed to create file: {self._combine(result)}"}
                )
            return f"File created/updated: {path}"
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error creating file: {str(e)}"})

    def read_file(self, file_path: str) -> str:
        """Read a file from the sandbox.

        Args:
            file_path: File path, relative to the working directory or absolute.

        Returns:
            File contents or JSON error.
        """
        try:
            path = self._resolve(file_path)
            result = self._exec_shell(f"cat {_q(path)}")
            if result.exit_code != 0:
                return json.dumps(
                    {"status": "error", "message": f"Error reading file: {self._combine(result)}"}
                )
            return result.stdout
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error reading file: {str(e)}"})

    def list_files(self, directory: Optional[str] = None) -> str:
        """List files in a directory.

        Args:
            directory: Directory to list (defaults to the current working directory).

        Returns:
            Directory listing or JSON error.
        """
        try:
            path = self._resolve(directory) if directory is not None else self._cwd
            result = self._exec_shell(f"ls -la {_q(path)}")
            if result.exit_code != 0:
                return json.dumps(
                    {"status": "error", "message": f"Error listing directory: {self._combine(result)}"}
                )
            return f"Contents of {path}:\n{result.stdout}"
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error listing files: {str(e)}"})

    def delete_file(self, file_path: str) -> str:
        """Delete a file or directory from the sandbox.

        Args:
            file_path: File or directory path, relative to the working directory or absolute.

        Returns:
            Success message or JSON error.
        """
        try:
            path = self._resolve(file_path)
            check = self._exec_shell(f"test -d {_q(path)} && echo directory || echo file")
            flags = "-rf" if "directory" in check.stdout else "-f"
            result = self._exec_shell(f"rm {flags} {_q(path)}")
            if result.exit_code != 0:
                return json.dumps(
                    {"status": "error", "message": f"Failed to delete: {self._combine(result)}"}
                )
            return f"Deleted: {path}"
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error deleting file: {str(e)}"})

    def change_directory(self, directory: str) -> str:
        """Change the current working directory used by subsequent commands.

        Args:
            directory: Directory to change to, relative to the working directory or absolute.

        Returns:
            Success message or error.
        """
        try:
            path = self._resolve(directory)
            result = self._exec_shell(f"test -d {_q(path)} && echo exists || echo missing")
            if "exists" in result.stdout:
                self._cwd = path
                log_debug(f"Working directory changed to: {path}")
                return f"Changed directory to: {path}"
            return f"Error: Directory {path} not found"
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error changing directory: {str(e)}"})

    def shutdown_sandbox(self) -> str:
        """Stop and remove the sandbox and release its resources. Idempotent.

        Returns:
            Success message or JSON error.
        """
        try:
            if self._box is not None:
                try:
                    self._await(self._box.stop(), timeout=self.timeout)
                finally:
                    self._box = None
            self._teardown()
            return "BoxLite sandbox shut down."
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error shutting down sandbox: {str(e)}"})

    def _resolve(self, file_path: str) -> str:
        """Resolve a path against the working directory and normalize it (POSIX)."""
        path = PurePosixPath(file_path)
        if not path.is_absolute():
            path = PurePosixPath(self._cwd) / path
        return posixpath.normpath(str(path))


def _q(value: str) -> str:
    """Quote a string for safe interpolation into a /bin/sh command."""
    return shlex.quote(value)
