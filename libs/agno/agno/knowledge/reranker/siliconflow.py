import math
from typing import Any, Dict, List, Optional, Tuple

import httpx
from pydantic import Field

from agno.exceptions import AgnoError
from agno.knowledge.document import Document
from agno.knowledge.reranker.base import Reranker
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
from agno.utils.log import logger


class SiliconflowReranker(Reranker):
    """Rerank text documents with Siliconflow's rerank API.

    The reranker reads ``SILICONFLOW_API_KEY`` lazily when ``api_key`` is not
    provided. Provider failures return the original documents by default; set
    ``raise_on_error=True`` to receive typed Agno provider exceptions instead.
    """

    model: str = Field(default="BAAI/bge-reranker-v2-m3", min_length=1)
    api_key: Optional[str] = Field(default=None, exclude=True, repr=False)
    base_url: str = Field(default=DEFAULT_SILICONFLOW_BASE_URL, min_length=1)
    top_n: Optional[int] = Field(default=None, gt=0)
    instruction: Optional[str] = Field(default=None, min_length=1)
    max_chunks_per_doc: Optional[int] = Field(default=None, ge=1)
    overlap_tokens: Optional[int] = Field(default=None, ge=0, le=80)
    timeout: float = Field(default=30.0, gt=0)
    raise_on_error: bool = False
    request_params: Optional[Dict[str, Any]] = None
    extra_headers: Optional[Dict[str, str]] = None
    http_client: Optional[httpx.Client] = Field(default=None, exclude=True, repr=False)
    async_http_client: Optional[httpx.AsyncClient] = Field(default=None, exclude=True, repr=False)

    @property
    def client(self) -> httpx.Client:
        return self.http_client or get_default_sync_client()

    @property
    def aclient(self) -> httpx.AsyncClient:
        return self.async_http_client or get_default_async_client()

    @property
    def endpoint(self) -> str:
        return get_siliconflow_url(self.base_url, "/rerank")

    def _build_payload(self, query: str, documents: List[Document]) -> Tuple[Dict[str, Any], int]:
        if not query:
            raise ValueError("query must not be empty")

        top_n = min(self.top_n or len(documents), len(documents))
        payload = dict(self.request_params or {})
        payload.update(
            {
                "model": self.model,
                "query": query,
                "documents": [document.content for document in documents],
                "top_n": top_n,
                "return_documents": False,
            }
        )
        if self.instruction is not None:
            payload["instruction"] = self.instruction
        else:
            payload.pop("instruction", None)
        if self.max_chunks_per_doc is not None:
            payload["max_chunks_per_doc"] = self.max_chunks_per_doc
        else:
            payload.pop("max_chunks_per_doc", None)
        if self.overlap_tokens is not None:
            payload["overlap_tokens"] = self.overlap_tokens
        else:
            payload.pop("overlap_tokens", None)
        return payload, top_n

    def _parse_response(
        self, response_body: Any, documents: List[Document], expected_count: int, trace_id: Optional[str]
    ) -> List[Document]:
        if not isinstance(response_body, dict) or not isinstance(response_body.get("results"), list):
            raise get_malformed_siliconflow_response_error("results must be a list", self.model, trace_id)

        results = response_body["results"]
        if len(results) != expected_count:
            raise get_malformed_siliconflow_response_error(
                f"expected {expected_count} results, received {len(results)}", self.model, trace_id
            )

        parsed_results: List[Tuple[int, float]] = []
        seen_indices = set()
        for result in results:
            if not isinstance(result, dict):
                raise get_malformed_siliconflow_response_error("each result must be an object", self.model, trace_id)

            index = result.get("index")
            score = result.get("relevance_score")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(documents):
                raise get_malformed_siliconflow_response_error("result index is invalid", self.model, trace_id)
            if index in seen_indices:
                raise get_malformed_siliconflow_response_error("result indices must be unique", self.model, trace_id)
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
                raise get_malformed_siliconflow_response_error(
                    "relevance_score must be a finite number", self.model, trace_id
                )

            seen_indices.add(index)
            parsed_results.append((index, float(score)))

        reranked_documents: List[Document] = []
        for index, score in parsed_results:
            document = documents[index]
            document.reranking_score = score
            reranked_documents.append(document)
        return reranked_documents

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        payload, expected_count = self._build_payload(query, documents)
        try:
            response = self.client.post(
                self.endpoint,
                headers=get_siliconflow_headers(self.api_key, self.extra_headers),
                json=payload,
                timeout=self.timeout,
            )
            raise_for_siliconflow_status(response, self.model)
            trace_id = get_siliconflow_trace_id(response)
            try:
                response_body = response.json()
            except ValueError as error:
                raise get_malformed_siliconflow_response_error(
                    "response is not valid JSON", self.model, trace_id
                ) from error
            return self._parse_response(response_body, documents, expected_count, trace_id)
        except AgnoError:
            raise
        except httpx.RequestError as error:
            raise get_siliconflow_request_error(error, self.model) from error
        except Exception as error:
            raise get_siliconflow_request_error(error, self.model) from error

    async def _arerank(self, query: str, documents: List[Document]) -> List[Document]:
        payload, expected_count = self._build_payload(query, documents)
        try:
            response = await self.aclient.post(
                self.endpoint,
                headers=get_siliconflow_headers(self.api_key, self.extra_headers),
                json=payload,
                timeout=self.timeout,
            )
            raise_for_siliconflow_status(response, self.model)
            trace_id = get_siliconflow_trace_id(response)
            try:
                response_body = response.json()
            except ValueError as error:
                raise get_malformed_siliconflow_response_error(
                    "response is not valid JSON", self.model, trace_id
                ) from error
            return self._parse_response(response_body, documents, expected_count, trace_id)
        except AgnoError:
            raise
        except httpx.RequestError as error:
            raise get_siliconflow_request_error(error, self.model) from error
        except Exception as error:
            raise get_siliconflow_request_error(error, self.model) from error

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        if not documents:
            return []
        try:
            return self._rerank(query, documents)
        except Exception:
            if self.raise_on_error:
                raise
            logger.exception("Siliconflow reranking failed. Returning original documents")
            return documents

    async def arerank(self, query: str, documents: List[Document]) -> List[Document]:
        if not documents:
            return []
        try:
            return await self._arerank(query, documents)
        except Exception:
            if self.raise_on_error:
                raise
            logger.exception("Siliconflow reranking failed. Returning original documents")
            return documents
