from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from agno.knowledge.embedder.base import (
    Embedder,
    aembed_texts_individually,
    pad_batch_embeddings,
    raise_embedding_error,
)
from agno.utils.log import log_info, log_warning

try:
    from mistralai.client import Mistral as MistralClient
    from mistralai.client.models import EmbeddingResponse
except ImportError:
    raise ImportError("`mistralai` not installed. Please install using `pip install mistralai`")


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
    mistral_client: Optional[MistralClient] = None

    @property
    def client(self) -> MistralClient:
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

        self.mistral_client = MistralClient(**_client_params)

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
        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="Mistral")

        # A 200 carrying no embedding is a valid provider response, not a failure (see
        # the note in GeminiEmbedder.get_embedding).
        if response.data and response.data[0].embedding:
            return response.data[0].embedding
        log_warning("No embeddings found in response")
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
            raise_embedding_error(e, model_id=self.id, provider="Mistral")

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

        except Exception as e:
            raise_embedding_error(e, model_id=self.id, provider="Mistral")

        # A 200 carrying no embedding is a valid provider response, not a failure (see
        # the note in GeminiEmbedder.get_embedding).
        if response.data and response.data[0].embedding:
            return response.data[0].embedding
        log_warning("No embeddings found in response")
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
            raise_embedding_error(e, model_id=self.id, provider="Mistral")

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

                # A batch that comes back short or empty is reported per text, not raised:
                # an empty embedding is a valid response, and the caller counts unembedded
                # chunks. Entries are kept in place (rather than filtered out) so a missing
                # embedding does not shift every later text onto the wrong vector.
                batch_embeddings = pad_batch_embeddings(
                    [data.embedding or [] for data in (response.data or [])], batch_texts, "Mistral"
                )
                if len(batch_embeddings) < len(batch_texts):
                    log_warning(f"Batch response returned {len(batch_embeddings)} of {len(batch_texts)} embeddings")
                    batch_embeddings.extend([[]] * (len(batch_texts) - len(batch_embeddings)))
                all_embeddings.extend(batch_embeddings)

                # Extract usage information
                usage_dict = response.usage.model_dump() if response.usage else None
                # Add same usage info for each embedding in the batch
                all_usage.extend([usage_dict] * len(batch_texts))

            except Exception as e:
                log_warning(f"Error in async batch embedding: {str(e)}")
                # Fall back to individual calls: a whole-batch failure is often transient
                # (or caused by a single bad text). Successes are kept so one bad chunk
                # does not discard the rest of the batch.
                batch_embeddings, batch_usage = await aembed_texts_individually(self, batch_texts)
                all_embeddings.extend(batch_embeddings)
                all_usage.extend(batch_usage)

        return all_embeddings, all_usage
