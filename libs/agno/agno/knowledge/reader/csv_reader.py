import asyncio
import csv
import io
from pathlib import Path
from typing import IO, Any, List, Optional, Union
from uuid import uuid4

try:
    import aiofiles
except ImportError:
    raise ImportError("`aiofiles` not installed. Please install it with `pip install aiofiles`")

from agno.knowledge.chunking.row import RowChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.reader.utils import stringify_cell_value
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_error


class CSVReader(Reader):
    """Reader for CSV files.

    Converts CSV files to documents with optional chunking support.
    For Excel files (.xlsx, .xls), use ExcelReader instead.

    Args:
        chunking_strategy: Strategy for chunking documents. Default is RowChunking.
        **kwargs: Additional arguments passed to base Reader.

    Example:
        ```python
        from agno.knowledge.reader.csv_reader import CSVReader

        reader = CSVReader()
        docs = reader.read("data.csv")

        # Custom delimiter
        docs = reader.read("data.tsv", delimiter="\\t")
        ```
    """

    def __init__(self, chunking_strategy: Optional[ChunkingStrategy] = RowChunking(), **kwargs):
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for CSV readers."""
        return [
            ChunkingStrategyType.ROW_CHUNKER,
            ChunkingStrategyType.CODE_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        """Get the list of supported content types."""
        return [ContentType.CSV]

    def read(
        self, file: Union[Path, IO[Any]], delimiter: str = ",", quotechar: str = '"', name: Optional[str] = None
    ) -> List[Document]:
        """Read a CSV file and return a list of documents.

        Args:
            file: Path to CSV file or file-like object.
            delimiter: CSV field delimiter. Default is comma.
            quotechar: CSV quote character. Default is double quote.
            name: Optional name override for the document.

        Returns:
            List of Document objects.

        Raises:
            FileNotFoundError: If the file path doesn't exist.
        """
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                log_debug(f"Reading: {file}")
                csv_name = name or file.stem
                file_content: Union[io.TextIOWrapper, io.StringIO] = file.open(
                    newline="", mode="r", encoding=self.encoding or "utf-8"
                )
            else:
                log_debug(f"Reading retrieved file: {getattr(file, 'name', 'BytesIO')}")
                csv_name = name or getattr(file, "name", "csv_file").split(".")[0]
                file.seek(0)
                file_content = io.StringIO(file.read().decode(self.encoding or "utf-8"))

            csv_lines: List[str] = []
            with file_content as csvfile:
                csv_reader = csv.reader(csvfile, delimiter=delimiter, quotechar=quotechar)
                for row in csv_reader:
                    # Normalize line endings in CSV cells to preserve row integrity
                    csv_lines.append(", ".join(stringify_cell_value(cell) for cell in row))

            documents = [
                Document(
                    name=csv_name,
                    id=str(uuid4()),
                    content="\n".join(csv_lines),
                )
            ]
            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents
            return documents
        except FileNotFoundError:
            raise
        except UnicodeDecodeError as e:
            file_desc = getattr(file, "name", str(file)) if isinstance(file, IO) else file
            log_error(f"Encoding error reading {file_desc}: {e}. Try specifying a different encoding.")
            return []
        except Exception as e:
            file_desc = getattr(file, "name", str(file)) if isinstance(file, IO) else file
            log_error(f"Error reading {file_desc}: {e}")
            return []

    async def async_read(
        self,
        file: Union[Path, IO[Any]],
        delimiter: str = ",",
        quotechar: str = '"',
        page_size: int = 1000,
        name: Optional[str] = None,
    ) -> List[Document]:
        """Read a CSV file asynchronously, processing batches of rows concurrently.

        Args:
            file: Path to CSV file or file-like object.
            delimiter: CSV field delimiter. Default is comma.
            quotechar: CSV quote character. Default is double quote.
            page_size: Number of rows per page for large files.
            name: Optional name override for the document.

        Returns:
            List of Document objects.

        Raises:
            FileNotFoundError: If the file path doesn't exist.
        """
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                log_debug(f"Reading async: {file}")
                async with aiofiles.open(file, mode="r", encoding=self.encoding or "utf-8", newline="") as file_content:
                    content = await file_content.read()
                    file_content_io = io.StringIO(content)
                csv_name = name or file.stem
            else:
                log_debug(f"Reading retrieved file async: {getattr(file, 'name', 'BytesIO')}")
                file.seek(0)
                file_content_io = io.StringIO(file.read().decode(self.encoding or "utf-8"))
                csv_name = name or getattr(file, "name", "csv_file").split(".")[0]

            file_content_io.seek(0)
            csv_reader = csv.reader(file_content_io, delimiter=delimiter, quotechar=quotechar)
            rows = list(csv_reader)
            total_rows = len(rows)

            if total_rows <= 10:
                # Small files: single document
                csv_content = " ".join(", ".join(stringify_cell_value(cell) for cell in row) for row in rows)
                documents = [
                    Document(
                        name=csv_name,
                        id=str(uuid4()),
                        content=csv_content,
                    )
                ]
            else:
                # Large files: paginate and process in parallel
                pages = []
                for i in range(0, total_rows, page_size):
                    pages.append(rows[i : i + page_size])

                async def _process_page(page_number: int, page_rows: List[List[str]]) -> Document:
                    """Process a page of rows into a document."""
                    start_row = (page_number - 1) * page_size + 1
                    page_content = " ".join(", ".join(stringify_cell_value(cell) for cell in row) for row in page_rows)

                    return Document(
                        name=csv_name,
                        id=str(uuid4()),
                        meta_data={"page": page_number, "start_row": start_row, "rows": len(page_rows)},
                        content=page_content,
                    )

                documents = await asyncio.gather(
                    *[_process_page(page_number, page) for page_number, page in enumerate(pages, start=1)]
                )

            if self.chunk:
                documents = await self.chunk_documents_async(documents)

            return documents
        except FileNotFoundError:
            raise
        except UnicodeDecodeError as e:
            file_desc = getattr(file, "name", str(file)) if isinstance(file, IO) else file
            log_error(f"Encoding error reading {file_desc}: {e}. Try specifying a different encoding.")
            return []
        except Exception as e:
            file_desc = getattr(file, "name", str(file)) if isinstance(file, IO) else file
            log_error(f"Error reading {file_desc}: {e}")
            return []
