from typing import Optional, Dict, List, Tuple, Any
from typing_extensions import Literal
from dataclasses import dataclass
from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    import requests
except ImportError:
    raise ImportError("requests not installed, use pip install requests")

@dataclass
class JinaEmbedder(Embedder):
    """
    Creates embeddings using the Jina API.
    """
    model: str = "jina-embeddings-v3"
    dimensions: int = 1024
    embedding_type: Literal["float", "base64", "int8"] = "float"
    late_chunking: bool = False
    user: Optional[str] = None
    api_key: Optional[str] = None
    base_url: str = "https://api.jina.ai/v1/embeddings"
    headers: Optional[Dict[str, str]] = None
    request_params: Optional[Dict[str, Any]] = None
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        if self.headers:
            headers.update(self.headers)
        return headers

    def get_embedding(self, text: str | List[str]) -> List[float]:
        """Get embeddings for a single text or list of texts.
        For multiple texts, returns list of embeddings."""
        try:
            # Convert single string to list for consistent handling
            input_text = [text] if isinstance(text, str) else text
            
            data = {
                "model": self.model,
                "late_chunking": self.late_chunking,
                "dimensions": self.dimensions,
                "embedding_type": self.embedding_type,
                "input": input_text
            }
            if self.user is not None:
                data["user"] = self.user
            if self.request_params:
                data.update(self.request_params)
            
            response = requests.post(
                self.base_url,
                headers=self._get_headers(),
                json=data
            )
            response.raise_for_status()
            result = response.json()
            
            # If input was a single string, return its embedding
            if isinstance(text, str):
                return result["data"][0]["embedding"]
            
            # Return list of embeddings
            return [item["embedding"] for item in result["data"]]
            
        except Exception as e:
            logger.warning(f"Failed to get embedding: {e}")
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Get embedding and usage information."""
        try:
            # Convert single string to list for consistent handling
            data = {
                "model": self.model,
                "late_chunking": self.late_chunking,
                "dimensions": self.dimensions,
                "embedding_type": self.embedding_type,
                "input": [text]
            }
            if self.user is not None:
                data["user"] = self.user
            if self.request_params:
                data.update(self.request_params)
            
            response = requests.post(
                self.base_url,
                headers=self._get_headers(),
                json=data
            )
            response.raise_for_status()
            result = response.json()
            
            embedding = result["data"][0]["embedding"]
            usage = result.get("usage")
            return embedding, usage
        except Exception as e:
            logger.warning(f"Failed to get embedding and usage: {e}")
            return [], None