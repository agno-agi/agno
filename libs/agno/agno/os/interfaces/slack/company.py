"""Verified Slack intake and durable delivery for Company conversations."""

import asyncio
import hashlib
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException


_slack_cancel: ContextVar[Optional[tuple[str, str]]] = ContextVar("slack_company_cancel", default=None)

def _identity(*parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, json.dumps(parts)))


@dataclass
class SlackCompany:
    """Bind one Slack installation to existing platform principals and permitted channels.

    No Slack identity receives token scopes. Each action resolves current platform
    permissions for the configured principal. Each participant has a separate
    conversation within a thread. Allowed channels are shared disclosure destinations:
    replies are visible to channel members, while private session history is isolated.
    Requires CompanyOS, managed authorization, PostgreSQL and the durable queue.
    agent_os_url is the UI's Company URL for this configured AgentOS instance.
    """

    workspace_id: str
    app_id: str
    bot_user_id: str
    users: Dict[str, str]
    channels: tuple[str, ...]
    agent_os_url: str

    def __post_init__(self) -> None:
        if not all((self.workspace_id, self.app_id, self.bot_user_id, self.users, self.channels)):
            raise ValueError("SlackCompany requires an installation, user mappings and allowed channels")
        if urlparse(self.agent_os_url).scheme not in {"http", "https"}:
            raise ValueError("agent_os_url must be an HTTP(S) Company UI URL")
        if any(not re.fullmatch(r"[UW][A-Z0-9]+", user) or not principal for user, principal in self.users.items()):
            raise ValueError("Slack user mappings require Slack user IDs and nonempty platform principals")
        self._os: Any = None
        self._store: Any = None
        self._tools: Any = None
        self._stream_client: Any = None
        self._scope = ""
        self._initialized = False

    def _bind(self, os: Any, prefix: str) -> None:
        from agno.os.interfaces.slack.store import _SlackStore

        if os.company is None or os.manager is None or os._authz_role_store is None or not os.authorization:
            raise ValueError("SlackCompany requires CompanyOS, Super Agent and managed platform authorization")
        if os.queue is None or not os.queue.durable or not os._scheduler_enabled:
            raise ValueError("SlackCompany requires the durable queue and existing Company scheduler")
        db = os._company_db
        if (
            getattr(getattr(db, "db_engine", None), "dialect", None) is None
            or db.db_engine.dialect.name != "postgresql"
        ):
            raise ValueError("SlackCompany requires PostgreSQL receipt storage")
        queue_db = os.queue.db or os.db
        if (
            getattr(getattr(queue_db, "db_engine", None), "dialect", None) is None
            or queue_db.db_engine.dialect.name != "postgresql"
        ):
            raise ValueError("SlackCompany requires the PostgreSQL durable queue")
        self._os = os
        self._scope = _identity(str(os.id), prefix, self.workspace_id, self.app_id)
        self._store = _SlackStore(db, self._scope)

    async def _initialize(self) -> None:
        if not self._initialized:
            await self._store._initialize()
            self._initialized = True

    async def _authority(self, app: Any, user: str, principal: Optional[str] = None) -> Any:
        from agno.os.authz.provider import AuthorizationContext
        from agno.os.authz.run_context import restore_authorization
        from agno.run.authorization import RunAuthorization

        actor = self.users.get(user)
        if actor is None or (principal is not None and actor != principal):
            raise PermissionError("Slack user is not mapped to this platform principal")
        user_store = getattr(app.state, "user_store", None)
        if user_store is not None:
            try:
                disabled = bool(await user_store.ais_disabled(actor))
            except Exception:
                if getattr(app.state, "user_directory_fail_closed", False):
                    raise HTTPException(503, "User directory unavailable")
                disabled = False
            if disabled:
                raise PermissionError("Platform principal is disabled")
        # Restored managed roles are resolved fresh, including revocations.
        from dataclasses import asdict

        authority = restore_authorization(
            app,
            {"context": asdict(AuthorizationContext(principal_id=actor, claims={"sub": actor})), "enforce_tools": True},
        )
        assert isinstance(authority, RunAuthorization)
        await authority.arequire("teams", "run", "super-agent")
        return authority

    def _envelope(self, data: Dict[str, Any]) -> tuple[str, str, str]:
        if data.get("team_id") != self.workspace_id or data.get("api_app_id") != self.app_id:
            raise HTTPException(403, "Slack installation does not match")
        authorizations = data.get("authorizations") or []
        if not any(
            a.get("team_id") == self.workspace_id and a.get("user_id") == self.bot_user_id and a.get("is_bot") is True
            for a in authorizations
        ):
            raise HTTPException(403, "Slack installation authorization is missing")
        event = data.get("event") or {}
        user, channel = event.get("user"), event.get("channel")
        thread = event.get("thread_ts") or event.get("ts")
        if not isinstance(user, str) or channel not in self.channels or not isinstance(thread, str):
            raise HTTPException(403, "Slack participant or channel is not configured")
        return user, channel, thread

    async def _receive(self, data: Dict[str, Any], request: Any, background_tasks: Any) -> None:
        event = data.get("event") or {}
        if (
            event.get("bot_id")
            or event.get("subtype")
            or event.get("user") == self.bot_user_id
            or event.get("type") not in {"message", "app_mention"}
        ):
            return
        user, channel, thread = self._envelope(data)
        await self._initialize()
        if event.get("type") != "app_mention" and not await self._store._thread_exists(channel, thread):
            return
        try:
            authority = await self._authority(request.app, user)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        event_id, message = data.get("event_id"), event.get("text")
        if not isinstance(event_id, str) or not event_id or not isinstance(message, str) or not message.strip():
            raise HTTPException(400, "Slack event id and message are required")
        message = message.replace("<@" + self.bot_user_id + ">", "").strip()
        principal = authority.context.principal_id
        session_id = _identity(self._scope, channel, thread, principal)
        receipt_id = _identity(self._scope, event_id)
        run_id = _identity(receipt_id, "conversation")
        body = {
            "user": user,
            "channel": channel,
            "thread": thread,
            "message": message,
            "run_id": run_id,
            "state": "received",
            "notifications": {},
            "attempts": 0,
        }
        cancellation = re.fullmatch(r"cancel\s+([a-zA-Z0-9_-]+)", message, flags=re.IGNORECASE)
        if cancellation:
            body.update(kind="cancel", task_id=cancellation.group(1))
        row = await self._store._receive(receipt_id, session_id, principal, body)
        if row["principal"] != principal or any(
            row["data"].get(key) != body[key] for key in ("user", "channel", "thread", "message")
        ):
            raise HTTPException(409, "Slack event id conflicts with an existing receipt")
        # The HTTP acknowledgement follows durable receipt. Submission never
        # waits for a model, and a failed provider post is retried by CompanyOS.
        background_tasks.add_task(self._process, request.app, receipt_id)

    async def _request(self, app: Any, row: Dict[str, Any], method: str, path: str, **kwargs: Any) -> Any:
        import httpx

        from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER
        from agno.run.authorization import AUTHORIZATION_HEADER

        authority = await self._authority(app, row["data"]["user"], row["principal"])
        headers = {
            "Authorization": "Bearer " + app.state.internal_service_token,
            AUTHORIZATION_HEADER: json.dumps(authority.snapshot()),
            SCHEDULE_OWNER_HEADER: quote(row["principal"], safe=""),
            "Idempotency-Key": row["id"],
        }
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://slack-company") as client:
            response = await client.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            raise HTTPException(response.status_code, response.text)
        return response.json()

    def _intent(self, row: Dict[str, Any], key: str, text: str, *, blocks: Any = None) -> None:
        row["data"]["notifications"].setdefault(
            key, {"text": text, "blocks": blocks, "sent": False, "id": _identity(row["id"], key)}
        )

    async def _submit(self, app: Any, row: Dict[str, Any]) -> None:
        from agno.company.conversation import _conversation_run_id
        from agno.company.execution import _call

        data = row["data"]
        if data.get("kind") == "cancel":
            task = await self._task(app, row, data["task_id"], write=True)
            if task.get("job_id") and task["status"] not in {"done", "cancelled"}:
                path = f"/company/runs/{quote(task['job_id'], safe='')}/cancel"
                token = _slack_cancel.set((path, row["principal"]))
                try:
                    await self._request(app, row, "POST", path)
                finally:
                    _slack_cancel.reset(token)
            data["state"] = "submitted"
            self._intent(row, "cancel", "Cancellation processed for Task " + task["id"] + ".")
            return
        if data.get("kind") == "continue":
            # The continue route validates persisted requirements and the queue
            # owns recovery. A terminal run is never restarted by a delivery retry.
            current = await _call(self._os.manager.db, "get_run", run_id=data["run_id"])
            status = getattr(current, "status", None)
            if str(getattr(status, "value", status)).upper() == "PAUSED":
                await self._request(
                    app,
                    row,
                    "POST",
                    f"/teams/super-agent/runs/{data['run_id']}/continue",
                    data={
                        "session_id": row["session_id"],
                        "requirements": json.dumps(data["requirements"]),
                        "stream": "false",
                        "background": "true",
                    },
                )
            data["state"] = "submitted"
            return
        # A committed historical run also fences replay after queue retention.
        run = await _call(self._os.manager.db, "get_run", run_id=data["run_id"])
        if run is None:
            token = _conversation_run_id.set(data["run_id"])
            try:
                result = await self._request(
                    app,
                    row,
                    "POST",
                    f"/company/conversations/{row['session_id']}/messages",
                    json={"message": data["message"]},
                )
            finally:
                _conversation_run_id.reset(token)
            if result.get("run_id") != data["run_id"]:
                raise RuntimeError("Conversation receipt did not retain its durable run identity")
        data["state"] = "submitted"
        self._intent(row, "receipt", "Received. Your conversation is queued; delegated work is tracked separately.")

    async def _task(self, app: Any, row: Dict[str, Any], task_id: str, *, write: bool = False) -> Dict[str, Any]:
        from agno.company.conversation import aget_conversation_tasks
        from agno.company.execution import _call
        from agno.run import RunContext

        authority = await self._authority(app, row["data"]["user"], row["principal"])
        tasks = await aget_conversation_tasks(
            self._os,
            RunContext(run_id=row["data"]["run_id"], session_id=row["session_id"], user_id=row["principal"], authorization=authority),
        )
        if not any(task["task_id"] == task_id for task in tasks):
            raise PermissionError("Task does not belong to this participant's conversation")
        task = await _call(self._os._company_db, "get_task", task_id)
        if task is None:
            raise PermissionError("Task is unavailable")
        if write:
            await authority.arequire("tasks", "write")
            await authority.arequire(task["executor_type"] + "s", "run", task["executor_id"])
        return task

    async def _collect(self, app: Any, row: Dict[str, Any]) -> bool:
        from agno.company.execution import _call

        data = row["data"]
        await self._authority(app, data["user"], row["principal"])
        run = await _call(self._os.manager.db, "get_run", run_id=data["run_id"])
        complete = False
        if data.get("kind") in {"continue", "cancel"}:
            return True  # The originating receipt delivers all subsequent run results.
        if run is not None:
            value = run.to_dict() if hasattr(run, "to_dict") else run
            status = str(value.get("status", "")).upper()
            if status in {"COMPLETED", "ERROR", "CANCELLED", "PAUSED"}:
                key = (
                    "conversation:"
                    + hashlib.sha256(
                        json.dumps([status, value.get("requirements")], sort_keys=True, default=str).encode()
                    ).hexdigest()
                )
                content = value.get("content") or {
                    "ERROR": "The conversation failed.",
                    "CANCELLED": "The conversation was cancelled.",
                    "PAUSED": "A tool needs your input or approval.",
                }.get(status, "Conversation complete.")
                blocks = None
                if status == "PAUSED":
                    from agno.os.interfaces.slack.builders import build_pause_message
                    from agno.os.interfaces.slack.types import block_to_dict
                    from agno.run.requirement import RunRequirement

                    requirements = [RunRequirement.from_dict(req) for req in value.get("requirements") or []]
                    blocks = [block_to_dict(block) for block in build_pause_message(data["run_id"], requirements)]
                self._intent(row, key, str(content), blocks=blocks)
                complete = status != "PAUSED"
        # Read associations through the authorized conversation API, which
        # checks the originating participant and run on every read.
        active = False
        if data.get("kind") == "continue":
            return complete
        from agno.company.conversation import aget_conversation_tasks
        from agno.run import RunContext

        authority = await self._authority(app, data["user"], row["principal"])
        try:
            payload = await aget_conversation_tasks(
                self._os,
                RunContext(
                    run_id=data["run_id"],
                    session_id=row["session_id"],
                    user_id=row["principal"],
                    authorization=authority,
                ),
                origin_run_id=data["run_id"],
            )
        except PermissionError:
            return complete
        tasks = payload if isinstance(payload, list) else payload.get("tasks", payload.get("data", []))
        for task in tasks:
            status = task["status"]
            active = active or status not in {"done", "cancelled"}
            if status in {"done", "cancelled", "in_review", "backlog"}:
                key = "task:" + task["task_id"] + ":" + hashlib.sha256(
                    json.dumps(task, sort_keys=True, default=str).encode()
                ).hexdigest()
                detail = (
                    "Work finished; CompanyOS is assessing the evidence."
                    if status == "in_review"
                    else task.get("reason") or task.get("result") or status
                )
                link = (
                    self.agent_os_url
                    + ("&" if "?" in self.agent_os_url else "?")
                    + "task="
                    + quote(task["task_id"], safe="")
                )
                self._intent(row, key, f"Task {task['title']}: {status}\n{detail}\n{link}")
        return complete and not active

    async def _deliver(self, app: Any, row: Dict[str, Any]) -> None:
        data = row["data"]
        # The token must belong to the configured installation before any post.
        identity = await asyncio.to_thread(self._tools.client.auth_test)
        if identity.get("team_id") != self.workspace_id or identity.get("user_id") != self.bot_user_id:
            raise PermissionError("Slack token installation does not match")
        for key, notification in data["notifications"].items():
            if notification["sent"]:
                continue
            if key != "failure":
                await self._authority(app, data["user"], row["principal"])
            await self._store._save(row)
            if key.startswith("task:"):
                from agno.company.conversation import aget_conversation_tasks
                from agno.run import RunContext

                authority = await self._authority(app, data["user"], row["principal"])
                visible = await aget_conversation_tasks(
                    self._os,
                    RunContext(
                        run_id=data["run_id"],
                        session_id=row["session_id"],
                        user_id=row["principal"],
                        authorization=authority,
                    ),
                    origin_run_id=data["run_id"],
                )
                if not any(task["task_id"] == key.split(":")[1] for task in visible):
                    raise PermissionError("Task is no longer visible to the originating participant")
            text = str(notification["text"]).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if self._stream_client is not None and not notification.get("blocks") and key != "receipt":
                from agno.os.interfaces.slack.helpers import open_chat_stream

                stream = await open_chat_stream(
                    self._stream_client, data["channel"], data["thread"], data["user"], self.workspace_id, "plan", 100
                )
                for offset in range(0, len(text), 3000):
                    await stream.append(markdown_text=text[offset : offset + 3000])
                result = await stream.stop()
            else:
                result = await asyncio.to_thread(
                    self._tools.client.chat_postMessage,
                    channel=data["channel"],
                    thread_ts=data["thread"],
                    text=text[:39000],
                    blocks=notification.get("blocks"),
                    client_msg_id=notification["id"],
                    unfurl_links=False,
                    unfurl_media=False,
                )
            if not result.get("ok"):
                raise RuntimeError("Slack result delivery was refused")
            notification.update(sent=True, ts=result.get("ts"))
            await self._store._save(row)

    async def _process(self, app: Any, receipt_id: Optional[str] = None) -> bool:
        await self._initialize()
        row = await self._store._claim(receipt_id)
        if row is None:
            return False
        finished = False
        try:
            if row["data"]["state"] == "failed":
                await self._deliver(app, row)
                row["data"].pop("error", None)
                await self._store._save(row, release=True, delay=86400 * 365 * 100)
                return True
            if row["data"]["state"] == "received":
                await self._submit(app, row)
                await self._store._save(row)
            finished = await self._collect(app, row)
            await self._store._save(row)  # Intent must commit before provider I/O.
            await self._deliver(app, row)
            row["data"]["attempts"] = 0
            row["data"].pop("error", None)
        except (PermissionError, HTTPException) as exc:
            if isinstance(exc, PermissionError) or 400 <= exc.status_code < 500 and exc.status_code != 429:
                row["data"]["state"] = "failed"
                row["data"]["notifications"] = {}
                self._intent(
                    row,
                    "failure",
                    "This request could not continue under your current platform access or inputs. Review it in AgentOS: "
                    + self.agent_os_url,
                )
                await self._store._save(row)
            row["data"]["attempts"] += 1
            row["data"]["error"] = type(exc).__name__
        except Exception as exc:
            row["data"]["attempts"] += 1
            row["data"]["error"] = type(exc).__name__ + ": " + str(exc)
        delay = (
            86400 * 365 * 100
            if finished and not row["data"].get("error")
            else min(300, 5 * 2 ** min(row["data"]["attempts"], 6))
        )
        await self._store._save(row, release=True, delay=delay)
        return True

    async def _tick(self, app: Any) -> None:
        for _ in range(100):
            if not await self._process(app):
                break

    async def _interact(self, payload: Dict[str, Any], request: Any, background_tasks: Any) -> None:
        from agno.company.execution import _call
        from agno.os.interfaces.slack.ids import (
            ACTION_ROW_APPROVE,
            ACTION_ROW_REJECT,
            ACTION_SUBMIT,
            decode_row_button_value,
        )
        from agno.os.interfaces.slack.interactions import apply_decisions, parse_submit_payload
        from agno.run.requirement import RunRequirement

        if (payload.get("team") or {}).get("id") != self.workspace_id or payload.get("api_app_id") != self.app_id:
            raise HTTPException(403, "Slack installation does not match")
        user = (payload.get("user") or {}).get("id")
        channel = (payload.get("channel") or {}).get("id")
        if not isinstance(user, str) or channel not in self.channels:
            raise HTTPException(403, "Slack channel is not configured")
        try:
            authority = await self._authority(request.app, user)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        actions = payload.get("actions") or []
        if not actions:
            return
        action = actions[0]
        action_id = action.get("action_id")
        if action_id not in {ACTION_ROW_APPROVE, ACTION_ROW_REJECT, ACTION_SUBMIT}:
            return  # Administrative approvals retain their AgentOS resolution path.
        req_id = None
        if action_id == ACTION_SUBMIT:
            block = action.get("block_id", "")
            if not block.startswith("pause:"):
                raise HTTPException(400, "Invalid pause action")
            run_id = block.removeprefix("pause:")
        else:
            req_id, run_id, _ = decode_row_button_value(action.get("value", ""))
        message = payload.get("message") or {}
        thread = message.get("thread_ts") or message.get("ts")
        await self._initialize()
        parent = await self._store._by_run(run_id, authority.context.principal_id, channel, thread)
        if parent is None:
            raise HTTPException(403, "This participant does not own this paused conversation")
        run = await _call(self._os.manager.db, "get_run", run_id=run_id)
        value = run.to_dict() if hasattr(run, "to_dict") else run
        if not value or str(value.get("status", "")).upper() != "PAUSED":
            return
        requirements = [RunRequirement.from_dict(req) for req in value.get("requirements") or []]
        if req_id:
            requirements = [req for req in requirements if req.id == req_id]
            if not requirements:
                raise HTTPException(400, "Unknown paused requirement")
            for req in requirements:
                if getattr(req.tool_execution, "approval_type", None) == "required":
                    raise HTTPException(403, "Resolve this administrative approval in AgentOS")
                req.confirm() if action_id == ACTION_ROW_APPROVE else req.reject()
        else:
            decisions, errors = parse_submit_payload(payload, requirements)
            if errors:
                raise HTTPException(400, "Complete the requested fields before submitting")
            apply_decisions(decisions, requirements)
        key = _identity(
            self._scope, "interaction", user, run_id, str(action.get("action_ts")), json.dumps(actions, sort_keys=True)
        )
        data = {
            **parent["data"],
            "kind": "continue",
            "state": "received",
            "notifications": {},
            "attempts": 0,
            "requirements": [req.to_dict() for req in requirements],
        }
        await self._store._receive(key, parent["session_id"], parent["principal"], data)
        background_tasks.add_task(self._process, request.app, key)
