from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from agno.knowledge.embedder.base import Embedder
from agno.utils.log import logger

try:
    from huggingface_hub import AsyncInferenceClient, InferenceClient
except ImportError:
    logger.error("`huggingface-hub` not installed, please run `pip install huggingface-hub`")
    raise


@dataclass
class HuggingfaceCustomEmbedder(Embedder):
    """Huggingface Custom Embedder"""

    id: str = "intfloat/multilingual-e5-large"
    api_key: Optional[str] = getenv("HUGGINGFACE_API_KEY")
    client_params: Optional[Dict[str, Any]] = None
    huggingface_client: Optional[InferenceClient] = None
    async_client: Optional[AsyncInferenceClient] = None

    @property
    def client(self) -> InferenceClient:
        if self.huggingface_client:
            return self.huggingface_client
        _client_params: Dict[str, Any] = {}
        if self.api_key:
            _client_params["api_key"] = self.api_key
        if self.client_params:
            _client_params.update(self.client_params)
        self.huggingface_client = InferenceClient(**_client_params)
        return self.huggingface_client

    @property
    def aclient(self) -> AsyncInferenceClient:
        if self.async_client:
            return self.async_client
        _client_params: Dict[str, Any] = {}
        if self.api_key:
            _client_params["api_key"] = self.api_key
        if self.client_params:
            _client_params.update(self.client_params)
        self.async_client = AsyncInferenceClient(**_client_params)
        return self.async_client

    def _response(self, text: str):
        return self.client.feature_extraction(text=text, model=self.id)

    def get_embedding(self, text: str) -> List[float]:
        response = self._response(text=text)
        try:
            # If already a list, return directly
            if isinstance(response, list):
                return response
            # If numpy array, convert to list
            elif hasattr(response, "tolist"):
                return response.tolist()
            else:
                return list(response)
        except Exception as e:
            logger.warning(f"Failed to process embeddings: {e}")
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        return self.get_embedding(text=text), None

    async def async_get_embedding(self, text: str) -> List[float]:
        """Async version of get_embedding using AsyncInferenceClient."""
        response = await self.aclient.feature_extraction(text=text, model=self.id)
        try:
            # If already a list, return directly
            if isinstance(response, list):
                return response
            # If numpy array, convert to list
            elif hasattr(response, "tolist"):
                return response.tolist()
            else:
                return list(response)
        except Exception as e:
            logger.warning(f"Failed to process embeddings: {e}")
            return []

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Async version of get_embedding_and_usage."""
        embedding = await self.async_get_embedding(text=text)
        return embedding, None
