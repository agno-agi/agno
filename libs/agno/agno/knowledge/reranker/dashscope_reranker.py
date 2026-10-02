from typing import List, Optional

try:
    import dashscope
except ImportError:
    raise ImportError("dashscope not installed, please run `pip install dashscope`")

from agno.knowledge.document import Document
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import logger


class DashScopeReranker(Reranker):
    """
    DashScope Reranker implementation.

    Uses DashScope platform for document reranking.
    """

    model: str = "gte-rerank"  # Default DashScope reranker model
    api_key: Optional[str] = None
    top_n: Optional[int] = None
    _client_initialized: bool = False

    @property
    def client(self) -> None:
        """
        Initialize the DashScope client by setting the API key.

        Unlike other clients, DashScope uses a global configuration pattern,
        so this property sets the API key globally.
        """
        if not self._client_initialized and self.api_key:
            dashscope.api_key = self.api_key
            self._client_initialized = True

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        """
        Perform reranking using DashScope API.

        Args:
            query: The search query string
            documents: List of documents to rerank

        Returns:
            Reranked list of documents with relevance scores
        """
        # Validate input documents
        if not documents:
            return []

        # Validate top_n parameter
        top_n = self.top_n
        if top_n is not None and not (0 < top_n):
            logger.warning(f"top_n should be a positive integer, got {self.top_n}, setting top_n to None")
            top_n = None

        # Initialize client
        self.client

        # Prepare document texts
        document_texts = [doc.content for doc in documents]

        # Call DashScope reranker API
        response = dashscope.TextReRank.call(
            model=self.model,
            query=query,
            documents=document_texts,
            return_documents=False,
            top_n=top_n if top_n else len(documents),
        )

        # Process response
        ranked_documents: List[Document] = []

        if not (hasattr(response, "output") and response.output):
            logger.warning(f"Unexpected response format from DashScope: {response}")
            return documents

        results = response.output.results
        logger.debug(f"Query: {query}, Results: {results}")

        for result in results:
            # Get the original document index
            doc_index = result.index
            if 0 <= doc_index < len(documents):
                # Get the original document
                original_doc = documents[doc_index]

                # Set reranking score on the original document
                # Handle both relevance_score and score fields
                relevance_score = result.get("relevance_score", result.get("score", 1.0))
                original_doc.reranking_score = relevance_score

                ranked_documents.append(original_doc)

        return ranked_documents

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        """
        Rerank documents with error handling wrapper.

        Args:
            query: The search query string
            documents: List of documents to rerank

        Returns:
            Reranked list of documents, or original documents if an error occurs
        """
        try:
            return self._rerank(query=query, documents=documents)
        except Exception as e:
            logger.error(f"Error reranking documents with DashScope: {e}. Returning original documents")
            return documents
