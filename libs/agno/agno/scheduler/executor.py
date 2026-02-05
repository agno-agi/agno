"""Schedule executor for running scheduled tasks.

This module handles the execution of scheduled tasks by making HTTP calls
to AgentOS endpoints and tracking the results.
"""

import json
import time
from typing import TYPE_CHECKING, Union, cast
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


class ScheduleExecutor:
    """Executes scheduled tasks by making HTTP calls to AgentOS endpoints.

    This executor supports both sync and async database adapters. When using
    an async adapter (AsyncBaseDb), database calls are non-blocking. When using
    a sync adapter (BaseDb), database calls will briefly block the event loop.

    The executor uses an internal service token for authentication. This token
    is not validated by JWT middleware, so the scheduler is not compatible with
    JWT authorization mode. Use security key authentication instead, or disable
    authentication for internal endpoints.
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
        # Check if db has async methods
        self._is_async_db = hasattr(db, "acreate_schedule_run")

    async def _create_schedule_run(self, run: ScheduleRun) -> ScheduleRun:
        """Create a schedule run record (async-aware)."""
        if self._is_async_db:
            return await self.db.acreate_schedule_run(run)  # type: ignore[union-attr]
        return cast(ScheduleRun, self.db.create_schedule_run(run))  # type: ignore[union-attr]

    async def _update_schedule_run(self, run: ScheduleRun) -> ScheduleRun:
        """Update a schedule run record (async-aware)."""
        if self._is_async_db:
            return await self.db.aupdate_schedule_run(run)  # type: ignore[union-attr]
        return cast(ScheduleRun, self.db.update_schedule_run(run))  # type: ignore[union-attr]

    async def _release_schedule(self, schedule_id: str, next_run_at: int) -> None:
        """Release a schedule lock (async-aware)."""
        if self._is_async_db:
            await self.db.arelease_schedule(schedule_id, next_run_at)  # type: ignore
        else:
            self.db.release_schedule(schedule_id, next_run_at)

    async def execute(self, schedule: Schedule) -> None:
        """Execute a schedule and track the result.

        Args:
            schedule: The schedule to execute.
        """
        if httpx is None:
            raise ImportError("httpx is required for scheduler execution")

        # Create a run record
        run = ScheduleRun(
            id=str(uuid4()),
            schedule_id=schedule.id,
            attempt=1,
            status="running",
        )

        try:
            await self._create_schedule_run(run)
            await self._execute_and_track(schedule, run)
        except Exception as e:
            log_error(f"Error executing schedule '{schedule.name}': {e}")
            await self._mark_failed(schedule, run, str(e))

    async def _execute_and_track(self, schedule: Schedule, run: ScheduleRun) -> None:
        """Execute the schedule and consume SSE stream until completion.

        Args:
            schedule: The schedule being executed.
            run: The run record to update.
        """
        url = f"{self.base_url}{schedule.endpoint}"
        log_info(f"Executing schedule '{schedule.name}': {schedule.method} {url}")

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
        # Agent/team/workflow runs typically support streaming
        should_stream = any(x in schedule.endpoint for x in ["/runs", "/agents/", "/teams/", "/workflows/"])

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

        try:
            async with client.stream(
                method=schedule.method,
                url=url,
                data=payload,
                headers=headers,
            ) as response:
                if response.status_code >= 400:
                    error_text = await response.aread()
                    await self._mark_failed(schedule, run, f"HTTP {response.status_code}: {error_text.decode()}")
                    return

                # Update run with status code
                run.status_code = response.status_code

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue

                    try:
                        data = json.loads(line[5:].strip())
                        event = data.get("event", "")

                        # Capture run info from first event
                        if data.get("run_id") and not run.run_id:
                            run.run_id = data.get("run_id")
                            run.session_id = data.get("session_id")
                            await self._update_schedule_run(run)

                        # Check for terminal events
                        if event == "RunCompleted":
                            await self._mark_success(schedule, run)
                            return
                        elif event == "RunError":
                            await self._mark_failed(schedule, run, data.get("content", "Unknown error"))
                            return

                    except json.JSONDecodeError:
                        continue

            # Stream ended without completion event
            await self._mark_failed(schedule, run, "Stream ended unexpectedly")

        except httpx.TimeoutException:
            await self._mark_failed(schedule, run, "Request timed out")
        except Exception as e:
            await self._mark_failed(schedule, run, str(e))

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
        try:
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
                await self._mark_failed(schedule, run, f"Unsupported method: {schedule.method}")
                return

            run.status_code = response.status_code

            if response.status_code >= 400:
                await self._mark_failed(schedule, run, f"HTTP {response.status_code}: {response.text}")
            else:
                # Try to extract run_id from response
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        run.run_id = data.get("run_id")
                        run.session_id = data.get("session_id")
                except (json.JSONDecodeError, ValueError):
                    pass

                await self._mark_success(schedule, run)

        except httpx.TimeoutException:
            await self._mark_failed(schedule, run, "Request timed out")
        except Exception as e:
            await self._mark_failed(schedule, run, str(e))

    async def _mark_success(self, schedule: Schedule, run: ScheduleRun) -> None:
        """Mark a run as successful and release the schedule.

        Args:
            schedule: The schedule that was executed.
            run: The run record to update.
        """
        run.status = "success"
        run.completed_at = int(time.time())
        await self._update_schedule_run(run)

        # Calculate next run time and release the schedule
        next_run_at = calculate_next_run(schedule.cron_expr, schedule.timezone)
        await self._release_schedule(schedule.id, next_run_at)

        log_info(f"Schedule '{schedule.name}' completed successfully")

    async def _mark_failed(self, schedule: Schedule, run: ScheduleRun, error: str) -> None:
        """Mark a run as failed and handle retry logic.

        Args:
            schedule: The schedule that was executed.
            run: The run record to update.
            error: The error message.
        """
        run.status = "failed"
        run.error = error
        run.completed_at = int(time.time())
        await self._update_schedule_run(run)

        log_error(f"Schedule '{schedule.name}' failed: {error}")

        # Check if we should retry
        if run.attempt < schedule.max_retries:
            # Schedule a retry
            retry_run = ScheduleRun(
                id=str(uuid4()),
                schedule_id=schedule.id,
                attempt=run.attempt + 1,
                status="pending",
                triggered_at=int(time.time()) + schedule.retry_delay_seconds,
            )
            await self._create_schedule_run(retry_run)
            log_debug(
                f"Scheduling retry {run.attempt + 1}/{schedule.max_retries} "
                f"for '{schedule.name}' in {schedule.retry_delay_seconds}s"
            )
        else:
            # All retries exhausted, release the schedule
            next_run_at = calculate_next_run(schedule.cron_expr, schedule.timezone)
            await self._release_schedule(schedule.id, next_run_at)
