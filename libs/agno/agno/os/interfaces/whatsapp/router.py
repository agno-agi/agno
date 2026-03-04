import asyncio
from os import getenv
from typing import Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.media import Audio, File, Image, Video
from agno.os.interfaces.whatsapp.helpers import (
    extract_earliest_timestamp,
    send_whatsapp_message_async,
    upload_response_audio_async,
    upload_response_audio_single_async,
    upload_response_files_async,
    upload_response_images_async,
)
from agno.os.interfaces.whatsapp.security import validate_webhook_signature
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.whatsapp import get_media_async, typing_indicator_async
from agno.workflow import RemoteWorkflow, Workflow

_ERROR_MESSAGE = "Sorry, there was an error processing your message. Please try again later."


class WhatsAppWebhookResponse(BaseModel):
    status: str = Field(default="ok", description="Processing status")


class WhatsAppVerifyResponse(BaseModel):
    challenge: str = Field(description="Challenge string echoed back to Meta")


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    show_reasoning: bool = True,
    send_user_number_to_context: bool = False,
) -> APIRouter:
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    entity = agent or team or workflow
    entity_type = "agent" if agent else "team" if team else "workflow"
    raw_name = getattr(entity, "name", None)
    entity_name = raw_name if isinstance(raw_name, str) else entity_type
    # Unique suffix prevents operation_id collisions across mounted routers
    op_suffix = entity_name.lower().replace(" ", "_")

    @router.get("/status")
    async def status():
        return {"status": "available"}

    @router.get(
        "/webhook",
        operation_id=f"whatsapp_verify_{op_suffix}",
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
        operation_id=f"whatsapp_webhook_{op_suffix}",
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
        timestamp = extract_earliest_timestamp(body)

        if not validate_webhook_signature(payload, signature, timestamp=timestamp):
            log_warning("Invalid webhook signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

        if body.get("object") != "whatsapp_business_account":
            log_warning(f"Received non-WhatsApp webhook object: {body.get('object')}")
            return WhatsAppWebhookResponse(status="ignored")

        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                for message in change.get("value", {}).get("messages", []):
                    background_tasks.add_task(process_message, message)

        return WhatsAppWebhookResponse(status="processing")

    async def process_message(message: dict):
        phone_number = message["from"]
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
                log_info(message_text)

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
                    reply = interactive.get("button_reply", {})
                    message_text = reply.get("title", "")
                    log_info(f"Button reply: id={reply.get('id')} title={message_text}")
                elif interactive_type == "list_reply":
                    reply = interactive.get("list_reply", {})
                    message_text = reply.get("title", "")
                    description = reply.get("description", "")
                    if description:
                        message_text = f"{message_text}: {description}"
                    log_info(f"List reply: id={reply.get('id')} title={message_text}")
                else:
                    log_warning(f"Unknown interactive type: {interactive_type}")
                    return

            else:
                log_warning(f"Unknown message type: {msg_type}")
                return

            log_info(f"Processing message from {phone_number}: {message_text}")

            run_kwargs = {
                "user_id": phone_number,
                "session_id": f"wa:{phone_number}",
                "images": [Image(content=await get_media_async(message_image))] if message_image else None,
                "files": [File(content=await get_media_async(message_doc))] if message_doc else None,
                "videos": [Video(content=await get_media_async(message_video))] if message_video else None,
                "audio": [Audio(content=await get_media_async(message_audio))] if message_audio else None,
            }

            if send_user_number_to_context:
                run_kwargs["dependencies"] = {"User info": f"User's Whatsapp number = {phone_number}"}
                run_kwargs["add_dependencies_to_context"] = True

            # Refresh typing indicator every 20s while the agent runs
            # WhatsApp auto-dismisses the indicator after ~25s
            async def _keep_typing():
                try:
                    while True:
                        await asyncio.sleep(20)
                        await typing_indicator_async(message_id)
                except asyncio.CancelledError:
                    pass

            typing_task = asyncio.create_task(_keep_typing())
            try:
                response = await entity.arun(message_text, **run_kwargs)  # type: ignore[union-attr]
            finally:
                typing_task.cancel()

            if response.status == "ERROR":
                await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE)
                log_error(response.content)
                return

            if show_reasoning and hasattr(response, "reasoning_content") and response.reasoning_content:
                await send_whatsapp_message_async(
                    phone_number,
                    f"Reasoning:\n{response.reasoning_content}",
                    italics=True,
                )

            has_media = False
            if response.images:
                await upload_response_images_async(response, phone_number)
                has_media = True
            if response.files:
                await upload_response_files_async(response, phone_number)
                has_media = True
            if response.audio:
                await upload_response_audio_async(response, phone_number)
                has_media = True
            if response.response_audio:
                await upload_response_audio_single_async(response.response_audio, phone_number)
                has_media = True
            if not has_media:
                await send_whatsapp_message_async(phone_number, response.content or "")

        except Exception as e:
            log_error(f"Error processing message: {str(e)}")
            try:
                await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE)
            except Exception as send_error:
                log_error(f"Error sending error message: {str(send_error)}")

    return router
