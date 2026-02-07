import base64
import json
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import httpx

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
            token (str): The Slack API token. Defaults to the SLACK_TOKEN environment variable.
            markdown (bool): Whether to enable Slack markdown formatting. Defaults to True.
            output_directory (str): Optional path to save downloaded/uploaded files locally.
            enable_send_message (bool): Whether to enable the send_message tool. Defaults to True.
            enable_send_message_thread (bool): Whether to enable the send_message_thread tool. Defaults to True.
            enable_list_channels (bool): Whether to enable the list_channels tool. Defaults to True.
            enable_get_channel_history (bool): Whether to enable the get_channel_history tool. Defaults to True.
            enable_upload_file (bool): Whether to enable the upload_file tool. Defaults to True.
            enable_download_file (bool): Whether to enable the download_file tool. Defaults to True.
            enable_search_messages (bool): Whether to enable the search_messages tool. Defaults to False.
            enable_get_thread (bool): Whether to enable the get_thread tool. Defaults to False.
            enable_list_users (bool): Whether to enable the list_users tool. Defaults to False.
            enable_get_user_info (bool): Whether to enable the get_user_info tool. Defaults to False.
            all (bool): Whether to enable all tools. Defaults to False.
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
            logger.error(f"Error sending message: {e}")
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
            logger.error(f"Error sending message: {e}")
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
            logger.error(f"Error listing channels: {e}")
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

        file_path = self.output_directory / Path(filename).name
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
        """Download a file from Slack by its file ID.

        Args:
            file_id (str): The Slack file ID to download.
            dest_path (str): An optional destination path to save the file to. Must be within the configured output_directory.

        Returns:
            str: A JSON string containing the file metadata and either the local file path or base64-encoded content.
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
            download_response = httpx.get(url_private, headers=headers, timeout=30)
            download_response.raise_for_status()
            content = download_response.content

            # Determine where to save
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
        except httpx.HTTPError as e:
            logger.error(f"Error downloading file content: {e}")
            return json.dumps({"error": f"HTTP error: {str(e)}"})

    def download_file_bytes(self, file_id: str) -> Optional[bytes]:
        """Download file content as raw bytes. For internal use by interfaces."""
        try:
            response = self.client.files_info(file=file_id)
            file_info = response["file"]

            url_private = file_info.get("url_private")
            if not url_private:
                return None

            headers = {"Authorization": f"Bearer {self.token}"}
            download_response = httpx.get(url_private, headers=headers, timeout=30)
            download_response.raise_for_status()
            return download_response.content

        except (SlackApiError, httpx.HTTPError) as e:
            logger.error(f"Error downloading file bytes: {e}")
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
            logger.error(f"Error searching messages: {e}")
            return json.dumps({"error": str(e)})

    def get_thread(self, channel: str, thread_ts: str, limit: int = 100) -> str:
        """Get all messages in a thread by the parent message's timestamp.

        Args:
            channel (str): The channel ID where the thread exists.
            thread_ts (str): The timestamp of the parent message.
            limit (int): The maximum number of replies to fetch. Defaults to 100, max 200.

        Returns:
            str: A JSON string containing the thread timestamp, reply count, and list of messages.
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
            logger.error(f"Error listing users: {e}")
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
            logger.error(f"Error getting user info: {e}")
            return json.dumps({"error": str(e)})
