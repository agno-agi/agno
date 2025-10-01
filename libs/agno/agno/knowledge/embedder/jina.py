from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from typing_extensions import Literal

from agno.knowledge.embedder.base import Embedder
from agno.utils.log import logger

try:
    import requests
except ImportError:
    raise ImportError("`requests` not installed, use pip install requests")

try:
    import aiohttp
except ImportError:
    raise ImportError("`aiohttp` not installed, use pip install aiohttp")


@dataclass
class JinaEmbedder(Embedder):
    id: str = "jina-embeddings-v3"
    dimensions: int = 1024
    embedding_type: Literal["float", "base64", "int8"] = "float"
    late_chunking: bool = False
    user: Optional[str] = None
    api_key: Optional[str] = getenv("JINA_API_KEY")
    base_url: str = "https://api.jina.ai/v1/embeddings"
    headers: Optional[Dict[str, str]] = None
    request_params: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = None

    def _get_headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ValueError(
                "API key is required for Jina embedder. Set JINA_API_KEY environment variable or pass api_key parameter."
            )

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        if self.headers:
            headers.update(self.headers)
        return headers

    def _response(self, text: str) -> Dict[str, Any]:
        data = {
            "model": self.id,
            "late_chunking": self.late_chunking,
            "dimensions": self.dimensions,
            "embedding_type": self.embedding_type,
            "input": [text],  # Jina API expects a list
        }
        if self.user is not None:
            data["user"] = self.user
        if self.request_params:
            data.update(self.request_params)

        response = requests.post(self.base_url, headers=self._get_headers(), json=data, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_embedding(self, text: str) -> List[float]:
        try:
            result = self._response(text)
            return result["data"][0]["embedding"]
        except Exception as e:
            logger.warning(f"Failed to get embedding: {e}")
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        try:
            result = self._response(text)
            embedding = result["data"][0]["embedding"]
            usage = result.get("usage")
            return embedding, usage
        except Exception as e:
            logger.warning(f"Failed to get embedding and usage: {e}")
            return [], None

    async def _async_response(self, text: str) -> Dict[str, Any]:
        """Async version of _response using aiohttp."""
        data = {
            "model": self.id,
            "late_chunking": self.late_chunking,
            "dimensions": self.dimensions,
            "embedding_type": self.embedding_type,
            "input": [text],  # Jina API expects a list
        }
        if self.user is not None:
            data["user"] = self.user
        if self.request_params:
            data.update(self.request_params)

        timeout = aiohttp.ClientTimeout(total=self.timeout) if self.timeout else None

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.base_url, headers=self._get_headers(), json=data) as response:
                response.raise_for_status()
                return await response.json()

    async def async_get_embedding(self, text: str) -> List[float]:
        """Async version of get_embedding."""
        try:
            result = await self._async_response(text)
            return result["data"][0]["embedding"]
        except Exception as e:
            logger.warning(f"Failed to get embedding: {e}")
            return []

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Async version of get_embedding_and_usage."""
        try:
            result = await self._async_response(text)
            embedding = result["data"][0]["embedding"]
            usage = result.get("usage")
            return embedding, usage
        except Exception as e:
            logger.warning(f"Failed to get embedding and usage: {e}")
            return [], None

    async def _async_batch_response(self, texts: List[str]) -> Dict[str, Any]:
        """Async batch version of _response using aiohttp."""
        data = {
            "model": self.id,
            "late_chunking": self.late_chunking,
            "dimensions": self.dimensions,
            "embedding_type": self.embedding_type,
            "input": texts,  # Jina API expects a list of texts for batch processing
        }
        if self.user is not None:
            data["user"] = self.user
        if self.request_params:
            data.update(self.request_params)

        timeout = aiohttp.ClientTimeout(total=self.timeout) if self.timeout else None

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.base_url, headers=self._get_headers(), json=data) as response:
                response.raise_for_status()
                return await response.json()

    async def async_get_embeddings_batch_and_usage(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        """
        Get embeddings and usage for multiple texts in batches.

        Args:
            texts: List of text strings to embed

        Returns:
            Tuple of (List of embedding vectors, List of usage dictionaries)
        """
        all_embeddings = []
        all_usage = []
        logger.info(f"Getting embeddings and usage for {len(texts)} texts in batches of {self.batch_size}")

        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]

            try:
                result = await self._async_batch_response(batch_texts)
                batch_embeddings = [data["embedding"] for data in result["data"]]
                all_embeddings.extend(batch_embeddings)

                # For each embedding in the batch, add the same usage information
                usage_dict = result.get("usage")
                all_usage.extend([usage_dict] * len(batch_embeddings))
            except Exception as e:
                logger.warning(f"Error in async batch embedding: {e}")
                # Fallback to individual calls for this batch
                for text in batch_texts:
                    try:
                        embedding, usage = await self.async_get_embedding_and_usage(text)
                        all_embeddings.append(embedding)
                        all_usage.append(usage)
                    except Exception as e2:
                        logger.warning(f"Error in individual async embedding fallback: {e2}")
                        all_embeddings.append([])
                        all_usage.append(None)

        return all_embeddings, all_usage
