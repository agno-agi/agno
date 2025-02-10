from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from typing_extensions import Literal

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    from openai import AzureOpenAI as AzureOpenAIClient
    from openai.types.create_embedding_response import CreateEmbeddingResponse
except ImportError:
    raise ImportError("`openai` not installed")


@dataclass
class AzureOpenAIEmbedder(Embedder):
    id: str = "text-embedding-3-small"  # This has to match the model that you deployed at the provided URL

    dimensions: int = 1536
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
        return AzureOpenAIClient(**_client_params)

    def _response(self, text: str) -> CreateEmbeddingResponse:
        _request_params: Dict[str, Any] = {
            "input": text,
            "model": self.id,
            "encoding_format": self.encoding_format,
        }
        if self.user is not None:
            _request_params["user"] = self.user
        if self.id.startswith("text-embedding-3"):
            _request_params["dimensions"] = self.dimensions
        if self.request_params:
            _request_params.update(self.request_params)

        return self.client.embeddings.create(**_request_params)

    def get_embedding(self, text: str) -> List[float]:
        response: CreateEmbeddingResponse = self._response(text=text)
        try:
            return response.data[0].embedding
        except Exception as e:
            logger.warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        response: CreateEmbeddingResponse = self._response(text=text)

        embedding = response.data[0].embedding
        usage = response.usage
        return embedding, usage.model_dump()
