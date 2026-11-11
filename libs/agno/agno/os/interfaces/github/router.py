import asyncio
import inspect
import json
import time
from urllib.parse import parse_qs
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Collection, Dict, Optional, Tuple, Union

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from agno.os.interfaces.github.events import GitHubEvent, ignore_reason, parse_event
from agno.os.interfaces.github.security import verify_signature
from agno.utils.log import log_error, log_warning

EventHandler = Callable[[GitHubEvent], Union[Optional[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]]


class DeliveryLog:
    """Deliveries this process has handled or is handling, by X-GitHub-Delivery.

    A redelivery of a delivery that succeeded is answered without running the handler again, and one
    that arrives while the first is still running waits for it. A delivery whose handler failed is
    forgotten, so a redelivery retries it. This is per process and short-lived: a handler that must
    never act twice on one event also keys its own records durably.
    """

    def __init__(self, ttl_seconds: float = 600, max_size: int = 4096):
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._seen: "OrderedDict[str, Tuple[float, asyncio.Future]]" = OrderedDict()

    def claim(self, delivery_id: str) -> Tuple["asyncio.Future", bool]:
        """The delivery's outcome, and whether this caller must produce it."""
        now = time.monotonic()
        while self._seen and next(iter(self._seen.values()))[0] < now:
            self._seen.popitem(last=False)
        known = self._seen.get(delivery_id)
        if known is not None:
            return known[1], False
        outcome: asyncio.Future = asyncio.get_running_loop().create_future()
        self._seen[delivery_id] = (now + self.ttl_seconds, outcome)
        while len(self._seen) > self.max_size:
            self._seen.popitem(last=False)
        return outcome, True

    def forget(self, delivery_id: str) -> None:
        self._seen.pop(delivery_id, None)


def _payload_text(body: bytes, content_type: str) -> str:
    """The JSON payload of a delivery. A webhook set to the form content type, the REST API's default for
    repository webhooks, sends it as payload=<url-encoded JSON>; the signature covers the raw body."""
    if content_type.split(";")[0].strip().lower() == "application/x-www-form-urlencoded":
        values = parse_qs(body.decode(), keep_blank_values=True).get("payload")
        if not values:
            raise ValueError("The form delivery has no payload field")
        return values[0]
    return body.decode()


async def _run(handler: EventHandler, event: GitHubEvent) -> Optional[Dict[str, Any]]:
    # A sync handler runs in the threadpool so a slow one doesn't hold up other deliveries.
    if inspect.iscoroutinefunction(handler):
        return await handler(event)
    result = await run_in_threadpool(handler, event)
    if inspect.isawaitable(result):
        result = await result
    return result


def attach_routes(
    router: APIRouter,
    handler: EventHandler,
    secret: str,
    repositories: Collection[str],
    events: Collection[str],
    handle_bot_events: bool = False,
    deliveries: Optional[DeliveryLog] = None,
) -> APIRouter:
    # Several GitHub interfaces can share an app on different prefixes; their operation ids must differ.
    op_suffix = (router.prefix.strip("/") or "root").replace("/", "_").replace("-", "_")
    log = deliveries if deliveries is not None else DeliveryLog()

    @router.get("/status", operation_id=f"github_status_{op_suffix}")
    async def status():
        return {"status": "available"}

    @router.post(
        "/events",
        operation_id=f"github_events_{op_suffix}",
        name="github_events",
        description="Receive GitHub webhook deliveries for the watched repositories.",
    )
    async def receive(request: Request):
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")
        if not signature:
            raise HTTPException(status_code=400, detail="Missing X-Hub-Signature-256 header")
        if not verify_signature(secret, body, signature):
            raise HTTPException(status_code=403, detail="Invalid signature")
        name = request.headers.get("X-GitHub-Event")
        delivery_id = request.headers.get("X-GitHub-Delivery")
        if not name or not delivery_id:
            raise HTTPException(status_code=400, detail="Missing X-GitHub-Event or X-GitHub-Delivery header")
        # GitHub sends a ping once, when the webhook is created.
        if name == "ping":
            return {"status": "pong"}
        try:
            payload = json.loads(_payload_text(body, request.headers.get("content-type", "")))
        except ValueError:
            raise HTTPException(status_code=400, detail="The delivery is not JSON")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="The delivery is not a JSON object")

        event = parse_event(name, delivery_id, payload)
        reason = "the delivery names no repository" if event is None else None
        if event is not None:
            reason = ignore_reason(event, repositories, events, handle_bot_events)
        if event is None or reason is not None:
            return {"status": "ignored", "reason": reason}

        outcome, owner = log.claim(delivery_id)
        if not owner:
            # A redelivery: answer with the first run's outcome instead of handling the event twice.
            first: Dict[str, Any] = await asyncio.shield(outcome)
            return JSONResponse(status_code=202, content={**first, "duplicate": True})

        # GitHub does not retry a failed delivery on its own, so success is reported only once the
        # handler has recorded the event; a failure asks for a redelivery instead of losing it quietly.
        try:
            result = await _run(handler, event)
        except Exception as exc:
            log.forget(delivery_id)
            failure = exc
            if not isinstance(exc, HTTPException):
                log_error(f"GitHub delivery {delivery_id} ({event.kind}) could not be recorded: {exc}")
                failure = HTTPException(
                    status_code=500, detail="The event could not be recorded; redeliver it from the webhook settings"
                )
            outcome.set_exception(failure)
            # Retrieved here so an unawaited outcome doesn't log "exception was never retrieved".
            outcome.exception()
            raise failure

        # The event is recorded from here on, so nothing below may fail the delivery.
        content: Dict[str, Any] = {"status": "recorded", "delivery_id": delivery_id}
        if result is not None:
            try:
                content["result"] = jsonable_encoder(result)
            except Exception as exc:
                log_warning(f"GitHub delivery {delivery_id}: the handler's result is not JSON and was left out: {exc}")
        outcome.set_result(content)
        return JSONResponse(status_code=202, content=content)

    return router
