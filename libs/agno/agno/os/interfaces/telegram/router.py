import base64
import binascii
from typing import Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.media import Image
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.telegram import (
    get_bot_token,
    get_file_bytes_async,
    send_chat_action_async,
    send_photo_message_async,
    send_text_chunked_async,
)
from agno.workflow import RemoteWorkflow, Workflow

from .security import validate_webhook_secret_token


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
) -> APIRouter:
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    # Validate token is available at startup
    get_bot_token()

    @router.get("/status")
    async def status():
        return {"status": "available"}

    @router.post("/webhook")
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        try:
            secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if not validate_webhook_secret_token(secret_token):
                log_warning("Invalid webhook secret token")
                raise HTTPException(status_code=403, detail="Invalid secret token")

            body = await request.json()

            message = body.get("message")
            if not message:
                return {"status": "ignored"}

            background_tasks.add_task(process_message, message, agent, team, workflow)
            return {"status": "processing"}

        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error processing webhook: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def process_message(
        message: dict,
        agent: Optional[Union[Agent, RemoteAgent]],
        team: Optional[Union[Team, RemoteTeam]],
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    ):
        chat_id = message.get("chat", {}).get("id")
        if not chat_id:
            log_warning("Received message without chat_id")
            return

        try:
            message_image = None

            await send_chat_action_async(chat_id, "typing")

            if message.get("text"):
                message_text = message["text"]
            elif message.get("photo"):
                message_image = message["photo"][-1]["file_id"]
                message_text = message.get("caption", "Describe the image")
            else:
                return

            user_id = str(message.get("from", {}).get("id", chat_id))
            session_id = f"tg:{chat_id}"
            log_info(f"Processing message from {user_id}: {message_text}")

            images = None
            if message_image:
                image_bytes = await get_file_bytes_async(message_image)
                if image_bytes:
                    images = [Image(content=image_bytes)]

            response = None
            if agent:
                response = await agent.arun(
                    message_text,
                    user_id=user_id,
                    session_id=session_id,
                    images=images,
                )
            elif team:
                response = await team.arun(  # type: ignore
                    message_text,
                    user_id=user_id,
                    session_id=session_id,
                    images=images,
                )
            elif workflow:
                response = await workflow.arun(  # type: ignore
                    message_text,
                    user_id=user_id,
                    session_id=session_id,
                    images=images,
                )

            if not response:
                return

            if response.status == "ERROR":
                await send_text_chunked_async(
                    chat_id, "Sorry, there was an error processing your message. Please try again later."
                )
                log_error(response.content)
                return

            if response.reasoning_content:
                await send_text_chunked_async(chat_id, f"Reasoning: \n{response.reasoning_content}")

            # Outbound image handling
            if response.images:
                any_sent = False
                for image in response.images:
                    image_bytes_out = None
                    content = image.content
                    if isinstance(content, bytes):
                        try:
                            decoded = content.decode("utf-8")
                            image_bytes_out = base64.b64decode(decoded)
                        except (UnicodeDecodeError, binascii.Error):
                            image_bytes_out = content
                    elif isinstance(content, str):
                        try:
                            image_bytes_out = base64.b64decode(content)
                        except binascii.Error:
                            log_warning(f"Invalid base64 image content for chat {chat_id}")
                    else:
                        log_warning(f"Unexpected image content type: {type(content)} for chat {chat_id}")

                    if image_bytes_out:
                        try:
                            await send_photo_message_async(
                                chat_id=chat_id,
                                photo_bytes=image_bytes_out,
                                caption=response.content[:1024] if response.content else None,
                            )
                            any_sent = True
                        except Exception as img_err:
                            log_error(f"Failed to send photo to chat {chat_id}: {img_err}")

                if not any_sent:
                    await send_text_chunked_async(chat_id, response.content or "")
            else:
                await send_text_chunked_async(chat_id, response.content or "")

        except Exception as e:
            log_error(f"Error processing message: {str(e)}")
            try:
                await send_text_chunked_async(
                    chat_id, "Sorry, there was an error processing your message. Please try again later."
                )
            except Exception as send_error:
                log_error(f"Error sending error message: {str(send_error)}")

    return router
