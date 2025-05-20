import asyncio
from typing import AsyncIterator, Iterator, List

from agno.document import Document
from agno.document.reader.url_reader import URLReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import logger


class UrlKnowledge(AgentKnowledge):
    urls: List[str] = []
    reader: URLReader = URLReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over URLs and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """
        for url in self.urls:
            try:
                yield self.reader.read(url=url)
            except Exception as e:
                logger.error(f"Error reading URL {url}: {str(e)}")

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Async version of document_lists"""

        async def process_url(url: str) -> List[Document]:
            try:
                return await self.reader.async_read(url=url)
            except Exception as e:
                logger.error(f"Error reading URL {url}: {str(e)}")
                return []

        # Process all URLs concurrently
        tasks = [process_url(url) for url in self.urls]
        results = await asyncio.gather(*tasks)

        # Yield each result
        for docs in results:
            if docs:
                yield docs
