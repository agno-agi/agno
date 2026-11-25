"""Trigger executor -- starts the run of one stored event and follows it to the end."""

import asyncio
import inspect
import time
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import httpx

from agno.db.schemas.scheduler import RUN_ENDPOINT_RE, Schedule, build_run_endpoint
from agno.db.schemas.triggers import (
    CODE_MANAGED,
    EVENT_CANCELLED,
    EVENT_FAILED,
    EVENT_IGNORED,
    EVENT_PAUSED,
    EVENT_PENDING,
    EVENT_SKIPPED,
    EVENT_SUCCESS,
)
from agno.scheduler.executor import ScheduleExecutor, terminal_run_status
from agno.triggers.source import (
    CHECK_SENDER_KEY,
    CHECK_SENDER_SINCE_KEY,
    RUN_ENDPOINT_KEY,
    RUN_UNREAD_SINCE_KEY,
    SenderCheckFailed,
    render_input,
)
from agno.triggers.trigger import TriggerRun
from agno.utils.log import log_debug, log_error

# Raised when a request was never sent: no connection was made, so the app started nothing.
_NEVER_REACHED = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)

# Called with the run id and session id as soon as a run is accepted. False when the worker no
# longer holds the event.
_on_accepted: ContextVar[Optional[Callable[[str, str], Awaitable[bool]]]] = ContextVar(
    "trigger_run_accepted", default=None
)


class ClaimLost(Exception):
    """Another worker holds the event now. This worker starts nothing more and records nothing."""


