from dataclasses import dataclass

from agno.models.openai.like import OpenAILike


@dataclass
class Nexus(OpenAILike):
    """
    A class for interacting with Nvidia models.

    Attributes:
        id (str): The id of the Nexus model to use. Default is "nvidia/llama-3.1-nemotron-70b-instruct".
        name (str): The name of this chat model instance. Default is "Nexus"
        provider (str): The provider of the model. Default is "Nexus".
        api_key (str): The api key to authorize request to Nexus.
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "openai/gpt-4"
    name: str = "Nexus"
    provider: str = "Nexus"

    base_url: str = "http://localhost:8000/llm/v1/"

    supports_native_structured_outputs: bool = False
