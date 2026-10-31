from datetime import date, datetime
from pathlib import Path
from typing import IO, Any, Iterable, List, Optional, Sequence, Tuple, Union
from uuid import uuid4

from agno.knowledge.document.base import Document
from agno.utils.log import log_debug


def stringify_cell_value(value: Any) -> str:
    """Convert cell value to string, normalizing dates and line endings."""
    if value is None:
        return ""

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    result = str(value)
    # Normalize all line endings to space to preserve row integrity in CSV-like output
    # Must handle CRLF first before individual CR/LF to avoid double-spacing
    result = result.replace("\r\n", " ")  # Windows (CRLF)
    result = result.replace("\r", " ")  # Old Mac (CR)
    result = result.replace("\n", " ")  # Unix (LF)
    return result


def get_workbook_name(file: Union[Path, IO[Any]], name: Optional[str]) -> str:
    """Extract workbook name from file path or name parameter."""
    if name:
        return Path(name).stem
    if isinstance(file, Path):
        return file.stem
    # getattr returns None when attribute exists but is None, so check explicitly
    file_name = getattr(file, "name", None)
    if file_name:
        return Path(file_name).stem
    return "workbook"


def infer_file_extension(file: Union[Path, IO[Any]], name: Optional[str]) -> str:
    """Infer file extension from Path, IO object, or explicit name."""
    if isinstance(file, Path):
        return file.suffix.lower()

    file_name = getattr(file, "name", None)
    if isinstance(file_name, str) and file_name:
        return Path(file_name).suffix.lower()

    if name:
        return Path(name).suffix.lower()

    return ""


def convert_xls_cell_value(cell_value: Any, cell_type: int, datemode: int) -> Any:
    """Convert xlrd cell value to Python type (dates and booleans need conversion)."""
    try:
        import xlrd
    except ImportError:
        return cell_value

    if cell_type == xlrd.XL_CELL_DATE:
        try:
            date_tuple = xlrd.xldate_as_tuple(cell_value, datemode)
            return datetime(*date_tuple)
        except Exception:
            return cell_value
    if cell_type == xlrd.XL_CELL_BOOLEAN:
        return bool(cell_value)
    return cell_value


def row_to_csv_line(row_values: Sequence[Any]) -> str:
    """Convert row values to CSV-like string, trimming trailing empty cells."""
    values = [stringify_cell_value(v) for v in row_values]
    while values and values[-1] == "":
        values.pop()

    return ", ".join(values)


def excel_rows_to_documents(
    *,
    workbook_name: str,
    sheets: Iterable[Tuple[str, int, Iterable[Sequence[Any]]]],
) -> List[Document]:
    """Convert Excel sheet rows to Documents (one per sheet).

    Materializes each sheet into a single document. Prefer
    :func:`excel_rows_to_row_documents` when using row-based chunking so
    large workbooks do not require a full sheet-sized string in memory.
    """
    documents = []
    for sheet_name, sheet_index, rows in sheets:
        lines = []
        for row in rows:
            line = row_to_csv_line(row)
            if line:
                lines.append(line)

        if not lines:
            log_debug(f"Sheet '{sheet_name}' is empty, skipping")
            continue

        documents.append(
            Document(
                name=workbook_name,
                id=str(uuid4()),
                meta_data={"sheet_name": sheet_name, "sheet_index": sheet_index},
                content="\n".join(lines),
            )
        )

    return documents


def excel_rows_to_row_documents(
    *,
    workbook_name: str,
    sheets: Iterable[Tuple[str, int, Iterable[Sequence[Any]]]],
    skip_header: bool = False,
    clean_rows: bool = True,
) -> List[Document]:
    """Stream Excel sheet rows into one Document per non-empty row.

    Mirrors :class:`~agno.knowledge.chunking.row.RowChunking` output
    (``row_number`` metadata, content cleaning, header skip) without
    building a full sheet-level string first.
    """
    from agno.knowledge.chunking.row import RowChunking

    documents: List[Document] = []
    row_chunking = RowChunking(skip_header=skip_header, clean_rows=clean_rows)

    for sheet_name, sheet_index, rows in sheets:
        sheet_id = str(uuid4())
        parent = Document(
            name=workbook_name,
            id=sheet_id,
            meta_data={"sheet_name": sheet_name, "sheet_index": sheet_index},
            content="",
        )

        # Logical index among non-empty CSV lines (matches RowChunking on joined content)
        non_empty_line_index = 0
        header_skipped = False
        sheet_had_rows = False

        for row in rows:
            line = row_to_csv_line(row)
            if not line:
                continue

            sheet_had_rows = True

            if skip_header and not header_skipped:
                header_skipped = True
                continue

            if clean_rows:
                chunk_content = " ".join(line.split())
            else:
                chunk_content = line.strip()

            # Keep numbering parity with RowChunking: index advances for every
            # non-empty source line after header skip, even if cleaning empties it.
            if skip_header:
                row_number = 2 + non_empty_line_index
            else:
                row_number = 1 + non_empty_line_index
            non_empty_line_index += 1

            if not chunk_content:
                continue

            meta_data = parent.meta_data.copy()
            meta_data["row_number"] = row_number
            chunk_id = row_chunking._generate_chunk_id(parent, row_number, chunk_content, prefix="row")
            documents.append(
                Document(
                    id=chunk_id,
                    name=workbook_name,
                    meta_data=meta_data,
                    content=chunk_content,
                )
            )

        if not sheet_had_rows:
            log_debug(f"Sheet '{sheet_name}' is empty, skipping")

    return documents
