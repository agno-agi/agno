from typing import AsyncIterator, Iterator, List, Union

from agno.document import Document
from agno.document.reader.pdf_reader import PDFUrlImageReader, PDFUrlReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import logger


class PDFUrlKnowledgeBase(AgentKnowledge):
    urls: List[str] = []
    reader: Union[PDFUrlReader, PDFUrlImageReader] = PDFUrlReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over PDF urls and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """

        for url in self.urls:
            if url.endswith(".pdf"):
                yield self.reader.read(url=url)
            else:
                logger.error(f"Unsupported URL: {url}")

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over PDF urls and yield lists of documents.
        Each object yielded by the iterator is a list of documents.
        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """

        for url in self.urls:
            if url.endswith(".pdf"):
                yield await self.reader.async_read(url=url)
            else:
                logger.error(f"Unsupported URL: {url}")
