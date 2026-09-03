from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from typing_extensions import Literal

from agno.knowledge.embedder.base import (
    Embedder,
    aembed_texts_individually,
    first_embedding,
    pad_batch_embeddings,
    raise_embedding_error,
)
from agno.utils.log import log_warning, logger

try:
    from openai import AsyncAzureOpenAI as AsyncAzureOpenAIClient
    from openai import AzureOpenAI as AzureOpenAIClient
    from openai.types.create_embedding_response import CreateEmbeddingResponse
except ImportError:
    raise ImportError("`openai` not installed")


@dataclass
class AzureOpenAIEmbedder(Embedder):
    id: str = "text-embedding-3-small"  # This has to match the model that you deployed at the provided URL
    dimensions: Optional[int] = None
    encoding_format: Literal["float", "base64"] = "float"
    user: Optional[str] = None
    api_key: Optional[str] = getenv("AZURE_EMBEDDER_OPENAI_API_KEY")
    api_version: str = getenv("AZURE_EMBEDDER_OPENAI_API_VERSION", "2024-10-21")
    azure_endpoint: Optional[str] = getenv("AZURE_EMBEDDER_OPENAI_ENDPOINT")
    azure_deployment: Optional[str] = getenv("AZURE_EMBEDDER_DEPLOYMENT")
    base_url: Optional[str] = None
    azure_ad_token: Optional[str] = None
    azure_ad_token_provider: Optional[Any] = None
    organization: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None
    openai_client: Optional[AzureOpenAIClient] = None
    async_client: Optional[AsyncAzureOpenAIClient] = None

    def __post_init__(self):
        if self.dimensions is None and self.id.startswith("text-embedding-3"):
            self.dimensions = 1536

    @property
    def client(self) -> AzureOpenAIClient:
        if self.openai_client:
            return self.openai_client

        _client_params: Dict[str, Any] = {}
        if self.api_key:
            _client_params["api_key"] = self.api_key
        if self.api_version:
            _client_params["api_version"] = self.api_version
        if self.organization:
            _client_params["organization"] = self.organization
        if self.azure_endpoint:
            _client_params["azure_endpoint"] = self.azure_endpoint
        if self.azure_deployment:
            _client_params["azure_deployment"] = self.azure_deployment
        if self.base_url:
            _client_params["base_url"] = self.base_url
        if self.azure_ad_token:
            _client_params["azure_ad_token"] = self.azure_ad_token
        if self.azure_ad_token_provider:
            _client_params["azure_ad_token_provider"] = self.azure_ad_token_provider

        if self.client_params:
            _client_params.update(self.client_params)

        return AzureOpenAIClient(**_client_params)

    @property
    def aclient(self) -> AsyncAzureOpenAIClient:
        if self.async_client:
            return self.async_client

        _client_params: Dict[str, Any] = {}
        if self.api_key:
            _client_params["api_key"] = self.api_key
        if self.api_version:
            _client_params["api_version"] = self.api_version
        if self.organization:
            _client_params["organization"] = self.organization
        if self.azure_endpoint:
            _client_params["azure_endpoint"] = self.azure_endpoint
        if self.azure_deployment:
            _client_params["azure_deployment"] = self.azure_deployment
        if self.base_url:
            _client_params["base_url"] = self.base_url
        if self.azure_ad_token:
            _client_params["azure_ad_token"] = self.azure_ad_token
        if self.azure_ad_token_provider:
            _client_params["azure_ad_token_provider"] = self.azure_ad_token_provider

        if self.client_params:
            _client_params.update(self.client_params)

        self.async_client = AsyncAzureOpenAIClient(**_client_params)
        return self.async_client

    def _response(self, text: str) -> CreateEmbeddingResponse:
        _request_params: Dict[str, Any] = {
            "input": [text],
            "model": self.id,
            "encoding_format": self.encoding_format,
        }
        if self.user is not None:
            _request_params["user"] = self.user
        if self.dimensions is not None:
            _request_params["dimensions"] = self.dimensions
        if self.request_params:
            _request_params.update(self.request_params)

        return self.client.embeddings.create(**_request_params)

    def get_embedding(self, text: str) -> List[float]:
        try:
            response: CreateEmbeddingResponse = self._response(text=text)
            entry = first_embedding(response.data, "AzureOpenAI")
            return entry.embedding if entry else []
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="AzureOpenAI")

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        try:
            response: CreateEmbeddingResponse = self._response(text=text)

            entry = first_embedding(response.data, "AzureOpenAI")
            embedding = entry.embedding if entry else []
            usage = response.usage
            return embedding, usage.model_dump() if usage else None
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="AzureOpenAI")

    async def _aresponse(self, text: str) -> CreateEmbeddingResponse:
        """Async version of _response method."""
        _request_params: Dict[str, Any] = {
            "input": [text],
            "model": self.id,
            "encoding_format": self.encoding_format,
        }
        if self.user is not None:
            _request_params["user"] = self.user
        if self.dimensions is not None:
            _request_params["dimensions"] = self.dimensions
        if self.request_params:
            _request_params.update(self.request_params)

        return await self.aclient.embeddings.create(**_request_params)

    async def async_get_embedding(self, text: str) -> List[float]:
        """Async version of get_embedding using the native Azure OpenAI async client."""
        try:
            response: CreateEmbeddingResponse = await self._aresponse(text=text)
            entry = first_embedding(response.data, "AzureOpenAI")
            return entry.embedding if entry else []
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="AzureOpenAI")

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Async version of get_embedding_and_usage using the native Azure OpenAI async client."""
        try:
            response: CreateEmbeddingResponse = await self._aresponse(text=text)

            entry = first_embedding(response.data, "AzureOpenAI")
            embedding = entry.embedding if entry else []
            usage = response.usage
            return embedding, usage.model_dump() if usage else None
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="AzureOpenAI")

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
        all_embeddings = []
        all_usage = []
        logger.info(f"Getting embeddings and usage for {len(texts)} texts in batches of {self.batch_size}")

        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]

            req: Dict[str, Any] = {
                "input": batch_texts,
                "model": self.id,
                "encoding_format": self.encoding_format,
            }
            if self.user is not None:
                req["user"] = self.user
            if self.dimensions is not None:
                req["dimensions"] = self.dimensions
            if self.request_params:
                req.update(self.request_params)

            try:
                response: CreateEmbeddingResponse = await self.aclient.embeddings.create(**req)
                batch_embeddings = pad_batch_embeddings(
                    [data.embedding for data in response.data], batch_texts, "AzureOpenAI"
                )
                all_embeddings.extend(batch_embeddings)

                # For each embedding in the batch, add the same usage information
                usage_dict = response.usage.model_dump() if response.usage else None
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
