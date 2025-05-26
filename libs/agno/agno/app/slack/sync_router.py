from typing import Optional, cast

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from agno.agent.agent import Agent
from agno.app.slack.security import verify_slack_signature
from agno.team.team import Team
from agno.tools.slack import SlackTools
from agno.utils.log import log_info


def get_sync_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    router = APIRouter()

    @router.post("/slack/events")
    def slack_events(request: Request, background_tasks: BackgroundTasks):
        body = cast(bytes, request.body())
        timestamp = request.headers.get("X-Slack-Request-Timestamp")
        slack_signature = request.headers.get("X-Slack-Signature", "")

        if not timestamp or not slack_signature:
            raise HTTPException(status_code=400, detail="Missing Slack headers")

        if not verify_slack_signature(body, timestamp, slack_signature):
            raise HTTPException(status_code=403, detail="Invalid signature")

        data = cast(dict, request.json())

        # Handle URL verification
        if data.get("type") == "url_verification":
            return {"challenge": data.get("challenge")}

        # Process other event types (e.g., message events) asynchronously
        if "event" in data:
            event = data["event"]
            background_tasks.add_task(process_slack_event, event)

        return {"status": "ok"}

    def process_slack_event(event: dict):
        log_info(f"Processing event: {event}")
        if event.get("type") == "message":
            if event.get("bot_id"):
                pass
            else:
                user = None
                message_text = event.get("text")
                channel_id = event.get("channel", "")
                if event.get("channel_type") == "im":
                    user = event.get("user")
                if agent:
                    response = agent.run(message_text, user_id=user if user else None)
                elif team:
                    response = team.run(message_text, user_id=user if user else None)  # type: ignore

                SlackTools().send_message(channel=channel_id, text=response.content or "")

    return router
