from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class DeepInfra(OpenAILike):
    """
    A class for interacting with DeepInfra models.

    For more information, see: https://deepinfra.com/docs/
    """

    id: str = "deepinfra-chat"
    name: str = "DeepInfra"
    provider: str = "DeepInfra"

    api_key: Optional[str] = getenv("DEEPINFRA_API_KEY", None)
    base_url: str = "https://api.deepinfra.com/v1/openai"
