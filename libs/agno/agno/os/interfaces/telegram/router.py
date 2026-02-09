import base64
import binascii
import os
from typing import Any, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.media import Image
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

from .security import validate_webhook_secret_token

AsyncTeleBot: Any = None
try:
    from telebot.async_telebot import AsyncTeleBot  # type: ignore[no-redef]
except ImportError:
    pass


def _require_telebot() -> None:
    if AsyncTeleBot is None:
        raise ImportError(
            "`telegram` interface requires the `pyTelegramBotAPI` package. "
            "Run `pip install pyTelegramBotAPI` or `pip install 'agno[telegram]'` to install it."
        )


def _get_bot_token() -> str:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN environment variable is not set")
    return token


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
) -> APIRouter:
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    # Validate token is available at startup
    _get_bot_token()

    async def _send_chat_action(chat_id: int, action: str) -> None:
        _require_telebot()
        bot = AsyncTeleBot(_get_bot_token())
        await bot.send_chat_action(chat_id, action)

    async def _get_file_bytes(file_id: str) -> Optional[bytes]:
        _require_telebot()
        try:
            bot = AsyncTeleBot(_get_bot_token())
            file_info = await bot.get_file(file_id)
            return await bot.download_file(file_info.file_path)
        except Exception as e:
            log_error(f"Error downloading file: {e}")
            return None

    async def _send_text_message(chat_id: int, text: str) -> None:
        _require_telebot()
        bot = AsyncTeleBot(_get_bot_token())
        await bot.send_message(chat_id, text)

    async def _send_text_chunked(chat_id: int, text: str, max_chars: int = 4000) -> None:
        _require_telebot()
        if len(text) <= 4096:
            await _send_text_message(chat_id, text)
            return
        chunks: List[str] = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
        bot = AsyncTeleBot(_get_bot_token())
        for i, chunk in enumerate(chunks, 1):
            await bot.send_message(chat_id, f"[{i}/{len(chunks)}] {chunk}")

    async def _send_photo_message(chat_id: int, photo_bytes: bytes, caption: Optional[str] = None) -> None:
        _require_telebot()
        bot = AsyncTeleBot(_get_bot_token())
        log_debug(f"Sending photo to chat_id={chat_id}, caption={caption[:50] if caption else None}")
        await bot.send_photo(chat_id, photo_bytes, caption=caption)

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

            await _send_chat_action(chat_id, "typing")

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
                image_bytes = await _get_file_bytes(message_image)
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
                await _send_text_chunked(
                    chat_id, "Sorry, there was an error processing your message. Please try again later."
                )
                log_error(response.content)
                return

            if response.reasoning_content:
                await _send_text_chunked(chat_id, f"Reasoning: \n{response.reasoning_content}")

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
                            await _send_photo_message(
                                chat_id=chat_id,
                                photo_bytes=image_bytes_out,
                                caption=response.content[:1024] if response.content else None,
                            )
                            any_sent = True
                        except Exception as img_err:
                            log_error(f"Failed to send photo to chat {chat_id}: {img_err}")

                if not any_sent:
                    await _send_text_chunked(chat_id, response.content or "")
            else:
                await _send_text_chunked(chat_id, response.content or "")

        except Exception as e:
            log_error(f"Error processing message: {str(e)}")
            try:
                await _send_text_chunked(
                    chat_id, "Sorry, there was an error processing your message. Please try again later."
                )
            except Exception as send_error:
                log_error(f"Error sending error message: {str(send_error)}")

    return router
