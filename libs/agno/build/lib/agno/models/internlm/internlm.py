from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class InternLM(OpenAILike):
    """
    Class for interacting with the InternLM API.

    Attributes:
        id (str): The ID of the language model. Defaults to "internlm2.5-latest".
        name (str): The name of the model. Defaults to "InternLM".
        provider (str): The provider of the model. Defaults to "InternLM".
        api_key (Optional[str]): The API key for the InternLM API.
        base_url (Optional[str]): The base URL for the InternLM API.
    """

    id: str = "internlm2.5-latest"
    name: str = "InternLM"
    provider: str = "InternLM"

    api_key: Optional[str] = getenv("INTERNLM_API_KEY")
    base_url: Optional[str] = "https://internlm-chat.intern-ai.org.cn/puyu/api/v1/chat/completions"
