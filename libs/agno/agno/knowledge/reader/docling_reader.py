import asyncio
import json
import shutil
from io import BytesIO
from pathlib import Path
from typing import IO, Any, Dict, List, Optional, Set, Union
from uuid import uuid4

from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader, package_is_importable
from agno.knowledge.reader.utils.url_validation import is_host_allowed, validate_allowed_hosts
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_error

try:
    from docling.datamodel.base_models import DocumentStream, OutputFormat
    from docling.document_converter import DocumentConverter
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
        chunking_strategy: Optional[ChunkingStrategy] = None,
        output_format: str = "markdown",
        converter: Optional[DocumentConverter] = None,
        format_options: Optional[Dict[Any, Any]] = None,
        allowed_hosts: Optional[List[str]] = None,
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
            converter: Optional pre-configured DocumentConverter instance.
            format_options: Optional format options dictionary for DocumentConverter.
            allowed_hosts: Optional hostname allowlist for URL inputs. When set, only URLs
                whose hostname is in the list are converted; others are refused. When None
                (default), all hosts are allowed (backwards compatible).
            **kwargs: Additional arguments passed to the Reader class
        """
        if chunking_strategy is None:
            chunk_size = kwargs.get("chunk_size", 5000)
            chunking_strategy = DocumentChunking(chunk_size=chunk_size)
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)

        self.output_format = OUTPUT_FORMAT_MAP.get(output_format.lower())
        if self.output_format is None:
            raise ValueError(
                f"Invalid output format: '{output_format}'. Valid options: {list(OUTPUT_FORMAT_MAP.keys())}"
            )

        if converter is not None:
            self.converter = converter
        elif format_options is not None:
            self.converter = DocumentConverter(format_options=format_options)
        else:
            self.converter = DocumentConverter()

        self.allowed_hosts: Optional[List[str]] = validate_allowed_hosts(allowed_hosts)

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
        """Get the list of supported content types for Docling readers.

        Based on Docling's InputFormat: DOCX, PPTX, HTML, IMAGE, PDF, ASCIIDOC,
        MD, CSV, XLSX, XML (USPTO/JATS/XBRL), METS_GBS, JSON_DOCLING, AUDIO, VTT, LATEX
        """
        return [
            # DOCX formats
            ContentType.DOCX,
            ContentType.DOTX,
            ContentType.DOCM,
            ContentType.DOTM,
            # PPTX formats
            ContentType.PPTX,
            ContentType.POTX,
            ContentType.PPSX,
            ContentType.POTM,
            ContentType.PPSM,
            ContentType.PPTM,
            # PDF
            ContentType.PDF,
            # Markdown
            ContentType.MARKDOWN,
            # HTML formats
            ContentType.HTML,
            ContentType.HTM,
            ContentType.XHTML,
            # XML formats
            ContentType.XML,
            ContentType.XML_JATS,
            ContentType.XML_XBRL,
            # AsciiDoc formats
            ContentType.ADOC,
            ContentType.ASCIIDOC,
            ContentType.ASC,
            # Spreadsheet formats
            ContentType.CSV,
            ContentType.XLSX,
            ContentType.XLSM,
            # LaTeX formats
            ContentType.LATEX,
            ContentType.LATEX_ALT,
            # Special formats
            ContentType.METS_GBS,
            ContentType.VTT,
            # Image formats
            ContentType.IMAGE_PNG,
            ContentType.IMAGE_JPEG,
            ContentType.IMAGE_JPG,
            ContentType.IMAGE_TIFF,
            ContentType.IMAGE_TIF,
            ContentType.IMAGE_BMP,
            ContentType.IMAGE_WEBP,
            # Audio/Video formats
            ContentType.AUDIO_WAV,
            ContentType.AUDIO_MP3,
            ContentType.AUDIO_M4A,
            ContentType.AUDIO_AAC,
            ContentType.AUDIO_OGG,
            ContentType.AUDIO_FLAC,
            ContentType.VIDEO_MP4,
            ContentType.VIDEO_AVI,
            ContentType.VIDEO_MOV,
        ]

    # Docling transcribes with whichever backend it picked at import time: mlx-whisper on
    # Apple silicon with MPS, native whisper otherwise, and whisper-s2t if configured.
    _SPEECH_BACKENDS = ("whisper", "mlx_whisper", "whisper_s2t")

    @classmethod
    def _media_content_type_values(cls) -> Set[str]:
        """The content types docling sends through its speech pipeline."""
        return {
            ContentType.AUDIO_WAV.value,
            ContentType.AUDIO_MP3.value,
            ContentType.AUDIO_M4A.value,
            ContentType.AUDIO_AAC.value,
            ContentType.AUDIO_OGG.value,
            ContentType.AUDIO_FLAC.value,
            ContentType.VIDEO_MP4.value,
            ContentType.VIDEO_AVI.value,
            ContentType.VIDEO_MOV.value,
        }

    @classmethod
    def get_missing_read_time_packages(cls, content_type: Optional[Union[ContentType, str]] = None) -> List[str]:
        """What transcription needs here, which a package list on its own cannot express.

        Docling loads its speech stack only when asked, so importing this class proves nothing
        about audio and video. Two things gate it and neither is a fixed import: the ffmpeg
        binary has to be on PATH -- docling fails outright without it, whatever else is
        installed -- and any one of several speech backends will do, chosen by hardware rather
        than declared. Requiring one named package would both offer formats that cannot run and
        withdraw formats that can.
        """
        media = cls._media_content_type_values()
        if content_type is not None:
            value = content_type.value if isinstance(content_type, ContentType) else content_type
            if value not in media:
                return []

        missing: List[str] = []
        if shutil.which("ffmpeg") is None:
            missing.append("ffmpeg")
        if not any(package_is_importable(backend) for backend in cls._SPEECH_BACKENDS):
            # Named rather than the backend docling would pick: native whisper is the one that
            # works on every platform, so it is always a correct answer to "what do I install".
            missing.append("openai-whisper")
        return missing

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
            # Declare source type - can be Path, str (URL), or DocumentStream
            source: Union[Path, str, DocumentStream]

            if isinstance(file, Path):
                # Handle Path objects
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                log_debug(f"Reading: {file}")
                doc_name = name or file.stem
                source = file
            elif isinstance(file, str) and file.startswith(("http://", "https://")):
                # Handle URLs - Docling can process them directly
                if not is_host_allowed(file, self.allowed_hosts):
                    log_debug(f"Host not in allowed_hosts, refusing to read: {file}")
                    return []
                url_path = file.split("?")[0]
                doc_name = name or Path(url_path).stem
                log_debug(f"Reading from URL: {file}")
                source = file
            elif isinstance(file, str):
                # Handle local file path strings
                file_path = Path(file)
                if not file_path.exists():
                    raise FileNotFoundError(f"Could not find file: {file_path}")
                log_debug(f"Reading: {file_path}")
                doc_name = name or file_path.stem
                source = file_path
            elif isinstance(file, BytesIO):
                # Handle BytesIO objects
                log_debug(f"Reading uploaded file: {getattr(file, 'name', 'BytesIO')}")
                if name and "." in name:
                    doc_name = Path(name).stem
                    stream_name = name
                else:
                    doc_name = name or getattr(file, "name", "docling_file").split(".")[0]
                    stream_name = f"{doc_name}"
                source = DocumentStream(name=stream_name, stream=file)
            else:
                raise ValueError("Unsupported file type.")

            result = self.converter.convert(source)

            if self.output_format == OutputFormat.TEXT:
                doc_content = result.document.export_to_text()
            elif self.output_format == OutputFormat.JSON:
                doc_content = json.dumps(result.document.export_to_dict(), ensure_ascii=False)
            elif self.output_format == OutputFormat.YAML:
                import yaml

                doc_content = yaml.safe_dump(result.document.export_to_dict(), allow_unicode=True)
            elif self.output_format == OutputFormat.HTML:
                doc_content = result.document.export_to_html()
            elif self.output_format == OutputFormat.HTML_SPLIT_PAGE:
                doc_content = result.document.export_to_html(split_page_view=True)
            elif self.output_format == OutputFormat.DOCTAGS:
                doc_content = result.document.export_to_doctags()
            elif self.output_format == OutputFormat.VTT:
                doc_content = result.document.export_to_vtt()
                if doc_content.strip() == "WEBVTT":
                    log_debug(f"VTT export contains only headers for: {doc_name}")
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

        except (FileNotFoundError, ValueError):
            raise

        except Exception as e:
            log_error(f"Error converting document: {file}: {str(e)}")
            return []

    async def async_read(self, file: Union[Path, str, IO[Any]], name: Optional[str] = None) -> List[Document]:
        """Asynchronously read a docling file and return a list of documents."""
        try:
            return await asyncio.to_thread(self.read, file, name)
        except (FileNotFoundError, ValueError):
            raise
        except Exception as e:
            log_error(f"Error reading file asynchronously: {str(e)}")
            return []
