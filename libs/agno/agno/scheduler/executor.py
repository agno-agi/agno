"""Schedule executor for running scheduled tasks.

This module handles the execution of scheduled tasks by making HTTP calls
to AgentOS endpoints and tracking the results.
"""

import asyncio
import json
import re
import time
from inspect import isawaitable
from typing import TYPE_CHECKING, Optional, Union
from uuid import uuid4

from agno.db.schemas.scheduler import Schedule, ScheduleRun
from agno.scheduler.cron import calculate_next_run
from agno.utils.log import log_debug, log_error, log_info

if TYPE_CHECKING:
    from agno.db.base import AsyncBaseDb, BaseDb

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


_STREAMING_RUN_ENDPOINT_RE = re.compile(r"^/(agents|teams|workflows)/[^/]+/runs/?$")


class ScheduleExecutor:
    """Executes scheduled tasks by making HTTP calls to AgentOS endpoints.

    This executor supports both sync and async database adapters. When using
    an async adapter (AsyncBaseDb), database calls are non-blocking. When using
    a sync adapter (BaseDb), database calls will briefly block the event loop.

    The executor uses an internal service token for authentication. This token
    is accepted by AgentOS security-key auth, and is also recognized by AgentOS's
    JWT middleware (when enabled) as an internal admin token. Keep this token
    secret: it grants full access to the AgentOS API.
    """

    def __init__(
        self,
        db: Union["BaseDb", "AsyncBaseDb"],
        base_url: str,
        token: str,
    ):
        """Initialize the executor.

        Args:
            db: Database instance for tracking runs (supports both sync and async).
            base_url: Base URL for AgentOS endpoints (e.g., 'http://localhost:7777').
            token: Internal service token for authentication.
        """
        self.db = db
        self.base_url = base_url.rstrip("/")
        self.token = token

    async def _create_schedule_run(self, run: ScheduleRun) -> ScheduleRun:
        """Create a schedule run record (sync/async)."""
        result = self.db.create_schedule_run(run)  # type: ignore[union-attr]
        if isawaitable(result):
            return await result  # type: ignore[misc]
        return result  # type: ignore[return-value]

    async def _update_schedule_run(self, run: ScheduleRun) -> ScheduleRun:
        """Update a schedule run record (sync/async)."""
        result = self.db.update_schedule_run(run)  # type: ignore[union-attr]
        if isawaitable(result):
            return await result  # type: ignore[misc]
        return result  # type: ignore[return-value]

    async def _release_schedule(self, schedule_id: str, next_run_at: int) -> None:
        """Release a schedule lock (sync/async)."""
        result = self.db.release_schedule(schedule_id, next_run_at)  # type: ignore[union-attr]
        if isawaitable(result):
            await result  # type: ignore[misc]

    async def _finalize_run(self, run: ScheduleRun, status: str, error: Optional[str] = None) -> None:
        run.status = status
        run.error = error
        run.completed_at = int(time.time())
        await self._update_schedule_run(run)

    async def execute(self, schedule: Schedule, release_schedule: bool = True) -> None:
        """Execute a schedule and track the result.

        Args:
            schedule: The schedule to execute.
            release_schedule: If True, update schedule.next_run_at and clear the lock
                at the end of execution. Manual triggers typically set this to False.
        """
        if httpx is None:
            raise ImportError("httpx is required for scheduler execution")

        max_attempts = max(1, schedule.max_retries + 1)
        succeeded = False
        last_error: Optional[str] = None

        try:
            for attempt in range(1, max_attempts + 1):
                run = ScheduleRun(
                    id=str(uuid4()),
                    schedule_id=schedule.id,
                    attempt=attempt,
                    status="running",
                )

                await self._create_schedule_run(run)

                try:
                    await self._execute_and_track(schedule, run)
                except httpx.TimeoutException:
                    last_error = "Request timed out"
                    log_error(f"Schedule '{schedule.name}' attempt {attempt} timed out: {last_error}")
                    await self._finalize_run(run, status="timeout", error=last_error)
                except Exception as e:
                    last_error = str(e)
                    log_error(f"Schedule '{schedule.name}' attempt {attempt} failed: {last_error}")
                    await self._finalize_run(run, status="failed", error=last_error)
                else:
                    await self._finalize_run(run, status="success")
                    succeeded = True
                    last_error = None
                    break

                if attempt <= schedule.max_retries:
                    delay_seconds = max(0, int(schedule.retry_delay_seconds))
                    log_debug(
                        f"Scheduling retry {attempt + 1}/{max_attempts} for '{schedule.name}' in {delay_seconds}s"
                    )
                    if delay_seconds > 0:
                        await asyncio.sleep(delay_seconds)
        finally:
            if release_schedule:
                try:
                    try:
                        next_run_at = calculate_next_run(schedule.cron_expr, schedule.timezone)
                    except Exception as e:
                        log_error(f"Error calculating next run for schedule '{schedule.name}': {e}")
                        next_run_at = schedule.next_run_at or int(time.time()) + 60
                    await self._release_schedule(schedule.id, next_run_at)
                except Exception as e:
                    log_error(f"Error releasing schedule '{schedule.name}': {e}")

        if succeeded:
            log_info(f"Schedule '{schedule.name}' completed successfully")
        else:
            log_error(f"Schedule '{schedule.name}' failed: {last_error or 'Unknown error'}")

    async def _execute_and_track(self, schedule: Schedule, run: ScheduleRun) -> None:
        """Execute the schedule and consume SSE stream until completion.

        Args:
            schedule: The schedule being executed.
            run: The run record to update.
        """
        url = f"{self.base_url}{schedule.endpoint}"
        log_info(f"Executing schedule '{schedule.name}' (attempt {run.attempt}): {schedule.method} {url}")

        timeout = httpx.Timeout(
            connect=10.0,
            read=float(schedule.timeout_seconds),
            write=10.0,
            pool=10.0,
        )

        # Prepare the request
        headers = {
            "Authorization": f"Bearer {self.token}",
        }

        # Determine if we should stream based on the endpoint
        # Agent/team/workflow run endpoints support streaming.
        should_stream = bool(_STREAMING_RUN_ENDPOINT_RE.match(schedule.endpoint))

        async with httpx.AsyncClient(timeout=timeout) as client:
            if should_stream and schedule.method.upper() == "POST":
                # For agent/team/workflow runs, use streaming to track completion
                await self._execute_streaming(client, schedule, run, url, headers)
            else:
                # For other endpoints, use simple request/response
                await self._execute_simple(client, schedule, run, url, headers)

    async def _execute_streaming(
        self,
        client: httpx.AsyncClient,
        schedule: Schedule,
        run: ScheduleRun,
        url: str,
        headers: dict,
    ) -> None:
        """Execute a streaming request and consume SSE events.

        Args:
            client: HTTP client.
            schedule: The schedule being executed.
            run: The run record to update.
            url: The URL to call.
            headers: Request headers.
        """
        # Add stream parameter to payload
        payload = dict(schedule.payload or {})
        payload["stream"] = True

        headers["Content-Type"] = "application/x-www-form-urlencoded"

        async with client.stream(
            method=schedule.method,
            url=url,
            data=payload,
            headers=headers,
        ) as response:
            run.status_code = response.status_code

            if response.status_code >= 400:
                error_text = await response.aread()
                error_body = error_text.decode(errors="replace")
                raise RuntimeError(f"HTTP {response.status_code}: {error_body}")

            success_events = {"RunCompleted", "TeamRunCompleted", "WorkflowCompleted"}
            error_events = {"RunError", "TeamRunError", "WorkflowError"}
            cancelled_events = {"RunCancelled", "TeamRunCancelled", "WorkflowCancelled"}

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue

                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue

                event = data.get("event", "")

                if data.get("run_id") and not run.run_id:
                    run.run_id = data.get("run_id")
                    run.session_id = data.get("session_id")
                    await self._update_schedule_run(run)

                if event in success_events:
                    return
                if event in error_events:
                    raise RuntimeError(data.get("content") or data.get("error") or "Unknown error")
                if event in cancelled_events:
                    raise RuntimeError(data.get("reason") or "Cancelled")

        raise RuntimeError("Stream ended unexpectedly")

    async def _execute_simple(
        self,
        client: httpx.AsyncClient,
        schedule: Schedule,
        run: ScheduleRun,
        url: str,
        headers: dict,
    ) -> None:
        """Execute a simple (non-streaming) request.

        Args:
            client: HTTP client.
            schedule: The schedule being executed.
            run: The run record to update.
            url: The URL to call.
            headers: Request headers.
        """
        if schedule.method.upper() == "GET":
            response = await client.get(url, headers=headers)
        elif schedule.method.upper() == "POST":
            headers["Content-Type"] = "application/json"
            response = await client.post(url, json=schedule.payload or {}, headers=headers)
        elif schedule.method.upper() == "PUT":
            headers["Content-Type"] = "application/json"
            response = await client.put(url, json=schedule.payload or {}, headers=headers)
        elif schedule.method.upper() == "DELETE":
            response = await client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported method: {schedule.method}")

        run.status_code = response.status_code

        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text}")

        # Try to extract run_id from response
        try:
            data = response.json()
            if isinstance(data, dict):
                run.run_id = data.get("run_id")
                run.session_id = data.get("session_id")
        except (json.JSONDecodeError, ValueError):
            pass
