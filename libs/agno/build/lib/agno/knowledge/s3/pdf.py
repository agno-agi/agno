from typing import Iterator, List

from agno.document import Document
from agno.document.reader.s3.pdf_reader import S3PDFReader
from agno.knowledge.s3.base import S3KnowledgeBase


class S3PDFKnowledgeBase(S3KnowledgeBase):
    reader: S3PDFReader = S3PDFReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over PDFs in a s3 bucket and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """
        for s3_object in self.s3_objects:
            if s3_object.name.endswith(".pdf"):
                yield self.reader.read(s3_object=s3_object)
