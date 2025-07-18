from typing import AsyncIterator, Iterator, List

from agno.document import Document
from agno.document.reader.s3.text_reader import S3TextReader
from agno.knowledge.s3.base import S3KnowledgeBase


class S3TextKnowledgeBase(S3KnowledgeBase):
    formats: List[str] = [".doc", ".docx"]
    reader: S3TextReader = S3TextReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over text files in a s3 bucket and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """
        for s3_object in self.s3_objects:
            if s3_object.name.endswith(tuple(self.formats)):
                yield self.reader.read(s3_object=s3_object)

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over text files in a s3 bucket and yield lists of documents asynchronously.
        Each object yielded by the iterator is a list of documents.

        Returns:
            AsyncIterator[List[Document]]: Async iterator yielding list of documents
        """
        for s3_object in self.s3_objects:
            if s3_object.name.endswith(tuple(self.formats)):
                yield await self.reader.async_read(s3_object=s3_object)
