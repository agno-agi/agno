from typing import Iterator, List

from agno.document import Document
from agno.document.reader.firecrawl_reader import FirecrawlReader
from agno.knowledge.agent import AgentKnowledge


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
            yield self.reader.scrape(url=url)
