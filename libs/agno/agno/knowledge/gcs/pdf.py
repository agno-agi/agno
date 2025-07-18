from typing import AsyncIterator, Iterator, List

from agno.document import Document
from agno.document.reader.gcs.pdf_reader import GCSPDFReader
from agno.knowledge.gcs.base import GCSKnowledgeBase


class GCSPDFKnowledgeBase(GCSKnowledgeBase):
    reader: GCSPDFReader = GCSPDFReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        for blob in self.gcs_blobs:
            if blob.name.endswith(".pdf"):
                yield self.reader.read(blob=blob)

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        for blob in self.gcs_blobs:
            if blob.name.endswith(".pdf"):
                yield await self.reader.async_read(blob=blob)
