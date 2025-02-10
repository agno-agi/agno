from pathlib import Path
from typing import Iterator, List, Union

from agno.document import Document
from agno.document.reader.pdf_reader import PDFImageReader, PDFReader
from agno.knowledge.agent import AgentKnowledge


class PDFKnowledgeBase(AgentKnowledge):
    path: Union[str, Path]
    reader: Union[PDFReader, PDFImageReader] = PDFReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over PDFs and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """

        _pdf_path: Path = Path(self.path) if isinstance(self.path, str) else self.path

        if _pdf_path.exists() and _pdf_path.is_dir():
            for _pdf in _pdf_path.glob("**/*.pdf"):
                yield self.reader.read(pdf=_pdf)
        elif _pdf_path.exists() and _pdf_path.is_file() and _pdf_path.suffix == ".pdf":
            yield self.reader.read(pdf=_pdf_path)
