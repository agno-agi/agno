from typing import Optional
import logging
from agno.media import Image, Video, Audio, File
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse
from agno.agent.agent import Agent
from agno.team.team import Team
from agno.utils.log import log_debug, log_error, log_warning
from .security import validate_webhook_signature
from .wappreq import VERIFY_TOKEN,get_media
from agno.tools.whatsapp import WhatsAppTools


def get_sync_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    router = APIRouter()

    if agent is None and team is None:
        raise ValueError("Either agent or team must be provided.")

    @router.get("/status")
    def status():
        return {"status": "available"}

    @router.get("/webhook")
    def verify_webhook(request: Request):
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
    def webhook(request: Request, background_tasks: BackgroundTasks):
        """Handle incoming WhatsApp messages"""
        try:
            # Get raw payload for signature validation
            payload = request.body()
            signature = request.headers.get("X-Hub-Signature-256")

            # Validate webhook signature
            if not validate_webhook_signature(payload, signature):
                log_warning("Invalid webhook signature")
                raise HTTPException(status_code=403, detail="Invalid signature")

            body = request.json()

            # Validate webhook data
            if body.get("object") != "whatsapp_business_account":
                log_warning(
                    f"Received non-WhatsApp webhook object: {body.get('object')}"
                )
                return {"status": "ignored"}

            # Process messages in background
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    messages = change.get("value", {}).get("messages", [])

                    if not messages:
                        continue

                    message = messages[0]
                    background_tasks.add_task(process_message, message, agent, team)

            return {"status": "processing"}

        except Exception as e:
            log_error(f"Error processing webhook: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def process_message(message: dict, agent: Optional[Agent], team: Optional[Team]):
        """Process a single WhatsApp message in the background"""
        try:
            message_image = None
            message_video = None
            message_audio = None
            message_doc = None
            
            if message.get("type") == "text":
                message_text = message["text"]["body"]
            elif message.get("type") == "image":
                try:
                    message_text = message["image"]["caption"]
                except Exception:
                    message_text = "Describe the image"
                message_image = message["image"]["id"]
            elif message.get("type") == "video":
                try:
                    message_text = message["video"]["caption"]
                except Exception:
                    message_text = "Describe the video"
                message_video = message["video"]["id"]
            elif message.get("type") == "audio":
                message_text = "Reply to audio"
                message_audio = message["audio"]["id"]
            elif message.get("type") == "document":
                message_text = "Process the document"
                message_doc = message["document"]["id"]
            else:
                return

            phone_number = message["from"]
            log_debug(f"Processing message from {phone_number}: {message_text}")

            # Generate and send response
            if agent:
                response = agent.run(
                    message_text,
                    user_id=phone_number,
                    images=[Image(content=get_media(message_image))] if message_image else None,
                    files=[File(content=get_media(message_doc))] if message_doc else None,
                    videos=[Video(content=get_media(message_video))] if message_video else None,
                    audio=[Audio(content=get_media(message_audio))] if message_audio else None,
                )
            elif team:
                response = team.run(
                    message_text,
                    user_id=phone_number,
                    files=[File(content=get_media(message_doc))] if message_doc else None,
                    images=[Image(content=get_media(message_image))] if message_image else None,
                    videos=[Video(content=get_media(message_video))] if message_video else None,
                    audio=[Audio(content=get_media(message_audio))] if message_audio else None,
                )

            if response.reasoning_content:
                _send_whatsapp_message(phone_number, f"Reasoning: \n{response.reasoning_content}", italics=True)
            
            _send_whatsapp_message(phone_number, response.content)

        except Exception as e:
            log_error(f"Error processing message: {str(e)}")
            # Optionally send an error message to the user
            try:
                _send_whatsapp_message(phone_number, "Sorry, there was an error processing your message. Please try again later.")
            except Exception as send_error:
                log_error(f"Error sending error message: {str(send_error)}")

    def _send_whatsapp_message(recipient: str, message: str, italics: bool = False):
        if len(message) <= 4096:
            WhatsAppTools().send_text_message_sync(recipient=recipient, text=f"_{message}_" if italics else message)
            return
        
        # Split message into batches of 4000 characters (WhatsApp message limit is 4096)
        message_batches = [message[i:i+4000] for i in range(0, len(message), 4000)]
        
        # Add a prefix with the batch number
        for i, batch in enumerate(message_batches, 1):
            batch_message = f"[{i}/{len(message_batches)}] {batch}"
            WhatsAppTools().send_text_message_sync(recipient=recipient, text=f"_{batch_message}_" if italics else batch_message)


    return router