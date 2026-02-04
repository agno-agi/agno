import json
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        all: bool = False,
        **kwargs,
    ):
        """
        Initialize the SlackTools class.
        Args:
            token: The Slack API token. Defaults to the SLACK_TOKEN environment variable.
            markdown: Whether to enable Slack markdown formatting. Defaults to True.
            output_directory: Optional directory to save copies of uploaded files.
            enable_send_message: Whether to enable the send_message tool. Defaults to True.
            enable_send_message_thread: Whether to enable the send_message_thread tool. Defaults to True.
            enable_list_channels: Whether to enable the list_channels tool. Defaults to True.
            enable_get_channel_history: Whether to enable the get_channel_history tool. Defaults to True.
            enable_upload_file: Whether to enable the upload_file tool. Defaults to True.
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

        super().__init__(name="slack", tools=tools, **kwargs)

    def send_message(self, channel: str, text: str) -> str:
        """
        Send a message to a Slack channel.

        Args:
            channel (str): The channel ID or name to send the message to.
            text (str): The text of the message to send.

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
        Send a message to a Slack channel.

        Args:
            channel (str): The channel ID or name to send the message to.
            text (str): The text of the message to send.
            thread_ts (ts): The thread to reply to.

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
        content: bytes,
        filename: str,
        title: Optional[str] = None,
        initial_comment: Optional[str] = None,
        thread_ts: Optional[str] = None,
    ) -> str:
        """
        Upload a file to a Slack channel.

        Args:
            channel (str): The channel ID or name to upload the file to.
            content (bytes): The file content as bytes.
            filename (str): The name for the file (e.g., "report.csv").
            title (str, optional): The title to display for the file in Slack.
            initial_comment (str, optional): A message to post with the file.
            thread_ts (str, optional): The thread timestamp to upload the file as a reply.

        Returns:
            str: A JSON string containing the response from the Slack API.
        """
        try:
            # Save to disk if output_directory is set
            file_path = self._save_file_to_disk(content, filename)

            response = self.client.files_upload_v2(
                channel=channel,
                content=content,
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
