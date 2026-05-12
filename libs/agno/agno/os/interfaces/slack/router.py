from __future__ import annotations

import json
from ssl import SSLContext
from typing import Dict, List, Literal, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent

try:
    from agno.os.interfaces.slack.event_handler import SlackEventHandler
    from agno.os.interfaces.slack.helpers import BotNameResolver
    from agno.os.interfaces.slack.hitl import HITLHandler
except ImportError as e:
    raise ImportError("Slack dependencies not installed. Please install using `pip install 'agno[slack]'`") from e

from agno.os.interfaces.slack.security import verify_slack_signature
from agno.team import RemoteTeam, Team
from agno.tools.slack import SlackTools
from agno.workflow import RemoteWorkflow, Workflow

# Slack sends lifecycle events for bots with these subtypes. Without this
# filter the router would try to process its own messages, causing infinite loops.
_IGNORED_SUBTYPES = frozenset(
    {
        "bot_message",
        "bot_add",
        "bot_remove",
        "bot_enable",
        "bot_disable",
        "message_changed",
        "message_deleted",
    }
)

class SlackEventResponse(BaseModel):
    status: str = Field(default="ok")


class SlackChallengeResponse(BaseModel):
    challenge: str = Field(description="Challenge string to echo back to Slack")


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    reply_to_mentions_only: bool = True,
    token: Optional[str] = None,
    signing_secret: Optional[str] = None,
    streaming: bool = True,
    loading_messages: Optional[List[str]] = None,
    task_display_mode: str = "plan",
    loading_text: str = "Thinking...",
    suggested_prompts: Optional[List[Dict[str, str]]] = None,
    ssl: Optional[SSLContext] = None,
    buffer_size: int = 100,
    max_file_size: int = 1_073_741_824,  # 1GB
    resolve_user_identity: bool = False,
) -> APIRouter:
    # Inner functions capture config via closure to keep each instance isolated
    entity = agent or team or workflow
    # entity_type drives event dispatch (agent vs team vs workflow events)
    entity_type: Literal["agent", "team", "workflow"] = "agent" if agent else "team" if team else "workflow"
    # Member HITL needs member runs embedded on Team run (member_responses).
    # Without this, continue_run cannot reliably reload member tool state from DB.
    if team is not None and not isinstance(team, RemoteTeam):
        team.store_member_responses = True
    raw_name = getattr(entity, "name", None)
    # entity_name labels task cards; entity_id namespaces session IDs
    entity_name = raw_name if isinstance(raw_name, str) else entity_type
    # Multiple Slack instances can be mounted on one FastAPI app (e.g. /research
    # and /analyst). op_suffix makes each operation_id unique to avoid collisions.
    op_suffix = entity_name.lower().replace(" ", "_")
    entity_id = getattr(entity, "id", None) or entity_name

    slack_tools = SlackTools(token=token, ssl=ssl, max_file_size=max_file_size)
    bot_name_resolver = BotNameResolver()
    if entity is None:
        raise ValueError("attach_routes requires agent, team, or workflow")
    hitl = HITLHandler(
        slack_tools=slack_tools,
        ssl=ssl,
        entity=entity,
        entity_id=entity_id,
        entity_name=entity_name,
        entity_type=entity_type,
        task_display_mode=task_display_mode,
        buffer_size=buffer_size,
    )
    event_handler = SlackEventHandler(
        slack_tools=slack_tools,
        ssl=ssl,
        entity=entity,
        entity_id=entity_id,
        entity_name=entity_name,
        entity_type=entity_type,
        bot_name_resolver=bot_name_resolver,
        reply_to_mentions_only=reply_to_mentions_only,
        resolve_user_identity=resolve_user_identity,
        loading_text=loading_text,
        loading_messages=loading_messages,
        task_display_mode=task_display_mode,
        buffer_size=buffer_size,
        suggested_prompts=suggested_prompts,
    )

    @router.post(
        "/events",
        operation_id=f"slack_events_{op_suffix}",
        name="slack_events",
        description="Process incoming Slack events",
        response_model=Union[SlackChallengeResponse, SlackEventResponse],
        response_model_exclude_none=True,
        responses={
            200: {"description": "Event processed successfully"},
            400: {"description": "Missing Slack headers"},
            403: {"description": "Invalid Slack signature"},
        },
    )
    async def slack_events(request: Request, background_tasks: BackgroundTasks):
        # ACK immediately, process in background. Slack retries after ~3s if it
        # doesn't get a 200, so long-running agent calls must not block the response.
        body = await request.body()
        timestamp = request.headers.get("X-Slack-Request-Timestamp")
        slack_signature = request.headers.get("X-Slack-Signature", "")

        if not timestamp or not slack_signature:
            raise HTTPException(status_code=400, detail="Missing Slack headers")

        if not verify_slack_signature(body, timestamp, slack_signature, signing_secret=signing_secret):
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Slack retries after ~3s if it doesn't get a 200. Since we ACK
        # immediately and process in background, retries are always duplicates.
        # Trade-off: if the server crashes mid-processing, the retried event
        # carrying the same payload won't be reprocessed — acceptable for chat.
        if request.headers.get("X-Slack-Retry-Num"):
            return SlackEventResponse(status="ok")

        data = await request.json()

        if data.get("type") == "url_verification":
            return SlackChallengeResponse(challenge=data.get("challenge"))

        if "event" in data:
            event = data["event"]
            event_type = event.get("type")
            # setSuggestedPrompts requires "Agents & AI Apps" mode (streaming UX only)
            if event_type == "assistant_thread_started" and streaming:
                background_tasks.add_task(event_handler.handle_thread_started, event)
            # Bot self-loop prevention: check bot_id at BOTH the top-level event
            # AND inside message_changed's nested "message" object. Slack puts
            # bot_id at different nesting levels depending on event shape — the
            # nested check catches edited bot messages that would otherwise be
            # reprocessed as new user events.
            elif (
                event.get("bot_id")
                or (event.get("message") or {}).get("bot_id")
                or event.get("subtype") in _IGNORED_SUBTYPES
            ):
                pass
            elif streaming:
                background_tasks.add_task(event_handler.handle_streaming, data)
            else:
                background_tasks.add_task(event_handler.handle_non_streaming, data)

        return SlackEventResponse(status="ok")

    @router.post(
        "/interactions",
        operation_id=f"slack_interactions_{op_suffix}",
        name="slack_interactions",
        description="Handle Slack interactive components (HITL buttons / form submit)",
        response_model=SlackEventResponse,
        response_model_exclude_none=True,
        responses={
            200: {"description": "Interaction accepted"},
            400: {"description": "Malformed interaction payload"},
            403: {"description": "Invalid Slack signature"},
        },
    )
    async def slack_interactions(request: Request, background_tasks: BackgroundTasks):
        body = await request.body()
        timestamp = request.headers.get("X-Slack-Request-Timestamp")
        slack_signature = request.headers.get("X-Slack-Signature", "")
        if not timestamp or not slack_signature:
            raise HTTPException(status_code=400, detail="Missing Slack headers")
        if not verify_slack_signature(body, timestamp, slack_signature, signing_secret=signing_secret):
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Pre-ack retry drop — Slack retries after ~3s if we don't ack. We ACK
        # below; any retry arriving before that gets the same 200 response.
        if request.headers.get("X-Slack-Retry-Num"):
            return SlackEventResponse(status="ok")

        # Slack sends interactive payloads as application/x-www-form-urlencoded
        # with a single form field `payload=<URL-encoded JSON>`.
        form = await request.form()
        payload_raw = form.get("payload")
        if not isinstance(payload_raw, str) or not payload_raw:
            raise HTTPException(status_code=400, detail="Missing payload")
        try:
            payload = json.loads(payload_raw)
        except Exception:
            raise HTTPException(status_code=400, detail="Malformed payload JSON")

        # Dispatch by action_id — only block_actions payloads carry HITL clicks.
        if payload.get("type") != "block_actions":
            return SlackEventResponse(status="ok")
        actions = payload.get("actions") or []
        if not actions:
            return SlackEventResponse(status="ok")
        action_id = actions[0].get("action_id", "")

        if action_id == "row_approve":
            background_tasks.add_task(hitl.handle_row_approve, payload)
        elif action_id == "row_reject":
            background_tasks.add_task(hitl.handle_row_reject, payload)
        elif action_id == "submit_pause":
            background_tasks.add_task(hitl.handle_submit, payload)
        # Silently ignore unknown action_ids — a non-HITL Slack app sharing
        # the same endpoint might also post interactions here.

        return SlackEventResponse(status="ok")

    return router
