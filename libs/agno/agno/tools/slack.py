import base64
import json
from os import getenv
from pathlib import Path
from ssl import SSLContext
from typing import Any, Dict, List, Literal, Optional, Union

import httpx

from agno.run.base import RunContext
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning, logger

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError:
    raise ImportError("Slack tools require the `slack_sdk` package. Run `pip install slack-sdk` to install it.")


class SlackTools(Toolkit):
    # ── Class methods ────────────────────────────────────────────────

    @classmethod
    def _build_instructions(cls, tool_names: list[str]) -> str:
        """Build instructions based on which tools are actually enabled.

        Only references tools the LLM can call — never mentions disabled tools.
        """
        enabled = set(tool_names)
        sections: list[str] = []

        if "search_workspace" in enabled:
            sections.append(
                "**search_workspace** — semantic and keyword search across the workspace.\n"
                "When to use: finding discussions about a topic, catching up, summarizing activity.\n"
                "Returns: messages with channel, author, timestamp, and surrounding context."
            )

        if "get_channel_history" in enabled:
            text = (
                "**get_channel_history** — recent top-level messages from a specific channel.\n"
                "When to use: reading the latest activity in a known channel.\n"
                "Note: returns only top-level messages, not thread replies."
            )
            # Only reference get_thread if the LLM can actually call it
            if "get_thread" in enabled:
                text += "\nLook for thread_ts and reply_count, then use get_thread to expand."
            text += "\nRequires: bot must be a member of the channel."
            sections.append(text)

        if "get_thread" in enabled:
            text = (
                "**get_thread** — full thread replies given a channel and thread timestamp.\n"
                "When to use: expanding a message with replies into its full discussion."
            )
            # Reference chaining sources that are actually available
            sources = [t for t in ("get_channel_history", "search_workspace") if t in enabled]
            if sources:
                text += f"\nChain after {' or '.join(sources)} for complete context."
            sections.append(text)

        if "get_channel_info" in enabled:
            sections.append(
                "**get_channel_info** — channel metadata (topic, purpose, member count).\n"
                "When to use: understanding what a channel is about."
            )

        if "search_messages" in enabled:
            text = "**search_messages** — legacy search API. Requires a user token."
            if "search_workspace" in enabled:
                text += "\nWhen to use: only when search_workspace is unavailable."
            sections.append(text)

        # Messaging guidance — critical for thread-aware responses
        if "send_message" in enabled and "send_message_thread" in enabled:
            sections.append(
                "**send_message** vs **send_message_thread** — choosing correctly:\n"
                "- If you have a `Slack thread_ts` in your context/dependencies, "
                "ALWAYS use send_message_thread with that thread_ts. "
                "Never use send_message when replying inside a thread.\n"
                "- Only use send_message for new top-level channel messages."
            )
        elif "send_message_thread" in enabled:
            sections.append(
                "**send_message_thread** — reply inside a thread.\n"
                "When you have a `Slack thread_ts` in your context/dependencies, use it."
            )

        # Only inject guidance when there are multiple tools to choose between
        if len(sections) < 2:
            return ""

        result = "## Slack Tool Selection\n\n" + "\n\n".join(sections)

        # Routing guidance
        routing: list[str] = []
        if "search_workspace" in enabled and "get_channel_history" in enabled:
            routing.append("- Topic search, catch-up, cross-channel → search_workspace")
            routing.append("- Latest messages in a specific channel → get_channel_history")
        if "get_thread" in enabled:
            routing.append("- Deep-dive into a message → get_thread with channel_id and ts")
            routing.append("- Always expand threads with high reply_count before summarizing")
        if "search_messages" in enabled and "search_workspace" in enabled:
            routing.append("- Fallback (user-token only) → search_messages")
        if "send_message" in enabled and "send_message_thread" in enabled:
            routing.append("- Replying in a thread → send_message_thread (use Slack thread_ts from context)")
            routing.append("- New top-level channel message → send_message")

        if routing:
            result += "\n\n## When to use which\n" + "\n".join(routing)

        return result

    # ── Init ─────────────────────────────────────────────────────────

    def __init__(
        self,
        token: Optional[str] = None,
        markdown: bool = True,
        output_directory: Optional[str] = None,
        enable_send_message: bool = True,
        enable_send_message_thread: bool = True,
        enable_list_channels: bool = True,
        enable_get_channel_history: bool = True,
        enable_upload_file: bool = True,
        enable_download_file: bool = True,
        enable_search_messages: bool = False,
        enable_search_workspace: bool = False,
        enable_get_thread: bool = False,
        enable_list_users: bool = False,
        enable_get_user_info: bool = False,
        enable_get_channel_info: bool = False,
        all: bool = False,
        ssl: Optional[SSLContext] = None,
        max_file_size: int = 1_073_741_824,  # 1GB
        thread_message_limit: int = 20,
        **kwargs,
    ):
        """
        Initialize the SlackTools class.

        Args:
            token (str): The Slack API token. Defaults to the SLACK_TOKEN environment variable.
            markdown (bool): Whether to enable Slack markdown formatting. Defaults to True.
            output_directory (str): Optional path to save downloaded/uploaded files locally.
            enable_send_message (bool): Whether to enable the send_message tool. Defaults to True.
            enable_send_message_thread (bool): Whether to enable the send_message_thread tool. Defaults to True.
            enable_list_channels (bool): Whether to enable the list_channels tool. Defaults to True.
            enable_get_channel_history (bool): Whether to enable the get_channel_history tool. Defaults to True.
            enable_upload_file (bool): Whether to enable the upload_file tool. Defaults to True.
            enable_download_file (bool): Whether to enable the download_file tool. Defaults to True.
            enable_search_messages (bool): Whether to enable the search_messages tool (legacy API). Defaults to False.
            enable_search_workspace (bool): Whether to enable the search_workspace tool (assistant.search.context API).
                Requires search:read.public, search:read.files, and search:read.users bot scopes.
                The action_token is read from run_context.metadata at call time. Defaults to False.
            enable_get_thread (bool): Whether to enable the get_thread tool. Defaults to False.
            enable_list_users (bool): Whether to enable the list_users tool. Defaults to False.
            enable_get_user_info (bool): Whether to enable the get_user_info tool. Defaults to False.
            enable_get_channel_info (bool): Whether to enable the get_channel_info tool. Defaults to False.
            all (bool): Whether to enable all tools. Defaults to False.
            ssl (SSLContext): Optional SSL context for the Slack WebClient. Defaults to None.
            max_file_size (int): Maximum file size in bytes for uploads and downloads. Defaults to 1GB.
            thread_message_limit (int): Maximum number of messages to fetch in get_thread. Defaults to 20.
        """
        _token = token or getenv("SLACK_TOKEN")
        if not _token:
            raise ValueError("SLACK_TOKEN is not set")
        self.token: str = _token
        self.client = WebClient(token=self.token, ssl=ssl)
        self.markdown = markdown
        self.max_file_size = max_file_size
        self.thread_message_limit = thread_message_limit
        self.output_directory = Path(output_directory) if output_directory else None

        if self.output_directory:
            self.output_directory.mkdir(parents=True, exist_ok=True)
            log_debug(f"Uploaded files will be saved to: {self.output_directory}")

        tools: List[Any] = []
        if enable_send_message or all:
            tools.append(self.send_message)
        if enable_send_message_thread or all:
            tools.append(self.send_message_thread)
        if enable_list_channels or all:
            tools.append(self.list_channels)
        if enable_get_channel_history or all:
            tools.append(self.get_channel_history)
        if enable_upload_file or all:
            tools.append(self.upload_file)
        if enable_download_file or all:
            tools.append(self.download_file)
        if enable_search_messages or all:
            tools.append(self.search_messages)
        if enable_search_workspace or all:
            tools.append(self.search_workspace)
        if enable_get_thread or all:
            tools.append(self.get_thread)
        if enable_list_users or all:
            tools.append(self.list_users)
        if enable_get_user_info or all:
            tools.append(self.get_user_info)
        if enable_get_channel_info or all:
            tools.append(self.get_channel_info)

        # Build tool instructions dynamically based on enabled tools
        if kwargs.get("instructions") is None:
            tool_names = [t.__name__ for t in tools]
            built = self._build_instructions(tool_names)
            if built:
                kwargs["instructions"] = built
                kwargs.setdefault("add_instructions", True)

        super().__init__(name="slack", tools=tools, **kwargs)

    # ── Private helpers ──────────────────────────────────────────────

    def _resolve_user_names(self, user_ids: List[str]) -> Dict[str, str]:
        """Resolve a list of Slack user IDs to display names.

        Makes one users.info call per unique ID. Typical channels have <10 unique
        participants so this stays well within Slack's Tier 4 rate limit (~100 req/min).
        Falls back to the raw ID on failure.
        """
        names: Dict[str, str] = {}
        for uid in user_ids:
            try:
                resp = self.client.users_info(user=uid)
                profile = resp.get("user", {}).get("profile", {})
                # Prefer display_name (chosen by user), fall back to real_name
                names[uid] = profile.get("display_name") or profile.get("real_name") or uid
            except SlackApiError:
                names[uid] = uid
        return names

    def _build_message_entry(self, msg: Dict[str, Any], user_names: Dict[str, str]) -> Dict[str, Any]:
        user_id = msg.get("user", "")
        user_label = msg.get("username") or user_names.get(user_id, user_id) or "unknown"
        entry: Dict[str, Any] = {
            "text": msg.get("text", ""),
            "user": user_label,
            "ts": msg.get("ts", ""),
        }
        if msg.get("attachments"):
            entry["attachments"] = msg["attachments"]
        return entry

    def _save_file_to_disk(self, content: bytes, filename: str) -> Optional[str]:
        """Save file to disk if output_directory is set. Return file path or None."""
        if not self.output_directory:
            return None

        file_path = self.output_directory / Path(filename).name
        try:
            file_path.write_bytes(content)
            log_debug(f"File saved to: {file_path}")
            return str(file_path)
        except OSError as e:
            log_warning(f"Failed to save file locally: {str(e)}")
            return None

    def _format_search_results(self, results: Dict[str, Any], include_context: bool) -> Dict[str, Any]:
        """Shape raw assistant.search.context results for LLM consumption.

        Extracts only fields the LLM needs to synthesize answers and offer
        drill-downs (via ts + channel_id -> get_thread). Drops API noise like
        team_id, blocks, and redundant uploader fields.
        """
        output: Dict[str, Any] = {}
        result_count = 0

        # Messages: core fields + optional surrounding conversation context
        messages = results.get("messages", [])
        if messages:
            output["messages"] = [self._format_message(m, include_context) for m in messages]
            result_count += len(output["messages"])

        # Files: title and type are enough for relevance; permalink for access
        files = results.get("files", [])
        if files:
            output["files"] = [
                {
                    "title": f.get("title", ""),
                    "file_type": f.get("file_type", ""),
                    "author": f.get("author_name", ""),
                    "permalink": f.get("permalink", ""),
                }
                for f in files
            ]
            result_count += len(output["files"])

        # Channels: topic + purpose help LLM judge relevance
        channels = results.get("channels", [])
        if channels:
            output["channels"] = [
                {
                    "name": ch.get("name", ""),
                    "topic": ch.get("topic", ""),
                    "purpose": ch.get("purpose", ""),
                    "permalink": ch.get("permalink", ""),
                }
                for ch in channels
            ]
            result_count += len(output["channels"])

        # Users: name + title for people discovery ("who works on X?")
        users = results.get("users", [])
        if users:
            output["users"] = [
                {
                    "user_id": u.get("user_id", ""),
                    "full_name": u.get("full_name", ""),
                    "title": u.get("title", ""),
                    "email": u.get("email", ""),
                    "permalink": u.get("permalink", ""),
                }
                for u in users
            ]
            result_count += len(output["users"])

        output["result_count"] = result_count
        return output

    @staticmethod
    def _format_message(msg: Dict[str, Any], include_context: bool) -> Dict[str, Any]:
        """Extract LLM-relevant fields from a single search result message.

        Field renames: author_name -> author, message_ts -> ts, is_author_bot -> is_bot.
        Keeps channel_id + ts so LLM can chain into get_thread.
        """
        entry: Dict[str, Any] = {
            "content": msg.get("content", ""),
            "author": msg.get("author_name", ""),
            "author_user_id": msg.get("author_user_id", ""),
            "is_bot": msg.get("is_author_bot", False),
            "channel_id": msg.get("channel_id", ""),
            "channel_name": msg.get("channel_name", ""),
            "ts": msg.get("message_ts", ""),
            "permalink": msg.get("permalink", ""),
        }

        # Surrounding messages give the LLM conversation context without
        # needing a separate get_thread call; omit when empty to save tokens
        if include_context:
            ctx = msg.get("context_messages", {})
            before = [{"text": cm.get("text", ""), "user_id": cm.get("user_id", "")} for cm in ctx.get("before", [])]
            after = [{"text": cm.get("text", ""), "user_id": cm.get("user_id", "")} for cm in ctx.get("after", [])]
            if before:
                entry["context_before"] = before
            if after:
                entry["context_after"] = after

        return entry

    # ── Public tool methods ──────────────────────────────────────────

    def send_message(self, channel: str, text: str) -> str:
        """Send a message to a Slack channel.

        Args:
            channel (str): The channel ID or name to send the message to.
            text (str): The text of the message to send. Supports Slack mrkdwn formatting.

        Returns:
            str: A JSON string containing the response from the Slack API.
        """
        try:
            response = self.client.chat_postMessage(channel=channel, text=text, mrkdwn=self.markdown)
            return json.dumps(response.data)
        except SlackApiError as e:
            logger.exception("Error sending message")
            return json.dumps({"error": str(e)})

    def send_message_thread(self, channel: str, text: str, thread_ts: str) -> str:
        """Reply to a message thread in a Slack channel.

        Args:
            channel (str): The channel ID or name where the thread exists.
            text (str): The text of the reply. Supports Slack mrkdwn formatting.
            thread_ts (str): The timestamp of the parent message to reply to.

        Returns:
            str: A JSON string containing the response from the Slack API.
        """
        try:
            response = self.client.chat_postMessage(
                channel=channel, text=text, thread_ts=thread_ts, mrkdwn=self.markdown
            )
            return json.dumps(response.data)
        except SlackApiError as e:
            logger.exception("Error sending message")
            return json.dumps({"error": str(e)})

    def list_channels(self) -> str:
        """List all channels in the Slack workspace.

        Returns:
            str: A JSON string containing a list of channels with their IDs and names.
        """
        try:
            response = self.client.conversations_list()
            channels = [{"id": channel["id"], "name": channel["name"]} for channel in response["channels"]]
            return json.dumps(channels)
        except SlackApiError as e:
            logger.exception("Error listing channels")
            return json.dumps({"error": str(e)})

    def get_channel_history(self, channel: str, limit: int = 100) -> str:
        """Get the message history of a Slack channel.

        Args:
            channel (str): The channel ID to fetch history from.
            limit (int): The maximum number of messages to fetch. Defaults to 100.

        Returns:
            str: A JSON string containing the channel's message history.
        """
        try:
            response = self.client.conversations_history(channel=channel, limit=limit)

            raw_messages = response.get("messages", [])
            human_msgs = [m for m in raw_messages if m.get("subtype") != "bot_message" and m.get("user")]
            user_names = self._resolve_user_names(list({m["user"] for m in human_msgs}))

            messages: List[Dict[str, Any]] = []
            for msg in raw_messages:
                entry = self._build_message_entry(msg, user_names)
                # Thread metadata lets the agent discover and expand threads
                thread_ts = msg.get("thread_ts")
                if thread_ts:
                    entry["thread_ts"] = thread_ts
                    entry["reply_count"] = msg.get("reply_count", 0)
                messages.append(entry)
            return json.dumps(messages)
        except SlackApiError as e:
            logger.exception("Error getting channel history")
            return json.dumps({"error": str(e)})

    def upload_file(
        self,
        channel: str,
        content: Union[str, bytes],
        filename: str,
        title: Optional[str] = None,
        initial_comment: Optional[str] = None,
        thread_ts: Optional[str] = None,
    ) -> str:
        """Upload a file to a Slack channel.

        Args:
            channel (str): The channel ID to upload the file to.
            content (str or bytes): The file content. Text strings will be encoded to bytes.
            filename (str): The name for the uploaded file.
            title (str): An optional title for the file.
            initial_comment (str): An optional message to include with the file upload.
            thread_ts (str): The timestamp of a thread to upload the file into. Optional.

        Returns:
            str: A JSON string containing the response from the Slack API.
        """
        try:
            if isinstance(content, str):
                content_bytes = content.encode("utf-8")
            else:
                content_bytes = content

            if len(content_bytes) > self.max_file_size:
                limit_mb = self.max_file_size / (1024 * 1024)
                actual_mb = len(content_bytes) / (1024 * 1024)
                return json.dumps(
                    {"error": f"File {filename} ({actual_mb:.1f}MB) exceeds {limit_mb:.0f}MB upload limit"}
                )

            file_path = self._save_file_to_disk(content_bytes, filename)

            response = self.client.files_upload_v2(
                channel=channel,
                content=content_bytes,
                filename=filename,
                title=title,
                initial_comment=initial_comment,
                thread_ts=thread_ts,
            )

            # Copy to avoid mutating the SDK's response object
            result = dict(response.data)
            if file_path:
                result["local_path"] = file_path

            return json.dumps(result)
        except SlackApiError as e:
            logger.exception("Error uploading file")
            return json.dumps({"error": str(e)})

    def download_file(self, file_id: str, dest_path: Optional[str] = None) -> str:
        """Download a file from Slack by its file ID.

        Args:
            file_id (str): The Slack file ID to download.
            dest_path (str): An optional destination path to save the file to. Must be within the configured output_directory.

        Returns:
            str: A JSON string containing the file metadata and either the local file path or base64-encoded content.
        """
        try:
            response = self.client.files_info(file=file_id)
            file_info = response["file"]

            url_private = file_info.get("url_private")
            if not url_private:
                return json.dumps({"error": "File URL not available"})

            filename = file_info.get("name", f"file_{file_id}")
            file_size = file_info.get("size", 0)

            if file_size > self.max_file_size:
                limit_mb = self.max_file_size / (1024 * 1024)
                actual_mb = file_size / (1024 * 1024)
                return json.dumps(
                    {"error": f"File {filename} ({actual_mb:.1f}MB) exceeds {limit_mb:.0f}MB download limit"}
                )

            headers = {"Authorization": f"Bearer {self.token}"}
            download_response = httpx.get(url_private, headers=headers, timeout=30)
            download_response.raise_for_status()
            content = download_response.content

            save_path: Optional[Path] = None
            if dest_path:
                save_path = Path(dest_path).resolve()
                if self.output_directory and not save_path.is_relative_to(self.output_directory.resolve()):
                    return json.dumps({"error": "dest_path must be within the configured output_directory"})
            elif self.output_directory:
                save_path = self.output_directory / Path(filename).name

            result: Dict[str, Any] = {
                "file_id": file_id,
                "filename": filename,
                "size": file_size,
            }

            if save_path:
                try:
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    save_path.write_bytes(content)
                    log_debug(f"File downloaded to: {save_path}")
                    result["path"] = str(save_path)
                except OSError as e:
                    log_warning(f"Failed to save file locally: {str(e)}")
                    result["content_base64"] = base64.b64encode(content).decode("utf-8")
            else:
                result["content_base64"] = base64.b64encode(content).decode("utf-8")

            return json.dumps(result)

        except SlackApiError as e:
            logger.exception("Error downloading file")
            return json.dumps({"error": str(e)})
        except httpx.HTTPError as e:
            logger.exception("Error downloading file content")
            return json.dumps({"error": f"HTTP error: {str(e)}"})

    def download_file_bytes(self, file_id: str) -> Optional[bytes]:
        """Download file content as raw bytes. For internal use by interfaces."""
        try:
            response = self.client.files_info(file=file_id)
            file_info = response["file"]

            file_size = file_info.get("size", 0)
            if file_size > self.max_file_size:
                limit_mb = self.max_file_size / (1024 * 1024)
                actual_mb = file_size / (1024 * 1024)
                filename = file_info.get("name", file_id)
                log_error(f"File {filename} ({actual_mb:.1f}MB) exceeds {limit_mb:.0f}MB download limit")
                return None

            url_private = file_info.get("url_private")
            if not url_private:
                return None

            headers = {"Authorization": f"Bearer {self.token}"}
            download_response = httpx.get(url_private, headers=headers, timeout=30)
            download_response.raise_for_status()
            return download_response.content

        except (SlackApiError, httpx.HTTPError):
            logger.exception("Error downloading file bytes")
            return None

    def search_messages(self, query: str, limit: int = 20) -> str:
        """Search messages across the Slack workspace.

        Args:
            query (str): The search query. Supports modifiers like from:@user, in:#channel, has:link, before:date, after:date.
            limit (int): The maximum number of results to return. Defaults to 20, max 100.

        Returns:
            str: A JSON string containing the count and list of matching messages with text, user, channel, timestamp, and permalink.
        """
        try:
            response = self.client.search_messages(query=query, count=min(limit, 100))
            matches = response.get("messages", {}).get("matches", [])
            messages = [
                {
                    "text": msg.get("text", ""),
                    "user": msg.get("user", "unknown"),
                    "channel_id": msg.get("channel", {}).get("id", ""),
                    "channel_name": msg.get("channel", {}).get("name", ""),
                    "ts": msg.get("ts", ""),
                    "permalink": msg.get("permalink", ""),
                }
                for msg in matches
            ]
            return json.dumps({"count": len(messages), "messages": messages})
        except SlackApiError as e:
            logger.exception("Error searching messages")
            return json.dumps({"error": str(e)})

    def search_workspace(
        self,
        run_context: RunContext,
        query: str,
        content_types: Optional[List[Literal["messages", "files", "channels", "users"]]] = None,
        channel_types: Optional[List[Literal["public_channel", "private_channel", "mpim", "im"]]] = None,
        limit: int = 10,
        include_context_messages: bool = True,
    ) -> str:
        """Search messages, files, and channels across the Slack workspace.

        Args:
            run_context (RunContext): Injected by the framework.
            query (str): Natural language question or keywords. Supports filters:
                in:<#channel>, from:<@user>, has:link, before:YYYY-MM-DD, after:YYYY-MM-DD.
            content_types (list): What to search for. Defaults to ["messages"].
            channel_types (list): Channel scopes to include. Defaults to ["public_channel"].
            limit (int): Results per content type, max 20.
            include_context_messages (bool): Include surrounding messages for each result.

        Returns:
            str: JSON with search results grouped by content type.
        """
        # Injected by the Slack interface via run_context.metadata; scopes results
        # to what the requesting user can see
        action_token = (run_context.metadata or {}).get("action_token") if run_context else None
        if not action_token:
            return json.dumps(
                {"error": "No action_token available. This tool only works when invoked through the Slack interface."}
            )

        try:
            response = self.client.api_call(
                "assistant.search.context",
                params={
                    "query": query,
                    "action_token": action_token,
                    "content_types": ",".join(content_types or ["messages"]),
                    "channel_types": ",".join(channel_types or ["public_channel"]),
                    "limit": min(limit, 20),
                    "include_context_messages": include_context_messages,
                },
            )

            if not response.get("ok"):
                error = response.get("error", "unknown_error")
                log_error(f"assistant.search.context failed: {error}")
                return json.dumps({"error": error})

            return json.dumps(self._format_search_results(response.get("results", {}), include_context_messages))
        except SlackApiError as e:
            logger.exception("Error in search_workspace")
            return json.dumps({"error": str(e)})

    def get_thread(self, channel: str, thread_ts: str, limit: int = 20) -> str:
        """Get all messages in a thread by the parent message's timestamp.

        Args:
            channel (str): The channel ID where the thread exists.
            thread_ts (str): The timestamp of the parent message.
            limit (int): The maximum number of replies to fetch. Defaults to 20. Capped by thread_message_limit.

        Returns:
            str: A JSON string containing the thread timestamp, reply count, and list of messages.
        """
        try:
            response = self.client.conversations_replies(
                channel=channel,
                ts=thread_ts,
                limit=min(limit, self.thread_message_limit),
            )
            raw_messages = response.get("messages", [])
            human_msgs = [m for m in raw_messages if m.get("subtype") != "bot_message" and m.get("user")]
            user_names = self._resolve_user_names(list({m["user"] for m in human_msgs}))

            messages: List[Dict[str, Any]] = []
            for msg in raw_messages:
                messages.append(self._build_message_entry(msg, user_names))
            return json.dumps(
                {
                    "thread_ts": thread_ts,
                    "reply_count": len(messages) - 1,
                    "messages": messages,
                }
            )
        except SlackApiError as e:
            logger.exception("Error getting thread")
            return json.dumps({"error": str(e)})

    def list_users(self, limit: int = 100) -> str:
        """List all users in the Slack workspace.

        Args:
            limit (int): The maximum number of users to fetch. Defaults to 100.

        Returns:
            str: A JSON string containing the count and list of users with their ID, name, real name, title, and bot status.
        """
        try:
            response = self.client.users_list(limit=limit)
            users = [
                {
                    "id": member.get("id", ""),
                    "name": member.get("name", ""),
                    "real_name": member.get("profile", {}).get("real_name", ""),
                    "title": member.get("profile", {}).get("title", ""),
                    "is_bot": member.get("is_bot", False),
                }
                for member in response.get("members", [])
                if not member.get("deleted", False)
            ]
            return json.dumps({"count": len(users), "users": users})
        except SlackApiError as e:
            logger.exception("Error listing users")
            return json.dumps({"error": str(e)})

    def get_user_info(self, user_id: str) -> str:
        """Get detailed information about a Slack user by their user ID.

        Args:
            user_id (str): The Slack user ID to look up.

        Returns:
            str: A JSON string containing the user's ID, name, real name, email, title, timezone, and bot status.
        """
        try:
            response = self.client.users_info(user=user_id)
            user = response.get("user", {})
            profile = user.get("profile", {})
            return json.dumps(
                {
                    "id": user.get("id", ""),
                    "name": user.get("name", ""),
                    "real_name": profile.get("real_name", ""),
                    "email": profile.get("email", ""),
                    "title": profile.get("title", ""),
                    "tz": user.get("tz", ""),
                    "is_bot": user.get("is_bot", False),
                }
            )
        except SlackApiError as e:
            logger.exception("Error getting user info")
            return json.dumps({"error": str(e)})

    def get_channel_info(self, channel: str) -> str:
        """Get detailed information about a Slack channel by its ID.

        Args:
            channel (str): The Slack channel ID to look up.

        Returns:
            str: A JSON string containing the channel's name, topic, purpose, member count, creation date, and visibility.
        """
        try:
            response = self.client.conversations_info(channel=channel, include_num_members=True)
            ch = response.get("channel", {})
            return json.dumps(
                {
                    "id": ch.get("id", ""),
                    "name": ch.get("name", ""),
                    "topic": ch.get("topic", {}).get("value", ""),
                    "purpose": ch.get("purpose", {}).get("value", ""),
                    "num_members": ch.get("num_members", 0),
                    "is_private": ch.get("is_private", False),
                    "is_archived": ch.get("is_archived", False),
                    "created": ch.get("created", 0),
                    "creator": ch.get("creator", ""),
                }
            )
        except SlackApiError as e:
            logger.exception("Error getting channel info")
            return json.dumps({"error": str(e)})
