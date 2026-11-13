"""Super Agent in Slack: a mapped Slack user's Company authority, and Task results posted back to the thread."""

import asyncio
import time
from typing import Any, Dict, Optional, Tuple
from weakref import ReferenceType, ref

from agno.db.schemas.tasks import TASK_STATUS_MEANING
from agno.os.interfaces.slack.context import SlackContext
from agno.os.interfaces.slack.helpers import slack_delivery_kwargs, slack_error_code
from agno.os.interfaces.slack.security import resolve_principal_authorization
from agno.utils.log import log_debug, log_error, log_warning

# Slack message metadata event type that marks a Task attempt's result as posted
_RESULT_EVENT = "agno_task_result"
_RESULT_STATUSES = ("in_review", "done", "cancelled")
_SWEEP_SECONDS = 5.0
_RETRY_MIN = 5.0
_RETRY_MAX = 300.0
# Failed posts retried per Task attempt before it is given up, so one Task never holds the mark for good
_RETRY_LIMIT = 10
# Slack error codes that fail the same way on every attempt: the thread is gone or closed to this app
_PERMANENT_SLACK_ERRORS = frozenset({"channel_not_found", "is_archived", "not_in_channel", "thread_not_found"})
# Slack error code for a rate limit, e.g. from the backfill after a restart, which clears by itself
_RATE_LIMITED_ERROR = "ratelimited"
# After a restart, results that finished this long ago are still delivered
_BACKFILL_SECONDS = 24 * 60 * 60
_PAGE_SIZE = 100
# Seconds each sweep re-covers before the last one started, for rows committed late with an earlier updated_at
_MARK_OVERLAP = 60
_RESULT_CHARS = 1500


class CompanyBridge:
    """The Company of the AgentOS whose Super Agent this Slack interface serves."""

    def __init__(self, agent_os: Any, deliver: bool = True):
        self._agent_os: ReferenceType[Any] = ref(agent_os)
        # Whether this interface posts Task results; one per bot token and users=/resolve_user_identity setting does
        self.deliver = deliver

    @property
    def agent_os(self) -> Any:
        return self._agent_os()

    @property
    def app(self) -> Any:
        return getattr(self.agent_os, "_company_app", None)

    @property
    def db(self) -> Any:
        return getattr(self.agent_os, "_company_db", None)

    async def authorize(self, app: Any, principal: str, entity_id: str) -> Any:
        """The platform authority of a mapped principal to run Super Agent.

        None when no authorization applies (neither AgentOS authorization nor an RBAC middleware).
        Raises PermissionError when the principal is disabled or not allowed to run the entity.
        """
        return await resolve_principal_authorization(app, principal, "teams", entity_id)


