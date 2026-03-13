import asyncio
import json
from pathlib import Path
from typing import IO, Any, List, Optional, Union
from uuid import uuid4

import yaml

from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_error

try:
    from docling.datamodel.base_models import OutputFormat  # type: ignore
    from docling.document_converter import DocumentConverter  # type: ignore
except ImportError:
    raise ImportError("The `docling` package is not installed. Please install it via `pip install docling`.")


# Mapping of string values to OutputFormat enum
OUTPUT_FORMAT_MAP = {
    "markdown": OutputFormat.MARKDOWN,
    "text": OutputFormat.TEXT,
    "json": OutputFormat.JSON,
    "yaml": OutputFormat.YAML,
    "html": OutputFormat.HTML,
    "html_split_page": OutputFormat.HTML_SPLIT_PAGE,
    "doctags": OutputFormat.DOCTAGS,
    "vtt": OutputFormat.VTT,
}


class DoclingReader(Reader):
    """Reader for various document formats using IBM's Docling library.

    Docling supports a wide range of input formats like:
    - Documents: PDF, DOCX, XLSX, PPTX, Markdown, HTML, AsciiDoc, LaTeX, CSV
    - Images: PNG, JPEG, TIFF, BMP, WEBP
    - Audio: WAV, MP3, M4A, AAC, OGG, FLAC
    - Video: MP4, AVI, MOV
    - Other: WebVTT, JSON, XML

    Converts all formats into a unified DoclingDocument representation,
    then exports to markdown, text, json, html, doctags, etc.
    """

    def __init__(
        self,
        chunking_strategy: Optional[ChunkingStrategy] = DocumentChunking(),
        output_format: str = "markdown",
        **kwargs,
    ):
        """Initialize the DoclingReader.

        Args:
            chunking_strategy: Strategy to use for chunking the documents
            output_format: Output format for Docling conversion. Options:
                - "markdown" (default): Preserves structure and formatting
                - "text": Plain text output
                - "json": Lossless serialization with document structure
                - "html": HTML with image embedding/referencing support
                - "doctags": Markup format with full content and layout characteristics
                - "vtt": WebVTT subtitle format
                - "yaml": YAML serialization
                - "html_split_page": HTML with page splitting
            **kwargs: Additional arguments passed to the Reader class
        """
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)

        self.output_format = OUTPUT_FORMAT_MAP.get(output_format.lower())
        if self.output_format is None:
            raise ValueError(
                f"Invalid output format: '{output_format}'. Valid options: {list(OUTPUT_FORMAT_MAP.keys())}"
            )

        self.converter = DocumentConverter()

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for Docling readers."""
        return [
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.CODE_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        """Get the list of supported content types for Docling readers."""
        return [
            ContentType.DOCX,
            ContentType.PPTX,
            ContentType.PDF,
            ContentType.MARKDOWN,
            ContentType.CSV,
            ContentType.XLSX,
            ContentType.URL,
            ContentType.VTT,
            ContentType.IMAGE_TIF,
            ContentType.IMAGE_PNG,
            ContentType.IMAGE_JPEG,
            ContentType.IMAGE_JPG,
            ContentType.IMAGE_TIFF,
            ContentType.IMAGE_BMP,
            ContentType.IMAGE_WEBP,
            ContentType.AUDIO_WAV,
            ContentType.AUDIO_MP3,
            ContentType.AUDIO_M4A,
            ContentType.AUDIO_AAC,
            ContentType.AUDIO_OGG,
            ContentType.AUDIO_FLAC,
            ContentType.AUDIO_MP4,
            ContentType.AUDIO_AVI,
            ContentType.AUDIO_MOV,
            # TODO: Add more supported content types
        ]

    def read(self, file: Union[Path, str, IO[Any]], name: Optional[str] = None) -> List[Document]:
        """Reads document using Docling.

        Args:
            file: Path to file, file path string, URL, or file-like object.
                 URLs starting with http:// or https:// are supported.
            name: Optional name for the document

        Returns:
            List of Document objects
        """
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                log_debug(f"Reading: {file}")
                doc_name = name or file.stem
            elif isinstance(file, str) and file.startswith(("http://", "https://")):
                url_path = file.split("?")[0]
                doc_name = name or Path(url_path).stem
                log_debug(f"Reading from URL: {file}")
            else:
                log_debug(f"Reading uploaded file: {getattr(file, 'name', 'BytesIO')}")
                doc_name = name or getattr(file, "name", "docling_file").split(".")[0]

            result = self.converter.convert(str(file))

            if self.output_format == OutputFormat.TEXT:
                doc_content = result.document.export_to_text()
            elif self.output_format == OutputFormat.JSON:
                doc_content = json.dumps(result.document.export_to_dict())
            elif self.output_format == OutputFormat.YAML:
                doc_content = yaml.safe_dump(result.document.export_to_dict())
            elif self.output_format == OutputFormat.HTML:
                doc_content = result.document.export_to_html()
            elif self.output_format == OutputFormat.HTML_SPLIT_PAGE:
                doc_content = result.document.export_to_html(split_page_view=True)
            elif self.output_format == OutputFormat.DOCTAGS:
                doc_content = result.document.export_to_doctags()
            elif self.output_format == OutputFormat.VTT:
                doc_content = result.document.export_to_vtt()
            else:
                doc_content = result.document.export_to_markdown()

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
            log_error(f"Error reading: {file}: {e}")
            return []

    async def async_read(self, file: Union[Path, str, IO[Any]], name: Optional[str] = None) -> List[Document]:
        """Asynchronously read a docling file and return a list of documents."""
        try:
            return await asyncio.to_thread(self.read, file, name)
        except Exception as e:
            log_error(f"Error reading file asynchronously: {e}")
            return []
