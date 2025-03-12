from dataclasses import dataclass

from agno.models.openai.like import OpenAILike


@dataclass
class LMStudio(OpenAILike):
    """
    A class for interacting with LM Studio.

    Attributes:
        id (str): The id of the LM Studio model. Default is "qwen2.5-7b-instruct-1m".
        name (str): The name of this chat model instance. Default is "LMStudio".
        provider (str): The provider of the model. Default is "LMStudio".
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "qwen2.5-7b-instruct-1m"
    name: str = "LMStudio"
    provider: str = "LMStudio"

    base_url: str = "http://127.0.0.1:1234/v1"
