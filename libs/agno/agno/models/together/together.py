from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class Together(OpenAILike):
    """
    A class for interacting with Together models.

    Attributes:
        id (str): The id of the Together model to use. Default is "mistralai/Mixtral-8x7B-Instruct-v0.1".
        name (str): The name of this chat model instance. Default is "Together"
        provider (str): The provider of the model. Default is "Together".
        api_key (str): The api key to authorize request to Together.
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "mistralai/Mixtral-8x7B-Instruct-v0.1"
    name: str = "Together"
    provider: str = "Together"
    api_key: Optional[str] = getenv("TOGETHER_API_KEY")
    base_url: str = "https://api.together.xyz/v1"
