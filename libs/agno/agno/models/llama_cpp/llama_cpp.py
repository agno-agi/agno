from dataclasses import dataclass

from agno.models.openai.like import OpenAILike


@dataclass
class LlamaCpp(OpenAILike):
    """
    A class for interacting with LLMs using Llama CPP.

    Attributes:
        id (str): The id of the Llama CPP model. Default is "ggml-org/gpt-oss-20b-GGUF".
        name (str): The name of this chat model instance. Default is "LlamaCpp".
        provider (str): The provider of the model. Default is "LlamaCpp".
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "ggml-org/gpt-oss-20b-GGUF"
    name: str = "LlamaCpp"
    provider: str = "LlamaCpp"

    base_url: str = "http://127.0.0.1:8080/v1"
