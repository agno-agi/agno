import asyncio
import re
from os import getenv
from typing import Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.media import Audio, File, Image, Video
from agno.os.interfaces.whatsapp.helpers import (
    parse_whatsapp_message,
    send_whatsapp_message_async,
    upload_response_audio_async,
    upload_response_audio_single_async,
    upload_response_files_async,
    upload_response_images_async,
)
from agno.os.interfaces.whatsapp.security import extract_earliest_timestamp, validate_webhook_signature
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.whatsapp import get_media_async, typing_indicator_async
from agno.workflow import RemoteWorkflow, Workflow

_ERROR_MESSAGE = "Sorry, there was an error processing your message. Please try again later."

# Metadata lines from ReasoningTools that aren't useful to end users
_REASONING_SKIP_PREFIXES = ("Action:", "Next Action:", "Confidence:")


def _format_reasoning(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped in ("—", "---"):
            continue
        if stripped.startswith(_REASONING_SKIP_PREFIXES):
            continue
        # Convert markdown headers to WhatsApp bold
        header = re.match(r"^#{1,3}\s+(.+)$", stripped)
        if header:
            lines.append(f"*{header.group(1)}*")
        else:
            lines.append(stripped)
    return "\n".join(lines)


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

    @router.get("/status", operation_id=f"whatsapp_status_{op_suffix}")
    async def status():
        return {"status": "available"}

    @router.get(
        "/webhook",
        operation_id=f"whatsapp_verify_{op_suffix}",
        name="whatsapp_verify",
        description="Handle WhatsApp webhook verification",
    )
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
        """Handle incoming WhatsApp messages"""
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
            message_id = message.get("id")
            await typing_indicator_async(message_id)

            parsed = parse_whatsapp_message(message)
            if parsed is None:
                return

            log_info(f"Processing message from {phone_number}: {parsed.text}")

            run_kwargs = {
                "user_id": phone_number,
                "session_id": f"wa:{phone_number}",
                "images": [Image(content=await get_media_async(parsed.image_id))] if parsed.image_id else None,
                "files": [File(content=await get_media_async(parsed.doc_id))] if parsed.doc_id else None,
                "videos": [Video(content=await get_media_async(parsed.video_id))] if parsed.video_id else None,
                "audio": [Audio(content=await get_media_async(parsed.audio_id))] if parsed.audio_id else None,
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
                response = await entity.arun(parsed.text, **run_kwargs)  # type: ignore[union-attr]
            finally:
                typing_task.cancel()

            if response.status == "ERROR":
                await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE)
                log_error(response.content)
                return

            if show_reasoning and hasattr(response, "reasoning_content") and response.reasoning_content:
                reasoning = _format_reasoning(response.reasoning_content)
                if reasoning:
                    await send_whatsapp_message_async(phone_number, reasoning, italics=True)

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

            # WhatsApp tools (send_list_message, send_reply_buttons, etc.) send
            # messages directly during agent execution — skip duplicate content
            _WA_TOOL_NAMES = {
                "send_reply_buttons",
                "send_list_message",
                "send_image",
                "send_document",
                "send_location",
                "send_reaction",
                "mark_as_read",
            }
            response_tools = getattr(response, "tools", None)
            tools_sent_message = response_tools and any(
                t.tool_name in _WA_TOOL_NAMES for t in response_tools
            )
            if not has_media and not tools_sent_message:
                await send_whatsapp_message_async(phone_number, response.content or "")

        except Exception as e:
            log_error(f"Error processing message: {str(e)}")
            try:
                await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE)
            except Exception as send_error:
                log_error(f"Error sending error message: {str(send_error)}")

    return router
