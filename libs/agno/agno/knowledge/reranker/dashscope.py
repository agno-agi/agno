from os import getenv
from typing import List, Optional

from agno.exceptions import ModelAuthenticationError
from agno.knowledge.document import Document
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import logger

try:
    from dashscope import TextReRank
except ImportError:
    raise ImportError("`dashscope` not installed, please run `pip install dashscope`")


class DashScopeReranker(Reranker):
    model: str = "qwen3-rerank"
    name: str = "Qwen"
    provider: str = "Dashscope"

    api_key: Optional[str] = getenv("DASHSCOPE_API_KEY") or getenv("QWEN_API_KEY")
    base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

    top_n: Optional[int] = None

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        # Validate input documents api_key and top_n
        if not documents:
            return []

        if not self.api_key:
            raise ModelAuthenticationError(
                message="DASHSCOPE_API_KEY not set. Please set the DASHSCOPE_API_KEY environment variable.",
                model_name=self.name,
            )

        top_n = self.top_n
        if top_n and not (0 < top_n):
            logger.warning(f"top_n should be a positive integer, got {self.top_n}, setting top_n to None")
            top_n = None

        _docs = [doc.content for doc in documents]
        resp = TextReRank.call(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            query=query,
            documents=_docs,
            top_n=top_n,
        )

        compressed_docs: list[Document] = []
        for r in resp.output.results:
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
