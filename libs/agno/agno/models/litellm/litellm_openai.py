from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class LiteLLMOpenAI(OpenAILike):
    """
    A class for interacting with LiteLLM.

    Attributes:
        id (str): The id of the LiteLLM model. Default is "gpt-4o".
        name (str): The name of this chat model instance. Default is "LiteLLM".
        provider (str): The provider of the model. Default is "LiteLLM".
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "gpt-4o"
    name: str = "LiteLLM"
    provider: str = "LiteLLM"

    api_key: Optional[str] = getenv("LITELLM_API_KEY")
    base_url: str = "http://0.0.0.0:4000"
