from dataclasses import dataclass, field
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike

try:
    from openai.types.chat.chat_completion import ChatCompletion
    from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
except (ImportError, ModuleNotFoundError):
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class Inception(OpenAILike):
    """
    Class for interacting with the Inception Labs API.

    Attributes:
        id (str): The ID of the language model. Defaults to "mercury".
        name (str): The name of the API. Defaults to "Inception".
        provider (str): The provider of the API. Defaults to "InceptionLabs".
        api_key (Optional[str]): The API key for the Inception Labs API.
        base_url (Optional[str]): The base URL for the Inception Labs API. Defaults to "https://api.inceptionlabs.ai/v1".
    """

    id: str = "mercury"
    name: str = "Inception"
    provider: str = "InceptionLabs"

    api_key: Optional[str] = field(default_factory=lambda: getenv("INCEPTION_API_KEY"))
    base_url: str = "https://api.inceptionlabs.ai/v1"
