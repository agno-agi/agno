"""Schedule executor — fires HTTP requests for due schedules."""

import asyncio
import re
import time
from typing import Any, Dict, Optional
from uuid import uuid4

from agno.utils.log import log_error, log_info, log_warning

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

# Regex to detect streaming run endpoints
_RUN_ENDPOINT_RE = re.compile(r"^/(agents|teams|workflows)/[^/]+/runs/?$")

# Terminal SSE event types that signal completion
_TERMINAL_EVENTS = {
    "RunCompleted",
    "RunError",
    "RunCancelled",
    "TeamRunCompleted",
    "TeamRunError",
    "TeamRunCancelled",
    "WorkflowRunCompleted",
    "WorkflowRunError",
    "WorkflowRunCancelled",
}


class ScheduleExecutor:
    """Execute a schedule by calling its endpoint on the AgentOS server.

    For run endpoints (``/agents/*/runs``, ``/teams/*/runs``, etc.) the executor
    consumes the SSE stream, captures ``run_id`` / ``session_id`` from the data,
    and waits for a terminal event before marking the run as complete.

    For all other endpoints a simple request/response cycle is used.
    """

    def __init__(
        self,
        base_url: str,
        internal_service_token: str,
        timeout: int = 3600,
    ) -> None:
        if httpx is None:
            raise ImportError("`httpx` not installed. Please install it using `pip install httpx`")
        self.base_url = base_url.rstrip("/")
        self.internal_service_token = internal_service_token
        self.timeout = timeout

    # ------------------------------------------------------------------
    async def execute(
        self,
        schedule: Dict[str, Any],
        db: Any,
        release_schedule: bool = True,
    ) -> Dict[str, Any]:
        """Execute *schedule* and persist run records.

        Args:
            schedule: Schedule dict (from DB).
            db: The DB adapter instance (must have scheduler methods).
            release_schedule: Whether to release the lock after execution.

        Returns:
            The ScheduleRun dict.
        """
        from agno.scheduler.cron import compute_next_run

        schedule_id = schedule["id"]
        max_attempts = max(1, (schedule.get("max_retries") or 0) + 1)
        retry_delay = schedule.get("retry_delay_seconds") or 60

        run_id_value: Optional[str] = None
        session_id_value: Optional[str] = None
        last_status = "failed"
        last_status_code: Optional[int] = None
        last_error: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            run_record_id = str(uuid4())
            now = int(time.time())

            run_dict: Dict[str, Any] = {
                "id": run_record_id,
                "schedule_id": schedule_id,
                "attempt": attempt,
                "triggered_at": now,
                "completed_at": None,
                "status": "running",
                "status_code": None,
                "run_id": None,
                "session_id": None,
                "error": None,
                "created_at": now,
            }

            if asyncio.iscoroutinefunction(getattr(db, "create_schedule_run", None)):
                await db.create_schedule_run(run_dict)
            else:
                db.create_schedule_run(run_dict)

            try:
                result = await self._call_endpoint(schedule)
                last_status = result.get("status", "success")
                last_status_code = result.get("status_code")
                last_error = result.get("error")
                run_id_value = result.get("run_id") or run_id_value
                session_id_value = result.get("session_id") or session_id_value

                updates: Dict[str, Any] = {
                    "completed_at": int(time.time()),
                    "status": last_status,
                    "status_code": last_status_code,
                    "run_id": run_id_value,
                    "session_id": session_id_value,
                    "error": last_error,
                }
                if asyncio.iscoroutinefunction(getattr(db, "update_schedule_run", None)):
                    await db.update_schedule_run(run_record_id, **updates)
                else:
                    db.update_schedule_run(run_record_id, **updates)

                if last_status == "success":
                    break

            except Exception as exc:
                last_status = "failed"
                last_error = str(exc)
                log_error(f"Schedule {schedule_id} attempt {attempt} failed: {exc}")

                updates = {
                    "completed_at": int(time.time()),
                    "status": "failed",
                    "error": last_error,
                }
                if asyncio.iscoroutinefunction(getattr(db, "update_schedule_run", None)):
                    await db.update_schedule_run(run_record_id, **updates)
                else:
                    db.update_schedule_run(run_record_id, **updates)

            if attempt < max_attempts:
                log_info(f"Schedule {schedule_id}: retrying in {retry_delay}s (attempt {attempt}/{max_attempts})")
                await asyncio.sleep(retry_delay)

        # Build final snapshot for the caller (don't mutate the DB-stored run_dict)
        final_run = dict(run_dict)
        final_run["status"] = last_status
        final_run["status_code"] = last_status_code
        final_run["error"] = last_error
        final_run["run_id"] = run_id_value
        final_run["session_id"] = session_id_value
        final_run["completed_at"] = int(time.time())

        # Release schedule lock and compute next run
        if release_schedule:
            try:
                next_run_at = compute_next_run(
                    schedule["cron_expr"],
                    schedule.get("timezone", "UTC"),
                )
            except Exception:
                log_warning(
                    f"Failed to compute next_run_at for schedule {schedule_id}; "
                    "disabling schedule to prevent it from becoming stuck"
                )
                next_run_at = None
                try:
                    if asyncio.iscoroutinefunction(getattr(db, "update_schedule", None)):
                        await db.update_schedule(schedule_id, enabled=False)
                    else:
                        db.update_schedule(schedule_id, enabled=False)
                except Exception as exc:
                    log_error(f"Failed to disable schedule {schedule_id} after cron failure: {exc}")

            try:
                if asyncio.iscoroutinefunction(getattr(db, "release_schedule", None)):
                    await db.release_schedule(schedule_id, next_run_at=next_run_at)
                else:
                    db.release_schedule(schedule_id, next_run_at=next_run_at)
            except Exception as exc:
                log_error(f"Failed to release schedule {schedule_id}: {exc}")

        return final_run

    # ------------------------------------------------------------------
    async def _call_endpoint(self, schedule: Dict[str, Any]) -> Dict[str, Any]:
        """Make the HTTP call to the schedule's endpoint."""
        method = (schedule.get("method") or "POST").upper()
        endpoint = schedule["endpoint"]
        payload = schedule.get("payload")
        timeout_seconds = schedule.get("timeout_seconds") or self.timeout
        url = f"{self.base_url}{endpoint}"

        headers = {
            "Authorization": f"Bearer {self.internal_service_token}",
            "Content-Type": "application/json",
        }

        is_streaming = _RUN_ENDPOINT_RE.match(endpoint) is not None and method == "POST"

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
            if is_streaming:
                return await self._stream_sse(client, url, headers, payload)
            else:
                return await self._simple_request(client, method, url, headers, payload)

    async def _simple_request(
        self,
        client: Any,
        method: str,
        url: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Non-streaming request/response."""
        kwargs: Dict[str, Any] = {"headers": headers}
        if payload is not None:
            kwargs["json"] = payload

        resp = await client.request(method, url, **kwargs)

        status = "success" if 200 <= resp.status_code < 300 else "failed"
        error = resp.text if status == "failed" else None
        return {
            "status": status,
            "status_code": resp.status_code,
            "error": error,
            "run_id": None,
            "session_id": None,
        }

    async def _stream_sse(
        self,
        client: Any,
        url: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Stream SSE from a run endpoint and capture run_id/session_id."""
        import json

        run_id: Optional[str] = None
        session_id: Optional[str] = None
        status = "failed"
        error: Optional[str] = None
        status_code: Optional[int] = None

        kwargs: Dict[str, Any] = {"headers": headers}
        if payload is not None:
            kwargs["json"] = payload

        async with client.stream("POST", url, **kwargs) as resp:
            status_code = resp.status_code
            if resp.status_code >= 400:
                body = await resp.aread()
                return {
                    "status": "failed",
                    "status_code": resp.status_code,
                    "error": body.decode("utf-8", errors="replace"),
                    "run_id": None,
                    "session_id": None,
                }

            event_type: Optional[str] = None
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    event_type = None
                    continue
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                    continue
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    try:
                        data = json.loads(data_str)
                    except (json.JSONDecodeError, TypeError):
                        log_warning(f"SSE: failed to parse data line: {data_str[:200]}")
                        continue

                    if isinstance(data, dict):
                        run_id = data.get("run_id") or run_id
                        session_id = data.get("session_id") or session_id

                    if event_type in _TERMINAL_EVENTS:
                        if "Error" in (event_type or "") or "Cancelled" in (event_type or ""):
                            if isinstance(data, dict):
                                error = data.get("error") or data.get("message")
                        else:
                            status = "success"
                        break

        return {
            "status": status,
            "status_code": status_code,
            "error": error,
            "run_id": run_id,
            "session_id": session_id,
        }
