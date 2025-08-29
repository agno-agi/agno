from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    from voyageai import Client as VoyageClient
    from voyageai.object import EmbeddingsObject, ContextualizedEmbeddingsObject
except ImportError:
    raise ImportError("`voyageai` not installed. Please install using `pip install voyageai`")


@dataclass
class VoyageAIEmbedder(Embedder):
    id: str = "voyage-context-3"
    dimensions: int = 1024
    request_params: Optional[Dict[str, Any]] = None
    api_key: Optional[str] = None
    max_retries: Optional[int] = None
    timeout: Optional[float] = None
    client_params: Optional[Dict[str, Any]] = None
    voyage_client: Optional[VoyageClient] = None

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

    def _contextualized_response(self, documents_chunks: List[List[str]], input_type: str = "document") -> ContextualizedEmbeddingsObject:
        """Get contextualized embedding response for multiple documents with chunks"""
        _request_params: Dict[str, Any] = {
            "inputs": documents_chunks,  # List[List[str]] format
            "model": self.id,
            "input_type": input_type,
        }
        if self.request_params:
            _request_params.update(self.request_params)
        return self.client.contextualized_embed(**_request_params)

    def _standard_response(self, text: str) -> EmbeddingsObject:
        """Get standard embedding response for a single text"""
        _request_params: Dict[str, Any] = {
            "texts": [text], 
            "model": self.id,
        }
        if self.request_params:
            _request_params.update(self.request_params)
        return self.client.embed(**_request_params)

    def get_embedding(self, text: str) -> Dict[str, Any]:
        """Get embedding for a single text with usage info"""
        try:
            response = self._standard_response(text=text)
            return {
                "embeddings": response.embeddings[0],
                "total_tokens": response.total_tokens
            }
        except Exception as e:
            logger.warning(f"Error getting standard embedding: {e}")
            return {"embeddings": [], "total_tokens": None}

    def get_contextualized_embeddings(
        self, 
        documents_chunks: List[List[str]], 
        input_type: str = "document"
    ) -> Dict[str, Any]:
        """
         Get contextualized embeddings for multiple documents, each with their own chunks.
        """
        try:
            response = self._contextualized_response(documents_chunks, input_type)
            embeddings = [emb for r in response.results for emb in r.embeddings]
            return {
                "embeddings": embeddings,
                "total_tokens": response.total_tokens
            }
        except Exception as e:
            logger.warning(f"Error getting contextualized embeddings: {e}")
            return {"embeddings": [], "total_tokens": None}
