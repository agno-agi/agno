from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from ssl import SSLContext
from typing import Any, Coroutine, Optional, Set

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.async_client import AsyncBaseSocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

from agno.os.interfaces.slack.event_handler import SlackEventHandler
from agno.os.interfaces.slack.helpers import EventDeduplicator
from agno.os.interfaces.slack.hitl import HITLHandler
from agno.os.interfaces.slack.ids import (
    ACTION_CHECK_STATUS,
    ACTION_ROW_APPROVE,
    ACTION_ROW_REJECT,
    ACTION_SUBMIT,
)
from agno.utils.log import log_error, log_warning


@dataclass
class SocketModeListener:
    """Turns Socket Mode envelopes into calls on the handlers the HTTP routes use."""

    event_handler: SlackEventHandler
    hitl: HITLHandler
    event_dedupe: EventDeduplicator
    streaming: bool
    # Strong references: asyncio keeps only weak ones, so an untracked task can vanish mid-run.
    tasks: Set[asyncio.Task[None]] = field(default_factory=set)

    async def __call__(self, client: AsyncBaseSocketModeClient, req: SocketModeRequest) -> None:
        # Ack first: Slack retries any envelope not acked within a few seconds, and an agent run
        # takes longer than that. If the ack itself fails nothing is dispatched or marked seen,
        # so Slack's redelivery runs the event exactly once.
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        if req.type == "events_api":
            self._dispatch_event(req)
        elif req.type == "interactive":
            self._dispatch_interaction(req)
        # slash_commands and anything else: acked above, not handled.

    def _dispatch_event(self, req: SocketModeRequest) -> None:
        data = req.payload
        # Same rule as the /events route: a retry is a duplicate only if the original arrived, so
        # dedupe on event_id and drop only the retries that carry no id to dedupe on.
        event_id = data.get("event_id")
        if isinstance(event_id, str) and event_id:
            if self.event_dedupe.is_duplicate(event_id):
                return
        elif req.retry_attempt:
            return

        event = data.get("event")
        if not isinstance(event, dict):
            log_warning("Ignoring Slack Socket Mode events_api envelope without an event body")
            return
        if event.get("type") == "assistant_thread_started" and self.streaming:
            self._spawn(self.event_handler.handle_thread_started(event))
        elif self.event_handler.should_process(event):
            handle = self.event_handler.handle_streaming if self.streaming else self.event_handler.handle_non_streaming
            self._spawn(handle(data))

    def _dispatch_interaction(self, req: SocketModeRequest) -> None:
        # Same rules as the /interactions route: retries are dropped, only block_actions carry HITL
        # clicks, and an unknown action_id may belong to another app sharing the Slack app.
        if req.retry_attempt:
            return
        payload = req.payload
        if payload.get("type") != "block_actions":
            return
        actions = payload.get("actions") or []
        if not actions:
            return
        handle = {
            ACTION_ROW_APPROVE: self.hitl.handle_row_approve,
            ACTION_ROW_REJECT: self.hitl.handle_row_reject,
            ACTION_CHECK_STATUS: self.hitl.handle_check_status,
            ACTION_SUBMIT: self.hitl.handle_submit,
        }.get(actions[0].get("action_id", ""))
        if handle is not None:
            self._spawn(handle(payload))

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self._finish)

    def _finish(self, task: asyncio.Task[None]) -> None:
        self.tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log_error(f"Slack Socket Mode handler failed: {exc}")


async def run_socket_mode(
    app_token: str,
    *,
    event_handler: SlackEventHandler,
    hitl: HITLHandler,
    event_dedupe: EventDeduplicator,
    streaming: bool,
    ssl: Optional[SSLContext],
) -> None:
    # The web client carries the bot token for API calls; the SDK substitutes the app token for
    # apps.connections.open itself and takes the WebSocket's ssl context from this client.
    web_client = AsyncWebClient(token=event_handler.slack_tools.token, ssl=ssl)
    # Built inside the running loop on purpose: the SDK opens an aiohttp session and schedules
    # its message processor in __init__.
    client = SocketModeClient(app_token=app_token, web_client=web_client)
    client.socket_mode_request_listeners.append(
        SocketModeListener(event_handler, hitl, event_dedupe, streaming=streaming)
    )
    try:
        # connect() swallows every error and retries forever, so fetch the URL first: an invalid
        # app token then fails the start with a SlackApiError instead of looping silently.
        client.wss_uri = await client.issue_new_wss_url()
        await client.connect()
        # connect() returns once the socket is up; hold the coroutine open until cancelled.
        await asyncio.Event().wait()
    finally:
        # In-flight handler tasks are left to the loop: asyncio.run cancels them at exit and an
        # embedding loop decides for itself. Awaiting them here could hang shutdown on a long run.
        await client.close()
