from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class Requesty(OpenAILike):
    """
    A class for using models hosted on Requesty.

    Attributes:
        id (str): The model id. Defaults to "openai/gpt-4.1".
        provider (str): The provider name. Defaults to "Requesty".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://router.requesty.ai/v1".
        max_tokens (int): The maximum number of tokens. Defaults to 1024.
    """

    id: str = "openai/gpt-4.1"
    name: str = "Requesty"
    provider: str = "Requesty"

    api_key: Optional[str] = getenv("REQUESTY_API_KEY")
    base_url: str = "https://router.requesty.ai/v1"
    max_tokens: int = 1024
