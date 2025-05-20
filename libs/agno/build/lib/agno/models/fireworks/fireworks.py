from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai import OpenAILike


@dataclass
class Fireworks(OpenAILike):
    """
    A class for interacting with models hosted on Fireworks.

    Attributes:
        id (str): The model name to use. Defaults to "accounts/fireworks/models/llama-v3p1-405b-instruct".
        name (str): The model name to use. Defaults to "Fireworks".
        provider (str): The provider to use. Defaults to "Fireworks".
        api_key (Optional[str]): The API key to use.
        base_url (str): The base URL to use. Defaults to "https://api.fireworks.ai/inference/v1".
    """

    id: str = "accounts/fireworks/models/llama-v3p1-405b-instruct"
    name: str = "Fireworks"
    provider: str = "Fireworks"

    api_key: Optional[str] = getenv("FIREWORKS_API_KEY")
    base_url: str = "https://api.fireworks.ai/inference/v1"