class Deferred(Exception):
    """The event cannot be settled yet. It stays claimed, and is looked at again once the claim is stale."""


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

    The run is submitted the way a schedule's is: in the background, with the internal token and the
    authority saved with the trigger. From there the executor follows it itself. The worker renews
    its claim on the event for as long as it follows the run, so a long run is never mistaken for an
    abandoned one.

    One event starts one run. Once a run is accepted it is followed to its end, and a second one is
    submitted only when the first is known to have failed or been cancelled.
    """

    def __init__(
        self,
        base_url: str,
        internal_service_token: str,
        timeout: int = 3600,
        poll_interval: int = 30,
        renew_interval: float = 30,
        read_attempts: int = 4,
        read_backoff: float = 1.0,
        stop_grace_seconds: float = 30.0,
        sender_check_attempts: int = 4,
        sender_check_backoff: float = 2.0,
        sender_check_seconds: int = 3600,
    ) -> None:
        """
        Args:
            renew_interval: Seconds between renewals of the claim on an event being handled.
            read_attempts: How many times the run an earlier claim started is read before the event
                is left for a later attempt.
            read_backoff: Seconds before the second of those reads; doubled for each one after.
            stop_grace_seconds: How long a run that was asked to stop is watched for having stopped.
            sender_check_attempts: How many times a source is asked whether a sender may start a
                run before the event is left for a later attempt.
            sender_check_backoff: Seconds before the second of those questions; doubled for each one after.
            sender_check_seconds: How long a source that gives no answer is asked before the event fails.
        """
        super().__init__(
            base_url=base_url,
            internal_service_token=internal_service_token,
            timeout=timeout,
            poll_interval=poll_interval,
        )
        self.renew_interval = renew_interval
        self.read_attempts = read_attempts
        self.read_backoff = read_backoff
        self.stop_grace_seconds = stop_grace_seconds
        self.sender_check_attempts = sender_check_attempts
        self.sender_check_backoff = sender_check_backoff
        self.sender_check_seconds = sender_check_seconds

    # --- Following a run ---

    def _said(self, error: Any) -> str:
        """What an error said, fit to be stored on an event or logged.

        The first line only: a database error carries its statement and parameters on the lines
        after it. And never this executor's token, which an HTTP library quotes when it refuses
        a header.
        """
        lines = str(error).strip().splitlines()
        text = lines[0] if lines else type(error).__name__
        token = self.internal_service_token
        if token:
            text = text.replace(token, "[internal token]").replace(token.strip(), "[internal token]")
        return text[:500]

    def _own_headers(self) -> Dict[str, str]:
        """Headers for reading a run and asking it to stop.

        The authority saved with a trigger decides what the run may do. It does not decide whether the
        executor may follow the run it started, so these requests carry the executor's token alone.
        """
        return {"Authorization": f"Bearer {self.internal_service_token}"}

    def _run_url(self, resource_type: str, resource_id: str, run_id: str) -> str:
        return f"{self.base_url}/{resource_type}/{resource_id}/runs/{run_id}"

    async def _read_run(self, url: str, session_id: Optional[str]) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        """Read a run once. The HTTP status, and the run when the answer held one."""
        client = await self._get_client()
        try:
            response = await client.request("GET", url, headers=self._own_headers(), params={"session_id": session_id})
        except Exception as exc:
            log_debug(f"Run at {url} could not be read: {self._said(exc)}")
            return None, None
        if response.status_code != 200:
            return response.status_code, None
        try:
            data = response.json()
        except ValueError:
            return response.status_code, None
        return response.status_code, data if isinstance(data, dict) else None

    async def _read_run_retrying(
        self, url: str, session_id: Optional[str]
    ) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        """Read a run, trying again after a failed read. The last answer."""
        status_code: Optional[int] = None
        for attempt in range(max(1, self.read_attempts)):
            if attempt:
                await asyncio.sleep(self.read_backoff * 2 ** (attempt - 1))
            status_code, data = await self._read_run(url, session_id)
            if data is not None:
                return status_code, data
        return status_code, None

    async def _request_stop(self, url: str, session_id: Optional[str]) -> None:
        client = await self._get_client()
        try:
            await client.request(
                "POST", f"{url}/cancel", headers=self._own_headers(), params={"session_id": session_id}
            )
        except Exception as exc:
            log_debug(f"Run at {url} could not be asked to stop: {self._said(exc)}")

    async def _stop_run(self, url: str, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Ask a run to stop and watch for it. The run as it ended, or None when it was not seen to end."""
        await self._request_stop(url, session_id)
        deadline = time.monotonic() + self.stop_grace_seconds
        while True:
            _, data = await self._read_run(url, session_id)
            if data is not None and terminal_run_status(data, False) is not None:
                return data
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(min(self.poll_interval, 1.0))

    def _result(self, data: Dict[str, Any], run_id: str, session_id: Optional[str]) -> Dict[str, Any]:
        """The result of a run that has ended."""
        settled = terminal_run_status(data, False)
        assert settled is not None
        status, error = settled
        return {
            "status": status,
            "status_code": 200,
            "error": error,
            "run_id": run_id,
            "session_id": session_id,
            "input": data.get("input") if isinstance(data.get("input"), dict) else None,
            "output": self._extract_output(data),
            "requirements": self._extract_requirements(data) if data.get("status") == "PAUSED" else None,
        }

    @staticmethod
    def _not_run_again(run_id: str, session_id: Optional[str], error: str) -> Dict[str, Any]:
        """A failed result for a run whose end is not known: nothing may be submitted in its place."""
        return {
            "status": EVENT_FAILED,
            "status_code": None,
            "error": f"{error}; the event was not run again",
            "run_id": run_id,
            "session_id": session_id,
            "input": None,
            "output": None,
            "requirements": None,
            "resubmit": False,
        }

    async def _follow_run(
        self,
        resource_type: str,
        resource_id: str,
        run_id: str,
        session_id: Optional[str],
        timeout_seconds: int,
        remaining: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Follow an accepted run until it ends or its timeout passes.

        A read that fails is tried again at the next poll: a run that was accepted is never answered
        with a second one. When the timeout passes the run is asked to stop. One that is seen to stop
        has failed and may be retried; one that is not may still be going, and is not.

        Args:
            remaining: Seconds of the timeout that are left, for a run that was started earlier.
        """
        url = self._run_url(resource_type, resource_id, run_id)
        deadline = time.monotonic() + (timeout_seconds if remaining is None else remaining)
        while True:
            _, data = await self._read_run(url, session_id)
            if data is not None and terminal_run_status(data, False) is not None:
                return self._result(data, run_id, session_id)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(self.poll_interval, remaining))

        stopped = await self._stop_run(url, session_id)
        if stopped is None:
            return self._not_run_again(
                run_id, session_id, f"Run {run_id} did not stop after its timeout of {timeout_seconds}s"
            )
        result = self._result(stopped, run_id, session_id)
        if result["status"] in (EVENT_SUCCESS, EVENT_PAUSED):
            # It ended on its own while it was being asked to stop.
            return result
        return {
            **result,
            "status": EVENT_FAILED,
            "status_code": None,
            "error": f"Run {run_id} was stopped after its timeout of {timeout_seconds}s",
        }

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
        if accepted is not None and not await accepted(run_id, session_id):
            # The event was taken by another worker while this run was being submitted. That worker
            # starts its own, so this one is asked to stop.
            await self._request_stop(self._run_url(resource_type, resource_id, run_id), session_id)
            raise ClaimLost()
        try:
            return await self._follow_run(resource_type, resource_id, run_id, session_id, timeout_seconds)
        except (ClaimLost, Deferred):
            raise
        except Exception as exc:
            # Whatever went wrong here, the run was accepted: nothing is submitted in its place.
            log_error(f"Run {run_id} could not be followed: {self._said(exc)}")
            return self._not_run_again(run_id, session_id, f"Run {run_id} could not be followed: {self._said(exc)}")

    async def _recorded_run(self, endpoint: str, row: Dict[str, Any], timeout_seconds: int) -> Optional[Dict[str, Any]]:
        """What the run an earlier claim started means for this event.

        A run that is still going is followed to its end by this worker, as the worker that started
        it would have followed it: nothing is submitted while it may be alive, and it is asked to
        stop only when its timeout passes. How it ends is the result.

        A run that had already ended is how the event's attempt ended, with one exception. A run
        that was cancelled stopped with its worker, as the runs in flight do when a process shuts
        down: None is returned for it, and the event is run again.

        Raises:
            Deferred: The run could not be read, so nothing is known about it. The event keeps its
                claim and nothing is submitted.
        """
        match = RUN_ENDPOINT_RE.match(endpoint)
        if match is None:
            return None
        run_id, session_id = row["run_id"], row.get("session_id")
        url = self._run_url(match.group(1), match.group(2), run_id)
        status_code, data = await self._read_run_retrying(url, session_id)
        if data is None:
            if status_code == 404:
                return self._not_run_again(
                    run_id, session_id, f"Run {run_id}, started by an earlier worker, was not found"
                )
            raise Deferred(f"run {run_id}, started by an earlier worker, could not be read")
        if terminal_run_status(data, False) is None:
            # The timeout counts from when the run was started, not from when this worker found it.
            started_at = data.get("created_at")
            remaining = None
            if isinstance(started_at, (int, float)):
                remaining = max(0.0, started_at + timeout_seconds - time.time())
            return await self._follow_run(
                match.group(1), match.group(2), run_id, session_id, timeout_seconds, remaining=remaining
            )
        result = self._result(data, run_id, session_id)
        return None if result["status"] == EVENT_CANCELLED else result

    # --- Handling an event ---

    @staticmethod
    async def _waiting_since(db: Any, row: Dict[str, Any], key: str) -> int:
        """When this event first waited for the answer ``key`` names, in epoch seconds.

        The time is kept on the event itself, so the waiting has an end whichever worker takes
        the event up next.
        """
        stored = row.get("event") or {}
        since = stored.get(key)
        if isinstance(since, (int, float)):
            return int(since)
        since = int(time.time())
        marked = {**stored, key: since}
        if await acall_db(db, "update_trigger_event", row["id"], held_by=row["claimed_by"], event=marked) is None:
            raise ClaimLost()
        row["event"] = marked
        return since

    async def _sender_refusal(self, source: Any, event: Any, row: Dict[str, Any], db: Any) -> Optional[str]:
        """Ask the source whether the sender may start a run; the reason when they may not.

        Only an answer about the sender counts. A question that gets no answer is asked again, with
        a longer wait each time, for at most ``sender_check_seconds`` from the first one.

        Raises:
            SenderCheckFailed: The question cannot be asked as configured, or it went unanswered
                for the whole time allowed. The event fails.
            Deferred: The source gave no answer yet. The event keeps its claim, so the events
                behind it for the same key wait, and a later attempt asks again.
        """
        event_id = row["id"]
        error: Optional[Exception] = None
        for attempt in range(max(1, self.sender_check_attempts)):
            if attempt:
                await asyncio.sleep(self.sender_check_backoff * 2 ** (attempt - 1))
            try:
                return await source.asender_refusal(event)
            except SenderCheckFailed as exc:
                raise SenderCheckFailed(f"the sender's access could not be checked: {self._said(exc)}") from exc
            except Exception as exc:
                error = exc
                log_debug(f"Trigger event {event_id}: the sender's access could not be checked: {self._said(exc)}")

        since = await self._waiting_since(db, row, CHECK_SENDER_SINCE_KEY)
        if time.time() - since >= self.sender_check_seconds:
            raise SenderCheckFailed(
                f"the sender's access could not be checked for {self.sender_check_seconds}s: {self._said(error)}"
            )
        raise Deferred(f"the sender's access could not be checked: {self._said(error)}")

    async def execute_event(self, row: Dict[str, Any], db: Any, runtime: Any) -> Dict[str, Any]:
        """Handle one claimed event and return its row as recorded.

        Args:
            row: The event as ``claim_trigger_event`` returned it.
            db: The DB adapter instance (must have trigger methods).
            runtime: Where the declared sources and triggers are found.
        """
        event_id, claim = row["id"], row["claimed_by"]
        # What the handling has in flight, for a worker that is stopped part way through.
        progress: Dict[str, Any] = {}
        renewal = asyncio.create_task(self._renew(db, event_id, claim))
        try:
            return await self._handle(row, db, runtime, progress)
        except ClaimLost:
            log_debug(f"Trigger event {event_id} is held by another worker; this one stopped")
            return row
        except Deferred as exc:
            # The event keeps this claim, so nothing takes it until the claim is stale.
            log_debug(f"Trigger event {event_id} waits for a later attempt: {exc}")
            try:
                await acall_db(db, "update_trigger_event", event_id, held_by=claim, error=f"waiting: {exc}")
            except Exception as update_exc:
                log_debug(f"Trigger event {event_id}: the reason it waits was not recorded: {update_exc}")
            return row
        except Exception as exc:
            # What raised here would raise again. Left as it is, the event would be taken up each
            # time its claim went stale and fail the same way, with every later event for its key
            # waiting behind it. So it ends, with what was raised.
            said = f"{type(exc).__name__}: {self._said(exc)}"
            log_error(f"Trigger event {event_id} could not be handled: {said}")
            ended = {
                "status": EVENT_FAILED,
                "completed_at": int(time.time()),
                "error": f"the event could not be handled: {said}",
            }
            try:
                await acall_db(db, "update_trigger_event", event_id, held_by=claim, **ended)
            except Exception as update_exc:
                # Storage is not answering either. The claim goes stale and the event is tried again.
                log_error(f"Trigger event {event_id}: its failure was not recorded: {self._said(update_exc)}")
            return {**row, **ended}
        except asyncio.CancelledError:
            await self._give_up(db, row, progress)
            raise
        finally:
            renewal.cancel()

    async def _give_up(self, db: Any, row: Dict[str, Any], progress: Dict[str, Any]) -> None:
        """Leave an event because the process is stopping."""
        event_id, claim = row["id"], row["claimed_by"]
        unrecorded = progress.get("unrecorded")
        if progress.get("in_flight"):
            # The run request went out and was not answered. The app may have accepted it, so the
            # event cannot be handed back: whoever took it would start a second run.
            fields: Dict[str, Any] = {
                "status": EVENT_FAILED,
                "completed_at": int(time.time()),
                "error": "the worker stopped while the run request was in flight, and the run may have been "
                "accepted; the event was not run again",
            }
        else:
            # Hand the event back so another worker, or this one after a restart, takes it without
            # waiting for the claim to go stale.
            fields = {"status": EVENT_PENDING, "claimed_by": None, "claimed_at": None}
            if unrecorded is not None:
                # The run was accepted and its id is not on the event yet. Name it now, so the
                # worker that takes the event follows this run and starts no other.
                fields.update(run_id=unrecorded[0], session_id=unrecorded[1])
        try:
            await acall_db(db, "update_trigger_event", event_id, held_by=claim, **fields)
        except Exception as exc:
            log_debug(f"Trigger event {event_id} could not be released on shutdown: {self._said(exc)}")
            if unrecorded is not None:
                # Nothing names the run, so the next worker would start one beside it.
                await self._request_stop(unrecorded[2], unrecorded[1])

    async def _renew(self, db: Any, event_id: str, claim: str) -> None:
        """Renew the claim until the event is finished or another worker holds it."""
        while True:
            await asyncio.sleep(self.renew_interval)
            try:
                if not await acall_db(db, "renew_trigger_event_claim", event_id, claim):
                    return
            except Exception as exc:
                log_debug(f"Trigger event {event_id}: claim renewal failed: {exc}")

    async def _handle(self, row: Dict[str, Any], db: Any, runtime: Any, progress: Dict[str, Any]) -> Dict[str, Any]:
        event_id, claim = row["id"], row["claimed_by"]

        async def finish(status: str, **fields: Any) -> Dict[str, Any]:
            updates = {"status": status, "completed_at": int(time.time()), **fields}
            # Guarded by the claim: a worker that lost the event writes nothing over the new holder.
            if await acall_db(db, "update_trigger_event", event_id, held_by=claim, **updates) is None:
                log_debug(f"Trigger event {event_id} is held by another worker; its result was not recorded")
            return {**row, **updates}

        trigger = await acall_db(db, "get_trigger", row["trigger_id"])
        source = runtime.sources.get(row["source_id"])
        endpoint = build_run_endpoint(trigger["target_type"], trigger["target_id"]) if trigger is not None else None
        timeout_seconds = (trigger or {}).get("timeout_seconds") or self.timeout
        max_attempts = max(1, int((trigger or {}).get("max_retries") or 0) + 1)
        retry_delay = (trigger or {}).get("retry_delay_seconds")
        retry_delay = 60 if retry_delay is None else retry_delay

        # An earlier claim may have started a run for this event. It is read before anything else,
        # and where it was started: the trigger may have been turned off or pointed elsewhere since,
        # and an event that already has its run is not checked, prepared or started a second time.
        result: Optional[Dict[str, Any]] = None
        attempt = 0
        run_endpoint = (row.get("event") or {}).get(RUN_ENDPOINT_KEY) or endpoint
        if row.get("run_id") and run_endpoint:
            try:
                result = await self._recorded_run(run_endpoint, row, timeout_seconds)
            except Deferred:
                # The run cannot be read. That may pass, so the event waits; but not for longer
                # than the run itself was given, and then nothing is started in its place.
                since = await self._waiting_since(db, row, RUN_UNREAD_SINCE_KEY)
                if time.time() - since < timeout_seconds:
                    raise
                result = self._not_run_again(
                    row["run_id"],
                    row.get("session_id"),
                    f"Run {row['run_id']}, started by an earlier worker, could not be read for {timeout_seconds}s",
                )
            # The recorded run was the attempt the event counts, unless it was cancelled with its
            # worker: taking an event over earns no retries beyond the ones the trigger allows.
            attempt = int(row.get("attempt") or 0)
            if result is None:
                attempt = max(attempt - 1, 0)

        # Only a run known to have failed is tried again, and only as often as the trigger allows.
        def retried(outcome: Dict[str, Any]) -> bool:
            return outcome["status"] == EVENT_FAILED and outcome.get("resubmit") is not False and attempt < max_attempts

        # Why no run may be started now, when none may.
        blocked: Optional[Tuple[str, str, str]] = None
        if trigger is None:
            blocked = (EVENT_SKIPPED, "reason", "the trigger no longer exists")
        elif not trigger.get("enabled"):
            blocked = (EVENT_SKIPPED, "reason", "the trigger is disabled")
        elif source is None:
            blocked = (EVENT_FAILED, "error", f"source {row['source_id']} is not declared on this AgentOS")

        starts = result is None or retried(result)
        if starts and blocked is not None:
            if result is None:
                return await finish(blocked[0], **{blocked[1]: blocked[2]})
            # The run this event had has failed and none may be started in its place: its failure stands.
            starts = False

        stored = row.get("event") or {}
        event = source.load(stored) if source is not None else None
        # prepare and on_complete are code: only a trigger declared in code has them.
        declared = None
        if trigger is not None and source is not None and trigger.get("managed_by") == CODE_MANAGED:
            declared = runtime.declared.get(trigger["name"])

        if starts:
            assert trigger is not None and source is not None and endpoint is not None
            if row["kind"] not in (trigger.get("events") or []):
                # The event only continues a conversation. Events for one key are handled in the
                # order they arrived, so the one that opens the conversation is behind us by now:
                # if it started no run, there is nothing to continue.
                _, started = await acall_db(
                    db,
                    "get_trigger_events",
                    trigger_id=trigger["id"],
                    event_key=row.get("event_key"),
                    started_run=True,
                    limit=1,
                )
                if not started:
                    key = row.get("event_key") or "this event"
                    reason = f"{row['kind']} continues a conversation, and {trigger['name']} started none for {key}"
                    return await finish(EVENT_IGNORED, reason=reason, event=source.trim(stored))

            if stored.get(CHECK_SENDER_KEY):
                try:
                    refusal = await self._sender_refusal(source, event, row, db)
                except SenderCheckFailed as exc:
                    # Nobody was refused: the question could not be answered. That is a failure.
                    return await finish(EVENT_FAILED, error=str(exc))
                if refusal:
                    # The text was kept for as long as the event might run. It will not.
                    return await finish(EVENT_IGNORED, reason=refusal, event=source.trim(stored))

            instruction = trigger["input"]
            if declared is not None and declared.prepare is not None:
                step = _name(declared.prepare)
                try:
                    outcome = await _run_step(declared.prepare, event)
                except Exception as exc:
                    log_error(
                        f"Trigger '{trigger['name']}': prepare {step} raised for event {event_id}: {self._said(exc)}"
                    )
                    return await finish(EVENT_FAILED, error=f"prepare {step} raised: {self._said(exc)}")
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
            # The run is submitted through the schedule path: this object carries the call, and is never stored.
            call = Schedule(
                id=trigger["id"],
                name=trigger["name"],
                cron_expr="",
                endpoint=endpoint,
                payload=payload,
                timeout_seconds=timeout_seconds,
                user_id=trigger.get("user_id"),
            )

            run_target = RUN_ENDPOINT_RE.match(endpoint)

            async def accepted(run_id: str, session_id: str) -> bool:
                # The request was answered: a run exists. Until its id is on the event, a worker
                # that is stopped here must still be able to name it.
                run_url = self._run_url(run_target.group(1), run_target.group(2), run_id) if run_target else ""
                progress["unrecorded"] = (run_id, session_id, run_url)
                progress["in_flight"] = False
                # Where the run was started goes on the event with it: the trigger can change later.
                marked = {**(row.get("event") or {}), RUN_ENDPOINT_KEY: endpoint}
                for tried in range(3):
                    try:
                        held = await acall_db(
                            db,
                            "update_trigger_event",
                            event_id,
                            held_by=claim,
                            run_id=run_id,
                            session_id=session_id,
                            event=marked,
                        )
                    except Exception as exc:
                        log_error(
                            f"Trigger event {event_id}: run {run_id} could not be recorded on it: {self._said(exc)}"
                        )
                        await asyncio.sleep(self.read_backoff * (tried + 1))
                        continue
                    progress.pop("unrecorded", None)
                    if held is not None:
                        row["event"] = marked
                    return held is not None
                # The run is going and this worker follows it. Only the record of it is missing.
                return True

            while True:
                if result is not None:
                    log_debug(f"Trigger '{trigger['name']}': retrying event {event_id} in {retry_delay}s")
                    await asyncio.sleep(retry_delay)
                attempt += 1
                # Only the worker that holds the event starts its run.
                if await acall_db(db, "update_trigger_event", event_id, held_by=claim, attempt=attempt) is None:
                    raise ClaimLost()
                # From here until the app answers, nobody knows whether a run exists.
                progress["in_flight"] = True
                token = _on_accepted.set(accepted)
                try:
                    result = await self._call_endpoint(call)
                except (ClaimLost, Deferred):
                    progress["in_flight"] = False
                    raise
                except _NEVER_REACHED as exc:
                    # No connection was made, so the app started nothing: this attempt may be retried.
                    said = self._said(exc)
                    log_error(f"Trigger '{trigger['name']}': event {event_id} attempt {attempt} failed: {said}")
                    result = {"status": EVENT_FAILED, "error": said}
                except Exception as exc:
                    # The request went out and no answer came back. The app may have accepted the
                    # run, and nothing here can tell: sending it again could start a second one.
                    said = f"{type(exc).__name__}: {self._said(exc)}"
                    log_error(f"Trigger '{trigger['name']}': event {event_id} attempt {attempt} got no answer: {said}")
                    result = {
                        "status": EVENT_FAILED,
                        "error": f"the run request got no answer and may have been accepted ({said}); "
                        "the event was not run again",
                        "resubmit": False,
                    }
                finally:
                    _on_accepted.reset(token)
                progress["in_flight"] = False
                if not retried(result):
                    break

        # Either the recorded run gave a result, or a run was started and gave one.
        assert result is not None
        recorded: Dict[str, Any] = {
            "status_code": result.get("status_code"),
            "run_id": result.get("run_id") or row.get("run_id"),
            "session_id": result.get("session_id") or row.get("session_id"),
            "error": result.get("error"),
            "input": result.get("input"),
            "output": result.get("output"),
            "requirements": result.get("requirements"),
        }
        if declared is not None and declared.on_complete is not None and event is not None and trigger is not None:
            # Only the worker that holds the event reports how its run ended.
            if not await acall_db(db, "renew_trigger_event_claim", event_id, claim):
                raise ClaimLost()
            step = _name(declared.on_complete)
            run = TriggerRun(
                status=result["status"],
                trigger_name=trigger["name"],
                event_id=event_id,
                attempt=max(attempt, int(row.get("attempt") or 0), 1),
                run_id=recorded["run_id"],
                session_id=recorded["session_id"],
                output=(result.get("output") or {}).get("content"),
                error=result.get("error"),
            )
            try:
                await _run_step(declared.on_complete, event, run)
            except Exception as exc:
                # The run already ended as it did; the failed step is recorded beside its status.
                log_error(
                    f"Trigger '{trigger['name']}': on_complete {step} raised for event {event_id}: {self._said(exc)}"
                )
                recorded["reason"] = f"on_complete {step} raised: {self._said(exc)}"
        return await finish(result["status"], **recorded)
