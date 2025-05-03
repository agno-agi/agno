from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class Cloudflare(OpenAILike):
    """
    Class for interacting with the Cloudflare API.
    see cloudflare doc : https://developers.cloudflare.com/api/resources/ai/methods/run/

    Attributes:
        id (str): The ID of the language model.
        name (str): The name of the API.
        provider (str): The provider of the API.
        api_acc (Optional[str]): The API account id for the Cloudflare API.
        api_key (Optional[str]): The API key for the Cloudflare API.
        base_url (Optional[str]): The base URL for the Cloudflare API.
    """

    id: str = "@cf/meta/llama-3.1-8b-instruct"
    name: str = "Cloudflare"
    provider: str = "Cloudflare"

    api_acc: Optional[str] = getenv("CLOUDFLARE_ID")
    api_key: Optional[str] = getenv("CLOUDFLARE_TOKEN")
    base_url: Optional[str] = f"https://api.cloudflare.com/client/v4/accounts/{api_acc}/ai/v1"
