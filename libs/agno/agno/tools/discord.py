import asyncio
import io
import json
from os import getenv
from typing import Any, Dict, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import aiohttp
    import discord
except ImportError:
    raise ImportError("`discord.py` not installed. Please install using `pip install discord.py`")

DISCORD_API_BASE = "https://discord.com/api/v10"


class DiscordTools(Toolkit):
    def __init__(
        self,
        bot_token: Optional[str] = None,
        async_mode: bool = False,
        enable_send_message: bool = True,
        enable_get_channel_messages: bool = True,
        enable_get_channel_info: bool = True,
        enable_list_channels: bool = True,
        enable_delete_message: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.bot_token = bot_token or getenv("DISCORD_BOT_TOKEN")
        self.async_mode = async_mode

        if not self.bot_token:
            if async_mode:
                logger.warning(
                    "DISCORD_BOT_TOKEN not set. Channel operations will fail, but webhook operations will work."
                )
            else:
                logger.error("DISCORD_BOT_TOKEN not set. Please set the DISCORD_BOT_TOKEN environment variable.")
                raise ValueError("Discord bot token is required for channel operations")

        self.base_url = DISCORD_API_BASE
        self.headers: Dict[str, str] = {}
        if self.bot_token:
            self.headers = {
                "Authorization": f"Bot {self.bot_token}",
                "Content-Type": "application/json",
            }

        # discord.Client for async channel operations (REST-only, no gateway)
        self._client: Optional[discord.Client] = None
        self._client_lock: Optional[asyncio.Lock] = None

        # aiohttp session for webhook ops that need raw REST
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._session_lock: Optional[asyncio.Lock] = None

        tools: List[Any] = []
        if async_mode:
            if enable_send_message or all:
                tools.append(self.send_message_async)
            if enable_get_channel_messages or all:
                tools.append(self.get_channel_messages_async)
            if enable_get_channel_info or all:
                tools.append(self.get_channel_info_async)
            if enable_list_channels or all:
                tools.append(self.list_channels_async)
            if enable_delete_message or all:
                tools.append(self.delete_message_async)
        else:
            if enable_send_message or all:
                tools.append(self.send_message)
            if enable_get_channel_messages or all:
                tools.append(self.get_channel_messages)
            if enable_get_channel_info or all:
                tools.append(self.get_channel_info)
            if enable_list_channels or all:
                tools.append(self.list_channels)
            if enable_delete_message or all:
                tools.append(self.delete_message)

        super().__init__(name="discord", tools=tools, **kwargs)

    # --- Client management (async channel ops via SDK) ---

    async def _get_client(self) -> discord.Client:
        if self._client_lock is None:
            self._client_lock = asyncio.Lock()
        async with self._client_lock:
            if self._client is None:
                self._client = discord.Client(intents=discord.Intents.none())
                await self._client.login(self.bot_token)
        return self._client

    # --- Session management (webhook ops that need raw REST) ---

    async def _get_aiohttp_session(self) -> aiohttp.ClientSession:
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        async with self._session_lock:
            if self._http_session is None or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
        return self._http_session

    # --- Sync channel tools (agent use, raw requests — no sync SDK) ---

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, json=data)
        response.raise_for_status()
        return response.json() if response.text else {}

    def send_message(self, channel_id: str, message: str) -> str:
        """
        Send a message to a Discord channel.

        Args:
            channel_id (str): The ID of the channel to send the message to.
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

    def get_channel_info(self, channel_id: str) -> str:
        """
        Get information about a Discord channel.

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
            return f"Error getting channel info: {str(e)}"

    def list_channels(self, guild_id: str) -> str:
        """
        List all channels in a Discord server.

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
            return f"Error listing channels: {str(e)}"

    def get_channel_messages(self, channel_id: str, limit: int = 100) -> str:
        """
        Get the message history of a Discord channel.

        Args:
            channel_id (str): The ID of the channel to fetch messages from.
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

    def delete_message(self, channel_id: str, message_id: str) -> str:
        """
        Delete a message from a Discord channel.

        Args:
            channel_id (str): The ID of the channel containing the message.
            message_id (str): The ID of the message to delete.

        Returns:
            str: A success message or error message.
        """
        try:
            self._make_request("DELETE", f"/channels/{channel_id}/messages/{message_id}")
            return f"Message {message_id} deleted successfully from channel {channel_id}"
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return f"Error deleting message: {str(e)}"

    # --- Async channel tools (agent use, discord.Client SDK) ---

    async def send_message_async(self, channel_id: str, message: str) -> str:
        """
        Send a message to a Discord channel.

        Args:
            channel_id (str): The ID of the channel to send the message to.
            message (str): The text of the message to send.

        Returns:
            str: A success message or error message.
        """
        try:
            client = await self._get_client()
            channel = await client.fetch_channel(int(channel_id))
            await channel.send(content=message)  # type: ignore[union-attr]
            return f"Message sent successfully to channel {channel_id}"
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return f"Error sending message: {str(e)}"

    async def get_channel_info_async(self, channel_id: str) -> str:
        """
        Get information about a Discord channel.

        Args:
            channel_id (str): The ID of the channel to get information about.

        Returns:
            str: A JSON string containing the channel information.
        """
        try:
            client = await self._get_client()
            channel = await client.fetch_channel(int(channel_id))
            info: Dict[str, Any] = {
                "id": str(channel.id),
                "type": channel.type.value,
            }
            if hasattr(channel, "name"):
                info["name"] = channel.name  # type: ignore[union-attr]
            if hasattr(channel, "guild_id"):
                info["guild_id"] = str(channel.guild_id)  # type: ignore[union-attr]
            if hasattr(channel, "topic"):
                info["topic"] = channel.topic  # type: ignore[union-attr]
            if hasattr(channel, "position"):
                info["position"] = channel.position  # type: ignore[union-attr]
            if hasattr(channel, "nsfw"):
                info["nsfw"] = channel.nsfw  # type: ignore[union-attr]
            return json.dumps(info, indent=2)
        except Exception as e:
            logger.error(f"Error getting channel info: {e}")
            return f"Error getting channel info: {str(e)}"

    async def list_channels_async(self, guild_id: str) -> str:
        """
        List all channels in a Discord server.

        Args:
            guild_id (str): The ID of the server to list channels from.

        Returns:
            str: A JSON string containing the list of channels.
        """
        try:
            client = await self._get_client()
            guild = await client.fetch_guild(int(guild_id))
            channels = await guild.fetch_channels()
            result = []
            for ch in channels:
                entry: Dict[str, Any] = {
                    "id": str(ch.id),
                    "name": ch.name,
                    "type": ch.type.value,
                }
                if hasattr(ch, "position"):
                    entry["position"] = ch.position
                result.append(entry)
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"Error listing channels: {e}")
            return f"Error listing channels: {str(e)}"

    async def get_channel_messages_async(self, channel_id: str, limit: int = 100) -> str:
        """
        Get the message history of a Discord channel.

        Args:
            channel_id (str): The ID of the channel to fetch messages from.
            limit (int): The maximum number of messages to fetch. Defaults to 100.

        Returns:
            str: A JSON string containing the channel's message history.
        """
        try:
            client = await self._get_client()
            channel = await client.fetch_channel(int(channel_id))
            messages = []
            async for msg in channel.history(limit=limit):  # type: ignore[union-attr]
                messages.append(
                    {
                        "id": str(msg.id),
                        "content": msg.content,
                        "author": {"id": str(msg.author.id), "username": msg.author.name},
                        "timestamp": msg.created_at.isoformat(),
                    }
                )
            return json.dumps(messages, indent=2)
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return f"Error getting messages: {str(e)}"

    async def delete_message_async(self, channel_id: str, message_id: str) -> str:
        """
        Delete a message from a Discord channel.

        Args:
            channel_id (str): The ID of the channel containing the message.
            message_id (str): The ID of the message to delete.

        Returns:
            str: A success message or error message.
        """
        try:
            client = await self._get_client()
            channel = await client.fetch_channel(int(channel_id))
            message = await channel.fetch_message(int(message_id))  # type: ignore[union-attr]
            await message.delete()
            return f"Message {message_id} deleted successfully from channel {channel_id}"
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return f"Error deleting message: {str(e)}"

    # --- Webhook operations (interface use, not registered as tools) ---

    async def send_webhook_followup(
        self,
        application_id: str,
        interaction_token: str,
        content: str,
        ephemeral: bool = False,
    ) -> None:
        session = await self._get_aiohttp_session()
        webhook_url = f"{self.base_url}/webhooks/{application_id}/{interaction_token}"
        webhook = discord.Webhook.from_url(webhook_url, session=session)
        await webhook.send(content=content, ephemeral=ephemeral)

    async def edit_webhook_message(
        self,
        application_id: str,
        interaction_token: str,
        content: str,
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        # Raw REST — Webhook.edit_message() expects int message_id, can't handle @original sentinel
        session = await self._get_aiohttp_session()
        url = f"{self.base_url}/webhooks/{application_id}/{interaction_token}/messages/@original"
        payload: Dict[str, Any] = {"content": content}
        if components is not None:
            payload["components"] = components
        async with session.patch(url, json=payload) as resp:
            resp.raise_for_status()

    async def download_attachment_async(self, url: str, max_size: int = 25 * 1024 * 1024) -> Optional[bytes]:
        session = await self._get_aiohttp_session()
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                content_length = resp.content_length or 0
                if content_length > max_size:
                    logger.warning(f"Attachment too large ({content_length} bytes), skipping")
                    return None
                return await resp.read()
        except Exception as e:
            logger.error(f"Failed to download attachment: {e}")
            return None

    async def upload_webhook_file(
        self,
        application_id: str,
        interaction_token: str,
        filename: str,
        content_bytes: bytes,
        mime_type: str = "application/octet-stream",
    ) -> None:
        session = await self._get_aiohttp_session()
        webhook_url = f"{self.base_url}/webhooks/{application_id}/{interaction_token}"
        webhook = discord.Webhook.from_url(webhook_url, session=session)
        file = discord.File(io.BytesIO(content_bytes), filename=filename)
        await webhook.send(content="", file=file)

    @staticmethod
    def get_tool_name() -> str:
        return "discord"

    @staticmethod
    def get_tool_description() -> str:
        return "Tool for interacting with Discord channels and servers"

    @staticmethod
    def get_tool_config() -> dict:
        return {
            "bot_token": {"type": "string", "description": "Discord bot token for authentication", "required": True}
        }
