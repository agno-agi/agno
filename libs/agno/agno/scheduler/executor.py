"""Schedule executor -- fires HTTP requests for due schedules."""

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from agno.db.schemas.scheduler import Schedule
from agno.utils.log import log_error, log_info, log_warning

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

# Regex to detect run endpoints and capture resource type + ID
_RUN_ENDPOINT_RE = re.compile(r"^/(agents|teams|workflows)/([^/]+)/runs/?$")

# Terminal run statuses (RunStatus enum values from agno.run.base)
_TERMINAL_STATUSES = {"COMPLETED", "CANCELLED", "ERROR", "PAUSED"}

# Default polling interval in seconds for background run status checks
_DEFAULT_POLL_INTERVAL = 30


def _to_form_value(v: Any) -> str:
    """Convert a payload value to a JSON-safe form string."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


class ScheduleExecutor:
    """Execute a schedule by calling its endpoint on the AgentOS server.

    For run endpoints (``/agents/*/runs``, ``/teams/*/runs``, etc.) the executor
    submits a background run (``background=true``), then polls the run status
    endpoint until it reaches a terminal state (COMPLETED, ERROR, CANCELLED, PAUSED).

    For all other endpoints a simple request/response cycle is used.
    """

    def __init__(
        self,
        base_url: str,
        internal_service_token: str,
        timeout: int = 3600,
        poll_interval: int = _DEFAULT_POLL_INTERVAL,
    ) -> None:
        if httpx is None:
            raise ImportError("`httpx` not installed. Please install it using `pip install httpx`")
        self.base_url = base_url.rstrip("/")
        self.internal_service_token = internal_service_token
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the shared httpx.AsyncClient."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        return self._client

    async def close(self) -> None:
        """Close the shared httpx client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    async def execute(
        self,
        schedule: Union[Schedule, Dict[str, Any]],
        db: Any,
        release_schedule: bool = True,
    ) -> Dict[str, Any]:
        """Execute *schedule* and persist run records.

        Args:
            schedule: Schedule object or dict (from DB).
            db: The DB adapter instance (must have scheduler methods).
            release_schedule: Whether to release the lock after execution.

        Returns:
            The ScheduleRun dict.
        """
        from agno.scheduler.cron import compute_next_run

        # Normalize to Schedule dataclass for typed access
        sched = Schedule.from_dict(schedule) if isinstance(schedule, dict) else schedule

        schedule_id: Optional[str] = None
        run_id_value: Optional[str] = None
        session_id_value: Optional[str] = None
        last_status = "failed"
        last_status_code: Optional[int] = None
        last_error: Optional[str] = None
        last_input: Optional[Dict[str, Any]] = None
        last_output: Optional[Dict[str, Any]] = None
        last_requirements: Optional[List[Dict[str, Any]]] = None
        run_record_id: Optional[str] = None
        run_dict: Dict[str, Any] = {}

        try:
            schedule_id = sched.id
            max_attempts = max(1, (sched.max_retries or 0) + 1)
            retry_delay = sched.retry_delay_seconds or 60
            for attempt in range(1, max_attempts + 1):
                run_record_id = str(uuid4())
                now = int(time.time())

                run_dict = {
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
                    "input": None,
                    "output": None,
                    "requirements": None,
                    "created_at": now,
                }

                if asyncio.iscoroutinefunction(getattr(db, "create_schedule_run", None)):
                    await db.create_schedule_run(run_dict)
                else:
                    db.create_schedule_run(run_dict)

                try:
                    result = await self._call_endpoint(sched)
                    last_status = result.get("status", "success")
                    last_status_code = result.get("status_code")
                    last_error = result.get("error")
                    run_id_value = result.get("run_id") or run_id_value
                    session_id_value = result.get("session_id") or session_id_value
                    last_input = result.get("input")
                    last_output = result.get("output")
                    last_requirements = result.get("requirements")

                    updates: Dict[str, Any] = {
                        "completed_at": int(time.time()),
                        "status": last_status,
                        "status_code": last_status_code,
                        "run_id": run_id_value,
                        "session_id": session_id_value,
                        "error": last_error,
                        "input": last_input,
                        "output": last_output,
                        "requirements": last_requirements,
                    }
                    if asyncio.iscoroutinefunction(getattr(db, "update_schedule_run", None)):
                        await db.update_schedule_run(run_record_id, **updates)
                    else:
                        db.update_schedule_run(run_record_id, **updates)

                    if last_status in ("success", "paused"):
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

            # Build final snapshot for the caller
            final_run = dict(run_dict)
            final_run["status"] = last_status
            final_run["status_code"] = last_status_code
            final_run["error"] = last_error
            final_run["run_id"] = run_id_value
            final_run["session_id"] = session_id_value
            final_run["input"] = last_input
            final_run["output"] = last_output
            final_run["requirements"] = last_requirements
            final_run["completed_at"] = int(time.time())

            return final_run

        except asyncio.CancelledError:
            log_warning(f"Schedule {schedule_id} execution cancelled")
            if run_record_id is not None:
                cancel_updates: Dict[str, Any] = {
                    "completed_at": int(time.time()),
                    "status": "cancelled",
                    "error": "Execution cancelled during shutdown",
                }
                try:
                    if asyncio.iscoroutinefunction(getattr(db, "update_schedule_run", None)):
                        await db.update_schedule_run(run_record_id, **cancel_updates)
                    else:
                        db.update_schedule_run(run_record_id, **cancel_updates)
                except Exception:
                    pass
            raise

        finally:
            # Always release the schedule lock so it doesn't stay stuck
            if release_schedule and schedule_id is not None:
                try:
                    next_run_at = compute_next_run(
                        sched.cron_expr,
                        sched.timezone or "UTC",
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

    # ------------------------------------------------------------------
    async def _call_endpoint(self, schedule: Schedule) -> Dict[str, Any]:
        """Make the HTTP call to the schedule's endpoint."""
        method = (schedule.method or "POST").upper()
        endpoint = schedule.endpoint
        payload = schedule.payload or {}
        timeout_seconds = schedule.timeout_seconds or self.timeout
        url = f"{self.base_url}{endpoint}"

        match = _RUN_ENDPOINT_RE.match(endpoint)
        is_run_endpoint = match is not None and method == "POST"

        headers: Dict[str, str] = {
            "Authorization": f"Bearer {self.internal_service_token}",
        }

        client = await self._get_client()

        if is_run_endpoint and match is not None:
            form_payload = {k: _to_form_value(v) for k, v in payload.items() if k not in ("stream", "background")}
            form_payload["stream"] = "false"
            form_payload["background"] = "true"

            resource_type = match.group(1)
            resource_id = match.group(2)

            return await self._background_run(
                client,
                url,
                headers,
                form_payload,
                resource_type,
                resource_id,
                timeout_seconds,
            )
        else:
            headers["Content-Type"] = "application/json"
            return await self._simple_request(client, method, url, headers, payload if payload else None)

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
            "input": None,
            "output": None,
            "requirements": None,
        }

    async def _background_run(
        self,
        client: Any,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, str],
        resource_type: str,
        resource_id: str,
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """Submit a background run and poll until completion."""
        kwargs: Dict[str, Any] = {"headers": headers}
        if payload is not None:
            kwargs["data"] = payload

        resp = await client.request("POST", url, **kwargs)

        if resp.status_code >= 400:
            return {
                "status": "failed",
                "status_code": resp.status_code,
                "error": resp.text,
                "run_id": None,
                "session_id": None,
                "input": None,
                "output": None,
                "requirements": None,
            }

        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError):
            return {
                "status": "failed",
                "status_code": resp.status_code,
                "error": f"Invalid JSON in background run response: {resp.text[:500]}",
                "run_id": None,
                "session_id": None,
                "input": None,
                "output": None,
                "requirements": None,
            }

        run_id = body.get("run_id")
        session_id = body.get("session_id")

        if not run_id or not session_id:
            return {
                "status": "failed",
                "status_code": resp.status_code,
                "error": f"Missing run_id or session_id in background run response: {body}",
                "run_id": run_id,
                "session_id": session_id,
                "input": None,
                "output": None,
                "requirements": None,
            }

        return await self._poll_run(
            client,
            headers,
            resource_type,
            resource_id,
            run_id,
            session_id,
            timeout_seconds,
        )

    async def _poll_run(
        self,
        client: Any,
        headers: Dict[str, str],
        resource_type: str,
        resource_id: str,
        run_id: str,
        session_id: str,
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """Poll a run status endpoint until the run reaches a terminal state."""
        poll_url = f"{self.base_url}/{resource_type}/{resource_id}/runs/{run_id}"
        deadline = time.monotonic() + timeout_seconds

        while True:
            if time.monotonic() >= deadline:
                return {
                    "status": "failed",
                    "status_code": None,
                    "error": f"Polling timed out after {timeout_seconds}s for run {run_id}",
                    "run_id": run_id,
                    "session_id": session_id,
                    "input": None,
                    "output": None,
                    "requirements": None,
                }

            try:
                resp = await client.request(
                    "GET",
                    poll_url,
                    headers=headers,
                    params={"session_id": session_id},
                )
            except Exception as exc:
                log_warning(f"Poll request failed for run {run_id}: {exc}")
                continue

            if resp.status_code == 404:
                continue

            if resp.status_code >= 400:
                return {
                    "status": "failed",
                    "status_code": resp.status_code,
                    "error": resp.text,
                    "run_id": run_id,
                    "session_id": session_id,
                    "input": None,
                    "output": None,
                    "requirements": None,
                }

            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError):
                log_warning(f"Invalid JSON in poll response for run {run_id}")
                continue

            run_status = data.get("status")

            if run_status in _TERMINAL_STATUSES:
                if run_status == "COMPLETED":
                    status = "success"
                    error = None
                elif run_status == "PAUSED":
                    status = "paused"
                    error = None
                elif run_status == "CANCELLED":
                    status = "failed"
                    error = data.get("error") or "Run was cancelled"
                else:
                    status = "failed"
                    error = data.get("error") or f"Run failed with status {run_status}"

                # Extract input, output, and requirements from RunOutput
                run_input = data.get("input") if isinstance(data.get("input"), dict) else None
                run_output = self._extract_output(data)
                run_requirements = self._extract_requirements(data) if run_status == "PAUSED" else None

                return {
                    "status": status,
                    "status_code": resp.status_code,
                    "error": error,
                    "run_id": run_id,
                    "session_id": session_id,
                    "input": run_input,
                    "output": run_output,
                    "requirements": run_requirements,
                }

            await asyncio.sleep(self.poll_interval)

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_output(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Build a structured output dict from RunOutput data."""
        content = data.get("content")
        if content is None:
            return None
        return {
            "content": content,
            "content_type": data.get("content_type"),
        }

    @staticmethod
    def _extract_requirements(data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Extract HITL requirements from RunOutput data."""
        raw = data.get("requirements")
        if raw and isinstance(raw, list):
            return raw
        return None
