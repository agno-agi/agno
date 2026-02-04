import asyncio
import json
from pathlib import Path
from typing import IO, Any, List, Optional, Union
from uuid import uuid4

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_error


class JSONReader(Reader):
    """Reader for JSON files"""

    chunk: bool = False

    def __init__(self, chunking_strategy: Optional[ChunkingStrategy] = FixedSizeChunking(), **kwargs):
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for JSON readers."""
        return [
            ChunkingStrategyType.CODE_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.JSON]

    def read(self, path: Union[Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        try:
            if isinstance(path, Path):
                if not path.exists():
                    raise FileNotFoundError(f"Could not find file: {path}")
                log_debug(f"Reading: {path}")
                json_name = name or path.stem
                json_contents = json.loads(path.read_text(encoding=self.encoding or "utf-8"))
            elif hasattr(path, "seek") and hasattr(path, "read"):
                log_debug(f"Reading uploaded file: {getattr(path, 'name', 'BytesIO')}")
                json_name = name or getattr(path, "name", "json_file").split(".")[0]
                path.seek(0)
                json_contents = json.load(path)
            else:
                raise ValueError("Unsupported file type. Must be Path or file-like object.")

            if isinstance(json_contents, dict):
                json_contents = [json_contents]

            documents = [
                Document(
                    name=json_name,
                    id=str(uuid4()),
                    meta_data={"page": page_number},
                    content=json.dumps(content),
                )
                for page_number, content in enumerate(json_contents, start=1)
            ]
            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents
            return documents
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            raise
        except Exception as e:
            log_error(f"Error reading: {path}: {e}")
            raise

    async def async_read(self, path: Union[Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        """Asynchronously read JSON files."""
        return await asyncio.to_thread(self.read, path, name)
