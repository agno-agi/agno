import json
from os import getenv
from pathlib import Path
from typing import Any, Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from telebot import TeleBot
    from telebot.apihelper import ApiTelegramException
    from telebot.types import ReactionTypeEmoji
except ImportError as e:
    raise ImportError("`pyTelegramBotAPI` not installed. Please install using `pip install 'agno[telegram]'`") from e


class TelegramTools(Toolkit):
    """Toolkit for interacting with the Telegram Bot API.

    Args:
        chat_id: Default chat ID. Falls back to TELEGRAM_CHAT_ID env var.
        token: Bot token. Falls back to TELEGRAM_TOKEN env var.
        output_directory: Directory for saving downloaded files.
        save_downloads: Save downloaded files to disk instead of returning base64.
        send_message: Enable send_message tool. Defaults to False (externally visible).
        send_photo: Enable send_photo tool. Defaults to False (externally visible).
        send_document: Enable send_document tool. Defaults to False (externally visible).
        send_video: Enable send_video tool. Defaults to False (externally visible).
        send_audio: Enable send_audio tool. Defaults to False (externally visible).
        send_animation: Enable send_animation tool. Defaults to False (externally visible).
        send_sticker: Enable send_sticker tool. Defaults to False (externally visible).
        edit_message: Enable edit_message tool. Defaults to False (modifies external).
        delete_message: Enable delete_message tool. Defaults to False (destructive).
        react_with_emoji: Enable react_with_emoji tool. Defaults to False (externally visible).
        pin_message: Enable pin_message tool. Defaults to False (modifies external).
        get_chat: Enable get_chat tool. Defaults to False.
        get_file: Enable get_file tool. Defaults to False.
        all: Enable all tools. Defaults to False.
    """

    def __init__(
        self,
        chat_id: Optional[str] = None,
        token: Optional[str] = None,
        output_directory: Optional[str] = None,
        save_downloads: bool = False,
        send_message: bool = False,
        send_photo: bool = False,
        send_document: bool = False,
        send_video: bool = False,
        send_audio: bool = False,
        send_animation: bool = False,
        send_sticker: bool = False,
        edit_message: bool = False,
        delete_message: bool = False,
        react_with_emoji: bool = False,
        pin_message: bool = False,
        get_chat: bool = False,
        get_file: bool = False,
        all: bool = False,
        **kwargs: Any,
    ):
        # Backwards compat: enable_X -> X
        if "enable_send_message" in kwargs:
            send_message = kwargs.pop("enable_send_message")
        if "enable_send_photo" in kwargs:
            send_photo = kwargs.pop("enable_send_photo")
        if "enable_send_document" in kwargs:
            send_document = kwargs.pop("enable_send_document")
        if "enable_send_video" in kwargs:
            send_video = kwargs.pop("enable_send_video")
        if "enable_send_audio" in kwargs:
            send_audio = kwargs.pop("enable_send_audio")
        if "enable_send_animation" in kwargs:
            send_animation = kwargs.pop("enable_send_animation")
        if "enable_send_sticker" in kwargs:
            send_sticker = kwargs.pop("enable_send_sticker")
        if "enable_edit_message" in kwargs:
            edit_message = kwargs.pop("enable_edit_message")
        if "enable_delete_message" in kwargs:
            delete_message = kwargs.pop("enable_delete_message")
        if "enable_react_with_emoji" in kwargs:
            react_with_emoji = kwargs.pop("enable_react_with_emoji")
        if "enable_pin_message" in kwargs:
            pin_message = kwargs.pop("enable_pin_message")
        if "enable_get_chat" in kwargs:
            get_chat = kwargs.pop("enable_get_chat")
        if "enable_get_file" in kwargs:
            get_file = kwargs.pop("enable_get_file")

        self.token = token or getenv("TELEGRAM_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_TOKEN not set. Please set the TELEGRAM_TOKEN environment variable.")

        self.chat_id = chat_id or getenv("TELEGRAM_CHAT_ID")
        self.bot = TeleBot(self.token)

        self.save_downloads = save_downloads or (output_directory is not None)
        if self.save_downloads:
            self.output_directory: Optional[Path] = (
                Path(output_directory).resolve() if output_directory else Path.cwd().resolve()
            )
            self.output_directory.mkdir(parents=True, exist_ok=True)
            log_debug(f"Downloaded files will be saved to: {self.output_directory}")
        else:
            self.output_directory = None

        tools: List[Callable] = []
        if all or send_message:
            tools.append(self.send_telegram_message)
        if all or send_photo:
            tools.append(self.send_telegram_photo)
        if all or send_document:
            tools.append(self.send_telegram_document)
        if all or send_video:
            tools.append(self.send_telegram_video)
        if all or send_audio:
            tools.append(self.send_telegram_audio)
        if all or send_animation:
            tools.append(self.send_telegram_animation)
        if all or send_sticker:
            tools.append(self.send_telegram_sticker)
        if all or edit_message:
            tools.append(self.edit_telegram_message)
        if all or delete_message:
            tools.append(self.delete_telegram_message)
        if all or react_with_emoji:
            tools.append(self.react_telegram_with_emoji)
        if all or pin_message:
            tools.append(self.pin_telegram_message)
        if all or get_chat:
            tools.append(self.get_telegram_chat)
        if all or get_file:
            tools.append(self.get_telegram_file)

        super().__init__(name="telegram", tools=tools, **kwargs)

    @property
    def _chat_id(self) -> str:
        if not self.chat_id:
            raise ValueError(
                "chat_id is required. Set it in the constructor or set the TELEGRAM_CHAT_ID environment variable."
            )
        return self.chat_id

    def send_telegram_message(self, message: str) -> str:
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

    def send_telegram_photo(self, photo: bytes, caption: Optional[str] = None) -> str:
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

    def send_telegram_document(self, document: bytes, filename: str, caption: Optional[str] = None) -> str:
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

    def send_telegram_video(self, video: bytes, caption: Optional[str] = None) -> str:
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

    def send_telegram_audio(self, audio: bytes, caption: Optional[str] = None, title: Optional[str] = None) -> str:
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

    def send_telegram_animation(self, animation: bytes, caption: Optional[str] = None) -> str:
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

    def send_telegram_sticker(self, sticker: bytes) -> str:
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

    def edit_telegram_message(self, text: str, message_id: int) -> str:
        """Edit a previously sent message in a Telegram chat.

        Args:
            text: The new message text.
            message_id: The ID of the message to edit.

        Returns:
            JSON string with status and message_id.
        """
        try:
            result = self.bot.edit_message_text(text, chat_id=self._chat_id, message_id=message_id)
            msg_id = result.message_id if hasattr(result, "message_id") else message_id
            return json.dumps({"status": "success", "message_id": msg_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def delete_telegram_message(self, message_id: int) -> str:
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

    def react_telegram_with_emoji(self, message_id: int, emoji: str) -> str:
        """React to a message with an emoji.

        Args:
            message_id: The ID of the message to react to.
            emoji: The emoji to react with.

        Returns:
            JSON string with status.
        """
        try:
            self.bot.set_message_reaction(
                chat_id=self._chat_id,
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
            )
            return json.dumps({"status": "success", "message_id": message_id, "emoji": emoji})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def pin_telegram_message(self, message_id: int, disable_notification: bool = False) -> str:
        """Pin a message in the chat.

        Args:
            message_id: The ID of the message to pin.
            disable_notification: If True, no notification is sent to chat members.

        Returns:
            JSON string with status and message_id.
        """
        try:
            self.bot.pin_chat_message(self._chat_id, message_id, disable_notification=disable_notification)
            return json.dumps({"status": "success", "pinned": True, "message_id": message_id})
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def get_telegram_chat(self) -> str:
        """Get information about the current chat.

        Returns:
            JSON string with status and chat info.
        """
        try:
            chat = self.bot.get_chat(self._chat_id)
            return json.dumps(
                {
                    "status": "success",
                    "id": chat.id,
                    "type": chat.type,
                    "title": getattr(chat, "title", None),
                    "username": getattr(chat, "username", None),
                    "first_name": getattr(chat, "first_name", None),
                    "last_name": getattr(chat, "last_name", None),
                    "description": getattr(chat, "description", None),
                }
            )
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})

    def get_telegram_file(self, file_id: str) -> str:
        """Download a file by its file_id. Returns path if save_downloads=True, else base64.

        Args:
            file_id: The file_id from a Telegram message (photo, document, etc.).

        Returns:
            JSON string with status and file info (local_path or content_base64).
        """
        import base64

        try:
            file_info = self.bot.get_file(file_id)
            if not file_info.file_path:
                return json.dumps({"status": "error", "message": "File path not available"})
            file_content = self.bot.download_file(file_info.file_path)

            result: dict[str, Any] = {
                "status": "success",
                "file_id": file_info.file_id,
                "file_path": file_info.file_path,
                "file_size": file_info.file_size,
            }
            if self.save_downloads and self.output_directory:
                filename = Path(file_info.file_path).name
                local_path = self.output_directory / filename
                local_path.write_bytes(file_content)
                result["local_path"] = str(local_path)
            else:
                result["content_base64"] = base64.b64encode(file_content).decode("utf-8")

            return json.dumps(result)
        except ApiTelegramException as e:
            return json.dumps({"status": "error", "message": str(e)})
