import asyncio
import json
import posixpath
from os import getenv
from textwrap import dedent
from threading import Lock
from typing import Any, Callable, Dict, Optional

from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.code_execution import prepare_python_code

DEFAULT_WORKING_DIRECTORY = "/home/tenki"
DEFAULT_MAX_OUTPUT_CHARS = 20_000
DEFAULT_SANDBOX_MAX_DURATION = 900
SANDBOX_ID_STATE_KEY = "tenki_sandbox_id"
SANDBOX_OWNED_STATE_KEY = "tenki_sandbox_owned"
WORKING_DIRECTORY_STATE_KEY = "tenki_working_directory"

DEFAULT_INSTRUCTIONS = dedent(
    """\
    You have access to a persistent Tenki sandbox for remote code execution and file operations.
    - Use `run_code` to execute Python code.
    - Use `run_shell_command` for shell commands and package installation.
    - Use `create_file`, `read_file`, `list_files`, and `delete_file` to manage sandbox files.
    - Use `change_directory` to update the working directory used by subsequent tools.
    - Use `get_sandbox_status` to inspect the active sandbox.
    - Auto-created sandboxes have a bounded lifetime. If `terminate_sandbox` is available, use it only when the user
      asks to end the persistent sandbox.
    Always report actual command output and errors instead of claiming that unexecuted code works.
    """
)


