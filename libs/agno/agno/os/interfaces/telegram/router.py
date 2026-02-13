import base64
import binascii
import os
import re
from typing import Any, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent
from agno.media import Audio, File, Image, Video
from agno.os.interfaces.telegram.security import validate_webhook_secret_token
from agno.team import RemoteTeam, Team
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

try:
    from telebot.async_telebot import AsyncTeleBot
except ImportError as e:
    raise ImportError("`pyTelegramBotAPI` not installed. Please install using `pip install 'agno[telegram]'`") from e

TG_MAX_MESSAGE_LENGTH = 4096
TG_CHUNK_SIZE = 4000
TG_MAX_CAPTION_LENGTH = 1024
TG_GROUP_CHAT_TYPES = {"group", "supergroup"}


class TelegramStatusResponse(BaseModel):
    status: str = Field(default="available")


class TelegramWebhookResponse(BaseModel):
    status: str = Field(description="Processing status")


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    reply_to_mentions_only: bool = True,
    reply_to_bot_messages: bool = True,
) -> APIRouter:
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    entity_type = "agent" if agent else "team" if team else "workflow"

    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN environment variable is not set")

    bot = AsyncTeleBot(token)

    _bot_username: Optional[str] = None
    _bot_id: Optional[int] = None

    async def _get_bot_info() -> tuple:
        nonlocal _bot_username, _bot_id
        if _bot_username is None or _bot_id is None:
            me = await bot.get_me()
            _bot_username = me.username
            _bot_id = me.id
        return _bot_username, _bot_id

    async def _get_bot_username() -> str:
        username, _ = await _get_bot_info()
        return username

    async def _get_bot_id() -> int:
        _, bot_id = await _get_bot_info()
        return bot_id

    def _message_mentions_bot(message: dict, bot_username: str) -> bool:
        text = message.get("text", "") or message.get("caption", "")
        entities = message.get("entities", []) or message.get("caption_entities", [])
        for entity in entities:
            if entity.get("type") == "mention":
                offset = entity["offset"]
                length = entity["length"]
                mention = text[offset : offset + length].lstrip("@").lower()
                if mention == bot_username.lower():
                    return True
        return False

    def _is_reply_to_bot(message: dict, bot_id: int) -> bool:
        reply_msg = message.get("reply_to_message")
        if not reply_msg:
            return False
        return reply_msg.get("from", {}).get("id") == bot_id

    def _strip_bot_mention(text: str, bot_username: str) -> str:
        return re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE).strip()

    def _parse_inbound_message(
        message: dict,
    ) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[dict]]:
        message_text: Optional[str] = None
        image_file_id: Optional[str] = None
        audio_file_id: Optional[str] = None
        video_file_id: Optional[str] = None
        document_meta: Optional[dict] = None

        if message.get("text"):
            message_text = message["text"]
        elif message.get("photo"):
            image_file_id = message["photo"][-1]["file_id"]
            message_text = message.get("caption", "Describe the image")
        elif message.get("sticker"):
            image_file_id = message["sticker"]["file_id"]
            message_text = "Describe this sticker"
        elif message.get("voice"):
            audio_file_id = message["voice"]["file_id"]
            message_text = message.get("caption", "Transcribe or describe this audio")
        elif message.get("audio"):
            audio_file_id = message["audio"]["file_id"]
            message_text = message.get("caption", "Describe this audio")
        elif message.get("video") or message.get("video_note") or message.get("animation"):
            vid: dict = message.get("video") or message.get("video_note") or message.get("animation")  # type: ignore[assignment]
            video_file_id = vid["file_id"]
            message_text = message.get("caption", "Describe this video")
        elif message.get("document"):
            document_meta = message["document"]
            message_text = message.get("caption", "Process this file")

        return message_text, image_file_id, audio_file_id, video_file_id, document_meta

    async def _download_inbound_media(
        image_file_id: Optional[str],
        audio_file_id: Optional[str],
        video_file_id: Optional[str],
        document_meta: Optional[dict],
    ) -> tuple[Optional[List[Image]], Optional[List[Audio]], Optional[List[Video]], Optional[List[File]]]:
        images: Optional[List[Image]] = None
        audio: Optional[List[Audio]] = None
        videos: Optional[List[Video]] = None
        files: Optional[List[File]] = None

        if image_file_id:
            image_bytes = await _get_file_bytes(image_file_id)
            if image_bytes:
                images = [Image(content=image_bytes)]
        if audio_file_id:
            audio_bytes = await _get_file_bytes(audio_file_id)
            if audio_bytes:
                audio = [Audio(content=audio_bytes)]
        if video_file_id:
            video_bytes = await _get_file_bytes(video_file_id)
            if video_bytes:
                videos = [Video(content=video_bytes)]
        if document_meta:
            doc_bytes = await _get_file_bytes(document_meta["file_id"])
            if doc_bytes:
                doc_mime = document_meta.get("mime_type")
                files = [
                    File(
                        content=doc_bytes,
                        mime_type=doc_mime if doc_mime in File.valid_mime_types() else None,
                        filename=document_meta.get("file_name"),
                    )
                ]

        return images, audio, videos, files

    async def _get_file_bytes(file_id: str) -> Optional[bytes]:
        try:
            file_info = await bot.get_file(file_id)
            return await bot.download_file(file_info.file_path)
        except Exception as e:
            log_error(f"Error downloading file: {e}")
            return None

    async def _send_text_chunked(chat_id: int, text: str, reply_to_message_id: Optional[int] = None) -> None:
        if len(text) <= TG_MAX_MESSAGE_LENGTH:
            await bot.send_message(chat_id, text, reply_to_message_id=reply_to_message_id)
            return
        chunks: List[str] = [text[i : i + TG_CHUNK_SIZE] for i in range(0, len(text), TG_CHUNK_SIZE)]
        for i, chunk in enumerate(chunks, 1):
            reply_id = reply_to_message_id if i == 1 else None
            await bot.send_message(chat_id, f"[{i}/{len(chunks)}] {chunk}", reply_to_message_id=reply_id)

    def _resolve_image_data(image: Any) -> Optional[Any]:
        if image.url:
            return image.url
        if image.content:
            content = image.content
            if isinstance(content, bytes):
                try:
                    decoded = content.decode("utf-8")
                    return base64.b64decode(decoded)
                except (UnicodeDecodeError, binascii.Error):
                    return content
            elif isinstance(content, str):
                try:
                    return base64.b64decode(content)
                except binascii.Error:
                    log_warning("Invalid base64 image content")
                    return None
        if image.filepath:
            try:
                with open(image.filepath, "rb") as f:
                    return f.read()
            except Exception as e:
                log_warning(f"Failed to read image file: {e}")
        return None

    async def _send_response_media(response: Any, chat_id: int, reply_to: Optional[int]) -> bool:
        any_media_sent = False
        caption = response.content[:TG_MAX_CAPTION_LENGTH] if response.content else None

        if response.images:
            for image in response.images:
                photo_data = _resolve_image_data(image)
                if photo_data:
                    try:
                        log_debug(f"Sending photo to chat_id={chat_id}, caption={caption[:50] if caption else None}")
                        await bot.send_photo(chat_id, photo_data, caption=caption, reply_to_message_id=reply_to)
                        any_media_sent = True
                        caption = None
                        reply_to = None
                    except Exception as e:
                        log_error(f"Failed to send photo to chat {chat_id}: {e}")

        if response.audio:
            for aud in response.audio:
                audio_data = aud.url or aud.get_content_bytes()
                if audio_data:
                    try:
                        await bot.send_audio(chat_id, audio_data, caption=caption, reply_to_message_id=reply_to)
                        any_media_sent = True
                        caption = None
                        reply_to = None
                    except Exception as e:
                        log_error(f"Failed to send audio to chat {chat_id}: {e}")

        if response.videos:
            for vid in response.videos:
                video_data = vid.url or vid.get_content_bytes()
                if video_data:
                    try:
                        await bot.send_video(chat_id, video_data, caption=caption, reply_to_message_id=reply_to)
                        any_media_sent = True
                        caption = None
                        reply_to = None
                    except Exception as e:
                        log_error(f"Failed to send video to chat {chat_id}: {e}")

        if response.files:
            for file_obj in response.files:
                file_data = file_obj.url or file_obj.get_content_bytes()
                if file_data:
                    try:
                        await bot.send_document(chat_id, file_data, caption=caption, reply_to_message_id=reply_to)
                        any_media_sent = True
                        caption = None
                        reply_to = None
                    except Exception as e:
                        log_error(f"Failed to send document to chat {chat_id}: {e}")

        return any_media_sent

    @router.get(
        "/status",
        operation_id=f"telegram_status_{entity_type}",
        name="telegram_status",
        description="Check Telegram interface status",
        response_model=TelegramStatusResponse,
    )
    async def status():
        return TelegramStatusResponse()

    @router.post(
        "/webhook",
        operation_id=f"telegram_webhook_{entity_type}",
        name="telegram_webhook",
        description="Process incoming Telegram webhook events",
        response_model=TelegramWebhookResponse,
        responses={
            200: {"description": "Event processed successfully"},
            403: {"description": "Invalid webhook secret token"},
        },
    )
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        try:
            secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if not validate_webhook_secret_token(secret_token):
                log_warning("Invalid webhook secret token")
                raise HTTPException(status_code=403, detail="Invalid secret token")

            body = await request.json()

            message = body.get("message")
            if not message:
                return TelegramWebhookResponse(status="ignored")

            background_tasks.add_task(_process_message, message, agent, team, workflow)
            return TelegramWebhookResponse(status="processing")

        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error processing webhook: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    async def _process_message(
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
            chat_type = message.get("chat", {}).get("type", "private")
            is_group = chat_type in TG_GROUP_CHAT_TYPES
            incoming_message_id = message.get("message_id")

            text = message.get("text", "")
            if text.startswith("/start"):
                await bot.send_message(chat_id, "Hello! I'm ready to help. Send me a message to get started.")
                return
            if text.startswith("/help"):
                await bot.send_message(
                    chat_id, "Send me text, photos, voice notes, videos, or documents and I'll help you with them."
                )
                return

            if is_group and reply_to_mentions_only:
                bot_username = await _get_bot_username()
                is_mentioned = _message_mentions_bot(message, bot_username)
                is_reply = reply_to_bot_messages and _is_reply_to_bot(message, await _get_bot_id())
                if not is_mentioned and not is_reply:
                    return

            await bot.send_chat_action(chat_id, "typing")

            message_text, image_file_id, audio_file_id, video_file_id, document_meta = _parse_inbound_message(message)
            if message_text is None:
                return

            if is_group and message_text:
                bot_username = await _get_bot_username()
                message_text = _strip_bot_mention(message_text, bot_username)

            user_id = str(message.get("from", {}).get("id", chat_id))
            if is_group:
                reply_msg = message.get("reply_to_message")
                root_msg_id = reply_msg.get("message_id", incoming_message_id) if reply_msg else incoming_message_id
                session_id = f"tg:{chat_id}:thread:{root_msg_id}"
            else:
                session_id = f"tg:{chat_id}"

            log_info(f"Processing message from {user_id}: {message_text}")

            reply_to = incoming_message_id if is_group else None

            images, audio, videos, files = await _download_inbound_media(
                image_file_id, audio_file_id, video_file_id, document_meta
            )

            run_kwargs: dict = dict(
                user_id=user_id,
                session_id=session_id,
                images=images,
                audio=audio,
                videos=videos,
                files=files,
            )
            response = None
            if agent:
                response = await agent.arun(message_text, **run_kwargs)
            elif team:
                response = await team.arun(message_text, **run_kwargs)  # type: ignore
            elif workflow:
                response = await workflow.arun(message_text, **run_kwargs)  # type: ignore

            if not response:
                return

            if response.status == "ERROR":
                await _send_text_chunked(
                    chat_id,
                    "Sorry, there was an error processing your message. Please try again later.",
                    reply_to_message_id=reply_to,
                )
                log_error(response.content)
                return

            if response.reasoning_content:
                await _send_text_chunked(
                    chat_id, f"Reasoning: \n{response.reasoning_content}", reply_to_message_id=reply_to
                )

            any_media_sent = await _send_response_media(response, chat_id, reply_to)

            if not any_media_sent:
                await _send_text_chunked(chat_id, response.content or "", reply_to_message_id=reply_to)

        except Exception as e:
            log_error(f"Error processing message: {e}")
            try:
                await _send_text_chunked(
                    chat_id, "Sorry, there was an error processing your message. Please try again later."
                )
            except Exception as send_error:
                log_error(f"Error sending error message: {send_error}")

    return router
