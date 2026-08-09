from __future__ import annotations

import asyncio
import json
import re
import subprocess
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

    def _run(self, args: list[str]) -> str:
        try:
            result = subprocess.run(
                [self.cli_path, *args],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._error("TaskMarket CLI command timed out")
        except OSError:
            return self._error("TaskMarket CLI could not be executed")

        if result.returncode != 0:
            return self._error("TaskMarket CLI command failed", returncode=result.returncode)

        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return self._error("TaskMarket CLI returned invalid JSON")
        return json.dumps(payload)

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
        return self._run(args)

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
        return await asyncio.to_thread(
            self.create_task,
            description=description,
            reward_usdc=reward_usdc,
            duration_hours=duration_hours,
            mode=mode,
            tags=tags,
            task_visibility=task_visibility,
            submission_visibility=submission_visibility,
        )
