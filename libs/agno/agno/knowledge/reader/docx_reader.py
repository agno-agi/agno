import asyncio
from pathlib import Path
from typing import IO, Any, List, Optional, Union
from uuid import uuid4

from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_error

try:
    from docx import Document as DocxDocument  # type: ignore
    from docx.document import Document as DocxDocumentType
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table, _Cell
    from docx.text.paragraph import Paragraph
except ImportError:
    raise ImportError("The `python-docx` package is not installed. Please install it via `pip install python-docx`.")


class DocxReader(Reader):
    """Reader for Doc/Docx files"""

    def __init__(self, chunking_strategy: Optional[ChunkingStrategy] = None, **kwargs):
        if chunking_strategy is None:
            chunk_size = kwargs.get("chunk_size", 5000)
            chunking_strategy = DocumentChunking(chunk_size=chunk_size)
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for DOCX readers."""
        return [
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.CODE_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        # .doc is deliberately absent: python-docx reads the Open XML package only, and a
        # legacy OLE2 .doc fails to open, so advertising it offers a format that never reads.
        return [ContentType.DOCX]

    def _extract_text(self, parent: Union[DocxDocumentType, _Cell]) -> str:
        """Read paragraphs and tables in their document or cell order."""
        if isinstance(parent, DocxDocumentType):
            container = parent.element.body
            separator = "\n\n"
        else:
            container = parent._tc
            separator = "\n"

        blocks: List[str] = []
        for element in container.iterchildren():
            if isinstance(element, CT_P):
                blocks.append(Paragraph(element, parent).text)
            elif isinstance(element, CT_Tbl):
                rows: List[str] = []
                seen_cells = set()
                for row in Table(element, parent).rows:
                    cells: List[str] = []
                    for cell in row.cells:
                        # A merged cell appears at each grid position it spans.
                        if cell._tc in seen_cells:
                            continue
                        seen_cells.add(cell._tc)
                        cells.append(self._extract_text(cell))
                    if cells:
                        rows.append("\t".join(cells))
                blocks.append("\n".join(rows))
        return separator.join(blocks)

    def read(self, file: Union[Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        """Read a docx file and return a list of documents"""
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                log_debug(f"Reading: {file}")
                docx_document = DocxDocument(str(file))
                doc_name = name or file.stem
            else:
                log_debug(f"Reading uploaded file: {getattr(file, 'name', 'BytesIO')}")
                docx_document = DocxDocument(file)
                doc_name = name or getattr(file, "name", "docx_file").split(".")[0]

            doc_content = self._extract_text(docx_document)

            documents = [
                Document(
                    name=doc_name,
                    id=str(uuid4()),
                    content=doc_content,
                )
            ]
            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents
            return documents

        except Exception as e:
            log_error(f"Error reading file: {str(e)}")
            return []

    async def async_read(self, file: Union[Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        """Asynchronously read a docx file and return a list of documents"""
        try:
            return await asyncio.to_thread(self.read, file, name)
        except Exception as e:
            log_error(f"Error reading file asynchronously: {str(e)}")
            return []
