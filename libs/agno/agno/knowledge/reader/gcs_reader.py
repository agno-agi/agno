import asyncio
from io import BytesIO
from typing import List, Optional
from uuid import uuid4

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_info

try:
    from google.cloud import storage  # type: ignore
except ImportError:
    raise ImportError("`google-cloud-storage` not installed. Please install it via `pip install google-cloud-storage`.")

try:
    from pypdf import PdfReader as DocumentReader
except ImportError:
    raise ImportError("`pypdf` not installed. Please install it via `pip install pypdf`.")


class GCSReader(Reader):
    def __init__(self, chunking_strategy: Optional[ChunkingStrategy] = FixedSizeChunking(), **kwargs):
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)

    @classmethod
    def get_supported_chunking_strategies(self) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for GCS readers."""
        return [
            ChunkingStrategyType.FIXED_SIZE_CHUNKING,
            ChunkingStrategyType.AGENTIC_CHUNKING,
            ChunkingStrategyType.DOCUMENT_CHUNKING,
            ChunkingStrategyType.RECURSIVE_CHUNKING,
            ChunkingStrategyType.SEMANTIC_CHUNKING,
        ]

    @classmethod
    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.FILE, ContentType.URL]

    def read(self, name: Optional[str], blob: storage.Blob) -> List[Document]:
        log_info(f"Reading: gs://{blob.bucket.name}/{blob.name}")
        data = blob.download_as_bytes()
        doc_name = blob.name.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
        if name is not None:
            doc_name = name
        doc_reader = DocumentReader(BytesIO(data))
        documents = [
            Document(
                name=doc_name,
                id=str(uuid4()),
                meta_data={"page": page_number},
                content=page.extract_text(),
            )
            for page_number, page in enumerate(doc_reader.pages, start=1)
        ]
        if self.chunk:
            chunked_documents = []
            for document in documents:
                chunked_documents.extend(self.chunk_document(document))
            return chunked_documents
        return documents

    async def async_read(self, name: Optional[str], blob: storage.Blob) -> List[Document]:
        return await asyncio.to_thread(self.read, name, blob)
