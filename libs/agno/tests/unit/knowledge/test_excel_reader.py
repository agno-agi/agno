import io
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.knowledge.reader.csv_reader import CSVReader
from agno.knowledge.reader.reader_factory import ReaderFactory


def test_reader_factory_routes_xlsx_to_csv_reader():
    ReaderFactory.clear_cache()
    reader = ReaderFactory.get_reader_for_extension(".xlsx")
    assert isinstance(reader, CSVReader)


def test_reader_factory_routes_xls_to_csv_reader():
    ReaderFactory.clear_cache()
    reader = ReaderFactory.get_reader_for_extension(".xls")
    assert isinstance(reader, CSVReader)


def test_csv_reader_reads_xlsx_as_per_sheet_documents(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    first_sheet = workbook.active
    first_sheet.title = "First"
    first_sheet.append(["name", "age"])
    first_sheet.append(["alice", 30])

    second_sheet = workbook.create_sheet("Second")
    second_sheet.append(["city"])
    second_sheet.append(["SF"])

    workbook.create_sheet("Empty")  # Should be ignored

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "workbook.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 2
    assert {doc.meta_data["sheet_name"] for doc in documents} == {"First", "Second"}

    first_doc = next(doc for doc in documents if doc.meta_data["sheet_name"] == "First")
    assert first_doc.meta_data["sheet_index"] == 1
    assert first_doc.content.splitlines() == ["name, age", "alice, 30"]


def test_csv_reader_reads_xlsx_preserves_cell_whitespace_when_chunk_disabled(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sheet"
    sheet.append(["  name", "age  "])
    sheet.append(["  alice", "30  "])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "whitespace.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    assert documents[0].content.splitlines() == ["  name, age  ", "  alice, 30  "]


def test_csv_reader_chunks_xlsx_rows_and_preserves_sheet_metadata(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    first_sheet = workbook.active
    first_sheet.title = "First"
    first_sheet.append(["name", "age"])
    first_sheet.append(["alice", 30])

    second_sheet = workbook.create_sheet("Second")
    second_sheet.append(["city"])
    second_sheet.append(["SF"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "workbook.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader()  # chunk=True by default
    chunked_documents = reader.read(file_path)

    assert len(chunked_documents) == 4
    assert {doc.meta_data["sheet_name"] for doc in chunked_documents} == {"First", "Second"}

    first_rows = sorted(
        doc.meta_data["row_number"] for doc in chunked_documents if doc.meta_data["sheet_name"] == "First"
    )
    assert first_rows == [1, 2]


def test_csv_reader_reads_xls_as_per_sheet_documents(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    first_sheet = workbook.add_sheet("First")
    first_sheet.write(0, 0, "name")
    first_sheet.write(0, 1, "age")
    first_sheet.write(1, 0, "alice")
    first_sheet.write(1, 1, 30)

    second_sheet = workbook.add_sheet("Second")
    second_sheet.write(0, 0, "city")
    second_sheet.write(1, 0, "SF")

    workbook.add_sheet("Empty")  # Should be ignored

    file_path = tmp_path / "workbook.xls"
    workbook.save(str(file_path))

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 2
    assert {doc.meta_data["sheet_name"] for doc in documents} == {"First", "Second"}

    first_doc = next(doc for doc in documents if doc.meta_data["sheet_name"] == "First")
    assert first_doc.meta_data["sheet_index"] == 1
    assert first_doc.content.splitlines() == ["name, age", "alice, 30"]


@pytest.mark.asyncio
async def test_csv_reader_async_reads_xlsx(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["name", "value"])
    sheet.append(["test", 42])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "async_test.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = await reader.async_read(file_path)

    assert len(documents) == 1
    assert documents[0].meta_data["sheet_name"] == "Data"
    assert documents[0].content.splitlines() == ["name, value", "test, 42"]


@pytest.mark.asyncio
async def test_csv_reader_async_reads_xls(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Data")
    sheet.write(0, 0, "name")
    sheet.write(0, 1, "value")
    sheet.write(1, 0, "test")
    sheet.write(1, 1, 42)

    file_path = tmp_path / "async_test.xls"
    workbook.save(str(file_path))

    reader = CSVReader(chunk=False)
    documents = await reader.async_read(file_path)

    assert len(documents) == 1
    assert documents[0].meta_data["sheet_name"] == "Data"
    assert documents[0].content.splitlines() == ["name, value", "test, 42"]


def test_csv_reader_reads_xlsx_from_bytesio_with_name(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(["col1", "col2"])
    sheet.append(["a", "b"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    buffer.seek(0)
    buffer.name = "named_workbook.xlsx"

    reader = CSVReader(chunk=False)
    documents = reader.read(buffer)

    assert len(documents) == 1
    assert documents[0].name == "named_workbook"
    assert documents[0].content.splitlines() == ["col1, col2", "a, b"]


def test_csv_reader_reads_xlsx_from_bytesio_without_name():
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(["col1", "col2"])
    sheet.append(["a", "b"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    buffer.seek(0)

    reader = CSVReader(chunk=False)
    documents = reader.read(buffer, name="fallback.xlsx")

    assert len(documents) == 1
    assert documents[0].name == "fallback"
    assert documents[0].content.splitlines() == ["col1, col2", "a, b"]


def test_csv_reader_xlsx_data_types(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Types"
    sheet.append(["type", "value"])
    sheet.append(["float", 3.14])
    sheet.append(["int_float", 30.0])
    sheet.append(["boolean_true", True])
    sheet.append(["boolean_false", False])
    sheet.append(["none", None])
    sheet.append(["string", "hello"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "types.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[0] == "type, value"
    assert lines[1] == "float, 3.14"
    assert lines[2] == "int_float, 30"
    assert lines[3] == "boolean_true, True"
    assert lines[4] == "boolean_false, False"
    assert lines[5] == "none"
    assert lines[6] == "string, hello"


def test_csv_reader_xlsx_unicode_content(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Unicode"
    sheet.append(["language", "greeting"])
    sheet.append(["Japanese", "こんにちは"])
    sheet.append(["Emoji", "Hello 👋🌍"])
    sheet.append(["Chinese", "你好"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "unicode.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[1] == "Japanese, こんにちは"
    assert lines[2] == "Emoji, Hello 👋🌍"
    assert lines[3] == "Chinese, 你好"


def test_csv_reader_xlsx_all_empty_sheets_returns_empty_list(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    workbook.active.title = "Empty1"
    workbook.create_sheet("Empty2")
    workbook.create_sheet("Empty3")

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "all_empty.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert documents == []


def test_csv_reader_xlsx_trims_trailing_empty_cells(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Trailing"
    sheet["A1"] = "a"
    sheet["B1"] = "b"
    sheet["C1"] = None
    sheet["D1"] = None
    sheet["E1"] = None

    sheet["A2"] = "x"
    sheet["B2"] = None
    sheet["C2"] = None

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "trailing.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[0] == "a, b"
    assert lines[1] == "x"


def test_csv_reader_xlsx_skips_empty_rows(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sparse"
    sheet.append(["header"])
    sheet.append([None, None, None])
    sheet.append(["data"])
    sheet.append([None])
    sheet.append(["more_data"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "sparse.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines == ["header", "data", "more_data"]


def test_csv_reader_xlsx_handles_special_characters(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Special"
    sheet.append(["type", "value"])
    sheet.append(["comma", "a,b,c"])
    sheet.append(["quote", 'say "hello"'])
    sheet.append(["newline", "line1\nline2"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "special.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "a,b,c" in content
    assert 'say "hello"' in content
    # Newlines in cells are converted to spaces to preserve row integrity
    assert "line1 line2" in content


def test_csv_reader_xlsx_datetime_cells_formatted_as_iso(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Dates"
    sheet.append(["type", "value"])
    sheet.append(["datetime", datetime(2024, 1, 20, 14, 30, 0)])
    sheet.append(["datetime_midnight", datetime(2024, 12, 25, 0, 0, 0)])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "dates.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[0] == "type, value"
    # datetime objects are formatted as ISO 8601 (instead of repr like "datetime.datetime(2024, 1, 20...)")
    assert lines[1] == "datetime, 2024-01-20T14:30:00"
    assert lines[2] == "datetime_midnight, 2024-12-25T00:00:00"


@pytest.mark.asyncio
async def test_csv_reader_async_xlsx_with_chunking(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["name", "value"])
    sheet.append(["row1", 100])
    sheet.append(["row2", 200])
    sheet.append(["row3", 300])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "async_chunk.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=True)
    documents = await reader.async_read(file_path)

    assert len(documents) == 4
    assert all(doc.meta_data.get("sheet_name") == "Data" for doc in documents)
    row_numbers = sorted(doc.meta_data.get("row_number") for doc in documents)
    assert row_numbers == [1, 2, 3, 4]


def test_csv_reader_xlsx_raises_import_error_when_openpyxl_missing(tmp_path: Path):
    file_path = tmp_path / "test.xlsx"
    file_path.write_bytes(b"dummy")

    with patch.dict(sys.modules, {"openpyxl": None}):
        reader = CSVReader(chunk=False)
        with pytest.raises(ImportError, match="openpyxl"):
            reader.read(file_path)


def test_csv_reader_xls_raises_import_error_when_xlrd_missing(tmp_path: Path):
    file_path = tmp_path / "test.xls"
    file_path.write_bytes(b"dummy")

    with patch.dict(sys.modules, {"xlrd": None}):
        reader = CSVReader(chunk=False)
        with pytest.raises(ImportError, match="xlrd"):
            reader.read(file_path)


def test_csv_reader_xlsx_corrupted_file_returns_empty_list(tmp_path: Path):
    pytest.importorskip("openpyxl")

    file_path = tmp_path / "corrupted.xlsx"
    file_path.write_bytes(b"not a valid xlsx file content")

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert documents == []


def test_csv_reader_csv_file_not_found_raises_error(tmp_path: Path):
    file_path = tmp_path / "nonexistent.csv"

    reader = CSVReader(chunk=False)
    with pytest.raises(FileNotFoundError, match="Could not find file"):
        reader.read(file_path)


def test_csv_reader_xlsx_file_not_found_raises_error(tmp_path: Path):
    pytest.importorskip("openpyxl")
    file_path = tmp_path / "nonexistent.xlsx"

    reader = CSVReader(chunk=False)
    # For Excel files, openpyxl raises its own FileNotFoundError
    with pytest.raises(FileNotFoundError):
        reader.read(file_path)


def test_csv_reader_xls_boolean_cells(tmp_path: Path):
    """Test that xls boolean cells show True/False, not 1/0."""
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Booleans")
    sheet.write(0, 0, "name")
    sheet.write(0, 1, "in_stock")
    sheet.write(1, 0, "Widget")
    sheet.write(1, 1, True)
    sheet.write(2, 0, "Gadget")
    sheet.write(2, 1, False)

    file_path = tmp_path / "booleans.xls"
    workbook.save(str(file_path))

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[0] == "name, in_stock"
    assert lines[1] == "Widget, True"
    assert lines[2] == "Gadget, False"


def test_csv_reader_xls_multiline_content_preserved_as_space(tmp_path: Path):
    """Test that multiline cell content is converted to spaces to preserve row integrity."""
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Multiline")
    sheet.write(0, 0, "id")
    sheet.write(0, 1, "description")
    sheet.write(1, 0, "1")
    sheet.write(1, 1, "Line1\nLine2\nLine3")

    file_path = tmp_path / "multiline.xls"
    workbook.save(str(file_path))

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    # Multiline content should be on a single line with spaces instead of newlines
    assert len(lines) == 2
    assert lines[1] == "1, Line1 Line2 Line3"


def test_csv_reader_xlsx_multiline_content_preserved_as_space(tmp_path: Path):
    """Test that multiline cell content is converted to spaces in xlsx files too."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["id", "description"])
    sheet.append([1, "Line1\nLine2\nLine3"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "multiline.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    # Multiline content should be on a single line with spaces instead of newlines
    assert len(lines) == 2
    assert lines[1] == "1, Line1 Line2 Line3"


def test_csv_reader_xlsx_carriage_return_normalized(tmp_path: Path):
    """Test that carriage return (CR) in xlsx cells is converted to space."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["type", "value"])
    sheet.append(["cr_only", "line1\rline2"])
    sheet.append(["crlf", "line1\r\nline2"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "carriage_return.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    # All line endings should be normalized to spaces
    assert len(lines) == 3
    assert lines[1] == "cr_only, line1 line2"
    assert lines[2] == "crlf, line1 line2"


def test_csv_reader_xls_carriage_return_normalized(tmp_path: Path):
    """Test that carriage return (CR) in xls cells is converted to space."""
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("LineEndings")
    sheet.write(0, 0, "type")
    sheet.write(0, 1, "value")
    sheet.write(1, 0, "cr_only")
    sheet.write(1, 1, "line1\rline2")
    sheet.write(2, 0, "crlf")
    sheet.write(2, 1, "line1\r\nline2")

    file_path = tmp_path / "carriage_return.xls"
    workbook.save(str(file_path))

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    # All line endings should be normalized to spaces
    assert len(lines) == 3
    assert lines[1] == "cr_only, line1 line2"
    assert lines[2] == "crlf, line1 line2"


def test_csv_reader_csv_multiline_cells_normalized(tmp_path: Path):
    """Test that embedded newlines in CSV cells are converted to spaces."""
    csv_content = """type,value
lf,"line1
line2"
normal,simple"""

    file_path = tmp_path / "multiline.csv"
    file_path.write_text(csv_content, encoding="utf-8")

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.strip().splitlines()
    # Embedded newlines should be converted to spaces
    assert len(lines) == 3
    assert lines[0] == "type, value"
    assert lines[1] == "lf, line1 line2"
    assert lines[2] == "normal, simple"


def test_csv_reader_csv_carriage_return_normalized(tmp_path: Path):
    """Test that carriage returns in CSV cells are converted to spaces."""
    # Create CSV with CR and CRLF embedded in cells
    csv_content = 'type,value\r\ncr_only,"line1\rline2"\r\ncrlf,"line1\r\nline2"'

    file_path = tmp_path / "cr_cells.csv"
    # Write in binary mode to preserve exact bytes
    file_path.write_bytes(csv_content.encode("utf-8"))

    reader = CSVReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.strip().splitlines()
    # All line endings inside cells should be normalized to spaces
    assert len(lines) == 3
    assert lines[1] == "cr_only, line1 line2"
    assert lines[2] == "crlf, line1 line2"
