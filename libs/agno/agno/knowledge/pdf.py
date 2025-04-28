from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from pydantic import Field

from agno.document import Document
from agno.document.reader.pdf_reader import PDFImageReader, PDFReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import log_info


class PDFKnowledgeBase(AgentKnowledge):
    path: Optional[Union[str, Path, List[Union[str, Path, Dict[str, Dict[str, Any]]]]]] = None  # type: ignore

    formats: List[str] = [".pdf"]

    exclude_files: List[str] = Field(default_factory=list)

    reader: Union[PDFReader, PDFImageReader] = PDFReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over PDFs and yield lists of documents."""
        if self.path is None:
            raise ValueError("Path is not set")

        # Handle list of paths/metadata
        if isinstance(self.path, list):
            for item in self.path:
                if isinstance(item, dict):
                    for file_path, config in item.items():
                        _pdf_path = Path(file_path)
                        if self._is_valid_pdf(_pdf_path):
                            documents = self.reader.read(pdf=_pdf_path)
                            # Add metadata to documents if provided
                            if config.get("metadata"):
                                for doc in documents:
                                    log_info(f"Adding metadata {config.get('metadata')} to document: {doc.name}")
                                    doc.meta_data.update(config["metadata"])
                            yield documents
                else:
                    # Handle simple path
                    _pdf_path = Path(item)
                    if self._is_valid_pdf(_pdf_path):
                        yield self.reader.read(pdf=_pdf_path)
        else:
            # Handle single path
            _pdf_path = Path(self.path)
            if _pdf_path.is_dir():
                for _pdf in _pdf_path.glob("**/*.pdf"):
                    if _pdf.name not in self.exclude_files:
                        yield self.reader.read(pdf=_pdf)
            elif self._is_valid_pdf(_pdf_path):
                yield self.reader.read(pdf=_pdf_path)

    def _is_valid_pdf(self, path: Path) -> bool:
        """Helper to check if path is a valid PDF file."""
        return path.exists() and path.is_file() and path.suffix == ".pdf" and path.name not in self.exclude_files

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over PDFs and yield lists of documents asynchronously."""
        if self.path is None:
            raise ValueError("Path is not set")

        # Handle list of paths/metadata
        if isinstance(self.path, list):
            for item in self.path:
                if isinstance(item, dict):
                    # Handle path with metadata
                    for file_path, config in item.items():
                        _pdf_path = Path(file_path)
                        if self._is_valid_pdf(_pdf_path):
                            documents = await self.reader.async_read(pdf=_pdf_path)
                            # Add metadata to documents if provided
                            if config.get("metadata"):
                                for doc in documents:
                                    log_info(f"Adding metadata {config.get('metadata')} to document: {doc.name}")
                                    doc.meta_data.update(config["metadata"])
                            yield documents
                else:
                    # Handle simple path
                    _pdf_path = Path(item)
                    if self._is_valid_pdf(_pdf_path):
                        yield await self.reader.async_read(pdf=_pdf_path)
        else:
            # Handle single path
            _pdf_path = Path(self.path)
            if _pdf_path.is_dir():
                for _pdf in _pdf_path.glob("**/*.pdf"):
                    if _pdf.name not in self.exclude_files:
                        yield await self.reader.async_read(pdf=_pdf)
            elif self._is_valid_pdf(_pdf_path):
                yield await self.reader.async_read(pdf=_pdf_path)
