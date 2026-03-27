from os import getenv
from typing import Any, Dict, List, Optional

from agno.knowledge.document import Document
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import logger

try:
    from zeroentropy import AsyncZeroEntropy, ZeroEntropy
except ImportError:
    raise ImportError("`zeroentropy` not installed, please run `pip install zeroentropy`")


class ZeroEntropyReranker(Reranker):
    model: str = "zerank-2"
    api_key: Optional[str] = None
    top_n: Optional[int] = None
    timeout: Optional[float] = None
    base_url: Optional[str] = None
    latency: Optional[str] = None
    _client: Optional[ZeroEntropy] = None
    _async_client: Optional[AsyncZeroEntropy] = None

    def _get_client_params(self) -> Dict[str, Any]:
        client_params: Dict[str, Any] = {}
        api_key = self.api_key or getenv("ZEROENTROPY_API_KEY")
        if api_key:
            client_params["api_key"] = api_key
        if self.timeout is not None:
            client_params["timeout"] = self.timeout
        if self.base_url is not None:
            client_params["base_url"] = self.base_url
        return client_params

    @property
    def client(self) -> ZeroEntropy:
        if self._client is None:
            self._client = ZeroEntropy(**self._get_client_params())
        return self._client

    @property
    def async_client(self) -> AsyncZeroEntropy:
        if self._async_client is None:
            self._async_client = AsyncZeroEntropy(**self._get_client_params())
        return self._async_client

    def _validated_top_n(self) -> Optional[int]:
        top_n = self.top_n
        if top_n is not None and top_n <= 0:
            logger.warning(f"top_n should be a positive integer, got {self.top_n}, setting top_n to None")
            top_n = None
        return top_n

    def _build_rerank_input(self, query: str, documents: List[Document], top_n: Optional[int]) -> Dict[str, Any]:
        rerank_input: Dict[str, Any] = {
            "model": self.model,
            "query": query,
            "documents": [doc.content for doc in documents],
        }
        if top_n is not None:
            rerank_input["top_n"] = top_n
        if self.latency is not None:
            if self.latency not in {"fast", "slow"}:
                logger.warning(f"latency should be 'fast' or 'slow', got {self.latency}, ignoring latency")
            else:
                rerank_input["latency"] = self.latency
        return rerank_input

    def _extract_results(self, response: Any) -> List[Any]:
        if isinstance(response, dict):
            results = response.get("results")
            if isinstance(results, list):
                return results
            return []

        results = getattr(response, "results", None)
        if isinstance(results, list):
            return results
        return []

    def _get_result_field(self, result: Any, field: str) -> Any:
        if isinstance(result, dict):
            return result.get(field)
        return getattr(result, field, None)

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        if not documents:
            return []

        top_n = self._validated_top_n()
        rerank_input = self._build_rerank_input(query=query, documents=documents, top_n=top_n)
        response = self.client.models.rerank(**rerank_input)

        results = self._extract_results(response)
        if not results:
            logger.warning("ZeroEntropy rerank response did not include valid results. Returning original documents")
            return documents

        reranked_docs: List[Document] = []
        for item in results:
            index = self._get_result_field(item, "index")
            relevance_score = self._get_result_field(item, "relevance_score")

            if isinstance(index, int) and 0 <= index < len(documents):
                doc = documents[index]
                if relevance_score is not None:
                    doc.reranking_score = float(relevance_score)
                reranked_docs.append(doc)

        reranked_docs.sort(
            key=lambda x: x.reranking_score if x.reranking_score is not None else float("-inf"),
            reverse=True,
        )

        if top_n is not None and len(reranked_docs) > top_n:
            reranked_docs = reranked_docs[:top_n]

        return reranked_docs

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        try:
            return self._rerank(query=query, documents=documents)
        except Exception as e:
            logger.warning(f"ZeroEntropy reranking failed: {e}. Returning original documents")
            return documents

    async def _arerank(self, query: str, documents: List[Document]) -> List[Document]:
        if not documents:
            return []

        top_n = self._validated_top_n()
        rerank_input = self._build_rerank_input(query=query, documents=documents, top_n=top_n)
        response = await self.async_client.models.rerank(**rerank_input)

        results = self._extract_results(response)
        if not results:
            logger.warning("ZeroEntropy rerank response did not include valid results. Returning original documents")
            return documents

        reranked_docs: List[Document] = []
        for item in results:
            index = self._get_result_field(item, "index")
            relevance_score = self._get_result_field(item, "relevance_score")

            if isinstance(index, int) and 0 <= index < len(documents):
                doc = documents[index]
                if relevance_score is not None:
                    doc.reranking_score = float(relevance_score)
                reranked_docs.append(doc)

        reranked_docs.sort(
            key=lambda x: x.reranking_score if x.reranking_score is not None else float("-inf"),
            reverse=True,
        )

        if top_n is not None and len(reranked_docs) > top_n:
            reranked_docs = reranked_docs[:top_n]

        return reranked_docs

    async def arerank(self, query: str, documents: List[Document]) -> List[Document]:
        try:
            return await self._arerank(query=query, documents=documents)
        except Exception as e:
            logger.warning(f"ZeroEntropy reranking failed: {e}. Returning original documents")
            return documents
