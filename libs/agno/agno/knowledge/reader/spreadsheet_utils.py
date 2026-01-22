from datetime import date, datetime
from pathlib import Path
from typing import IO, Any, Iterable, List, Optional, Sequence, Tuple, Union
from uuid import uuid4

from agno.knowledge.document.base import Document
from agno.utils.log import log_debug


def get_workbook_name(file: Union[Path, IO[Any]], name: Optional[str]) -> str:
    """Extract workbook name from file path or name parameter.

    Priority: explicit name > file path stem > file object name attribute > "workbook"
    """
    if name:
        return Path(name).stem
    if isinstance(file, Path):
        return file.stem
    return Path(getattr(file, "name", "workbook")).stem


def infer_file_extension(file: Union[Path, IO[Any]], name: Optional[str]) -> str:
    """Infer file extension from Path, IO object, or explicit name.

    Returns lowercase extension including the dot (e.g., ".xlsx", ".csv").
    Returns empty string if extension cannot be determined.
    """
    if isinstance(file, Path):
        return file.suffix.lower()

    file_name = getattr(file, "name", None)
    if isinstance(file_name, str) and file_name:
        return Path(file_name).suffix.lower()

    if name:
        return Path(name).suffix.lower()

    return ""


def convert_xls_cell_value(cell_value: Any, cell_type: int, datemode: int) -> Any:
    """Convert xlrd cell value to Python type.

    xlrd returns dates as Excel serial numbers and booleans as 0/1 integers.
    This converts them to proper Python types for consistent handling with openpyxl.

    Args:
        cell_value: The raw cell value from xlrd.
        cell_type: The xlrd cell type constant (XL_CELL_DATE, XL_CELL_BOOLEAN, etc.).
        datemode: The workbook's datemode (0 for 1900-based, 1 for 1904-based).

    Returns:
        Converted Python value (datetime for dates, bool for booleans, unchanged otherwise).
    """
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


def stringify_cell_value(value: Any) -> str:
    """Convert a spreadsheet cell value to string.

    Handles special types:
    - None -> empty string
    - datetime -> ISO format string
    - date -> ISO format string
    - float with integer value -> integer string (e.g., 30.0 -> "30")
    - All line endings normalized to spaces (preserves row integrity)

    Args:
        value: Any cell value from a spreadsheet.

    Returns:
        String representation of the value.
    """
    if value is None:
        return ""

    # Handle datetime/date before float check (datetime is not a float)
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


def row_to_csv_line(row_values: Sequence[Any]) -> str:
    """Convert a row of cell values to a CSV-like line.

    Converts all values to strings, trims trailing empty cells,
    and joins with ", " delimiter.

    Args:
        row_values: Sequence of cell values from a spreadsheet row.

    Returns:
        CSV-like string with values joined by ", ".
    """
    values = [stringify_cell_value(v) for v in row_values]
    # Trim trailing empty cells
    while values and values[-1] == "":
        values.pop()

    return ", ".join(values)


def excel_rows_to_documents(
    *,
    workbook_name: str,
    sheets: Iterable[Tuple[str, Iterable[Sequence[Any]]]],
) -> List[Document]:
    """Convert Excel sheet rows to Document objects (one Document per sheet).

    Args:
        workbook_name: Name to use for the documents.
        sheets: Iterable of (sheet_name, rows) tuples where rows is an
            iterable of sequences (row values).

    Returns:
        List of Document objects, one per non-empty sheet.
    """
    documents = []
    for sheet_index, (sheet_name, rows) in enumerate(sheets, start=1):
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
