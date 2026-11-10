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
    """Convert Excel sheet rows to Documents (one per sheet)."""
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
