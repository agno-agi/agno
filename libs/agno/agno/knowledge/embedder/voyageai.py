from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agno.knowledge.embedder.base import Embedder
from agno.utils.log import logger

try:
    from voyageai import AsyncClient as AsyncVoyageClient
    from voyageai import Client as VoyageClient
    from voyageai.object import EmbeddingsObject
except ImportError:
    raise ImportError("`voyageai` not installed. Please install using `pip install voyageai`")


@dataclass
class VoyageAIEmbedder(Embedder):
    id: str = "voyage-2"
    dimensions: int = 1024
    request_params: Optional[Dict[str, Any]] = None
    api_key: Optional[str] = None
    base_url: str = "https://api.voyageai.com/v1/embeddings"
    max_retries: Optional[int] = None
    timeout: Optional[float] = None
    client_params: Optional[Dict[str, Any]] = None
    voyage_client: Optional[VoyageClient] = None
    async_client: Optional[AsyncVoyageClient] = None

    @property
    def client(self) -> VoyageClient:
        if self.voyage_client:
            return self.voyage_client

        _client_params = {
            "api_key": self.api_key,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
        }
        _client_params = {k: v for k, v in _client_params.items() if v is not None}
        if self.client_params:
            _client_params.update(self.client_params)
        self.voyage_client = VoyageClient(**_client_params)
        return self.voyage_client

    @property
    def aclient(self) -> AsyncVoyageClient:
        if self.async_client:
            return self.async_client

        _client_params = {
            "api_key": self.api_key,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
        }
        _client_params = {k: v for k, v in _client_params.items() if v is not None}
        if self.client_params:
            _client_params.update(self.client_params)
        self.async_client = AsyncVoyageClient(**_client_params)
        return self.async_client

    def _response(self, text: str) -> EmbeddingsObject:
        _request_params: Dict[str, Any] = {
            "texts": [text],
            "model": self.id,
        }
        if self.request_params:
            _request_params.update(self.request_params)
        return self.client.embed(**_request_params)

    def get_embedding(self, text: str) -> List[float]:
        response: EmbeddingsObject = self._response(text=text)
        try:
            return response.embeddings[0]
        except Exception as e:
            logger.warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        response: EmbeddingsObject = self._response(text=text)

        embedding = response.embeddings[0]
        usage = {"total_tokens": response.total_tokens}
        return embedding, usage

    async def _async_response(self, text: str) -> EmbeddingsObject:
        """Async version of _response using AsyncVoyageClient."""
        _request_params: Dict[str, Any] = {
            "texts": [text],
            "model": self.id,
        }
        if self.request_params:
            _request_params.update(self.request_params)
        return await self.aclient.embed(**_request_params)

    async def async_get_embedding(self, text: str) -> List[float]:
        """Async version of get_embedding."""
        try:
            response: EmbeddingsObject = await self._async_response(text=text)
            return response.embeddings[0]
        except Exception as e:
            logger.warning(f"Error getting embedding: {e}")
            return []

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Async version of get_embedding_and_usage."""
        try:
            response: EmbeddingsObject = await self._async_response(text=text)
            embedding = response.embeddings[0]
            usage = {"total_tokens": response.total_tokens}
            return embedding, usage
        except Exception as e:
            logger.warning(f"Error getting embedding and usage: {e}")
            return [], None
