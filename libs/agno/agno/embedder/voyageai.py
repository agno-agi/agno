from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    from voyageai import Client
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
    voyage_client: Optional[Client] = None

    @property
    def client(self) -> Client:
        if self.voyage_client:
            return self.voyage_client

        _client_params: Dict[str, Any] = {}
        if self.api_key:
            _client_params["api_key"] = self.api_key
        if self.max_retries:
            _client_params["max_retries"] = self.max_retries
        if self.timeout:
            _client_params["timeout"] = self.timeout
        if self.client_params:
            _client_params.update(self.client_params)
        return Client(**_client_params)

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
