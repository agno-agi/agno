import base64
import json
from os import getenv
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import requests

from agno.tools import Toolkit
from agno.utils.log import logger

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_CDN_DOMAINS = {"cdn.discordapp.com", "media.discordapp.net"}


class DiscordTools(Toolkit):
    def __init__(
        self,
        bot_token: Optional[str] = None,
        enable_send_message: bool = True,
        enable_send_message_thread: bool = True,
        enable_upload_file: bool = True,
        enable_download_file: bool = True,
        enable_get_channel_messages: bool = True,
        enable_get_channel_info: bool = True,
        enable_list_channels: bool = True,
        enable_delete_message: bool = True,
        enable_search_messages: bool = False,
        enable_get_thread: bool = False,
        enable_list_users: bool = False,
        enable_get_user_info: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.bot_token = bot_token or getenv("DISCORD_BOT_TOKEN")
        if not self.bot_token:
            logger.error("DISCORD_BOT_TOKEN not set. Please set the DISCORD_BOT_TOKEN environment variable.")
            raise ValueError("Discord bot token is required")

        self.base_url = DISCORD_API_BASE
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bot {self.bot_token}"

        tools: List[Any] = []
        if enable_send_message or all:
            tools.append(self.send_message)
        if enable_send_message_thread or all:
            tools.append(self.send_message_thread)
        if enable_upload_file or all:
            tools.append(self.upload_file)
        if enable_download_file or all:
            tools.append(self.download_file)
        if enable_get_channel_messages or all:
            tools.append(self.get_channel_messages)
        if enable_get_channel_info or all:
            tools.append(self.get_channel_info)
        if enable_list_channels or all:
            tools.append(self.list_channels)
        if enable_delete_message or all:
            tools.append(self.delete_message)
        if enable_search_messages or all:
            tools.append(self.search_messages)
        if enable_get_thread or all:
            tools.append(self.get_thread)
        if enable_list_users or all:
            tools.append(self.list_users)
        if enable_get_user_info or all:
            tools.append(self.get_user_info)

        super().__init__(name="discord", tools=tools, **kwargs)

    def _make_request(
        self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        response = self._session.request(method, url, json=data, params=params, timeout=30)
        response.raise_for_status()
        return response.json() if response.text else {}

    def send_message(self, channel_id: str, message: str) -> str:
        """Send a message to a Discord channel.

        Args:
            channel_id (str): The ID of the channel to send the message to.
            message (str): The text of the message to send.

        Returns:
            str: A success message or error message.
        """
        try:
            data = {"content": message}
            response = self._make_request("POST", f"/channels/{channel_id}/messages", data)
            return json.dumps({"status": "success", "channel_id": channel_id, "message_id": response.get("id", "")})
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return json.dumps({"error": str(e)})

    def send_message_thread(self, channel_id: str, message: str, message_id: str) -> str:
        """Reply to a message in a Discord channel.

        Args:
            channel_id (str): The ID of the channel containing the message.
            message (str): The text of the reply.
            message_id (str): The ID of the message to reply to.

        Returns:
            str: A JSON string containing the response from the Discord API.
        """
        try:
            data: Dict[str, Any] = {
                "content": message,
                "message_reference": {"message_id": message_id},
            }
            response = self._make_request("POST", f"/channels/{channel_id}/messages", data)
            return json.dumps(response, indent=2)
        except Exception as e:
            logger.error(f"Error sending thread reply: {e}")
            return json.dumps({"error": str(e)})

    def upload_file(
        self,
        channel_id: str,
        content: Union[str, bytes],
        filename: str,
        message: Optional[str] = None,
    ) -> str:
        """Upload a file to a Discord channel.

        Args:
            channel_id (str): The channel ID to upload the file to.
            content (str or bytes): The file content. Text strings will be encoded to bytes.
            filename (str): The name for the uploaded file.
            message (str): An optional message to include with the file upload.

        Returns:
            str: A JSON string containing the response from the Discord API.
        """
        try:
            if isinstance(content, str):
                content_bytes = content.encode("utf-8")
            else:
                content_bytes = content

            url = f"{self.base_url}/channels/{channel_id}/messages"
            payload: Dict[str, Any] = {}
            if message:
                payload["content"] = message

            response = self._session.post(
                url,
                data={"payload_json": json.dumps(payload)},
                files={"files[0]": (filename, content_bytes)},
                timeout=30,
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return json.dumps({"error": str(e)})

    def download_file(self, attachment_url: str) -> str:
        """Download a file from a Discord attachment URL.

        Args:
            attachment_url (str): The URL of the Discord attachment to download.
                Must be a Discord CDN URL (cdn.discordapp.com or media.discordapp.net).

        Returns:
            str: A JSON string containing the filename, size, and base64-encoded content.
        """
        try:
            parsed = urlparse(attachment_url)
            if parsed.hostname not in DISCORD_CDN_DOMAINS:
                return json.dumps(
                    {"error": f"URL domain not allowed. Must be one of: {', '.join(sorted(DISCORD_CDN_DOMAINS))}"}
                )

            response = self._session.get(attachment_url, timeout=30)
            response.raise_for_status()

            filename = attachment_url.split("/")[-1].split("?")[0]

            return json.dumps(
                {
                    "filename": filename,
                    "size": len(response.content),
                    "content_base64": base64.b64encode(response.content).decode("utf-8"),
                }
            )
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return json.dumps({"error": str(e)})

    def get_channel_info(self, channel_id: str) -> str:
        """Get information about a Discord channel.

        Args:
            channel_id (str): The ID of the channel to get information about.

        Returns:
            str: A JSON string containing the channel information.
        """
        try:
            response = self._make_request("GET", f"/channels/{channel_id}")
            return json.dumps(response, indent=2)
        except Exception as e:
            logger.error(f"Error getting channel info: {e}")
            return json.dumps({"error": str(e)})

    def list_channels(self, guild_id: str) -> str:
        """List all channels in a Discord server.

        Args:
            guild_id (str): The ID of the server to list channels from.

        Returns:
            str: A JSON string containing the list of channels.
        """
        try:
            response = self._make_request("GET", f"/guilds/{guild_id}/channels")
            return json.dumps(response, indent=2)
        except Exception as e:
            logger.error(f"Error listing channels: {e}")
            return json.dumps({"error": str(e)})

    def get_channel_messages(self, channel_id: str, limit: int = 100) -> str:
        """Get the message history of a Discord channel.

        Args:
            channel_id (str): The ID of the channel to fetch messages from.
            limit (int): The maximum number of messages to fetch. Defaults to 100.

        Returns:
            str: A JSON string containing the channel's message history.
        """
        try:
            response = self._make_request("GET", f"/channels/{channel_id}/messages", params={"limit": limit})
            return json.dumps(response, indent=2)
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return json.dumps({"error": str(e)})

    def delete_message(self, channel_id: str, message_id: str) -> str:
        """Delete a message from a Discord channel.

        Args:
            channel_id (str): The ID of the channel containing the message.
            message_id (str): The ID of the message to delete.

        Returns:
            str: A success message or error message.
        """
        try:
            self._make_request("DELETE", f"/channels/{channel_id}/messages/{message_id}")
            return json.dumps({"status": "success", "channel_id": channel_id, "message_id": message_id})
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return json.dumps({"error": str(e)})

    def search_messages(self, guild_id: str, query: str, limit: int = 25) -> str:
        """Search messages in a Discord server.

        Args:
            guild_id (str): The ID of the server to search in.
            query (str): The search query string.
            limit (int): The maximum number of results to return. Defaults to 25, max 25.

        Returns:
            str: A JSON string containing matching messages.
        """
        try:
            params: Dict[str, Any] = {"content": query, "limit": min(limit, 25)}
            response = self._make_request("GET", f"/guilds/{guild_id}/messages/search", params=params)
            return json.dumps(response, indent=2)
        except Exception as e:
            logger.error(f"Error searching messages: {e}")
            return json.dumps({"error": str(e)})

    def get_thread(self, channel_id: str, limit: int = 100) -> str:
        """Get messages from a Discord thread.

        Args:
            channel_id (str): The ID of the thread channel.
            limit (int): The maximum number of messages to fetch. Defaults to 100.

        Returns:
            str: A JSON string containing the thread messages.
        """
        try:
            response = self._make_request("GET", f"/channels/{channel_id}/messages", params={"limit": limit})
            return json.dumps(response, indent=2)
        except Exception as e:
            logger.error(f"Error getting thread: {e}")
            return json.dumps({"error": str(e)})

    def list_users(self, guild_id: str, limit: int = 100) -> str:
        """List members of a Discord server.

        Args:
            guild_id (str): The ID of the server to list members from.
            limit (int): The maximum number of members to fetch. Defaults to 100, max 1000.

        Returns:
            str: A JSON string containing the count and list of server members.
        """
        try:
            response = self._make_request("GET", f"/guilds/{guild_id}/members", params={"limit": min(limit, 1000)})
            items: list = response if isinstance(response, list) else []
            members = [
                {
                    "user_id": m.get("user", {}).get("id", ""),
                    "username": m.get("user", {}).get("username", ""),
                    "display_name": m.get("nick") or m.get("user", {}).get("global_name", ""),
                    "joined_at": m.get("joined_at", ""),
                    "is_bot": m.get("user", {}).get("bot", False),
                }
                for m in items
            ]
            return json.dumps({"count": len(members), "members": members})
        except Exception as e:
            logger.error(f"Error listing users: {e}")
            return json.dumps({"error": str(e)})

    def get_user_info(self, user_id: str) -> str:
        """Get information about a Discord user.

        Args:
            user_id (str): The ID of the user to get information about.

        Returns:
            str: A JSON string containing the user information.
        """
        try:
            response = self._make_request("GET", f"/users/{user_id}")
            return json.dumps(
                {
                    "id": response.get("id", ""),
                    "username": response.get("username", ""),
                    "global_name": response.get("global_name", ""),
                    "bot": response.get("bot", False),
                    "avatar": response.get("avatar"),
                }
            )
        except Exception as e:
            logger.error(f"Error getting user info: {e}")
            return json.dumps({"error": str(e)})
