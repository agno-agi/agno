import json
import shlex
from os import getenv
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.team import Team
from agno.tools import Toolkit
from agno.utils.code_execution import prepare_python_code
from agno.utils.log import log_debug, log_info

try:
    from superserve import AsyncSandbox, Sandbox
except ImportError:
    raise ImportError("`superserve` not installed. Please install using `pip install superserve`")

DEFAULT_INSTRUCTIONS = dedent(
    """\
    You have access to a Superserve sandbox: an isolated cloud environment (Firecracker microVM) for running code.
    The sandbox persists across tool calls, so files you write and packages you install remain available.
    Available tools:
    - `run_python_code`: Execute Python code and return its output
    - `run_command`: Execute a shell command (bash)
    - `create_file`: Create or overwrite a file
    - `read_file`: Read a file's contents
    - `list_files`: List the contents of a directory
    - `delete_file`: Delete a file or directory
    - `download_directory`: Download a directory from the sandbox as a zip archive
    - `get_sandbox_info`: Inspect the current sandbox
    - `list_sandboxes`: List all sandboxes for the team
    - `shutdown_sandbox`: Delete the current sandbox
    When asked to run or verify code, write it, execute it with run_python_code or run_command, and show the real output.
    Install missing packages with run_command, for example `pip install <package>`.
    """
)

# Key under which the active sandbox id is stored in the agent's session state,
# so the same sandbox is reused across tool calls and across runs.
SESSION_STATE_SANDBOX_ID = "superserve_sandbox_id"


