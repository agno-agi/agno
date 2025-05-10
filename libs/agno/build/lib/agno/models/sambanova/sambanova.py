from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class Sambanova(OpenAILike):
    """
    A class for interacting with Sambanova models.

    Attributes:
        id (str): The id of the Sambanova model to use. Default is "Meta-Llama-3.1-8B-Instruct".
        name (str): The name of this chat model instance. Default is "Sambanova"
        provider (str): The provider of the model. Default is "Sambanova".
        api_key (str): The api key to authorize request to Sambanova.
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "Meta-Llama-3.1-8B-Instruct"
    name: str = "Sambanova"
    provider: str = "Sambanova"

    api_key: Optional[str] = getenv("SAMBANOVA_API_KEY")
    base_url: str = "https://api.sambanova.ai/v1"

    supports_native_structured_outputs: bool = False
