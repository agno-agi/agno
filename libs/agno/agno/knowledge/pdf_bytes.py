import io
from typing import IO, AsyncIterator, Iterator, List, Union

from pydantic import Field

from agno.document import Document
from agno.document.reader.pdf_reader import PDFImageReader, PDFReader
from agno.knowledge.agent import AgentKnowledge


class PDFBytesKnowledgeBase(AgentKnowledge):
    pdfs: Union[List[bytes], List[IO]]

    exclude_files: List[str] = Field(default_factory=list)

    reader: Union[PDFReader, PDFImageReader] = PDFReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over PDFs bytes and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """

        for pdf in self.pdfs:
            _pdf = io.BytesIO(pdf) if isinstance(pdf, bytes) else pdf
            yield self.reader.read(pdf=_pdf)

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over PDFs bytes and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """

        for pdf in self.pdfs:
            _pdf = io.BytesIO(pdf) if isinstance(pdf, bytes) else pdf
            yield await self.reader.async_read(pdf=_pdf)