class TenkiTools(Toolkit):
    """Tools for executing commands and managing files in a persistent Tenki sandbox.

    Auto-created sandboxes are owned by the current Agno session and default to a bounded 15-minute lifetime.
    Their IDs and ownership are recorded in session state so callers can persist or explicitly terminate them.
    """

    def __init__(
        self,
        auth_token: Optional[str] = None,
        base_url: Optional[str] = None,
        workspace_id: Optional[str] = None,
        timeout: int = 180,
        command_timeout: int = 30,
        max_output_chars: Optional[int] = DEFAULT_MAX_OUTPUT_CHARS,
        sandbox_max_duration: Optional[int] = DEFAULT_SANDBOX_MAX_DURATION,
        sandbox_id: Optional[str] = None,
        auto_create_sandbox: bool = True,
        enable_terminate_sandbox: bool = False,
        allow_inbound: bool = False,
        allow_outbound: bool = True,
        sandbox_options: Optional[Dict[str, Any]] = None,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        client: Optional[Any] = None,
        async_client: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        if client is None or async_client is None:
            try:
                from tenki import AsyncClient, Client
            except ImportError:
                raise ImportError(
                    "`tenki` not installed. Please install it with `pip install tenki` using Python 3.10 or newer."
                )

            client_options: Dict[str, Any] = {"timeout": timeout}
            if auth_token is not None:
                client_options["auth_token"] = auth_token
            if base_url is not None:
                client_options["base_url"] = base_url
            client = client or Client(**client_options)
            async_client = async_client or AsyncClient(**client_options)

        assert client is not None
        assert async_client is not None
        if max_output_chars is not None and max_output_chars <= 0:
            raise ValueError("max_output_chars must be greater than zero or None")
        if sandbox_max_duration is not None and sandbox_max_duration <= 0:
            raise ValueError("sandbox_max_duration must be greater than zero or None")
        self.client = client
        self.async_client = async_client
        self.command_timeout = command_timeout
        self.max_output_chars = max_output_chars
        self.sandbox_timeout = timeout
        self.sandbox_id = sandbox_id
        self.auto_create_sandbox = auto_create_sandbox
        self._creation_locks_guard = Lock()
        self._registration_lock = Lock()
        self._sync_creation_locks: Dict[tuple[Optional[str], str], Any] = {}
        self._async_creation_locks: Dict[tuple[Optional[str], str, int], asyncio.Lock] = {}
        self._session_sandbox_ids: Dict[tuple[Optional[str], str], str] = {}
        self.sandbox_options: Dict[str, Any] = {
            "allow_inbound": allow_inbound,
            "allow_outbound": allow_outbound,
            "timeout": timeout,
        }
        if sandbox_max_duration is not None:
            self.sandbox_options["max_duration"] = sandbox_max_duration
        self.sandbox_options.update(sandbox_options or {})
        if workspace_id is not None:
            self.sandbox_options["workspace_id"] = workspace_id
        elif not self.sandbox_options.get("workspace_id") and getenv("TENKI_WORKSPACE_ID"):
            self.sandbox_options["workspace_id"] = getenv("TENKI_WORKSPACE_ID")
        self.instructions = instructions or DEFAULT_INSTRUCTIONS

        tools: list[Callable[..., Any]] = [
            self.run_code,
            self.run_shell_command,
            self.create_file,
            self.read_file,
            self.list_files,
            self.delete_file,
            self.change_directory,
            self.get_sandbox_status,
        ]
        async_tools: list[tuple[Callable[..., Any], str]] = [
            (self.arun_code, "run_code"),
            (self.arun_shell_command, "run_shell_command"),
            (self.acreate_file, "create_file"),
            (self.aread_file, "read_file"),
            (self.alist_files, "list_files"),
            (self.adelete_file, "delete_file"),
            (self.achange_directory, "change_directory"),
            (self.aget_sandbox_status, "get_sandbox_status"),
        ]
        requires_confirmation_tools = list(kwargs.pop("requires_confirmation_tools", None) or [])
        if enable_terminate_sandbox:
            tools.append(self.terminate_sandbox)
            async_tools.append((self.aterminate_sandbox, "terminate_sandbox"))
            if "terminate_sandbox" not in requires_confirmation_tools:
                requires_confirmation_tools.append("terminate_sandbox")

        super().__init__(
            name="tenki_tools",
            tools=tools,
            async_tools=async_tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            requires_confirmation_tools=requires_confirmation_tools,
            timeout=timeout,
            **kwargs,
        )

    @staticmethod
    def _session_state(run_context: RunContext) -> Dict[str, Any]:
        if run_context.session_state is None:
            run_context.session_state = {}
        run_context.session_state.setdefault(WORKING_DIRECTORY_STATE_KEY, DEFAULT_WORKING_DIRECTORY)
        return run_context.session_state

    @staticmethod
    def _session_key(run_context: RunContext) -> tuple[Optional[str], str]:
        return run_context.user_id, run_context.session_id

    def _sync_creation_lock(self, run_context: RunContext) -> Any:
        key = self._session_key(run_context)
        with self._creation_locks_guard:
            return self._sync_creation_locks.setdefault(key, Lock())

    def _async_creation_lock(self, run_context: RunContext) -> asyncio.Lock:
        session_key = self._session_key(run_context)
        key = (*session_key, id(asyncio.get_running_loop()))
        with self._creation_locks_guard:
            return self._async_creation_locks.setdefault(key, asyncio.Lock())

    def _registered_sandbox_id(self, run_context: RunContext) -> Optional[str]:
        with self._registration_lock:
            return self._session_sandbox_ids.get(self._session_key(run_context))

    def _remember_sandbox(self, run_context: RunContext, sandbox_id: str) -> None:
        with self._registration_lock:
            self._session_sandbox_ids[self._session_key(run_context)] = sandbox_id

    def _clear_sandbox_state(self, run_context: RunContext, state: Dict[str, Any]) -> None:
        sandbox_id = state.pop(SANDBOX_ID_STATE_KEY, None)
        state.pop(SANDBOX_OWNED_STATE_KEY, None)
        if self.sandbox_id:
            return
        with self._registration_lock:
            key = self._session_key(run_context)
            registered_id = self._session_sandbox_ids.get(key)
            if sandbox_id is None or registered_id == sandbox_id:
                self._session_sandbox_ids.pop(key, None)

    def _get_reusable_sandbox(self, run_context: RunContext) -> Optional[Any]:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY) or self._registered_sandbox_id(run_context)
        if not sandbox_id:
            return None
        try:
            sandbox = self.client.get(sandbox_id)
        except Exception as error:
            if self.sandbox_id or not self._is_missing_sandbox_error(error):
                raise
            self._clear_sandbox_state(run_context, state)
            return None
        if sandbox.state in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}:
            if self.sandbox_id:
                raise RuntimeError(f"Tenki sandbox {sandbox.id} is in terminal state {sandbox.state}")
            self._clear_sandbox_state(run_context, state)
            return None
        state[SANDBOX_ID_STATE_KEY] = sandbox.id
        state.setdefault(SANDBOX_OWNED_STATE_KEY, self.sandbox_id is None)
        if not self.sandbox_id:
            self._remember_sandbox(run_context, sandbox.id)
        return self._prepare_sandbox(sandbox)

    async def _aget_reusable_sandbox(self, run_context: RunContext) -> Optional[Any]:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY) or self._registered_sandbox_id(run_context)
        if not sandbox_id:
            return None
        try:
            sandbox = await self.async_client.get(sandbox_id)
        except Exception as error:
            if self.sandbox_id or not self._is_missing_sandbox_error(error):
                raise
            self._clear_sandbox_state(run_context, state)
            return None
        if sandbox.state in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}:
            if self.sandbox_id:
                raise RuntimeError(f"Tenki sandbox {sandbox.id} is in terminal state {sandbox.state}")
            self._clear_sandbox_state(run_context, state)
            return None
        state[SANDBOX_ID_STATE_KEY] = sandbox.id
        state.setdefault(SANDBOX_OWNED_STATE_KEY, self.sandbox_id is None)
        if not self.sandbox_id:
            self._remember_sandbox(run_context, sandbox.id)
        return await self._aprepare_sandbox(sandbox)

    def _register_created_sandbox(
        self, run_context: RunContext, state: Dict[str, Any], sandbox_id: str
    ) -> Optional[str]:
        with self._registration_lock:
            key = self._session_key(run_context)
            existing_id = state.get(SANDBOX_ID_STATE_KEY) or self._session_sandbox_ids.get(key)
            if existing_id:
                state[SANDBOX_ID_STATE_KEY] = existing_id
                state[SANDBOX_OWNED_STATE_KEY] = True
                return existing_id
            self._session_sandbox_ids[key] = sandbox_id
            state[SANDBOX_ID_STATE_KEY] = sandbox_id
            state[SANDBOX_OWNED_STATE_KEY] = True
            state[WORKING_DIRECTORY_STATE_KEY] = DEFAULT_WORKING_DIRECTORY
            return None

    def _get_or_create_sandbox(self, run_context: RunContext) -> Any:
        sandbox = self._get_reusable_sandbox(run_context)
        if sandbox is not None:
            return sandbox
        if not self.auto_create_sandbox:
            raise RuntimeError("No Tenki sandbox is associated with this session and auto-creation is disabled")

        with self._sync_creation_lock(run_context):
            sandbox = self._get_reusable_sandbox(run_context)
            if sandbox is not None:
                return sandbox
            sandbox = self.client.create(**self.sandbox_options)
            state = self._session_state(run_context)
            winning_id = self._register_created_sandbox(run_context, state, sandbox.id)
            if winning_id is not None:
                sandbox.close()
                return self._prepare_sandbox(self.client.get(winning_id))
            return self._prepare_sandbox(sandbox)

    async def _aget_or_create_sandbox(self, run_context: RunContext) -> Any:
        sandbox = await self._aget_reusable_sandbox(run_context)
        if sandbox is not None:
            return sandbox
        if not self.auto_create_sandbox:
            raise RuntimeError("No Tenki sandbox is associated with this session and auto-creation is disabled")

        async with self._async_creation_lock(run_context):
            sandbox = await self._aget_reusable_sandbox(run_context)
            if sandbox is not None:
                return sandbox
            sandbox = await self.async_client.create(**self.sandbox_options)
            state = self._session_state(run_context)
            winning_id = self._register_created_sandbox(run_context, state, sandbox.id)
            if winning_id is not None:
                await sandbox.close()
                return await self._aprepare_sandbox(await self.async_client.get(winning_id))
            return await self._aprepare_sandbox(sandbox)

    def _get_existing_sandbox(self, run_context: RunContext) -> Any:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY) or self._registered_sandbox_id(run_context)
        if not sandbox_id:
            raise RuntimeError("No Tenki sandbox is associated with this session")
        try:
            return self.client.get(sandbox_id)
        except Exception as error:
            if not self.sandbox_id and self._is_missing_sandbox_error(error):
                self._clear_sandbox_state(run_context, state)
                raise RuntimeError("No Tenki sandbox is associated with this session") from error
            raise

    async def _aget_existing_sandbox(self, run_context: RunContext) -> Any:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY) or self._registered_sandbox_id(run_context)
        if not sandbox_id:
            raise RuntimeError("No Tenki sandbox is associated with this session")
        try:
            return await self.async_client.get(sandbox_id)
        except Exception as error:
            if not self.sandbox_id and self._is_missing_sandbox_error(error):
                self._clear_sandbox_state(run_context, state)
                raise RuntimeError("No Tenki sandbox is associated with this session") from error
            raise

    def _prepare_sandbox(self, sandbox: Any) -> Any:
        if sandbox.state == "PAUSED":
            sandbox.resume()
        if sandbox.state in {"CREATING", "RESUMING", "UNSPECIFIED"}:
            sandbox.wait_ready(self.sandbox_timeout)
        return sandbox

    async def _aprepare_sandbox(self, sandbox: Any) -> Any:
        if sandbox.state == "PAUSED":
            await sandbox.resume()
        if sandbox.state in {"CREATING", "RESUMING", "UNSPECIFIED"}:
            await sandbox.wait_ready(self.sandbox_timeout)
        return sandbox

    @staticmethod
    def _is_missing_sandbox_error(error: Exception) -> bool:
        return isinstance(error, KeyError) or error.__class__.__name__ == "SessionNotFoundError"

    def _truncate_command_output(self, text: str) -> tuple[str, bool]:
        if self.max_output_chars is None or len(text) <= self.max_output_chars:
            return text, False
        return (
            f"{text[: self.max_output_chars]}\n"
            f"[Output truncated after {self.max_output_chars} characters; original length: {len(text)}.]",
            True,
        )

    def _format_command_result(self, result: Any) -> str:
        stdout, stdout_truncated = self._truncate_command_output(result.stdout_text)
        stderr, stderr_truncated = self._truncate_command_output(result.stderr_text)
        payload = {
            "status": "success" if result.ok else "error",
            "exit_code": result.exit_code,
            "stdout": stdout,
            "stderr": stderr,
        }
        if stdout_truncated:
            payload["stdout_truncated"] = True
            payload["stdout_original_chars"] = len(result.stdout_text)
        if stderr_truncated:
            payload["stderr_truncated"] = True
            payload["stderr_original_chars"] = len(result.stderr_text)
        return json.dumps(payload)

    @staticmethod
    def _resolve_path(run_context: RunContext, path: str) -> str:
        state = TenkiTools._session_state(run_context)
        working_directory = state[WORKING_DIRECTORY_STATE_KEY]
        resolved_path = posixpath.normpath(path if posixpath.isabs(path) else posixpath.join(working_directory, path))
        if posixpath.commonpath([DEFAULT_WORKING_DIRECTORY, resolved_path]) != DEFAULT_WORKING_DIRECTORY:
            raise ValueError(f"Path must remain within {DEFAULT_WORKING_DIRECTORY}: {path}")
        return resolved_path

    def run_code(self, run_context: RunContext, code: str) -> str:
        """Execute Python code in the Tenki sandbox and return its output.

        Args:
            code: Python code to execute.
        """
        sandbox = self._get_or_create_sandbox(run_context)
        result = sandbox.exec(
            "python3",
            "-c",
            prepare_python_code(code),
            cwd=self._session_state(run_context)[WORKING_DIRECTORY_STATE_KEY],
            timeout=self.command_timeout,
        )
        return self._format_command_result(result)

    async def arun_code(self, run_context: RunContext, code: str) -> str:
        """Execute Python code asynchronously in the Tenki sandbox and return its output.

        Args:
            code: Python code to execute.
        """
        sandbox = await self._aget_or_create_sandbox(run_context)
        result = await sandbox.exec(
            "python3",
            "-c",
            prepare_python_code(code),
            cwd=self._session_state(run_context)[WORKING_DIRECTORY_STATE_KEY],
            timeout=self.command_timeout,
        )
        return self._format_command_result(result)

    def run_shell_command(self, run_context: RunContext, command: str) -> str:
        """Execute a Bash command in the Tenki sandbox and return its output.

        Args:
            command: Bash command to execute.
        """
        sandbox = self._get_or_create_sandbox(run_context)
        result = sandbox.shell(
            command,
            cwd=self._session_state(run_context)[WORKING_DIRECTORY_STATE_KEY],
            timeout=self.command_timeout,
        )
        return self._format_command_result(result)

    async def arun_shell_command(self, run_context: RunContext, command: str) -> str:
        """Execute a Bash command asynchronously in the Tenki sandbox and return its output.

        Args:
            command: Bash command to execute.
        """
        sandbox = await self._aget_or_create_sandbox(run_context)
        result = await sandbox.shell(
            command,
            cwd=self._session_state(run_context)[WORKING_DIRECTORY_STATE_KEY],
            timeout=self.command_timeout,
        )
        return self._format_command_result(result)

    def create_file(self, run_context: RunContext, path: str, content: str) -> str:
        """Create or overwrite a text file in the Tenki sandbox.

        Args:
            path: File path relative to the current working directory.
            content: Text content to write.
        """
        resolved_path = self._resolve_path(run_context, path)
        sandbox = self._get_or_create_sandbox(run_context)
        parent_directory = posixpath.dirname(resolved_path)
        if parent_directory != DEFAULT_WORKING_DIRECTORY:
            sandbox.fs.mkdir(parent_directory, recursive=True)
        sandbox.fs.write_text(resolved_path, content)
        return json.dumps({"status": "success", "path": resolved_path})

    async def acreate_file(self, run_context: RunContext, path: str, content: str) -> str:
        """Create or overwrite a text file asynchronously in the Tenki sandbox.

        Args:
            path: File path relative to the current working directory.
            content: Text content to write.
        """
        resolved_path = self._resolve_path(run_context, path)
        sandbox = await self._aget_or_create_sandbox(run_context)
        parent_directory = posixpath.dirname(resolved_path)
        if parent_directory != DEFAULT_WORKING_DIRECTORY:
            await sandbox.fs.mkdir(parent_directory, recursive=True)
        await sandbox.fs.write_text(resolved_path, content)
        return json.dumps({"status": "success", "path": resolved_path})

    def read_file(self, run_context: RunContext, path: str) -> str:
        """Read a text file from the Tenki sandbox.

        Args:
            path: File path relative to the current working directory.
        """
        resolved_path = self._resolve_path(run_context, path)
        sandbox = self._get_or_create_sandbox(run_context)
        return sandbox.fs.read_text(resolved_path)

    async def aread_file(self, run_context: RunContext, path: str) -> str:
        """Read a text file asynchronously from the Tenki sandbox.

        Args:
            path: File path relative to the current working directory.
        """
        resolved_path = self._resolve_path(run_context, path)
        sandbox = await self._aget_or_create_sandbox(run_context)
        return await sandbox.fs.read_text(resolved_path)

    @staticmethod
    def _file_info(file_info: Any) -> Dict[str, Any]:
        return {
            "path": file_info.path,
            "size": file_info.size,
            "mode": file_info.mode,
            "is_dir": file_info.is_dir,
            "modified_unix_ns": file_info.modified_unix_ns,
            "is_symlink": file_info.is_symlink,
            "symlink_target": file_info.symlink_target,
        }

    def list_files(self, run_context: RunContext, path: str = ".", include_hidden: bool = False) -> str:
        """List files in a Tenki sandbox directory.

        Args:
            path: Directory path relative to the current working directory.
            include_hidden: Include hidden directory entries.
        """
        resolved_path = self._resolve_path(run_context, path)
        sandbox = self._get_or_create_sandbox(run_context)
        files = sorted(sandbox.fs.list(resolved_path, include_hidden=include_hidden), key=lambda item: item.path)
        return json.dumps(
            {
                "status": "success",
                "path": resolved_path,
                "files": [self._file_info(file_info) for file_info in files],
            }
        )

    async def alist_files(self, run_context: RunContext, path: str = ".", include_hidden: bool = False) -> str:
        """List files asynchronously in a Tenki sandbox directory.

        Args:
            path: Directory path relative to the current working directory.
            include_hidden: Include hidden directory entries.
        """
        resolved_path = self._resolve_path(run_context, path)
        sandbox = await self._aget_or_create_sandbox(run_context)
        files = sorted(await sandbox.fs.list(resolved_path, include_hidden=include_hidden), key=lambda item: item.path)
        return json.dumps(
            {
                "status": "success",
                "path": resolved_path,
                "files": [self._file_info(file_info) for file_info in files],
            }
        )

    def delete_file(self, run_context: RunContext, path: str) -> str:
        """Delete a file or directory from the Tenki sandbox.

        Args:
            path: Path relative to the current working directory.
        """
        resolved_path = self._resolve_path(run_context, path)
        if resolved_path == self._session_state(run_context)[WORKING_DIRECTORY_STATE_KEY]:
            raise ValueError("Cannot delete the current Tenki working directory")
        sandbox = self._get_or_create_sandbox(run_context)
        sandbox.fs.remove(resolved_path, recursive=True)
        return json.dumps({"status": "success", "path": resolved_path})

    async def adelete_file(self, run_context: RunContext, path: str) -> str:
        """Delete a file or directory asynchronously from the Tenki sandbox.

        Args:
            path: Path relative to the current working directory.
        """
        resolved_path = self._resolve_path(run_context, path)
        if resolved_path == self._session_state(run_context)[WORKING_DIRECTORY_STATE_KEY]:
            raise ValueError("Cannot delete the current Tenki working directory")
        sandbox = await self._aget_or_create_sandbox(run_context)
        await sandbox.fs.remove(resolved_path, recursive=True)
        return json.dumps({"status": "success", "path": resolved_path})

    def change_directory(self, run_context: RunContext, path: str) -> str:
        """Change the working directory used by subsequent Tenki tools.

        Args:
            path: Directory path relative to the current working directory.
        """
        resolved_path = self._resolve_path(run_context, path)
        sandbox = self._get_or_create_sandbox(run_context)
        if not sandbox.fs.stat(resolved_path).is_dir:
            raise NotADirectoryError(resolved_path)
        state = self._session_state(run_context)
        state[WORKING_DIRECTORY_STATE_KEY] = resolved_path
        return json.dumps({"status": "success", "working_directory": resolved_path})

    async def achange_directory(self, run_context: RunContext, path: str) -> str:
        """Change the working directory asynchronously for subsequent Tenki tools.

        Args:
            path: Directory path relative to the current working directory.
        """
        resolved_path = self._resolve_path(run_context, path)
        sandbox = await self._aget_or_create_sandbox(run_context)
        if not (await sandbox.fs.stat(resolved_path)).is_dir:
            raise NotADirectoryError(resolved_path)
        state = self._session_state(run_context)
        state[WORKING_DIRECTORY_STATE_KEY] = resolved_path
        return json.dumps({"status": "success", "working_directory": resolved_path})

    def _format_sandbox_status(self, run_context: RunContext, sandbox: Optional[Any]) -> str:
        state = run_context.session_state or {}
        if sandbox is None:
            return json.dumps(
                {
                    "status": "success",
                    "sandbox_id": None,
                    "name": None,
                    "state": "ABSENT",
                    "owned": False,
                    "working_directory": state.get(WORKING_DIRECTORY_STATE_KEY, DEFAULT_WORKING_DIRECTORY),
                }
            )
        return json.dumps(
            {
                "status": "success",
                "sandbox_id": sandbox.id,
                "name": sandbox.info.name,
                "state": sandbox.state,
                "owned": state.get(
                    SANDBOX_OWNED_STATE_KEY,
                    self.sandbox_id is None and self._registered_sandbox_id(run_context) == sandbox.id,
                ),
                "working_directory": state.get(WORKING_DIRECTORY_STATE_KEY, DEFAULT_WORKING_DIRECTORY),
            }
        )

    def _get_sandbox_for_status(self, run_context: RunContext) -> Optional[Any]:
        state = run_context.session_state or {}
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY) or self._registered_sandbox_id(run_context)
        if not sandbox_id:
            return None
        try:
            return self.client.get(sandbox_id)
        except Exception as error:
            if not self._is_missing_sandbox_error(error):
                raise
            if not self.sandbox_id:
                self._clear_sandbox_state(run_context, run_context.session_state or {})
            return None

    async def _aget_sandbox_for_status(self, run_context: RunContext) -> Optional[Any]:
        state = run_context.session_state or {}
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY) or self._registered_sandbox_id(run_context)
        if not sandbox_id:
            return None
        try:
            return await self.async_client.get(sandbox_id)
        except Exception as error:
            if not self._is_missing_sandbox_error(error):
                raise
            if not self.sandbox_id:
                self._clear_sandbox_state(run_context, run_context.session_state or {})
            return None

    def get_sandbox_status(self, run_context: RunContext) -> str:
        """Get the current Tenki sandbox status without creating or resuming it."""
        sandbox = self._get_sandbox_for_status(run_context)
        return self._format_sandbox_status(run_context, sandbox)

    async def aget_sandbox_status(self, run_context: RunContext) -> str:
        """Get the current Tenki sandbox status asynchronously without creating or resuming it."""
        sandbox = await self._aget_sandbox_for_status(run_context)
        return self._format_sandbox_status(run_context, sandbox)

    def terminate_sandbox(self, run_context: RunContext) -> str:
        """Terminate the current Tenki sandbox."""
        sandbox = self._get_existing_sandbox(run_context)
        if sandbox.state not in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}:
            sandbox.close()
        state = self._session_state(run_context)
        self._clear_sandbox_state(run_context, state)
        if self.sandbox_id == sandbox.id:
            self.sandbox_id = None
        return json.dumps({"status": "success", "sandbox_id": sandbox.id, "state": sandbox.state})

    async def aterminate_sandbox(self, run_context: RunContext) -> str:
        """Terminate the current Tenki sandbox asynchronously."""
        sandbox = await self._aget_existing_sandbox(run_context)
        if sandbox.state not in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}:
            await sandbox.close()
        state = self._session_state(run_context)
        self._clear_sandbox_state(run_context, state)
        if self.sandbox_id == sandbox.id:
            self.sandbox_id = None
        return json.dumps({"status": "success", "sandbox_id": sandbox.id, "state": sandbox.state})
