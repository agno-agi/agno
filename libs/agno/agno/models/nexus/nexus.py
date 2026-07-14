from dataclasses import dataclass

from agno.models.openai.like import OpenAILike


@dataclass
class Nexus(OpenAILike):
    """
    A class for interacting with LLMs using Nexus.

    Attributes:
        id (str): The id of the Nexus model to use. Default is "openai/gpt-4".
        name (str): The name of this chat model instance. Default is "Nexus"
        provider (str): The provider of the model. Default is "Nexus".
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "openai/gpt-4"
    name: str = "Nexus"
    provider: str = "Nexus"

    base_url: str = "http://localhost:8000/llm/v1/"
