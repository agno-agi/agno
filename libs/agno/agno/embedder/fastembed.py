from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    from fastembed import TextEmbedding  # type: ignore

except ImportError:
    raise ImportError("fastembed not installed, use pip install fastembed")


@dataclass
class FastEmbedEmbedder(Embedder):
    """Using BAAI/bge-small-en-v1.5 model, more models available: https://qdrant.github.io/fastembed/examples/Supported_Models/"""

    id: str = "BAAI/bge-small-en-v1.5"
    dimensions: int = 384

    def get_embedding(self, text: str) -> List[float]:
        model = TextEmbedding(model_name=self.id)
        embeddings = model.embed(text)
        embedding_list = list(embeddings)[0]

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
