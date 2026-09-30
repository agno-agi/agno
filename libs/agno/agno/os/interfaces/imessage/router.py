import asyncio
import hmac
import json
from collections import OrderedDict
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set
from uuid import uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from agno.run.base import RunStatus
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.os.interfaces.imessage.imessage import IMessage


class _Handle(BaseModel):
    address: str = Field(min_length=1)


class _Chat(BaseModel):
    guid: str = Field(min_length=1)


class _Message(BaseModel):
    guid: str = Field(min_length=1)
    text: Optional[str] = None
    isFromMe: bool
    handle: Optional[_Handle] = None
    chats: List[_Chat] = Field(default_factory=list)
    associatedMessageType: Optional[int] = None
    isSystemMessage: bool = False
    itemType: Optional[int] = None


class IMessageResponse(BaseModel):
    status: str


def attach_routes(router: APIRouter, interface: "IMessage", use_async: bool = True) -> APIRouter:
    entity = interface.agent or interface.team or interface.workflow
    if entity is None:
        raise ValueError("IMessage requires an agent, team, or workflow")
    entity_type = "agent" if interface.agent is not None else "team" if interface.team is not None else "workflow"
    entity_id = entity.id or entity.name or entity_type
    allowed_senders = interface.allowed_senders

    # State is bounded and local to this router/process. Use one worker for this
    # initial implementation; acknowledgement is not durable queue acceptance.
    pending: Set[str] = set()
    completed: OrderedDict[str, None] = OrderedDict()
    processing_lock = asyncio.Lock()

    async def _send_text(chat_guid: str, text: str) -> None:
        async with httpx.AsyncClient(timeout=interface.timeout) as client:
            response = await client.post(
                f"{interface.server_url}/api/v1/message/text",
                params={"password": interface.password},
                json={
                    "chatGuid": chat_guid,
                    "tempGuid": str(uuid4()),
                    "message": text,
                    "method": "apple-script",
                },
            )
            # Do not expose HTTP exceptions containing the password-bearing URL.
            if not response.is_success:
                raise RuntimeError("BlueBubbles rejected the outgoing message")
            body = response.json()
            if body.get("status") != 200 or body.get("error"):
                raise RuntimeError("BlueBubbles failed to send the outgoing message")

    async def _process_message(message: _Message, chat_guid: str, sender: str) -> None:
        try:
            # Serialize runs to preserve conversation order and avoid concurrent
            # history writes on the reused entity in this first implementation.
            async with processing_lock:
                scope = json.dumps([interface.prefix, entity_type, entity_id, chat_guid, sender])
                run_kwargs: Dict[str, Any] = {
                    "input": message.text,
                    "user_id": f"imessage:{sender}",
                    "session_id": f"imessage:{sha256(scope.encode()).hexdigest()}",
                    "stream": False,
                }
                if use_async:
                    result = await entity.arun(**run_kwargs)
                else:
                    result = await asyncio.to_thread(entity.run, **run_kwargs)

                if result.status != RunStatus.completed:
                    log_error("iMessage run did not complete; no reply was sent")
                    return
                content = result.content
                if isinstance(content, BaseModel):
                    content = content.model_dump_json()
                elif content is not None and not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False, default=str)
                if content and content.strip():
                    await _send_text(chat_guid, content)
        except Exception as exc:
            # Provider errors may contain credentials or message content. Log only
            # the exception type; do not forward internal errors to the sender.
            log_error(f"iMessage processing failed ({type(exc).__name__})")
        finally:
            pending.discard(message.guid)
            # Remember failed attempts too: replaying a run can repeat tool side
            # effects or duplicate a reply whose send timed out after delivery.
            completed[message.guid] = None
            if len(completed) > 1024:
                completed.popitem(last=False)

    @router.get("/status", response_model=IMessageResponse, name="imessage_status")
    async def status() -> IMessageResponse:
        # Availability of the route, not a live check of the Mac or its account.
        return IMessageResponse(status="available")

    @router.post("/webhook", response_model=IMessageResponse, name="imessage_webhook")
    async def webhook(request: Request, background_tasks: BackgroundTasks) -> IMessageResponse:
        # BlueBubbles webhooks support a URL but do not attach a signature or
        # configurable authentication header. Use a separate shared URL token.
        token = request.query_params.get("token", "")
        if not hmac.compare_digest(token.encode(), interface.webhook_secret.encode()):
            raise HTTPException(status_code=403, detail="Invalid webhook token")
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid JSON") from None
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Expected a webhook object")
        if body.get("type") != "new-message":
            return IMessageResponse(status="ignored")
        try:
            message = _Message.model_validate(body.get("data"))
        except ValidationError:
            raise HTTPException(status_code=400, detail="Invalid message payload") from None

        if (
            message.isFromMe
            or message.isSystemMessage
            or message.itemType not in (None, 0)
            or message.associatedMessageType not in (None, 0)
            or not message.text
            or not message.text.strip()
            or message.handle is None
            or len(message.chats) != 1
        ):
            return IMessageResponse(status="ignored")

        chat_guid = message.chats[0].guid
        sender = message.handle.address
        # Only direct iMessage chats; ignore groups and SMS/RCS conversations.
        if not chat_guid.startswith("iMessage;-;"):
            return IMessageResponse(status="ignored")
        if allowed_senders is not None and sender not in allowed_senders:
            return IMessageResponse(status="ignored")
        if message.guid in pending or message.guid in completed:
            return IMessageResponse(status="duplicate")
        if len(pending) >= 100:
            raise HTTPException(status_code=503, detail="iMessage processing queue is full")

        pending.add(message.guid)
        background_tasks.add_task(_process_message, message, chat_guid, sender)
        return IMessageResponse(status="processing")

    return router
