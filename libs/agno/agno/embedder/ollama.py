from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    import pkg_resources
    from packaging import version

    ollama_version = pkg_resources.get_distribution("ollama").version
    if version.parse(ollama_version).major == 0 and version.parse(ollama_version).minor < 3:
        import warnings

        warnings.warn(
            "We only support Ollama v0.3.x and above.",
            UserWarning,
        )
        raise RuntimeError("Incompatible Ollama version detected. Execution halted.")

    from ollama import Client as OllamaClient
except (ModuleNotFoundError, ImportError):
    raise ImportError("`ollama` not installed. Please install using `pip install ollama`")


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

        return self.client.embed(input=text, model=self.id, **kwargs)  # type: ignore

    def get_embedding(self, text: str) -> List[float]:
        try:
            response = self._response(text=text)
            if response is None:
                return []
            return response.get("embeddings", [])
        except Exception as e:
            logger.warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        embedding = self.get_embedding(text=text)
        usage = None
        return embedding, usage
