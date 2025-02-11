from asyncio.log import logger
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.utils.openai import add_audio_to_message, add_images_to_message


@dataclass
class GeminiOpenAI(OpenAILike):
    """
    Class for interacting with the Gemini API (OpenAI).

    Attributes:
        id (str): The ID of the API.
        name (str): The name of the API.
        provider (str): The provider of the API.
        api_key (Optional[str]): The API key for the xAI API.
        base_url (Optional[str]): The base URL for the xAI API.
    """

    id: str = "gemini-1.5-flash"
    name: str = "GeminiOpenAI"
    provider: str = "Google"

    api_key: Optional[str] = getenv("GOOGLE_API_KEY", None)
    base_url: Optional[str] = "https://generativelanguage.googleapis.com/v1beta/"


    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        if message.role == "user":
            if message.images is not None:
                message = add_images_to_message(message=message, images=message.images)

            if message.audio is not None:
                message = add_audio_to_message(message=message, audio=message.audio)

            if message.videos is not None:
                logger.warning("Video input is currently unsupported.")

        # OpenAI expects the tool_calls to be None if empty, not an empty list
        if message.tool_calls is not None and len(message.tool_calls) == 0:
            message.tool_calls = None

        message_dict = message.to_dict()
        message_dict["role"] = self.role_map[message_dict["role"]]
        
        # Gemini expects the content to be removed if it is None
        if message_dict["content"] is None:
            message_dict.pop("content")

        return message_dict
