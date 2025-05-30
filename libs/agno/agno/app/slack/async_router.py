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
            if event.get("bot_id"):
                log_info("bot event")
                pass
            else:
                background_tasks.add_task(_process_slack_event, event)

        return {"status": "ok"}

    async def _process_slack_event(event: dict):
        if event.get("type") == "message":
            user = None
            message_text = event.get("text")
            channel_id = event.get("channel", "")
            user = event.get("user")
            if event.get("thread_ts"):
                ts = event.get("thread_ts", "")
            else:
                ts = event.get("ts", "")

            # Use the timestamp as the session id, so that each thread is a separate session
            session_id = ts

            if agent:
                response = await agent.arun(message_text, user_id=user if user else None, session_id=session_id)
            elif team:
                response = await team.arun(message_text, user_id=user if user else None, session_id=session_id)  # type: ignore

            if response.reasoning_content:
                _send_slack_message(
                    channel=channel_id, message=f"Reasoning: \n{response.reasoning_content}", thread_ts=ts, italics=True
                )
            _send_slack_message(channel=channel_id, message=response.content or "", thread_ts=ts)

    def _send_slack_message(channel: str, thread_ts: str, message: str, italics: bool = False):
        if len(message) <= 40000:
            if italics:
                # Handle multi-line messages by making each line italic
                formatted_message = "\n".join([f"_{line}_" for line in message.split("\n")])
                SlackTools().send_message_thread(channel=channel, text=formatted_message or "", thread_ts=thread_ts)
            else:
                SlackTools().send_message_thread(channel=channel, text=message or "", thread_ts=thread_ts)
            return

        # Split message into batches of 4000 characters (WhatsApp message limit is 4096)
        message_batches = [message[i : i + 40000] for i in range(0, len(message), 40000)]

        # Add a prefix with the batch number
        for i, batch in enumerate(message_batches, 1):
            batch_message = f"[{i}/{len(message_batches)}] {batch}"
            if italics:
                # Handle multi-line messages by making each line italic
                formatted_batch = "\n".join([f"_{line}_" for line in batch_message.split("\n")])
                SlackTools().send_message_thread(channel=channel, text=formatted_batch or "", thread_ts=thread_ts)
            else:
                SlackTools().send_message_thread(channel=channel, text=message or "", thread_ts=thread_ts)

    return router
