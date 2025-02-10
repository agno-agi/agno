import json
import os
from typing import Any, Dict, List, Optional

from agno.tools.toolkit import Toolkit
from agno.utils.log import logger

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError:
    raise ImportError("Slack tools require the `slack_sdk` package. Run `pip install slack-sdk` to install it.")


class SlackTools(Toolkit):
    def __init__(
        self,
        token: Optional[str] = None,
        send_message: bool = True,
        list_channels: bool = True,
        get_channel_history: bool = True,
    ):
        super().__init__(name="slack")
        self.token: Optional[str] = token or os.getenv("SLACK_TOKEN")
        if self.token is None or self.token == "":
            raise ValueError("SLACK_TOKEN is not set")
        self.client = WebClient(token=self.token)
        if send_message:
            self.register(self.send_message)
        if list_channels:
            self.register(self.list_channels)
        if get_channel_history:
            self.register(self.get_channel_history)

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
            response = self.client.chat_postMessage(channel=channel, text=text)
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
