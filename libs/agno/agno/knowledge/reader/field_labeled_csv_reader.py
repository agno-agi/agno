import asyncio
import csv
import io
from pathlib import Path
from typing import IO, Any, List, Optional, Union

try:
    import aiofiles
except ImportError:
    raise ImportError("`aiofiles` not installed. Please install it with `pip install aiofiles`")

from agno.knowledge.chunking.strategy import ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import logger


class FieldLabeledCSVReader(Reader):
    """Reader for CSV files that converts each row to a field-labeled document."""

    def __init__(
        self,
        chunk_title: Optional[Union[str, List[str]]] = None,
        field_names: Optional[List[str]] = None,
        format_headers: bool = True,
        skip_empty_fields: bool = True,
        **kwargs,
    ):
        super().__init__(chunk=False, chunking_strategy=None, **kwargs)
        self.chunk_title = chunk_title
        self.field_names = field_names or []
        self.format_headers = format_headers
        self.skip_empty_fields = skip_empty_fields

        logger.info(f"FieldLabeledCSVReader initialized - chunk_title: {chunk_title}, field_names: {self.field_names}")

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        """Chunking is not supported - each row is already a logical document unit."""
        return []

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        """Get the list of supported content types."""
        return [ContentType.CSV, ContentType.XLSX, ContentType.XLS]

    def _format_field_name(self, field_name: str) -> str:
        """Format field name to be more readable."""
        if not self.format_headers:
            return field_name.strip()

        # Replace underscores with spaces and title case
        formatted = field_name.replace("_", " ").strip().title()
        return formatted

    def _get_title_for_entry(self, entry_index: int) -> Optional[str]:
        """Get title for a specific entry."""
        if self.chunk_title is None:
            return None

        if isinstance(self.chunk_title, str):
            return self.chunk_title

        if isinstance(self.chunk_title, list) and self.chunk_title:
            return self.chunk_title[entry_index % len(self.chunk_title)]

        return None

    def _convert_row_to_labeled_text(self, headers: List[str], row: List[str], entry_index: int) -> str:
        """
        Convert a CSV row to field-labeled text format.

        Args:
            headers: Column headers
            row: Data row values
            entry_index: Index of this entry (for title rotation)

        Returns:
            Formatted text with field labels
        """
        lines = []

        title = self._get_title_for_entry(entry_index)
        if title:
            lines.append(title)

        for i, (header, value) in enumerate(zip(headers, row)):
            clean_value = value.strip() if value else ""

            if self.skip_empty_fields and not clean_value:
                continue

            if self.field_names and i < len(self.field_names):
                field_name = self.field_names[i]
            else:
                field_name = self._format_field_name(header)

            lines.append(f"{field_name}: {clean_value}")

        return "\n".join(lines)

    def read(
        self, file: Union[Path, IO[Any]], delimiter: str = ",", quotechar: str = '"', name: Optional[str] = None
    ) -> List[Document]:
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                logger.info(f"Reading: {file}")
                file_content = file.open(newline="", mode="r", encoding=self.encoding or "utf-8")
            else:
                logger.info(f"Reading retrieved file: {name or file.name}")
                file.seek(0)
                file_content = io.StringIO(file.read().decode("utf-8"))  # type: ignore

            csv_name = name or (
                Path(file.name).stem
                if isinstance(file, Path)
                else (getattr(file, "name", "csv_file").split(".")[0] if hasattr(file, "name") else "csv_file")
            )

            documents = []

            with file_content as csvfile:
                csv_reader = csv.reader(csvfile, delimiter=delimiter, quotechar=quotechar)

                # Read all rows
                rows = list(csv_reader)

                if not rows:
                    logger.warning("CSV file is empty")
                    return []

                # First row is headers
                headers = [header.strip() for header in rows[0]]
                logger.info(f"Found {len(headers)} headers: {headers}")

                data_rows = rows[1:] if len(rows) > 1 else []
                logger.info(f"Processing {len(data_rows)} data rows")

                for row_index, row in enumerate(data_rows):
                    # Ensure row has same length as headers (pad or truncate)
                    normalized_row = row[: len(headers)]  # Truncate if too long
                    while len(normalized_row) < len(headers):  # Pad if too short
                        normalized_row.append("")

                    # Convert row to labeled text
                    labeled_text = self._convert_row_to_labeled_text(headers, normalized_row, row_index)

                    if labeled_text.strip():
                        # Create document for this row
                        doc_id = f"{csv_name}_row_{row_index + 1}"

                        document = Document(
                            id=doc_id,
                            name=csv_name,
                            meta_data={
                                "row_index": row_index,
                                "headers": headers,
                                "total_rows": len(data_rows),
                                "source": "field_labeled_csv_reader",
                            },
                            content=labeled_text,
                        )

                        documents.append(document)
                        logger.debug(f"Created document for row {row_index + 1}: {len(labeled_text)} chars")

            logger.info(f"Successfully created {len(documents)} labeled documents from CSV")
            return documents

        except Exception as e:
            logger.error(f"Error reading: {getattr(file, 'name', str(file)) if isinstance(file, IO) else file}: {e}")
            return []

    async def async_read(
        self,
        file: Union[Path, IO[Any]],
        delimiter: str = ",",
        quotechar: str = '"',
        page_size: int = 1000,
        name: Optional[str] = None,
    ) -> List[Document]:
        try:
            # Handle file input
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                logger.info(f"Reading async: {file}")
                async with aiofiles.open(file, mode="r", encoding=self.encoding or "utf-8", newline="") as file_content:
                    content = await file_content.read()
                    file_content_io = io.StringIO(content)
            else:
                logger.info(f"Reading retrieved file async: {name or file.name}")
                file.seek(0)
                file_content_io = io.StringIO(file.read().decode("utf-8"))  # type: ignore

            csv_name = name or (
                Path(file.name).stem
                if isinstance(file, Path)
                else (getattr(file, "name", "csv_file").split(".")[0] if hasattr(file, "name") else "csv_file")
            )

            file_content_io.seek(0)
            csv_reader = csv.reader(file_content_io, delimiter=delimiter, quotechar=quotechar)
            rows = list(csv_reader)

            if not rows:
                logger.warning("CSV file is empty")
                return []

            # First row is headers
            headers = [header.strip() for header in rows[0]]
            logger.info(f"Found {len(headers)} headers: {headers}")

            # Process data rows
            data_rows = rows[1:] if len(rows) > 1 else []
            total_rows = len(data_rows)
            logger.info(f"Processing {total_rows} data rows")

            # For small files, process all at once
            if total_rows <= 10:
                documents = []
                for row_index, row in enumerate(data_rows):
                    normalized_row = row[: len(headers)]
                    while len(normalized_row) < len(headers):
                        normalized_row.append("")

                    labeled_text = self._convert_row_to_labeled_text(headers, normalized_row, row_index)

                    if labeled_text.strip():
                        document = Document(
                            id=f"{csv_name}_row_{row_index + 1}",
                            name=csv_name,
                            meta_data={
                                "row_index": row_index,
                                "headers": headers,
                                "total_rows": total_rows,
                                "source": "field_labeled_csv_reader",
                            },
                            content=labeled_text,
                        )
                        documents.append(document)
            else:
                pages = []
                for i in range(0, total_rows, page_size):
                    pages.append(data_rows[i : i + page_size])

                async def _process_page(page_number: int, page_rows: List[List[str]]) -> List[Document]:
                    """Process a page of rows into documents"""
                    page_documents = []
                    start_row_index = (page_number - 1) * page_size

                    for i, row in enumerate(page_rows):
                        row_index = start_row_index + i

                        normalized_row = row[: len(headers)]
                        while len(normalized_row) < len(headers):
                            normalized_row.append("")

                        labeled_text = self._convert_row_to_labeled_text(headers, normalized_row, row_index)

                        if labeled_text.strip():
                            document = Document(
                                id=f"{csv_name}_row_{row_index + 1}",
                                name=csv_name,
                                meta_data={
                                    "row_index": row_index,
                                    "headers": headers,
                                    "total_rows": total_rows,
                                    "page": page_number,
                                    "source": "field_labeled_csv_reader",
                                },
                                content=labeled_text,
                            )
                            page_documents.append(document)

                    return page_documents

                page_results = await asyncio.gather(
                    *[_process_page(page_number, page) for page_number, page in enumerate(pages, start=1)]
                )

                documents = [doc for page_docs in page_results for doc in page_docs]

            logger.info(f"Successfully created {len(documents)} labeled documents from CSV")
            return documents

        except Exception as e:
            logger.error(
                f"Error reading async: {getattr(file, 'name', str(file)) if isinstance(file, IO) else file}: {e}"
            )
            return []
