import platform
import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union
from sentence_transformers import SentenceTransformer

from agno.embedder.base import Embedder
from agno.utils.log import logger


@dataclass
class SentenceTransformerEmbedder(Embedder):
    id: str = "sentence-transformers/all-MiniLM-L6-v2"
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
