"""TaskMarket tools for discovering and safely delegating agent work."""

import asyncio
import hashlib
import json
import math
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import httpx

from agno.tools import Toolkit

DEFAULT_API_BASE_URL = "https://api.taskmarket.dev"
BASE_CHAIN_ID = 8453
PLATFORM_FEE_BPS = 750
RELAY_BUFFER_USDC = Decimal("0.001")
USDC_QUANTUM = Decimal("0.000001")
SUPPORTED_MODES = {"bounty", "claim", "pitch", "benchmark"}


class TaskMarketTools(Toolkit):
    """Expose TaskMarket discovery and an explicitly authorized create flow.

    The read tools use TaskMarket's public API. Creating a task is deliberately
    delegated to the first-party CLI so this toolkit never reads or handles a
    wallet key. The create method requires ``confirm=True``, the exact
    ``confirmation_token`` returned by a preview, and a maximum spend that
    covers the reward, platform fee estimate, and relay buffer.

    Args:
        api_base_url: Public TaskMarket API base URL.
        cli_command: First-party TaskMarket CLI executable or command name.
        timeout: Timeout in seconds for HTTP and CLI operations.
        enable_list_tasks: Register the public task listing tool.
        enable_get_task: Register the task status tool.
        enable_list_submissions: Register the submission review tool.
        enable_preview_task: Register the non-paying cost preview tool.
        enable_create_task: Register the guarded create tool.
        all: Register every tool, overriding individual enable flags.
    """

    def __init__(
        self,
        api_base_url: str = DEFAULT_API_BASE_URL,
        cli_command: str = "taskmarket",
        timeout: int = 30,
        enable_list_tasks: bool = True,
        enable_get_task: bool = True,
        enable_list_submissions: bool = True,
        enable_preview_task: bool = True,
        enable_create_task: bool = True,
        all: bool = False,
        **kwargs: Any,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.cli_command = cli_command
        self.timeout = timeout
        self._pending_previews: Dict[str, Dict[str, Any]] = {}

        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []
        confirmation_tools = list(kwargs.pop("requires_confirmation_tools", []) or [])

        if all or enable_list_tasks:
            tools.append(self.list_tasks)
            async_tools.append((self.alist_tasks, "list_tasks"))
        if all or enable_get_task:
            tools.append(self.get_task)
            async_tools.append((self.aget_task, "get_task"))
        if all or enable_list_submissions:
            tools.append(self.list_submissions)
            async_tools.append((self.alist_submissions, "list_submissions"))
        if all or enable_preview_task:
            tools.append(self.preview_task)
            async_tools.append((self.apreview_task, "preview_task"))
        if all or enable_create_task:
            tools.append(self.create_task)
            async_tools.append((self.acreate_task, "create_task"))
            if "create_task" not in confirmation_tools:
                confirmation_tools.append("create_task")

        super().__init__(
            name="taskmarket_tools",
            tools=tools,
            async_tools=async_tools,
            requires_confirmation_tools=confirmation_tools,
            timeout=timeout,
            **kwargs,
        )

    def list_tasks(self, status: str = "open", limit: int = 20) -> str:
        """List public TaskMarket tasks without spending funds.

        Args:
            status: Task status such as ``open`` or ``completed``.
            limit: Maximum number of tasks to return, from 1 to 100.

        Returns:
            JSON containing the public API response or an error.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            return self._json_error("limit must be an integer between 1 and 100")
        if not status or len(status) > 40:
            return self._json_error("status must be a non-empty string")
        return self._get_json("/api/tasks", {"status": status, "limit": limit})

    def get_task(self, task_id: str) -> str:
        """Retrieve one public TaskMarket task by its hexadecimal ID."""
        error = self._validate_task_id(task_id)
        if error:
            return self._json_error(error)
        return self._get_json(f"/api/tasks/{task_id}")

    def list_submissions(self, task_id: str) -> str:
        """List submissions for a public task for human review."""
        error = self._validate_task_id(task_id)
        if error:
            return self._json_error(error)
        return self._get_json(f"/api/tasks/{task_id}/submissions")

    def preview_task(
        self,
        description: str,
        reward_usdc: str,
        duration_hours: float,
        tags: Union[str, Sequence[str]],
        max_spend_usdc: str,
        mode: str = "bounty",
    ) -> str:
        """Preview a task's budget and deadline without submitting it."""
        preview, error = self._build_preview(
            description=description,
            reward_usdc=reward_usdc,
            duration_hours=duration_hours,
            tags=tags,
            max_spend_usdc=max_spend_usdc,
            mode=mode,
        )
        if error:
            return self._json_error(error, notSubmitted=True)
        preview_with_token = self._remember_preview(preview)
        return self._json({"preview": preview_with_token, "notSubmitted": True, "success": True})

    def create_task(
        self,
        description: str,
        reward_usdc: str,
        duration_hours: float,
        tags: Union[str, Sequence[str]],
        max_spend_usdc: str,
        confirm: bool = False,
        mode: str = "bounty",
        confirmation_token: Optional[str] = None,
    ) -> str:
        """Create a TaskMarket task once after explicit user authorization.

        The first-party CLI is called at most once after the exact preview token
        is verified. If the CLI reports a failure after it may have contacted
        the payment rail, this method returns ``retry: false`` and an unknown
        settlement state instead of retrying automatically.
        """
        preview, error = self._build_preview(
            description=description,
            reward_usdc=reward_usdc,
            duration_hours=duration_hours,
            tags=tags,
            max_spend_usdc=max_spend_usdc,
            mode=mode,
        )
        if error:
            return self._json_error(error, notSubmitted=True, retry=False)

        if not confirm:
            preview_with_token = self._remember_preview(preview)
            return self._json(
                {
                    "confirmationRequired": True,
                    "notSubmitted": True,
                    "preview": preview_with_token,
                    "message": "Call again with confirm=true and the preview confirmationToken only after the user approves this exact preview.",
                }
            )

        if not isinstance(confirmation_token, str) or not confirmation_token:
            return self._json_error(
                "confirmation_token is required and must come from the exact preview being approved",
                notSubmitted=True,
                retry=False,
            )

        approved_preview = self._pending_previews.pop(confirmation_token, None)
        if approved_preview is None:
            return self._json_error(
                "confirmation_token is unknown or already used; preview the exact task again",
                notSubmitted=True,
                retry=False,
            )
        if not self._same_preview_request(preview, approved_preview):
            return self._json_error(
                "create arguments do not match the approved preview; preview the exact task again",
                notSubmitted=True,
                retry=False,
            )
        preview = approved_preview

        max_spend = Decimal(preview["maxSpendUsdc"])
        estimated = Decimal(preview["estimatedMaxSpendUsdc"])
        if max_spend < estimated:
            return self._json_error(
                f"max_spend_usdc must be at least {preview['estimatedMaxSpendUsdc']} USDC",
                notSubmitted=True,
                retry=False,
            )

        deposit = self._run_cli(["deposit"])
        if deposit["returncode"] != 0 or not deposit["json"]:
            return self._json(
                {
                    "error": "Unable to verify the first-party TaskMarket wallet/network; task was not submitted.",
                    "notSubmitted": True,
                    "paymentState": "not_started",
                    "retry": False,
                }
            )

        wallet = deposit["json"].get("data", deposit["json"])
        if (
            wallet.get("chainId") != BASE_CHAIN_ID
            or str(wallet.get("network", "")).lower() != "base"
            or str(wallet.get("currency", "")).upper() != "USDC"
        ):
            return self._json(
                {
                    "error": "TaskMarket wallet must report Base chain ID 8453 and USDC; task was not submitted.",
                    "notSubmitted": True,
                    "paymentState": "not_started",
                    "retry": False,
                }
            )

        cli_args = [
            "task",
            "create",
            "--description",
            description,
            "--reward",
            reward_usdc,
            "--duration",
            str(duration_hours),
            "--mode",
            mode,
            "--tags",
            ",".join(preview["tags"]),
        ]
        created = self._run_cli(cli_args)
        if created["returncode"] != 0:
            return self._json(
                {
                    "error": "TaskMarket create command failed; inspect live task state before any manual decision.",
                    "notSubmitted": False,
                    "paymentState": "unknown_or_not_settled",
                    "retry": False,
                }
            )

        task_payload = created["json"] or {}
        task_data = task_payload.get("data", task_payload)
        task_id = task_data.get("id") or task_data.get("taskId") or task_payload.get("taskId")
        if not task_id:
            return self._json(
                {
                    "error": "TaskMarket create returned no task ID; settlement is unknown.",
                    "notSubmitted": False,
                    "paymentState": "unknown_or_not_settled",
                    "retry": False,
                }
            )

        return self._json(
            {
                "success": True,
                "taskId": task_id,
                "taskUrl": f"{self.api_base_url}/api/tasks/{task_id}",
                "preview": preview,
                "paymentState": "submitted_once",
                "retry": False,
            }
        )

    async def alist_tasks(self, status: str = "open", limit: int = 20) -> str:
        """Async variant of :meth:`list_tasks`."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            return self._json_error("limit must be an integer between 1 and 100")
        if not status or len(status) > 40:
            return self._json_error("status must be a non-empty string")
        return await self._async_get_json("/api/tasks", {"status": status, "limit": limit})

    async def aget_task(self, task_id: str) -> str:
        """Async variant of :meth:`get_task`."""
        error = self._validate_task_id(task_id)
        if error:
            return self._json_error(error)
        return await self._async_get_json(f"/api/tasks/{task_id}")

    async def alist_submissions(self, task_id: str) -> str:
        """Async variant of :meth:`list_submissions`."""
        error = self._validate_task_id(task_id)
        if error:
            return self._json_error(error)
        return await self._async_get_json(f"/api/tasks/{task_id}/submissions")

    async def apreview_task(self, *args: Any, **kwargs: Any) -> str:
        """Async variant of :meth:`preview_task`."""
        return await asyncio.to_thread(self.preview_task, *args, **kwargs)

    async def acreate_task(self, *args: Any, **kwargs: Any) -> str:
        """Async variant of :meth:`create_task`."""
        return await asyncio.to_thread(self.create_task, *args, **kwargs)

    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        try:
            with httpx.Client(base_url=self.api_base_url, timeout=self.timeout) as client:
                response = client.get(path, params=params)
                response.raise_for_status()
                return self._json(response.json())
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            return self._json_error(f"TaskMarket API returned HTTP {status_code}", retry=False)
        except httpx.RequestError:
            return self._json_error("TaskMarket API request failed", retry=False)
        except (TypeError, ValueError):
            return self._json_error("TaskMarket API returned invalid JSON", retry=False)

    async def _async_get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        try:
            async with httpx.AsyncClient(base_url=self.api_base_url, timeout=self.timeout) as client:
                response = await client.get(path, params=params)
                response.raise_for_status()
                return self._json(response.json())
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            return self._json_error(f"TaskMarket API returned HTTP {status_code}", retry=False)
        except httpx.RequestError:
            return self._json_error("TaskMarket API request failed", retry=False)
        except (TypeError, ValueError):
            return self._json_error("TaskMarket API returned invalid JSON", retry=False)

    def _run_cli(self, args: List[str]) -> Dict[str, Any]:
        try:
            completed = subprocess.run(
                [self.cli_command, *args],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return {"returncode": 1, "json": None}

        return {"returncode": completed.returncode, "json": self._parse_cli_json(completed.stdout)}

    @staticmethod
    def _parse_cli_json(output: str) -> Optional[Dict[str, Any]]:
        for line in reversed(output.splitlines()):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _build_preview(
        self,
        description: str,
        reward_usdc: str,
        duration_hours: float,
        tags: Union[str, Sequence[str]],
        max_spend_usdc: str,
        mode: str,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        if not isinstance(description, str) or not description.strip() or len(description) > 10000:
            return {}, "description must be a non-empty string of at most 10000 characters"
        if mode not in SUPPORTED_MODES:
            return {}, f"mode must be one of: {', '.join(sorted(SUPPORTED_MODES))}"

        reward, reward_error = self._parse_usdc(reward_usdc, "reward_usdc")
        if reward_error:
            return {}, reward_error
        max_spend, max_spend_error = self._parse_usdc(max_spend_usdc, "max_spend_usdc")
        if max_spend_error:
            return {}, max_spend_error

        try:
            duration = Decimal(str(duration_hours))
        except (InvalidOperation, ValueError):
            return {}, "duration_hours must be a positive finite number"
        if not duration.is_finite() or duration <= 0:
            return {}, "duration_hours must be a positive finite number"

        normalized_tags = self._normalize_tags(tags)
        if not normalized_tags:
            return {}, "tags must contain between 1 and 10 non-empty values"
        if len(normalized_tags) > 10:
            return {}, "tags must contain between 1 and 10 non-empty values"

        estimated = self._estimate_max_spend(reward)
        try:
            duration_float = float(duration)
            if not math.isfinite(duration_float):
                return {}, "duration_hours must be a positive finite number within the supported date range"
            deadline = datetime.now(timezone.utc) + timedelta(hours=duration_float)
        except (OverflowError, ValueError):
            return {}, "duration_hours must be a positive finite number within the supported date range"
        preview = {
            "description": description,
            "rewardUsdc": self._format_usdc(reward),
            "durationHours": self._format_duration(duration),
            "deadlineUtc": deadline.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "tags": normalized_tags,
            "mode": mode,
            "maxSpendUsdc": self._format_usdc(max_spend),
            "estimatedMaxSpendUsdc": self._format_usdc(estimated),
            "maxSpendSufficient": max_spend >= estimated,
            "platformFeeEstimateBps": PLATFORM_FEE_BPS,
            "relayBufferUsdc": self._format_usdc(RELAY_BUFFER_USDC),
            "network": {"name": "Base", "chainId": BASE_CHAIN_ID, "asset": "USDC"},
        }
        return preview, None

    def _remember_preview(self, preview: Dict[str, Any]) -> Dict[str, Any]:
        token_payload = json.dumps(preview, sort_keys=True, separators=(",", ":"))
        token = hashlib.sha256(token_payload.encode("utf-8")).hexdigest()
        self._pending_previews[token] = preview
        if len(self._pending_previews) > 32:
            oldest_token = next(iter(self._pending_previews))
            del self._pending_previews[oldest_token]
        return {**preview, "confirmationToken": token}

    @staticmethod
    def _same_preview_request(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
        fields = ("description", "rewardUsdc", "durationHours", "tags", "mode", "maxSpendUsdc")
        return all(first.get(field) == second.get(field) for field in fields)

    @staticmethod
    def _parse_usdc(value: Any, field_name: str) -> Tuple[Decimal, Optional[str]]:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return Decimal(0), f"{field_name} must be a positive USDC amount with at most 6 decimals"
        exponent = parsed.as_tuple().exponent
        if not parsed.is_finite() or parsed <= 0 or not isinstance(exponent, int) or exponent < -6:
            return Decimal(0), f"{field_name} must be a positive USDC amount with at most 6 decimals"
        return parsed, None

    @staticmethod
    def _normalize_tags(tags: Union[str, Sequence[str]]) -> List[str]:
        if isinstance(tags, str):
            values = tags.split(",")
        else:
            values = list(tags)
        return [tag.strip() for tag in values if isinstance(tag, str) and tag.strip()]

    @staticmethod
    def _estimate_max_spend(reward: Decimal) -> Decimal:
        total = reward * (Decimal(10000 + PLATFORM_FEE_BPS) / Decimal(10000)) + RELAY_BUFFER_USDC
        return total.quantize(USDC_QUANTUM, rounding=ROUND_HALF_UP)

    @staticmethod
    def _format_usdc(value: Decimal) -> str:
        return format(value.quantize(USDC_QUANTUM, rounding=ROUND_HALF_UP), "f")

    @staticmethod
    def _format_duration(value: Decimal) -> str:
        formatted = format(value, "f").rstrip("0").rstrip(".")
        return formatted or "0"

    @staticmethod
    def _validate_task_id(task_id: str) -> Optional[str]:
        if not isinstance(task_id, str) or not task_id.startswith("0x") or len(task_id) < 4:
            return "task_id must be a 0x-prefixed hexadecimal ID"
        try:
            int(task_id[2:], 16)
        except ValueError:
            return "task_id must be a 0x-prefixed hexadecimal ID"
        return None

    @staticmethod
    def _json(payload: Dict[str, Any]) -> str:
        return json.dumps(payload, indent=2, sort_keys=True)

    @classmethod
    def _json_error(cls, message: str, **extra: Any) -> str:
        return cls._json({"error": message, **extra})
