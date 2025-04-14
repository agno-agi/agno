from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class AImlAPI(OpenAILike):
    """
    A class for using models hosted on AI/ML API.

    Attributes:
        id (str): The model id. Defaults to "gpt-4o".
        name (str): The model name. Defaults to "AImlAPI".
        provider (str): The provider name. Defaults to "AImlAPI: " + id.
        api_key (Optional[str]): The API key. Defaults to None.
        base_url (str): The base URL. Defaults to "https://api.aimlapi.com/v1".
        max_tokens (int): The maximum number of tokens. Defaults to 1024.
    """

    id: str = "gpt-4o-mini"
    name: str = "AImlAPI"
    provider: str = "AImlAPI"

    api_key: Optional[str] = getenv("AIMLAPI_API_KEY")
    base_url: str = "https://api.aimlapi.com/v1/chat/completions"
    max_tokens: int = 1024
