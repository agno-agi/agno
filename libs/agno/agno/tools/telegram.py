import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from telebot import TeleBot
    from telebot.apihelper import ApiTelegramException
except ImportError as e:
    raise ImportError("`pyTelegramBotAPI` not installed. Please install using `pip install 'agno[telegram]'`") from e


class TelegramTools(Toolkit):
    """Toolkit for sending messages and media via the Telegram Bot API.

    Args:
        chat_id: Default chat ID. Falls back to TELEGRAM_CHAT_ID env var.
        token: Bot token. Falls back to TELEGRAM_TOKEN env var.
        enable_send_message: Enable send_message tool. Defaults to True.
        enable_send_photo: Enable send_photo tool. Defaults to False.
        enable_send_document: Enable send_document tool. Defaults to False.
        enable_send_video: Enable send_video tool. Defaults to False.
        enable_send_audio: Enable send_audio tool. Defaults to False.
        enable_send_animation: Enable send_animation tool. Defaults to False.
        enable_send_sticker: Enable send_sticker tool. Defaults to False.
        enable_edit_message: Enable edit_message tool. Defaults to False.
        enable_delete_message: Enable delete_message tool. Defaults to False.
        all: Enable all tools. Overrides individual flags when True.
    """

    def __init__(
        self,
        chat_id: Optional[str] = None,
        token: Optional[str] = None,
        enable_send_message: bool = True,
        enable_send_photo: bool = False,
        enable_send_document: bool = False,
        enable_send_video: bool = False,
        enable_send_audio: bool = False,
        enable_send_animation: bool = False,
        enable_send_sticker: bool = False,
        enable_edit_message: bool = False,
        enable_delete_message: bool = False,
        all: bool = False,
        **kwargs: Any,
    ):
        self.token = token or getenv("TELEGRAM_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_TOKEN not set. Please set the TELEGRAM_TOKEN environment variable.")

        self.chat_id = chat_id or getenv("TELEGRAM_CHAT_ID")
        self.bot = TeleBot(self.token)

        tools: List[Any] = []
        if enable_send_message or all:
            tools.append(self.send_message)
        if enable_send_photo or all:
            tools.append(self.send_photo)
        if enable_send_document or all:
            tools.append(self.send_document)
        if enable_send_video or all:
            tools.append(self.send_video)
        if enable_send_audio or all:
            tools.append(self.send_audio)
        if enable_send_animation or all:
            tools.append(self.send_animation)
        if enable_send_sticker or all:
            tools.append(self.send_sticker)
        if enable_edit_message or all:
            tools.append(self.edit_message)
        if enable_delete_message or all:
            tools.append(self.delete_message)

        super().__init__(name="telegram", tools=tools, **kwargs)

    @property
    def _chat_id(self) -> str:
        if not self.chat_id:
            raise ValueError(
                "chat_id is required. Set it in the constructor or set the TELEGRAM_CHAT_ID environment variable."
            )
        return self.chat_id

    def send_message(self, message: str) -> str:
        """Send a text message to a Telegram chat.

        Args:
            message: The message text to send.

        Returns:
            JSON string with status and message_id.
        """
        log_debug(f"Sending telegram message: {message}")
        try:
            result = self.bot.send_message(self._chat_id, message)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_photo(self, photo: bytes, caption: Optional[str] = None) -> str:
        """Send a photo to a Telegram chat.

        Args:
            photo: The photo as bytes.
            caption: Optional caption for the photo.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_photo(self._chat_id, photo, caption=caption)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_document(self, document: bytes, filename: str, caption: Optional[str] = None) -> str:
        """Send a document to a Telegram chat.

        Args:
            document: The document as bytes.
            filename: The filename for the document.
            caption: Optional caption for the document.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_document(self._chat_id, (filename, document), caption=caption)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_video(self, video: bytes, caption: Optional[str] = None) -> str:
        """Send a video to a Telegram chat.

        Args:
            video: The video as bytes.
            caption: Optional caption for the video.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_video(self._chat_id, video, caption=caption)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_audio(self, audio: bytes, caption: Optional[str] = None, title: Optional[str] = None) -> str:
        """Send an audio file to a Telegram chat.

        Args:
            audio: The audio as bytes.
            caption: Optional caption for the audio.
            title: Optional title for the audio track.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_audio(self._chat_id, audio, caption=caption, title=title)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_animation(self, animation: bytes, caption: Optional[str] = None) -> str:
        """Send an animation (GIF) to a Telegram chat.

        Args:
            animation: The animation as bytes.
            caption: Optional caption for the animation.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_animation(self._chat_id, animation, caption=caption)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_sticker(self, sticker: bytes) -> str:
        """Send a sticker to a Telegram chat.

        Args:
            sticker: The sticker as bytes.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_sticker(self._chat_id, sticker)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def edit_message(self, text: str, message_id: int) -> str:
        """Edit a previously sent message in a Telegram chat.

        Args:
            text: The new message text.
            message_id: The ID of the message to edit.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.edit_message_text(text, chat_id=self._chat_id, message_id=message_id)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def delete_message(self, message_id: int) -> str:
        """Delete a message from a Telegram chat.

        Args:
            message_id: The ID of the message to delete.

        Returns:
            JSON string with status and deleted flag.
        """
        try:
            self.bot.delete_message(self._chat_id, message_id)
            return json.dumps({"status": "success", "deleted": True})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})
