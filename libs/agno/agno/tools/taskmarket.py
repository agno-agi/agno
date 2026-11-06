from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import threading
from decimal import Decimal, InvalidOperation
from typing import Any

from agno.tools import Toolkit

_TASK_ID_PATTERN = re.compile(r"^0x[0-9a-fA-F]{64}$")
_ALLOWED_STATUSES = {
    "open",
    "claimed",
    "worker_selected",
    "pending_approval",
    "review",
    "appealing",
    "disputed",
    "completed",
    "expired",
    "cancelled",
}
_ALLOWED_MODES = {"bounty", "claim", "pitch", "benchmark", "auction"}
_ALLOWED_VISIBILITIES = {"public", "unlisted", "private"}
_ALLOWED_SUBMISSION_VISIBILITIES = {"public", "reveal_all", "winner_only", "never"}
_USDC_QUANTUM = Decimal("0.000001")
_CLI_OUTPUT_LIMIT_BYTES = 1024 * 1024
_CLI_READ_CHUNK_BYTES = 64 * 1024
_PROCESS_CLEANUP_TIMEOUT = 1.0


class _ProcessCreationTimeout(Exception):
    pass


class TaskMarketTools(Toolkit):
    """Discover work and explicitly create tasks through the first-party TaskMarket CLI.

    Read tools are enabled by default. Task creation is available only when
    ``allow_write=True`` and ``max_reward_usdc`` sets a positive spending cap.
    Agno also marks creation as requiring confirmation before execution.
    """

    def __init__(
        self,
        cli_path: str = "taskmarket",
        timeout: int = 30,
        allow_write: bool = False,
        max_reward_usdc: str | float | Decimal | None = None,
        **kwargs: Any,
    ):
        if not cli_path.strip():
            raise ValueError("cli_path must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if allow_write and max_reward_usdc is None:
            raise ValueError("max_reward_usdc is required when allow_write=True")
        if not allow_write and max_reward_usdc is not None:
            raise ValueError("max_reward_usdc requires allow_write=True")

        self.cli_path = cli_path
        self.timeout = timeout
        self.allow_write = allow_write
        self.max_reward_usdc = self._positive_decimal(max_reward_usdc, "max_reward_usdc") if allow_write else None
        self._funded_create_state_lock = threading.Lock()
        self._funded_create_in_flight = False
        self._funded_create_outcome_unknown = False

        tools: list[Any] = [self.list_tasks, self.get_task]
        async_tools = [(self.alist_tasks, "list_tasks"), (self.aget_task, "get_task")]
        confirmation_tools = list(kwargs.pop("requires_confirmation_tools", []) or [])
        if allow_write:
            tools.append(self.create_task)
            async_tools.append((self.acreate_task, "create_task"))
            if "create_task" not in confirmation_tools:
                confirmation_tools.append("create_task")

        super().__init__(
            name="taskmarket",
            tools=tools,
            async_tools=async_tools,
            requires_confirmation_tools=confirmation_tools,
            timeout=timeout,
            **kwargs,
        )

    @staticmethod
    def _positive_decimal(value: Any, name: str) -> Decimal:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValueError(f"{name} must be a valid number")
        if not number.is_finite() or number <= 0:
            raise ValueError(f"{name} must be greater than zero")
        exponent = number.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -6:
            raise ValueError(f"{name} must have at most 6 decimal places")
        if number > Decimal(1000000000):
            raise ValueError(f"{name} is too large")
        return number

    @staticmethod
    def _error(message: str, **details: Any) -> str:
        return json.dumps({"ok": False, "error": message, **details})

    @staticmethod
    def _process_group_kwargs() -> dict[str, Any]:
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            return {"creationflags": creation_flags} if creation_flags else {}
        return {"start_new_session": True}

    def _latch_unknown_funded_create(self) -> None:
        with self._funded_create_state_lock:
            self._funded_create_outcome_unknown = True

    def _begin_funded_create(self) -> str | None:
        with self._funded_create_state_lock:
            if self._funded_create_outcome_unknown:
                return self._unknown_funded_create_error()
            if self._funded_create_in_flight:
                return self._error(
                    "another funded task creation is already in progress; wait for it to finish before retrying",
                    retry_blocked=True,
                    outcome="in_progress",
                )
            self._funded_create_in_flight = True
        return None

    def _end_funded_create(self) -> None:
        with self._funded_create_state_lock:
            self._funded_create_in_flight = False

    def _unknown_funded_create_error(self) -> str:
        return self._error(
            "a previous funded task creation has an unknown outcome; inspect TaskMarket state before retrying",
            retry_blocked=True,
            outcome="unknown",
        )

    def _output_limit_error(self) -> str:
        return self._error("TaskMarket CLI output exceeded the safety byte limit")

    @staticmethod
    def _signal_process_group(process: Any, sig: signal.Signals) -> None:
        pid = getattr(process, "pid", None)
        if os.name != "nt" and pid is not None:
            try:
                # POSIX subprocesses are started with ``start_new_session=True``,
                # so the child PID is also the process-group ID.  Use it
                # directly: the parent may have exited while a descendant
                # still holds a pipe open.
                os.killpg(pid, sig)
                return
            except ProcessLookupError:
                return
            except OSError:
                pass

        try:
            if sig == signal.SIGTERM:
                if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT") and hasattr(process, "send_signal"):
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass

    def _terminate_sync_process(self, process: Any, force: bool = False) -> None:
        if force:
            self._signal_process_group(process, signal.SIGKILL)
        elif getattr(process, "returncode", None) is None:
            self._signal_process_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=_PROCESS_CLEANUP_TIMEOUT)
        except subprocess.TimeoutExpired:
            self._signal_process_group(process, signal.SIGKILL)
            try:
                process.wait(timeout=_PROCESS_CLEANUP_TIMEOUT)
            except subprocess.TimeoutExpired:
                return

    def _cleanup_sync_process(self, process: Any, force: bool = False) -> None:
        try:
            self._terminate_sync_process(process, force=force)
        except Exception:  # noqa: BLE001
            try:
                self._signal_process_group(process, signal.SIGKILL)
            except Exception:  # noqa: BLE001
                return
            try:
                process.wait(timeout=_PROCESS_CLEANUP_TIMEOUT)
            except (OSError, subprocess.TimeoutExpired):
                return

    def _run(self, args: list[str], funded_create: bool = False) -> str:
        try:
            process = subprocess.Popen(
                [self.cli_path, *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **self._process_group_kwargs(),
            )
        except OSError:
            return self._error("TaskMarket CLI could not be executed")

        try:
            streams = [process.stdout, process.stderr]
            outputs = [bytearray(), bytearray()]
        except Exception:  # noqa: BLE001
            if funded_create:
                self._latch_unknown_funded_create()
            self._cleanup_sync_process(process)
            return self._unknown_funded_create_error() if funded_create else self._error("TaskMarket CLI failed")

        output_size = 0
        output_lock = threading.Lock()
        output_exceeded = threading.Event()
        reader_failed = threading.Event()

        def read_stream(index: int) -> None:
            nonlocal output_size
            stream = streams[index]
            try:
                while True:
                    if output_exceeded.is_set():
                        return
                    chunk = stream.read(_CLI_READ_CHUNK_BYTES)
                    if not chunk:
                        return
                    with output_lock:
                        if output_size + len(chunk) > _CLI_OUTPUT_LIMIT_BYTES:
                            output_exceeded.set()
                            break
                        output_size += len(chunk)
                        outputs[index].extend(chunk)
                if output_exceeded.is_set():
                    self._cleanup_sync_process(process, force=True)
            except Exception:  # noqa: BLE001
                reader_failed.set()
                self._cleanup_sync_process(process, force=True)

        readers = [threading.Thread(target=read_stream, args=(index,), daemon=True) for index in range(2)]
        for reader in readers:
            reader.start()
        try:
            returncode = process.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            if funded_create:
                self._latch_unknown_funded_create()
            self._cleanup_sync_process(process)
            return self._error("TaskMarket CLI command timed out")
        except Exception:  # noqa: BLE001
            if funded_create:
                self._latch_unknown_funded_create()
            self._cleanup_sync_process(process)
            return self._unknown_funded_create_error() if funded_create else self._error("TaskMarket CLI failed")
        finally:
            for reader in readers:
                reader.join(timeout=1)
            if any(reader.is_alive() for reader in readers):
                self._cleanup_sync_process(process, force=True)
                for reader in readers:
                    reader.join(timeout=1)
            for stream in streams:
                if stream is not None and not stream.closed:
                    stream.close()

        if output_exceeded.is_set():
            if funded_create:
                self._latch_unknown_funded_create()
            return self._output_limit_error()
        if reader_failed.is_set():
            if funded_create:
                self._latch_unknown_funded_create()
                return self._unknown_funded_create_error()
            return self._error("TaskMarket CLI failed while reading output")
        if returncode != 0:
            if funded_create:
                self._latch_unknown_funded_create()
                return self._unknown_funded_create_error()
            return self._error("TaskMarket CLI command failed", returncode=returncode)

        try:
            payload = json.loads(bytes(outputs[0]).decode())
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            if funded_create:
                self._latch_unknown_funded_create()
            return self._error("TaskMarket CLI returned invalid JSON")
        return json.dumps(payload)

    @staticmethod
    def _consume_task_result(task: asyncio.Future[Any]) -> None:
        try:
            task.result()
        except BaseException:  # noqa: BLE001
            return

    async def _wait_process_bounded(self, process: asyncio.subprocess.Process) -> bool:
        wait_task = asyncio.create_task(process.wait())
        try:
            await asyncio.wait_for(asyncio.shield(wait_task), timeout=_PROCESS_CLEANUP_TIMEOUT)
            return True
        except asyncio.TimeoutError:
            wait_task.cancel()
            wait_task.add_done_callback(self._consume_task_result)
            return False

    async def _terminate_and_wait(self, process: asyncio.subprocess.Process) -> None:
        try:
            if os.name != "nt" or process.returncode is None:
                self._signal_process_group(process, signal.SIGTERM)
        except (AttributeError, OSError, ProcessLookupError, RuntimeError):
            return
        if not await self._wait_process_bounded(process):
            await self._kill_and_wait(process)

    async def _kill_and_wait(self, process: asyncio.subprocess.Process) -> None:
        try:
            if os.name != "nt" or process.returncode is None:
                self._signal_process_group(process, signal.SIGKILL)
        except (AttributeError, OSError, ProcessLookupError, RuntimeError):
            return
        await self._wait_process_bounded(process)

    async def _cleanup_cancelled_process(self, process: asyncio.subprocess.Process) -> None:
        cleanup = asyncio.create_task(self._terminate_and_wait(process))
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        await cleanup

    async def _await_process_creation(
        self, process_creation: asyncio.Task[asyncio.subprocess.Process]
    ) -> asyncio.subprocess.Process:
        try:
            return await asyncio.wait_for(asyncio.shield(process_creation), timeout=_PROCESS_CLEANUP_TIMEOUT)
        except asyncio.CancelledError:
            process_creation.add_done_callback(self._cleanup_late_process)
            raise
        except asyncio.TimeoutError as error:
            process_creation.cancel()
            try:
                return await asyncio.wait_for(asyncio.shield(process_creation), timeout=_PROCESS_CLEANUP_TIMEOUT)
            except asyncio.CancelledError:
                process_creation.add_done_callback(self._cleanup_late_process)
                raise
            except asyncio.TimeoutError:
                process_creation.add_done_callback(self._cleanup_late_process)
                raise _ProcessCreationTimeout from error

    def _cleanup_late_process(self, process_creation: asyncio.Future[Any]) -> None:
        try:
            process = process_creation.result()
        except BaseException:  # noqa: BLE001
            return
        cleanup = asyncio.create_task(self._cleanup_cancelled_process(process))
        cleanup.add_done_callback(self._consume_task_result)

    async def _arun(self, args: list[str], funded_create: bool = False) -> str:
        process_creation = asyncio.create_task(
            asyncio.create_subprocess_exec(
                self.cli_path,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_CLI_READ_CHUNK_BYTES,
                **self._process_group_kwargs(),
            )
        )
        try:
            process = await asyncio.shield(process_creation)
        except asyncio.CancelledError:
            if funded_create:
                self._latch_unknown_funded_create()
            try:
                process = await self._await_process_creation(process_creation)
            except (_ProcessCreationTimeout, OSError):
                raise asyncio.CancelledError from None
            except asyncio.CancelledError:
                raise
            if funded_create:
                self._latch_unknown_funded_create()
            await self._cleanup_cancelled_process(process)
            raise
        except OSError:
            return self._error("TaskMarket CLI could not be executed")

        try:
            deadline = asyncio.get_running_loop().time() + self.timeout
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            stdout, output_exceeded = await asyncio.wait_for(self._read_process_output(process), timeout=remaining)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            await asyncio.wait_for(process.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            if funded_create:
                self._latch_unknown_funded_create()
            await self._cleanup_cancelled_process(process)
            return self._error("TaskMarket CLI command timed out")
        except asyncio.CancelledError:
            if funded_create:
                self._latch_unknown_funded_create()
            await self._cleanup_cancelled_process(process)
            raise
        except OSError:
            if funded_create:
                self._latch_unknown_funded_create()
            await self._cleanup_cancelled_process(process)
            return self._error("TaskMarket CLI could not be executed")
        except Exception:  # noqa: BLE001
            if funded_create:
                self._latch_unknown_funded_create()
                await self._cleanup_cancelled_process(process)
                return self._unknown_funded_create_error()
            await self._cleanup_cancelled_process(process)
            return self._error("TaskMarket CLI failed")

        if output_exceeded:
            if funded_create:
                self._latch_unknown_funded_create()
            await self._cleanup_cancelled_process(process)
            return self._output_limit_error()
        if process.returncode != 0:
            if funded_create:
                self._latch_unknown_funded_create()
                return self._unknown_funded_create_error()
            return self._error("TaskMarket CLI command failed", returncode=process.returncode)

        try:
            payload = json.loads(stdout.decode())
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            if funded_create:
                self._latch_unknown_funded_create()
            return self._error("TaskMarket CLI returned invalid JSON")
        return json.dumps(payload)

    async def _read_process_output(self, process: asyncio.subprocess.Process) -> tuple[bytes, bool]:
        stdout_stream = getattr(process, "stdout", None)
        stderr_stream = getattr(process, "stderr", None)
        if stdout_stream is None or stderr_stream is None:
            stdout, stderr = await process.communicate()
            output_exceeded = len(stdout) + len(stderr) > _CLI_OUTPUT_LIMIT_BYTES
            if output_exceeded:
                await self._terminate_and_wait(process)
            return stdout[:_CLI_OUTPUT_LIMIT_BYTES], output_exceeded

        output_size = 0
        output_exceeded = False

        async def read_stream(stream: asyncio.StreamReader, capture: bool) -> bytes:
            nonlocal output_size, output_exceeded
            output = bytearray()
            while True:
                if output_exceeded:
                    return bytes(output)
                chunk = await stream.read(max(1, min(_CLI_READ_CHUNK_BYTES, _CLI_OUTPUT_LIMIT_BYTES + 1 - output_size)))
                if not chunk:
                    return bytes(output)
                if output_size + len(chunk) > _CLI_OUTPUT_LIMIT_BYTES:
                    output_exceeded = True
                    await self._kill_and_wait(process)
                    return b""
                output_size += len(chunk)
                if capture:
                    output.extend(chunk)

        stdout_task = asyncio.create_task(read_stream(stdout_stream, capture=True))
        stderr_task = asyncio.create_task(read_stream(stderr_stream, capture=False))
        try:
            stdout, _ = await asyncio.gather(stdout_task, stderr_task)
        except BaseException:
            for task in (stdout_task, stderr_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        return stdout, output_exceeded

    def list_tasks(
        self,
        status: str = "open",
        mode: str | None = None,
        tags: str | None = None,
        reward_min: float | None = None,
        reward_max: float | None = None,
        deadline_hours: float | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> str:
        """List TaskMarket opportunities using validated filters."""
        if status not in _ALLOWED_STATUSES:
            return self._error("unsupported task status")
        if mode is not None and mode not in _ALLOWED_MODES:
            return self._error("unsupported task mode")
        if limit < 1 or limit > 100:
            return self._error("limit must be between 1 and 100")

        args = ["task", "list", "--status", status]
        options: list[tuple[str, Any]] = [
            ("--mode", mode),
            ("--tags", tags),
            ("--reward-min", reward_min),
            ("--reward-max", reward_max),
            ("--deadline-hours", deadline_hours),
        ]
        for flag, value in options:
            if value is not None:
                args.extend([flag, str(value)])
        args.extend(["--limit", str(limit)])
        if cursor is not None:
            args.extend(["--cursor", cursor])
        return self._run(args)

    async def alist_tasks(
        self,
        status: str = "open",
        mode: str | None = None,
        tags: str | None = None,
        reward_min: float | None = None,
        reward_max: float | None = None,
        deadline_hours: float | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> str:
        """Asynchronously list TaskMarket opportunities."""
        return await asyncio.to_thread(
            self.list_tasks,
            status=status,
            mode=mode,
            tags=tags,
            reward_min=reward_min,
            reward_max=reward_max,
            deadline_hours=deadline_hours,
            limit=limit,
            cursor=cursor,
        )

    def get_task(self, task_id: str) -> str:
        """Get the current state and available actions for one TaskMarket task."""
        if not _TASK_ID_PATTERN.fullmatch(task_id):
            return self._error("task_id must be a 0x-prefixed 32-byte hex value")
        return self._run(["task", "get", task_id])

    async def aget_task(self, task_id: str) -> str:
        """Asynchronously get one TaskMarket task."""
        return await asyncio.to_thread(self.get_task, task_id)

    def _create_task_args(
        self,
        description: str,
        reward_usdc: str | float | Decimal,
        duration_hours: int,
        mode: str = "bounty",
        tags: str | None = None,
        task_visibility: str = "public",
        submission_visibility: str = "public",
    ) -> list[str] | str:
        if self._funded_create_outcome_unknown:
            return self._unknown_funded_create_error()
        if not self.allow_write or self.max_reward_usdc is None:
            return self._error("task creation is disabled")
        if not description.strip():
            return self._error("description must not be empty")
        if duration_hours <= 0:
            return self._error("duration_hours must be greater than zero")
        if mode not in {"bounty", "claim"}:
            return self._error("unsupported task creation mode")
        if task_visibility == "private":
            return self._error("private task creation is not supported")
        if task_visibility not in _ALLOWED_VISIBILITIES:
            return self._error("unsupported task visibility")
        if submission_visibility not in _ALLOWED_SUBMISSION_VISIBILITIES:
            return self._error("unsupported submission visibility")

        try:
            reward = self._positive_decimal(reward_usdc, "reward_usdc")
        except ValueError as error:
            return self._error(str(error))
        if reward > self.max_reward_usdc:
            return self._error(f"reward_usdc exceeds the configured {self.max_reward_usdc:g} USDC spending cap")

        args = [
            "task",
            "create",
            "--description",
            description,
            "--reward",
            format(reward.quantize(_USDC_QUANTUM).normalize(), "f"),
            "--duration",
            str(duration_hours),
            "--mode",
            mode,
            "--task-visibility",
            task_visibility,
            "--submission-visibility",
            submission_visibility,
        ]
        if tags is not None:
            args.extend(["--tags", tags])
        return args

    def create_task(
        self,
        description: str,
        reward_usdc: str | float | Decimal,
        duration_hours: int,
        mode: str = "bounty",
        tags: str | None = None,
        task_visibility: str = "public",
        submission_visibility: str = "public",
    ) -> str:
        """Create a funded TaskMarket task after opt-in, cap checks, and Agno confirmation."""
        args = self._create_task_args(
            description=description,
            reward_usdc=reward_usdc,
            duration_hours=duration_hours,
            mode=mode,
            tags=tags,
            task_visibility=task_visibility,
            submission_visibility=submission_visibility,
        )
        if isinstance(args, str):
            return args
        reservation_error = self._begin_funded_create()
        if reservation_error is not None:
            return reservation_error
        try:
            return self._run(args, funded_create=True)
        except BaseException:
            self._latch_unknown_funded_create()
            raise
        finally:
            self._end_funded_create()

    async def acreate_task(
        self,
        description: str,
        reward_usdc: str | float | Decimal,
        duration_hours: int,
        mode: str = "bounty",
        tags: str | None = None,
        task_visibility: str = "public",
        submission_visibility: str = "public",
    ) -> str:
        """Asynchronously create a TaskMarket task with the same safeguards."""
        args = self._create_task_args(
            description=description,
            reward_usdc=reward_usdc,
            duration_hours=duration_hours,
            mode=mode,
            tags=tags,
            task_visibility=task_visibility,
            submission_visibility=submission_visibility,
        )
        if isinstance(args, str):
            return args
        reservation_error = self._begin_funded_create()
        if reservation_error is not None:
            return reservation_error
        try:
            return await self._arun(args, funded_create=True)
        except BaseException:
            self._latch_unknown_funded_create()
            raise
        finally:
            self._end_funded_create()
