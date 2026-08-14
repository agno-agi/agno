"""Discord integration tools for interacting with Discord channels and servers."""

import json
from os import getenv
from typing import Any, Callable, Dict, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_error, logger


class DiscordTools(Toolkit):
    def __init__(
        self,
        bot_token: Optional[str] = None,
        send_message: bool = False,
        get_channel_messages: bool = True,
        get_channel_info: bool = True,
        list_channels: bool = True,
        delete_message: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """Initialize Discord toolkit.

        Args:
            bot_token: Discord bot token. Falls back to DISCORD_BOT_TOKEN env var.
            send_message: Enable the send_discord_message tool. Defaults to False
                (sends messages on the user's behalf).
            get_channel_messages: Enable the get_discord_channel_messages tool. Defaults to True.
            get_channel_info: Enable the get_discord_channel_info tool. Defaults to True.
            list_channels: Enable the list_discord_channels tool. Defaults to True.
            delete_message: Enable the delete_discord_message tool. Defaults to False
                (destructive).
            all: Enable all tools.
        """
        self.bot_token = bot_token or getenv("DISCORD_BOT_TOKEN")
        if not self.bot_token:
            log_error("Discord bot token is required")
            raise ValueError("Discord bot token is required")

        self.base_url = "https://discord.com/api/v10"
        self.headers = {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
        }

        tools: List[Callable] = []
        if all or send_message:
            tools.append(self.send_discord_message)
        if all or get_channel_messages:
            tools.append(self.get_discord_channel_messages)
        if all or get_channel_info:
            tools.append(self.get_discord_channel_info)
        if all or list_channels:
            tools.append(self.list_discord_channels)
        if all or delete_message:
            tools.append(self.delete_discord_message)

        super().__init__(name="discord", tools=tools, **kwargs)

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to Discord API."""
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, json=data)
        response.raise_for_status()
        return response.json() if response.text else {}

    def send_discord_message(self, channel_id: str, message: str) -> str:
        """Send a message to a Discord channel.

        Args:
            channel_id: The ID of the channel to send the message to.
            message: The text of the message to send.

        Returns:
            JSON with success status and message_id, or error.
        """
        try:
            data = {"content": message}
            result = self._make_request("POST", f"/channels/{channel_id}/messages", data)
            return json.dumps({"success": True, "channel_id": channel_id, "message_id": result.get("id")})
        except Exception as e:
            logger.exception("Error sending message")
            return json.dumps({"error": f"Error sending message: {str(e)}"})

    def get_discord_channel_info(self, channel_id: str) -> str:
        """Get information about a Discord channel.

        Args:
            channel_id: The ID of the channel to get information about.

        Returns:
            JSON with channel information or error.
        """
        try:
            response = self._make_request("GET", f"/channels/{channel_id}")
            return json.dumps(response)
        except Exception as e:
            logger.exception("Error getting channel info")
            return json.dumps({"error": f"Error getting channel info: {str(e)}"})

    def list_discord_channels(self, guild_id: str) -> str:
        """List all channels in a Discord server.

        Args:
            guild_id: The ID of the server (guild) to list channels from.

        Returns:
            JSON with channels array and count, or error.
        """
        try:
            response = self._make_request("GET", f"/guilds/{guild_id}/channels")
            return json.dumps({"channels": response, "count": len(response)})
        except Exception as e:
            logger.exception("Error listing channels")
            return json.dumps({"error": f"Error listing channels: {str(e)}"})

    def get_discord_channel_messages(self, channel_id: str, limit: int = 100) -> str:
        """Get the message history of a Discord channel.

        Args:
            channel_id: The ID of the channel to fetch messages from.
            limit: Maximum number of messages to fetch (default 100, max 100).

        Returns:
            JSON with messages array and count, or error.
        """
        try:
            response = self._make_request("GET", f"/channels/{channel_id}/messages?limit={limit}")
            return json.dumps({"messages": response, "count": len(response)})
        except Exception as e:
            logger.exception("Error getting messages")
            return json.dumps({"error": f"Error getting messages: {str(e)}"})

    def delete_discord_message(self, channel_id: str, message_id: str) -> str:
        """Delete a message from a Discord channel.

        Args:
            channel_id: The ID of the channel containing the message.
            message_id: The ID of the message to delete.

        Returns:
            JSON with success status or error.
        """
        try:
            self._make_request("DELETE", f"/channels/{channel_id}/messages/{message_id}")
            return json.dumps({"success": True, "deleted_message_id": message_id, "channel_id": channel_id})
        except Exception as e:
            logger.exception("Error deleting message")
            return json.dumps({"error": f"Error deleting message: {str(e)}"})

    @staticmethod
    def get_tool_name() -> str:
        """Get the name of the tool."""
        return "discord"

    @staticmethod
    def get_tool_description() -> str:
        """Get the description of the tool."""
        return "Tool for interacting with Discord channels and servers"

    @staticmethod
    def get_tool_config() -> dict:
        """Get the required configuration for the tool."""
        return {
            "bot_token": {"type": "string", "description": "Discord bot token for authentication", "required": True}
        }
