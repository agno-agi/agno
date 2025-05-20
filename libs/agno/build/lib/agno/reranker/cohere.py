from typing import Any, Dict, List, Optional

from agno.document import Document
from agno.reranker.base import Reranker
from agno.utils.log import logger

try:
    from cohere import Client as CohereClient
except ImportError:
    raise ImportError("cohere not installed, please run pip install cohere")


class CohereReranker(Reranker):
    model: str = "rerank-multilingual-v3.0"
    api_key: Optional[str] = None
    cohere_client: Optional[CohereClient] = None
    top_n: Optional[int] = None

    @property
    def client(self) -> CohereClient:
        if self.cohere_client:
            return self.cohere_client

        _client_params: Dict[str, Any] = {}
        if self.api_key:
            _client_params["api_key"] = self.api_key
        return CohereClient(**_client_params)

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        # Validate input documents and top_n
        if not documents:
            return []

        top_n = self.top_n
        if top_n and not (0 < top_n):
            logger.warning(f"top_n should be a positive integer, got {self.top_n}, setting top_n to None")
            top_n = None

        compressed_docs: list[Document] = []
        _docs = [doc.content for doc in documents]
        response = self.client.rerank(query=query, documents=_docs, model=self.model)
        for r in response.results:
            doc = documents[r.index]
            doc.reranking_score = r.relevance_score
            compressed_docs.append(doc)

        # Order by relevance score
        compressed_docs.sort(
            key=lambda x: x.reranking_score if x.reranking_score is not None else float("-inf"),
            reverse=True,
        )

        # Limit to top_n if specified
        if top_n:
            compressed_docs = compressed_docs[:top_n]

        return compressed_docs

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        try:
            return self._rerank(query=query, documents=documents)
        except Exception as e:
            logger.error(f"Error reranking documents: {e}. Returning original documents")
            return documents
