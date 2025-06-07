from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from typing_extensions import Literal

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    from openai import OpenAI as OpenAIClient
    from openai.types.create_embedding_response import CreateEmbeddingResponse
except ImportError:
    raise ImportError("`openai` not installed")


class LangDBEmbedder(Embedder):
    model: str = "text-embedding-ada-002"
    dimensions: int = 1536
    encoding_format: Literal["float", "base64"] = "float"
    user: Optional[str] = None
    api_key: Optional[str] = getenv("LANGDB_API_KEY")
    project_id: Optional[str] = getenv("LANGDB_PROJECT_ID")
    if not project_id:
        logger.error("LANGDB_PROJECT_ID not set in the environment")
    organization: Optional[str] = None
    base_url: Optional[str] = f"https://api.us-east-1.langdb.ai/{project_id}/v1"
    request_params: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None
    openai_client: Optional[OpenAIClient] = None

    @property
    def client(self) -> OpenAIClient:
        if self.openai_client:
            return self.openai_client

        _client_params: Dict[str, Any] = {}
        if self.api_key:
            _client_params["api_key"] = self.api_key
        if self.organization:
            _client_params["organization"] = self.organization
        if self.base_url:
            _client_params["base_url"] = self.base_url
        if self.client_params:
            _client_params.update(self.client_params)
        return OpenAIClient(**_client_params)

    def response(self, text: str) -> CreateEmbeddingResponse:
        _request_params: Dict[str, Any] = {
            "input": text,
            "model": self.model,
            "encoding_format": self.encoding_format,
        }
        if self.user is not None:
            _request_params["user"] = self.user
        if self.model.startswith("text-embedding-3"):
            _request_params["dimensions"] = self.dimensions
        if self.request_params:
            _request_params.update(self.request_params)
        return self.client.embeddings.create(**_request_params)

    def get_embedding(self, text: str) -> List[float]:
        response: CreateEmbeddingResponse = self.response(text=text)
        try:
            return response.data[0].embedding
        except Exception as e:
            logger.warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        response: CreateEmbeddingResponse = self.response(text=text)

        embedding = response.data[0].embedding
        usage = response.usage
        if usage:
            return embedding, usage.model_dump()
        return embedding, None
