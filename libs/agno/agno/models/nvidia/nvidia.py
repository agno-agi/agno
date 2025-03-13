from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class Nvidia(OpenAILike):
    """
    A class for interacting with Nvidia models.

    Attributes:
        id (str): The id of the Nvidia model to use. Default is "nvidia/llama-3.1-nemotron-70b-instruct".
        name (str): The name of this chat model instance. Default is "Nvidia"
        provider (str): The provider of the model. Default is "Nvidia".
        api_key (str): The api key to authorize request to Nvidia.
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "meta/llama-3.3-70b-instruct"
    name: str = "Nvidia"
    provider: str = "Nvidia"

    api_key: Optional[str] = getenv("NVIDIA_API_KEY", None)
    base_url: str = "https://integrate.api.nvidia.com/v1"
