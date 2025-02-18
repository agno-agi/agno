from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    from google import genai
    from google.genai import Client as GeminiClient
    from google.genai.types import EmbedContentResponse
except ImportError:
    raise ImportError("`google-genai` not installed. Please install it using `pip install google-genai`")


@dataclass
class GeminiEmbedder(Embedder):
    id: str = "text-embedding-004"
    task_type: str = "RETRIEVAL_QUERY"
    title: Optional[str] = None
    dimensions: Optional[int] = 768
    api_key: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None
    gemini_client: Optional[GeminiClient] = None

    @property
    def client(self):
        if self.gemini_client:
            return self.gemini_client

        _client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.error("GOOGLE_API_KEY not set. Please set the GOOGLE_API_KEY environment variable.")

        if self.api_key:
            _client_params["api_key"] = self.api_key
        if self.client_params:
            _client_params.update(self.client_params)

        self.gemini_client = genai.Client(**_client_params)

        return self.gemini_client

    def _response(self, text: str) -> EmbedContentResponse:
        # If a user provides a model id with the `models/` prefix, we need to remove it
        _id = self.id
        if _id.startswith("models/"):
            _id = _id.split("/")[-1]

        _request_params: Dict[str, Any] = {"contents": text, "model": _id, "config": {}}
        if self.dimensions:
            _request_params["config"]["output_dimensionality"] = self.dimensions
        if self.task_type:
            _request_params["config"]["task_type"] = self.task_type
        if self.title:
            _request_params["config"]["title"] = self.title
        if not _request_params["config"]:
            del _request_params["config"]

        if self.request_params:
            _request_params.update(self.request_params)
        return self.client.models.embed_content(**_request_params)

    def get_embedding(self, text: str) -> List[float]:
        response = self._response(text=text)
        try:
            return response.embeddings[0].values
        except Exception as e:
            logger.warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        response = self._response(text=text)
        usage = response.metadata.billable_character_count if response.metadata else None
        try:
            return response.embeddings[0].values, usage
        except Exception as e:
            logger.warning(e)
            return [], usage
