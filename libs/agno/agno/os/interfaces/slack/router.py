"""Bolt app and FastAPI routes for the Slack interface.

Slack sends events and button clicks to two routes. Bolt verifies each request,
acknowledges it, and dispatches to a listener; the listeners hand off to
``SlackEventHandler`` (messages, lifecycle events) and ``HITLHandler`` (approval cards).
"""

import re
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from fastapi import Request
from fastapi.routing import APIRouter
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from slack_bolt.request.async_request import AsyncBoltRequest
from slack_bolt.response import BoltResponse
from slack_sdk.web.async_client import AsyncWebClient

from agno.os.interfaces.slack.utils import ACTION_CHECK_STATUS, ACTION_ROW_APPROVE, ACTION_ROW_REJECT, ACTION_SUBMIT
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.os.interfaces.slack.slack import Slack

# Replaces Bolt's auth.test lookup of the bot identity (tests, multi-workspace installs)
AuthorizeFn = Callable[..., Awaitable[Any]]


class EventDeduplicator:
    """Remembers recent ``event_id`` values so a retried event runs once per process.

    Slack retries when it does not get a 200 within three seconds; Bolt would process
    the retry again. Ids are kept longer than Slack's last retry (five minutes).
    """

    def __init__(self, ttl_seconds: float = 600.0, max_entries: int = 4096) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._seen: "OrderedDict[str, float]" = OrderedDict()

    def is_duplicate(self, key: str) -> bool:
        now = time.monotonic()
        while self._seen:
            oldest_key, oldest_ts = next(iter(self._seen.items()))
            if now - oldest_ts <= self._ttl:
                break
            del self._seen[oldest_key]
        if key in self._seen:
            return True
        self._seen[key] = now
        while len(self._seen) > self._max_entries:
            self._seen.popitem(last=False)
        return False

    def __len__(self) -> int:
        return len(self._seen)

    async def middleware(self, req: AsyncBoltRequest, resp: BoltResponse, next_: Callable[[], Awaitable[Any]]) -> Any:
        # Runs after Bolt verified the signature, so only signed requests mark an id.
        # Interaction payloads have no event_id; for those a retry header is the signal.
        body = req.body if isinstance(req.body, dict) else {}
        event_id = body.get("event_id")
        if isinstance(event_id, str) and event_id:
            if self.is_duplicate(event_id):
                return BoltResponse(status=200, body="")
            return await next_()
        if req.headers.get("x-slack-retry-num"):
            return BoltResponse(status=200, body="")
        return await next_()


def build_bolt_app(slack: "Slack", authorize: Optional[AuthorizeFn] = None) -> AsyncApp:
    """Create the Bolt app and register every listener against the interface's handlers."""
    # Bolt refuses a fixed token together with ``authorize``, so the two are exclusive
    kwargs: dict = {
        "signing_secret": slack.signing_secret,
        "process_before_response": False,
        "request_verification_enabled": True,
        "ignoring_self_events_enabled": True,
        "url_verification_enabled": True,
        "ssl_check_enabled": True,
        "raise_error_for_unhandled_request": False,
    }
    if authorize is not None:
        kwargs["authorize"] = authorize
    else:
        kwargs["client"] = AsyncWebClient(token=slack.token, ssl=slack.ssl)

    app = AsyncApp(**kwargs)
    app.use(slack.dedupe.middleware)
    events = slack.event_handler
    hitl = slack.hitl

    # Bolt injects arguments by name, so listener signatures stay explicit
    @app.event("assistant_thread_started")
    async def _on_thread_started(event: dict) -> None:
        await events.handle_thread_started(event)

    @app.event("app_mention")
    async def _on_app_mention(body: dict) -> None:
        await events.handle_message(body)

    @app.event("message")
    async def _on_message(body: dict) -> None:
        await events.handle_message(body)

    @app.event("app_home_opened")
    async def _on_home_opened(event: dict) -> None:
        await events.handle_home_opened(event)

    @app.event("agent_session_stopped")
    async def _on_session_stopped(event: dict) -> None:
        await events.handle_session_stopped(event)

    @app.event("agent_session_title_changed")
    async def _on_title_changed(event: dict) -> None:
        await events.handle_title_changed(event)

    @app.event("app_context_changed")
    async def _on_context_changed(event: dict) -> None:
        await events.handle_context_changed(event)

    @app.event("assistant_thread_context_changed")
    async def _on_assistant_context_changed(event: dict) -> None:
        await events.handle_context_changed(event)

    # Events without a handler still get a 200 so Slack does not retry them
    @app.event(re.compile(".*"))
    async def _on_other_event() -> None:
        return None

    @app.action(ACTION_ROW_APPROVE)
    async def _on_row_approve(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
        await ack()
        await hitl.handle_row_approve(body)

    @app.action(ACTION_ROW_REJECT)
    async def _on_row_reject(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
        await ack()
        await hitl.handle_row_reject(body)

    @app.action(ACTION_CHECK_STATUS)
    async def _on_check_status(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
        await ack()
        await hitl.handle_check_status(body)

    @app.action(ACTION_SUBMIT)
    async def _on_submit(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
        await ack()
        await hitl.handle_submit(body)

    # Unknown action ids are acknowledged and ignored: another Slack app sharing the
    # endpoint, or a card from a newer build, must not produce an error for the user
    @app.action(re.compile(".*"))
    async def _on_other_action(ack: Callable[..., Awaitable[Any]]) -> None:
        await ack()

    @app.error
    async def _on_error(error: Exception) -> None:
        log_error(f"Slack listener error: {error}")

    return app


def attach_routes(router: APIRouter, bolt_app: AsyncApp) -> APIRouter:
    """Add the two Slack webhook routes to ``router``, both served by Bolt."""
    handler = AsyncSlackRequestHandler(bolt_app)

    # Multiple Slack instances can be mounted on one FastAPI app (e.g. /research
    # and /analyst). The prefix makes each operation_id unique to avoid collisions.
    op_suffix = router.prefix.strip("/").replace("/", "_") or "slack"

    @router.post(
        "/events",
        operation_id=f"slack_events_{op_suffix}",
        name="slack_events",
        description="Process incoming Slack events",
        responses={200: {"description": "Event accepted"}, 401: {"description": "Invalid Slack signature"}},
    )
    async def slack_events(request: Request) -> Any:
        return await handler.handle(request)

    @router.post(
        "/interactions",
        operation_id=f"slack_interactions_{op_suffix}",
        name="slack_interactions",
        description="Handle Slack interactive components (HITL buttons / form submit)",
        responses={200: {"description": "Interaction accepted"}, 401: {"description": "Invalid Slack signature"}},
    )
    async def slack_interactions(request: Request) -> Any:
        return await handler.handle(request)

    return router
