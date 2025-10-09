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
    dimensions: Optional[int] = None
    _model: Optional["TextEmbedding"] = None

    def __post_init__(self):
        """Initialize the model and auto-detect dimensions if not specified."""
        if self._model is None:
            self._model = TextEmbedding(model_name=self.id)

        # Auto-detect dimensions from the model if not specified
        if self.dimensions is None:
            # Get a sample embedding to determine dimensions
            sample_embedding = list(self._model.embed(["sample text"]))[0]
            self.dimensions = len(sample_embedding)
            logger.info(f"Auto-detected dimensions for model {self.id}: {self.dimensions}")
        else:
            # Validate that specified dimensions match the model
            sample_embedding = list(self._model.embed(["sample text"]))[0]
            actual_dimensions = len(sample_embedding)
            if self.dimensions != actual_dimensions:
                logger.warning(
                    f"Specified dimensions ({self.dimensions}) don't match model's actual dimensions ({actual_dimensions}). "
                    f"Using model's actual dimensions: {actual_dimensions}"
                )
                self.dimensions = actual_dimensions

    def get_embedding(self, text: str) -> List[float]:
        if self._model is None:
            self._model = TextEmbedding(model_name=self.id)

        embeddings = self._model.embed(text)
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
