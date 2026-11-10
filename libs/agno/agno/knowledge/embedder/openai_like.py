from dataclasses import dataclass
from typing import Optional

from agno.knowledge.embedder.openai import OpenAIEmbedder


@dataclass
class OpenAILikeEmbedder(OpenAIEmbedder):
    """
    A class for interacting with any provider using the OpenAI-compatible embedding API.

    Use this for LiteLLM proxy, Ollama (OpenAI-compatible mode), vLLM, and other
    providers that expose an OpenAI-compatible /v1/embeddings endpoint.

    Args:
        id (str): The model id to use. Defaults to "not-provided".
        api_key (Optional[str]): The API key to use. Defaults to "not-provided".
        base_url (Optional[str]): The base URL for the API endpoint.
        dimensions (Optional[int]): The dimensions of the embeddings. Defaults to 1536.
    """

    id: str = "not-provided"
    dimensions: Optional[int] = 1536
    api_key: Optional[str] = "not-provided"

    def __post_init__(self):
        # Skip the OpenAIEmbedder __post_init__ which sets dimensions based on known OpenAI model IDs.
        # For custom providers, the user should set dimensions explicitly.
        pass
