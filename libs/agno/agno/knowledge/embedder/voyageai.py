from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agno.knowledge.embedder.base import (
    Embedder,
    aembed_texts_individually,
    first_embedding,
    pad_batch_embeddings,
    raise_embedding_error,
)
from agno.utils.log import log_warning, logger

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

        _client_params: Dict[str, Any] = {}
        if self.api_key is not None:
            _client_params["api_key"] = self.api_key
        if self.max_retries is not None:
            _client_params["max_retries"] = self.max_retries
        if self.timeout is not None:
            _client_params["timeout"] = self.timeout
        if self.client_params:
            _client_params.update(self.client_params)
        self.voyage_client = VoyageClient(**_client_params)
        return self.voyage_client

    @property
    def aclient(self) -> AsyncVoyageClient:
        if self.async_client:
            return self.async_client

        _client_params: Dict[str, Any] = {}
        if self.api_key is not None:
            _client_params["api_key"] = self.api_key
        if self.max_retries is not None:
            _client_params["max_retries"] = self.max_retries
        if self.timeout is not None:
            _client_params["timeout"] = self.timeout
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
        try:
            response: EmbeddingsObject = self._response(text=text)
            embedding = first_embedding(response.embeddings, "VoyageAI") or []
            return [float(x) for x in embedding]  # Ensure all values are float
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="VoyageAI")

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        try:
            response: EmbeddingsObject = self._response(text=text)

            embedding = first_embedding(response.embeddings, "VoyageAI") or []
            usage = {"total_tokens": response.total_tokens}
            return [float(x) for x in embedding], usage
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="VoyageAI")

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
            embedding = first_embedding(response.embeddings, "VoyageAI") or []
            return [float(x) for x in embedding]  # Ensure all values are float
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="VoyageAI")

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Async version of get_embedding_and_usage."""
        try:
            response: EmbeddingsObject = await self._async_response(text=text)
            embedding = first_embedding(response.embeddings, "VoyageAI") or []
            usage = {"total_tokens": response.total_tokens}
            return [float(x) for x in embedding], usage
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="VoyageAI")

    async def async_get_embeddings_batch_and_usage(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        """
        Get embeddings and usage for multiple texts in batches.

        Args:
            texts: List of text strings to embed

        Returns:
            Tuple of (List of embedding vectors, List of usage dictionaries)
        """
        all_embeddings: List[List[float]] = []
        all_usage: List[Optional[Dict]] = []
        logger.info(f"Getting embeddings and usage for {len(texts)} texts in batches of {self.batch_size}")

        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]

            req: Dict[str, Any] = {
                "texts": batch_texts,
                "model": self.id,
            }
            if self.request_params:
                req.update(self.request_params)

            try:
                response: EmbeddingsObject = await self.aclient.embed(**req)
                batch_embeddings = pad_batch_embeddings(
                    [[float(x) for x in emb] for emb in response.embeddings], batch_texts, "VoyageAI"
                )
                all_embeddings.extend(batch_embeddings)

                # For each embedding in the batch, add the same usage information
                usage_dict = {"total_tokens": response.total_tokens}
                all_usage.extend([usage_dict] * len(batch_embeddings))
            except Exception as e:
                log_warning(f"Error in async batch embedding: {str(e)}")
                # Fall back to individual calls: a whole-batch failure is often transient
                # (or caused by a single bad text). Successes are kept so one bad chunk
                # does not discard the rest of the batch.
                batch_embeddings, batch_usage = await aembed_texts_individually(self, batch_texts)
                all_embeddings.extend(batch_embeddings)
                all_usage.extend(batch_usage)

        return all_embeddings, all_usage
