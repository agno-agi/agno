from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from agno.knowledge.embedder.base import Embedder
from agno.utils.log import log_error, log_info, log_warning

try:
    from mistralai import Mistral  # type: ignore
    from mistralai.models.embeddingresponse import EmbeddingResponse  # type: ignore
except ImportError:
    log_error("`mistralai` not installed")
    raise


@dataclass
class MistralEmbedder(Embedder):
    id: str = "mistral-embed"
    dimensions: int = 1024
    # -*- Request parameters
    request_params: Optional[Dict[str, Any]] = None
    # -*- Client parameters
    api_key: Optional[str] = getenv("MISTRAL_API_KEY")
    endpoint: Optional[str] = None
    max_retries: Optional[int] = None
    timeout: Optional[int] = None
    client_params: Optional[Dict[str, Any]] = None
    # -*- Provide the Mistral Client manually
    mistral_client: Optional[Mistral] = None

    @property
    def client(self) -> Mistral:
        if self.mistral_client:
            return self.mistral_client

        _client_params: Dict[str, Any] = {
            "api_key": self.api_key,
            "endpoint": self.endpoint,
            "max_retries": self.max_retries,
            "timeout_ms": self.timeout * 1000 if self.timeout else None,
        }
        _client_params = {k: v for k, v in _client_params.items() if v is not None}

        if self.client_params:
            _client_params.update(self.client_params)

        self.mistral_client = Mistral(**_client_params)

        return self.mistral_client

    def _response(self, text: str) -> EmbeddingResponse:
        _request_params: Dict[str, Any] = {
            "inputs": [text],  # Mistral API expects a list
            "model": self.id,
        }
        if self.request_params:
            _request_params.update(self.request_params)
        response = self.client.embeddings.create(**_request_params)
        if response is None:
            raise ValueError("Failed to get embedding response")
        return response

    def get_embedding(self, text: str) -> List[float]:
        try:
            response: EmbeddingResponse = self._response(text=text)
            if response.data and response.data[0].embedding:
                return response.data[0].embedding
            return []
        except Exception as e:
            log_warning(f"Error getting embedding: {e}")
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Dict[str, Any]]:
        try:
            response: EmbeddingResponse = self._response(text=text)
            embedding: List[float] = (
                response.data[0].embedding if (response.data and response.data[0].embedding) else []
            )
            usage: Dict[str, Any] = response.usage.model_dump() if response.usage else {}
            return embedding, usage
        except Exception as e:
            log_warning(f"Error getting embedding and usage: {e}")
            return [], {}

    async def async_get_embedding(self, text: str) -> List[float]:
        """Async version of get_embedding."""
        try:
            # Check if the client has an async version of embeddings.create
            if hasattr(self.client.embeddings, "create_async"):
                response: EmbeddingResponse = await self.client.embeddings.create_async(
                    inputs=[text], model=self.id, **self.request_params if self.request_params else {}
                )
            else:
                # Fallback to running sync method in thread executor
                import asyncio

                loop = asyncio.get_running_loop()
                response: EmbeddingResponse = await loop.run_in_executor(  # type: ignore
                    None,
                    lambda: self.client.embeddings.create(
                        inputs=[text], model=self.id, **self.request_params if self.request_params else {}
                    ),
                )

            if response.data and response.data[0].embedding:
                return response.data[0].embedding
            return []
        except Exception as e:
            log_warning(f"Error getting embedding: {e}")
            return []

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Dict[str, Any]]:
        """Async version of get_embedding_and_usage."""
        try:
            # Check if the client has an async version of embeddings.create
            if hasattr(self.client.embeddings, "create_async"):
                response: EmbeddingResponse = await self.client.embeddings.create_async(
                    inputs=[text], model=self.id, **self.request_params if self.request_params else {}
                )
            else:
                # Fallback to running sync method in thread executor
                import asyncio

                loop = asyncio.get_running_loop()
                response: EmbeddingResponse = await loop.run_in_executor(  # type: ignore
                    None,
                    lambda: self.client.embeddings.create(
                        inputs=[text], model=self.id, **self.request_params if self.request_params else {}
                    ),
                )

            embedding: List[float] = (
                response.data[0].embedding if (response.data and response.data[0].embedding) else []
            )
            usage: Dict[str, Any] = response.usage.model_dump() if response.usage else {}
            return embedding, usage
        except Exception as e:
            log_warning(f"Error getting embedding and usage: {e}")
            return [], {}

    async def async_get_embeddings_batch_and_usage(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], List[Optional[Dict[str, Any]]]]:
        """
        Get embeddings and usage for multiple texts in batches.

        Args:
            texts: List of text strings to embed

        Returns:
            Tuple of (List of embedding vectors, List of usage dictionaries)
        """
        all_embeddings = []
        all_usage = []
        log_info(f"Getting embeddings and usage for {len(texts)} texts in batches of {self.batch_size}")

        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]

            _request_params: Dict[str, Any] = {
                "inputs": batch_texts,  # Mistral API expects a list for batch processing
                "model": self.id,
            }
            if self.request_params:
                _request_params.update(self.request_params)

            try:
                # Check if the client has an async version of embeddings.create
                if hasattr(self.client.embeddings, "create_async"):
                    response: EmbeddingResponse = await self.client.embeddings.create_async(**_request_params)
                else:
                    # Fallback to running sync method in thread executor
                    import asyncio

                    loop = asyncio.get_running_loop()
                    response: EmbeddingResponse = await loop.run_in_executor(  # type: ignore
                        None, lambda: self.client.embeddings.create(**_request_params)
                    )

                # Extract embeddings from batch response
                if response.data:
                    batch_embeddings = [data.embedding for data in response.data if data.embedding]
                    all_embeddings.extend(batch_embeddings)
                else:
                    # If no embeddings, add empty lists for each text in batch
                    all_embeddings.extend([[] for _ in batch_texts])

                # Extract usage information
                usage_dict = response.usage.model_dump() if response.usage else None
                # Add same usage info for each embedding in the batch
                all_usage.extend([usage_dict] * len(batch_texts))

            except Exception as e:
                log_warning(f"Error in async batch embedding: {e}")
                # Fallback to individual calls for this batch
                for text in batch_texts:
                    try:
                        embedding, usage = await self.async_get_embedding_and_usage(text)
                        all_embeddings.append(embedding)
                        all_usage.append(usage)
                    except Exception as e2:
                        log_warning(f"Error in individual async embedding fallback: {e2}")
                        all_embeddings.append([])
                        all_usage.append(None)

        return all_embeddings, all_usage
