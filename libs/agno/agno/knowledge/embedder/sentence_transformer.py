from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from agno.knowledge.embedder.base import Embedder
from agno.utils.log import logger

try:
    from sentence_transformers import SentenceTransformer

except ImportError:
    raise ImportError("`sentence-transformers` not installed, please run `pip install sentence-transformers`")

try:
    import numpy as np

except ImportError:
    raise ImportError("numpy not installed, use `pip install numpy`")


@dataclass
class SentenceTransformerEmbedder(Embedder):
    id: str = "sentence-transformers/all-MiniLM-L6-v2"
    dimensions: int = 384
    sentence_transformer_client: Optional[SentenceTransformer] = None
    prompt: Optional[str] = None
    normalize_embeddings: bool = False
    _lock: Optional[object] = None  # asyncio.Lock for thread-safe async operations

    def __post_init__(self):
        """Initialize the async lock after dataclass initialization."""
        import asyncio

        self._lock = asyncio.Lock()

    def get_embedding(self, text: Union[str, List[str]]) -> List[float]:
        if not self.sentence_transformer_client:
            self.sentence_transformer_client = SentenceTransformer(model_name_or_path=self.id)

        model = self.sentence_transformer_client
        embedding = model.encode(text, prompt=self.prompt, normalize_embeddings=self.normalize_embeddings)
        try:
            if isinstance(embedding, np.ndarray):
                return embedding.tolist()

            return embedding  # type: ignore
        except Exception as e:
            logger.warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        return self.get_embedding(text=text), None

    async def async_get_embedding(self, text: Union[str, List[str]]) -> List[float]:
        """Async version using thread executor for CPU-bound operations with locking."""
        import asyncio

        # Ensure lock is initialized
        if self._lock is None:
            self._lock = asyncio.Lock()

        loop = asyncio.get_event_loop()
        # Use lock to prevent concurrent access to the model
        async with self._lock:
            # Run the CPU-bound operation in a thread executor
            return await loop.run_in_executor(None, self.get_embedding, text)

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Async version using thread executor for CPU-bound operations with locking."""
        import asyncio

        # Ensure lock is initialized
        if self._lock is None:
            self._lock = asyncio.Lock()

        loop = asyncio.get_event_loop()
        # Use lock to prevent concurrent access to the model
        async with self._lock:
            return await loop.run_in_executor(None, self.get_embedding_and_usage, text)
