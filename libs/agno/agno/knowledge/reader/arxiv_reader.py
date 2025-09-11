import asyncio
from typing import List, Optional

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType

try:
    import arxiv  # noqa: F401
except ImportError:
    raise ImportError("The `arxiv` package is not installed. Please install it via `pip install arxiv`.")


class ArxivReader(Reader):
    sort_by: arxiv.SortCriterion = arxiv.SortCriterion.Relevance

    @classmethod
    def get_supported_chunking_strategies(self) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for Arxiv readers."""
        return [
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.TOPIC]

    def __init__(
        self,
        chunking_strategy: Optional[ChunkingStrategy] = FixedSizeChunking(),
        sort_by: arxiv.SortCriterion = arxiv.SortCriterion.Relevance,
        **kwargs,
    ) -> None:
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)

        # ArxivReader-specific attributes
        self.sort_by = sort_by

    def read(self, query: str) -> List[Document]:
        """
        Search a query from arXiv database

        This function gets the top_k articles based on a user's query, sorted by relevance from arxiv

        @param query:
        @return: List of documents
        """

        documents = []
        search = arxiv.Search(query=query, max_results=self.max_results, sort_by=self.sort_by)

        for result in search.results():
            links = ", ".join([x.href for x in result.links])

            documents.append(
                Document(
                    name=result.title,
                    id=result.title,
                    meta_data={"pdf_url": str(result.pdf_url), "article_links": links},
                    content=result.summary,
                )
            )

        return documents

    async def async_read(self, query: str) -> List[Document]:
        """
        Search a query from arXiv database asynchronously

        This function gets the top_k articles based on a user's query, sorted by relevance from arxiv

        @param query: Search query string
        @return: List of documents
        """
        return await asyncio.to_thread(self.read, query)
