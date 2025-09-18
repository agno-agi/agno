from dataclasses import dataclass

from agno.models.openai.like import OpenAILike


@dataclass
class LlamaCpp(OpenAILike):
    """
    A class for interacting with Llama CPP.

    Attributes:
        id (str): The id of the Llama CPP model. Default is "qwen2.5-7b-instruct-1m".
        name (str): The name of this chat model instance. Default is "Llama CPP".
        provider (str): The provider of the model. Default is "Llama CPP".
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "qwen2.5-7b-instruct-1m"
    name: str = "Llama CPP"
    provider: str = "Llama CPP"

    base_url: str = "http://127.0.0.1:8080/v1"

    supports_native_structured_outputs: bool = False
    supports_json_schema_outputs: bool = True
