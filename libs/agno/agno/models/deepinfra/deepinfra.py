from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class DeepInfra(OpenAILike):
    """
    A class for interacting with DeepInfra models.

    For more information, see: https://deepinfra.com/docs/

    Attributes:
        id (str): The id of the Nvidia model to use. Default is "meta-llama/Llama-2-70b-chat-hf".
        name (str): The name of this chat model instance. Default is "Nvidia"
        provider (str): The provider of the model. Default is "Nvidia".
        api_key (str): The api key to authorize request to Nvidia.
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "meta-llama/Llama-2-70b-chat-hf"
    name: str = "DeepInfra"
    provider: str = "DeepInfra"

    api_key: Optional[str] = getenv("DEEPINFRA_API_KEY", None)
    base_url: str = "https://api.deepinfra.com/v1/openai"

    supports_native_structured_outputs: bool = False
