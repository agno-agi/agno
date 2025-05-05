from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class DeepInfra(OpenAILike):
    """
    A class for interacting with DeepInfra models.

    Attributes:
        id (str): The model id. Defaults to "meta-llama/Llama-2-70b-chat-hf".
        name (str): The model name. Defaults to "DeepInfra".
        provider (str): The provider name. Defaults to "DeepInfra".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.deepinfra.com/v1/openai".
    """

    id: str = "meta-llama/Llama-2-70b-chat-hf"
    name: str = "DeepInfra"
    provider: str = "DeepInfra"

    api_key: Optional[str] = getenv("DEEPINFRA_API_KEY")
    base_url: str = "https://api.deepinfra.com/v1/openai"

    supports_native_structured_outputs: bool = False
