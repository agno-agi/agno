"""Schedule executor -- fires HTTP requests for due schedules."""

import asyncio
import inspect
import json
import re
import time
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from agno.db.schemas.scheduler import (
    STUDIO_SCHEDULE_ACTOR_HEADER,
    Schedule,
    encode_studio_schedule_actor_id,
    is_studio_managed_schedule,
    is_valid_studio_schedule_actor_id,
)
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

# Schedule claims use the same default five-minute lease as the official DB
# adapters. The executor renews a claimed lease well before it can be treated
# as stale by another poller.
_DEFAULT_LOCK_GRACE_SECONDS = 300

# Internal result key used to distinguish a request that is safe to submit
# again from a background run that has already been accepted by AgentOS.
_RETRYABLE_RESULT_KEY = "_retryable"


def match_run_endpoint(endpoint: str, method: str) -> Optional[re.Match[str]]:
    """Return the canonical run-route match for a POST endpoint."""
    if method.upper() != "POST":
        return None
    return _RUN_ENDPOINT_RE.fullmatch(endpoint)


def is_run_endpoint(endpoint: str, method: str) -> bool:
    """Return whether *endpoint* is a canonical AgentOS run route."""
    return match_run_endpoint(endpoint, method) is not None


def _to_form_value(v: Any) -> str:
    """Convert a payload value to a JSON-safe form string."""
    if v is None:
        return ""
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
        lock_grace_seconds: int = _DEFAULT_LOCK_GRACE_SECONDS,
    ) -> None:
        if httpx is None:
            raise ImportError("`httpx` not installed. Please install it using `pip install httpx`")
        self.base_url = base_url.rstrip("/")
        self.internal_service_token = internal_service_token
        self.timeout = timeout
        self.poll_interval = poll_interval
        if lock_grace_seconds <= 0:
            raise ValueError("lock_grace_seconds must be greater than zero")
        self.lock_grace_seconds = lock_grace_seconds
        self._heartbeat_interval = max(0.1, lock_grace_seconds / 3)
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

    @staticmethod
    async def _call_db(db: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Call a native async adapter directly and offload a sync adapter."""
        method = getattr(db, method_name, None)
        if method is None:
            raise NotImplementedError(f"Database does not support {method_name}")
        if asyncio.iscoroutinefunction(method):
            result = await method(*args, **kwargs)
        else:
            result = await asyncio.to_thread(method, *args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _log_run_persistence_failure(
        schedule_id: Optional[str],
        attempt: int,
        studio_managed: bool,
        exc: Exception,
    ) -> None:
        """Log a run-record failure without exposing Studio-owned details."""
        if studio_managed:
            log_error(f"Failed to persist Studio schedule {schedule_id} attempt {attempt}")
        else:
            log_error(f"Failed to persist schedule {schedule_id} attempt {attempt}: {exc}")

    async def _heartbeat_claim(
        self,
        db: Any,
        schedule_id: str,
        worker_id: str,
        lease: Dict[str, Any],
        stop: asyncio.Event,
    ) -> None:
        """Renew one fenced claim until execution finishes or ownership is lost."""
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._heartbeat_interval)
                return
            except asyncio.TimeoutError:
                pass

            locked_at = lease["locked_at"]
            try:
                renewed_at = await self._call_db(
                    db,
                    "renew_schedule_claim",
                    schedule_id,
                    worker_id=worker_id,
                    locked_at=locked_at,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                log_error(f"Failed to renew schedule claim {schedule_id}")
                continue

            if not isinstance(renewed_at, int) or isinstance(renewed_at, bool):
                log_error(f"Lost ownership of schedule claim {schedule_id}")
                return
            lease["locked_at"] = renewed_at

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
        studio_managed = is_studio_managed_schedule(sched)

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
        lease: Dict[str, Any] = {"locked_at": sched.locked_at}
        heartbeat_stop: Optional[asyncio.Event] = None
        heartbeat_task: Optional[asyncio.Task[None]] = None

        try:
            schedule_id = sched.id
            scheduler_api_version = getattr(db, "scheduler_api_version", 1)
            if (
                isinstance(scheduler_api_version, int)
                and scheduler_api_version >= 2
                and sched.locked_by is not None
                and sched.locked_at is not None
                and callable(getattr(db, "renew_schedule_claim", None))
            ):
                heartbeat_stop = asyncio.Event()
                heartbeat_task = asyncio.create_task(
                    self._heartbeat_claim(db, schedule_id, sched.locked_by, lease, heartbeat_stop)
                )

            max_attempts = max(1, (sched.max_retries or 0) + 1)
            retry_delay = sched.retry_delay_seconds if sched.retry_delay_seconds is not None else 60
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

                await self._call_db(db, "create_schedule_run", run_dict)

                endpoint_retryable = True
                try:
                    result = await self._call_endpoint(sched)
                except Exception as exc:
                    last_status = "failed"
                    last_status_code = None
                    if studio_managed:
                        last_error = "Studio schedule execution failed"
                        log_error(f"Studio schedule {schedule_id} attempt {attempt} failed")
                    else:
                        last_error = str(exc)
                        log_error(f"Schedule {schedule_id} attempt {attempt} failed: {exc}")

                    failure_updates = {
                        "completed_at": int(time.time()),
                        "status": "failed",
                        "error": last_error,
                    }
                    try:
                        await self._call_db(db, "update_schedule_run", run_record_id, **failure_updates)
                    except Exception as persistence_exc:
                        self._log_run_persistence_failure(
                            schedule_id,
                            attempt,
                            studio_managed,
                            persistence_exc,
                        )
                else:
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
                    try:
                        await self._call_db(db, "update_schedule_run", run_record_id, **updates)
                    except Exception as persistence_exc:
                        self._log_run_persistence_failure(
                            schedule_id,
                            attempt,
                            studio_managed,
                            persistence_exc,
                        )
                    endpoint_retryable = bool(result.get(_RETRYABLE_RESULT_KEY, last_status == "failed"))

                # Persistence is deliberately outside the endpoint exception
                # boundary. A DB write failure after AgentOS accepted a run
                # must never turn that accepted outcome into a new submission.
                if last_status in ("success", "paused") or not endpoint_retryable:
                    break

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

        except asyncio.CancelledError as exc:
            if studio_managed:
                log_warning(f"Studio schedule {schedule_id} execution cancelled")
            else:
                log_warning(f"Schedule {schedule_id} execution cancelled: {exc}")
            if run_record_id is not None:
                cancel_updates: Dict[str, Any] = {
                    "completed_at": int(time.time()),
                    "status": "cancelled",
                    "error": "Execution cancelled during shutdown",
                }
                try:
                    await self._call_db(db, "update_schedule_run", run_record_id, **cancel_updates)
                except Exception:
                    pass
            raise

        finally:
            # Stop between renewals, or wait for an in-progress renewal to
            # publish its new fence before attempting the release.
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            if heartbeat_task is not None:
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    heartbeat_task.cancel()
                    raise

            # Always release the schedule lock so it doesn't stay stuck
            if release_schedule and schedule_id is not None:
                # A manual trigger is independent from the cron cursor. Its
                # claim marker is cleared by release_schedule, but the stored
                # next_run_at must remain untouched -- especially when stale
                # recovery happens after that cron occurrence became due.
                next_run_at = None
                if not sched.manual_trigger_claimed:
                    try:
                        next_run_at = compute_next_run(
                            sched.cron_expr,
                            sched.timezone or "UTC",
                        )
                    except Exception as exc:
                        if studio_managed:
                            log_warning(
                                f"Failed to compute next_run_at for Studio schedule {schedule_id}; "
                                "disabling it to prevent a stuck lock"
                            )
                        else:
                            log_warning(
                                f"Failed to compute next_run_at for schedule {schedule_id}; "
                                f"disabling it to prevent a stuck lock: {exc}"
                            )

                        try:
                            await self._call_db(db, "update_schedule", schedule_id, enabled=False)
                        except Exception as exc:
                            if studio_managed:
                                log_error(f"Failed to disable Studio schedule {schedule_id} after cron failure")
                            else:
                                log_error(f"Failed to disable schedule {schedule_id} after cron failure: {exc}")

                try:
                    release_kwargs: Dict[str, Any] = {"next_run_at": next_run_at}
                    scheduler_api_version = getattr(db, "scheduler_api_version", 1)
                    if (
                        isinstance(scheduler_api_version, int)
                        and scheduler_api_version >= 2
                        and sched.locked_by is not None
                        and sched.locked_at is not None
                    ):
                        # Fence release to the exact claim. A worker that wakes
                        # after its stale lock was recovered must not clear the
                        # replacement worker's lock or in-flight trigger marker.
                        release_kwargs.update(worker_id=sched.locked_by, locked_at=lease["locked_at"])
                    await self._call_db(db, "release_schedule", schedule_id, **release_kwargs)
                except Exception as exc:
                    if studio_managed:
                        log_error(f"Failed to release Studio schedule {schedule_id}")
                    else:
                        log_error(f"Failed to release schedule {schedule_id}: {exc}")

    # ------------------------------------------------------------------
    async def _call_endpoint(self, schedule: Schedule) -> Dict[str, Any]:
        """Make the HTTP call to the schedule's endpoint."""
        method = (schedule.method or "POST").upper()
        endpoint = schedule.endpoint
        payload = schedule.payload or {}
        timeout_seconds = schedule.timeout_seconds if schedule.timeout_seconds is not None else self.timeout
        url = f"{self.base_url}{endpoint}"

        match = match_run_endpoint(endpoint, method)
        run_endpoint = match is not None

        headers: Dict[str, str] = {
            "Authorization": f"Bearer {self.internal_service_token}",
        }

        if is_studio_managed_schedule(schedule):
            owner_actor_id = schedule.owner_actor_id
            expected_target_type = schedule.target_type
            expected_target_id = schedule.target_id
            if (
                not is_valid_studio_schedule_actor_id(owner_actor_id)
                or not run_endpoint
                or match is None
                or expected_target_type not in ("agent", "team", "workflow")
                or match.group(1) != f"{expected_target_type}s"
                or not isinstance(expected_target_id, str)
                or match.group(2) != expected_target_id
            ):
                raise RuntimeError("Studio schedule provenance is invalid")
            assert isinstance(owner_actor_id, str)
            headers[STUDIO_SCHEDULE_ACTOR_HEADER] = encode_studio_schedule_actor_id(owner_actor_id)

        client = await self._get_client()

        if run_endpoint and match is not None:
            # Optional form fields must be omitted when unset. Sending Python's
            # ``str(None)`` creates a real user/session id named "None".
            form_payload = {
                k: _to_form_value(v) for k, v in payload.items() if k not in ("stream", "background") and v is not None
            }
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
            _RETRYABLE_RESULT_KEY: status == "failed",
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

        try:
            resp = await client.request("POST", url, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Without an idempotency key a transport failure is ambiguous: the
            # server may have accepted the run before the connection failed.
            log_warning("Background run submission outcome is unknown")
            return {
                "status": "failed",
                "status_code": None,
                "error": "Background run submission outcome is unknown",
                "run_id": None,
                "session_id": None,
                "input": None,
                "output": None,
                "requirements": None,
                _RETRYABLE_RESULT_KEY: False,
            }

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
                _RETRYABLE_RESULT_KEY: True,
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
                # A 2xx response means AgentOS may already be executing the
                # run even if its acknowledgement cannot be decoded.
                _RETRYABLE_RESULT_KEY: False,
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
                _RETRYABLE_RESULT_KEY: False,
            }

        try:
            result = await self._poll_run(
                client,
                headers,
                resource_type,
                resource_id,
                run_id,
                session_id,
                timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log_error(f"Failed while polling submitted run {run_id}")
            result = {
                "status": "failed",
                "status_code": None,
                "error": f"Failed while polling submitted run {run_id}",
                "run_id": run_id,
                "session_id": session_id,
                "input": None,
                "output": None,
                "requirements": None,
            }
        result.setdefault(_RETRYABLE_RESULT_KEY, False)
        return result

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
                    _RETRYABLE_RESULT_KEY: False,
                }

            try:
                resp = await client.request(
                    "GET",
                    poll_url,
                    headers=headers,
                    params={"session_id": session_id},
                )
            except Exception:
                log_warning(f"Poll request failed for run {run_id}")
                await self._sleep_before_next_poll(deadline)
                continue

            if resp.status_code == 404:
                await self._sleep_before_next_poll(deadline)
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
                    _RETRYABLE_RESULT_KEY: False,
                }

            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError):
                log_warning(f"Invalid JSON in poll response for run {run_id}")
                await self._sleep_before_next_poll(deadline)
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
                    _RETRYABLE_RESULT_KEY: run_status == "ERROR",
                }

            await self._sleep_before_next_poll(deadline)

    async def _sleep_before_next_poll(self, deadline: float) -> None:
        """Throttle every non-terminal poll path without oversleeping its deadline."""
        remaining = max(0.0, deadline - time.monotonic())
        await asyncio.sleep(min(float(self.poll_interval), remaining))

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
