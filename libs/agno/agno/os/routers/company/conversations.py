"""Durable Company coordinator intake with prompt receipts and serialized turns."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from agno.company.conversation import aget_conversation_tasks, asubmit_conversation
from agno.os.auth import get_authentication_dependency
from agno.os.authz.run_context import request_authorization
from agno.os.middleware.user_scope import get_scoped_user_id, resolve_run_user_id
from agno.run import RunContext


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=100000)


def get_company_conversations_router(agent_os: Any) -> APIRouter:
    router = APIRouter(
        prefix="/company/conversations", tags=["Company conversations"], dependencies=[Depends(get_scoped_user_id)]
    )
    authentication = get_authentication_dependency(agent_os.settings)

    def context(request: Request, session_id: str) -> RunContext:
        return RunContext(
            run_id="",
            session_id=session_id,
            user_id=resolve_run_user_id(request),
            authorization=request_authorization(request),
        )

    @router.post("/{session_id}/messages", status_code=202)
    async def submit(session_id: str, body: ConversationMessage, request: Request, _: bool = Depends(authentication)):
        try:
            receipt = await asubmit_conversation(
                agent_os,
                body.message,
                context(request, session_id),
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {**receipt, "receipt": "Message received; coordinator turn submitted."}

    @router.get("/{session_id}/tasks")
    async def tasks(
        session_id: str, request: Request, origin_run_id: Optional[str] = None, _: bool = Depends(authentication)
    ):
        try:
            return await aget_conversation_tasks(agent_os, context(request, session_id), origin_run_id=origin_run_id)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    return router
