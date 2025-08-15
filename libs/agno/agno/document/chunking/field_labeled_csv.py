import csv
import io
import re
from typing import List, Optional, Tuple, Union

from agno.document.base import Document
from agno.document.chunking.strategy import ChunkingStrategy
from agno.utils.log import log_error

class FieldLabeledCSVChunking(ChunkingStrategy):
    """Chunking strategy that converts CSV content to field-labeled text format."""

    def __init__(
        self,
        chunk_title: Optional[Union[str, List[str]]] = None,
        format_headers: bool = False,
        field_names: Optional[List[str]] = None,
        entry_separator: str = "\n\n",
        delimiter: str = ",",
    ):
        self.chunk_title = chunk_title
        self.format_headers = format_headers
        self.field_names = field_names or []
        self.entry_separator = entry_separator
        self.delimiter = delimiter

    def _format_field_name(self, field_name: str) -> str:
        if not self.format_headers:
            return field_name

        formatted = field_name.replace("_", " ").title()
        return formatted

    def _get_title_for_entry(self, entry_index: int) -> Optional[str]:
        if self.chunk_title is None:
            return None

        if isinstance(self.chunk_title, str):
            return self.chunk_title

        if isinstance(self.chunk_title, list):
            return self.chunk_title[entry_index % len(self.chunk_title)]

        return None

    def _convert_row_to_labeled_text(self, headers: List[str], row: List[str], entry_index: int = 0) -> str:
        lines = []

        title = self._get_title_for_entry(entry_index)
        if title:
            lines.append(title)

        for i, (header, value) in enumerate(zip(headers, row)):
            if not value or value.strip() == "":
                continue

            if self.field_names and i < len(self.field_names):
                formatted_header = self.field_names[i]
            else:
                formatted_header = self._format_field_name(header)
            lines.append(f"{formatted_header}: {value}")

        return "\n".join(lines)

    def clean_text(self, text: str) -> str:
        """Clean up the text content"""
        # For CSV, normalize newlines and remove null characters
        cleaned_text = re.sub(r"\n\n+", "\n", text)  # Multiple newlines -> single newline
        cleaned_text = re.sub(r"\r\n", "\n", cleaned_text)  # Windows line endings -> Unix
        cleaned_text = re.sub(r"\r", "\n", cleaned_text)  # Mac line endings -> Unix
        cleaned_text = cleaned_text.replace("\x00", "\ufffd")  # Replace null chars
        return cleaned_text.strip()

    def _parse_csv_content(self, content: str) -> Tuple[List[str], List[List[str]]]:
        try:
            csv_file = io.StringIO(self.clean_text(content))
            csv_reader = csv.reader(csv_file, delimiter=self.delimiter)

            # Read all rows
            rows = list(csv_reader)

            if not rows:
                raise ValueError("CSV content is empty")

            # Determine headers and data rows based on chunk_title
            if self.chunk_title is not None:
                # When chunk_title is provided, first row is headers
                headers = [header.strip() for header in rows[0]]

                if not headers or all(not h for h in headers):
                    raise ValueError("CSV headers are missing or empty")

                # Data starts from second row
                data_rows = rows[1:] if len(rows) > 1 else []
            else:
                # When no chunk_title, generate generic field names
                first_row = rows[0] if rows else []
                headers = [f"Field_{i + 1}" for i in range(len(first_row))]

                # All rows are data
                data_rows = rows

            return headers, data_rows

        except csv.Error as e:
            raise ValueError(f"Invalid CSV format: {e}")
        except Exception as e:
            raise ValueError(f"Error parsing CSV content: {e}")

    def _normalize_row_length(self, row: List[str], expected_length: int) -> List[str]:
        """Normalize row length to match headers length."""
        if len(row) < expected_length:
            # Pad with empty strings
            row.extend([""] * (expected_length - len(row)))
        elif len(row) > expected_length:
            # Truncate extra columns
            row = row[:expected_length]

        return row

    def chunk(self, document: Document) -> List[Document]:
        if not document or not document.content:
            return [document] if document else []

        if not isinstance(document.content, str):
            raise ValueError("Document content must be a string")

        try:
            headers, data_rows = self._parse_csv_content(document.content)

            if not data_rows:
                return [document]

            labeled_content_parts = []
            entry_index = 0
            for row in data_rows:
                # Skip completely empty rows
                if not any(cell.strip() for cell in row):
                    continue

                normalized_row = self._normalize_row_length([cell.strip() for cell in row], len(headers))

                labeled_text = self._convert_row_to_labeled_text(headers, normalized_row, entry_index)

                if labeled_text.strip():
                    labeled_content_parts.append(labeled_text)
                    entry_index += 1

            if not labeled_content_parts:
                return [document]

            labeled_content = self.entry_separator.join(labeled_content_parts)

            chunk_meta_data = document.meta_data.copy() if document.meta_data else {}
            chunk_meta_data.update(
                {
                    "chunk": 1,
                    "chunk_size": len(labeled_content),
                    "total_rows": len(labeled_content_parts),
                    "headers": headers,
                }
            )

            chunk_id = None
            if document.id:
                chunk_id = f"{document.id}_field_labeled"
            elif document.name:
                chunk_id = f"{document.name}_field_labeled"

            labeled_document = Document(
                id=chunk_id,
                name=document.name,
                meta_data=chunk_meta_data,
                content=labeled_content,
            )

            return [labeled_document]
        except Exception as e:
            log_error(f"Unexpected error in FieldLabeledCSVChunking: {e}. Returning original document.")
            return [document]
