from typing import List, Optional

import requests

from agno.knowledge.document import Document
from agno.knowledge.reranker.base import Reranker
from agno.utils.log import logger


class XinferenceReranker(Reranker):
    """
    Xinference Reranker implementation.

    Uses Xinference's rerank API for document reranking.
    Xinference provides an OpenAI-compatible API for reranking.
    """

    base_url: str = "http://localhost:9997/v1"
    model: str = "bge-reranker-base"
    api_key: Optional[str] = None
    top_n: Optional[int] = None
    _session: Optional[requests.Session] = None

    @property
    def client(self) -> requests.Session:
        """
        Get or create a requests session for API calls.

        Returns:
            requests.Session: The HTTP session
        """
        if self._session is None:
            self._session = requests.Session()
            if self.api_key:
                self._session.headers.update(
                    {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    }
                )
            else:
                self._session.headers.update({"Content-Type": "application/json"})
        return self._session

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        """
        Perform reranking using Xinference API.

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

        # Prepare document texts
        document_texts = [doc.content for doc in documents]

        # Prepare request payload
        payload = {
            "model": self.model,
            "query": query,
            "documents": document_texts,
            "return_documents": False,  # We don't need the document content in response
        }

        # Add top_n if specified
        if top_n:
            payload["top_n"] = top_n

        # Call Xinference rerank API
        response = self.client.post(
            f"{self.base_url}/rerank",
            json=payload,
        )

        # Raise an exception for bad status codes
        response.raise_for_status()

        # Parse response
        response_data = response.json()

        # Check response format
        if "results" not in response_data:
            logger.warning(f"Unexpected response format from Xinference: {response_data}")
            return documents

        results = response_data["results"]
        logger.debug(f"Query: {query}, Results: {results}")

        # Process results and build ranked documents list
        ranked_documents: List[Document] = []

        for result in results:
            # Get the original document index
            doc_index = result.get("index")
            relevance_score = result.get("relevance_score")

            # Validate index
            if doc_index is None or not (0 <= doc_index < len(documents)):
                logger.warning(f"Invalid document index: {doc_index}")
                continue

            # Get the original document
            original_doc = documents[doc_index]

            # Set reranking score on the original document
            if relevance_score is not None:
                original_doc.reranking_score = relevance_score
            else:
                original_doc.reranking_score = 1.0

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
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error reranking documents with Xinference: {e}. Returning original documents")
            return documents
        except Exception as e:
            logger.error(f"Error reranking documents with Xinference: {e}. Returning original documents")
            return documents
