import inspect
import json
from typing import Any, Awaitable, Callable, Collection, Dict, Optional, Union

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from agno.os.interfaces.github.events import GitHubEvent, ignore_reason, parse_event
from agno.os.interfaces.github.security import verify_signature
from agno.utils.log import log_error

EventHandler = Callable[[GitHubEvent], Union[Optional[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]]


def attach_routes(
    router: APIRouter,
    handler: EventHandler,
    secret: str,
    repositories: Collection[str],
    events: Collection[str],
    ignore_logins: Collection[str],
) -> APIRouter:
    @router.post(
        "/events",
        operation_id="github_events",
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
            payload = json.loads(body)
        except ValueError:
            raise HTTPException(status_code=400, detail="The delivery is not JSON")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="The delivery is not a JSON object")

        event = parse_event(name, delivery_id, payload)
        reason = "the delivery names no repository" if event is None else None
        if event is not None:
            reason = ignore_reason(event, repositories, events, ignore_logins)
        if event is None or reason is not None:
            return {"status": "ignored", "reason": reason}

        # GitHub does not retry a failed delivery on its own, so success is reported only once the
        # handler has recorded the event; a failure asks for a redelivery instead of losing it quietly.
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                result = await result
        except HTTPException:
            raise
        except Exception as exc:
            log_error(f"GitHub delivery {delivery_id} ({event.kind}) could not be recorded: {exc}")
            raise HTTPException(
                status_code=500, detail="The event could not be recorded; redeliver it from the webhook settings"
            )
        return JSONResponse(status_code=202, content={"status": "recorded", **(result or {})})

    return router
