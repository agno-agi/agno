from typing import Optional, cast
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse

from agno.agent.agent import Agent, RunResponse
from agno.team.team import Team

from .security import validate_webhook_signature
from .wappreq import VERIFY_TOKEN
logger = logging.getLogger(__name__)

def get_sync_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    router = APIRouter()

    if agent is None and team is None:
        raise ValueError("Either agent or team must be provided.")

    @router.get("/status")
    def status():
        return {"status": "available"}

    @router.get("/webhook")
    async def verify_webhook(request: Request):
        """Handle WhatsApp webhook verification"""
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            if not challenge:
                raise HTTPException(status_code=400, detail="No challenge received")
            return PlainTextResponse(content=challenge)

        raise HTTPException(status_code=403, detail="Invalid verify token or mode")

    @router.post("/webhook")
    def webhook(request: Request):
        """Handle incoming WhatsApp messages"""
        try:
            # Get raw payload for signature validation
            payload = request.body()
            signature = request.headers.get("X-Hub-Signature-256")

            # Validate webhook signature
            if not validate_webhook_signature(payload, signature):
                logger.warning("Invalid webhook signature")
                raise HTTPException(status_code=403, detail="Invalid signature")

            body = request.json()

            # Validate webhook data
            if body.get("object") != "whatsapp_business_account":
                logger.warning(
                    f"Received non-WhatsApp webhook object: {body.get('object')}"
                )
                return {"status": "ignored"}

            # Process messages
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    messages = change.get("value", {}).get("messages", [])

                    if not messages:
                        continue

                    message = messages[0]
                    if message.get("type") != "text":
                        continue

                    # Extract message details
                    phone_number = message["from"]
                    message_text = message["text"]["body"]

                    logger.info(f"Processing message from {phone_number}: {message_text}")

                    # Generate and send response
                    response = agent.run(message_text,user_id=phone_number)
                    agent.tools[0].send_text_message_sync(
                        recipient=phone_number, text=response.content
                    )
                    logger.info(f"Response \n {response.content} \n sent to {phone_number}")

            return {"status": "ok"}

        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
        if agent:
            run_response = cast(
                RunResponse,
                agent.run(...),
            )
        elif team:
            run_response = team.arun(...)
        return run_response.to_dict()

    return router
