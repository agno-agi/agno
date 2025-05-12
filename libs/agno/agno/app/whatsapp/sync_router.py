from typing import Optional
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse
from agno.media import Audio,Video,Image
from agno.agent.agent import Agent
from agno.team.team import Team
from agno.tools.whatsapp import WhatsAppTools

from .security import validate_webhook_signature
from .wappreq import VERIFY_TOKEN,get_media
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
                    if message.get("type") == "text":
                        # Extract message details
                        message_text = message["text"]["body"]
                        message_image = None
                        message_video = None
                        message_audio = None
                    elif message.get("type") == "image":
                        try:
                            message_text = message["image"]["caption"]
                        except:
                            message_text = "Describe the image"
                        message_image = message["image"]["id"]
                        message_video = None
                        message_audio = None
                    elif message.get("type") == "video":
                        try:
                            message_text = message["video"]["caption"]
                        except:
                            message_text = "Describe the video"
                        message_video = message["video"]["id"]
                        message_image = None
                        message_audio = None
                    elif message.get("type") == "audio":
                        message_text = "reply to audio"
                        message_audio = message["audio"]["id"]
                        message_image = None
                        message_video = None
                    else:
                        continue
                    phone_number = message["from"]
                    logger.info(f"Processing message from {phone_number}: {message_text}")
                    # Generate and send response
                    if agent:
                        response = agent.run(message_text,user_id=phone_number,
                                             images=[Image(content=get_media(message_image))] if message_image else None,
                                             videos=[Video(content=get_media(message_video))] if message_video else None,
                                             audio=[Audio(content=get_media(message_audio))] if message_audio else None,)
                    elif team:
                        response = team.run(message_text,user_id=phone_number,
                                             images=[Image(content=get_media(message_image))] if message_image else None,
                                             videos=[Video(content=get_media(message_video))] if message_video else None,
                                             audio=[Audio(content=get_media(message_audio))] if message_audio else None,)
                    WhatsAppTools().send_text_message_sync(
                        recipient=phone_number, text=response.content
                    )
                    logger.info(f"Response \n {response.content} \n sent to {phone_number}")

            return {"status": "ok"}

        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))


    return router
