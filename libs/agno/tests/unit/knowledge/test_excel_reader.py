import io
from pathlib import Path

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
