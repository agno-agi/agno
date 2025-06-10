from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class OpenRouter(OpenAILike):
    """
    A class for using models hosted on OpenRouter.

    Attributes:
        id (str): The model id. Defaults to "gpt-4o".
        name (str): The model name. Defaults to "OpenRouter".
        provider (str): The provider name. Defaults to "OpenRouter".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://openrouter.ai/api/v1".
        max_tokens (int): The maximum number of tokens. Defaults to 1024.
    """

    id: str = "gpt-4o"
    name: str = "OpenRouter"
    provider: str = "OpenRouter"

    api_key: Optional[str] = getenv("OPENROUTER_API_KEY")
    base_url: str = "https://openrouter.ai/api/v1"
    max_tokens: int = 1024
