from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai import OpenAILike


@dataclass
class Qianfan(OpenAILike):
    """
    A class for interacting with BaiduQianfan models.

    Attributes:
        id (str): The id of the Nvidia model to use. Default is "nvidia/llama-3.1-nemotron-70b-instruct".
        name (str): The name of this chat model instance. Default is "Nvidia"
        provider (str): The provider of the model. Default is "Nvidia".
        api_key (str): The api key to authorize request to Nvidia.
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "deepseek-v3"
    name: str = "Qianfan"
    provider: str = "Qianfan"

    api_key: Optional[str] = getenv("QIANFAN_API_KEY")
    base_url: str = "https://qianfan.baidubce.com/v2"

    supports_native_structured_outputs: bool = True

    role_map = {
        "system": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
        "model": "assistant",
    }
