import base64
import io
from dataclasses import dataclass
from typing import List, Union

from agno.knowledge.embedder.sentence_transformer import SentenceTransformerEmbedder
from agno.utils.log import log_warning

try:
    from PIL import Image
except ImportError:
    raise ImportError("`Pillow` not installed, please run `pip install Pillow`")


@dataclass
class CLIPEmbedder(SentenceTransformerEmbedder):
    """Embedder for images and text using CLIP models via sentence-transformers.

    Handles both image content (base64-encoded) and text queries in the same vector space.
    """

    id: str = "clip-ViT-B-32"
    dimensions: int = 512

    def _is_base64_image(self, text: str) -> bool:
        """Check if the text is likely base64-encoded image data."""
        if len(text) < 100:
            return False
        try:
            decoded = base64.b64decode(text[:32], validate=True)
            # JPEG starts with FF D8, PNG starts with 89 50 4E 47
            return decoded[:2] in (b"\xff\xd8", b"\x89P") or decoded[:4] == b"\x89PNG"
        except Exception:
            return False

    def get_embedding(self, text: Union[str, List[str]]) -> List[float]:
        if self.sentence_transformer_client is None:
            raise RuntimeError("SentenceTransformer model not initialized")
        model = self.sentence_transformer_client

        if isinstance(text, str) and self._is_base64_image(text):
            image_bytes = base64.b64decode(text)
            image = Image.open(io.BytesIO(image_bytes))
            embedding = model.encode(image, normalize_embeddings=self.normalize_embeddings)
        else:
            embedding = model.encode(text, prompt=self.prompt, normalize_embeddings=self.normalize_embeddings)

        try:
            import numpy as np

            if isinstance(embedding, np.ndarray):
                return embedding.tolist()
            return embedding  # type: ignore
        except Exception as e:
            log_warning(f"Failed to get embedding: {str(e)}")
            return []
