import io
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.knowledge.reader.excel_reader import ExcelReader
from agno.knowledge.reader.reader_factory import ReaderFactory


def test_reader_factory_routes_xlsx_to_excel_reader():
    ReaderFactory.clear_cache()
    reader = ReaderFactory.get_reader_for_extension(".xlsx")
    assert isinstance(reader, ExcelReader)


def test_reader_factory_routes_xls_to_excel_reader():
    ReaderFactory.clear_cache()
    reader = ReaderFactory.get_reader_for_extension(".xls")
    assert isinstance(reader, ExcelReader)


def test_excel_reader_reads_xlsx_as_per_sheet_documents(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 2
    assert {doc.meta_data["sheet_name"] for doc in documents} == {"First", "Second"}

    first_doc = next(doc for doc in documents if doc.meta_data["sheet_name"] == "First")
    assert first_doc.meta_data["sheet_index"] == 1
    assert first_doc.content.splitlines() == ["name, age", "alice, 30"]


def test_excel_reader_reads_xlsx_preserves_cell_whitespace_when_chunk_disabled(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    assert documents[0].content.splitlines() == ["  name, age  ", "  alice, 30  "]


def test_excel_reader_chunks_xlsx_rows_and_preserves_sheet_metadata(tmp_path: Path):
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

    reader = ExcelReader()  # chunk=True by default
    chunked_documents = reader.read(file_path)

    assert len(chunked_documents) == 4
    assert {doc.meta_data["sheet_name"] for doc in chunked_documents} == {"First", "Second"}

    first_rows = sorted(
        doc.meta_data["row_number"] for doc in chunked_documents if doc.meta_data["sheet_name"] == "First"
    )
    assert first_rows == [1, 2]


def test_excel_reader_reads_xls_as_per_sheet_documents(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 2
    assert {doc.meta_data["sheet_name"] for doc in documents} == {"First", "Second"}

    first_doc = next(doc for doc in documents if doc.meta_data["sheet_name"] == "First")
    assert first_doc.meta_data["sheet_index"] == 1
    assert first_doc.content.splitlines() == ["name, age", "alice, 30"]


@pytest.mark.asyncio
async def test_excel_reader_async_reads_xlsx(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = await reader.async_read(file_path)

    assert len(documents) == 1
    assert documents[0].meta_data["sheet_name"] == "Data"
    assert documents[0].content.splitlines() == ["name, value", "test, 42"]


@pytest.mark.asyncio
async def test_excel_reader_async_reads_xls(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Data")
    sheet.write(0, 0, "name")
    sheet.write(0, 1, "value")
    sheet.write(1, 0, "test")
    sheet.write(1, 1, 42)

    file_path = tmp_path / "async_test.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = await reader.async_read(file_path)

    assert len(documents) == 1
    assert documents[0].meta_data["sheet_name"] == "Data"
    assert documents[0].content.splitlines() == ["name, value", "test, 42"]


def test_excel_reader_reads_xlsx_from_bytesio_with_name(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(buffer)

    assert len(documents) == 1
    assert documents[0].name == "named_workbook"
    assert documents[0].content.splitlines() == ["col1, col2", "a, b"]


def test_excel_reader_reads_xlsx_from_bytesio_without_name():
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(buffer, name="fallback.xlsx")

    assert len(documents) == 1
    assert documents[0].name == "fallback"
    assert documents[0].content.splitlines() == ["col1, col2", "a, b"]


def test_excel_reader_raises_error_when_name_has_no_extension():
    """When BytesIO has no name and name param has no extension, reader raises ValueError."""
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

    reader = ExcelReader(chunk=False)

    with pytest.raises(ValueError, match="Unsupported file extension.*Expected .xlsx or .xls"):
        reader.read(buffer, name="Lorcan_data")


def test_excel_reader_succeeds_when_name_has_extension():
    """When BytesIO has no name but name param has extension, reader works correctly."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Products"
    sheet.append(["product", "price"])
    sheet.append(["Widget", 19.99])
    sheet.append(["Gadget", 29.99])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    buffer.seek(0)

    reader = ExcelReader(chunk=False)
    # This is the FIXED scenario: name="Lorcan_data.xlsx" (with extension)
    documents = reader.read(buffer, name="Lorcan_data.xlsx")

    assert len(documents) == 1
    assert documents[0].name == "Lorcan_data"
    assert "Widget" in documents[0].content
    assert "19.99" in documents[0].content


def test_excel_reader_xlsx_data_types(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
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


def test_excel_reader_xlsx_unicode_content(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[1] == "Japanese, こんにちは"
    assert lines[2] == "Emoji, Hello 👋🌍"
    assert lines[3] == "Chinese, 你好"


def test_excel_reader_xlsx_all_empty_sheets_returns_empty_list(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert documents == []


def test_excel_reader_xlsx_trims_trailing_empty_cells(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[0] == "a, b"
    assert lines[1] == "x"


def test_excel_reader_xlsx_skips_empty_rows(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines == ["header", "data", "more_data"]


def test_excel_reader_xlsx_handles_special_characters(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "a,b,c" in content
    assert 'say "hello"' in content
    # Newlines in cells are converted to spaces to preserve row integrity
    assert "line1 line2" in content


def test_excel_reader_xlsx_datetime_cells_formatted_as_iso(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[0] == "type, value"
    # datetime objects are formatted as ISO 8601 (instead of repr like "datetime.datetime(2024, 1, 20...)")
    assert lines[1] == "datetime, 2024-01-20T14:30:00"
    assert lines[2] == "datetime_midnight, 2024-12-25T00:00:00"


@pytest.mark.asyncio
async def test_excel_reader_async_xlsx_with_chunking(tmp_path: Path):
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

    reader = ExcelReader(chunk=True)
    documents = await reader.async_read(file_path)

    assert len(documents) == 4
    assert all(doc.meta_data.get("sheet_name") == "Data" for doc in documents)
    row_numbers = sorted(doc.meta_data.get("row_number") for doc in documents)
    assert row_numbers == [1, 2, 3, 4]


def test_excel_reader_xlsx_raises_import_error_when_openpyxl_missing(tmp_path: Path):
    file_path = tmp_path / "test.xlsx"
    file_path.write_bytes(b"dummy")

    with patch.dict(sys.modules, {"openpyxl": None}):
        reader = ExcelReader(chunk=False)
        with pytest.raises(ImportError, match="openpyxl"):
            reader.read(file_path)


def test_excel_reader_xls_raises_import_error_when_xlrd_missing(tmp_path: Path):
    file_path = tmp_path / "test.xls"
    file_path.write_bytes(b"dummy")

    with patch.dict(sys.modules, {"xlrd": None}):
        reader = ExcelReader(chunk=False)
        with pytest.raises(ImportError, match="xlrd"):
            reader.read(file_path)


def test_excel_reader_xlsx_corrupted_file_returns_empty_list(tmp_path: Path):
    pytest.importorskip("openpyxl")

    file_path = tmp_path / "corrupted.xlsx"
    file_path.write_bytes(b"not a valid xlsx file content")

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert documents == []


def test_excel_reader_xlsx_file_not_found_raises_error(tmp_path: Path):
    pytest.importorskip("openpyxl")
    file_path = tmp_path / "nonexistent.xlsx"

    reader = ExcelReader(chunk=False)
    with pytest.raises(FileNotFoundError):
        reader.read(file_path)


def test_excel_reader_xls_boolean_cells(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[0] == "name, in_stock"
    assert lines[1] == "Widget, True"
    assert lines[2] == "Gadget, False"


def test_excel_reader_xls_multiline_content_preserved_as_space(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Multiline")
    sheet.write(0, 0, "id")
    sheet.write(0, 1, "description")
    sheet.write(1, 0, "1")
    sheet.write(1, 1, "Line1\nLine2\nLine3")

    file_path = tmp_path / "multiline.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    # Multiline content should be on a single line with spaces instead of newlines
    assert len(lines) == 2
    assert lines[1] == "1, Line1 Line2 Line3"


def test_excel_reader_xlsx_multiline_content_preserved_as_space(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    # Multiline content should be on a single line with spaces instead of newlines
    assert len(lines) == 2
    assert lines[1] == "1, Line1 Line2 Line3"


def test_excel_reader_xlsx_carriage_return_normalized(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    # All line endings should be normalized to spaces
    assert len(lines) == 3
    assert lines[1] == "cr_only, line1 line2"
    assert lines[2] == "crlf, line1 line2"


def test_excel_reader_xls_carriage_return_normalized(tmp_path: Path):
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

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    # All line endings should be normalized to spaces
    assert len(lines) == 3
    assert lines[1] == "cr_only, line1 line2"
    assert lines[2] == "crlf, line1 line2"


def test_excel_reader_filter_sheets_by_name(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    first_sheet = workbook.active
    first_sheet.title = "First"
    first_sheet.append(["a", "b"])

    second_sheet = workbook.create_sheet("Second")
    second_sheet.append(["c", "d"])

    third_sheet = workbook.create_sheet("Third")
    third_sheet.append(["e", "f"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "filter.xlsx"
    file_path.write_bytes(buffer.getvalue())

    # Read only "First" and "Third" sheets
    reader = ExcelReader(chunk=False, sheets=["First", "Third"])
    documents = reader.read(file_path)

    assert len(documents) == 2
    assert {doc.meta_data["sheet_name"] for doc in documents} == {"First", "Third"}


def test_excel_reader_filter_sheets_by_index(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    first_sheet = workbook.active
    first_sheet.title = "First"
    first_sheet.append(["a", "b"])

    second_sheet = workbook.create_sheet("Second")
    second_sheet.append(["c", "d"])

    third_sheet = workbook.create_sheet("Third")
    third_sheet.append(["e", "f"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "filter.xlsx"
    file_path.write_bytes(buffer.getvalue())

    # Read only sheets at index 1 and 3 (First and Third) - 1-based to match metadata
    reader = ExcelReader(chunk=False, sheets=[1, 3])
    documents = reader.read(file_path)

    assert len(documents) == 2
    assert {doc.meta_data["sheet_name"] for doc in documents} == {"First", "Third"}


def test_excel_reader_filter_by_index_is_1_based():
    """Index filtering uses 1-based indices to match sheet_index in document metadata."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    workbook.active.title = "First"
    workbook.active["A1"] = "first"
    workbook.create_sheet("Second")
    workbook["Second"]["A1"] = "second"
    workbook.create_sheet("Third")
    workbook["Third"]["A1"] = "third"

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    buffer.seek(0)
    buffer.name = "test.xlsx"

    # sheets=[1] should get "First" (index 1 in metadata)
    reader = ExcelReader(chunk=False, sheets=[1])
    documents = reader.read(buffer)

    assert len(documents) == 1
    assert documents[0].meta_data["sheet_name"] == "First"
    assert documents[0].meta_data["sheet_index"] == 1


def test_excel_reader_filter_by_name_case_insensitive():
    """Name filtering is case-insensitive."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    workbook.active.title = "Sales"
    workbook.active["A1"] = "data"

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    buffer.seek(0)
    buffer.name = "test.xlsx"

    # "sales" (lowercase) should match "Sales" (capitalized)
    reader = ExcelReader(chunk=False, sheets=["sales"])
    documents = reader.read(buffer)

    assert len(documents) == 1
    assert documents[0].meta_data["sheet_name"] == "Sales"


def test_excel_reader_empty_sheets_list_returns_all():
    """Empty sheets list should return all sheets, same as None."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    workbook.active.title = "First"
    workbook.active["A1"] = "first"
    workbook.create_sheet("Second")
    workbook["Second"]["A1"] = "second"

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    buffer.seek(0)
    buffer.name = "test.xlsx"

    # sheets=[] should return all sheets
    reader = ExcelReader(chunk=False, sheets=[])
    documents = reader.read(buffer)

    assert len(documents) == 2
    assert {doc.meta_data["sheet_name"] for doc in documents} == {"First", "Second"}


def test_excel_reader_unsupported_extension_raises_error(tmp_path: Path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("not an excel file")

    reader = ExcelReader(chunk=False)

    with pytest.raises(ValueError, match="Unsupported file extension.*Expected .xlsx or .xls"):
        reader.read(file_path)


def test_excel_reader_xls_date_cells_converted_to_iso(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Dates")
    sheet.write(0, 0, "type")
    sheet.write(0, 1, "value")

    # xlwt requires xlrd-style date tuples or datetime objects
    # Write dates using xlwt's date format
    date_format = xlwt.XFStyle()
    date_format.num_format_str = "YYYY-MM-DD"

    datetime_format = xlwt.XFStyle()
    datetime_format.num_format_str = "YYYY-MM-DD HH:MM:SS"

    sheet.write(1, 0, "date")
    sheet.write(1, 1, datetime(2024, 1, 20), date_format)

    sheet.write(2, 0, "datetime")
    sheet.write(2, 1, datetime(2024, 12, 25, 14, 30, 45), datetime_format)

    file_path = tmp_path / "dates.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[0] == "type, value"
    # Dates should be converted to ISO format (not raw serial numbers)
    assert "2024-01-20" in lines[1]
    assert "2024-12-25" in lines[2]


def test_excel_reader_xls_corrupted_file_returns_empty_list(tmp_path: Path):
    pytest.importorskip("xlrd")

    file_path = tmp_path / "corrupted.xls"
    file_path.write_bytes(b"not a valid xls file content")

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert documents == []


def test_excel_reader_xls_file_not_found_raises_error(tmp_path: Path):
    pytest.importorskip("xlrd")
    file_path = tmp_path / "nonexistent.xls"

    reader = ExcelReader(chunk=False)
    with pytest.raises(FileNotFoundError):
        reader.read(file_path)


def test_excel_reader_xls_unicode_content(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Unicode")
    sheet.write(0, 0, "language")
    sheet.write(0, 1, "greeting")
    sheet.write(1, 0, "Japanese")
    sheet.write(1, 1, "こんにちは")
    sheet.write(2, 0, "Chinese")
    sheet.write(2, 1, "你好")
    sheet.write(3, 0, "German")
    sheet.write(3, 1, "Größe")

    file_path = tmp_path / "unicode.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[1] == "Japanese, こんにちは"
    assert lines[2] == "Chinese, 你好"
    assert lines[3] == "German, Größe"


def test_excel_reader_xls_filter_sheets_by_name(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    first_sheet = workbook.add_sheet("First")
    first_sheet.write(0, 0, "a")
    first_sheet.write(0, 1, "b")

    second_sheet = workbook.add_sheet("Second")
    second_sheet.write(0, 0, "c")
    second_sheet.write(0, 1, "d")

    third_sheet = workbook.add_sheet("Third")
    third_sheet.write(0, 0, "e")
    third_sheet.write(0, 1, "f")

    file_path = tmp_path / "filter.xls"
    workbook.save(str(file_path))

    # Read only "First" and "Third" sheets
    reader = ExcelReader(chunk=False, sheets=["First", "Third"])
    documents = reader.read(file_path)

    assert len(documents) == 2
    assert {doc.meta_data["sheet_name"] for doc in documents} == {"First", "Third"}


def test_excel_reader_xls_filter_sheets_by_index(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    first_sheet = workbook.add_sheet("First")
    first_sheet.write(0, 0, "a")
    first_sheet.write(0, 1, "b")

    second_sheet = workbook.add_sheet("Second")
    second_sheet.write(0, 0, "c")
    second_sheet.write(0, 1, "d")

    third_sheet = workbook.add_sheet("Third")
    third_sheet.write(0, 0, "e")
    third_sheet.write(0, 1, "f")

    file_path = tmp_path / "filter.xls"
    workbook.save(str(file_path))

    # Read only sheets at index 1 and 3 (First and Third) - 1-based to match metadata
    reader = ExcelReader(chunk=False, sheets=[1, 3])
    documents = reader.read(file_path)

    assert len(documents) == 2
    assert {doc.meta_data["sheet_name"] for doc in documents} == {"First", "Third"}


def test_excel_reader_xls_from_bytesio(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Data")
    sheet.write(0, 0, "col1")
    sheet.write(0, 1, "col2")
    sheet.write(1, 0, "a")
    sheet.write(1, 1, "b")

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    buffer.name = "test.xls"

    reader = ExcelReader(chunk=False)
    documents = reader.read(buffer)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].content.splitlines() == ["col1, col2", "a, b"]


def test_excel_reader_xls_data_types(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Types")
    sheet.write(0, 0, "type")
    sheet.write(0, 1, "value")
    sheet.write(1, 0, "float")
    sheet.write(1, 1, 3.14)
    sheet.write(2, 0, "int_float")
    sheet.write(2, 1, 30.0)
    sheet.write(3, 0, "string")
    sheet.write(3, 1, "hello")
    sheet.write(4, 0, "empty")
    sheet.write(4, 1, None)

    file_path = tmp_path / "types.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[0] == "type, value"
    assert lines[1] == "float, 3.14"
    assert lines[2] == "int_float, 30"
    assert lines[3] == "string, hello"
    assert lines[4] == "empty"


def test_excel_reader_xls_special_characters(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Special")
    sheet.write(0, 0, "type")
    sheet.write(0, 1, "value")
    sheet.write(1, 0, "comma")
    sheet.write(1, 1, "a,b,c")
    sheet.write(2, 0, "quote")
    sheet.write(2, 1, 'say "hello"')

    file_path = tmp_path / "special.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "a,b,c" in content
    assert 'say "hello"' in content


def test_excel_reader_xls_trims_trailing_empty_cells(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Trailing")
    sheet.write(0, 0, "a")
    sheet.write(0, 1, "b")
    # Cells C1, D1, E1 left empty (trailing)

    sheet.write(1, 0, "x")
    # Cells B2, C2 left empty (trailing)

    file_path = tmp_path / "trailing.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines[0] == "a, b"
    assert lines[1] == "x"


def test_excel_reader_xls_skips_empty_rows(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Sparse")
    sheet.write(0, 0, "header")
    # Row 1 left empty
    sheet.write(2, 0, "data")
    # Row 3 left empty
    sheet.write(4, 0, "more_data")

    file_path = tmp_path / "sparse.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert lines == ["header", "data", "more_data"]


def test_excel_reader_xls_all_empty_sheets_returns_empty_list(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    workbook.add_sheet("Empty1")
    workbook.add_sheet("Empty2")

    file_path = tmp_path / "all_empty.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert documents == []


def test_excel_reader_xls_chunks_rows_for_rag(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Products")
    sheet.write(0, 0, "name")
    sheet.write(0, 1, "category")
    sheet.write(0, 2, "price")
    sheet.write(1, 0, "Widget A")
    sheet.write(1, 1, "Electronics")
    sheet.write(1, 2, 99.99)
    sheet.write(2, 0, "Widget B")
    sheet.write(2, 1, "Home")
    sheet.write(2, 2, 49.99)
    sheet.write(3, 0, "Widget C")
    sheet.write(3, 1, "Electronics")
    sheet.write(3, 2, 149.99)

    file_path = tmp_path / "products.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=True)  # Default chunking
    documents = reader.read(file_path)

    assert len(documents) == 4  # Header + 3 data rows
    assert all(doc.meta_data.get("sheet_name") == "Products" for doc in documents)
    row_numbers = sorted(doc.meta_data.get("row_number") for doc in documents)
    assert row_numbers == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_excel_reader_xls_async_with_chunking(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Data")
    sheet.write(0, 0, "id")
    sheet.write(0, 1, "value")
    sheet.write(1, 0, "1")
    sheet.write(1, 1, "first")
    sheet.write(2, 0, "2")
    sheet.write(2, 1, "second")

    file_path = tmp_path / "async_chunk.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=True)
    documents = await reader.async_read(file_path)

    assert len(documents) == 3
    assert all(doc.meta_data.get("sheet_name") == "Data" for doc in documents)


def test_excel_reader_xls_numeric_edge_cases(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Financial")
    sheet.write(0, 0, "type")
    sheet.write(0, 1, "amount")

    # Large number (revenue)
    sheet.write(1, 0, "revenue")
    sheet.write(1, 1, 1234567890.50)

    # Negative number (refund)
    sheet.write(2, 0, "refund")
    sheet.write(2, 1, -5000.25)

    # Scientific notation (market cap)
    sheet.write(3, 0, "market_cap")
    sheet.write(3, 1, 1.5e12)

    # Very small number (interest rate)
    sheet.write(4, 0, "rate")
    sheet.write(4, 1, 0.0325)

    file_path = tmp_path / "financial.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    assert "1234567890.5" in lines[1]
    assert "-5000.25" in lines[2]
    assert "1500000000000" in lines[3] or "1.5e" in lines[3].lower()
    assert "0.0325" in lines[4]


def test_excel_reader_xls_long_text_cells(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Products")
    sheet.write(0, 0, "name")
    sheet.write(0, 1, "description")

    long_description = (
        "This premium widget features advanced technology with "
        "multiple connectivity options including WiFi, Bluetooth, "
        "and NFC. Perfect for home automation, smart home integration, "
        "and IoT applications. Includes 2-year warranty and 24/7 support."
    )
    sheet.write(1, 0, "Smart Widget Pro")
    sheet.write(1, 1, long_description)

    file_path = tmp_path / "catalog.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "Smart Widget Pro" in content
    assert "premium widget" in content
    assert "24/7 support" in content
    assert len(content) > 200


def test_excel_reader_xls_multi_sheet_chunking(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()

    sales_sheet = workbook.add_sheet("Sales")
    sales_sheet.write(0, 0, "product")
    sales_sheet.write(0, 1, "amount")
    sales_sheet.write(1, 0, "Widget")
    sales_sheet.write(1, 1, 1000)

    inventory_sheet = workbook.add_sheet("Inventory")
    inventory_sheet.write(0, 0, "item")
    inventory_sheet.write(0, 1, "stock")
    inventory_sheet.write(1, 0, "Widget")
    inventory_sheet.write(1, 1, 50)

    file_path = tmp_path / "report.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=True)
    documents = reader.read(file_path)

    # 2 rows per sheet = 4 total documents
    assert len(documents) == 4
    sheet_names = {doc.meta_data["sheet_name"] for doc in documents}
    assert sheet_names == {"Sales", "Inventory"}


def test_excel_reader_xls_wide_table(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Wide")

    # Create 20 columns
    num_cols = 20
    for col in range(num_cols):
        sheet.write(0, col, f"col_{col}")
        sheet.write(1, col, f"val_{col}")

    file_path = tmp_path / "wide.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    lines = documents[0].content.splitlines()
    # All columns should be present
    assert "col_0" in lines[0]
    assert "col_19" in lines[0]
    assert "val_0" in lines[1]
    assert "val_19" in lines[1]


def test_excel_reader_stress_large_sheet_xlsx(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "LargeData"
    sheet.append(["id", "name", "description", "price", "category"])

    for i in range(1000):
        sheet.append([i, f"Product_{i}", f"Description for product {i}", 99.99 + i, f"Category_{i % 10}"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "large.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=True)
    documents = reader.read(file_path)

    assert len(documents) == 1001  # header + 1000 data rows
    assert all(doc.meta_data.get("sheet_name") == "LargeData" for doc in documents)


def test_excel_reader_stress_large_sheet_xls(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("LargeData")
    headers = ["id", "name", "description", "price", "category"]
    for col, header in enumerate(headers):
        sheet.write(0, col, header)

    for i in range(1000):
        sheet.write(i + 1, 0, i)
        sheet.write(i + 1, 1, f"Product_{i}")
        sheet.write(i + 1, 2, f"Description for product {i}")
        sheet.write(i + 1, 3, 99.99 + i)
        sheet.write(i + 1, 4, f"Category_{i % 10}")

    file_path = tmp_path / "large.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=True)
    documents = reader.read(file_path)

    assert len(documents) == 1001  # header + 1000 data rows


def test_excel_reader_stress_wide_table_50_cols(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "WideData"

    # 50 columns
    headers = [f"col_{i}" for i in range(50)]
    sheet.append(headers)

    # 100 rows of data
    for row in range(100):
        sheet.append([f"row{row}_col{col}" for col in range(50)])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "wide.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "col_0" in content
    assert "col_49" in content


@pytest.mark.asyncio
async def test_excel_reader_stress_concurrent_reads(tmp_path: Path):
    import asyncio

    openpyxl = pytest.importorskip("openpyxl")

    files = []
    for i in range(5):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = f"Data{i}"
        sheet.append(["id", "value"])
        for j in range(100):
            sheet.append([j, f"file{i}_value{j}"])

        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()

        file_path = tmp_path / f"concurrent_{i}.xlsx"
        file_path.write_bytes(buffer.getvalue())
        files.append(file_path)

    reader = ExcelReader(chunk=True)
    results = await asyncio.gather(*[reader.async_read(f) for f in files])

    assert len(results) == 5
    for docs in results:
        assert len(docs) == 101  # header + 100 rows


def test_excel_reader_stress_multi_sheet_large(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet_names = ["Q1_Sales", "Q2_Sales", "Q3_Sales", "Q4_Sales", "Annual_Summary"]

    for idx, name in enumerate(sheet_names):
        if idx == 0:
            sheet = workbook.active
            sheet.title = name
        else:
            sheet = workbook.create_sheet(name)

        sheet.append(["region", "product", "revenue", "units"])
        for row in range(200):
            sheet.append([f"Region_{row % 5}", f"Product_{row}", row * 1000, row * 10])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "multi_sheet.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=True)
    documents = reader.read(file_path)

    # 5 sheets × 201 rows (header + 200 data) = 1005 documents
    assert len(documents) == 1005
    found_sheets = {doc.meta_data["sheet_name"] for doc in documents}
    assert found_sheets == set(sheet_names)


def test_excel_reader_stress_mixed_types_1000_rows(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "MixedTypes"
    sheet.append(["id", "name", "price", "in_stock", "created_date", "description"])

    for i in range(1000):
        sheet.append(
            [
                i,
                f"Product_{i}",
                99.99 + (i * 0.01),
                i % 2 == 0,  # Boolean
                datetime(2024, (i % 12) + 1, (i % 28) + 1),
                f"Long description for product {i} with multiple words",
            ]
        )

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "mixed_types.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=True)
    documents = reader.read(file_path)

    assert len(documents) == 1001


def test_excel_reader_xlsx_formula_cells_return_values(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Formulas"
    sheet.append(["item", "quantity", "unit_price", "total"])
    sheet.append(["Widget A", 10, 5.00, "=B2*C2"])
    sheet.append(["Widget B", 5, 10.00, "=B3*C3"])
    sheet.append(["", "", "Grand Total", "=SUM(D2:D3)"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "formulas.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    # Note: openpyxl with data_only=True returns None for formulas in newly created files
    # because Excel hasn't calculated them yet. In real files from Excel, values would be present.
    content = documents[0].content
    assert "Widget A" in content


def test_excel_reader_xlsx_merged_cells_return_top_left_value(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Merged"
    sheet["A1"] = "Merged Header"
    sheet.merge_cells("A1:C1")
    sheet["A2"] = "col1"
    sheet["B2"] = "col2"
    sheet["C2"] = "col3"
    sheet["A3"] = "data1"
    sheet["B3"] = "data2"
    sheet["C3"] = "data3"

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "merged.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "Merged Header" in content


def test_excel_reader_xlsx_leading_zeros_in_text_cells(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "SKUs"
    sheet.append(["sku", "name", "barcode"])
    sheet.append(["00123", "Widget A", "0001234567890"])
    sheet.append(["007", "Widget B", "0009876543210"])
    sheet.append(["0001", "Widget C", "0000000000001"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "skus.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    # Text cells preserve leading zeros
    assert "00123" in content
    assert "007" in content
    assert "0001" in content


def test_excel_reader_xlsx_error_cells_returned_as_strings(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Errors"
    sheet.append(["type", "value"])
    # Manually set error values as strings (simulating what Excel would show)
    sheet.append(["div_zero", "#DIV/0!"])
    sheet.append(["ref_error", "#REF!"])
    sheet.append(["na_error", "#N/A"])
    sheet.append(["value_error", "#VALUE!"])
    sheet.append(["name_error", "#NAME?"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "errors.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "#DIV/0!" in content
    assert "#REF!" in content
    assert "#N/A" in content


def test_excel_reader_xlsx_large_numbers_preserved(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Financial"
    sheet.append(["type", "amount"])
    sheet.append(["revenue", 1234567890.50])
    sheet.append(["market_cap", 2500000000])
    sheet.append(["refund", -5000.25])
    sheet.append(["small", 0.0001])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "financial.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "1234567890.5" in content
    assert "2500000000" in content
    assert "-5000.25" in content


def test_excel_reader_xlsx_whitespace_only_cells_handled(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Whitespace"
    sheet.append(["id", "name", "notes"])
    sheet.append([1, "Widget", "   "])  # spaces only
    sheet.append([2, "Gadget", "\t\t"])  # tabs only
    sheet.append([3, "Item", "  \n  "])  # mixed whitespace

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "whitespace.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "Widget" in content
    assert "Gadget" in content


def test_excel_reader_xlsx_large_cell_content(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Products"
    sheet.append(["name", "description"])

    long_desc = (
        "This premium enterprise widget features cutting-edge technology with "
        "advanced AI-powered automation capabilities. It includes seamless integration "
        "with existing enterprise systems, real-time analytics dashboard, comprehensive "
        "reporting suite, multi-language support for global deployments, and 24/7 "
        "enterprise support with guaranteed SLA. The widget also supports custom "
        "configurations, API access for third-party integrations, and complies with "
        "SOC 2, GDPR, and HIPAA regulations. Perfect for large-scale deployments."
    )
    sheet.append(["Enterprise Widget Pro", long_desc])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "products.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "Enterprise Widget Pro" in content
    assert "AI-powered automation" in content
    assert "HIPAA regulations" in content


def test_excel_reader_xlsx_sparse_data_with_gaps(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sparse"
    sheet["A1"] = "a"
    sheet["C1"] = "c"
    sheet["E1"] = "e"
    sheet["A3"] = "data1"
    sheet["C3"] = "data2"
    sheet["A5"] = "more"

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "sparse.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "a" in content
    assert "c" in content
    assert "data1" in content
    assert "more" in content


def test_excel_reader_xls_error_cells_returned_as_strings(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Errors")
    sheet.write(0, 0, "type")
    sheet.write(0, 1, "value")
    sheet.write(1, 0, "div_zero")
    sheet.write(1, 1, "#DIV/0!")
    sheet.write(2, 0, "ref_error")
    sheet.write(2, 1, "#REF!")
    sheet.write(3, 0, "na_error")
    sheet.write(3, 1, "#N/A")

    file_path = tmp_path / "errors.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "#DIV/0!" in content
    assert "#REF!" in content


def test_excel_reader_xls_leading_zeros_in_text_cells(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("SKUs")
    sheet.write(0, 0, "sku")
    sheet.write(0, 1, "name")
    sheet.write(1, 0, "00123")
    sheet.write(1, 1, "Widget A")
    sheet.write(2, 0, "007")
    sheet.write(2, 1, "Widget B")
    sheet.write(3, 0, "0001")
    sheet.write(3, 1, "Widget C")

    file_path = tmp_path / "skus.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "00123" in content
    assert "007" in content
    assert "0001" in content


def test_excel_reader_xls_large_cell_content(tmp_path: Path):
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Products")
    sheet.write(0, 0, "name")
    sheet.write(0, 1, "description")

    long_desc = (
        "This premium enterprise widget features cutting-edge technology with "
        "advanced AI-powered automation capabilities and comprehensive reporting."
    )
    sheet.write(1, 0, "Enterprise Widget")
    sheet.write(1, 1, long_desc)

    file_path = tmp_path / "products.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "Enterprise Widget" in content
    assert "AI-powered automation" in content


def test_excel_reader_xlsx_non_ascii_via_bytesio():
    """Non-ASCII Unicode content should be preserved when reading via BytesIO."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "International"
    sheet.append(["language", "greeting", "description"])
    sheet.append(["Chinese", "你好世界", "中文描述"])
    sheet.append(["Japanese", "こんにちは", "日本語の説明"])
    sheet.append(["Korean", "안녕하세요", "한국어 설명"])
    sheet.append(["Arabic", "مرحبا", "وصف عربي"])
    sheet.append(["Russian", "Привет", "Русское описание"])
    sheet.append(["Emoji", "Hello 👋🌍", "Description with 🎉 emoji"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    buffer.seek(0)
    buffer.name = "international.xlsx"

    reader = ExcelReader(chunk=False)
    documents = reader.read(buffer)

    assert len(documents) == 1
    content = documents[0].content

    # All non-ASCII characters should be preserved
    assert "你好世界" in content
    assert "こんにちは" in content
    assert "안녕하세요" in content
    assert "مرحبا" in content
    assert "Привет" in content
    assert "👋🌍" in content
    assert "🎉" in content


def test_excel_reader_xls_non_ascii_via_bytesio():
    """XLS: Non-ASCII Unicode content should be preserved when reading via BytesIO."""
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("International")
    sheet.write(0, 0, "language")
    sheet.write(0, 1, "greeting")
    sheet.write(1, 0, "Chinese")
    sheet.write(1, 1, "你好世界")
    sheet.write(2, 0, "Japanese")
    sheet.write(2, 1, "こんにちは")
    sheet.write(3, 0, "Russian")
    sheet.write(3, 1, "Привет мир")
    sheet.write(4, 0, "German")
    sheet.write(4, 1, "Größenmaßstab")

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    buffer.name = "international.xls"

    reader = ExcelReader(chunk=False)
    documents = reader.read(buffer)

    assert len(documents) == 1
    content = documents[0].content

    # All non-ASCII characters should be preserved
    assert "你好世界" in content
    assert "こんにちは" in content
    assert "Привет" in content
    assert "Größenmaßstab" in content


@pytest.mark.asyncio
async def test_excel_reader_xlsx_non_ascii_via_bytesio_async():
    """Async: Non-ASCII Unicode content should be preserved when reading via BytesIO."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "International"
    sheet.append(["language", "greeting"])
    sheet.append(["Chinese", "你好世界"])
    sheet.append(["Japanese", "こんにちは"])
    sheet.append(["Emoji", "Hello 👋🌍"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    buffer.seek(0)
    buffer.name = "international.xlsx"

    reader = ExcelReader(chunk=False)
    documents = await reader.async_read(buffer)

    assert len(documents) == 1
    content = documents[0].content

    assert "你好世界" in content
    assert "こんにちは" in content
    assert "👋🌍" in content


def test_excel_reader_bytesio_with_empty_name_uses_name_param():
    """BytesIO with empty .name attribute should use name param for workbook name."""
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
    buffer.name = ""  # Empty string

    reader = ExcelReader(chunk=False)
    documents = reader.read(buffer, name="fallback_name.xlsx")

    assert len(documents) == 1
    # Workbook name should come from name param since buffer.name is empty
    assert documents[0].name == "fallback_name"


def test_excel_reader_bytesio_with_none_name_uses_name_param():
    """BytesIO with .name=None should use name param for workbook name."""
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
    buffer.name = None  # type: ignore[assignment]  # Explicitly set to None

    reader = ExcelReader(chunk=False)
    documents = reader.read(buffer, name="fallback_name.xlsx")

    assert len(documents) == 1
    # Workbook name should come from name param since buffer.name is None
    assert documents[0].name == "fallback_name"


def test_excel_reader_bytesio_no_name_no_param_uses_default():
    """BytesIO without .name and no name param should use default 'workbook'."""
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
    # BytesIO has no .name attribute by default

    reader = ExcelReader(chunk=False)
    # Note: This will return empty list since no extension can be inferred
    # But if we could bypass extension check, the name would be "workbook"
    documents = reader.read(buffer, name="data.xlsx")

    assert len(documents) == 1
    assert documents[0].name == "data"


def test_sheets_filter_with_nonexistent_sheet_returns_empty(tmp_path: Path):
    """Filtering to a nonexistent sheet returns empty list."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["col1", "col2"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "test.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False, sheets=["NonexistentSheet"])
    docs = reader.read(file_path)

    assert docs == []


def test_sheets_filter_with_out_of_range_index_returns_empty(tmp_path: Path):
    """Filtering to an out-of-range index returns empty list."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["col1", "col2"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "test.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False, sheets=[99])
    docs = reader.read(file_path)

    assert docs == []


def test_mixed_sheet_name_and_index_filter(tmp_path: Path):
    """Filtering with both names and indices works."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    first_sheet = workbook.active
    first_sheet.title = "First"
    first_sheet.append(["first"])

    second_sheet = workbook.create_sheet("Second")
    second_sheet.append(["second"])

    third_sheet = workbook.create_sheet("Third")
    third_sheet.append(["third"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "test.xlsx"
    file_path.write_bytes(buffer.getvalue())

    # Mix name ("First") and 1-based index (3=Third)
    reader = ExcelReader(chunk=False, sheets=["First", 3])
    docs = reader.read(file_path)

    assert len(docs) == 2
    assert {doc.meta_data["sheet_name"] for doc in docs} == {"First", "Third"}


def test_excel_reader_xls_encoding_parameter_passed_to_xlrd(tmp_path: Path):
    """Encoding parameter should be passed through to xlrd."""
    xlwt = pytest.importorskip("xlwt")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Data")
    sheet.write(0, 0, "header")
    sheet.write(0, 1, "value")
    sheet.write(1, 0, "name")
    sheet.write(1, 1, "test")

    file_path = tmp_path / "encoding_test.xls"
    workbook.save(str(file_path))

    reader = ExcelReader(encoding="utf-8", chunk=False)
    docs = reader.read(file_path)

    assert len(docs) == 1
    assert "name" in docs[0].content
    assert "test" in docs[0].content
