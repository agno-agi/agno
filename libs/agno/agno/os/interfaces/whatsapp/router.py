import base64
from os import getenv
from typing import Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.media import Audio, File, Image, Video
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.tools.whatsapp import WhatsAppTools
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.whatsapp import get_media_async, send_image_message_async, typing_indicator_async, upload_media_async
from agno.workflow import RemoteWorkflow, Workflow

from .security import validate_webhook_signature


class WhatsAppWebhookResponse(BaseModel):
    status: str = Field(default="ok", description="Processing status")


class WhatsAppVerifyResponse(BaseModel):
    challenge: str = Field(description="Challenge string echoed back to Meta")


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    show_reasoning: bool = False,
) -> APIRouter:
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    entity_type = "agent" if agent else "team" if team else "workflow" if workflow else "unknown"
    whatsapp_tools = WhatsAppTools()

    @router.get("/status")
    async def status():
        return {"status": "available"}

    @router.get(
        "/webhook",
        operation_id=f"whatsapp_verify_{entity_type}",
        name="whatsapp_verify",
        description="Handle WhatsApp webhook verification",
    )
    async def verify_webhook(request: Request):
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

    @router.post(
        "/webhook",
        operation_id=f"whatsapp_webhook_{entity_type}",
        name="whatsapp_webhook",
        description="Process incoming WhatsApp messages",
        response_model=WhatsAppWebhookResponse,
        responses={
            200: {"description": "Event processed successfully"},
            403: {"description": "Invalid webhook signature"},
        },
    )
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        payload = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")

        body = await request.json()

        # Extract earliest message timestamp for replay protection
        timestamp = _extract_earliest_timestamp(body)

        if not validate_webhook_signature(payload, signature, timestamp=timestamp):
            log_warning("Invalid webhook signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

        if body.get("object") != "whatsapp_business_account":
            log_warning(f"Received non-WhatsApp webhook object: {body.get('object')}")
            return WhatsAppWebhookResponse(status="ignored")

        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                messages = change.get("value", {}).get("messages", [])
                if not messages:
                    continue
                message = messages[0]
                background_tasks.add_task(process_message, message, agent, team, workflow)

        return WhatsAppWebhookResponse(status="processing")

    async def process_message(
        message: dict,
        agent: Optional[Union[Agent, RemoteAgent]],
        team: Optional[Union[Team, RemoteTeam]],
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    ):
        try:
            message_image = None
            message_video = None
            message_audio = None
            message_doc = None

            message_id = message.get("id")
            await typing_indicator_async(message_id)

            msg_type = message.get("type")

            if msg_type == "text":
                message_text = message["text"]["body"]

            elif msg_type == "image":
                message_text = message.get("image", {}).get("caption", "Describe the image")
                message_image = message["image"]["id"]

            elif msg_type == "video":
                message_text = message.get("video", {}).get("caption", "Describe the video")
                message_video = message["video"]["id"]

            elif msg_type == "audio":
                message_text = "Reply to audio"
                message_audio = message["audio"]["id"]

            elif msg_type == "document":
                message_text = message.get("document", {}).get("caption", "Process the document")
                message_doc = message["document"]["id"]

            elif msg_type == "interactive":
                interactive = message.get("interactive", {})
                interactive_type = interactive.get("type")
                if interactive_type == "button_reply":
                    reply = interactive["button_reply"]
                    message_text = f"[Button Selected] {reply['title']} (id: {reply['id']})"
                elif interactive_type == "list_reply":
                    reply = interactive["list_reply"]
                    message_text = f"[List Selected] {reply['title']} (id: {reply['id']})"
                else:
                    log_warning(f"Unknown interactive type: {interactive_type}")
                    return

            elif msg_type == "location":
                loc = message.get("location", {})
                name = loc.get("name", "Unknown")
                message_text = f"[Location] {name} ({loc.get('latitude')}, {loc.get('longitude')})"

            elif msg_type == "reaction":
                reaction = message.get("reaction", {})
                message_text = f"[Reaction] {reaction.get('emoji', '')} on message {reaction.get('message_id', '')}"

            elif msg_type == "contacts":
                contacts = message.get("contacts", [])
                names = [c.get("name", {}).get("formatted_name", "Unknown") for c in contacts]
                message_text = f"[Contacts Shared] {', '.join(names)}"

            elif msg_type == "sticker":
                message_text = "Sticker received"
                message_image = message.get("sticker", {}).get("id")

            else:
                log_warning(f"Unknown message type: {msg_type}")
                return

            phone_number = message["from"]
            log_info(f"Processing message from {phone_number}: {message_text}")

            if agent:
                response = await agent.arun(  # type: ignore[misc]
                    message_text,
                    user_id=phone_number,
                    session_id=f"wa:{phone_number}",
                    images=[Image(content=await get_media_async(message_image))] if message_image else None,
                    files=[File(content=await get_media_async(message_doc))] if message_doc else None,
                    videos=[Video(content=await get_media_async(message_video))] if message_video else None,
                    audio=[Audio(content=await get_media_async(message_audio))] if message_audio else None,
                )
            elif team:
                response = await team.arun(  # type: ignore
                    message_text,
                    user_id=phone_number,
                    session_id=f"wa:{phone_number}",
                    files=[File(content=await get_media_async(message_doc))] if message_doc else None,
                    images=[Image(content=await get_media_async(message_image))] if message_image else None,
                    videos=[Video(content=await get_media_async(message_video))] if message_video else None,
                    audio=[Audio(content=await get_media_async(message_audio))] if message_audio else None,
                )
            elif workflow:
                response = await workflow.arun(  # type: ignore
                    message_text,
                    user_id=phone_number,
                    session_id=f"wa:{phone_number}",
                    images=[Image(content=await get_media_async(message_image))] if message_image else None,
                    files=[File(content=await get_media_async(message_doc))] if message_doc else None,
                    videos=[Video(content=await get_media_async(message_video))] if message_video else None,
                    audio=[Audio(content=await get_media_async(message_audio))] if message_audio else None,
                )

            if response.status == "ERROR":
                _send_whatsapp_message(
                    whatsapp_tools,
                    phone_number,
                    "Sorry, there was an error processing your message. Please try again later.",
                )
                log_error(response.content)
                return

            if show_reasoning and hasattr(response, "reasoning_content") and response.reasoning_content:
                _send_whatsapp_message(
                    whatsapp_tools,
                    phone_number,
                    f"Reasoning: \n{response.reasoning_content}",
                    italics=True,
                )

            if response.images:
                await _upload_response_images(response, phone_number)
            else:
                _send_whatsapp_message(whatsapp_tools, phone_number, response.content or "")

        except Exception as e:
            log_error(f"Error processing message: {str(e)}")
            try:
                _send_whatsapp_message(
                    whatsapp_tools,
                    phone_number,
                    "Sorry, there was an error processing your message. Please try again later.",
                )
            except Exception as send_error:
                log_error(f"Error sending error message: {str(send_error)}")

    async def _upload_response_images(response, recipient: str):
        for img in response.images:
            image_content = img.content
            image_bytes = None
            if isinstance(image_content, bytes):
                try:
                    decoded_string = image_content.decode("utf-8")
                    image_bytes = base64.b64decode(decoded_string)
                except UnicodeDecodeError:
                    image_bytes = image_content
            elif isinstance(image_content, str):
                image_bytes = base64.b64decode(image_content)
            else:
                log_error(f"Unexpected image content type: {type(image_content)} for user {recipient}")

            if image_bytes:
                media_id = await upload_media_async(media_data=image_bytes, mime_type="image/png", filename="image.png")
                await send_image_message_async(media_id=media_id, recipient=recipient, text=response.content)
            else:
                log_warning(f"Could not process image content for user {recipient}. Type: {type(image_content)}")
                _send_whatsapp_message(whatsapp_tools, recipient, response.content or "")

    def _send_whatsapp_message(tools: WhatsAppTools, recipient: str, message: str, italics: bool = False):
        def _format(text: str) -> str:
            if italics:
                return "\n".join([f"_{line}_" for line in text.split("\n")])
            return text

        if len(message) <= 4096:
            tools.send_text_message(recipient=recipient, text=_format(message))
            return

        message_batches = [message[i : i + 4000] for i in range(0, len(message), 4000)]
        for i, batch in enumerate(message_batches, 1):
            batch_message = f"[{i}/{len(message_batches)}] {batch}"
            tools.send_text_message(recipient=recipient, text=_format(batch_message))

    def _extract_earliest_timestamp(body: dict) -> Optional[int]:
        timestamps = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    ts = msg.get("timestamp")
                    if ts:
                        try:
                            timestamps.append(int(ts))
                        except (ValueError, TypeError):
                            pass
        return min(timestamps) if timestamps else None

    return router
