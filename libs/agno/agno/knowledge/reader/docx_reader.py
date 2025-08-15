import asyncio
from pathlib import Path
from typing import IO, Any, List, Optional, Union
from uuid import uuid4

from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.utils.log import log_info, logger

try:
    from docx import Document as DocxDocument  # type: ignore
except ImportError:
    raise ImportError("The `python-docx` package is not installed. Please install it via `pip install python-docx`.")


class DocxReader(Reader):
    """Reader for Doc/Docx files"""

    def __init__(self, chunking_strategy: Optional[ChunkingStrategy] = None, **kwargs):
        # Set DocumentChunking as default strategy if none provided
        if chunking_strategy is None:
            from agno.knowledge.chunking.document import DocumentChunking

            chunking_strategy = DocumentChunking()

        super().__init__(chunking_strategy=chunking_strategy, **kwargs)

    def get_supported_chunking_strategies(self) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for DOCX readers."""
        return [
            ChunkingStrategyType.AGENTIC_CHUNKING,
            ChunkingStrategyType.DOCUMENT_CHUNKING,
            ChunkingStrategyType.RECURSIVE_CHUNKING,
        ]

    def read(self, file: Union[Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        """Read a docx file and return a list of documents"""
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                log_info(f"Reading: {file}")
                docx_document = DocxDocument(str(file))
                doc_name = name or file.stem
            else:
                log_info(f"Reading uploaded file: {getattr(file, 'name', 'docx_file')}")
                docx_document = DocxDocument(file)
                doc_name = name or (
                    getattr(file, "name", "docx_file").split(".")[0] if hasattr(file, "name") else "docx_file"
                )

            doc_content = "\n\n".join([para.text for para in docx_document.paragraphs])

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
            logger.error(f"Error reading file: {e}")
            return []

    async def async_read(self, file: Union[Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        """Asynchronously read a docx file and return a list of documents"""
        try:
            return await asyncio.to_thread(self.read, file, name)
        except Exception as e:
            logger.error(f"Error reading file asynchronously: {e}")
            return []
