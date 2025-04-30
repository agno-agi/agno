from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class LlamaOpenAI(OpenAILike):
    """
    Class for interacting with the Llama API.

    Attributes:
        id (str): The ID of the language model.
        name (str): The name of the API.
        provider (str): The provider of the API.
        api_key (Optional[str]): The API key for the xAI API.
        base_url (Optional[str]): The base URL for the xAI API.
    """

    id: str = "Llama-4-Maverick-17B-128E-Instruct-FP8"
    name: str = "LlamaOpenAI"
    provider: str = "LlamaOpenAI"

    api_key: Optional[str] = getenv("LLAMA_API_KEY")
    base_url: Optional[str] = "https://api.llama.com/compat/v1/"
