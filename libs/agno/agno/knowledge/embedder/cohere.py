import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from agno.knowledge.embedder.base import Embedder
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from cohere import AsyncClient as AsyncCohereClient
    from cohere import Client as CohereClient
    from cohere.types.embed_response import EmbeddingsByTypeEmbedResponse, EmbeddingsFloatsEmbedResponse
except ImportError:
    raise ImportError("`cohere` not installed. Please install using `pip install cohere`.")


@dataclass
class CohereEmbedder(Embedder):
    id: str = "embed-english-v3.0"
    input_type: str = "search_query"
    embedding_types: Optional[List[str]] = None
    api_key: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None
    cohere_client: Optional[CohereClient] = None
    async_client: Optional[AsyncCohereClient] = None
    exponential_backoff: bool = False  # Enable exponential backoff on rate limits

    @property
    def client(self) -> CohereClient:
        if self.cohere_client:
            return self.cohere_client
        client_params: Dict[str, Any] = {}
        if self.api_key:
            client_params["api_key"] = self.api_key
        if self.client_params:
            client_params.update(self.client_params)
        self.cohere_client = CohereClient(**client_params)
        return self.cohere_client

    @property
    def aclient(self) -> AsyncCohereClient:
        """Lazy init for Cohere async client."""
        if self.async_client:
            return self.async_client
        params: Dict[str, Any] = {}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.client_params:
            params.update(self.client_params)
        self.async_client = AsyncCohereClient(**params)
        return self.async_client

    def response(self, text: str) -> Union[EmbeddingsFloatsEmbedResponse, EmbeddingsByTypeEmbedResponse]:
        request_params: Dict[str, Any] = {}

        if self.id:
            request_params["model"] = self.id
        if self.input_type:
            request_params["input_type"] = self.input_type
        if self.embedding_types:
            request_params["embedding_types"] = self.embedding_types
        if self.request_params:
            request_params.update(self.request_params)
        return self.client.embed(texts=[text], **request_params)

    def _get_batch_request_params(self) -> Dict[str, Any]:
        """Get request parameters for batch embedding calls."""
        request_params: Dict[str, Any] = {}

        if self.id:
            request_params["model"] = self.id
        if self.input_type:
            request_params["input_type"] = self.input_type
        if self.embedding_types:
            request_params["embedding_types"] = self.embedding_types
        if self.request_params:
            request_params.update(self.request_params)

        return request_params

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if the error is a rate limiting error."""
        if hasattr(error, "status_code") and error.status_code == 429:
            return True
        error_str = str(error).lower()
        return any(
            phrase in error_str
            for phrase in ["rate limit", "too many requests", "429", "trial key", "api calls / minute"]
        )

    def _exponential_backoff_sleep(self, attempt: int, base_delay: float = 1.0) -> None:
        """Sleep with exponential backoff."""
        delay = base_delay * (2**attempt) + (time.time() % 1)  # Add jitter
        log_debug(f"Rate limited, waiting {delay:.2f} seconds before retry (attempt {attempt + 1})")
        time.sleep(delay)

    async def _async_rate_limit_backoff_sleep(self, attempt: int) -> None:
        """Async version of rate-limit-aware backoff for APIs with per-minute limits."""
        import asyncio

        # For 40 req/min APIs like Cohere Trial, we need longer waits
        if attempt == 0:
            delay = 15.0  # Wait 15 seconds (1/4 of minute window)
        elif attempt == 1:
            delay = 30.0  # Wait 30 seconds (1/2 of minute window)
        else:
            delay = 60.0  # Wait full minute for window reset

        # Add small jitter
        delay += time.time() % 3

        log_debug(
            f"Async rate limit backoff, waiting {delay:.1f} seconds for rate limit window reset (attempt {attempt + 1})"
        )
        await asyncio.sleep(delay)

    async def _async_batch_with_retry(
        self, texts: List[str], max_retries: int = 3
    ) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        """Execute async batch embedding with rate-limit-aware backoff for rate limiting."""

        log_debug(f"Starting async batch retry for {len(texts)} texts with max_retries={max_retries}")

        for attempt in range(max_retries + 1):
            try:
                request_params = self._get_batch_request_params()
                response: Union[
                    EmbeddingsFloatsEmbedResponse, EmbeddingsByTypeEmbedResponse
                ] = await self.aclient.embed(texts=texts, **request_params)

                # Extract embeddings from response
                if isinstance(response, EmbeddingsFloatsEmbedResponse):
                    batch_embeddings = response.embeddings
                elif isinstance(response, EmbeddingsByTypeEmbedResponse):
                    batch_embeddings = response.embeddings.float_ if response.embeddings.float_ else []
                else:
                    log_warning("No embeddings found in response")
                    batch_embeddings = []

                # Extract usage information
                usage = response.meta.billed_units if response.meta else None
                usage_dict = usage.model_dump() if usage else None
                all_usage = [usage_dict] * len(batch_embeddings)

                log_debug(f"Async batch embedding succeeded on attempt {attempt + 1}")
                return batch_embeddings, all_usage

            except Exception as e:
                if self._is_rate_limit_error(e):
                    if not self.exponential_backoff:
                        log_warning(
                            "Rate limit detected. To enable automatic backoff retry, set enable_backoff=True when creating the embedder."
                        )
                        raise e

                    log_info(f"Async rate limit detected on attempt {attempt + 1}")
                    if attempt < max_retries:
                        await self._async_rate_limit_backoff_sleep(attempt)
                        continue
                    else:
                        log_warning(f"Async max retries ({max_retries}) reached for rate limiting")
                        raise e
                else:
                    log_debug(f"Async non-rate-limit error on attempt {attempt + 1}: {e}")
                    raise e

        # This should never be reached, but just in case
        log_error("Could not create embeddings. End of retry loop reached.")
        return [], []

    def get_embedding(self, text: str) -> List[float]:
        response: Union[EmbeddingsFloatsEmbedResponse, EmbeddingsByTypeEmbedResponse] = self.response(text=text)
        try:
            if isinstance(response, EmbeddingsFloatsEmbedResponse):
                return response.embeddings[0]
            elif isinstance(response, EmbeddingsByTypeEmbedResponse):
                return response.embeddings.float_[0] if response.embeddings.float_ else []
            else:
                log_warning("No embeddings found")
                return []
        except Exception as e:
            log_warning(e)
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        response: Union[EmbeddingsFloatsEmbedResponse, EmbeddingsByTypeEmbedResponse] = self.response(text=text)

        embedding: List[float] = []
        if isinstance(response, EmbeddingsFloatsEmbedResponse):
            embedding = response.embeddings[0]
        elif isinstance(response, EmbeddingsByTypeEmbedResponse):
            embedding = response.embeddings.float_[0] if response.embeddings.float_ else []

        usage = response.meta.billed_units if response.meta else None
        if usage:
            return embedding, usage.model_dump()
        return embedding, None

    async def async_get_embedding(self, text: str) -> List[float]:
        request_params: Dict[str, Any] = {}

        if self.id:
            request_params["model"] = self.id
        if self.input_type:
            request_params["input_type"] = self.input_type
        if self.embedding_types:
            request_params["embedding_types"] = self.embedding_types
        if self.request_params:
            request_params.update(self.request_params)

        try:
            response: Union[EmbeddingsFloatsEmbedResponse, EmbeddingsByTypeEmbedResponse] = await self.aclient.embed(
                texts=[text], **request_params
            )
            if isinstance(response, EmbeddingsFloatsEmbedResponse):
                return response.embeddings[0]
            elif isinstance(response, EmbeddingsByTypeEmbedResponse):
                return response.embeddings.float_[0] if response.embeddings.float_ else []
            else:
                log_warning("No embeddings found")
                return []
        except Exception as e:
            log_warning(e)
            return []

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        request_params: Dict[str, Any] = {}

        if self.id:
            request_params["model"] = self.id
        if self.input_type:
            request_params["input_type"] = self.input_type
        if self.embedding_types:
            request_params["embedding_types"] = self.embedding_types
        if self.request_params:
            request_params.update(self.request_params)

        response: Union[EmbeddingsFloatsEmbedResponse, EmbeddingsByTypeEmbedResponse] = await self.aclient.embed(
            texts=[text], **request_params
        )

        embedding: List[float] = []
        if isinstance(response, EmbeddingsFloatsEmbedResponse):
            embedding = response.embeddings[0]
        elif isinstance(response, EmbeddingsByTypeEmbedResponse):
            embedding = response.embeddings.float_[0] if response.embeddings.float_ else []

        usage = response.meta.billed_units if response.meta else None
        if usage:
            return embedding, usage.model_dump()
        return embedding, None

    async def async_get_embeddings_batch_and_usage(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        """
                Get embeddings and usage for multiple texts in batches (async version).

                Args:
                    texts: List of text strings to embed

                Returns:
        s, List of usage dictionaries)
        """
        all_embeddings = []
        all_usage = []
        log_info(f"Getting embeddings and usage for {len(texts)} texts in batches of {self.batch_size} (async)")

        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i : i + self.batch_size]

            try:
                # Use retry logic for batch processing
                batch_embeddings, batch_usage = await self._async_batch_with_retry(batch_texts)
                all_embeddings.extend(batch_embeddings)
                all_usage.extend(batch_usage)

            except Exception as e:
                log_warning(f"Async batch embedding failed after retries: {e}")

                # Check if this is a rate limit error and backoff is disabled
                if self._is_rate_limit_error(e) and not self.exponential_backoff:
                    log_warning("Rate limit hit and backoff is disabled. Failing immediately.")
                    raise e

                # Only fall back to individual calls for non-rate-limit errors
                # For rate limit errors, we should reduce batch size instead
                if self._is_rate_limit_error(e):
                    log_warning("Rate limit hit even after retries. Consider reducing batch_size or upgrading API key.")
                    # Try with smaller batch size
                    if len(batch_texts) > 1:
                        smaller_batch_size = max(1, len(batch_texts) // 2)
                        log_info(f"Retrying with smaller batch size: {smaller_batch_size}")
                        for j in range(0, len(batch_texts), smaller_batch_size):
                            small_batch = batch_texts[j : j + smaller_batch_size]
                            try:
                                small_embeddings, small_usage = await self._async_batch_with_retry(small_batch)
                                all_embeddings.extend(small_embeddings)
                                all_usage.extend(small_usage)
                            except Exception as e3:
                                log_error(f"Failed even with reduced batch size: {e3}")
                                # Fall back to empty results for this batch
                                all_embeddings.extend([[] for _ in small_batch])
                                all_usage.extend([None for _ in small_batch])
                    else:
                        # Single item already failed, add empty result
                        log_debug("Single item failed, adding empty result")
                        all_embeddings.append([])
                        all_usage.append(None)
                else:
                    # For non-rate-limit errors, fall back to individual calls
                    log_debug("Non-rate-limit error, falling back to individual calls")
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
