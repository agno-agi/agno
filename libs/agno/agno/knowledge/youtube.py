import asyncio
from typing import AsyncIterator, Iterator, List

from agno.document import Document
from agno.document.reader.youtube_reader import YouTubeReader
from agno.knowledge.agent import AgentKnowledge


class YouTubeKnowledgeBase(AgentKnowledge):
    urls: List[str] = []
    reader: YouTubeReader = YouTubeReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over YouTube URLs and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
                Iterator[List[Document]]: Iterator yielding list of documents
        """
        for url in self.urls:
            yield self.reader.read(video_url=url)

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Asynchronously iterate over YouTube URLs and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            AsyncIterator[List[Document]]: Async iterator yielding list of documents
        """
        tasks = [self.reader.async_read(video_url=url) for url in self.urls]
        results = await asyncio.gather(*tasks)
        for documents in results:
            yield documents
