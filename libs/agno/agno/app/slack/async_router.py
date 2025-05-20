import os
import hmac
import hashlib
import time
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from typing import Optional
from agno.agent.agent import Agent
from agno.media import Audio, File, Image, Video
from agno.team.team import Team
from agno.tools.slack import SlackTools
from agno.utils.log import log_error, log_info, log_warning

try:
    SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
except:
    log_error("Slack signin secret missing")
def get_async_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    
    router = APIRouter()
    def verify_slack_signature(body: bytes, timestamp: str, slack_signature: str) -> bool:
        if not SLACK_SIGNING_SECRET:
            raise HTTPException(status_code=500, detail="SLACK_SIGNING_SECRET is not set")

        # Ensure the request timestamp is recent (e.g., to prevent replay attacks)
        if abs(time.time() - int(timestamp)) > 60 * 5:
            return False

        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
        my_signature = "v0=" + hmac.new(
            SLACK_SIGNING_SECRET.encode("utf-8"), 
            sig_basestring.encode("utf-8"), 
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(my_signature, slack_signature)

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
        if event.get("type")=="message":
            if event.get("bot_id"):
                log_info("bot event")
            else:
                user=None
                message_text=event.get("text")
                channel_id=event.get("channel")
                if event.get("channel_type")=="im": 
                    user=event.get("user")
                if agent:
                    response = await agent.arun(message_text,user_id=user if user else None)
                elif team:
                    response = await team.arun(message_text,user_id=user if user else None)
                SlackTools().send_message(channel=channel_id if channel_id else None,text=response.content)
    return router