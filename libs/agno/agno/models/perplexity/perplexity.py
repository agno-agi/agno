from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class Perplexity(OpenAILike):
    """
    A class for using models hosted on Perplexity.

    Attributes:
        id (str): The model id. Defaults to "sonar".
        name (str): The model name. Defaults to "Perplexity".
        provider (str): The provider name. Defaults to "Perplexity: " + id.
        api_key (Optional[str]): The API key. Defaults to None.
        base_url (str): The base URL. Defaults to "https://api.perplexity.ai/chat/completions".
        max_tokens (int): The maximum number of tokens. Defaults to 1024.
    """

    id: str = "sonar"
    name: str = "Perplexity"
    provider: str = "Perplexity: " + id

    api_key: Optional[str] = getenv("PERPLEXITY_API_KEY")
    base_url: str = "https://api.perplexity.ai/"
    max_tokens: int = 1024
