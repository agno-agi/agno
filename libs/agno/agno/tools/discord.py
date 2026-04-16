"""
Discord Bot Tools — interact with Discord channels, threads, and servers.

Setup:
1. Create a Discord application at https://discord.com/developers/applications
2. Go to the Bot section and create a bot
3. Copy the bot token and set it as the DISCORD_BOT_TOKEN environment variable
4. Under OAuth2 > URL Generator, select the "bot" scope
5. Select required bot permissions:
   - Send Messages
   - Read Message History
   - Manage Messages (for delete/pin)
   - Add Reactions
   - Create Public Threads / Create Private Threads
   - Send Messages in Threads
   - View Channel
6. Use the generated URL to invite the bot to your server

Required permissions vary by tool:
- send_message, send_message_in_thread, send_embed: Send Messages
- get_channel_messages, get_thread_messages: Read Message History
- list_channels, get_channel_info: View Channel
- delete_message, pin_message: Manage Messages
- create_thread, create_forum_thread: Create Public Threads
- add_reaction, remove_reaction: Add Reactions
- list_members, get_member_info: Server Members Intent (privileged, enable in Developer Portal)
"""

import json
from os import getenv
from typing import Any, Dict, List, Optional
from urllib.parse import quote as url_quote

import requests

from agno.tools import Toolkit
from agno.utils.log import log_error


