from typing import Any, Dict, List, Optional

from agno.document import Document
from agno.reranker.base import Reranker
from agno.utils.log import logger

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    raise ImportError("`sentence-transformers` not installed, please run `pip install sentence-transformers`")


class SentenceTransformerReranker(Reranker):
    model: str = "BAAI/bge-reranker-v2-m3"
    model_kwargs: Optional[Dict[str, Any]] = None
    top_n: Optional[int] = None

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        if not documents:
            return []

        sentence_transformer_client = CrossEncoder(model_name_or_path=self.model, model_kwargs=self.model_kwargs)

        top_n = self.top_n
        if top_n and not (0 < top_n):
            logger.warning(f"top_n should be a positive integer, got {self.top_n}, setting top_n to None")
            top_n = None

        compressed_docs: list[Document] = []

        sentence_pairs = [[query, doc.content] for doc in documents]

        scores = sentence_transformer_client.predict(sentence_pairs).tolist()
        for index, score in enumerate(scores):
            doc = documents[index]
            doc.reranking_score = score
            compressed_docs.append(doc)

        compressed_docs.sort(
            key=lambda x: x.reranking_score if x.reranking_score is not None else float("-inf"),
            reverse=True,
        )

        if top_n:
            compressed_docs = compressed_docs[:top_n]

        return compressed_docs

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        try:
            return self._rerank(query=query, documents=documents)
        except Exception as e:
            logger.error(f"Error reranking documents: {e}. Returning original documents")
            return documents
