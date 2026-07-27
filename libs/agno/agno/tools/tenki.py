import asyncio
import base64
import hashlib
import json
import posixpath
from os import getenv
from textwrap import dedent
from threading import Lock
from time import sleep
from typing import Any, Callable, Dict, Optional
from uuid import uuid4
from weakref import WeakKeyDictionary

from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.code_execution import prepare_python_code
from agno.utils.log import log_warning

DEFAULT_WORKING_DIRECTORY = "/home/tenki"
DEFAULT_MAX_OUTPUT_CHARS = 20_000
DEFAULT_SANDBOX_MAX_DURATION = 900
CLAIM_RECONCILIATION_DELAYS = (0.0, 0.05, 0.1, 0.2)
COMMAND_TERMINATION_GRACE_SECONDS = 2
CREATION_LOCK_STRIPES = 64
MAX_UTF8_BYTES_PER_CHAR = 4
READ_STREAM_CHUNK_BYTES = 64 * 1024
SANDBOX_ID_STATE_KEY = "tenki_sandbox_id"
SANDBOX_OWNED_STATE_KEY = "tenki_sandbox_owned"
WORKING_DIRECTORY_STATE_KEY = "tenki_working_directory"

BOUNDED_COMMAND_RUNNER = """\
import base64
import json
import os
import signal
import subprocess
import sys
import threading
import time

mode, command_path, cwd, raw_limit, raw_timeout, raw_termination_grace = sys.argv[1:]
limit = int(raw_limit)
timeout = float(raw_timeout)
termination_grace = float(raw_termination_grace)
argv = (
    ["python3", command_path]
    if mode == "python"
    else ["bash", "-lc", 'command_path=$1; set --; source "$command_path"', "bash", command_path]
)
env = os.environ.copy()
env["PYTHONPATH"] = os.pathsep.join(part for part in (cwd, env.get("PYTHONPATH")) if part)
process = subprocess.Popen(
    argv,
    cwd=cwd,
    env=env,
    start_new_session=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
streams = (process.stdout, process.stderr)
buffers = (bytearray(), bytearray())
totals = [0, 0]

def drain(index):
    stream = streams[index]
    while True:
        chunk = stream.read(65536)
        if not chunk:
            return
        totals[index] += len(chunk)
        if limit < 0:
            buffers[index].extend(chunk)
        elif len(buffers[index]) < limit:
            buffers[index].extend(chunk[: limit - len(buffers[index])])

threads = [threading.Thread(target=drain, args=(index,)) for index in range(2)]
for thread in threads:
    thread.start()
deadline = time.monotonic() + timeout
timed_out = False

def terminate_process_group():
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=termination_grace)
        except subprocess.TimeoutExpired:
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        process.wait()

try:
    exit_code = process.wait(timeout=timeout)
except subprocess.TimeoutExpired:
    timed_out = True
    terminate_process_group()
    exit_code = 124
if not timed_out:
    for thread in threads:
        thread.join(timeout=max(0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        timed_out = True
        terminate_process_group()
        exit_code = 124
for thread in threads:
    thread.join()

print(
    json.dumps(
        {
            "exit_code": exit_code,
            "stdout": base64.b64encode(buffers[0]).decode("ascii"),
            "stderr": base64.b64encode(buffers[1]).decode("ascii"),
            "stdout_bytes": totals[0],
            "stderr_bytes": totals[1],
            "timed_out": timed_out,
        }
    )
)
"""

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
        enable_run_code: bool = True,
        enable_run_shell_command: bool = True,
        enable_create_file: bool = True,
        enable_read_file: bool = True,
        enable_list_files: bool = True,
        enable_delete_file: bool = True,
        enable_change_directory: bool = True,
        enable_get_sandbox_status: bool = True,
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
        if command_timeout <= 0:
            raise ValueError("command_timeout must be greater than zero")
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
        self._creation_locks = tuple(Lock() for _ in range(CREATION_LOCK_STRIPES))
        self._async_creation_locks_by_loop: WeakKeyDictionary[Any, tuple[asyncio.Lock, ...]] = WeakKeyDictionary()
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
        if auto_create_sandbox and sandbox_id is None and self.sandbox_options.get("max_duration") is None:
            raise ValueError(
                "Auto-created Tenki sandboxes require a bounded max duration; set sandbox_max_duration or "
                "sandbox_options['max_duration']"
            )
        self.instructions = instructions or DEFAULT_INSTRUCTIONS

        tools: list[Callable[..., Any]] = []
        async_tools: list[tuple[Callable[..., Any], str]] = []
        if enable_run_code:
            tools.append(self.run_code)
            async_tools.append((self.arun_code, "run_code"))
        if enable_run_shell_command:
            tools.append(self.run_shell_command)
            async_tools.append((self.arun_shell_command, "run_shell_command"))
        if enable_create_file:
            tools.append(self.create_file)
            async_tools.append((self.acreate_file, "create_file"))
        if enable_read_file:
            tools.append(self.read_file)
            async_tools.append((self.aread_file, "read_file"))
        if enable_list_files:
            tools.append(self.list_files)
            async_tools.append((self.alist_files, "list_files"))
        if enable_delete_file:
            tools.append(self.delete_file)
            async_tools.append((self.adelete_file, "delete_file"))
        if enable_change_directory:
            tools.append(self.change_directory)
            async_tools.append((self.achange_directory, "change_directory"))
        if enable_get_sandbox_status:
            tools.append(self.get_sandbox_status)
            async_tools.append((self.aget_sandbox_status, "get_sandbox_status"))
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

    def _creation_lock(self, run_context: RunContext) -> Any:
        return self._creation_locks[hash(self._session_key(run_context)) % CREATION_LOCK_STRIPES]

    def _async_creation_lock(self, run_context: RunContext) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        with self._creation_locks_guard:
            locks = self._async_creation_locks_by_loop.get(loop)
            if locks is None:
                locks = tuple(asyncio.Lock() for _ in range(CREATION_LOCK_STRIPES))
                self._async_creation_locks_by_loop[loop] = locks
        return locks[hash(self._session_key(run_context)) % CREATION_LOCK_STRIPES]

    @staticmethod
    def _clear_sandbox_state(state: Dict[str, Any], expected_sandbox_id: Optional[str] = None) -> None:
        if expected_sandbox_id is not None and state.get(SANDBOX_ID_STATE_KEY) != expected_sandbox_id:
            return
        state.pop(SANDBOX_ID_STATE_KEY, None)
        state.pop(SANDBOX_OWNED_STATE_KEY, None)

    def _claim_tag(self, run_context: RunContext) -> str:
        user_id, session_id = self._session_key(run_context)
        digest = hashlib.sha256(f"{user_id or ''}\0{session_id}".encode()).hexdigest()[:19]
        return f"agno-session:{digest}"

    def _create_options(self, run_context: RunContext) -> Dict[str, Any]:
        options = dict(self.sandbox_options)
        tags = list(options.get("tags") or [])
        claim_tag = self._claim_tag(run_context)
        if claim_tag not in tags:
            tags.append(claim_tag)
        options["tags"] = tags
        options["wait"] = False
        return options

    def _claimed_sandboxes(self, run_context: RunContext) -> list[Any]:
        list_options: Dict[str, Any] = {"tags": [self._claim_tag(run_context)]}
        workspace_id = self.sandbox_options.get("workspace_id")
        if workspace_id:
            list_options["workspace_id"] = workspace_id
        return [
            sandbox
            for sandbox in self.client.list(**list_options)
            if sandbox.state not in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}
        ]

    async def _aclaimed_sandboxes(self, run_context: RunContext) -> list[Any]:
        list_options: Dict[str, Any] = {"tags": [self._claim_tag(run_context)]}
        workspace_id = self.sandbox_options.get("workspace_id")
        if workspace_id:
            list_options["workspace_id"] = workspace_id
        return [
            sandbox
            for sandbox in await self.async_client.list(**list_options)
            if sandbox.state not in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}
        ]

    def _find_claimed_sandbox(self, run_context: RunContext) -> Optional[Any]:
        sandboxes = self._claimed_sandboxes(run_context)
        return min(sandboxes, key=lambda sandbox: sandbox.id) if sandboxes else None

    async def _afind_claimed_sandbox(self, run_context: RunContext) -> Optional[Any]:
        sandboxes = await self._aclaimed_sandboxes(run_context)
        return min(sandboxes, key=lambda sandbox: sandbox.id) if sandboxes else None

    def _reconcile_created_sandbox(self, run_context: RunContext, created_sandbox: Any) -> Any:
        """Best-effort reconciliation after the created row reaches a read replica.

        Tenki's list endpoint may be replica-backed, so a missing created row means the
        result is too stale to arbitrate safely. Auto-created sandboxes always retain a
        bounded lifetime as the cleanup backstop when reconciliation is inconclusive.
        """
        last_error: Optional[Exception] = None
        for delay in CLAIM_RECONCILIATION_DELAYS:
            if delay:
                sleep(delay)
            try:
                sandboxes = self._claimed_sandboxes(run_context)
            except Exception as error:
                last_error = error
                continue
            if any(sandbox.id == created_sandbox.id for sandbox in sandboxes):
                return min(sandboxes, key=lambda sandbox: sandbox.id)

        if last_error is not None:
            log_warning(
                f"Could not reconcile Tenki sandbox claim after creating {created_sandbox.id}; "
                f"continuing with the created sandbox: {last_error}"
            )
        else:
            log_warning(
                f"Tenki sandbox {created_sandbox.id} was not visible during claim reconciliation; "
                "continuing with the created sandbox"
            )
        return created_sandbox

    async def _areconcile_created_sandbox(self, run_context: RunContext, created_sandbox: Any) -> Any:
        """Asynchronously reconcile a claim after the created row becomes visible."""
        last_error: Optional[Exception] = None
        for delay in CLAIM_RECONCILIATION_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            try:
                sandboxes = await self._aclaimed_sandboxes(run_context)
            except Exception as error:
                last_error = error
                continue
            if any(sandbox.id == created_sandbox.id for sandbox in sandboxes):
                return min(sandboxes, key=lambda sandbox: sandbox.id)

        if last_error is not None:
            log_warning(
                f"Could not reconcile Tenki sandbox claim after creating {created_sandbox.id}; "
                f"continuing with the created sandbox: {last_error}"
            )
        else:
            log_warning(
                f"Tenki sandbox {created_sandbox.id} was not visible during claim reconciliation; "
                "continuing with the created sandbox"
            )
        return created_sandbox

    @staticmethod
    def _record_sandbox(state: Dict[str, Any], sandbox_id: str, *, owned: bool) -> None:
        state[SANDBOX_ID_STATE_KEY] = sandbox_id
        state[SANDBOX_OWNED_STATE_KEY] = owned

    def _get_reusable_sandbox(self, run_context: RunContext) -> Optional[Any]:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY)
        if sandbox_id:
            try:
                sandbox = self.client.get(sandbox_id)
            except Exception as error:
                if self.sandbox_id or not self._is_missing_sandbox_error(error):
                    raise
                self._clear_sandbox_state(state, sandbox_id)
                sandbox = self._find_claimed_sandbox(run_context)
                if sandbox is None:
                    return None
        else:
            sandbox = self._find_claimed_sandbox(run_context)
            if sandbox is None:
                return None
        if sandbox.state in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}:
            if self.sandbox_id:
                raise RuntimeError(f"Tenki sandbox {sandbox.id} is in terminal state {sandbox.state}")
            self._clear_sandbox_state(state, sandbox.id)
            return None
        owned = self.sandbox_id is None and state.get(SANDBOX_OWNED_STATE_KEY, True)
        self._record_sandbox(state, sandbox.id, owned=owned)
        try:
            return self._prepare_sandbox(sandbox)
        except Exception as error:
            if not owned or getattr(error, "retryable", False):
                raise
            try:
                sandbox.close()
            except Exception as cleanup_error:
                log_warning(f"Could not terminate unready Tenki sandbox {sandbox.id}: {cleanup_error}")
            finally:
                self._clear_sandbox_state(state, sandbox.id)
            return None

    async def _aget_reusable_sandbox(self, run_context: RunContext) -> Optional[Any]:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY)
        if sandbox_id:
            try:
                sandbox = await self.async_client.get(sandbox_id)
            except Exception as error:
                if self.sandbox_id or not self._is_missing_sandbox_error(error):
                    raise
                self._clear_sandbox_state(state, sandbox_id)
                sandbox = await self._afind_claimed_sandbox(run_context)
                if sandbox is None:
                    return None
        else:
            sandbox = await self._afind_claimed_sandbox(run_context)
            if sandbox is None:
                return None
        if sandbox.state in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}:
            if self.sandbox_id:
                raise RuntimeError(f"Tenki sandbox {sandbox.id} is in terminal state {sandbox.state}")
            self._clear_sandbox_state(state, sandbox.id)
            return None
        owned = self.sandbox_id is None and state.get(SANDBOX_OWNED_STATE_KEY, True)
        self._record_sandbox(state, sandbox.id, owned=owned)
        try:
            return await self._aprepare_sandbox(sandbox)
        except Exception as error:
            if not owned or getattr(error, "retryable", False):
                raise
            try:
                await sandbox.close()
            except Exception as cleanup_error:
                log_warning(f"Could not terminate unready Tenki sandbox {sandbox.id}: {cleanup_error}")
            finally:
                self._clear_sandbox_state(state, sandbox.id)
            return None

    def _get_or_create_sandbox(self, run_context: RunContext) -> Any:
        sandbox = self._get_reusable_sandbox(run_context)
        if sandbox is not None:
            return sandbox
        if not self.auto_create_sandbox:
            raise RuntimeError("No Tenki sandbox is associated with this session and auto-creation is disabled")

        with self._creation_lock(run_context):
            sandbox = self._get_reusable_sandbox(run_context)
            if sandbox is not None:
                return sandbox
            sandbox = self.client.create(**self._create_options(run_context))
            state = self._session_state(run_context)
            self._record_sandbox(state, sandbox.id, owned=True)
            state[WORKING_DIRECTORY_STATE_KEY] = DEFAULT_WORKING_DIRECTORY
            try:
                sandbox = self._prepare_sandbox(sandbox)
            except Exception:
                if state.get(SANDBOX_ID_STATE_KEY) == sandbox.id:
                    try:
                        sandbox.close()
                    except Exception as cleanup_error:
                        log_warning(f"Could not terminate unready Tenki sandbox {sandbox.id}: {cleanup_error}")
                    finally:
                        self._clear_sandbox_state(state, sandbox.id)
                raise
            winner = self._reconcile_created_sandbox(run_context, sandbox)
            if winner.id != sandbox.id:
                self._record_sandbox(state, winner.id, owned=True)
                try:
                    sandbox.close()
                except Exception as cleanup_error:
                    log_warning(f"Could not terminate duplicate Tenki sandbox {sandbox.id}: {cleanup_error}")
                return self._prepare_sandbox(winner)
            return sandbox

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
            sandbox = await self.async_client.create(**self._create_options(run_context))
            state = self._session_state(run_context)
            self._record_sandbox(state, sandbox.id, owned=True)
            state[WORKING_DIRECTORY_STATE_KEY] = DEFAULT_WORKING_DIRECTORY
            try:
                sandbox = await self._aprepare_sandbox(sandbox)
            except Exception:
                if state.get(SANDBOX_ID_STATE_KEY) == sandbox.id:
                    try:
                        await sandbox.close()
                    except Exception as cleanup_error:
                        log_warning(f"Could not terminate unready Tenki sandbox {sandbox.id}: {cleanup_error}")
                    finally:
                        self._clear_sandbox_state(state, sandbox.id)
                raise
            winner = await self._areconcile_created_sandbox(run_context, sandbox)
            if winner.id != sandbox.id:
                self._record_sandbox(state, winner.id, owned=True)
                try:
                    await sandbox.close()
                except Exception as cleanup_error:
                    log_warning(f"Could not terminate duplicate Tenki sandbox {sandbox.id}: {cleanup_error}")
                return await self._aprepare_sandbox(winner)
            return sandbox

    def _get_existing_sandbox(self, run_context: RunContext) -> Any:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY)
        if not sandbox_id and not self.sandbox_id:
            sandbox = self._find_claimed_sandbox(run_context)
            if sandbox is not None:
                self._record_sandbox(state, sandbox.id, owned=True)
                return sandbox
        if not sandbox_id:
            raise RuntimeError("No Tenki sandbox is associated with this session")
        try:
            return self.client.get(sandbox_id)
        except Exception as error:
            if not self.sandbox_id and self._is_missing_sandbox_error(error):
                self._clear_sandbox_state(state, sandbox_id)
                raise RuntimeError("No Tenki sandbox is associated with this session") from error
            raise

    async def _aget_existing_sandbox(self, run_context: RunContext) -> Any:
        state = self._session_state(run_context)
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY)
        if not sandbox_id and not self.sandbox_id:
            sandbox = await self._afind_claimed_sandbox(run_context)
            if sandbox is not None:
                self._record_sandbox(state, sandbox.id, owned=True)
                return sandbox
        if not sandbox_id:
            raise RuntimeError("No Tenki sandbox is associated with this session")
        try:
            return await self.async_client.get(sandbox_id)
        except Exception as error:
            if not self.sandbox_id and self._is_missing_sandbox_error(error):
                self._clear_sandbox_state(state, sandbox_id)
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
        # Avoid importing the optional Tenki dependency when clients are injected in tests.
        return error.__class__.__name__ == "SessionNotFoundError"

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

    def _decode_bounded_output(
        self,
        data: bytes,
        total_bytes: Optional[int],
        label: str = "Output",
        *,
        was_truncated: bool = False,
    ) -> tuple[str, bool]:
        text = data.decode("utf-8", errors="replace")
        if self.max_output_chars is None:
            return text, False
        truncated = (
            was_truncated or (total_bytes is not None and total_bytes > len(data)) or len(text) > self.max_output_chars
        )
        if not truncated:
            return text, False
        original_size = f"; original size: {total_bytes} bytes" if total_bytes is not None else ""
        return (
            f"{text[: self.max_output_chars]}\n"
            f"[{label} truncated after {self.max_output_chars} characters{original_size}.]",
            True,
        )

    def _format_collected_command_result(self, collected: Dict[str, Any]) -> str:
        stdout_bytes = base64.b64decode(collected["stdout"])
        stderr_bytes = base64.b64decode(collected["stderr"])
        stdout, stdout_truncated = self._decode_bounded_output(stdout_bytes, int(collected["stdout_bytes"]))
        stderr, stderr_truncated = self._decode_bounded_output(stderr_bytes, int(collected["stderr_bytes"]))
        exit_code = int(collected["exit_code"])
        payload = {
            "status": "success" if exit_code == 0 else "error",
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        }
        if stdout_truncated:
            payload["stdout_truncated"] = True
            payload["stdout_original_bytes"] = int(collected["stdout_bytes"])
        if stderr_truncated:
            payload["stderr_truncated"] = True
            payload["stderr_original_bytes"] = int(collected["stderr_bytes"])
        if collected.get("timed_out"):
            payload["timed_out"] = True
        return json.dumps(payload)

    def _command_capture_bytes(self) -> int:
        if self.max_output_chars is None:
            return -1
        return self.max_output_chars * MAX_UTF8_BYTES_PER_CHAR + 1

    def _run_bounded_command(self, sandbox: Any, run_context: RunContext, *, mode: str, content: str) -> str:
        command_directory = posixpath.join(DEFAULT_WORKING_DIRECTORY, ".agno", "commands", uuid4().hex)
        command_path = posixpath.join(command_directory, "command.py" if mode == "python" else "command.sh")
        working_directory = self._session_state(run_context)[WORKING_DIRECTORY_STATE_KEY]
        sandbox.fs.mkdir(command_directory, recursive=True)
        sandbox.fs.write_text(command_path, content)
        try:
            result = sandbox.exec(
                "python3",
                "-c",
                BOUNDED_COMMAND_RUNNER,
                mode,
                command_path,
                working_directory,
                str(self._command_capture_bytes()),
                str(self.command_timeout),
                str(COMMAND_TERMINATION_GRACE_SECONDS),
                cwd=working_directory,
                timeout=self.command_timeout + COMMAND_TERMINATION_GRACE_SECONDS + 1,
            )
            if not result.ok:
                return self._format_command_result(result)
            try:
                collected = json.loads(result.stdout_text)
            except (json.JSONDecodeError, TypeError):
                return self._format_command_result(result)
            return self._format_collected_command_result(collected)
        finally:
            try:
                sandbox.fs.remove(command_directory, recursive=True)
            except Exception as error:
                log_warning(f"Could not remove temporary Tenki command directory {command_directory}: {error}")

    async def _arun_bounded_command(self, sandbox: Any, run_context: RunContext, *, mode: str, content: str) -> str:
        command_directory = posixpath.join(DEFAULT_WORKING_DIRECTORY, ".agno", "commands", uuid4().hex)
        command_path = posixpath.join(command_directory, "command.py" if mode == "python" else "command.sh")
        working_directory = self._session_state(run_context)[WORKING_DIRECTORY_STATE_KEY]
        await sandbox.fs.mkdir(command_directory, recursive=True)
        await sandbox.fs.write_text(command_path, content)
        try:
            result = await sandbox.exec(
                "python3",
                "-c",
                BOUNDED_COMMAND_RUNNER,
                mode,
                command_path,
                working_directory,
                str(self._command_capture_bytes()),
                str(self.command_timeout),
                str(COMMAND_TERMINATION_GRACE_SECONDS),
                cwd=working_directory,
                timeout=self.command_timeout + COMMAND_TERMINATION_GRACE_SECONDS + 1,
            )
            if not result.ok:
                return self._format_command_result(result)
            try:
                collected = json.loads(result.stdout_text)
            except (json.JSONDecodeError, TypeError):
                return self._format_command_result(result)
            return self._format_collected_command_result(collected)
        finally:
            try:
                await sandbox.fs.remove(command_directory, recursive=True)
            except Exception as error:
                log_warning(f"Could not remove temporary Tenki command directory {command_directory}: {error}")

    def _read_bounded_text(self, filesystem: Any, path: str, label: str = "File content") -> str:
        if self.max_output_chars is None:
            return filesystem.read_text(path)
        capture_bytes = self._command_capture_bytes()
        read_length = capture_bytes + 1
        data = bytearray()
        for chunk in filesystem.read_stream(
            path,
            length=read_length,
            chunk_bytes=min(READ_STREAM_CHUNK_BYTES, max(read_length, 1)),
        ):
            remaining = read_length - len(data)
            if remaining <= 0:
                break
            data.extend(chunk[:remaining])
        was_truncated = len(data) > capture_bytes
        text, _ = self._decode_bounded_output(
            bytes(data[:capture_bytes]),
            None,
            label,
            was_truncated=was_truncated,
        )
        return text

    async def _aread_bounded_text(self, filesystem: Any, path: str, label: str = "File content") -> str:
        if self.max_output_chars is None:
            return await filesystem.read_text(path)
        capture_bytes = self._command_capture_bytes()
        read_length = capture_bytes + 1
        data = bytearray()
        async for chunk in filesystem.read_stream(
            path,
            length=read_length,
            chunk_bytes=min(READ_STREAM_CHUNK_BYTES, max(read_length, 1)),
        ):
            remaining = read_length - len(data)
            if remaining <= 0:
                break
            data.extend(chunk[:remaining])
        was_truncated = len(data) > capture_bytes
        text, _ = self._decode_bounded_output(
            bytes(data[:capture_bytes]),
            None,
            label,
            was_truncated=was_truncated,
        )
        return text

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
        return self._run_bounded_command(sandbox, run_context, mode="python", content=prepare_python_code(code))

    async def arun_code(self, run_context: RunContext, code: str) -> str:
        """Execute Python code asynchronously in the Tenki sandbox and return its output.

        Args:
            code: Python code to execute.
        """
        sandbox = await self._aget_or_create_sandbox(run_context)
        return await self._arun_bounded_command(sandbox, run_context, mode="python", content=prepare_python_code(code))

    def run_shell_command(self, run_context: RunContext, command: str) -> str:
        """Execute a Bash command in the Tenki sandbox and return its output.

        Args:
            command: Bash command to execute.
        """
        sandbox = self._get_or_create_sandbox(run_context)
        return self._run_bounded_command(sandbox, run_context, mode="shell", content=command)

    async def arun_shell_command(self, run_context: RunContext, command: str) -> str:
        """Execute a Bash command asynchronously in the Tenki sandbox and return its output.

        Args:
            command: Bash command to execute.
        """
        sandbox = await self._aget_or_create_sandbox(run_context)
        return await self._arun_bounded_command(sandbox, run_context, mode="shell", content=command)

    def create_file(self, run_context: RunContext, path: str, content: str) -> str:
        """Create or overwrite a text file in the Tenki sandbox.

        Args:
            path: File path relative to the current working directory, or an absolute path within /home/tenki.
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
            path: File path relative to the current working directory, or an absolute path within /home/tenki.
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
            path: File path relative to the current working directory, or an absolute path within /home/tenki.
        """
        resolved_path = self._resolve_path(run_context, path)
        sandbox = self._get_or_create_sandbox(run_context)
        return self._read_bounded_text(sandbox.fs, resolved_path)

    async def aread_file(self, run_context: RunContext, path: str) -> str:
        """Read a text file asynchronously from the Tenki sandbox.

        Args:
            path: File path relative to the current working directory, or an absolute path within /home/tenki.
        """
        resolved_path = self._resolve_path(run_context, path)
        sandbox = await self._aget_or_create_sandbox(run_context)
        return await self._aread_bounded_text(sandbox.fs, resolved_path)

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
            path: Directory path relative to the current working directory, or an absolute path within /home/tenki.
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
            path: Directory path relative to the current working directory, or an absolute path within /home/tenki.
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
            path: Path relative to the current working directory, or an absolute path within /home/tenki.
        """
        resolved_path = self._resolve_path(run_context, path)
        working_directory = self._session_state(run_context)[WORKING_DIRECTORY_STATE_KEY]
        if posixpath.commonpath([resolved_path, working_directory]) == resolved_path:
            raise ValueError("Cannot delete the current Tenki working directory")
        sandbox = self._get_or_create_sandbox(run_context)
        sandbox.fs.remove(resolved_path, recursive=True)
        return json.dumps({"status": "success", "path": resolved_path})

    async def adelete_file(self, run_context: RunContext, path: str) -> str:
        """Delete a file or directory asynchronously from the Tenki sandbox.

        Args:
            path: Path relative to the current working directory, or an absolute path within /home/tenki.
        """
        resolved_path = self._resolve_path(run_context, path)
        working_directory = self._session_state(run_context)[WORKING_DIRECTORY_STATE_KEY]
        if posixpath.commonpath([resolved_path, working_directory]) == resolved_path:
            raise ValueError("Cannot delete the current Tenki working directory")
        sandbox = await self._aget_or_create_sandbox(run_context)
        await sandbox.fs.remove(resolved_path, recursive=True)
        return json.dumps({"status": "success", "path": resolved_path})

    def change_directory(self, run_context: RunContext, path: str) -> str:
        """Change the working directory used by subsequent Tenki tools.

        Args:
            path: Directory path relative to the current working directory, or an absolute path within /home/tenki.
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
            path: Directory path relative to the current working directory, or an absolute path within /home/tenki.
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
                    False,
                ),
                "working_directory": state.get(WORKING_DIRECTORY_STATE_KEY, DEFAULT_WORKING_DIRECTORY),
            }
        )

    def _get_sandbox_for_status(self, run_context: RunContext) -> Optional[Any]:
        state = run_context.session_state or {}
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY)
        if not sandbox_id:
            return None
        try:
            return self.client.get(sandbox_id)
        except Exception as error:
            if not self._is_missing_sandbox_error(error):
                raise
            if not self.sandbox_id:
                self._clear_sandbox_state(run_context.session_state or {}, sandbox_id)
            return None

    async def _aget_sandbox_for_status(self, run_context: RunContext) -> Optional[Any]:
        state = run_context.session_state or {}
        sandbox_id = self.sandbox_id or state.get(SANDBOX_ID_STATE_KEY)
        if not sandbox_id:
            return None
        try:
            return await self.async_client.get(sandbox_id)
        except Exception as error:
            if not self._is_missing_sandbox_error(error):
                raise
            if not self.sandbox_id:
                self._clear_sandbox_state(run_context.session_state or {}, sandbox_id)
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
        self._clear_sandbox_state(state, sandbox.id)
        return json.dumps({"status": "success", "sandbox_id": sandbox.id, "state": sandbox.state})

    async def aterminate_sandbox(self, run_context: RunContext) -> str:
        """Terminate the current Tenki sandbox asynchronously."""
        sandbox = await self._aget_existing_sandbox(run_context)
        if sandbox.state not in {"TERMINATING", "TERMINATED", "USER_SHUTDOWN"}:
            await sandbox.close()
        state = self._session_state(run_context)
        self._clear_sandbox_state(state, sandbox.id)
        return json.dumps({"status": "success", "sandbox_id": sandbox.id, "state": sandbox.state})
