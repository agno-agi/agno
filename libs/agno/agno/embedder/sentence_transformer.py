import platform
import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from agno.embedder.base import Embedder
from agno.utils.log import logger

try:
    from sentence_transformers import SentenceTransformer

    if platform.system() == "Windows":
        import numpy as np
except ImportError:
    raise ImportError("`sentence-transformers` not installed, please run `pip install sentence-transformers`")

@dataclass
class SentenceTransformerEmbedder(Embedder):
    id: str = "sentence-transformers/all-MiniLM-L6-v2"
    dimensions: int = 384
    sentence_transformer_client: Optional[SentenceTransformer] = None

    def get_embedding(self, text: Union[str, List[str]]) -> List[float]:
        model = SentenceTransformer(model_name_or_path=self.id)
        embedding = model.encode(text)
        try:
            return embedding  # type: ignore
        except Exception as e:
            logger.warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        return self.get_embedding(text=text), None
