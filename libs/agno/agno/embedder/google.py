from dataclasses import dataclass
from os import getenv
from types import ModuleType
from typing import Any, Dict, List, Optional, Tuple, Union

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    import google.generativeai as genai
    from google.generativeai.types.text_types import BatchEmbeddingDict, EmbeddingDict
except ImportError:
    logger.error("`google-generativeai` not installed. Please install it using `pip install google-generativeai`")
    raise


@dataclass
class GeminiEmbedder(Embedder):
    id: str = "models/text-embedding-004"
    task_type: str = "RETRIEVAL_QUERY"
    title: Optional[str] = None
    dimensions: Optional[int] = 768
    api_key: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None
    gemini_client: Optional[ModuleType] = None

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
        self.gemini_client = genai
        self.gemini_client.configure(**_client_params)  # type: ignore
        return self.gemini_client

    def _response(self, text: str) -> Union[EmbeddingDict, BatchEmbeddingDict]:
        _request_params: Dict[str, Any] = {
            "content": text,
            "model": self.id,
            "output_dimensionality": self.dimensions,
            "task_type": self.task_type,
            "title": self.title,
        }
        if self.request_params:
            _request_params.update(self.request_params)
        return self.client.embed_content(**_request_params)

    def get_embedding(self, text: str) -> List[float]:
        response = self._response(text=text)
        try:
            return response.get("embedding", [])
        except Exception as e:
            logger.warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        response = self._response(text=text)
        usage = None
        try:
            return response.get("embedding", []), usage
        except Exception as e:
            logger.warning(e)
            return [], usage
