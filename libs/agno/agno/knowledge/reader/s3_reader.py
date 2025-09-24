import asyncio
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.knowledge.reader.text_reader import TextReader
from agno.knowledge.types import ContentType
from agno.utils.log import log_info, logger

try:
    from agno.aws.resource.s3.object import S3Object  # type: ignore
except (ModuleNotFoundError, ImportError):
    raise ImportError("`agno-aws` not installed. Please install using `pip install agno-aws`")

try:
    import textract  # noqa: F401
except ImportError:
    raise ImportError("`textract` not installed. Please install it via `pip install textract`.")

try:
    from pypdf import PdfReader as DocumentReader  # noqa: F401
except ImportError:
    raise ImportError("`pypdf` not installed. Please install it via `pip install pypdf`.")


class S3Reader(Reader):
    """Reader for S3 files"""

    def __init__(self, chunking_strategy: Optional[ChunkingStrategy] = FixedSizeChunking(), **kwargs):
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)

    @classmethod
    def get_supported_chunking_strategies(self) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for S3 readers."""
        return [
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.FILE, ContentType.URL, ContentType.TEXT]

    def read(self, name: Optional[str], s3_object: S3Object) -> List[Document]:
        try:
            log_info(f"Reading S3 file: {s3_object.uri}")

            # Read PDF files
            if s3_object.uri.endswith(".pdf"):
                object_resource = s3_object.get_resource()
                object_body = object_resource.get()["Body"]
                doc_name = (
                    s3_object.name.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
                    if name is None
                    else name
                )
                return PDFReader().read(pdf=BytesIO(object_body.read()), name=doc_name)

            # Read text files
            else:
                doc_name = (
                    s3_object.name.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
                    if name is None
                    else name
                )
                obj_name = s3_object.name.split("/")[-1]
                temporary_file = Path("storage").joinpath(obj_name)
                s3_object.download(temporary_file)
                documents = TextReader().read(file=temporary_file, name=doc_name)

                temporary_file.unlink()
                return documents

        except Exception as e:
            logger.error(f"Error reading: {s3_object.uri}: {e}")

        return []

    async def async_read(self, name: Optional[str], s3_object: S3Object) -> List[Document]:
        """Asynchronously read S3 files by running the synchronous read operation in a thread."""
        return await asyncio.to_thread(self.read, name, s3_object)
