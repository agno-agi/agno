"""Trigger executor -- starts the run of one stored event and follows it to the end."""

import asyncio
import inspect
import time
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import quote

from agno.db.schemas.scheduler import RUN_ENDPOINT_RE, SCHEDULE_OWNER_HEADER, Schedule, build_run_endpoint
from agno.db.schemas.triggers import (
    CODE_MANAGED,
    EVENT_FAILED,
    EVENT_IGNORED,
    EVENT_PAUSED,
    EVENT_PENDING,
    EVENT_SKIPPED,
    EVENT_SUCCESS,
)
from agno.scheduler.executor import ScheduleExecutor, terminal_run_status
from agno.triggers.source import render_input
from agno.triggers.trigger import TriggerRun
from agno.utils.log import log_debug, log_error

# Set on a stored event whose payload did not show that the sender may start a run. The source is
# asked when the event is claimed, never while the delivery is being answered.
CHECK_SENDER_KEY = "check_sender"

# Called with the run id and session id as soon as a run is accepted.
_on_accepted: ContextVar[Optional[Callable[[str, str], Awaitable[None]]]] = ContextVar(
    "trigger_run_accepted", default=None
)


async def acall_db(db: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    """Call a storage method on a sync or an async adapter without holding the event loop."""
    fn = getattr(db, method)
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


async def _run_step(function: Callable[..., Any], *args: Any) -> Any:
    """Call a trigger's own function. A sync one runs on a worker thread, so a slow one holds nothing up."""
    if inspect.iscoroutinefunction(function):
        return await function(*args)
    result = await asyncio.to_thread(function, *args)
    if inspect.isawaitable(result):
        result = await result
    return result


def _name(function: Any) -> str:
    return getattr(function, "__name__", None) or type(function).__name__


class TriggerExecutor(ScheduleExecutor):
    """Start the run a stored event asks for, on the target's own run endpoint, and record how it ends.

    The run is started and followed the way a schedule's is: submitted in the background with the
    internal token, then polled until it finishes. The worker renews its claim on the event for as
    long as it follows the run, so a long run is never mistaken for an abandoned one.
    """

    def __init__(
        self,
        base_url: str,
        internal_service_token: str,
        timeout: int = 3600,
        poll_interval: int = 30,
        renew_interval: float = 30,
    ) -> None:
        super().__init__(
            base_url=base_url,
            internal_service_token=internal_service_token,
            timeout=timeout,
            poll_interval=poll_interval,
        )
        self.renew_interval = renew_interval

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
        # The run is accepted: record it on the event before following it, so a worker that takes
        # the event over knows which run to look at.
        accepted = _on_accepted.get()
        if accepted is not None:
            await accepted(run_id, session_id)
        return await super()._poll_run(client, headers, resource_type, resource_id, run_id, session_id, timeout_seconds)

    async def execute_event(self, row: Dict[str, Any], db: Any, runtime: Any) -> Dict[str, Any]:
        """Handle one claimed event and return its row as recorded.

        Args:
            row: The event as ``claim_trigger_event`` returned it.
            db: The DB adapter instance (must have trigger methods).
            runtime: Where the declared sources and triggers are found.
        """
        event_id, claim = row["id"], row["claimed_by"]
        renewal = asyncio.create_task(self._renew(db, event_id, claim))
        try:
            return await self._handle(row, db, runtime)
        except asyncio.CancelledError:
            # The process is stopping. Hand the event back so another worker, or this one after a
            # restart, runs it without waiting for the claim to go stale.
            try:
                await acall_db(
                    db,
                    "update_trigger_event",
                    event_id,
                    held_by=claim,
                    status=EVENT_PENDING,
                    claimed_by=None,
                    claimed_at=None,
                )
            except Exception as exc:
                log_debug(f"Trigger event {event_id} could not be released on shutdown: {exc}")
            raise
        finally:
            renewal.cancel()

    async def _renew(self, db: Any, event_id: str, claim: str) -> None:
        """Renew the claim until the event is finished or another worker holds it."""
        while True:
            await asyncio.sleep(self.renew_interval)
            try:
                if not await acall_db(db, "renew_trigger_event_claim", event_id, claim):
                    return
            except Exception as exc:
                log_debug(f"Trigger event {event_id}: claim renewal failed: {exc}")

    async def _handle(self, row: Dict[str, Any], db: Any, runtime: Any) -> Dict[str, Any]:
        event_id, claim = row["id"], row["claimed_by"]

        async def finish(status: str, **fields: Any) -> Dict[str, Any]:
            updates = {"status": status, "completed_at": int(time.time()), **fields}
            # Guarded by the claim: a worker that lost the event writes nothing over the new holder.
            if await acall_db(db, "update_trigger_event", event_id, held_by=claim, **updates) is None:
                log_debug(f"Trigger event {event_id} is held by another worker; its result was not recorded")
            return {**row, **updates}

        trigger = await acall_db(db, "get_trigger", row["trigger_id"])
        if trigger is None:
            return await finish(EVENT_SKIPPED, reason="the trigger no longer exists")
        if not trigger.get("enabled"):
            return await finish(EVENT_SKIPPED, reason="the trigger is disabled")
        source = runtime.sources.get(row["source_id"])
        if source is None:
            return await finish(EVENT_FAILED, error=f"source {row['source_id']} is not declared on this AgentOS")

        stored = row.get("event") or {}
        event = source.load(stored)

        if stored.get(CHECK_SENDER_KEY):
            try:
                refusal = await source.asender_refusal(event)
            except Exception as exc:
                refusal = f"the sender's access could not be checked: {exc}"
            if refusal:
                return await finish(EVENT_IGNORED, reason=refusal)

        # prepare and on_complete are code: only a trigger declared in code has them.
        declared = runtime.declared.get(trigger["name"]) if trigger.get("managed_by") == CODE_MANAGED else None
        instruction = trigger["input"]
        if declared is not None and declared.prepare is not None:
            step = _name(declared.prepare)
            try:
                outcome = await _run_step(declared.prepare, event)
            except Exception as exc:
                log_error(f"Trigger '{trigger['name']}': prepare {step} raised for event {event_id}: {exc}")
                return await finish(EVENT_FAILED, error=f"prepare {step} raised: {exc}")
            if outcome is False:
                return await finish(EVENT_SKIPPED, reason=f"prepare {step} returned False")
            if isinstance(outcome, str):
                instruction = outcome

        metadata = {
            "trigger_id": trigger["id"],
            "trigger_name": trigger["name"],
            "event_id": event_id,
            "source": row["source_id"],
            "event_kind": row["kind"],
            **source.run_metadata(event),
        }
        payload = {
            **(trigger.get("payload") or {}),
            "message": render_input(instruction, source.type, row["kind"], source.describe(event)),
            "metadata": metadata,
        }
        if row.get("session_id"):
            payload["session_id"] = row["session_id"]
        # The run is fired through the schedule path: this object carries the call, and is never stored.
        call = Schedule(
            id=trigger["id"],
            name=trigger["name"],
            cron_expr="",
            endpoint=build_run_endpoint(trigger["target_type"], trigger["target_id"]),
            payload=payload,
            timeout_seconds=trigger.get("timeout_seconds") or self.timeout,
            user_id=trigger.get("user_id"),
        )

        async def accepted(run_id: str, session_id: str) -> None:
            await acall_db(db, "update_trigger_event", event_id, held_by=claim, run_id=run_id, session_id=session_id)

        # An earlier claim may already have started a run for this event.
        result = await self._recorded_run(call, row) if row.get("run_id") else None
        max_attempts = max(1, int(trigger.get("max_retries") or 0) + 1)
        retry_delay = trigger.get("retry_delay_seconds")
        retry_delay = 60 if retry_delay is None else retry_delay
        attempt = 0
        while result is None or (result["status"] == EVENT_FAILED and attempt < max_attempts):
            if result is not None:
                log_debug(f"Trigger '{trigger['name']}': retrying event {event_id} in {retry_delay}s")
                await asyncio.sleep(retry_delay)
            attempt += 1
            await acall_db(db, "update_trigger_event", event_id, held_by=claim, attempt=attempt)
            token = _on_accepted.set(accepted)
            try:
                result = await self._call_endpoint(call)
            except Exception as exc:
                log_error(f"Trigger '{trigger['name']}': event {event_id} attempt {attempt} failed: {exc}")
                result = {"status": EVENT_FAILED, "error": str(exc)}
            finally:
                _on_accepted.reset(token)

        recorded: Dict[str, Any] = {
            "status_code": result.get("status_code"),
            "run_id": result.get("run_id") or row.get("run_id"),
            "session_id": result.get("session_id") or row.get("session_id"),
            "error": result.get("error"),
            "input": result.get("input"),
            "output": result.get("output"),
            "requirements": result.get("requirements"),
        }
        if declared is not None and declared.on_complete is not None:
            step = _name(declared.on_complete)
            run = TriggerRun(
                status=result["status"],
                trigger_name=trigger["name"],
                event_id=event_id,
                attempt=max(attempt, 1),
                run_id=recorded["run_id"],
                session_id=recorded["session_id"],
                output=(result.get("output") or {}).get("content"),
                error=result.get("error"),
            )
            try:
                await _run_step(declared.on_complete, event, run)
            except Exception as exc:
                # The run already ended as it did; the failed step is recorded beside its status.
                log_error(f"Trigger '{trigger['name']}': on_complete {step} raised for event {event_id}: {exc}")
                recorded["reason"] = f"on_complete {step} raised: {exc}"
        return await finish(result["status"], **recorded)

    async def _recorded_run(self, call: Schedule, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The result of the run an earlier claim started, when that run completed or is waiting on a person.

        Any other run is not a result: one that was cancelled or failed most likely stopped with
        its worker, and one that is still going has nobody following it and is asked to stop.
        None is returned for those, so the event is run again.
        """
        match = RUN_ENDPOINT_RE.match(call.endpoint)
        if match is None:
            return None
        headers = {"Authorization": f"Bearer {self.internal_service_token}"}
        if call.user_id is not None:
            headers[SCHEDULE_OWNER_HEADER] = quote(call.user_id, safe="")
        client = await self._get_client()
        url = f"{self.base_url}/{match.group(1)}/{match.group(2)}/runs/{row['run_id']}"
        try:
            response = await client.request("GET", url, headers=headers, params={"session_id": row.get("session_id")})
            data = response.json() if response.status_code == 200 else None
        except Exception as exc:
            log_debug(f"Trigger event {row['id']}: its earlier run could not be read: {exc}")
            return None
        if not isinstance(data, dict):
            return None
        settled = terminal_run_status(data, False)
        if settled is None:
            try:
                await client.request("POST", f"{url}/cancel", headers=headers)
            except Exception as exc:
                log_debug(f"Trigger event {row['id']}: its earlier run could not be cancelled: {exc}")
            return None
        status, error = settled
        if status not in (EVENT_SUCCESS, EVENT_PAUSED):
            return None
        return {
            "status": status,
            "status_code": response.status_code,
            "error": error,
            "run_id": row["run_id"],
            "session_id": row.get("session_id"),
            "input": data.get("input") if isinstance(data.get("input"), dict) else None,
            "output": self._extract_output(data),
            "requirements": self._extract_requirements(data) if data.get("status") == "PAUSED" else None,
        }
