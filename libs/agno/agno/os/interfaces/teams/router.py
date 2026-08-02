import asyncio
from time import time
from typing import Any, Literal, NamedTuple, Optional, Type, Union
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.os.interfaces.teams.helpers import (
    TeamsConfig,
    build_conversation_ref,
    download_attachments_async,
    extract_activity_content,
    merge_conversation_ref,
    send_teams_message_async,
    typing_indicator_async,
)
from agno.os.interfaces.teams.security import validate_bot_framework_jwt
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

_ERROR_MESSAGE = "Sorry, there was an error processing your message. Please try again later."
_SESSION_RESET_MESSAGE = "New conversation started!"

_REASONING_SKIP_PREFIXES = ("Action:", "Next Action:", "Confidence:")


class _SessionConfig(NamedTuple):
    session_type: SessionType
    session_class: Type[Any]
    id_field: str
    db: Any
    has_db: bool
    is_async_db: bool


_SESSION_DISPATCH = {
    "agent": (SessionType.AGENT, AgentSession, "agent_id"),
    "team": (SessionType.TEAM, TeamSession, "team_id"),
    "workflow": (SessionType.WORKFLOW, WorkflowSession, "workflow_id"),
}


def _resolve_session_config(entity: Any, entity_type: str) -> _SessionConfig:
    session_type, session_class, id_field = _SESSION_DISPATCH[entity_type]
    db = getattr(entity, "db", None)
    return _SessionConfig(
        session_type=session_type,
        session_class=session_class,
        id_field=id_field,
        db=db,
        has_db=isinstance(db, (BaseDb, AsyncBaseDb)),
        is_async_db=isinstance(db, AsyncBaseDb),
    )


