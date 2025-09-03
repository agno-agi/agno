from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from typing_extensions import Literal

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    import requests
except ImportError:
    raise ImportError("requests not installed, use pip install requests")


@dataclass
class JinaEmbedder(Embedder):
    id: str = "jina-embeddings-v3"
    dimensions: int = 1024
    embedding_type: Literal["float", "base64", "int8"] = "float"
    late_chunking: bool = False
    user: Optional[str] = None
    api_key: Optional[str] = getenv("JINA_API_KEY")
    base_url: str = "https://api.jina.ai/v1/embeddings"
    headers: Optional[Dict[str, str]] = None
    request_params: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = None

    def _get_headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ValueError(
                "API key is required for Jina embedder. Set JINA_API_KEY environment variable or pass api_key parameter."
            )

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        if self.headers:
            headers.update(self.headers)
        return headers

    def _response(self, text: str) -> Dict[str, Any]:
        data = {
            "model": self.id,
            "late_chunking": self.late_chunking,
            "dimensions": self.dimensions,
            "embedding_type": self.embedding_type,
            "input": [text],  # Jina API expects a list
        }
        if self.user is not None:
            data["user"] = self.user
        if self.request_params:
            data.update(self.request_params)

        response = requests.post(self.base_url, headers=self._get_headers(), json=data, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_embedding(self, text: str) -> List[float]:
        try:
            result = self._response(text)
            return result["data"][0]["embedding"]
        except Exception as e:
            logger.warning(f"Failed to get embedding: {e}")
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        try:
            result = self._response(text)
            embedding = result["data"][0]["embedding"]
            usage = result.get("usage")
            return embedding, usage
        except Exception as e:
            logger.warning(f"Failed to get embedding and usage: {e}")
            return [], None
