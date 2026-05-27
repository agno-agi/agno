import asyncio
import uuid
from pathlib import Path
from typing import IO, Any, List, Optional, Union

from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_error, log_warning

# Check if MarkdownChunking is available
MARKDOWN_CHUNKER_AVAILABLE = False

try:
    from agno.knowledge.chunking.markdown import MarkdownChunking

    MARKDOWN_CHUNKER_AVAILABLE = True
except ImportError:
    pass


class MarkdownReader(Reader):
    """Reader for Markdown files"""

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for Markdown readers."""
        strategies = [
            ChunkingStrategyType.CODE_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
        ]

        # Only include MarkdownChunking if it's available
        if MARKDOWN_CHUNKER_AVAILABLE:
            strategies.insert(0, ChunkingStrategyType.MARKDOWN_CHUNKER)

        return strategies

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.MARKDOWN]

    def __init__(
        self,
        chunking_strategy: Optional[ChunkingStrategy] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs,
    ) -> None:
        # Create default chunking strategy with the caller's chunk_size
        if chunking_strategy is None:
            chunk_size = kwargs.get("chunk_size", 5000)
            if MARKDOWN_CHUNKER_AVAILABLE:
                chunking_strategy = MarkdownChunking(chunk_size=chunk_size)
            else:
                from agno.knowledge.chunking.fixed import FixedSizeChunking

                chunking_strategy = FixedSizeChunking(chunk_size=chunk_size)

        super().__init__(chunking_strategy=chunking_strategy, name=name, description=description, **kwargs)

    def read(self, file: Union[Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                log_debug(f"Reading: {file}")
                file_name = name or file.stem
                file_contents = file.read_text(encoding=self.encoding or "utf-8")
            else:
                log_debug(f"Reading uploaded file: {getattr(file, 'name', 'BytesIO')}")
                file_name = name or getattr(file, "name", "file").split(".")[0]
                file.seek(0)
                file_contents = file.read().decode(self.encoding or "utf-8")

            documents = [Document(name=file_name, id=str(uuid.uuid4()), content=file_contents)]
            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents
            return documents
        except Exception as e:
            log_error(f"Error reading: {file}: {str(e)}")
            return []

    async def async_read(self, file: Union[Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")

                log_debug(f"Reading asynchronously: {file}")
                file_name = name or file.stem

                try:
                    import aiofiles

                    async with aiofiles.open(file, "r", encoding=self.encoding or "utf-8") as f:
                        file_contents = await f.read()
                except ImportError as e:
                    log_warning(f"aiofiles not installed, using synchronous file I/O: {str(e)}")
                    file_contents = file.read_text(encoding=self.encoding or "utf-8")
            else:
                log_debug(f"Reading uploaded file asynchronously: {getattr(file, 'name', 'BytesIO')}")
                file_name = name or getattr(file, "name", "file").split(".")[0]
                file.seek(0)
                file_contents = file.read().decode(self.encoding or "utf-8")

            document = Document(
                name=file_name,
                id=str(uuid.uuid4()),
                content=file_contents,
            )

            if self.chunk:
                return await self._async_chunk_document(document)
            return [document]
        except Exception as e:
            log_error(f"Error reading asynchronously: {file}: {str(e)}")
            return []

    async def _async_chunk_document(self, document: Document) -> List[Document]:
        if not self.chunk or not document:
            return [document]

        async def process_chunk(chunk_doc: Document) -> Document:
            return chunk_doc

        chunked_documents = self.chunk_document(document)

        if not chunked_documents:
            return [document]

        tasks = [process_chunk(chunk_doc) for chunk_doc in chunked_documents]
        return await asyncio.gather(*tasks)
