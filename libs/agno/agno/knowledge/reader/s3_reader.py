import asyncio
from io import BytesIO
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_info, logger

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
            ChunkingStrategyType.FIXED_SIZE_CHUNKING,
            ChunkingStrategyType.AGENTIC_CHUNKING,
            ChunkingStrategyType.DOCUMENT_CHUNKING,
            ChunkingStrategyType.RECURSIVE_CHUNKING,
            ChunkingStrategyType.SEMANTIC_CHUNKING,
        ]

    @classmethod
    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.FILE, ContentType.URL, ContentType.TEXT]

    def read(self, name: Optional[str], s3_object: S3Object) -> List[Document]:
        try:
            log_info(f"Reading S3 file: {s3_object.uri}")

            if s3_object.uri.endswith(".pdf"):
                return S3PDFReader().read(name, s3_object)
            else:
                return S3TextReader().read(name, s3_object)

        except Exception as e:
            logger.error(f"Error reading: {s3_object.uri}: {e}")
        return []

    async def async_read(self, name: Optional[str], s3_object: S3Object) -> List[Document]:
        """Asynchronously read S3 files by running the synchronous read operation in a thread."""
        return await asyncio.to_thread(self.read, name, s3_object)


class S3TextReader(Reader):
    """Reader for text files on S3"""

    def get_supported_chunking_strategies(self) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for S3 text readers."""
        return [
            ChunkingStrategyType.AGENTIC_CHUNKING,
            ChunkingStrategyType.DOCUMENT_CHUNKING,
            ChunkingStrategyType.RECURSIVE_CHUNKING,
        ]

    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.TEXT]

    def read(self, name: Optional[str], s3_object: S3Object) -> List[Document]:
        try:
            log_info(f"Reading text file: {s3_object.uri}")

            doc_name = s3_object.name.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
            if name is not None:
                doc_name = name
            obj_name = s3_object.name.split("/")[-1]
            temporary_file = Path("storage").joinpath(obj_name)
            s3_object.download(temporary_file)

            log_info(f"Parsing: {temporary_file}")
            doc_content = textract.process(temporary_file)
            documents = [
                Document(
                    name=doc_name,
                    id=doc_name,
                    content=doc_content.decode("utf-8"),
                )
            ]
            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents

            log_debug(f"Deleting: {temporary_file}")
            temporary_file.unlink()
            return documents
        except Exception as e:
            logger.error(f"Error reading: {s3_object.uri}: {e}")
        return []

    async def async_read(self, name: Optional[str], s3_object: S3Object) -> List[Document]:
        """Asynchronously read text files from S3 by running the synchronous read operation in a thread.

        Args:
            s3_object (S3Object): The S3 object to read

        Returns:
            List[Document]: List of documents from the text file
        """
        return await asyncio.to_thread(self.read, name, s3_object)


class S3PDFReader(Reader):
    """Reader for PDF files on S3"""

    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.FILE]

    def read(self, name: Optional[str], s3_object: S3Object) -> List[Document]:
        try:
            log_info(f"Reading PDF file: {s3_object.uri}")

            object_resource = s3_object.get_resource()
            object_body = object_resource.get()["Body"]
            doc_name = s3_object.name.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
            if name is not None:
                doc_name = name
            doc_reader = DocumentReader(BytesIO(object_body.read()))
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
        except Exception:
            raise

    async def async_read(self, name: Optional[str], s3_object: S3Object) -> List[Document]:
        """Asynchronously read PDF files from S3 by running the synchronous read operation in a thread.

        Args:
            s3_object (S3Object): The S3 object to read

        Returns:
            List[Document]: List of documents from the PDF file
        """
        return await asyncio.to_thread(self.read, name, s3_object)
