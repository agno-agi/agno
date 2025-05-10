from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    import importlib.metadata as metadata

    from ollama import Client as OllamaClient
    from packaging import version

    # Get installed Ollama version
    ollama_version = metadata.version("ollama")

    # Check version compatibility (requires v0.3.x or higher)
    parsed_version = version.parse(ollama_version)
    if parsed_version.major == 0 and parsed_version.minor < 3:
        import warnings

        warnings.warn("Only Ollama v0.3.x and above are supported", UserWarning)
        raise RuntimeError("Incompatible Ollama version detected")

except ImportError as e:
    # Handle different import error scenarios
    if "ollama" in str(e):
        raise ImportError("Ollama not installed. Install with `pip install ollama`") from e
    else:
        raise ImportError("Missing dependencies. Install with `pip install packaging importlib-metadata`") from e

except Exception as e:
    # Catch-all for unexpected errors
    print(f"An unexpected error occurred: {e}")


@dataclass
class OllamaEmbedder(Embedder):
    id: str = "openhermes"
    dimensions: int = 4096
    host: Optional[str] = None
    timeout: Optional[Any] = None
    options: Optional[Any] = None
    client_kwargs: Optional[Dict[str, Any]] = None
    ollama_client: Optional[OllamaClient] = None

    @property
    def client(self) -> OllamaClient:
        if self.ollama_client:
            return self.ollama_client

        _ollama_params: Dict[str, Any] = {
            "host": self.host,
            "timeout": self.timeout,
        }
        _ollama_params = {k: v for k, v in _ollama_params.items() if v is not None}
        if self.client_kwargs:
            _ollama_params.update(self.client_kwargs)
        self.ollama_client = OllamaClient(**_ollama_params)
        return self.ollama_client

    def _response(self, text: str) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {}
        if self.options is not None:
            kwargs["options"] = self.options

        response = self.client.embed(input=text, model=self.id, **kwargs)
        if response and "embeddings" in response:
            embeddings = response["embeddings"]
            if isinstance(embeddings, list) and len(embeddings) > 0 and isinstance(embeddings[0], list):
                return {"embeddings": embeddings[0]}  # Use the first element
            elif isinstance(embeddings, list) and all(isinstance(x, (int, float)) for x in embeddings):
                return {"embeddings": embeddings}  # Return as-is if already flat
        return {"embeddings": []}  # Return an empty list if no valid embedding is found

    def get_embedding(self, text: str) -> List[float]:
        try:
            response = self._response(text=text)
            embedding = response.get("embeddings", [])
            if len(embedding) != self.dimensions:
                logger.warning(f"Expected embedding dimension {self.dimensions}, but got {len(embedding)}")
                return []
            return embedding
        except Exception as e:
            logger.warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        embedding = self.get_embedding(text=text)
        usage = None
        return embedding, usage