class SuperserveTools(Toolkit):
    """Run agent-generated code in an isolated Superserve sandbox.

    A focused set of code-execution and file tools is enabled by default. The
    sandbox lifecycle tools (pause/resume) and secret-binding tools are opt-in via
    their `enable_*` flags, or turn everything on with `all=True`. Every tool has
    both a sync and an async variant, so the toolkit works with `agent.run()` and
    `agent.arun()`.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        sandbox_id: Optional[str] = None,
        template: Optional[str] = None,
        timeout: int = 300,
        command_timeout: int = 60,
        metadata: Optional[Dict[str, str]] = None,
        env_vars: Optional[Dict[str, str]] = None,
        secrets: Optional[Dict[str, str]] = None,
        persistent: bool = True,
        enable_run_python_code: bool = True,
        enable_run_command: bool = True,
        enable_create_file: bool = True,
        enable_read_file: bool = True,
        enable_list_files: bool = True,
        enable_delete_file: bool = True,
        enable_download_directory: bool = True,
        enable_get_sandbox_info: bool = True,
        enable_list_sandboxes: bool = True,
        enable_shutdown_sandbox: bool = True,
        enable_pause_sandbox: bool = False,
        enable_resume_sandbox: bool = False,
        enable_attach_secret: bool = False,
        enable_detach_secret: bool = False,
        all: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        **kwargs: Any,
    ):
        """Initialize the Superserve toolkit.

        Args:
            api_key: Superserve API key (defaults to the SUPERSERVE_API_KEY env var).
            base_url: Override the control-plane base URL (defaults to SUPERSERVE_BASE_URL or the SDK default).
            sandbox_id: Connect to an existing sandbox instead of creating a new one.
            template: Template name to create the sandbox from.
            timeout: Sandbox lifetime in seconds before it is auto-stopped (default: 300).
            command_timeout: Per-command timeout in seconds (default: 60).
            metadata: Metadata to attach to created sandboxes.
            env_vars: Environment variables to set in created sandboxes.
            secrets: Team secrets to bind as {ENV_VAR: secret_name}. The sandbox sees a
                proxy token; the real credential never enters the sandbox.
            persistent: Persist the sandbox id in the agent's session state so the same
                sandbox is reused across runs (default: True).
            enable_run_python_code: Register the run_python_code tool (default: True).
            enable_run_command: Register the run_command tool (default: True).
            enable_create_file: Register the create_file tool (default: True).
            enable_read_file: Register the read_file tool (default: True).
            enable_list_files: Register the list_files tool (default: True).
            enable_delete_file: Register the delete_file tool (default: True).
            enable_download_directory: Register the download_directory tool (default: True).
            enable_get_sandbox_info: Register the get_sandbox_info tool (default: True).
            enable_list_sandboxes: Register the list_sandboxes tool (default: True).
            enable_shutdown_sandbox: Register the shutdown_sandbox tool (default: True).
            enable_pause_sandbox: Register the pause_sandbox tool (default: False).
            enable_resume_sandbox: Register the resume_sandbox tool (default: False).
            enable_attach_secret: Register the attach_secret tool (default: False).
            enable_detach_secret: Register the detach_secret tool (default: False).
            all: Register every tool, overriding the individual enable_* flags (default: False).
            instructions: Override the default toolkit instructions.
            add_instructions: Whether to add the instructions to the agent's system message.
        """
        self.api_key = api_key or getenv("SUPERSERVE_API_KEY")
        if not self.api_key:
            raise ValueError("SUPERSERVE_API_KEY not set. Please set the SUPERSERVE_API_KEY environment variable.")

        self.base_url = base_url or getenv("SUPERSERVE_BASE_URL")
        self.sandbox_id = sandbox_id
        self.template = template
        self.timeout = timeout
        self.command_timeout = command_timeout
        self.metadata = metadata
        self.env_vars = env_vars
        self.secrets = secrets
        self.persistent = persistent

        # Lazily-created clients. Both resolve to the same sandbox VM via a shared
        # id, so sync and async tools operate on the same environment.
        self._sandbox: Optional[Sandbox] = None
        self._async_sandbox: Optional[AsyncSandbox] = None

        self.instructions = instructions or DEFAULT_INSTRUCTIONS

        tools: List[Any] = []
        async_tools: List[Any] = []
        if all or enable_run_python_code:
            tools.append(self.run_python_code)
            async_tools.append((self.arun_python_code, "run_python_code"))
        if all or enable_run_command:
            tools.append(self.run_command)
            async_tools.append((self.arun_command, "run_command"))
        if all or enable_create_file:
            tools.append(self.create_file)
            async_tools.append((self.acreate_file, "create_file"))
        if all or enable_read_file:
            tools.append(self.read_file)
            async_tools.append((self.aread_file, "read_file"))
        if all or enable_list_files:
            tools.append(self.list_files)
            async_tools.append((self.alist_files, "list_files"))
        if all or enable_delete_file:
            tools.append(self.delete_file)
            async_tools.append((self.adelete_file, "delete_file"))
        if all or enable_download_directory:
            tools.append(self.download_directory)
            async_tools.append((self.adownload_directory, "download_directory"))
        if all or enable_get_sandbox_info:
            tools.append(self.get_sandbox_info)
            async_tools.append((self.aget_sandbox_info, "get_sandbox_info"))
        if all or enable_list_sandboxes:
            tools.append(self.list_sandboxes)
            async_tools.append((self.alist_sandboxes, "list_sandboxes"))
        if all or enable_shutdown_sandbox:
            tools.append(self.shutdown_sandbox)
            async_tools.append((self.ashutdown_sandbox, "shutdown_sandbox"))
        if all or enable_pause_sandbox:
            tools.append(self.pause_sandbox)
            async_tools.append((self.apause_sandbox, "pause_sandbox"))
        if all or enable_resume_sandbox:
            tools.append(self.resume_sandbox)
            async_tools.append((self.aresume_sandbox, "resume_sandbox"))
        if all or enable_attach_secret:
            tools.append(self.attach_secret)
            async_tools.append((self.aattach_secret, "attach_secret"))
        if all or enable_detach_secret:
            tools.append(self.detach_secret)
            async_tools.append((self.adetach_secret, "detach_secret"))

        super().__init__(
            name="superserve_tools",
            tools=tools,
            async_tools=async_tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Sandbox lifecycle helpers
    # ------------------------------------------------------------------
    def _generate_name(self) -> str:
        return f"agno-{uuid4().hex[:8]}"

    def _resolve_sandbox_id(self, agent: Optional[Union[Agent, Team]]) -> Optional[str]:
        """Resolve the sandbox id to reuse: explicit id, else session state."""
        if self.sandbox_id:
            return self.sandbox_id
        if self.persistent and agent is not None and hasattr(agent, "session_state"):
            if agent.session_state is None:
                agent.session_state = {}
            stored = agent.session_state.get(SESSION_STATE_SANDBOX_ID)
            return stored if isinstance(stored, str) else None
        return None

    def _store_sandbox_id(self, agent: Optional[Union[Agent, Team]], sandbox_id: str) -> None:
        if self.persistent and agent is not None and hasattr(agent, "session_state"):
            if agent.session_state is None:
                agent.session_state = {}
            agent.session_state[SESSION_STATE_SANDBOX_ID] = sandbox_id

    def _clear_sandbox_id(self, agent: Optional[Union[Agent, Team]]) -> None:
        if agent is not None and hasattr(agent, "session_state") and agent.session_state:
            agent.session_state.pop(SESSION_STATE_SANDBOX_ID, None)

    def _get_sandbox(self, agent: Optional[Union[Agent, Team]]) -> Sandbox:
        """Get the cached sync sandbox, connecting to or creating one as needed."""
        sandbox_id = self._resolve_sandbox_id(agent)
        if self._sandbox is not None and (sandbox_id is None or self._sandbox.id == sandbox_id):
            return self._sandbox

        if sandbox_id:
            log_debug(f"Connecting to Superserve sandbox: {sandbox_id}")
            self._sandbox = Sandbox.connect(sandbox_id, api_key=self.api_key, base_url=self.base_url)
        else:
            self._sandbox = Sandbox.create(
                name=self._generate_name(),
                from_template=self.template,
                timeout_seconds=self.timeout,
                metadata=self.metadata,
                env_vars=self.env_vars,
                secrets=self.secrets,
                api_key=self.api_key,
                base_url=self.base_url,
            )
            self._store_sandbox_id(agent, self._sandbox.id)
            log_info(f"Created Superserve sandbox: {self._sandbox.id}")
        return self._sandbox

    async def _aget_sandbox(self, agent: Optional[Union[Agent, Team]]) -> AsyncSandbox:
        """Async variant of _get_sandbox."""
        sandbox_id = self._resolve_sandbox_id(agent)
        if self._async_sandbox is not None and (sandbox_id is None or self._async_sandbox.id == sandbox_id):
            return self._async_sandbox

        if sandbox_id:
            log_debug(f"Connecting to Superserve sandbox: {sandbox_id}")
            self._async_sandbox = await AsyncSandbox.connect(sandbox_id, api_key=self.api_key, base_url=self.base_url)
        else:
            self._async_sandbox = await AsyncSandbox.create(
                name=self._generate_name(),
                from_template=self.template,
                timeout_seconds=self.timeout,
                metadata=self.metadata,
                env_vars=self.env_vars,
                secrets=self.secrets,
                api_key=self.api_key,
                base_url=self.base_url,
            )
            self._store_sandbox_id(agent, self._async_sandbox.id)
            log_info(f"Created Superserve sandbox: {self._async_sandbox.id}")
        return self._async_sandbox

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _error(message: str, error: Union[str, Exception]) -> str:
        return json.dumps({"status": "error", "message": f"{message}: {str(error)}"})

    @staticmethod
    def _format_result(stdout: str, stderr: str, exit_code: int) -> str:
        parts: List[str] = []
        if stdout:
            parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            parts.append(f"STDERR:\n{stderr}")
        parts.append(f"Exit code: {exit_code}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Core tools (sync)
    # ------------------------------------------------------------------
    def run_python_code(self, agent: Union[Agent, Team], code: str) -> str:
        """Execute Python code in the sandbox and return its output.

        Args:
            code: Python code to execute.

        Returns:
            The command output (stdout, stderr, exit code) or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            path = f"/tmp/agno_run_{uuid4().hex[:8]}.py"
            sandbox.files.write(path, prepare_python_code(code))
            result = sandbox.commands.run(f"python3 {shlex.quote(path)}", timeout_seconds=self.command_timeout)
            return self._format_result(result.stdout, result.stderr, result.exit_code)
        except Exception as e:
            return self._error("Error executing code", e)

    def run_command(self, agent: Union[Agent, Team], command: str) -> str:
        """Execute a shell command in the sandbox.

        Args:
            command: Shell command to execute.

        Returns:
            The command output (stdout, stderr, exit code) or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            result = sandbox.commands.run(command, timeout_seconds=self.command_timeout)
            return self._format_result(result.stdout, result.stderr, result.exit_code)
        except Exception as e:
            return self._error("Error executing command", e)

    def create_file(self, agent: Union[Agent, Team], file_path: str, content: str) -> str:
        """Create or overwrite a file in the sandbox.

        Args:
            file_path: Absolute path to the file in the sandbox.
            content: Text content to write.

        Returns:
            A success message or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            sandbox.files.write(file_path, content)
            return f"File written: {file_path}"
        except Exception as e:
            return self._error("Error creating file", e)

    def read_file(self, agent: Union[Agent, Team], file_path: str) -> str:
        """Read a file's contents from the sandbox.

        Args:
            file_path: Absolute path to the file in the sandbox.

        Returns:
            The file contents as text or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            return sandbox.files.read_text(file_path)
        except Exception as e:
            return self._error("Error reading file", e)

    def list_files(self, agent: Union[Agent, Team], directory: str = "/") -> str:
        """List the contents of a directory in the sandbox.

        Args:
            directory: Directory to list (default: root).

        Returns:
            The directory listing or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            result = sandbox.commands.run(f"ls -la {shlex.quote(directory)}")
            if result.exit_code != 0:
                return self._error(f"Error listing {directory}", result.stderr or "non-zero exit code")
            return f"Contents of {directory}:\n{result.stdout}"
        except Exception as e:
            return self._error("Error listing files", e)

    def delete_file(self, agent: Union[Agent, Team], file_path: str) -> str:
        """Delete a file or directory in the sandbox.

        Args:
            file_path: Absolute path to the file or directory in the sandbox.

        Returns:
            A success message or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            result = sandbox.commands.run(f"rm -rf {shlex.quote(file_path)}")
            if result.exit_code != 0:
                return self._error(f"Error deleting {file_path}", result.stderr or "non-zero exit code")
            return f"Deleted: {file_path}"
        except Exception as e:
            return self._error("Error deleting file", e)

    def download_directory(self, agent: Union[Agent, Team], sandbox_path: str, local_path: str) -> str:
        """Download a directory from the sandbox as a zip archive saved locally.

        Args:
            sandbox_path: Directory path in the sandbox to download.
            local_path: Local path to write the zip archive to (e.g. "out.zip").

        Returns:
            The local path written or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            data = sandbox.files.download_dir(sandbox_path, timeout=self.command_timeout)
            with open(local_path, "wb") as f:
                f.write(data)
            return f"Downloaded {sandbox_path} to {local_path}"
        except Exception as e:
            return self._error("Error downloading directory", e)

    def get_sandbox_info(self, agent: Union[Agent, Team]) -> str:
        """Get information about the current sandbox.

        Returns:
            JSON with the sandbox id, name, status, and metadata, or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            info = sandbox.get_info()
            return json.dumps(
                {"id": info.id, "name": info.name, "status": info.status.value, "metadata": info.metadata}
            )
        except Exception as e:
            return self._error("Error getting sandbox info", e)

    def list_sandboxes(self) -> str:
        """List all sandboxes belonging to the team.

        Returns:
            JSON list of sandboxes (id, name, status) or an error message.
        """
        try:
            sandboxes = Sandbox.list(api_key=self.api_key, base_url=self.base_url)
            return json.dumps([{"id": s.id, "name": s.name, "status": s.status.value} for s in sandboxes])
        except Exception as e:
            return self._error("Error listing sandboxes", e)

    def shutdown_sandbox(self, agent: Union[Agent, Team]) -> str:
        """Delete the current sandbox and release its resources.

        Returns:
            A success message or an error message.
        """
        try:
            if self._sandbox is None and not self._resolve_sandbox_id(agent):
                return "No active sandbox to shut down."
            sandbox = self._get_sandbox(agent)
            sandbox_id = sandbox.id
            sandbox.kill()
            self._sandbox = None
            self._async_sandbox = None
            self._clear_sandbox_id(agent)
            return f"Sandbox {sandbox_id} shut down."
        except Exception as e:
            return self._error("Error shutting down sandbox", e)

    # ------------------------------------------------------------------
    # Lifecycle tools (opt-in)
    # ------------------------------------------------------------------
    def pause_sandbox(self, agent: Union[Agent, Team]) -> str:
        """Pause the current sandbox to save resources. It can be resumed later.

        Returns:
            A success message or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            sandbox.pause()
            return f"Sandbox {sandbox.id} paused."
        except Exception as e:
            return self._error("Error pausing sandbox", e)

    def resume_sandbox(self, agent: Union[Agent, Team]) -> str:
        """Resume the current paused sandbox.

        Returns:
            A success message or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            sandbox.resume()
            return f"Sandbox {sandbox.id} resumed."
        except Exception as e:
            return self._error("Error resuming sandbox", e)

    # ------------------------------------------------------------------
    # Secret tools (opt-in)
    # ------------------------------------------------------------------
    def attach_secret(self, agent: Union[Agent, Team], env_key: str, secret_name: str) -> str:
        """Bind a team secret to the sandbox under an environment variable.

        The sandbox sees a proxy token; the real credential is swapped in only for
        outbound requests to the secret's allowed hosts.

        Args:
            env_key: Environment variable name the sandbox will see.
            secret_name: Name of the team secret to bind.

        Returns:
            A success message or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            sandbox.attach_secret(env_key, secret_name)
            return f"Secret '{secret_name}' attached as {env_key}."
        except Exception as e:
            return self._error("Error attaching secret", e)

    def detach_secret(self, agent: Union[Agent, Team], env_key: str) -> str:
        """Remove a secret binding from the sandbox by its environment variable key.

        Args:
            env_key: Environment variable name of the binding to remove.

        Returns:
            A success message or an error message.
        """
        try:
            sandbox = self._get_sandbox(agent)
            sandbox.detach_secret(env_key)
            return f"Secret binding {env_key} removed."
        except Exception as e:
            return self._error("Error detaching secret", e)

    # ------------------------------------------------------------------
    # Core tools (async)
    # ------------------------------------------------------------------
    async def arun_python_code(self, agent: Union[Agent, Team], code: str) -> str:
        """Async variant of run_python_code."""
        try:
            sandbox = await self._aget_sandbox(agent)
            path = f"/tmp/agno_run_{uuid4().hex[:8]}.py"
            await sandbox.files.write(path, prepare_python_code(code))
            result = await sandbox.commands.run(f"python3 {shlex.quote(path)}", timeout_seconds=self.command_timeout)
            return self._format_result(result.stdout, result.stderr, result.exit_code)
        except Exception as e:
            return self._error("Error executing code", e)

    async def arun_command(self, agent: Union[Agent, Team], command: str) -> str:
        """Async variant of run_command."""
        try:
            sandbox = await self._aget_sandbox(agent)
            result = await sandbox.commands.run(command, timeout_seconds=self.command_timeout)
            return self._format_result(result.stdout, result.stderr, result.exit_code)
        except Exception as e:
            return self._error("Error executing command", e)

    async def acreate_file(self, agent: Union[Agent, Team], file_path: str, content: str) -> str:
        """Async variant of create_file."""
        try:
            sandbox = await self._aget_sandbox(agent)
            await sandbox.files.write(file_path, content)
            return f"File written: {file_path}"
        except Exception as e:
            return self._error("Error creating file", e)

    async def aread_file(self, agent: Union[Agent, Team], file_path: str) -> str:
        """Async variant of read_file."""
        try:
            sandbox = await self._aget_sandbox(agent)
            return await sandbox.files.read_text(file_path)
        except Exception as e:
            return self._error("Error reading file", e)

    async def alist_files(self, agent: Union[Agent, Team], directory: str = "/") -> str:
        """Async variant of list_files."""
        try:
            sandbox = await self._aget_sandbox(agent)
            result = await sandbox.commands.run(f"ls -la {shlex.quote(directory)}")
            if result.exit_code != 0:
                return self._error(f"Error listing {directory}", result.stderr or "non-zero exit code")
            return f"Contents of {directory}:\n{result.stdout}"
        except Exception as e:
            return self._error("Error listing files", e)

    async def adelete_file(self, agent: Union[Agent, Team], file_path: str) -> str:
        """Async variant of delete_file."""
        try:
            sandbox = await self._aget_sandbox(agent)
            result = await sandbox.commands.run(f"rm -rf {shlex.quote(file_path)}")
            if result.exit_code != 0:
                return self._error(f"Error deleting {file_path}", result.stderr or "non-zero exit code")
            return f"Deleted: {file_path}"
        except Exception as e:
            return self._error("Error deleting file", e)

    async def adownload_directory(self, agent: Union[Agent, Team], sandbox_path: str, local_path: str) -> str:
        """Async variant of download_directory."""
        try:
            sandbox = await self._aget_sandbox(agent)
            data = await sandbox.files.download_dir(sandbox_path, timeout=self.command_timeout)
            with open(local_path, "wb") as f:
                f.write(data)
            return f"Downloaded {sandbox_path} to {local_path}"
        except Exception as e:
            return self._error("Error downloading directory", e)

    async def aget_sandbox_info(self, agent: Union[Agent, Team]) -> str:
        """Async variant of get_sandbox_info."""
        try:
            sandbox = await self._aget_sandbox(agent)
            info = await sandbox.get_info()
            return json.dumps(
                {"id": info.id, "name": info.name, "status": info.status.value, "metadata": info.metadata}
            )
        except Exception as e:
            return self._error("Error getting sandbox info", e)

    async def alist_sandboxes(self) -> str:
        """Async variant of list_sandboxes."""
        try:
            sandboxes = await AsyncSandbox.list(api_key=self.api_key, base_url=self.base_url)
            return json.dumps([{"id": s.id, "name": s.name, "status": s.status.value} for s in sandboxes])
        except Exception as e:
            return self._error("Error listing sandboxes", e)

    async def ashutdown_sandbox(self, agent: Union[Agent, Team]) -> str:
        """Async variant of shutdown_sandbox."""
        try:
            if self._async_sandbox is None and not self._resolve_sandbox_id(agent):
                return "No active sandbox to shut down."
            sandbox = await self._aget_sandbox(agent)
            sandbox_id = sandbox.id
            await sandbox.kill()
            self._sandbox = None
            self._async_sandbox = None
            self._clear_sandbox_id(agent)
            return f"Sandbox {sandbox_id} shut down."
        except Exception as e:
            return self._error("Error shutting down sandbox", e)

    # ------------------------------------------------------------------
    # Lifecycle tools (async, opt-in)
    # ------------------------------------------------------------------
    async def apause_sandbox(self, agent: Union[Agent, Team]) -> str:
        """Async variant of pause_sandbox."""
        try:
            sandbox = await self._aget_sandbox(agent)
            await sandbox.pause()
            return f"Sandbox {sandbox.id} paused."
        except Exception as e:
            return self._error("Error pausing sandbox", e)

    async def aresume_sandbox(self, agent: Union[Agent, Team]) -> str:
        """Async variant of resume_sandbox."""
        try:
            sandbox = await self._aget_sandbox(agent)
            await sandbox.resume()
            return f"Sandbox {sandbox.id} resumed."
        except Exception as e:
            return self._error("Error resuming sandbox", e)

    # ------------------------------------------------------------------
    # Secret tools (async, opt-in)
    # ------------------------------------------------------------------
    async def aattach_secret(self, agent: Union[Agent, Team], env_key: str, secret_name: str) -> str:
        """Async variant of attach_secret."""
        try:
            sandbox = await self._aget_sandbox(agent)
            await sandbox.attach_secret(env_key, secret_name)
            return f"Secret '{secret_name}' attached as {env_key}."
        except Exception as e:
            return self._error("Error attaching secret", e)

    async def adetach_secret(self, agent: Union[Agent, Team], env_key: str) -> str:
        """Async variant of detach_secret."""
        try:
            sandbox = await self._aget_sandbox(agent)
            await sandbox.detach_secret(env_key)
            return f"Secret binding {env_key} removed."
        except Exception as e:
            return self._error("Error detaching secret", e)
