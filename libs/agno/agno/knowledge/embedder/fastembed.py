from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from agno.knowledge.embedder.base import Embedder
from agno.utils.log import logger

try:
    import numpy as np

except ImportError:
    raise ImportError("numpy not installed, use `pip install numpy`")


try:
    from fastembed import TextEmbedding  # type: ignore

except ImportError:
    raise ImportError("fastembed not installed, use pip install fastembed")


@dataclass
class FastEmbedEmbedder(Embedder):
    """Using BAAI/bge-small-en-v1.5 model, more models available: https://qdrant.github.io/fastembed/examples/Supported_Models/"""

    id: str = "BAAI/bge-small-en-v1.5"
    dimensions: Optional[int] = 384

    # Cache the model to avoid loading GBs of weights on every call
    _model: Optional[TextEmbedding] = None

    def __post_init__(self):
        """Initialize lazily - model will be created on first use."""
        self._model = None

    def _get_model(self) -> TextEmbedding:
        """Get or create the embedding model (lazy initialization)."""
        if self._model is None:
            self._model = TextEmbedding(model_name=self.id)
        return self._model

    def get_embedding(self, text: str) -> List[float]:
        model = self._get_model()  # Reuse cached model instead of creating new one
        embeddings = model.embed(text)
        embedding_list = list(embeddings)[0]
        if isinstance(embedding_list, np.ndarray):
            return embedding_list.tolist()

        try:
            return list(embedding_list)
        except Exception as e:
            logger.warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        embedding = self.get_embedding(text=text)
        # Currently, FastEmbed does not provide usage information
        usage = None

        return embedding, usage

    async def async_get_embedding(self, text: str) -> List[float]:
        """Async version using thread executor for CPU-bound operations."""
        import asyncio

        loop = asyncio.get_running_loop()  # Use get_running_loop() instead of deprecated get_event_loop()
        # Run the CPU-bound operation in a thread executor
        return await loop.run_in_executor(None, self.get_embedding, text)

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Async version using thread executor for CPU-bound operations."""
        import asyncio

        loop = asyncio.get_running_loop()  # Use get_running_loop() instead of deprecated get_event_loop()
        # Run the CPU-bound operation in a thread executor
        return await loop.run_in_executor(None, self.get_embedding_and_usage, text)