class TaskDelivery:
    """Posts the result of each Task started from this Slack interface into its thread, once per attempt.

    Every few seconds it reads Tasks updated since an in-memory high-water mark. A failed post or read
    is retried with backoff up to a retry limit and holds the mark; a rate-limited post retries without
    counting toward the limit, and permanent Slack errors (channel gone, bot removed) are given up at
    once. After a restart the mark starts a day back, so held results and results refused for lack of
    access are checked again. Delivery is at-least-once.
    """

    def __init__(self, ctx: SlackContext):
        self.ctx = ctx
        self.company: CompanyBridge = ctx.company
        self._mark = int(time.time()) - _BACKFILL_SECONDS
        self._done: Dict[Tuple[str, int], int] = {}
        self._retry: Dict[Tuple[str, int], Tuple[float, float, int]] = {}
        self._task: Optional["asyncio.Task[None]"] = None

    async def start(self) -> None:
        """Start the polling loop as a background task."""
        # Only spawns: AgentOS startup awaits this, so every read and post happens inside the loop
        if self._task is None:
            self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop the polling loop."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.sweep()
                self.ctx.failing.discard("task_delivery")
            except asyncio.CancelledError:
                break
            except NotImplementedError as exc:
                log_warning(f"Slack Task delivery stopped: {exc}")
                break
            except Exception as exc:
                # Logged once until a sweep succeeds again, not every few seconds
                if "task_delivery" not in self.ctx.failing:
                    log_error(f"Slack Task delivery sweep failed: {exc}")
                self.ctx.failing.add("task_delivery")
            await asyncio.sleep(_SWEEP_SECONDS)

    async def sweep(self) -> None:
        """Deliver every Task result updated since the high-water mark."""
        from agno.company.execution import _call

        app = self.company.app
        if self.company.db is None or app is None:
            return
        started = int(time.time())
        held: Optional[int] = None
        page = 1
        while True:
            # Each read starts from the top, so a row a mid-sweep delete shifts onto an earlier page is not skipped
            limit = _PAGE_SIZE * 2 ** (page - 1)
            rows, _ = await _call(
                self.company.db, "get_tasks", limit=limit, page=1, sort_by="updated_at", sort_order="desc"
            )
            below_mark = False
            for row in rows:
                updated = int(row.get("updated_at") or row.get("created_at") or 0)
                if updated < self._mark:
                    below_mark = True
                    break
                if not await self._deliver(app, row, updated):
                    held = updated if held is None else min(held, updated)
            if below_mark or len(rows) < limit:
                break
            page += 1
        # Rows seen again are skipped by the in-memory record or the Slack marker
        self._mark = (started if held is None else min(held, started)) - _MARK_OVERLAP
        self._done = {key: updated for key, updated in self._done.items() if updated >= self._mark}

    async def _deliver(self, app: Any, row: Dict[str, Any], updated: int) -> bool:
        """Post one Task's latest attempt if it is due. False while it waits for a retry."""
        attempts = [entry for entry in row.get("transitions") or [] if entry.get("attempt")]
        if not attempts or not _has_outcome(row):
            return True
        latest = attempts[-1]
        key = (row["id"], latest["attempt"])
        if key in self._done:
            return True
        retry = self._retry.get(key)
        if retry is not None and retry[0] > time.monotonic():
            return False
        try:
            accepted = await self._accept(latest)
            if accepted is None:
                self._finish(key, updated)
                return True
            channel, thread_ts, user_id, message_ts = accepted
            client = self.ctx.web()
            # The run's user must have written the message that started it, in this thread, read from Slack
            if await self._message_author(client, channel, thread_ts, message_ts) != user_id:
                log_debug(f"Task {key[0]} was not started by a Slack message from its run's user; not posted")
                self._finish(key, updated)
                return True
            # Never post without a completed check: a failed read is retried, not skipped past
            if await self._marked(client, channel, thread_ts, key, latest.get("created_at")):
                self._finish(key, updated)
                return True
            # Access is checked again before a delayed post: a revoked person sees nothing more
            try:
                authority = await self.company.authorize(app, user_id, self.ctx.entity_id)
                if authority is not None:
                    await authority.arequire("tasks", "read")
            except PermissionError as exc:
                log_debug(f"Task {key[0]} result not posted to Slack: {exc}")
                self._finish(key, updated)
                return True
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=await self._message(row, latest),
                metadata={"event_type": _RESULT_EVENT, "event_payload": {"task_id": key[0], "attempt": key[1]}},
                **slack_delivery_kwargs(self.ctx.unfurl_links, self.ctx.unfurl_media, self.ctx.markdown),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = slack_error_code(exc)
            failures = retry[2] if retry is not None else 0
            # A rate limit clears by itself, so it backs off without counting toward the retry limit
            if code != _RATE_LIMITED_ERROR:
                failures += 1
            if code in _PERMANENT_SLACK_ERRORS or failures > _RETRY_LIMIT:
                log_warning(f"Could not post Task {key[0]} attempt {key[1]} to Slack, not retrying: {exc}")
                self._finish(key, updated)
                return True
            delay = min(retry[1] * 2, _RETRY_MAX) if retry is not None else _RETRY_MIN
            self._retry[key] = (time.monotonic() + delay, delay, failures)
            log_warning(f"Could not post Task {key[0]} attempt {key[1]} to Slack, retrying in {delay:.0f}s: {exc}")
            return False
        self._finish(key, updated)
        return True

    def _finish(self, key: Tuple[str, int], updated: int) -> None:
        self._retry.pop(key, None)
        self._done[key] = updated

    async def _accept(self, attempt: Dict[str, Any]) -> Optional[Tuple[str, str, str, str]]:
        """The thread, principal and starting message of a Task attempt this Slack interface started, or None."""
        # Only the Super Agent start tool records requested_from, on the attempt its own call queued
        requested = attempt.get("requested_from") or {}
        session_id, run_id = requested.get("session_id"), requested.get("run_id")
        if not isinstance(session_id, str) or not isinstance(run_id, str):
            return None
        prefix = f"{self.ctx.entity_id}:"
        # Legacy "{entity_id}:{thread_ts}" sessions name no channel, so there is nowhere to post
        coordinates = session_id[len(prefix) :].split(":") if session_id.startswith(prefix) else []
        if len(coordinates) != 2 or not all(coordinates):
            return None
        session = await self.ctx.entity.aget_session(session_id=session_id)
        run = session.get_run(run_id) if session is not None else None
        if run is None or not run.user_id:
            return None
        # A run another interface started names no Slack message
        message_ts = (run.metadata or {}).get("slack_message_ts")
        if not isinstance(message_ts, str) or not message_ts:
            return None
        return coordinates[0], coordinates[1], run.user_id, message_ts

    async def _message_author(self, client: Any, channel: str, thread_ts: str, message_ts: str) -> Optional[str]:
        """The agno user id of the message's author, derived as for the event context; None outside the thread."""
        key = f"message_author:{channel}:{message_ts}"
        sender = self.ctx.lookup_cache.get(key)
        if sender is None:
            response = await client.conversations_replies(
                channel=channel, ts=thread_ts, oldest=message_ts, latest=message_ts, inclusive=True
            )
            message = next((m for m in response.get("messages") or [] if m.get("ts") == message_ts), None)
            if message is None:
                return None
            sender = (message.get("user") or "", message.get("bot_id") or "")
            self.ctx.lookup_cache.set(key, sender)
        user, bot_id = sender
        if self.ctx.users is not None:
            return self.ctx.users.get(user or bot_id)
        if self.ctx.resolve_user_identity:
            sender_id = user or bot_id
            # A user-token post carries both ids; the human is the sender, as for the event context
            if user:
                resolved_id, display_name = await self.ctx.lookup_cache.user_identity(client, user)
            else:
                resolved_id, display_name = await self.ctx.lookup_cache.bot_identity(client, bot_id)
            # A failed users.info or bots.info falls back to the raw id: retry rather than refuse the Task
            if resolved_id == sender_id and display_name is None:
                raise RuntimeError(f"Could not resolve Slack sender {sender_id}")
            return resolved_id
        return user or bot_id or None

    async def _marked(self, client: Any, channel: str, thread_ts: str, key: Tuple[str, int], since: Any) -> bool:
        """Whether a message in the thread since the attempt started already carries this attempt's marker."""
        cursor: Optional[str] = None
        while True:
            kwargs: Dict[str, Any] = {"channel": channel, "ts": thread_ts, "include_all_metadata": True}
            # Only replies after the attempt started can hold its marker
            if since:
                kwargs["oldest"] = str(since)
            if cursor:
                kwargs["cursor"] = cursor
            response = await client.conversations_replies(**kwargs)
            for message in response.get("messages") or []:
                metadata = message.get("metadata") or {}
                payload = metadata.get("event_payload") or {}
                if (
                    metadata.get("event_type") == _RESULT_EVENT
                    and payload.get("task_id") == key[0]
                    and payload.get("attempt") == key[1]
                ):
                    return True
            cursor = (response.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return False

    async def _message(self, row: Dict[str, Any], attempt: Dict[str, Any]) -> str:
        from agno.os.routers.company.runs import _TaskStarter

        heading = (
            f"'{row.get('title')}' (Task {row['id']}, attempt {attempt['attempt']}): "
            f"{TASK_STATUS_MEANING.get(row['status'], row['status'])}"
        )
        result = row.get("result") or {}
        if not result or result.get("run_id") != row.get("job_id"):
            return heading + "."
        lines = [f"{heading}; run {result.get('status')}."]
        content = result.get("content")
        if isinstance(content, str) and content.strip():
            lines.append(content[:_RESULT_CHARS])
            if len(content) > _RESULT_CHARS:
                lines.append("(Result shortened. The full result is on the Task in AgentOS.)")
        evidence = await _TaskStarter(self.company.agent_os).run_evidence(row)
        if evidence.get("evidence"):
            lines.append(f"Recorded evidence items: {len(evidence['evidence'])}.")
        if evidence.get("evidence_note"):
            lines.append(evidence["evidence_note"])
        return "\n".join(lines)


def _has_outcome(row: Dict[str, Any]) -> bool:
    """A Task finished or cancelled, or whose latest run ended in an error or a cancel while still in progress."""
    if row.get("status") in _RESULT_STATUSES:
        return True
    result = row.get("result") or {}
    return bool(result) and result.get("run_id") == row.get("job_id") and result.get("status") in ("ERROR", "CANCELLED")
