import base64
import json
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import requests

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError:
    raise ImportError("Slack tools require the `slack_sdk` package. Run `pip install slack-sdk` to install it.")


class SlackTools(Toolkit):
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
        enable_get_thread: bool = False,
        enable_list_users: bool = False,
        enable_get_user_info: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """
        Initialize the SlackTools class.
        Args:
            token: The Slack API token. Defaults to the SLACK_TOKEN environment variable.
            markdown: Whether to enable Slack markdown formatting. Defaults to True.
            output_directory: Optional directory to save copies of uploaded/downloaded files.
            enable_send_message: Whether to enable the send_message tool. Defaults to True.
            enable_send_message_thread: Whether to enable the send_message_thread tool. Defaults to True.
            enable_list_channels: Whether to enable the list_channels tool. Defaults to True.
            enable_get_channel_history: Whether to enable the get_channel_history tool. Defaults to True.
            enable_upload_file: Whether to enable the upload_file tool. Defaults to True.
            enable_download_file: Whether to enable the download_file tool. Defaults to True.
            enable_search_messages: Whether to enable the search_messages tool. Defaults to False.
            enable_get_thread: Whether to enable the get_thread tool. Defaults to False.
            enable_list_users: Whether to enable the list_users tool. Defaults to False.
            enable_get_user_info: Whether to enable the get_user_info tool. Defaults to False.
            all: Whether to enable all tools. Defaults to False.
        """
        self.token: Optional[str] = token or getenv("SLACK_TOKEN")
        if self.token is None or self.token == "":
            raise ValueError("SLACK_TOKEN is not set")
        self.client = WebClient(token=self.token)
        self.markdown = markdown
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
        if enable_get_thread or all:
            tools.append(self.get_thread)
        if enable_list_users or all:
            tools.append(self.list_users)
        if enable_get_user_info or all:
            tools.append(self.get_user_info)

        super().__init__(name="slack", tools=tools, **kwargs)

    def send_message(self, channel: str, text: str) -> str:
        """
        Send a message to a Slack channel.

        Use Slack mrkdwn formatting in text: *bold*, _italic_, `code`, <url|text>.

        Args:
            channel (str): The channel ID or name to send the message to.
            text (str): The text of the message (supports Slack mrkdwn formatting).

        Returns:
            str: A JSON string containing the response from the Slack API.
        """
        try:
            response = self.client.chat_postMessage(channel=channel, text=text, mrkdwn=self.markdown)
            return json.dumps(response.data)
        except SlackApiError as e:
            logger.error(f"Error sending message: {e}")
            return json.dumps({"error": str(e)})

    def send_message_thread(self, channel: str, text: str, thread_ts: str) -> str:
        """
        Send a message to a Slack channel thread.

        Use Slack mrkdwn formatting in text: *bold*, _italic_, `code`, <url|text>.

        Args:
            channel (str): The channel ID or name to send the message to.
            text (str): The text of the message (supports Slack mrkdwn formatting).
            thread_ts (str): The thread timestamp to reply to.

        Returns:
            str: A JSON string containing the response from the Slack API.
        """
        try:
            response = self.client.chat_postMessage(
                channel=channel, text=text, thread_ts=thread_ts, mrkdwn=self.markdown
            )
            return json.dumps(response.data)
        except SlackApiError as e:
            logger.error(f"Error sending message: {e}")
            return json.dumps({"error": str(e)})

    def list_channels(self) -> str:
        """
        List all channels in the Slack workspace.

        Returns:
            str: A JSON string containing the list of channels.
        """
        try:
            response = self.client.conversations_list()
            channels = [{"id": channel["id"], "name": channel["name"]} for channel in response["channels"]]
            return json.dumps(channels)
        except SlackApiError as e:
            logger.error(f"Error listing channels: {e}")
            return json.dumps({"error": str(e)})

    def get_channel_history(self, channel: str, limit: int = 100) -> str:
        """
        Get the message history of a Slack channel.

        Args:
            channel (str): The channel ID to fetch history from.
            limit (int): The maximum number of messages to fetch. Defaults to 100.

        Returns:
            str: A JSON string containing the channel's message history.
        """
        try:
            response = self.client.conversations_history(channel=channel, limit=limit)
            messages: List[Dict[str, Any]] = [  # type: ignore
                {
                    "text": msg.get("text", ""),
                    "user": "webhook" if msg.get("subtype") == "bot_message" else msg.get("user", "unknown"),
                    "ts": msg.get("ts", ""),
                    "sub_type": msg.get("subtype", "unknown"),
                    "attachments": msg.get("attachments", []) if msg.get("subtype") == "bot_message" else "n/a",
                }
                for msg in response.get("messages", [])
            ]
            return json.dumps(messages)
        except SlackApiError as e:
            logger.error(f"Error getting channel history: {e}")
            return json.dumps({"error": str(e)})

    def _save_file_to_disk(self, content: bytes, filename: str) -> Optional[str]:
        """Save file to disk if output_directory is set. Return file path or None."""
        if not self.output_directory:
            return None

        file_path = self.output_directory / filename
        try:
            file_path.write_bytes(content)
            log_debug(f"File saved to: {file_path}")
            return str(file_path)
        except OSError as e:
            logger.warning(f"Failed to save file locally: {e}")
            return None

    def upload_file(
        self,
        channel: str,
        content: Union[str, bytes],
        filename: str,
        title: Optional[str] = None,
        initial_comment: Optional[str] = None,
        thread_ts: Optional[str] = None,
    ) -> str:
        """
        Upload a file to a Slack channel.

        Args:
            channel (str): The channel ID or name to upload the file to.
            content (str | bytes): The file content as text or bytes. Use bytes for
                binary files (e.g., PDFs) or when integrating with FileGenerationTools.
            filename (str): The name for the file (e.g., "report.csv").
            title (str, optional): The title to display for the file in Slack.
            initial_comment (str, optional): A message to post with the file.
            thread_ts (str, optional): The thread timestamp to upload the file as a reply.

        Returns:
            str: A JSON string containing the response from the Slack API.
        """
        try:
            # Handle both string and bytes content
            if isinstance(content, str):
                content_bytes = content.encode("utf-8")
            else:
                content_bytes = content

            # Save to disk if output_directory is set
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
            logger.error(f"Error uploading file: {e}")
            return json.dumps({"error": str(e)})

    def download_file(self, file_id: str, dest_path: Optional[str] = None) -> str:
        """
        Download a file from Slack.

        Args:
            file_id (str): The Slack file ID (e.g., "F12345").
            dest_path (str, optional): Destination path for the file. If not provided,
                uses output_directory. If neither is set, returns base64-encoded content.

        Returns:
            str: A JSON string containing file metadata and either the local path
                 or base64-encoded content.
        """
        try:
            # Get file info from Slack API
            response = self.client.files_info(file=file_id)
            file_info = response["file"]

            url_private = file_info.get("url_private")
            if not url_private:
                return json.dumps({"error": "File URL not available"})

            filename = file_info.get("name", f"file_{file_id}")
            file_size = file_info.get("size", 0)

            # Download file content
            headers = {"Authorization": f"Bearer {self.token}"}
            download_response = requests.get(url_private, headers=headers, timeout=30)
            download_response.raise_for_status()
            content = download_response.content

            # Determine where to save
            save_path: Optional[Path] = None
            if dest_path:
                save_path = Path(dest_path)
            elif self.output_directory:
                save_path = self.output_directory / filename

            result: Dict[str, Any] = {
                "file_id": file_id,
                "filename": filename,
                "size": file_size,
            }

            # Save to disk or return as base64
            if save_path:
                try:
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    save_path.write_bytes(content)
                    log_debug(f"File downloaded to: {save_path}")
                    result["path"] = str(save_path)
                except OSError as e:
                    logger.warning(f"Failed to save file locally: {e}")
                    # Fall through to return base64
                    result["content_base64"] = base64.b64encode(content).decode("utf-8")
            else:
                result["content_base64"] = base64.b64encode(content).decode("utf-8")

            return json.dumps(result)

        except SlackApiError as e:
            logger.error(f"Error downloading file: {e}")
            return json.dumps({"error": str(e)})
        except requests.RequestException as e:
            logger.error(f"Error downloading file content: {e}")
            return json.dumps({"error": f"HTTP error: {str(e)}"})

    def search_messages(self, query: str, limit: int = 20) -> str:
        """
        Search for messages across the workspace.

        Use Slack search modifiers in query:
        - from:@username - Messages from a specific user
        - in:#channel - Messages in a specific channel
        - has:link - Messages containing links
        - before:2024-01-01 / after:2024-01-01 - Date filters

        Args:
            query (str): Search query with optional Slack modifiers.
            limit (int): Maximum results to return (max 100). Defaults to 20.

        Returns:
            str: JSON string with matching messages.
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
            logger.error(f"Error searching messages: {e}")
            return json.dumps({"error": str(e)})

    def get_thread(self, channel: str, thread_ts: str, limit: int = 100) -> str:
        """
        Get all messages in a thread.

        Args:
            channel (str): Channel ID containing the thread.
            thread_ts (str): Timestamp of the parent message.
            limit (int): Max replies to fetch (max 200). Defaults to 100.

        Returns:
            str: JSON string with thread messages (parent first, then replies).
        """
        try:
            response = self.client.conversations_replies(
                channel=channel,
                ts=thread_ts,
                limit=min(limit, 200),
            )
            messages = [
                {
                    "text": msg.get("text", ""),
                    "user": msg.get("user", "unknown"),
                    "ts": msg.get("ts", ""),
                }
                for msg in response.get("messages", [])
            ]
            return json.dumps(
                {
                    "thread_ts": thread_ts,
                    "reply_count": len(messages) - 1,
                    "messages": messages,
                }
            )
        except SlackApiError as e:
            logger.error(f"Error getting thread: {e}")
            return json.dumps({"error": str(e)})

    def list_users(self, limit: int = 100) -> str:
        """
        List all users in the workspace.

        Use this to find experts by name or role, or to resolve user IDs to names.

        Args:
            limit (int): Maximum users to return. Defaults to 100.

        Returns:
            str: JSON string with user list.
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
            logger.error(f"Error listing users: {e}")
            return json.dumps({"error": str(e)})

    def get_user_info(self, user_id: str) -> str:
        """
        Get information about a Slack user.

        Args:
            user_id (str): Slack user ID (e.g., "U12345678").

        Returns:
            str: JSON string with user info including name, email, title, timezone.
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
            logger.error(f"Error getting user info: {e}")
            return json.dumps({"error": str(e)})
