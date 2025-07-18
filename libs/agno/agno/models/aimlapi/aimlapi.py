from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.models.message import Message
from agno.models.openai.like import OpenAILike


@dataclass
class AIMLApi(OpenAILike):
    """
    A class for using models hosted on AIMLApi.

    Attributes:
        id (str): The model id. Defaults to "gpt-4o-mini".
        name (str): The model name. Defaults to "AIMLApi".
        provider (str): The provider name. Defaults to "AIMLApi".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.aimlapi.com/v1".
        max_tokens (int): The maximum number of tokens. Defaults to 4096.
    """

    id: str = "gpt-4o-mini"
    name: str = "AIMLApi"
    provider: str = "AIMLApi"

    api_key: Optional[str] = getenv("AIMLAPI_API_KEY")
    base_url: str = "https://api.aimlapi.com/v1"
    max_tokens: int = 4096

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Minimal additional formatter that only replaces None with empty string.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message, where 'content = None' is replaced with the empty string.
        """
        formatted: dict = super()._format_message(message)

        formatted["content"] = "" if formatted.get("content") is None else formatted["content"]

        return formatted
