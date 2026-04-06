from __future__ import annotations

from ssl import SSLContext
from typing import Dict, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.slack._processing import (
    IGNORED_SUBTYPES,
    build_processing_config,
    handle_thread_started,
    process_slack_event,
    stream_slack_response,
)
from agno.os.interfaces.slack.security import verify_slack_signature
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


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
    config = build_processing_config(
        agent=agent,
        team=team,
        workflow=workflow,
        reply_to_mentions_only=reply_to_mentions_only,
        token=token,
        streaming=streaming,
        loading_messages=loading_messages,
        task_display_mode=task_display_mode,
        loading_text=loading_text,
        suggested_prompts=suggested_prompts,
        ssl=ssl,
        buffer_size=buffer_size,
        max_file_size=max_file_size,
        resolve_user_identity=resolve_user_identity,
    )

    # Multiple Slack instances can be mounted on one FastAPI app (e.g. /research
    # and /analyst). op_suffix makes each operation_id unique to avoid collisions.
    op_suffix = config.entity_name.lower().replace(" ", "_")

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
                background_tasks.add_task(handle_thread_started, event, config)
            # Bot self-loop prevention: check bot_id at both the top-level event
            # and inside message_changed's nested "message" object. Without the
            # nested check, edited bot messages would be reprocessed as new events.
            elif (
                event.get("bot_id")
                or (event.get("message") or {}).get("bot_id")
                or event.get("subtype") in IGNORED_SUBTYPES
            ):
                pass
            elif streaming:
                background_tasks.add_task(stream_slack_response, data, config)
            else:
                background_tasks.add_task(process_slack_event, data, config)

        return SlackEventResponse(status="ok")

    return router
