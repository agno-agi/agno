"""Discord integration tools for interacting with Discord channels and servers."""

import json
from os import getenv
from typing import Any, Dict, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import logger


class DiscordTools(Toolkit):
    def __init__(
        self,
        bot_token: Optional[str] = None,
        enable_messaging: bool = True,
        enable_history: bool = True,
        enable_channel_management: bool = True,
        enable_message_management: bool = True,
        **kwargs,
    ):
        """Initialize Discord tools."""
        super().__init__(name="discord", **kwargs)

        self.bot_token = bot_token or getenv("DISCORD_BOT_TOKEN")
        if not self.bot_token:
            logger.error("Discord bot token is required")
            raise ValueError("Discord bot token is required")

        self.base_url = "https://discord.com/api/v10"
        self.headers = {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
        }

        # Register tools based on enabled features
        if enable_messaging:
            self.register(self.send_message)
        if enable_history:
            self.register(self.get_channel_messages)
        if enable_channel_management:
            self.register(self.get_channel_info)
            self.register(self.list_channels)
        if enable_message_management:
            self.register(self.delete_message)

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to Discord API."""
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, json=data)
        response.raise_for_status()
        return response.json() if response.text else {}

    def send_message(self, channel_id: int, message: str) -> str:
        """
        Send a message to a Discord channel.

        Args:
            channel_id (int): The ID of the channel to send the message to.
            message (str): The text of the message to send.

        Returns:
            str: A success message or error message.
        """
        try:
            data = {"content": message}
            self._make_request("POST", f"/channels/{channel_id}/messages", data)
            return f"Message sent successfully to channel {channel_id}"
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return f"Error sending message: {str(e)}"

    def get_channel_info(self, channel_id: int) -> str:
        """
        Get information about a Discord channel.

        Args:
            channel_id (int): The ID of the channel to get information about.

        Returns:
            str: A JSON string containing the channel information.
        """
        try:
            response = self._make_request("GET", f"/channels/{channel_id}")
            return json.dumps(response, indent=2)
        except Exception as e:
            logger.error(f"Error getting channel info: {e}")
            return f"Error getting channel info: {str(e)}"

    def list_channels(self, guild_id: int) -> str:
        """
        List all channels in a Discord server.

        Args:
            guild_id (int): The ID of the server to list channels from.

        Returns:
            str: A JSON string containing the list of channels.
        """
        try:
            response = self._make_request("GET", f"/guilds/{guild_id}/channels")
            return json.dumps(response, indent=2)
        except Exception as e:
            logger.error(f"Error listing channels: {e}")
            return f"Error listing channels: {str(e)}"

    def get_channel_messages(self, channel_id: int, limit: int = 100) -> str:
        """
        Get the message history of a Discord channel.

        Args:
            channel_id (int): The ID of the channel to fetch messages from.
            limit (int): The maximum number of messages to fetch. Defaults to 100.

        Returns:
            str: A JSON string containing the channel's message history.
        """
        try:
            response = self._make_request("GET", f"/channels/{channel_id}/messages?limit={limit}")
            return json.dumps(response, indent=2)
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return f"Error getting messages: {str(e)}"

    def delete_message(self, channel_id: int, message_id: int) -> str:
        """
        Delete a message from a Discord channel.

        Args:
            channel_id (int): The ID of the channel containing the message.
            message_id (int): The ID of the message to delete.

        Returns:
            str: A success message or error message.
        """
        try:
            self._make_request("DELETE", f"/channels/{channel_id}/messages/{message_id}")
            return f"Message {message_id} deleted successfully from channel {channel_id}"
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return f"Error deleting message: {str(e)}"

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
