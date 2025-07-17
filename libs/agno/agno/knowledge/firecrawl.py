from typing import AsyncIterator, Iterator, List

from agno.knowledge.agent import AgentKnowledge
from agno.knowledge.document import Document
from agno.knowledge.reader.firecrawl_reader import FirecrawlReader


class FireCrawlKnowledgeBase(AgentKnowledge):
    urls: List[str] = []
    reader: FirecrawlReader = FirecrawlReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Scrape urls using FireCrawl and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """
        for url in self.urls:
            yield self.reader.read(url=url)

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Asynchronously scrape urls using FireCrawl and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            AsyncIterator[List[Document]]: Async iterator yielding list of documents
        """
        for url in self.urls:
            documents = await self.reader.async_read(url=url)
            if documents:
                yield documents
