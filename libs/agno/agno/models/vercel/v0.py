from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class v0(OpenAILike):
    """
    Class for interacting with the v0 API.

    Attributes:
        id (str): The ID of the language model. Defaults to "v0-1.0-md".
        name (str): The name of the API. Defaults to "v0".
        provider (str): The provider of the API. Defaults to "v0".
        api_key (Optional[str]): The API key for the v0 API.
        base_url (Optional[str]): The base URL for the v0 API. Defaults to "https://v0.dev/chat/settings/keys".
    """

    id: str = "v0-1.0-md"
    name: str = "v0"
    provider: str = "Vercel"

    api_key: Optional[str] = getenv("V0_API_KEY")
    base_url: str = "https://api.v0.dev/v1/"
