"""Telegram integration tools for sending messages, media, and managing chats."""

import json
from os import getenv
from typing import Any, List, Optional, Union

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class TelegramTools(Toolkit):
    def __init__(
        self,
        chat_id: Optional[Union[str, int]] = None,
        token: Optional[str] = None,
        parse_mode: Optional[str] = "Markdown",
        enable_send_message: bool = True,
        enable_send_photo: bool = True,
        enable_send_document: bool = True,
        enable_send_audio: bool = True,
        enable_send_video: bool = True,
        enable_edit_message: bool = True,
        enable_delete_message: bool = True,
        enable_pin_message: bool = True,
        enable_get_chat: bool = True,
        enable_get_updates: bool = True,
        enable_get_file: bool = True,
        enable_send_chat_action: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize TelegramTools.

        Args:
            chat_id: Default chat ID for all operations. Can be overridden per method.
            token: Telegram Bot API token. Defaults to TELEGRAM_TOKEN env var.
            parse_mode: Default parse mode for text messages ("Markdown", "MarkdownV2", "HTML").
            enable_*: Toggle individual tools on/off.
            all: Enable all tools regardless of individual flags.
        """
        self.token = token or getenv("TELEGRAM_TOKEN")
        if not self.token:
            logger.error(
                "TELEGRAM_TOKEN not set. Please set the TELEGRAM_TOKEN "
                "environment variable."
            )

        self.chat_id = chat_id
        self.parse_mode = parse_mode
        self.base_url = f"https://api.telegram.org/bot{self.token}"

        tools: List[Any] = []
        if all or enable_send_message:
            tools.append(self.send_message)
        if all or enable_send_photo:
            tools.append(self.send_photo)
        if all or enable_send_document:
            tools.append(self.send_document)
        if all or enable_send_audio:
            tools.append(self.send_audio)
        if all or enable_send_video:
            tools.append(self.send_video)
        if all or enable_edit_message:
            tools.append(self.edit_message)
        if all or enable_delete_message:
            tools.append(self.delete_message)
        if all or enable_pin_message:
            tools.append(self.pin_message)
        if all or enable_get_chat:
            tools.append(self.get_chat)
        if all or enable_get_updates:
            tools.append(self.get_updates)
        if all or enable_get_file:
            tools.append(self.get_file)
        if all or enable_send_chat_action:
            tools.append(self.send_chat_action)

        super().__init__(name="telegram", tools=tools, **kwargs)

    def _resolve_chat_id(self, chat_id: Optional[Union[str, int]] = None) -> Union[str, int]:
        """Resolve the chat_id, falling back to the constructor default."""
        resolved = chat_id or self.chat_id
        if not resolved:
            raise ValueError(
                "chat_id must be provided either in the constructor or as a method argument"
            )
        return resolved

    def _make_request(self, method: str, **params) -> dict:
        """Make a POST request to the Telegram Bot API.

        Args:
            method: The Telegram Bot API method name (e.g. "sendMessage").
            **params: Parameters to include in the request body.

        Returns:
            The parsed JSON response from Telegram.
        """
        payload = {k: v for k, v in params.items() if v is not None}
        response = httpx.post(f"{self.base_url}/{method}", json=payload)
        response.raise_for_status()
        return response.json()

    # ---- Messaging ----

    def send_message(
        self,
        message: str,
        chat_id: Optional[Union[str, int]] = None,
        parse_mode: Optional[str] = None,
    ) -> str:
        """Send a text message to a Telegram chat.

        Args:
            message: The text of the message to send.
            chat_id: Target chat ID. Uses default if not provided.
            parse_mode: Message formatting ("Markdown", "MarkdownV2", "HTML").

        Returns:
            A JSON string with the API response.
        """
        log_debug(f"Sending telegram message to chat")
        try:
            result = self._make_request(
                "sendMessage",
                chat_id=self._resolve_chat_id(chat_id),
                text=message,
                parse_mode=parse_mode or self.parse_mode,
            )
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error sending message: {e}")
            return json.dumps({"ok": False, "error": str(e)})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})

    # ---- Media ----

    def send_photo(
        self,
        photo: str,
        chat_id: Optional[Union[str, int]] = None,
        caption: Optional[str] = None,
    ) -> str:
        """Send a photo to a Telegram chat.

        Args:
            photo: Photo URL or file_id from a previous message.
            chat_id: Target chat ID. Uses default if not provided.
            caption: Optional caption for the photo.

        Returns:
            A JSON string with the API response.
        """
        log_debug("Sending photo to Telegram chat")
        try:
            result = self._make_request(
                "sendPhoto",
                chat_id=self._resolve_chat_id(chat_id),
                photo=photo,
                caption=caption,
            )
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error sending photo: {e}")
            return json.dumps({"ok": False, "error": str(e)})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})

    def send_document(
        self,
        document: str,
        chat_id: Optional[Union[str, int]] = None,
        caption: Optional[str] = None,
    ) -> str:
        """Send a document to a Telegram chat.

        Args:
            document: Document URL or file_id from a previous message.
            chat_id: Target chat ID. Uses default if not provided.
            caption: Optional caption for the document.

        Returns:
            A JSON string with the API response.
        """
        log_debug("Sending document to Telegram chat")
        try:
            result = self._make_request(
                "sendDocument",
                chat_id=self._resolve_chat_id(chat_id),
                document=document,
                caption=caption,
            )
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error sending document: {e}")
            return json.dumps({"ok": False, "error": str(e)})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})

    def send_audio(
        self,
        audio: str,
        chat_id: Optional[Union[str, int]] = None,
        caption: Optional[str] = None,
    ) -> str:
        """Send an audio file to a Telegram chat.

        Args:
            audio: Audio URL or file_id from a previous message.
            chat_id: Target chat ID. Uses default if not provided.
            caption: Optional caption for the audio.

        Returns:
            A JSON string with the API response.
        """
        log_debug("Sending audio to Telegram chat")
        try:
            result = self._make_request(
                "sendAudio",
                chat_id=self._resolve_chat_id(chat_id),
                audio=audio,
                caption=caption,
            )
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error sending audio: {e}")
            return json.dumps({"ok": False, "error": str(e)})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})

    def send_video(
        self,
        video: str,
        chat_id: Optional[Union[str, int]] = None,
        caption: Optional[str] = None,
    ) -> str:
        """Send a video to a Telegram chat.

        Args:
            video: Video URL or file_id from a previous message.
            chat_id: Target chat ID. Uses default if not provided.
            caption: Optional caption for the video.

        Returns:
            A JSON string with the API response.
        """
        log_debug("Sending video to Telegram chat")
        try:
            result = self._make_request(
                "sendVideo",
                chat_id=self._resolve_chat_id(chat_id),
                video=video,
                caption=caption,
            )
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error sending video: {e}")
            return json.dumps({"ok": False, "error": str(e)})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})

    # ---- Message management ----

    def edit_message(
        self,
        message_id: int,
        text: str,
        chat_id: Optional[Union[str, int]] = None,
        parse_mode: Optional[str] = None,
    ) -> str:
        """Edit a previously sent message.

        Args:
            message_id: The ID of the message to edit.
            text: The new text for the message.
            chat_id: Target chat ID. Uses default if not provided.
            parse_mode: Message formatting ("Markdown", "MarkdownV2", "HTML").

        Returns:
            A JSON string with the API response.
        """
        log_debug(f"Editing message {message_id} in Telegram chat")
        try:
            result = self._make_request(
                "editMessageText",
                chat_id=self._resolve_chat_id(chat_id),
                message_id=message_id,
                text=text,
                parse_mode=parse_mode or self.parse_mode,
            )
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error editing message: {e}")
            return json.dumps({"ok": False, "error": str(e)})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})

    def delete_message(
        self,
        message_id: int,
        chat_id: Optional[Union[str, int]] = None,
    ) -> str:
        """Delete a message from a Telegram chat.

        Args:
            message_id: The ID of the message to delete.
            chat_id: Target chat ID. Uses default if not provided.

        Returns:
            A JSON string with the API response.
        """
        log_debug(f"Deleting message {message_id} from Telegram chat")
        try:
            result = self._make_request(
                "deleteMessage",
                chat_id=self._resolve_chat_id(chat_id),
                message_id=message_id,
            )
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error deleting message: {e}")
            return json.dumps({"ok": False, "error": str(e)})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})

    def pin_message(
        self,
        message_id: int,
        chat_id: Optional[Union[str, int]] = None,
    ) -> str:
        """Pin a message in a Telegram chat.

        Args:
            message_id: The ID of the message to pin.
            chat_id: Target chat ID. Uses default if not provided.

        Returns:
            A JSON string with the API response.
        """
        log_debug(f"Pinning message {message_id} in Telegram chat")
        try:
            result = self._make_request(
                "pinChatMessage",
                chat_id=self._resolve_chat_id(chat_id),
                message_id=message_id,
            )
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error pinning message: {e}")
            return json.dumps({"ok": False, "error": str(e)})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})

    # ---- Chat info ----

    def get_chat(
        self,
        chat_id: Optional[Union[str, int]] = None,
    ) -> str:
        """Get information about a Telegram chat.

        Args:
            chat_id: Target chat ID. Uses default if not provided.

        Returns:
            A JSON string with chat details (title, type, member count, etc.).
        """
        log_debug("Getting Telegram chat info")
        try:
            result = self._make_request(
                "getChat",
                chat_id=self._resolve_chat_id(chat_id),
            )
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error getting chat info: {e}")
            return json.dumps({"ok": False, "error": str(e)})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})

    def get_updates(self, limit: int = 10) -> str:
        """Get recent incoming updates (messages) for the bot.

        Args:
            limit: Maximum number of updates to retrieve (1-100). Defaults to 10.

        Returns:
            A JSON string with an array of recent updates.
        """
        log_debug(f"Getting Telegram updates (limit={limit})")
        try:
            result = self._make_request("getUpdates", limit=limit)
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error getting updates: {e}")
            return json.dumps({"ok": False, "error": str(e)})

    def get_file(self, file_id: str) -> str:
        """Get a file's download URL from Telegram by its file_id.

        Use this to retrieve photos, documents, audio, or video from received messages.
        The file_id can be found in incoming updates (e.g. message.photo[-1].file_id).

        Args:
            file_id: The file identifier from a Telegram message.

        Returns:
            A JSON string with file info including the download URL.
        """
        log_debug(f"Getting file info for file_id={file_id}")
        try:
            result = self._make_request("getFile", file_id=file_id)
            # Build the full download URL if file_path is present
            if result.get("ok") and result.get("result", {}).get("file_path"):
                file_path = result["result"]["file_path"]
                result["result"]["download_url"] = (
                    f"https://api.telegram.org/file/bot{self.token}/{file_path}"
                )
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error getting file: {e}")
            return json.dumps({"ok": False, "error": str(e)})

    # ---- Utility ----

    def send_chat_action(
        self,
        action: str = "typing",
        chat_id: Optional[Union[str, int]] = None,
    ) -> str:
        """Send a chat action indicator (e.g. "typing", "upload_photo").

        Use this to show the user that the bot is performing an action.
        Supported actions: typing, upload_photo, record_video, upload_video,
        record_voice, upload_voice, upload_document, find_location,
        record_video_note, upload_video_note.

        Args:
            action: The action to broadcast. Defaults to "typing".
            chat_id: Target chat ID. Uses default if not provided.

        Returns:
            A JSON string with the API response.
        """
        log_debug(f"Sending chat action '{action}' to Telegram chat")
        try:
            result = self._make_request(
                "sendChatAction",
                chat_id=self._resolve_chat_id(chat_id),
                action=action,
            )
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.error(f"Error sending chat action: {e}")
            return json.dumps({"ok": False, "error": str(e)})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})
