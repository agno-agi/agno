"""Reader registry for Knowledge.

Manages reader instances: lazy loading, caching, selection by extension/URI,
and read/async_read operations.
"""

import inspect
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from agno.knowledge.document import Document
from agno.knowledge.reader import Reader, ReaderFactory
from agno.utils.log import log_info, log_warning


@dataclass
class ReaderRegistry:
    """Manages reader instances for a Knowledge base."""

    readers: Dict[str, Reader] = field(default_factory=dict)

    # ==========================================
    # PUBLIC METHODS
    # ==========================================

    def construct_readers(self) -> None:
        """Initialize readers dictionary for lazy loading."""
        if self.readers is None:
            self.readers = {}

    def add_reader(self, reader: Reader) -> Reader:
        """Add a custom reader to the registry."""
        if self.readers is None:
            self.readers = {}

        reader_key = self._generate_reader_key(reader)
        self.readers[reader_key] = reader
        return reader

    def get_readers(self) -> Dict[str, Reader]:
        """Get all currently loaded readers (only returns readers that have been used)."""
        if self.readers is None:
            self.readers = {}
        elif not isinstance(self.readers, dict):
            if isinstance(self.readers, list):
                readers_dict: Dict[str, Reader] = {}
                for reader in self.readers:
                    if isinstance(reader, Reader):
                        reader_key = self._generate_reader_key(reader)
                        original_key = reader_key
                        counter = 1
                        while reader_key in readers_dict:
                            reader_key = f"{original_key}_{counter}"
                            counter += 1
                        readers_dict[reader_key] = reader
                self.readers = readers_dict
            else:
                self.readers = {}

        return self.readers

    # ==========================================
    # READER SELECTION
    # ==========================================

    def select_reader(self, extension: str) -> Reader:
        """Select the appropriate reader for a file extension."""
        log_info(f"Selecting reader for extension: {extension}")
        return ReaderFactory.get_reader_for_extension(extension)

    def select_reader_by_extension(
        self, file_extension: str, provided_reader: Optional[Reader] = None
    ) -> Tuple[Optional[Reader], str]:
        """Select a reader based on file extension."""
        if provided_reader:
            return provided_reader, ""

        file_extension = file_extension.lower()
        if file_extension == ".csv":
            return self.csv_reader, "data.csv"
        elif file_extension == ".pdf":
            return self.pdf_reader, ""
        elif file_extension == ".docx":
            return self.docx_reader, ""
        elif file_extension == ".pptx":
            return self.pptx_reader, ""
        elif file_extension == ".json":
            return self.json_reader, ""
        elif file_extension == ".markdown":
            return self.markdown_reader, ""
        elif file_extension in [".xlsx", ".xls"]:
            return self.excel_reader, ""
        else:
            return self.text_reader, ""

    def select_reader_by_uri(self, uri: str, provided_reader: Optional[Reader] = None) -> Optional[Reader]:
        """Select a reader based on URI/file path extension."""
        if provided_reader:
            return provided_reader

        uri_lower = uri.lower()
        if uri_lower.endswith(".pdf"):
            return self.pdf_reader
        elif uri_lower.endswith(".csv"):
            return self.csv_reader
        elif uri_lower.endswith(".docx"):
            return self.docx_reader
        elif uri_lower.endswith(".pptx"):
            return self.pptx_reader
        elif uri_lower.endswith(".json"):
            return self.json_reader
        elif uri_lower.endswith(".markdown"):
            return self.markdown_reader
        elif uri_lower.endswith(".xlsx") or uri_lower.endswith(".xls"):
            return self.excel_reader
        else:
            return self.text_reader

    # ==========================================
    # READ OPERATIONS
    # ==========================================

    def read(
        self,
        reader: Reader,
        source: Union[Path, str, BytesIO],
        name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Document]:
        """Read content using a reader with optional password handling."""
        read_signature = inspect.signature(reader.read)
        if password is not None and "password" in read_signature.parameters:
            if isinstance(source, BytesIO):
                return reader.read(source, name=name, password=password)
            else:
                return reader.read(source, name=name, password=password)
        else:
            if isinstance(source, BytesIO):
                return reader.read(source, name=name)
            else:
                return reader.read(source, name=name)

    async def aread(
        self,
        reader: Reader,
        source: Union[Path, str, BytesIO],
        name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Document]:
        """Read content using a reader's async_read method with optional password handling."""
        read_signature = inspect.signature(reader.async_read)
        if password is not None and "password" in read_signature.parameters:
            return await reader.async_read(source, name=name, password=password)
        else:
            if isinstance(source, BytesIO):
                return await reader.async_read(source, name=name)
            else:
                return await reader.async_read(source, name=name)

    # ==========================================
    # INTERNAL HELPERS
    # ==========================================

    def _generate_reader_key(self, reader: Reader) -> str:
        """Generate a key for a reader instance."""
        if reader.name:
            return f"{reader.name.lower().replace(' ', '_')}"
        else:
            return f"{reader.__class__.__name__.lower().replace(' ', '_')}"

    def _get_reader(self, reader_type: str) -> Optional[Reader]:
        """Get a cached reader or create it if not cached, handling missing dependencies gracefully."""
        if self.readers is None:
            self.readers = {}

        if reader_type not in self.readers:
            try:
                reader = ReaderFactory.create_reader(reader_type)
                if reader:
                    self.readers[reader_type] = reader
                else:
                    return None

            except Exception as e:
                log_warning(f"Cannot create {reader_type} reader {e}")
                return None

        return self.readers.get(reader_type)

    # ==========================================
    # READER PROPERTIES (Lazy Loading)
    # ==========================================

    @property
    def pdf_reader(self) -> Optional[Reader]:
        return self._get_reader("pdf")

    @property
    def csv_reader(self) -> Optional[Reader]:
        return self._get_reader("csv")

    @property
    def excel_reader(self) -> Optional[Reader]:
        return self._get_reader("excel")

    @property
    def docx_reader(self) -> Optional[Reader]:
        return self._get_reader("docx")

    @property
    def pptx_reader(self) -> Optional[Reader]:
        return self._get_reader("pptx")

    @property
    def json_reader(self) -> Optional[Reader]:
        return self._get_reader("json")

    @property
    def markdown_reader(self) -> Optional[Reader]:
        return self._get_reader("markdown")

    @property
    def text_reader(self) -> Optional[Reader]:
        return self._get_reader("text")

    @property
    def website_reader(self) -> Optional[Reader]:
        return self._get_reader("website")

    @property
    def firecrawl_reader(self) -> Optional[Reader]:
        return self._get_reader("firecrawl")

    @property
    def youtube_reader(self) -> Optional[Reader]:
        return self._get_reader("youtube")
