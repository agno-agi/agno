from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class Siliconflow(OpenAILike):
    """
    A class for interacting with Siliconflow API.

    Attributes:
        id (str): The id of the Siliconflow model to use. Default is "Qwen/QwQ-32B".
        name (str): The name of this chat model instance. Default is "Siliconflow".
        provider (str): The provider of the model. Default is "Siliconflow".
        api_key (str): The api key to authorize request to Siliconflow.
        base_url (str): The base url to which the requests are sent. Defaults to "https://api.siliconflow.cn/v1".
    """

    id: str = "Qwen/QwQ-32B"
    name: str = "Siliconflow"
    provider: str = "Siliconflow"
    api_key: Optional[str] = getenv("SILICONFLOW_API_KEY")
    base_url: str = "https://api.siliconflow.com/v1"
