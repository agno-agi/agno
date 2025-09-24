from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from agno.knowledge.embedder.base import Embedder
from agno.utils.log import logger

try:
    from cohere import AsyncClient as AsyncCohereClient
    from cohere import Client as CohereClient
    from cohere.types.embed_response import EmbeddingsByTypeEmbedResponse, EmbeddingsFloatsEmbedResponse
except ImportError:
    raise ImportError("`cohere` not installed. Please install using `pip install cohere`.")


@dataclass
class CohereEmbedder(Embedder):
    id: str = "embed-english-v3.0"
    input_type: str = "search_query"
    embedding_types: Optional[List[str]] = None
    api_key: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None
    cohere_client: Optional[CohereClient] = None
    async_client: Optional[AsyncCohereClient] = None

    @property
    def client(self) -> CohereClient:
        if self.cohere_client:
            return self.cohere_client
        client_params: Dict[str, Any] = {}
        if self.api_key:
            client_params["api_key"] = self.api_key
        if self.client_params:
            client_params.update(self.client_params)
        self.cohere_client = CohereClient(**client_params)
        return self.cohere_client

    @property
    def aclient(self) -> AsyncCohereClient:
        """Lazy init for Cohere async client."""
        if self.async_client:
            return self.async_client
        params: Dict[str, Any] = {}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.client_params:
            params.update(self.client_params)
        self.async_client = AsyncCohereClient(**params)
        return self.async_client

    def response(self, text: str) -> Union[EmbeddingsFloatsEmbedResponse, EmbeddingsByTypeEmbedResponse]:
        request_params: Dict[str, Any] = {}

        if self.id:
            request_params["model"] = self.id
        if self.input_type:
            request_params["input_type"] = self.input_type
        if self.embedding_types:
            request_params["embedding_types"] = self.embedding_types
        if self.request_params:
            request_params.update(self.request_params)
        return self.client.embed(texts=[text], **request_params)

    def get_embedding(self, text: str) -> List[float]:
        response: Union[EmbeddingsFloatsEmbedResponse, EmbeddingsByTypeEmbedResponse] = self.response(text=text)
        try:
            if isinstance(response, EmbeddingsFloatsEmbedResponse):
                return response.embeddings[0]
            elif isinstance(response, EmbeddingsByTypeEmbedResponse):
                return response.embeddings.float_[0] if response.embeddings.float_ else []
            else:
                logger.warning("No embeddings found")
                return []
        except Exception as e:
            logger.warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        response: Union[EmbeddingsFloatsEmbedResponse, EmbeddingsByTypeEmbedResponse] = self.response(text=text)

        embedding: List[float] = []
        if isinstance(response, EmbeddingsFloatsEmbedResponse):
            embedding = response.embeddings[0]
        elif isinstance(response, EmbeddingsByTypeEmbedResponse):
            embedding = response.embeddings.float_[0] if response.embeddings.float_ else []

        usage = response.meta.billed_units if response.meta else None
        if usage:
            return embedding, usage.model_dump()
        return embedding, None

    async def async_get_embedding(self, text: str) -> List[float]:
        request_params: Dict[str, Any] = {}

        if self.id:
            request_params["model"] = self.id
        if self.input_type:
            request_params["input_type"] = self.input_type
        if self.embedding_types:
            request_params["embedding_types"] = self.embedding_types
        if self.request_params:
            request_params.update(self.request_params)

        try:
            response: Union[EmbeddingsFloatsEmbedResponse, EmbeddingsByTypeEmbedResponse] = await self.aclient.embed(
                texts=[text], **request_params
            )
            if isinstance(response, EmbeddingsFloatsEmbedResponse):
                return response.embeddings[0]
            elif isinstance(response, EmbeddingsByTypeEmbedResponse):
                return response.embeddings.float_[0] if response.embeddings.float_ else []
            else:
                logger.warning("No embeddings found")
                return []
        except Exception as e:
            logger.warning(e)
            return []

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        request_params: Dict[str, Any] = {}

        if self.id:
            request_params["model"] = self.id
        if self.input_type:
            request_params["input_type"] = self.input_type
        if self.embedding_types:
            request_params["embedding_types"] = self.embedding_types
        if self.request_params:
            request_params.update(self.request_params)

        response: Union[EmbeddingsFloatsEmbedResponse, EmbeddingsByTypeEmbedResponse] = await self.aclient.embed(
            texts=[text], **request_params
        )

        embedding: List[float] = []
        if isinstance(response, EmbeddingsFloatsEmbedResponse):
            embedding = response.embeddings[0]
        elif isinstance(response, EmbeddingsByTypeEmbedResponse):
            embedding = response.embeddings.float_[0] if response.embeddings.float_ else []

        usage = response.meta.billed_units if response.meta else None
        if usage:
            return embedding, usage.model_dump()
        return embedding, None