class DiscordTools(Toolkit):
    """Tools for interacting with Discord servers, channels, and threads.

    Uses the Discord REST API (v10) with bot token authentication.
    All methods return JSON strings for LLM consumption.
    """

    @classmethod
    def _build_instructions(cls, tool_names: list[str]) -> str:
        """Build instructions based on which tools are actually enabled.

        Only references tools the LLM can call — never mentions disabled tools.
        """
        enabled = set(tool_names)
        sections: list[str] = []

        if "get_channel_messages" in enabled:
            text = (
                "**get_channel_messages** — recent messages from a specific channel.\n"
                "When to use: reading the latest activity in a known channel."
            )
            if "get_thread_messages" in enabled:
                text += "\nFor thread conversations, use get_thread_messages instead."
            sections.append(text)

        if "get_thread_messages" in enabled:
            sections.append(
                "**get_thread_messages** — messages from a thread.\n"
                "When to use: reading a threaded conversation. Threads are channels in Discord,\n"
                "so you need the thread's channel ID (returned when creating a thread)."
            )

        if "send_message" in enabled and "send_message_in_thread" in enabled:
            sections.append(
                "**send_message** vs **send_message_in_thread** — choosing correctly:\n"
                "- Use send_message for top-level channel messages.\n"
                "- Use send_message_in_thread when replying inside a thread.\n"
                "- In Discord, threads have their own channel ID. Use that ID with send_message_in_thread."
            )
        elif "send_message_in_thread" in enabled:
            sections.append(
                "**send_message_in_thread** — send a message inside a thread.\n"
                "Threads have their own channel ID in Discord."
            )

        if "create_thread" in enabled or "create_forum_thread" in enabled:
            parts: list[str] = []
            if "create_thread" in enabled:
                parts.append(
                    "**create_thread** — create a thread from an existing message.\n"
                    "When to use: starting a discussion about a specific message."
                )
            if "create_forum_thread" in enabled:
                parts.append(
                    "**create_forum_thread** — create a new post in a forum channel.\n"
                    "When to use: creating a new topic in a forum-type channel. Requires an initial message."
                )
            sections.extend(parts)

        if "send_embed" in enabled:
            sections.append(
                "**send_embed** — send a rich embed with title, description, color, and fields.\n"
                "When to use: sending formatted announcements, summaries, or structured data."
            )

        if len(sections) < 2:
            return ""

        result = "## Discord Tool Selection\n\n" + "\n\n".join(sections)

        routing: list[str] = []
        if "send_message" in enabled and "send_message_in_thread" in enabled:
            routing.append("- New channel message -> send_message")
            routing.append("- Reply in a thread -> send_message_in_thread (use the thread's channel ID)")
        if "get_channel_messages" in enabled and "get_thread_messages" in enabled:
            routing.append("- Channel history -> get_channel_messages")
            routing.append("- Thread history -> get_thread_messages")
        if "create_thread" in enabled and "create_forum_thread" in enabled:
            routing.append("- Thread from a message -> create_thread")
            routing.append("- New forum post -> create_forum_thread")

        if routing:
            result += "\n\n## When to use which\n" + "\n".join(routing)

        return result

    def __init__(
        self,
        bot_token: Optional[str] = None,
        guild_id: Optional[str] = None,
        enable_send_message: bool = True,
        enable_send_message_in_thread: bool = True,
        enable_get_channel_messages: bool = True,
        enable_list_channels: bool = True,
        enable_create_thread: bool = True,
        enable_create_forum_thread: bool = False,
        enable_get_thread_messages: bool = False,
        enable_get_channel_info: bool = False,
        enable_add_reaction: bool = False,
        enable_remove_reaction: bool = False,
        enable_list_members: bool = False,
        enable_get_member_info: bool = False,
        enable_pin_message: bool = False,
        enable_send_embed: bool = False,
        enable_delete_message: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """Initialize the DiscordTools toolkit.

        Args:
            bot_token: Discord bot token. Defaults to the DISCORD_BOT_TOKEN environment variable.
            guild_id: Default guild (server) ID for list_channels and list_members.
                Defaults to the DISCORD_GUILD_ID environment variable.
            enable_send_message: Enable the send_message tool. Defaults to True.
            enable_send_message_in_thread: Enable the send_message_in_thread tool. Defaults to True.
            enable_get_channel_messages: Enable the get_channel_messages tool. Defaults to True.
            enable_list_channels: Enable the list_channels tool. Defaults to True.
            enable_create_thread: Enable the create_thread tool. Defaults to True.
            enable_create_forum_thread: Enable the create_forum_thread tool. Defaults to False.
            enable_get_thread_messages: Enable the get_thread_messages tool. Defaults to False.
            enable_get_channel_info: Enable the get_channel_info tool. Defaults to False.
            enable_add_reaction: Enable the add_reaction tool. Defaults to False.
            enable_remove_reaction: Enable the remove_reaction tool. Defaults to False.
            enable_list_members: Enable the list_members tool. Defaults to False.
            enable_get_member_info: Enable the get_member_info tool. Defaults to False.
            enable_pin_message: Enable the pin_message tool. Defaults to False.
            enable_send_embed: Enable the send_embed tool. Defaults to False.
            enable_delete_message: Enable the delete_message tool. Defaults to False.
            all: Enable all tools. Defaults to False.
        """
        _token = bot_token or getenv("DISCORD_BOT_TOKEN")
        if not _token:
            raise ValueError("DISCORD_BOT_TOKEN is not set")

        self.bot_token: str = _token
        self.guild_id: Optional[str] = guild_id or getenv("DISCORD_GUILD_ID")
        self.base_url = "https://discord.com/api/v10"
        self.headers = {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
        }

        tools: List[Any] = []
        if enable_send_message or all:
            tools.append(self.send_message)
        if enable_send_message_in_thread or all:
            tools.append(self.send_message_in_thread)
        if enable_get_channel_messages or all:
            tools.append(self.get_channel_messages)
        if enable_list_channels or all:
            tools.append(self.list_channels)
        if enable_create_thread or all:
            tools.append(self.create_thread)
        if enable_create_forum_thread or all:
            tools.append(self.create_forum_thread)
        if enable_get_thread_messages or all:
            tools.append(self.get_thread_messages)
        if enable_get_channel_info or all:
            tools.append(self.get_channel_info)
        if enable_add_reaction or all:
            tools.append(self.add_reaction)
        if enable_remove_reaction or all:
            tools.append(self.remove_reaction)
        if enable_list_members or all:
            tools.append(self.list_members)
        if enable_get_member_info or all:
            tools.append(self.get_member_info)
        if enable_pin_message or all:
            tools.append(self.pin_message)
        if enable_send_embed or all:
            tools.append(self.send_embed)
        if enable_delete_message or all:
            tools.append(self.delete_message)

        if kwargs.get("instructions") is None:
            tool_names = [t.__name__ for t in tools]
            built = self._build_instructions(tool_names)
            if built:
                kwargs["instructions"] = built
                kwargs.setdefault("add_instructions", True)

        super().__init__(name="discord", tools=tools, **kwargs)

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to the Discord API that returns a JSON object.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH).
            endpoint: API endpoint path (e.g., /channels/{id}/messages).
            data: Optional JSON body for the request.

        Returns:
            Parsed JSON response, or empty dict for 204 No Content responses.
        """
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, json=data)
        response.raise_for_status()
        if response.status_code == 204:
            return {}
        return response.json() if response.text else {}

    def _make_list_request(self, method: str, endpoint: str) -> List[Dict[str, Any]]:
        """Make a request to the Discord API that returns a JSON array.

        Args:
            method: HTTP method (typically GET).
            endpoint: API endpoint path that returns a list.

        Returns:
            Parsed JSON array response, or empty list on failure.
        """
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers)
        response.raise_for_status()
        result = response.json() if response.text else []
        return result if isinstance(result, list) else []

    def send_message(self, channel_id: str, message: str) -> str:
        """Send a message to a Discord channel.

        Args:
            channel_id: The ID of the channel to send the message to.
            message: The text content of the message. Supports Discord markdown.

        Returns:
            A JSON string containing the created message object with id, content, author, and timestamp.
        """
        try:
            result = self._make_request("POST", f"/channels/{channel_id}/messages", {"content": message})
            return json.dumps(
                {
                    "id": result.get("id", ""),
                    "channel_id": result.get("channel_id", ""),
                    "content": result.get("content", ""),
                    "author": result.get("author", {}).get("username", ""),
                    "timestamp": result.get("timestamp", ""),
                }
            )
        except requests.HTTPError as e:
            log_error(f"Failed to send message to channel {channel_id}: {e}")
            return json.dumps({"error": str(e)})

    def send_message_in_thread(self, thread_id: str, message: str) -> str:
        """Send a message inside a Discord thread.

        In Discord, threads have their own channel ID. Use the thread's ID as thread_id.

        Args:
            thread_id: The channel ID of the thread to send the message in.
            message: The text content of the message. Supports Discord markdown.

        Returns:
            A JSON string containing the created message object with id, content, author, and timestamp.
        """
        try:
            # Threads are channels in Discord
            result = self._make_request("POST", f"/channels/{thread_id}/messages", {"content": message})
            return json.dumps(
                {
                    "id": result.get("id", ""),
                    "thread_id": result.get("channel_id", ""),
                    "content": result.get("content", ""),
                    "author": result.get("author", {}).get("username", ""),
                    "timestamp": result.get("timestamp", ""),
                }
            )
        except requests.HTTPError as e:
            log_error(f"Failed to send message in thread {thread_id}: {e}")
            return json.dumps({"error": str(e)})

    def get_channel_messages(self, channel_id: str, limit: int = 50) -> str:
        """Get recent messages from a Discord channel.

        Args:
            channel_id: The ID of the channel to fetch messages from.
            limit: Maximum number of messages to return, between 1 and 100. Defaults to 50.

        Returns:
            A JSON string containing a list of messages, each with id, content, author, timestamp,
            and thread information if the message started a thread.
        """
        try:
            clamped = min(max(limit, 1), 100)
            raw = self._make_list_request("GET", f"/channels/{channel_id}/messages?limit={clamped}")
            messages = []
            for msg in raw:
                entry: Dict[str, Any] = {
                    "id": msg.get("id", ""),
                    "content": msg.get("content", ""),
                    "author": msg.get("author", {}).get("username", ""),
                    "author_id": msg.get("author", {}).get("id", ""),
                    "timestamp": msg.get("timestamp", ""),
                }
                # Surface thread metadata so the LLM can discover threads
                thread = msg.get("thread")
                if thread:
                    entry["thread_id"] = thread.get("id", "")
                    entry["thread_name"] = thread.get("name", "")
                    entry["thread_message_count"] = thread.get("message_count", 0)
                messages.append(entry)
            return json.dumps({"count": len(messages), "messages": messages})
        except requests.HTTPError as e:
            log_error(f"Failed to get messages from channel {channel_id}: {e}")
            return json.dumps({"error": str(e)})

    def get_channel_info(self, channel_id: str) -> str:
        """Get metadata about a Discord channel.

        Args:
            channel_id: The ID of the channel to get information about.

        Returns:
            A JSON string containing the channel's id, name, type, topic, guild_id,
            and position in the channel list.
        """
        try:
            ch = self._make_request("GET", f"/channels/{channel_id}")
            return json.dumps(
                {
                    "id": ch.get("id", ""),
                    "name": ch.get("name", ""),
                    "type": ch.get("type", 0),
                    "topic": ch.get("topic", ""),
                    "guild_id": ch.get("guild_id", ""),
                    "position": ch.get("position", 0),
                    "nsfw": ch.get("nsfw", False),
                    "parent_id": ch.get("parent_id"),
                }
            )
        except requests.HTTPError as e:
            log_error(f"Failed to get channel info for {channel_id}: {e}")
            return json.dumps({"error": str(e)})

    def list_channels(self, guild_id: Optional[str] = None) -> str:
        """List all channels in a Discord server (guild).

        Args:
            guild_id: The ID of the server. Falls back to the default guild_id set during init.

        Returns:
            A JSON string containing a list of channels with id, name, type, and position.
        """
        gid = guild_id or self.guild_id
        if not gid:
            return json.dumps({"error": "guild_id is required. Provide it as an argument or set it during init."})
        try:
            raw = self._make_list_request("GET", f"/guilds/{gid}/channels")
            channels = [
                {
                    "id": ch.get("id", ""),
                    "name": ch.get("name", ""),
                    "type": ch.get("type", 0),
                    "position": ch.get("position", 0),
                    "parent_id": ch.get("parent_id"),
                }
                for ch in raw
            ]
            return json.dumps({"count": len(channels), "channels": channels})
        except requests.HTTPError as e:
            log_error(f"Failed to list channels for guild {gid}: {e}")
            return json.dumps({"error": str(e)})

    def delete_message(self, channel_id: str, message_id: str) -> str:
        """Delete a message from a Discord channel.

        Requires the Manage Messages permission, or be the message author.

        Args:
            channel_id: The ID of the channel containing the message.
            message_id: The ID of the message to delete.

        Returns:
            A JSON string confirming deletion or containing an error.
        """
        try:
            self._make_request("DELETE", f"/channels/{channel_id}/messages/{message_id}")
            return json.dumps({"ok": True, "channel_id": channel_id, "message_id": message_id})
        except requests.HTTPError as e:
            log_error(f"Failed to delete message {message_id} from channel {channel_id}: {e}")
            return json.dumps({"error": str(e)})

    def create_thread(
        self,
        channel_id: str,
        message_id: str,
        name: str,
        auto_archive_duration: int = 1440,
    ) -> str:
        """Create a thread from an existing message in a channel.

        Args:
            channel_id: The ID of the channel containing the message.
            message_id: The ID of the message to start the thread from.
            name: Name for the thread (1-100 characters).
            auto_archive_duration: Minutes of inactivity before auto-archiving.
                Valid values: 60, 1440, 4320, 10080. Defaults to 1440 (24 hours).

        Returns:
            A JSON string containing the created thread's id, name, and parent channel id.
        """
        try:
            result = self._make_request(
                "POST",
                f"/channels/{channel_id}/messages/{message_id}/threads",
                {
                    "name": name,
                    "auto_archive_duration": auto_archive_duration,
                },
            )
            return json.dumps(
                {
                    "id": result.get("id", ""),
                    "name": result.get("name", ""),
                    "parent_id": result.get("parent_id", ""),
                    "type": result.get("type", 0),
                    "message_count": result.get("message_count", 0),
                }
            )
        except requests.HTTPError as e:
            log_error(f"Failed to create thread on message {message_id}: {e}")
            return json.dumps({"error": str(e)})

    def create_forum_thread(
        self,
        channel_id: str,
        name: str,
        content: str,
        auto_archive_duration: int = 1440,
    ) -> str:
        """Create a new thread (post) in a forum channel.

        Forum channels require an initial message when creating a thread.

        Args:
            channel_id: The ID of the forum channel.
            name: Name for the thread/post (1-100 characters).
            content: The text content of the initial message.
            auto_archive_duration: Minutes of inactivity before auto-archiving.
                Valid values: 60, 1440, 4320, 10080. Defaults to 1440 (24 hours).

        Returns:
            A JSON string containing the created thread's id, name, and the initial message id.
        """
        try:
            result = self._make_request(
                "POST",
                f"/channels/{channel_id}/threads",
                {
                    "name": name,
                    "auto_archive_duration": auto_archive_duration,
                    "message": {"content": content},
                },
            )
            return json.dumps(
                {
                    "id": result.get("id", ""),
                    "name": result.get("name", ""),
                    "parent_id": result.get("parent_id", ""),
                    "type": result.get("type", 0),
                }
            )
        except requests.HTTPError as e:
            log_error(f"Failed to create forum thread in channel {channel_id}: {e}")
            return json.dumps({"error": str(e)})

    def get_thread_messages(self, thread_id: str, limit: int = 50) -> str:
        """Get messages from a Discord thread.

        In Discord, threads are channels, so this fetches messages using the thread's channel ID.

        Args:
            thread_id: The channel ID of the thread.
            limit: Maximum number of messages to return, between 1 and 100. Defaults to 50.

        Returns:
            A JSON string containing a list of messages with id, content, author, and timestamp.
        """
        try:
            clamped = min(max(limit, 1), 100)
            raw = self._make_list_request("GET", f"/channels/{thread_id}/messages?limit={clamped}")
            messages = [
                {
                    "id": msg.get("id", ""),
                    "content": msg.get("content", ""),
                    "author": msg.get("author", {}).get("username", ""),
                    "author_id": msg.get("author", {}).get("id", ""),
                    "timestamp": msg.get("timestamp", ""),
                }
                for msg in raw
            ]
            return json.dumps({"thread_id": thread_id, "count": len(messages), "messages": messages})
        except requests.HTTPError as e:
            log_error(f"Failed to get messages from thread {thread_id}: {e}")
            return json.dumps({"error": str(e)})

    def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> str:
        """Add a reaction to a message.

        Args:
            channel_id: The ID of the channel containing the message.
            message_id: The ID of the message to react to.
            emoji: The emoji to react with. Use Unicode emoji (e.g., a thumbs-up character)
                or custom emoji in the format name:id (e.g., myemoji:123456789).

        Returns:
            A JSON string confirming the reaction was added or containing an error.
        """
        try:
            encoded_emoji = url_quote(emoji)
            self._make_request("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me")
            return json.dumps({"ok": True, "channel_id": channel_id, "message_id": message_id, "emoji": emoji})
        except requests.HTTPError as e:
            log_error(f"Failed to add reaction to message {message_id}: {e}")
            return json.dumps({"error": str(e)})

    def remove_reaction(self, channel_id: str, message_id: str, emoji: str) -> str:
        """Remove the bot's own reaction from a message.

        Args:
            channel_id: The ID of the channel containing the message.
            message_id: The ID of the message to remove the reaction from.
            emoji: The emoji to remove. Use Unicode emoji or custom emoji in the format name:id.

        Returns:
            A JSON string confirming the reaction was removed or containing an error.
        """
        try:
            encoded_emoji = url_quote(emoji)
            self._make_request("DELETE", f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me")
            return json.dumps({"ok": True, "channel_id": channel_id, "message_id": message_id, "emoji": emoji})
        except requests.HTTPError as e:
            log_error(f"Failed to remove reaction from message {message_id}: {e}")
            return json.dumps({"error": str(e)})

    def list_members(self, guild_id: Optional[str] = None, limit: int = 100) -> str:
        """List members of a Discord server (guild).

        Requires the Server Members Intent to be enabled in the Discord Developer Portal.

        Args:
            guild_id: The ID of the server. Falls back to the default guild_id set during init.
            limit: Maximum number of members to return, between 1 and 1000. Defaults to 100.

        Returns:
            A JSON string containing a list of members with user id, username, nickname,
            joined_at date, and roles.
        """
        gid = guild_id or self.guild_id
        if not gid:
            return json.dumps({"error": "guild_id is required. Provide it as an argument or set it during init."})
        try:
            clamped = min(max(limit, 1), 1000)
            raw = self._make_list_request("GET", f"/guilds/{gid}/members?limit={clamped}")
            members = [
                {
                    "user_id": m.get("user", {}).get("id", ""),
                    "username": m.get("user", {}).get("username", ""),
                    "display_name": m.get("nick") or m.get("user", {}).get("global_name", ""),
                    "joined_at": m.get("joined_at", ""),
                    "roles": m.get("roles", []),
                }
                for m in raw
            ]
            return json.dumps({"count": len(members), "members": members})
        except requests.HTTPError as e:
            log_error(f"Failed to list members for guild {gid}: {e}")
            return json.dumps({"error": str(e)})

    def get_member_info(self, guild_id: Optional[str] = None, user_id: str = "") -> str:
        """Get detailed information about a specific guild member.

        Args:
            guild_id: The ID of the server. Falls back to the default guild_id set during init.
            user_id: The Discord user ID to look up.

        Returns:
            A JSON string containing the member's user id, username, nickname, joined_at date,
            roles, and avatar URL.
        """
        gid = guild_id or self.guild_id
        if not gid:
            return json.dumps({"error": "guild_id is required. Provide it as an argument or set it during init."})
        if not user_id:
            return json.dumps({"error": "user_id is required."})
        try:
            m = self._make_request("GET", f"/guilds/{gid}/members/{user_id}")
            user = m.get("user", {})
            return json.dumps(
                {
                    "user_id": user.get("id", ""),
                    "username": user.get("username", ""),
                    "display_name": m.get("nick") or user.get("global_name", ""),
                    "joined_at": m.get("joined_at", ""),
                    "roles": m.get("roles", []),
                    "avatar": m.get("avatar"),
                    "is_bot": user.get("bot", False),
                }
            )
        except requests.HTTPError as e:
            log_error(f"Failed to get member info for user {user_id} in guild {gid}: {e}")
            return json.dumps({"error": str(e)})

    def pin_message(self, channel_id: str, message_id: str) -> str:
        """Pin a message in a Discord channel.

        Requires the Manage Messages permission. Channels have a max of 50 pinned messages.

        Args:
            channel_id: The ID of the channel containing the message.
            message_id: The ID of the message to pin.

        Returns:
            A JSON string confirming the message was pinned or containing an error.
        """
        try:
            self._make_request("PUT", f"/channels/{channel_id}/pins/{message_id}")
            return json.dumps({"ok": True, "channel_id": channel_id, "message_id": message_id})
        except requests.HTTPError as e:
            log_error(f"Failed to pin message {message_id} in channel {channel_id}: {e}")
            return json.dumps({"error": str(e)})

    def send_embed(
        self,
        channel_id: str,
        title: str,
        description: str,
        color: Optional[int] = None,
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Send a rich embed message to a Discord channel.

        Args:
            channel_id: The ID of the channel to send the embed to.
            title: The title of the embed.
            description: The description text of the embed. Supports Discord markdown.
            color: Optional integer color code for the embed sidebar (e.g., 0x00FF00 for green).
            fields: Optional list of field dicts, each with "name" (str), "value" (str),
                and optionally "inline" (bool, defaults to False).

        Returns:
            A JSON string containing the created message object with id and embed details.
        """
        try:
            embed: Dict[str, Any] = {
                "title": title,
                "description": description,
            }
            if color is not None:
                embed["color"] = color
            if fields:
                embed["fields"] = [
                    {
                        "name": f.get("name", ""),
                        "value": f.get("value", ""),
                        "inline": f.get("inline", False),
                    }
                    for f in fields
                ]
            result = self._make_request("POST", f"/channels/{channel_id}/messages", {"embeds": [embed]})
            return json.dumps(
                {
                    "id": result.get("id", ""),
                    "channel_id": result.get("channel_id", ""),
                    "embeds": result.get("embeds", []),
                    "timestamp": result.get("timestamp", ""),
                }
            )
        except requests.HTTPError as e:
            log_error(f"Failed to send embed to channel {channel_id}: {e}")
            return json.dumps({"error": str(e)})
