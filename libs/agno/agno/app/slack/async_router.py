from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from agno.agent.agent import Agent
from agno.app.slack.security import verify_slack_signature
from agno.team.team import Team
from agno.tools.slack import SlackTools
from agno.utils.log import log_info


def get_async_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    router = APIRouter()

    @router.post("/slack/events")
    async def slack_events(request: Request, background_tasks: BackgroundTasks):
        body = await request.body()
        timestamp = request.headers.get("X-Slack-Request-Timestamp")
        slack_signature = request.headers.get("X-Slack-Signature", "")

        if not timestamp or not slack_signature:
            raise HTTPException(status_code=400, detail="Missing Slack headers")

        if not verify_slack_signature(body, timestamp, slack_signature):
            raise HTTPException(status_code=403, detail="Invalid signature")

        data = await request.json()

        # Handle URL verification
        if data.get("type") == "url_verification":
            return {"challenge": data.get("challenge")}

        # Process other event types (e.g., message events) asynchronously
        if "event" in data:
            event = data["event"]
            background_tasks.add_task(process_slack_event, event)

        return {"status": "ok"}

    async def process_slack_event(event: dict):
        log_info(f"Processing event: {event}")
        if event.get("type") == "message":
            if event.get("bot_id"):
                log_info("bot event")
            else:
                user = None
                message_text = event.get("text")
                channel_id = event.get("channel", "")
                user = event.get("user")
                if event.get("thread_ts"):
                    ts=event.get("thread_ts")
                else:
                    ts=event.get("ts")
                session=ts
                if agent:
                    response = await agent.arun(message_text, user_id=user if user else None, session_id=session)
                elif team:
                    response = await team.arun(message_text, user_id=user if user else None, session_id=session)  # type: ignore

                SlackTools().send_message_thread(channel=channel_id, text=response.content or "",ts=ts)

    return router
