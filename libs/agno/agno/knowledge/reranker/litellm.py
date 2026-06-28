from typing import Any, Dict, List, Optional

from agno.knowledge.document import Document
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import logger

try:
    import litellm
except ImportError:
    raise ImportError("`litellm` not installed. Please install it via `pip install litellm`.")


class LiteLLMReranker(Reranker):
    """Reranker implementation using LiteLLM unified rerank interface.

    Provide any supported rerank model string e.g.
        - cohere/rerank-multilingual-v3.0
        - cohere/rerank-english-v3.0
        - jina/jina-reranker-v2-base-en
        - voyageai/voyage-rerank-2

    Attributes:
        model: Reranking model identifier understood by LiteLLM.
        top_n: Optional limit for returned documents.
        api_key: Optional explicit API key.
        api_base: Optional custom base URL.
        request_params: Extra provider specific params forwarded to litellm.rerank.
    """

    model: str = "cohere/rerank-multilingual-v3.0"
    top_n: Optional[int] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None

    def _build_request(self, query: str, documents: List[Document]) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "model": self.model,
            "query": query,
            "documents": [d.content for d in documents],
        }
        if self.top_n and self.top_n > 0:
            params["top_n"] = self.top_n
        if self.api_key is not None:
            params["api_key"] = self.api_key
        if self.api_base is not None:
            params["api_base"] = self.api_base
        if self.request_params:
            params.update(self.request_params)
        return params

    @staticmethod
    def _extract_results(response: Any) -> List[Any]:
        """Extract results from LiteLLM rerank response."""
        try:
            if hasattr(response, 'results'):
                return response.results
            return []
        except Exception:
            return []

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        if not documents:
            return []
        try:
            request = self._build_request(query=query, documents=documents)
            response = litellm.rerank(**request)
            results = self._extract_results(response)
            ranked: List[Document] = []
            for r in results:
                try:
                    idx = getattr(r, "index", None)
                    score = getattr(r, "relevance_score", None)
                    if idx is None or idx >= len(documents):
                        continue
                    doc = documents[idx]
                    doc.reranking_score = score
                    ranked.append(doc)
                except Exception as e:
                    logger.warning(f"Failed processing rerank item: {e}")

            ranked.sort(
                key=lambda d: d.reranking_score if d.reranking_score is not None else float("-inf"),
                reverse=True,
            )
            if self.top_n and self.top_n > 0:
                ranked = ranked[: self.top_n]
            return ranked
        except Exception as e:
            logger.error(f"LiteLLM rerank error: {e}. Returning original documents")
            return documents

    def rerank(self, query: str, documents: List[Document]) -> List[Document]: 
        try:
            return self._rerank(query=query, documents=documents)
        except Exception as e:
            logger.error(f"Unexpected rerank error: {e}. Returning original documents")
            return documents
