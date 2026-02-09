import base64
import binascii
import os
from typing import Any, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from agno.agent import Agent, RemoteAgent
from agno.media import Audio, File, Image, Video
from agno.os.interfaces.telegram.security import validate_webhook_secret_token
from agno.team import RemoteTeam, Team
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

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

    entity_type = "agent" if agent else "team" if team else "workflow"

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

    async def _send_photo_message(chat_id: int, photo: Union[bytes, str], caption: Optional[str] = None) -> None:
        _require_telebot()
        bot = AsyncTeleBot(_get_bot_token())
        log_debug(f"Sending photo to chat_id={chat_id}, caption={caption[:50] if caption else None}")
        await bot.send_photo(chat_id, photo, caption=caption)

    async def _send_audio_message(chat_id: int, audio: Union[bytes, str], caption: Optional[str] = None) -> None:
        _require_telebot()
        bot = AsyncTeleBot(_get_bot_token())
        await bot.send_audio(chat_id, audio, caption=caption)

    async def _send_video_message(chat_id: int, video: Union[bytes, str], caption: Optional[str] = None) -> None:
        _require_telebot()
        bot = AsyncTeleBot(_get_bot_token())
        await bot.send_video(chat_id, video, caption=caption)

    async def _send_document_message(chat_id: int, document: Union[bytes, str], caption: Optional[str] = None) -> None:
        _require_telebot()
        bot = AsyncTeleBot(_get_bot_token())
        await bot.send_document(chat_id, document, caption=caption)

    @router.get(
        "/status",
        operation_id=f"telegram_status_{entity_type}",
        name="telegram_status",
        description="Check Telegram interface status",
    )
    async def status():
        return {"status": "available"}

    @router.post(
        "/webhook",
        operation_id=f"telegram_webhook_{entity_type}",
        name="telegram_webhook",
        description="Process incoming Telegram webhook events",
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
                return {"status": "ignored"}

            background_tasks.add_task(_process_message, message, agent, team, workflow)
            return {"status": "processing"}

        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error processing webhook: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

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
            await _send_chat_action(chat_id, "typing")

            # Parse inbound message — extract text and media
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
                vid = message.get("video") or message.get("video_note") or message.get("animation")
                video_file_id = vid["file_id"]
                message_text = message.get("caption", "Describe this video")
            elif message.get("document"):
                document_meta = message["document"]
                message_text = message.get("caption", "Process this file")
            else:
                return

            user_id = str(message.get("from", {}).get("id", chat_id))
            session_id = f"tg:{chat_id}"
            log_info(f"Processing message from {user_id}: {message_text}")

            # Download media and build typed objects
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

            # Run agent/team/workflow
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
                    chat_id, "Sorry, there was an error processing your message. Please try again later."
                )
                log_error(response.content)
                return

            if response.reasoning_content:
                await _send_text_chunked(chat_id, f"Reasoning: \n{response.reasoning_content}")

            # Outbound media handling
            any_media_sent = False
            caption = response.content[:1024] if response.content else None

            if response.images:
                for image in response.images:
                    photo_data: Any = None

                    if image.url:
                        photo_data = image.url
                    elif image.content:
                        content = image.content
                        if isinstance(content, bytes):
                            try:
                                decoded = content.decode("utf-8")
                                photo_data = base64.b64decode(decoded)
                            except (UnicodeDecodeError, binascii.Error):
                                photo_data = content
                        elif isinstance(content, str):
                            try:
                                photo_data = base64.b64decode(content)
                            except binascii.Error:
                                log_warning(f"Invalid base64 image content for chat {chat_id}")
                    elif image.filepath:
                        try:
                            with open(image.filepath, "rb") as f:
                                photo_data = f.read()
                        except Exception as e:
                            log_warning(f"Failed to read image file for chat {chat_id}: {e}")

                    if photo_data:
                        try:
                            await _send_photo_message(chat_id=chat_id, photo=photo_data, caption=caption)
                            any_media_sent = True
                            caption = None
                        except Exception as img_err:
                            log_error(f"Failed to send photo to chat {chat_id}: {img_err}")

            if response.audios:
                for aud in response.audios:
                    audio_data = aud.url or aud.get_content_bytes()
                    if audio_data:
                        try:
                            await _send_audio_message(chat_id=chat_id, audio=audio_data, caption=caption)
                            any_media_sent = True
                            caption = None
                        except Exception as e:
                            log_error(f"Failed to send audio to chat {chat_id}: {e}")

            if response.videos:
                for vid in response.videos:
                    video_data = vid.url or vid.get_content_bytes()
                    if video_data:
                        try:
                            await _send_video_message(chat_id=chat_id, video=video_data, caption=caption)
                            any_media_sent = True
                            caption = None
                        except Exception as e:
                            log_error(f"Failed to send video to chat {chat_id}: {e}")

            if response.files:
                for file_obj in response.files:
                    file_data = file_obj.url or file_obj.get_content_bytes()
                    if file_data:
                        try:
                            await _send_document_message(chat_id=chat_id, document=file_data, caption=caption)
                            any_media_sent = True
                            caption = None
                        except Exception as e:
                            log_error(f"Failed to send document to chat {chat_id}: {e}")

            if not any_media_sent:
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
