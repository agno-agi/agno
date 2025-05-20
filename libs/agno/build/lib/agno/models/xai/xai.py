from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class xAI(OpenAILike):
    """
    Class for interacting with the xAI API.

    Attributes:
        id (str): The ID of the language model. Defaults to "grok-beta".
        name (str): The name of the API. Defaults to "xAI".
        provider (str): The provider of the API. Defaults to "xAI".
        api_key (Optional[str]): The API key for the xAI API.
        base_url (Optional[str]): The base URL for the xAI API. Defaults to "https://api.x.ai/v1".
    """

    id: str = "grok-beta"
    name: str = "xAI"
    provider: str = "xAI"

    api_key: Optional[str] = getenv("XAI_API_KEY")
    base_url: str = "https://api.x.ai/v1"
