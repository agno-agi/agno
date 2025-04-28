from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from agno.document import Document
from agno.document.reader.text_reader import TextReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import log_info, logger


class TextKnowledgeBase(AgentKnowledge):
    path: Optional[Union[str, Path, List[Union[str, Path, Dict[str, Dict[str, Any]]]]]] = None
    formats: List[str] = [".txt"]
    reader: TextReader = TextReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over text files and yield lists of documents."""
        if self.path is None:
            raise ValueError("Path is not set")

        if isinstance(self.path, list):
            for item in self.path:
                if isinstance(item, dict):
                    # Handle path with metadata
                    for file_path, config in item.items():
                        _file_path = Path(file_path)
                        if self._is_valid_text(_file_path):
                            documents = self.reader.read(file=_file_path)
                            if config.get("metadata"):
                                for doc in documents:
                                    log_info(f"Adding metadata {config.get('metadata')} to document: {doc.name}")
                                    doc.meta_data.update(config["metadata"])
                            yield documents
                else:
                    # Handle simple path
                    _file_path = Path(item)
                    if self._is_valid_text(_file_path):
                        yield self.reader.read(file=_file_path)
        else:
            # Handle single path
            _file_path = Path(self.path)
            if _file_path.is_dir():
                for _file in _file_path.glob("**/*"):
                    if self._is_valid_text(_file):
                        yield self.reader.read(file=_file)
            elif self._is_valid_text(_file_path):
                yield self.reader.read(file=_file_path)

    def _is_valid_text(self, path: Path) -> bool:
        """Helper to check if path is a valid text file."""
        return path.exists() and path.is_file() and path.suffix in self.formats

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over text files and yield lists of documents asynchronously."""
        if self.path is None:
            raise ValueError("Path is not set")

        if isinstance(self.path, list):
            for item in self.path:
                if isinstance(item, dict):
                    # Handle path with metadata
                    for file_path, config in item.items():
                        _file_path = Path(file_path)
                        if self._is_valid_text(_file_path):
                            documents = await self.reader.async_read(file=_file_path)
                            if config.get("metadata"):
                                for doc in documents:
                                    log_info(f"Adding metadata {config.get('metadata')} to document: {doc.name}")
                                    doc.meta_data.update(config["metadata"])
                            yield documents
                else:
                    # Handle simple path
                    _file_path = Path(item)
                    if self._is_valid_text(_file_path):
                        yield await self.reader.async_read(file=_file_path)
        else:
            # Handle single path
            _file_path = Path(self.path)
            if _file_path.is_dir():
                for _file in _file_path.glob("**/*"):
                    if self._is_valid_text(_file):
                        yield await self.reader.async_read(file=_file)
            elif self._is_valid_text(_file_path):
                yield await self.reader.async_read(file=_file_path)

    def load_text(
        self,
        path: Union[str, Path],
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load documents from a single text file with specific metadata into the vector DB."""

        _file_path = Path(path) if isinstance(path, str) else path

        # Validate file and prepare collection in one step
        if not self.prepare_load(_file_path, self.formats, metadata, recreate):
            return

        # Read documents
        try:
            documents = self.reader.read(file=_file_path)
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

    async def aload_text(
        self,
        path: Union[str, Path],
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load documents from a single text file with specific metadata into the vector DB."""

        _file_path = Path(path) if isinstance(path, str) else path

        # Validate file and prepare collection in one step
        if not await self.aprepare_load(_file_path, self.formats, metadata, recreate):
            return

        # Read documents
        try:
            documents = await self.reader.async_read(file=_file_path)
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
