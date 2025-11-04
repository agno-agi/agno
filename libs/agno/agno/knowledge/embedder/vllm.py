import asyncio
from dataclasses import dataclass
from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agno.knowledge.embedder.base import Embedder
from agno.utils.log import logger

try:
    from vllm import LLM  # type: ignore
    from vllm.outputs import EmbeddingRequestOutput  # type: ignore
except ImportError:
    raise ImportError("`vllm` not installed. Please install using `pip install vllm`.")

if TYPE_CHECKING:
    from openai import AsyncOpenAI
    from openai import OpenAI as OpenAIClient
    from openai.types.create_embedding_response import CreateEmbeddingResponse


@dataclass
class VLLMEmbedder(Embedder):
    """
    VLLM Embedder supporting both local and remote deployment modes.

    Local Mode (default):
        - Loads model locally and runs inference on your GPU/CPU
        - No API key required
        - Example: VLLMEmbedder(id="intfloat/e5-mistral-7b-instruct")

    Remote Mode:
        - Connects to a remote vLLM server via OpenAI-compatible API
        - Uses OpenAI SDK to communicate with vLLM's OpenAI-compatible endpoint
        - Requires base_url and optionally api_key
        - Example: VLLMEmbedder(base_url="http://localhost:8000/v1", api_key="your-key")
        - Ref: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html
    """

    id: str = "sentence-transformers/all-MiniLM-L6-v2"
    dimensions: int = 4096
    # Local mode parameters
    enforce_eager: bool = True
    vllm_kwargs: Optional[Dict[str, Any]] = None
    vllm_client: Optional[LLM] = None
    # Remote mode parameters
    api_key: Optional[str] = getenv("VLLM_API_KEY")
    base_url: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None
    remote_client: Optional["OpenAIClient"] = None  # OpenAI-compatible client for vLLM server
    async_remote_client: Optional["AsyncOpenAI"] = None  # Async OpenAI-compatible client for vLLM server

    @property
    def is_remote(self) -> bool:
        """Determine if we should use remote mode."""
        return self.base_url is not None

    def _get_vllm_client(self) -> LLM:
        """Get local VLLM client."""
        if self.vllm_client:
            return self.vllm_client

        _vllm_params: Dict[str, Any] = {
            "model": self.id,
            "task": "embed",
            "enforce_eager": self.enforce_eager,
        }
        if self.vllm_kwargs:
            _vllm_params.update(self.vllm_kwargs)
        self.vllm_client = LLM(**_vllm_params)
        return self.vllm_client

    def _get_remote_client(self) -> "OpenAIClient":
        """Get OpenAI-compatible client for remote vLLM server."""
        if self.remote_client:
            return self.remote_client

        try:
            from openai import OpenAI as OpenAIClient
        except ImportError:
            raise ImportError("`openai` package required for remote vLLM mode. ")

        _client_params: Dict[str, Any] = {
            "api_key": self.api_key or "EMPTY",  # VLLM can run without API key
            "base_url": self.base_url,
        }
        if self.client_params:
            _client_params.update(self.client_params)
        self.remote_client = OpenAIClient(**_client_params)
        return self.remote_client

    def _get_async_remote_client(self) -> "AsyncOpenAI":
        """Get async OpenAI-compatible client for remote vLLM server."""
        if self.async_remote_client:
            return self.async_remote_client

        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("`openai` package required for remote vLLM mode. ")

        _client_params: Dict[str, Any] = {
            "api_key": self.api_key or "EMPTY",
            "base_url": self.base_url,
        }
        if self.client_params:
            _client_params.update(self.client_params)
        self.async_remote_client = AsyncOpenAI(**_client_params)
        return self.async_remote_client

    def _create_embedding_local(self, text: str) -> Optional[EmbeddingRequestOutput]:
        """Create embedding using local VLLM."""
        try:
            outputs = self._get_vllm_client().embed([text])
            return outputs[0] if outputs else None
        except Exception as e:
            logger.warning(f"Error creating local embedding: {e}")
            return None

    def _create_embedding_remote(self, text: str) -> "CreateEmbeddingResponse":
        """Create embedding using remote vLLM server."""
        _request_params: Dict[str, Any] = {
            "input": text,
            "model": self.id,
        }
        if self.request_params:
            _request_params.update(self.request_params)
        return self._get_remote_client().embeddings.create(**_request_params)

    def get_embedding(self, text: str) -> List[float]:
        try:
            if self.is_remote:
                # Remote mode: OpenAI-compatible API
                response: "CreateEmbeddingResponse" = self._create_embedding_remote(text=text)
                return response.data[0].embedding
            else:
                # Local mode: Direct VLLM
                output = self._create_embedding_local(text=text)
                if output and hasattr(output, "outputs") and hasattr(output.outputs, "embedding"):
                    embedding = output.outputs.embedding
                    if len(embedding) != self.dimensions:
                        logger.warning(f"Expected embedding dimension {self.dimensions}, but got {len(embedding)}")
                    return embedding
                return []
        except Exception as e:
            logger.warning(f"Error extracting embedding: {e}")
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        if self.is_remote:
            try:
                response: "CreateEmbeddingResponse" = self._create_embedding_remote(text=text)
                embedding = response.data[0].embedding
                usage = response.usage
                if usage:
                    return embedding, usage.model_dump()
                return embedding, None
            except Exception as e:
                logger.warning(f"Error in remote embedding: {e}")
                return [], None
        else:
            embedding = self.get_embedding(text=text)
            # Local VLLM doesn't provide usage information
            return embedding, None

    async def async_get_embedding(self, text: str) -> List[float]:
        """Async version of get_embedding using thread executor for local mode."""
        if self.is_remote:
            # Remote mode: async client for vLLM server
            try:
                req: Dict[str, Any] = {
                    "input": text,
                    "model": self.id,
                }
                if self.request_params:
                    req.update(self.request_params)
                response: "CreateEmbeddingResponse" = await self._get_async_remote_client().embeddings.create(**req)
                return response.data[0].embedding
            except Exception as e:
                logger.warning(f"Error in async remote embedding: {e}")
                return []
        else:
            # Local mode: use thread executor for CPU-bound operations
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.get_embedding, text)

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Async version of get_embedding_and_usage using thread executor for local mode."""
        if self.is_remote:
            try:
                req: Dict[str, Any] = {
                    "input": text,
                    "model": self.id,
                }
                if self.request_params:
                    req.update(self.request_params)
                response: "CreateEmbeddingResponse" = await self._get_async_remote_client().embeddings.create(**req)
                embedding = response.data[0].embedding
                usage = response.usage
                return embedding, usage.model_dump() if usage else None
            except Exception as e:
                logger.warning(f"Error in async remote embedding: {e}")
                return [], None
        else:
            # Local mode: use thread executor for CPU-bound operations
            try:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, self.get_embedding_and_usage, text)
            except Exception as e:
                logger.warning(f"Error in async local embedding: {e}")
                return [], None

    async def async_get_embeddings_batch_and_usage(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        """
        Get embeddings and usage for multiple texts in batches (async version).

        Args:
            texts: List of text strings to embed

        Returns:
            Tuple of (List of embedding vectors, List of usage dictionaries)
        """
        all_embeddings = []
        all_usage = []
        logger.info(f"Getting embeddings for {len(texts)} texts in batches of {self.batch_size} (async)")

        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]

            try:
                if self.is_remote:
                    # Remote mode: use batch API
                    req: Dict[str, Any] = {
                        "input": batch_texts,
                        "model": self.id,
                    }
                    if self.request_params:
                        req.update(self.request_params)
                    response: "CreateEmbeddingResponse" = await self._get_async_remote_client().embeddings.create(**req)
                    batch_embeddings = [data.embedding for data in response.data]
                    all_embeddings.extend(batch_embeddings)

                    # For each embedding in the batch, add the same usage information
                    usage_dict = response.usage.model_dump() if response.usage else None
                    all_usage.extend([usage_dict] * len(batch_embeddings))
                else:
                    # Local mode: process individually using thread executor
                    for text in batch_texts:
                        embedding, usage = await self.async_get_embedding_and_usage(text)
                        all_embeddings.append(embedding)
                        all_usage.append(usage)

            except Exception as e:
                logger.warning(f"Error in async batch embedding: {e}")
                # Fallback: add empty results for failed batch
                for _ in batch_texts:
                    all_embeddings.append([])
                    all_usage.append(None)

        return all_embeddings, all_usage
