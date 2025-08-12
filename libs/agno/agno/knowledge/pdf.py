from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from pydantic import Field
from typing_extensions import TypedDict

from agno.document import Document
from agno.document.reader.pdf_reader import PDFImageReader, PDFReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import log_error, log_info, logger


class PDFConfig(TypedDict, total=False):
    path: str
    password: Optional[str]
    metadata: Optional[Dict[str, Any]]


class PDFKnowledgeBase(AgentKnowledge):
    path: Optional[Union[str, Path, List[PDFConfig]]] = None
    formats: List[str] = [".pdf"]
    exclude_files: List[str] = Field(default_factory=list)
    reader: Union[PDFReader, PDFImageReader] = PDFReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over PDFs and yield lists of documents."""
        if self.path is None:
            raise ValueError("Path is not set")

        if isinstance(self.path, list):
            for item in self.path:
                if isinstance(item, dict) and "path" in item:
                    file_path = item["path"]
                    config = item.get("metadata", {})
                    file_password = item.get("password")
                    if file_password is not None and not isinstance(file_password, str):
                        file_password = None

                    _pdf_path = Path(file_path)  # type: ignore
                    if self._is_valid_pdf(_pdf_path):
                        documents = self.reader.read(pdf=_pdf_path, password=file_password)
                        if config:
                            for doc in documents:
                                log_info(f"Adding metadata {config} to document: {doc.name}")
                                doc.meta_data.update(config)  # type: ignore
                        yield documents
        else:
            _pdf_path = Path(self.path)
            if _pdf_path.is_dir():
                for _pdf in _pdf_path.glob("**/*.pdf"):
                    if _pdf.name not in self.exclude_files:
                        yield self.reader.read(pdf=_pdf)
            elif self._is_valid_pdf(_pdf_path):
                yield self.reader.read(pdf=_pdf_path)

    def _is_valid_pdf(self, path: Path) -> bool:
        """Helper to check if path is a valid PDF file."""
        if not path.exists():
            log_error(f"PDF file not found: {path}")
            return False
        if not path.is_file():
            log_error(f"Path is not a file: {path}")
            return False
        if path.suffix != ".pdf":
            log_error(f"File is not a PDF: {path}")
            return False
        if path.name in self.exclude_files:
            log_error(f"PDF file excluded: {path}")
            return False
        return True

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over PDFs and yield lists of documents asynchronously."""
        if self.path is None:
            raise ValueError("Path is not set")

        if isinstance(self.path, list):
            for item in self.path:
                if isinstance(item, dict) and "path" in item:
                    file_path = item["path"]
                    config = item.get("metadata", {})
                    file_password = item.get("password")
                    if file_password is not None and not isinstance(file_password, str):
                        file_password = None

                    _pdf_path = Path(file_path)  # type: ignore
                    if self._is_valid_pdf(_pdf_path):
                        documents = await self.reader.async_read(pdf=_pdf_path, password=file_password)
                        if config:
                            for doc in documents:
                                log_info(f"Adding metadata {config} to document: {doc.name}")
                                doc.meta_data.update(config)  # type: ignore
                        yield documents
        else:
            # Handle single path
            _pdf_path = Path(self.path)
            if _pdf_path.is_dir():
                for _pdf in _pdf_path.glob("**/*.pdf"):
                    if _pdf.name not in self.exclude_files:
                        yield await self.reader.async_read(pdf=_pdf)
            elif self._is_valid_pdf(_pdf_path):
                yield await self.reader.async_read(pdf=_pdf_path)

    def load_document(
        self,
        path: Union[str, Path],
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        _file_path = Path(path) if isinstance(path, str) else path

        # Validate file and prepare collection in one step
        if not self.prepare_load(_file_path, self.formats, metadata, recreate):
            return

        # Read documents
        try:
            documents = self.reader.read(pdf=_file_path)
        except Exception as e:
            logger.exception(f"Failed to read documents from file {_file_path}: {e}")
            return

        # Process documents
        self.process_documents(
            documents=documents,
            metadata=metadata,
            upsert=upsert,
            skip_existing=skip_existing,
            source_info=str(_file_path),
        )

    async def aload_document(
        self,
        path: Union[str, Path],
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        _file_path = Path(path) if isinstance(path, str) else path

        # Validate file and prepare collection in one step
        if not await self.aprepare_load(_file_path, self.formats, metadata, recreate):
            return

        # Read documents
        try:
            documents = await self.reader.async_read(pdf=_file_path)
        except Exception as e:
            logger.exception(f"Failed to read documents from file {_file_path}: {e}")
            return

        # Process documents
        await self.aprocess_documents(
            documents=documents,
            metadata=metadata,
            upsert=upsert,
            skip_existing=skip_existing,
            source_info=str(_file_path),
        )
