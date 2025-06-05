from typing import Any, List, Optional
from urllib.parse import urlparse

from agno.document import Document
from agno.reranker.base import Reranker
from agno.utils.log import logger

try:
    from infinity_client import AuthenticatedClient, Client
    from infinity_client.api.default import rerank
    from infinity_client.models import RerankInput
except ImportError:
    raise ImportError("infinity_client not installed, please run `pip install infinity_client`")


class InfinityReranker(Reranker):
    model: str = "BAAI/bge-reranker-base"
    host: str = "localhost"
    port: int = 7997
    url: Optional[str] = None
    top_n: Optional[int] = None
    api_key: Optional[str] = None
    verify_ssl: bool = True
    _client: Optional[Any] = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.url:
            self._parse_url()

    def _parse_url(self):
        """Parse URL to extract host, port and path"""
        if self.url:
            parsed = urlparse(self.url)
            if parsed.hostname:
                self.host = parsed.hostname
            if parsed.port:
                self.port = parsed.port
            # If no port specified in URL, keep default port

    @property
    def base_url(self) -> str:
        """Construct the base URL for the Infinity server"""
        return f"http://{self.host}:{self.port}"

    @property
    def client(self) -> Any:
        """Get or create the infinity client"""
        if self._client:
            return self._client

        base_url = self.base_url

        if self.api_key:
            self._client = AuthenticatedClient(base_url=base_url, token=self.api_key, verify_ssl=self.verify_ssl)
        else:
            self._client = Client(base_url=base_url, verify_ssl=self.verify_ssl)

        return self._client

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        # Validate input documents and top_n
        if not documents:
            return []

        top_n = self.top_n
        if top_n and not (0 < top_n):
            logger.warning(f"top_n should be a positive integer, got {self.top_n}, setting top_n to None")
            top_n = None

        compressed_docs: list[Document] = []

        try:
            # Prepare the request body for Infinity reranking
            rerank_input = {
                "model": self.model,
                "query": query,
                "documents": [doc.content for doc in documents],
                "return_documents": False,  # We only need scores, we already have documents
            }

            # Add top_n to payload if specified
            if top_n:
                rerank_input["top_n"] = top_n

            # Create the input object
            body = RerankInput.from_dict(rerank_input)

            # Make request to Infinity rerank endpoint using the client
            with self.client as client:
                result = rerank.sync(client=client, body=body)

                if result is None:
                    logger.error("Rerank request returned None")
                    return documents

                # Process the response
                # Infinity returns results with index and relevance_score
                if hasattr(result, "results") and result.results:
                    for item in result.results:
                        doc_index = item.index
                        relevance_score = item.relevance_score

                        if doc_index < len(documents):
                            doc = documents[doc_index]
                            doc.reranking_score = relevance_score
                            compressed_docs.append(doc)

                # Order by relevance score
                compressed_docs.sort(
                    key=lambda x: x.reranking_score if x.reranking_score is not None else float("-inf"),
                    reverse=True,
                )

                # Limit to top_n if specified and not already limited by the API
                if top_n and len(compressed_docs) > top_n:
                    compressed_docs = compressed_docs[:top_n]

        except Exception as e:
            logger.error(f"Error connecting to Infinity server at {self.base_url}: {e}")
            return documents

        return compressed_docs

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        try:
            return self._rerank(query=query, documents=documents)
        except Exception as e:
            logger.error(f"Error reranking documents: {e}. Returning original documents")
            return documents

    async def arerank(self, query: str, documents: List[Document]) -> List[Document]:
        """Async version of rerank"""
        # Validate input documents and top_n
        if not documents:
            return []

        top_n = self.top_n
        if top_n and not (0 < top_n):
            logger.warning(f"top_n should be a positive integer, got {self.top_n}, setting top_n to None")
            top_n = None

        compressed_docs: list[Document] = []

        try:
            # Prepare the request body for Infinity reranking
            rerank_input = {
                "model": self.model,
                "query": query,
                "documents": [doc.content for doc in documents],
                "return_documents": False,  # We only need scores, we already have documents
            }

            # Add top_n to payload if specified
            if top_n:
                rerank_input["top_n"] = top_n

            # Create the input object
            body = RerankInput.from_dict(rerank_input)

            # Make async request to Infinity rerank endpoint using the client
            async with self.client as client:
                result = await rerank.asyncio(client=client, body=body)

                if result is None:
                    logger.error("Async rerank request returned None")
                    return documents

                # Process the response
                # Infinity returns results with index and relevance_score
                if hasattr(result, "results") and result.results:
                    for item in result.results:
                        doc_index = item.index
                        relevance_score = item.relevance_score

                        if doc_index < len(documents):
                            doc = documents[doc_index]
                            doc.reranking_score = relevance_score
                            compressed_docs.append(doc)

                # Order by relevance score
                compressed_docs.sort(
                    key=lambda x: x.reranking_score if x.reranking_score is not None else float("-inf"),
                    reverse=True,
                )

                # Limit to top_n if specified and not already limited by the API
                if top_n and len(compressed_docs) > top_n:
                    compressed_docs = compressed_docs[:top_n]

        except Exception as e:
            logger.error(f"Error connecting to Infinity server at {self.base_url}: {e}")
            return documents

        return compressed_docs
