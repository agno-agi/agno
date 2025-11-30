from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agno.knowledge.embedder.base import Embedder
from agno.utils.log import logger

try:
    import litellm
except ImportError:
    raise ImportError("`litellm` not installed. Please install it via `pip install litellm`.")


@dataclass
class LiteLLMEmbedder(Embedder):
    """Embedder implementation backed by LiteLLM unified interface.

    This enables using any embedding provider supported by LiteLLM with a single
    configuration surface. You can supply any provider specific model string that
    LiteLLM understands, for example:
        - openai/text-embedding-3-small
        - openai/text-embedding-3-large
        - cohere/embed-english-v3.0
        - jina/jina-embeddings-v2-base-en

    Args:
        id: The LiteLLM model identifier.
        api_key: Optional API key (falls back to environment variables recognized by LiteLLM).
        api_base: Optional custom base URL.
        request_params: Extra parameters forwarded to litellm.embedding / aembedding.
        enable_batch: Whether batch embedding helper should be used.
        batch_size: Batch size for async batch helper.
    """

    id: str = "openai/text-embedding-3-small"
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None
    enable_batch: bool = False
    batch_size: int = 100

    def _build_request(self, texts: List[str]) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "model": self.id,
            "input": texts,
        }
        if self.api_key is not None:
            params["api_key"] = self.api_key
        if self.api_base is not None:
            params["api_base"] = self.api_base
        if self.request_params:
            params.update(self.request_params)
        return params

    @staticmethod
    def _extract_embedding(response: Any) -> List[float]:
        """Extract first embedding from LiteLLM embedding response."""
        try:
            if hasattr(response, 'data') and response.data:
                return response.data[0].embedding
            return []
        except Exception as e:
            logger.warning(f"Failed to extract embedding: {e}")
            return []

    @staticmethod
    def _extract_usage(response: Any) -> Optional[Dict[str, Any]]:
        """Extract usage information from LiteLLM response."""
        try:
            if hasattr(response, 'usage') and response.usage:
                return response.usage.model_dump()
            return None
        except Exception as e:
            logger.warning(f"Failed to extract usage: {e}")
            return None

    def get_embedding(self, text: str) -> List[float]:
        try:
            request = self._build_request([text])
            response = litellm.embedding(**request)
            return self._extract_embedding(response)
        except Exception as e:
            logger.warning(f"LiteLLM embedding error: {e}")
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        try:
            request = self._build_request([text])
            response = litellm.embedding(**request)
            embedding = self._extract_embedding(response)
            usage = self._extract_usage(response)
            return embedding, usage
        except Exception as e:
            logger.warning(f"LiteLLM embedding error: {e}")
            return [], None

    async def async_get_embedding(self, text: str) -> List[float]:
        try:
            request = self._build_request([text])
            response = await litellm.aembedding(**request)
            return self._extract_embedding(response)
        except Exception as e:
            logger.warning(f"LiteLLM async embedding error: {e}")
            return []

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        try:
            request = self._build_request([text])
            response = await litellm.aembedding(**request)
            embedding = self._extract_embedding(response)
            usage = self._extract_usage(response)
            return embedding, usage
        except Exception as e:
            logger.warning(f"LiteLLM async embedding error: {e}")
            return [], None

    async def async_get_embeddings_batch_and_usage(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        """Batch async embedding helper using LiteLLM.

        Falls back to individual calls on failure to maximize resilience.
        """
        all_embeddings: List[List[float]] = []
        all_usage: List[Optional[Dict]] = []

        logger.info(
            f"Getting embeddings and usage for {len(texts)} texts in batches of {self.batch_size} (LiteLLM async)"
        )
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            try:
                request = self._build_request(batch)
                response = await litellm.aembedding(**request)
                embeddings: List[List[float]] = []
                if hasattr(response, 'data') and response.data:
                    for item in response.data:
                        embeddings.append(item.embedding)
                
                usage = self._extract_usage(response)
                all_embeddings.extend(embeddings)
                all_usage.extend([usage] * len(embeddings))
            except Exception as e:
                logger.warning(f"LiteLLM batch embedding error: {e} - falling back to per item")
                for t in batch:
                    emb, usage = await self.async_get_embedding_and_usage(t)
                    all_embeddings.append(emb)
                    all_usage.append(usage)
        return all_embeddings, all_usage
