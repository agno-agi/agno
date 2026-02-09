import json
from os import getenv
from typing import Any, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from telebot import TeleBot
    from telebot.apihelper import ApiTelegramException
    from telebot.async_telebot import AsyncTeleBot
except ImportError:
    raise ImportError(
        "`telegram` tools require the `pyTelegramBotAPI` package. "
        "Run `pip install pyTelegramBotAPI` or `pip install 'agno[telegram]'` to install it."
    )


class TelegramTools(Toolkit):
    """Toolkit for sending messages and media via the Telegram Bot API.

    Args:
        chat_id: Default chat ID. Falls back to TELEGRAM_CHAT_ID env var.
        token: Bot token. Falls back to TELEGRAM_TOKEN env var.
        async_mode: Use async methods. Defaults to False.
        enable_send_message: Enable send_message tool. Defaults to True.
        enable_send_photo: Enable send_photo tool. Defaults to True.
        enable_send_document: Enable send_document tool. Defaults to True.
        enable_send_video: Enable send_video tool. Defaults to True.
        enable_send_audio: Enable send_audio tool. Defaults to True.
        enable_send_animation: Enable send_animation tool. Defaults to True.
        enable_send_sticker: Enable send_sticker tool. Defaults to True.
        enable_edit_message: Enable edit_message tool. Defaults to False.
        enable_delete_message: Enable delete_message tool. Defaults to False.
        all: Enable all tools. Overrides individual flags when True.
    """

    def __init__(
        self,
        chat_id: Optional[Union[str, int]] = None,
        token: Optional[str] = None,
        async_mode: bool = False,
        enable_send_message: bool = True,
        enable_send_photo: bool = True,
        enable_send_document: bool = True,
        enable_send_video: bool = True,
        enable_send_audio: bool = True,
        enable_send_animation: bool = True,
        enable_send_sticker: bool = True,
        enable_edit_message: bool = False,
        enable_delete_message: bool = False,
        all: bool = False,
        **kwargs: Any,
    ):
        self.token = token or getenv("TELEGRAM_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_TOKEN not set. Please set the TELEGRAM_TOKEN environment variable.")

        self.chat_id = chat_id or getenv("TELEGRAM_CHAT_ID")
        self.async_mode = async_mode

        if async_mode:
            self.async_bot = AsyncTeleBot(self.token)
        else:
            self.bot = TeleBot(self.token)

        tools: List[Any] = []
        if async_mode:
            if all or enable_send_message:
                tools.append(self.send_message_async)
            if all or enable_send_photo:
                tools.append(self.send_photo_async)
            if all or enable_send_document:
                tools.append(self.send_document_async)
            if all or enable_send_video:
                tools.append(self.send_video_async)
            if all or enable_send_audio:
                tools.append(self.send_audio_async)
            if all or enable_send_animation:
                tools.append(self.send_animation_async)
            if all or enable_send_sticker:
                tools.append(self.send_sticker_async)
            if all or enable_edit_message:
                tools.append(self.edit_message_async)
            if all or enable_delete_message:
                tools.append(self.delete_message_async)
        else:
            if all or enable_send_message:
                tools.append(self.send_message)
            if all or enable_send_photo:
                tools.append(self.send_photo)
            if all or enable_send_document:
                tools.append(self.send_document)
            if all or enable_send_video:
                tools.append(self.send_video)
            if all or enable_send_audio:
                tools.append(self.send_audio)
            if all or enable_send_animation:
                tools.append(self.send_animation)
            if all or enable_send_sticker:
                tools.append(self.send_sticker)
            if all or enable_edit_message:
                tools.append(self.edit_message)
            if all or enable_delete_message:
                tools.append(self.delete_message)

        super().__init__(name="telegram", tools=tools, **kwargs)

    def _resolve_chat_id(self, chat_id: Optional[Union[str, int]] = None) -> Union[str, int]:
        resolved = chat_id or self.chat_id
        if not resolved:
            raise ValueError(
                "chat_id is required. Pass it as a parameter, set it in the constructor, "
                "or set the TELEGRAM_CHAT_ID environment variable."
            )
        return resolved

    def send_message(self, message: str, chat_id: Optional[Union[str, int]] = None) -> str:
        """Send a text message to a Telegram chat.

        Args:
            message: The message text to send.
            chat_id: Target chat ID. Uses the default if not provided.

        Returns:
            JSON string with status and message_id.
        """
        log_debug(f"Sending telegram message: {message}")
        try:
            result = self.bot.send_message(self._resolve_chat_id(chat_id), message)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def send_message_async(self, message: str, chat_id: Optional[Union[str, int]] = None) -> str:
        """Send a text message to a Telegram chat asynchronously.

        Args:
            message: The message text to send.
            chat_id: Target chat ID. Uses the default if not provided.

        Returns:
            JSON string with status and message_id.
        """
        log_debug(f"Sending telegram message: {message}")
        try:
            result = await self.async_bot.send_message(self._resolve_chat_id(chat_id), message)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_photo(self, photo: bytes, chat_id: Optional[Union[str, int]] = None, caption: Optional[str] = None) -> str:
        """Send a photo to a Telegram chat.

        Args:
            photo: The photo as bytes.
            chat_id: Target chat ID. Uses the default if not provided.
            caption: Optional caption for the photo.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_photo(self._resolve_chat_id(chat_id), photo, caption=caption)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def send_photo_async(
        self, photo: bytes, chat_id: Optional[Union[str, int]] = None, caption: Optional[str] = None
    ) -> str:
        """Send a photo to a Telegram chat asynchronously.

        Args:
            photo: The photo as bytes.
            chat_id: Target chat ID. Uses the default if not provided.
            caption: Optional caption for the photo.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = await self.async_bot.send_photo(self._resolve_chat_id(chat_id), photo, caption=caption)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_document(
        self, document: bytes, filename: str, chat_id: Optional[Union[str, int]] = None, caption: Optional[str] = None
    ) -> str:
        """Send a document to a Telegram chat.

        Args:
            document: The document as bytes.
            filename: The filename for the document.
            chat_id: Target chat ID. Uses the default if not provided.
            caption: Optional caption for the document.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_document(self._resolve_chat_id(chat_id), (filename, document), caption=caption)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def send_document_async(
        self, document: bytes, filename: str, chat_id: Optional[Union[str, int]] = None, caption: Optional[str] = None
    ) -> str:
        """Send a document to a Telegram chat asynchronously.

        Args:
            document: The document as bytes.
            filename: The filename for the document.
            chat_id: Target chat ID. Uses the default if not provided.
            caption: Optional caption for the document.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = await self.async_bot.send_document(
                self._resolve_chat_id(chat_id), (filename, document), caption=caption
            )
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_video(self, video: bytes, chat_id: Optional[Union[str, int]] = None, caption: Optional[str] = None) -> str:
        """Send a video to a Telegram chat.

        Args:
            video: The video as bytes.
            chat_id: Target chat ID. Uses the default if not provided.
            caption: Optional caption for the video.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_video(self._resolve_chat_id(chat_id), video, caption=caption)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def send_video_async(
        self, video: bytes, chat_id: Optional[Union[str, int]] = None, caption: Optional[str] = None
    ) -> str:
        """Send a video to a Telegram chat asynchronously.

        Args:
            video: The video as bytes.
            chat_id: Target chat ID. Uses the default if not provided.
            caption: Optional caption for the video.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = await self.async_bot.send_video(self._resolve_chat_id(chat_id), video, caption=caption)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_audio(
        self,
        audio: bytes,
        chat_id: Optional[Union[str, int]] = None,
        caption: Optional[str] = None,
        title: Optional[str] = None,
    ) -> str:
        """Send an audio file to a Telegram chat.

        Args:
            audio: The audio as bytes.
            chat_id: Target chat ID. Uses the default if not provided.
            caption: Optional caption for the audio.
            title: Optional title for the audio track.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_audio(self._resolve_chat_id(chat_id), audio, caption=caption, title=title)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def send_audio_async(
        self,
        audio: bytes,
        chat_id: Optional[Union[str, int]] = None,
        caption: Optional[str] = None,
        title: Optional[str] = None,
    ) -> str:
        """Send an audio file to a Telegram chat asynchronously.

        Args:
            audio: The audio as bytes.
            chat_id: Target chat ID. Uses the default if not provided.
            caption: Optional caption for the audio.
            title: Optional title for the audio track.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = await self.async_bot.send_audio(
                self._resolve_chat_id(chat_id), audio, caption=caption, title=title
            )
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_animation(
        self, animation: bytes, chat_id: Optional[Union[str, int]] = None, caption: Optional[str] = None
    ) -> str:
        """Send an animation (GIF) to a Telegram chat.

        Args:
            animation: The animation as bytes.
            chat_id: Target chat ID. Uses the default if not provided.
            caption: Optional caption for the animation.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_animation(self._resolve_chat_id(chat_id), animation, caption=caption)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def send_animation_async(
        self, animation: bytes, chat_id: Optional[Union[str, int]] = None, caption: Optional[str] = None
    ) -> str:
        """Send an animation (GIF) to a Telegram chat asynchronously.

        Args:
            animation: The animation as bytes.
            chat_id: Target chat ID. Uses the default if not provided.
            caption: Optional caption for the animation.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = await self.async_bot.send_animation(self._resolve_chat_id(chat_id), animation, caption=caption)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def send_sticker(self, sticker: bytes, chat_id: Optional[Union[str, int]] = None) -> str:
        """Send a sticker to a Telegram chat.

        Args:
            sticker: The sticker as bytes.
            chat_id: Target chat ID. Uses the default if not provided.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.send_sticker(self._resolve_chat_id(chat_id), sticker)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def send_sticker_async(self, sticker: bytes, chat_id: Optional[Union[str, int]] = None) -> str:
        """Send a sticker to a Telegram chat asynchronously.

        Args:
            sticker: The sticker as bytes.
            chat_id: Target chat ID. Uses the default if not provided.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = await self.async_bot.send_sticker(self._resolve_chat_id(chat_id), sticker)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def edit_message(self, text: str, message_id: int, chat_id: Optional[Union[str, int]] = None) -> str:
        """Edit a previously sent message in a Telegram chat.

        Args:
            text: The new message text.
            message_id: The ID of the message to edit.
            chat_id: Target chat ID. Uses the default if not provided.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.edit_message_text(text, chat_id=self._resolve_chat_id(chat_id), message_id=message_id)
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def edit_message_async(self, text: str, message_id: int, chat_id: Optional[Union[str, int]] = None) -> str:
        """Edit a previously sent message in a Telegram chat asynchronously.

        Args:
            text: The new message text.
            message_id: The ID of the message to edit.
            chat_id: Target chat ID. Uses the default if not provided.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = await self.async_bot.edit_message_text(
                text, chat_id=self._resolve_chat_id(chat_id), message_id=message_id
            )
            return json.dumps({"status": "success", "message_id": result.message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def delete_message(self, message_id: int, chat_id: Optional[Union[str, int]] = None) -> str:
        """Delete a message from a Telegram chat.

        Args:
            message_id: The ID of the message to delete.
            chat_id: Target chat ID. Uses the default if not provided.

        Returns:
            JSON string with status and deleted flag.
        """
        try:
            self.bot.delete_message(self._resolve_chat_id(chat_id), message_id)
            return json.dumps({"status": "success", "deleted": True})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def delete_message_async(self, message_id: int, chat_id: Optional[Union[str, int]] = None) -> str:
        """Delete a message from a Telegram chat asynchronously.

        Args:
            message_id: The ID of the message to delete.
            chat_id: Target chat ID. Uses the default if not provided.

        Returns:
            JSON string with status and deleted flag.
        """
        try:
            await self.async_bot.delete_message(self._resolve_chat_id(chat_id), message_id)
            return json.dumps({"status": "success", "deleted": True})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})
