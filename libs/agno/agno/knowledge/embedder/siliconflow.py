import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from agno.exceptions import AgnoError
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.siliconflow import (
    DEFAULT_SILICONFLOW_BASE_URL,
    get_malformed_siliconflow_response_error,
    get_siliconflow_headers,
    get_siliconflow_request_error,
    get_siliconflow_trace_id,
    get_siliconflow_url,
    raise_for_siliconflow_status,
)
from agno.utils.http import get_default_async_client, get_default_sync_client

DEFAULT_SILICONFLOW_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_SILICONFLOW_EMBEDDING_DIMENSIONS = 1024
MAX_SILICONFLOW_BATCH_SIZE = 32


@dataclass
class SiliconflowEmbedder(Embedder):
    """Embed text with Siliconflow's embeddings API.

    The default ``BAAI/bge-m3`` model produces 1024-dimensional vectors. A
    custom model requires an explicit ``dimensions`` value because Agno vector
    databases need the dimension before the first API request.
    """

    id: str = DEFAULT_SILICONFLOW_EMBEDDING_MODEL
    dimensions: Optional[int] = None
    enable_batch: bool = True
    batch_size: int = MAX_SILICONFLOW_BATCH_SIZE
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: str = DEFAULT_SILICONFLOW_BASE_URL
    timeout: float = 30.0
    send_dimensions: Optional[bool] = None
    request_params: Optional[Dict[str, Any]] = None
    extra_headers: Optional[Dict[str, str]] = None
    http_client: Optional[httpx.Client] = field(default=None, repr=False)
    async_http_client: Optional[httpx.AsyncClient] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must not be empty")
        if self.dimensions is None:
            if self.id != DEFAULT_SILICONFLOW_EMBEDDING_MODEL:
                raise ValueError("dimensions must be provided when using a custom Siliconflow embedding model")
            self.dimensions = DEFAULT_SILICONFLOW_EMBEDDING_DIMENSIONS
        if isinstance(self.dimensions, bool) or not isinstance(self.dimensions, int) or self.dimensions <= 0:
            raise ValueError("dimensions must be a positive integer")
        if isinstance(self.batch_size, bool) or not isinstance(self.batch_size, int):
            raise ValueError("batch_size must be an integer")
        if not 1 <= self.batch_size <= MAX_SILICONFLOW_BATCH_SIZE:
            raise ValueError(f"batch_size must be between 1 and {MAX_SILICONFLOW_BATCH_SIZE}")
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)) or self.timeout <= 0:
            raise ValueError("timeout must be a positive number")

    @property
    def client(self) -> httpx.Client:
        return self.http_client or get_default_sync_client()

    @property
    def aclient(self) -> httpx.AsyncClient:
        return self.async_http_client or get_default_async_client()

    @property
    def endpoint(self) -> str:
        return get_siliconflow_url(self.base_url, "/embeddings")

    def _should_send_dimensions(self) -> bool:
        if self.send_dimensions is not None:
            return self.send_dimensions
        return self.id.startswith("Qwen/Qwen3-Embedding-")

    def _build_payload(self, inputs: Union[str, List[str]]) -> Dict[str, Any]:
        payload = dict(self.request_params or {})
        payload.update(
            {
                "model": self.id,
                "input": inputs,
                "encoding_format": "float",
            }
        )
        if self._should_send_dimensions():
            payload["dimensions"] = self.dimensions
        else:
            payload.pop("dimensions", None)
        return payload

    @staticmethod
    def _validate_text(text: str) -> None:
        if not isinstance(text, str) or not text:
            raise ValueError("text must be a non-empty string")

    @classmethod
    def _validate_texts(cls, texts: List[str]) -> None:
        if not isinstance(texts, list):
            raise ValueError("texts must be a list")
        for text in texts:
            cls._validate_text(text)

    def _parse_response(
        self, response_body: Any, expected_count: int, trace_id: Optional[str]
    ) -> Tuple[List[List[float]], Optional[Dict[str, Any]]]:
        if not isinstance(response_body, dict) or not isinstance(response_body.get("data"), list):
            raise get_malformed_siliconflow_response_error("data must be a list", self.id, trace_id)

        data = response_body["data"]
        if len(data) != expected_count:
            raise get_malformed_siliconflow_response_error(
                f"expected {expected_count} embeddings, received {len(data)}", self.id, trace_id
            )

        embeddings_by_index: Dict[int, List[float]] = {}
        for item in data:
            if not isinstance(item, dict):
                raise get_malformed_siliconflow_response_error("each data item must be an object", self.id, trace_id)

            index = item.get("index")
            embedding = item.get("embedding")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < expected_count:
                raise get_malformed_siliconflow_response_error("embedding index is invalid", self.id, trace_id)
            if index in embeddings_by_index:
                raise get_malformed_siliconflow_response_error("embedding indices must be unique", self.id, trace_id)
            if not isinstance(embedding, list) or len(embedding) != self.dimensions:
                raise get_malformed_siliconflow_response_error(
                    f"embedding at index {index} must contain {self.dimensions} values", self.id, trace_id
                )

            parsed_embedding: List[float] = []
            for value in embedding:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise get_malformed_siliconflow_response_error(
                        f"embedding at index {index} must contain only finite numbers", self.id, trace_id
                    )
                parsed_embedding.append(float(value))
            embeddings_by_index[index] = parsed_embedding

        expected_indices = set(range(expected_count))
        if set(embeddings_by_index) != expected_indices:
            raise get_malformed_siliconflow_response_error("embedding indices must be complete", self.id, trace_id)

        usage = response_body.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise get_malformed_siliconflow_response_error("usage must be an object", self.id, trace_id)

        return [embeddings_by_index[index] for index in range(expected_count)], usage

    def _request(
        self, inputs: Union[str, List[str]], expected_count: int
    ) -> Tuple[List[List[float]], Optional[Dict[str, Any]]]:
        try:
            response = self.client.post(
                self.endpoint,
                headers=get_siliconflow_headers(self.api_key, self.extra_headers),
                json=self._build_payload(inputs),
                timeout=self.timeout,
            )
            raise_for_siliconflow_status(response, self.id)
            trace_id = get_siliconflow_trace_id(response)
            try:
                response_body = response.json()
            except ValueError as error:
                raise get_malformed_siliconflow_response_error(
                    "response is not valid JSON", self.id, trace_id
                ) from error
            return self._parse_response(response_body, expected_count, trace_id)
        except AgnoError:
            raise
        except httpx.RequestError as error:
            raise get_siliconflow_request_error(error, self.id) from error
        except Exception as error:
            raise get_siliconflow_request_error(error, self.id) from error

    async def _async_request(
        self, inputs: Union[str, List[str]], expected_count: int
    ) -> Tuple[List[List[float]], Optional[Dict[str, Any]]]:
        try:
            response = await self.aclient.post(
                self.endpoint,
                headers=get_siliconflow_headers(self.api_key, self.extra_headers),
                json=self._build_payload(inputs),
                timeout=self.timeout,
            )
            raise_for_siliconflow_status(response, self.id)
            trace_id = get_siliconflow_trace_id(response)
            try:
                response_body = response.json()
            except ValueError as error:
                raise get_malformed_siliconflow_response_error(
                    "response is not valid JSON", self.id, trace_id
                ) from error
            return self._parse_response(response_body, expected_count, trace_id)
        except AgnoError:
            raise
        except httpx.RequestError as error:
            raise get_siliconflow_request_error(error, self.id) from error
        except Exception as error:
            raise get_siliconflow_request_error(error, self.id) from error

    def get_embedding(self, text: str) -> List[float]:
        self._validate_text(text)
        embeddings, _ = self._request(text, expected_count=1)
        return embeddings[0]

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        self._validate_text(text)
        embeddings, usage = self._request(text, expected_count=1)
        return embeddings[0], usage

    async def async_get_embedding(self, text: str) -> List[float]:
        self._validate_text(text)
        embeddings, _ = await self._async_request(text, expected_count=1)
        return embeddings[0]

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        self._validate_text(text)
        embeddings, usage = await self._async_request(text, expected_count=1)
        return embeddings[0], usage

    def get_embeddings_batch_and_usage(self, texts: List[str]) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        """Embed texts in batches and repeat each batch-level usage record per result."""
        self._validate_texts(texts)
        all_embeddings: List[List[float]] = []
        all_usage: List[Optional[Dict]] = []
        for index in range(0, len(texts), self.batch_size):
            batch = texts[index : index + self.batch_size]
            embeddings, usage = self._request(batch, expected_count=len(batch))
            all_embeddings.extend(embeddings)
            all_usage.extend([dict(usage) if usage is not None else None for _ in embeddings])
        return all_embeddings, all_usage

    async def async_get_embeddings_batch_and_usage(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        """Asynchronously embed texts and repeat each batch-level usage record per result."""
        self._validate_texts(texts)
        all_embeddings: List[List[float]] = []
        all_usage: List[Optional[Dict]] = []
        for index in range(0, len(texts), self.batch_size):
            batch = texts[index : index + self.batch_size]
            embeddings, usage = await self._async_request(batch, expected_count=len(batch))
            all_embeddings.extend(embeddings)
            all_usage.extend([dict(usage) if usage is not None else None for _ in embeddings])
        return all_embeddings, all_usage
