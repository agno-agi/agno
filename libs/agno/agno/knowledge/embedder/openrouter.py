from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.utils.log import log_info, log_warning

try:
    from openai.types.create_embedding_response import CreateEmbeddingResponse
except ImportError:
    raise ImportError("`openai` not installed")


@dataclass
class OpenRouterEmbedder(OpenAIEmbedder):
    """
    Embedder that uses OpenRouter's API to access various embedding models.

    OpenRouter provides a unified API to access embedding models from multiple providers
    (OpenAI, Cohere, Mistral, etc.) through a single endpoint.

    Attributes:
        id (str): The model id in OpenRouter format (provider/model-name).
            Defaults to "openai/text-embedding-3-small".
        dimensions (int): The embedding dimensions. Defaults to 1536.
        api_key (Optional[str]): The OpenRouter API key. If not provided,
            will use OPENROUTER_API_KEY environment variable.
        base_url (str): The OpenRouter API base URL.
            Defaults to "https://openrouter.ai/api/v1".

    Example:
        >>> from agno.knowledge.embedder.openrouter import OpenRouterEmbedder
        >>> embedder = OpenRouterEmbedder()
        >>> embeddings = embedder.get_embedding("Hello, world!")

        >>> # Use a different model
        >>> embedder = OpenRouterEmbedder(id="cohere/embed-english-v3.0", dimensions=1024)

    Note:
        The async methods are overridden because OpenAIEmbedder uses
        `self.id.startswith("text-embedding-3")` to check dimension support,
        which doesn't match OpenRouter's "provider/model" format.
    """

    id: str = "openai/text-embedding-3-small"
    dimensions: int = 1536
    api_key: Optional[str] = None
    base_url: str = "https://openrouter.ai/api/v1"

    def __post_init__(self):
        if self.api_key is None:
            self.api_key = getenv("OPENROUTER_API_KEY")
        super().__post_init__()

    def _supports_dimensions(self) -> bool:
        """Check if the model supports the dimensions parameter."""
        return "text-embedding-3" in self.id

    def _build_request_params(self, input_data: Any) -> Dict[str, Any]:
        """Build request parameters, handling OpenRouter's model ID format."""
        params: Dict[str, Any] = {
            "input": input_data,
            "model": self.id,
            "encoding_format": self.encoding_format,
        }
        if self.user is not None:
            params["user"] = self.user
        if self._supports_dimensions():
            params["dimensions"] = self.dimensions
        if self.request_params:
            params.update(self.request_params)
        return params

    def response(self, text: str) -> CreateEmbeddingResponse:
        return self.client.embeddings.create(**self._build_request_params(text))

    async def async_get_embedding(self, text: str) -> List[float]:
        try:
            response: CreateEmbeddingResponse = await self.aclient.embeddings.create(**self._build_request_params(text))
            return response.data[0].embedding
        except Exception as e:
            log_warning(e)
            return []

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        try:
            response = await self.aclient.embeddings.create(**self._build_request_params(text))
            return response.data[0].embedding, response.usage.model_dump() if response.usage else None
        except Exception as e:
            log_warning(f"Error getting embedding: {e}")
            return [], None

    async def async_get_embeddings_batch_and_usage(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        all_embeddings: List[List[float]] = []
        all_usage: List[Optional[Dict]] = []
        log_info(f"Getting embeddings for {len(texts)} texts in batches of {self.batch_size}")

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            try:
                response: CreateEmbeddingResponse = await self.aclient.embeddings.create(
                    **self._build_request_params(batch)
                )
                all_embeddings.extend([d.embedding for d in response.data])
                usage = response.usage.model_dump() if response.usage else None
                all_usage.extend([usage] * len(response.data))
            except Exception as e:
                log_warning(f"Batch embedding error: {e}")
                for text in batch:
                    emb, usage = await self.async_get_embedding_and_usage(text)
                    all_embeddings.append(emb)
                    all_usage.append(usage)

        return all_embeddings, all_usage