def _format_reasoning(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped in ("—", "---"):
            continue
        if stripped.startswith(_REASONING_SKIP_PREFIXES):
            continue
        lines.append(stripped)
    return "\n".join(lines)


class TeamsWebhookResponse(BaseModel):
    status: str = Field(default="ok", description="Processing status")


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    show_reasoning: bool = False,
    send_user_id_to_context: bool = False,
    app_id: Optional[str] = None,
    app_password: Optional[str] = None,
    tenant_id: Optional[str] = None,
    app_type: Optional[str] = None,
    request_timeout: int = 30,
) -> APIRouter:
    """Attach ``/status`` and ``/messages`` routes for a Teams-bound entity.

    Exactly one of ``agent`` / ``team`` / ``workflow`` must be provided;
    remaining arguments configure webhook processing (reasoning echo, user
    context injection) and Bot Framework credentials (falling back to the
    ``MICROSOFT_APP_*`` env vars via :meth:`TeamsConfig.init`).
    """
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    entity = agent or team or workflow
    entity_type: Literal["agent", "team", "workflow"] = "agent" if agent else "team" if team else "workflow"
    raw_name = getattr(entity, "name", None)
    entity_name = raw_name if isinstance(raw_name, str) else entity_type
    op_suffix = entity_name.lower().replace(" ", "_")
    entity_id = getattr(entity, "id", None) or entity_name

    session_config = _resolve_session_config(entity, entity_type)

    config = TeamsConfig.init(
        app_id=app_id,
        app_password=app_password,
        tenant_id=tenant_id,
        app_type=app_type,
        request_timeout=request_timeout,
    )

    @router.get("/status", operation_id=f"teams_status_{op_suffix}")
    async def status():
        return {"status": "available"}

    @router.post(
        "/messages",
        operation_id=f"teams_webhook_{op_suffix}",
        name="teams_webhook",
        description="Process inbound Microsoft Teams Bot Framework activities",
        response_model=TeamsWebhookResponse,
        responses={
            200: {"description": "Activity accepted"},
            403: {"description": "Invalid Bot Framework JWT"},
        },
    )
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        auth_header = request.headers.get("Authorization")
        if not validate_bot_framework_jwt(auth_header, config.app_id):
            log_warning("Rejected inbound Teams activity: JWT validation failed")
            raise HTTPException(status_code=403, detail="Invalid Bot Framework token")

        try:
            activity = await request.json()
        except Exception as e:
            log_warning(f"Malformed activity payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        background_tasks.add_task(process_activity, activity)
        return TeamsWebhookResponse(status="processing")

    async def process_activity(activity: dict):
        activity_type = activity.get("type")
        service_url = activity.get("serviceUrl")
        conversation = activity.get("conversation") or {}
        conversation_id = conversation.get("id")
        activity_id = activity.get("id")
        sender = activity.get("from") or {}
        user_id = sender.get("aadObjectId") or sender.get("id")
        bot_identity: Optional[dict] = activity.get("recipient") or None

        if activity_type in ("conversationUpdate", "contactRelationUpdate"):
            return

        if activity_type != "message":
            log_info(f"Ignoring activity type: {activity_type}")
            return

        if not service_url or not conversation_id or not user_id:
            log_warning("Activity missing serviceUrl / conversation.id / from.id, skipping")
            return

        try:
            await typing_indicator_async(service_url, conversation_id, config, activity_id, bot_identity=bot_identity)

            parsed = extract_activity_content(activity)
            if parsed is None:
                await send_teams_message_async(
                    service_url,
                    conversation_id,
                    "Sorry, that message type isn't supported yet.",
                    config,
                    reply_to_activity_id=activity_id,
                    bot_identity=bot_identity,
                )
                return

            if parsed.text.strip().lower() == "/new":
                if not session_config.has_db:
                    await send_teams_message_async(
                        service_url,
                        conversation_id,
                        "Session reset requires storage to be configured.",
                        config,
                        reply_to_activity_id=activity_id,
                        bot_identity=bot_identity,
                    )
                    return
                try:
                    new_session_id = f"teams:{entity_id}:{user_id}:{uuid4().hex[:8]}"
                    now = int(time())
                    new_session = session_config.session_class(
                        session_id=new_session_id,
                        user_id=user_id,
                        created_at=now,
                        updated_at=now,
                        **{session_config.id_field: entity_id},
                    )
                    if session_config.is_async_db:
                        await session_config.db.upsert_session(new_session)
                    else:
                        session_config.db.upsert_session(new_session)
                    await send_teams_message_async(
                        service_url,
                        conversation_id,
                        _SESSION_RESET_MESSAGE,
                        config,
                        reply_to_activity_id=activity_id,
                        bot_identity=bot_identity,
                    )
                except Exception as e:
                    log_warning(f"Failed to persist /new session: {e}")
                    await send_teams_message_async(
                        service_url,
                        conversation_id,
                        _ERROR_MESSAGE,
                        config,
                        reply_to_activity_id=activity_id,
                        bot_identity=bot_identity,
                    )
                return

            log_info(f"Processing Teams message from {user_id[:12]}: {parsed.text}")

            default_session_id = f"teams:{entity_id}:{user_id}"
            session_id = default_session_id
            latest_session = None
            if session_config.has_db:
                try:
                    session_filter = dict(
                        session_type=session_config.session_type,
                        user_id=user_id,
                        component_id=entity_id,
                        limit=1,
                        sort_by="updated_at",
                        sort_order="desc",
                    )
                    if session_config.is_async_db:
                        sessions = await session_config.db.get_sessions(**session_filter)
                    else:
                        sessions = session_config.db.get_sessions(**session_filter)
                    if sessions:
                        latest_session = sessions[0]
                        session_id = latest_session.session_id
                except Exception as e:
                    log_warning(f"Session lookup failed, using default: {e}")

            media_kwargs, skipped_media = await download_attachments_async(parsed, config)
            run_kwargs: dict = {
                "user_id": user_id,
                "session_id": session_id,
                **media_kwargs,
            }

            if skipped_media:
                notice = "[Some attachments could not be downloaded: " + ", ".join(skipped_media) + "]\n\n"
                parsed.text = notice + parsed.text

            if send_user_id_to_context:
                run_kwargs["dependencies"] = {
                    "Teams user id": user_id,
                    "Teams conversation id": conversation_id,
                }
                run_kwargs["add_dependencies_to_context"] = True

            async def _keep_typing():
                try:
                    while True:
                        await asyncio.sleep(15)
                        await typing_indicator_async(
                            service_url, conversation_id, config, activity_id, bot_identity=bot_identity
                        )
                except asyncio.CancelledError:
                    pass

            typing_task = asyncio.create_task(_keep_typing())
            try:
                response = await entity.arun(parsed.text, **run_kwargs)  # type: ignore[union-attr]
            finally:
                typing_task.cancel()

            if session_config.has_db:
                try:
                    if session_config.is_async_db:
                        sessions = await session_config.db.get_sessions(
                            session_type=session_config.session_type,
                            user_id=user_id,
                            component_id=entity_id,
                            limit=1,
                            sort_by="updated_at",
                            sort_order="desc",
                        )
                    else:
                        sessions = session_config.db.get_sessions(
                            session_type=session_config.session_type,
                            user_id=user_id,
                            component_id=entity_id,
                            limit=1,
                            sort_by="updated_at",
                            sort_order="desc",
                        )
                    if sessions:
                        current = sessions[0]
                        ref = build_conversation_ref(service_url, conversation_id, bot_identity)
                        current.session_data = merge_conversation_ref(current.session_data, ref)
                        if session_config.is_async_db:
                            await session_config.db.upsert_session(current)
                        else:
                            session_config.db.upsert_session(current)
                except Exception as e:
                    log_warning(f"Could not persist conversation reference (non-fatal): {e}")

            if response.status == "ERROR":
                await send_teams_message_async(
                    service_url,
                    conversation_id,
                    _ERROR_MESSAGE,
                    config,
                    reply_to_activity_id=activity_id,
                    bot_identity=bot_identity,
                )
                log_error(response.content)
                return

            if show_reasoning and hasattr(response, "reasoning_content") and response.reasoning_content:
                reasoning = _format_reasoning(response.reasoning_content)
                if reasoning:
                    await send_teams_message_async(
                        service_url,
                        conversation_id,
                        reasoning,
                        config,
                        reply_to_activity_id=activity_id,
                        italics=True,
                        bot_identity=bot_identity,
                    )

            if response.content:
                await send_teams_message_async(
                    service_url,
                    conversation_id,
                    response.content,
                    config,
                    reply_to_activity_id=activity_id,
                    bot_identity=bot_identity,
                )

        except Exception as e:
            log_error(f"Error processing Teams activity: {e}")
            try:
                await send_teams_message_async(
                    service_url,
                    conversation_id,
                    _ERROR_MESSAGE,
                    config,
                    reply_to_activity_id=activity_id,
                    bot_identity=bot_identity,
                )
            except Exception as send_error:
                log_error(f"Error sending error message: {send_error}")

    return router
