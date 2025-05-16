from typing import Optional

from os import getenv
from agno.utils.whatsapp import get_media_async, send_image_message_async, upload_media_async
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

from agno.agent.agent import Agent
from agno.media import Audio, File, Image, Video
from agno.team.team import Team
from agno.tools.whatsapp import WhatsAppTools
from agno.utils.log import log_error, log_info, log_warning

from .security import validate_webhook_signature


def get_async_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    router = APIRouter()

    if agent is None and team is None:
        raise ValueError("Either agent or team must be provided.")

    @router.get("/status")
    async def status():
        return {"status": "available"}

    @router.get("/webhook")
    async def verify_webhook(request: Request):
        """Handle WhatsApp webhook verification"""
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        
        verify_token = getenv("WHATSAPP_VERIFY_TOKEN")
        if not verify_token:
            raise HTTPException(status_code=500, detail="WHATSAPP_VERIFY_TOKEN is not set")

        if mode == "subscribe" and token == verify_token:
            if not challenge:
                raise HTTPException(status_code=400, detail="No challenge received")
            return PlainTextResponse(content=challenge)

        raise HTTPException(status_code=403, detail="Invalid verify token or mode")

    @router.post("/webhook")
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        """Handle incoming WhatsApp messages"""
        try:
            # Get raw payload for signature validation
            payload = await request.body()
            signature = request.headers.get("X-Hub-Signature-256")

            # Validate webhook signature
            if not validate_webhook_signature(payload, signature):
                log_warning("Invalid webhook signature")
                raise HTTPException(status_code=403, detail="Invalid signature")

            body = await request.json()

            # Validate webhook data
            if body.get("object") != "whatsapp_business_account":
                log_warning(f"Received non-WhatsApp webhook object: {body.get('object')}")
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

    async def process_message(message: dict, agent: Optional[Agent], team: Optional[Team]):
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
            log_info(f"Processing message from {phone_number}: {message_text}")

            # Generate and send response
            if agent:
                response = await agent.arun(
                    message_text,
                    user_id=phone_number,
                    images=[Image(content=await get_media_async(message_image))] if message_image else None,
                    files=[File(content=await get_media_async(message_doc))] if message_doc else None,
                    videos=[Video(content=await get_media_async(message_video))] if message_video else None,
                    audio=[Audio(content=await get_media_async(message_audio))] if message_audio else None,
                )
            elif team:
                response = await team.arun(
                    message_text,
                    user_id=phone_number,
                    files=[File(content=await get_media_async(message_doc))] if message_doc else None,
                    images=[Image(content=await get_media_async(message_image))] if message_image else None,
                    videos=[Video(content=await get_media_async(message_video))] if message_video else None,
                    audio=[Audio(content=await get_media_async(message_audio))] if message_audio else None,
                )

            if response.reasoning_content:
                await _send_whatsapp_message(phone_number, f"Reasoning: \n{response.reasoning_content}", italics=True)
                
            if response.images:
                from io import BytesIO
                # Convert content to buffer
                image_buffer = BytesIO(response.images[0].content)
                media_id = await upload_media_async(file_data=image_buffer, mime_type="image/png", filename="image.png")
                await send_image_message_async(media_id=media_id, recipient=phone_number, text=response.content)
                
            await _send_whatsapp_message(phone_number, response.content)

        except Exception as e:
            log_error(f"Error processing message: {str(e)}")
            # Optionally send an error message to the user
            try:
                await _send_whatsapp_message(
                    phone_number, "Sorry, there was an error processing your message. Please try again later."
                )
            except Exception as send_error:
                log_error(f"Error sending error message: {str(send_error)}")

    async def _send_whatsapp_message(recipient: str, message: str, italics: bool = False):
        if len(message) <= 4096:
            if italics:
                # Handle multi-line messages by making each line italic
                formatted_message = "\n".join([f"_{line}_" for line in message.split("\n")])
                await WhatsAppTools().send_text_message_async(recipient=recipient, text=formatted_message)
            else:
                await WhatsAppTools().send_text_message_async(recipient=recipient, text=message)
            return

        # Split message into batches of 4000 characters (WhatsApp message limit is 4096)
        message_batches = [message[i : i + 4000] for i in range(0, len(message), 4000)]

        # Add a prefix with the batch number
        for i, batch in enumerate(message_batches, 1):
            batch_message = f"[{i}/{len(message_batches)}] {batch}"
            if italics:
                # Handle multi-line messages by making each line italic
                formatted_batch = "\n".join([f"_{line}_" for line in batch_message.split("\n")])
                await WhatsAppTools().send_text_message_async(recipient=recipient, text=formatted_batch)
            else:
                await WhatsAppTools().send_text_message_async(recipient=recipient, text=batch_message)

    return router
