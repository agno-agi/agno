import csv
import io
import re
from typing import List, Optional, Tuple

from agno.document.base import Document
from agno.document.chunking.strategy import ChunkingStrategy
from agno.utils.log import log_error, log_warning


class FieldLabeledCSVChunking(ChunkingStrategy):
    """Chunking strategy that converts CSV content to field-labeled text format."""

    def __init__(
        self,
        chunk_title: Optional[str] = None,
        format_headers: bool = True,
        skip_empty_values: bool = True,
        field_names: Optional[List[str]] = None,
        entry_separator: str = "\n\n",
        delimiter: str = ",",
    ):
        self.chunk_title = chunk_title
        self.format_headers = format_headers
        self.skip_empty_values = skip_empty_values
        self.field_names = field_names or []
        self.entry_separator = entry_separator
        self.delimiter = delimiter

    def clean_text(self, text: str) -> str:
        """Clean up the field name"""
        # For CSV, we only want to normalize multiple consecutive newlines
        # but preserve single newlines that separate rows
        cleaned_text = re.sub(r"\n\n+", "\n", text)  # Multiple newlines -> single newline
        cleaned_text = re.sub(r"\r\n", "\n", cleaned_text)  # Windows line endings -> Unix
        cleaned_text = re.sub(r"\r", "\n", cleaned_text)  # Mac line endings -> Unix

        return cleaned_text.strip()

    def _format_field_name(self, field_name: str) -> str:
        """Format a field name for display."""
        if not self.format_headers:
            return field_name

        # Replace underscores with spaces and apply title case
        formatted = field_name.replace("_", " ").title()
        return formatted

    def _get_title_for_entry(self, entry_index: int) -> Optional[str]:
        """Get the appropriate title for a given entry index."""
        if self.chunk_title is None:
            return None

        if isinstance(self.chunk_title, str):
            # Single string - use for all entries
            return self.chunk_title

        if isinstance(self.chunk_title, list):
            if len(self.chunk_title) == 1:
                # Single item in list - use for all entries
                return self.chunk_title[0]
            elif len(self.chunk_title) > 1:
                # Multiple items - cycle through them
                return self.chunk_title[entry_index % len(self.chunk_title)]

        return None

    def _convert_row_to_labeled_text(self, headers: List[str], row: List[str], entry_index: int = 0) -> str:
        """Convert a CSV row to field-labeled text format."""
        lines = []

        # Add title if provided
        title = self._get_title_for_entry(entry_index)
        if title:
            lines.append(title)

        # Process each field
        for i, (header, value) in enumerate(zip(headers, row)):
            # Skip empty values if configured to do so
            if self.skip_empty_values and (not value or value.strip() == ""):
                continue

            # Use custom field name if provided, otherwise format the header
            if self.field_names and i < len(self.field_names):
                formatted_header = self.field_names[i]
            else:
                formatted_header = self._format_field_name(header)
            lines.append(f"{formatted_header}: {value}")

        return "\n".join(lines)

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
        """Normalize row length to match headers length.

        Args:
            row: Row values
            expected_length: Expected number of columns

        Returns:
            Normalized row with correct length
        """
        if len(row) < expected_length:
            # Pad with empty strings
            row.extend([""] * (expected_length - len(row)))
        elif len(row) > expected_length:
            # Truncate extra columns
            row = row[:expected_length]

        return row

    def chunk(self, document: Document) -> List[Document]:
        """Convert CSV document content to field-labeled text format.

        Args:
            document: Document containing CSV content as a string

        Returns:
            List of Document objects with field-labeled text content
        """
        # Handle empty or None document
        if not document or not document.content:
            return [document] if document else []

        if not isinstance(document.content, str):
            raise ValueError("Document content must be a string")

        try:
            # Parse CSV content
            headers, data_rows = self._parse_csv_content(document.content)

            if not data_rows:
                # Return original document if no data rows
                return [document]

            # Convert rows to field-labeled text
            labeled_content_parts = []
            entry_index = 0

            for row in data_rows:
                if not any(cell.strip() for cell in row):  # Skip completely empty rows
                    continue

                # Handle empty cells
                normalized_row = self._normalize_row_length([cell.strip() for cell in row], len(headers))

                # Convert to field-labeled text with entry index for title cycling
                labeled_text = self._convert_row_to_labeled_text(headers, normalized_row, entry_index)

                if labeled_text.strip():  # Only add non-empty entries
                    labeled_content_parts.append(labeled_text)
                    entry_index += 1

            if not labeled_content_parts:
                # Return original document if no valid labeled content generated
                return [document]

            # Create new document with field-labeled content
            labeled_content = self.entry_separator.join(labeled_content_parts)

            # Prepare metadata following established patterns
            chunk_meta_data = document.meta_data.copy() if document.meta_data else {}
            chunk_meta_data.update(
                {
                    "source_type": "field_labeled_csv",
                    "total_rows": len(labeled_content_parts),
                    "headers": headers,
                    "chunking_strategy": "field_labeled_csv",
                    "chunk": 1,  # Single chunk containing all field-labeled entries
                    "chunk_size": len(labeled_content),
                }
            )

            # Generate chunk ID following established pattern
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

        except ValueError as e:
            # Log warning and return original document as fallback
            log_warning(f"Failed to process CSV content: {e}. Returning original document.")
            return [document]
        except Exception as e:
            # Log error for any other unexpected errors
            log_error(f"Unexpected error in FieldLabeledCSVChunking: {e}. Returning original document.")
            return [document]
