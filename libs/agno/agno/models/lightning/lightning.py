from dataclasses import dataclass, field
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class Lightning(OpenAILike):
    """
    A class for interacting with Lightning-AI models.

    Attributes:
        id (str): The id of the Lightning model to use. Default is "openai/gpt-5-nano".
        name (str): The name of this chat model instance. Default is "Lightning"
        provider (str): The provider of the model. Default is "Lightning".
        api_key (str): The api key to authorize request to Lightning-AI.
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "openai/gpt-5-nano"
    name: str = "Lightning"
    provider: str = "Lightning"

    api_key: Optional[str] = field(default_factory=lambda: getenv("LIGHTNING_API_KEY"))
    base_url: str = "https://lightning.ai/api/v1/"

    supports_native_structured_outputs: bool = False
