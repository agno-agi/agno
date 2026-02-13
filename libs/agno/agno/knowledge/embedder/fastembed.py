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
    fastembed_client: Optional[TextEmbedding] = None

    @property
    def client(self) -> TextEmbedding:
        if self.fastembed_client is None:
            self.fastembed_client = TextEmbedding(model_name=self.id)
        return self.fastembed_client

    def get_embedding(self, text: str) -> List[float]:
        embeddings = self.client.embed(text)
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

        loop = asyncio.get_event_loop()
        # Run the CPU-bound operation in a thread executor
        return await loop.run_in_executor(None, self.get_embedding, text)

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Async version using thread executor for CPU-bound operations."""
        import asyncio

        loop = asyncio.get_event_loop()
        # Run the CPU-bound operation in a thread executor
        return await loop.run_in_executor(None, self.get_embedding_and_usage, text)
