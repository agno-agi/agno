import json
import posixpath
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, Optional

from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.code_execution import prepare_python_code

DEFAULT_WORKING_DIRECTORY = "/home/tenki"
SANDBOX_ID_STATE_KEY = "tenki_sandbox_id"
WORKING_DIRECTORY_STATE_KEY = "tenki_working_directory"

DEFAULT_INSTRUCTIONS = dedent(
    """\
    You have access to a persistent Tenki sandbox for remote code execution and file operations.
    - Use `run_code` to execute Python code.
    - Use `run_shell_command` for shell commands and package installation.
    - Use `create_file`, `read_file`, `list_files`, and `delete_file` to manage sandbox files.
    - Use `change_directory` to update the working directory used by subsequent tools.
    - Use `get_sandbox_status` to inspect the active sandbox.
    Always report actual command output and errors instead of claiming that unexecuted code works.
    """
)


class TenkiTools(Toolkit):
    """Tools for executing commands and managing files in a persistent Tenki sandbox."""

    def __init__(
        self,
        auth_token: Optional[str] = None,
        base_url: Optional[str] = None,
        workspace_id: Optional[str] = None,
        timeout: int = 180,
        command_timeout: int = 30,
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
        self.client = client
        self.async_client = async_client
        self.command_timeout = command_timeout
        self.sandbox_timeout = timeout
        self.sandbox_id = sandbox_id
        self.auto_create_sandbox = auto_create_sandbox
        self.sandbox_options: Dict[str, Any] = {
            "allow_inbound": allow_inbound,
            "allow_outbound": allow_outbound,
            "timeout": timeout,
        }
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

    def _get_or_create_sandbox(self, run_context: RunContext) -> Any:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY)
        if sandbox_id:
            try:
                sandbox = self.client.get(sandbox_id)
            except Exception as error:
                if self.sandbox_id or not self._is_missing_sandbox_error(error):
                    raise
                state.pop(SANDBOX_ID_STATE_KEY, None)
            else:
                if sandbox.state in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}:
                    if self.sandbox_id:
                        raise RuntimeError(f"Tenki sandbox {sandbox.id} is in terminal state {sandbox.state}")
                    state.pop(SANDBOX_ID_STATE_KEY, None)
                else:
                    state[SANDBOX_ID_STATE_KEY] = sandbox.id
                    return self._prepare_sandbox(sandbox)
        if not self.auto_create_sandbox:
            raise RuntimeError("No Tenki sandbox is associated with this session and auto-creation is disabled")
        sandbox = self.client.create(**self.sandbox_options)
        state[SANDBOX_ID_STATE_KEY] = sandbox.id
        state[WORKING_DIRECTORY_STATE_KEY] = DEFAULT_WORKING_DIRECTORY
        return self._prepare_sandbox(sandbox)

    async def _aget_or_create_sandbox(self, run_context: RunContext) -> Any:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY)
        if sandbox_id:
            try:
                sandbox = await self.async_client.get(sandbox_id)
            except Exception as error:
                if self.sandbox_id or not self._is_missing_sandbox_error(error):
                    raise
                state.pop(SANDBOX_ID_STATE_KEY, None)
            else:
                if sandbox.state in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}:
                    if self.sandbox_id:
                        raise RuntimeError(f"Tenki sandbox {sandbox.id} is in terminal state {sandbox.state}")
                    state.pop(SANDBOX_ID_STATE_KEY, None)
                else:
                    state[SANDBOX_ID_STATE_KEY] = sandbox.id
                    return await self._aprepare_sandbox(sandbox)
        if not self.auto_create_sandbox:
            raise RuntimeError("No Tenki sandbox is associated with this session and auto-creation is disabled")
        sandbox = await self.async_client.create(**self.sandbox_options)
        state[SANDBOX_ID_STATE_KEY] = sandbox.id
        state[WORKING_DIRECTORY_STATE_KEY] = DEFAULT_WORKING_DIRECTORY
        return await self._aprepare_sandbox(sandbox)

    def _get_existing_sandbox(self, run_context: RunContext) -> Any:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY)
        if not sandbox_id:
            raise RuntimeError("No Tenki sandbox is associated with this session")
        try:
            return self.client.get(sandbox_id)
        except Exception as error:
            if not self.sandbox_id and self._is_missing_sandbox_error(error):
                state.pop(SANDBOX_ID_STATE_KEY, None)
                raise RuntimeError("No Tenki sandbox is associated with this session") from error
            raise

    async def _aget_existing_sandbox(self, run_context: RunContext) -> Any:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY)
        if not sandbox_id:
            raise RuntimeError("No Tenki sandbox is associated with this session")
        try:
            return await self.async_client.get(sandbox_id)
        except Exception as error:
            if not self.sandbox_id and self._is_missing_sandbox_error(error):
                state.pop(SANDBOX_ID_STATE_KEY, None)
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

    @staticmethod
    def _format_command_result(result: Any) -> str:
        return json.dumps(
            {
                "status": "success" if result.ok else "error",
                "exit_code": result.exit_code,
                "stdout": result.stdout_text,
                "stderr": result.stderr_text,
            }
        )

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

    @staticmethod
    def _format_sandbox_status(run_context: RunContext, sandbox: Any) -> str:
        return json.dumps(
            {
                "status": "success",
                "sandbox_id": sandbox.id,
                "name": sandbox.info.name,
                "state": sandbox.state,
                "working_directory": TenkiTools._session_state(run_context)[WORKING_DIRECTORY_STATE_KEY],
            }
        )

    def get_sandbox_status(self, run_context: RunContext) -> str:
        """Get the current Tenki sandbox status and working directory."""
        sandbox = self._get_or_create_sandbox(run_context)
        return self._format_sandbox_status(run_context, sandbox)

    async def aget_sandbox_status(self, run_context: RunContext) -> str:
        """Get the current Tenki sandbox status asynchronously."""
        sandbox = await self._aget_or_create_sandbox(run_context)
        return self._format_sandbox_status(run_context, sandbox)

    def terminate_sandbox(self, run_context: RunContext) -> str:
        """Terminate the current Tenki sandbox."""
        sandbox = self._get_existing_sandbox(run_context)
        if sandbox.state not in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}:
            sandbox.close()
        state = self._session_state(run_context)
        state.pop(SANDBOX_ID_STATE_KEY, None)
        if self.sandbox_id == sandbox.id:
            self.sandbox_id = None
        return json.dumps({"status": "success", "sandbox_id": sandbox.id, "state": sandbox.state})

    async def aterminate_sandbox(self, run_context: RunContext) -> str:
        """Terminate the current Tenki sandbox asynchronously."""
        sandbox = await self._aget_existing_sandbox(run_context)
        if sandbox.state not in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}:
            await sandbox.close()
        state = self._session_state(run_context)
        state.pop(SANDBOX_ID_STATE_KEY, None)
        if self.sandbox_id == sandbox.id:
            self.sandbox_id = None
        return json.dumps({"status": "success", "sandbox_id": sandbox.id, "state": sandbox.state})
