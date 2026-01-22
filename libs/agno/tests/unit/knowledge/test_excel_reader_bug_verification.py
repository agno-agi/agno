"""Tests for ExcelReader sheet filtering and metadata."""

import io
from pathlib import Path

import pytest

from agno.knowledge.reader.excel_reader import ExcelReader


def test_positive_indices_work_correctly(tmp_path: Path):
    """Positive indices should work correctly."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    first_sheet = workbook.active
    first_sheet.title = "First"
    first_sheet.append(["first", "sheet"])

    second_sheet = workbook.create_sheet("Second")
    second_sheet.append(["second", "sheet"])

    third_sheet = workbook.create_sheet("Third")
    third_sheet.append(["third", "sheet"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "three_sheets.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False, sheets=[0, 2])
    docs = reader.read(file_path)

    assert len(docs) == 2
    assert {doc.meta_data["sheet_name"] for doc in docs} == {"First", "Third"}


def test_sheet_index_reflects_original_position(tmp_path: Path):
    """sheet_index in metadata reflects original workbook position."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    first_sheet = workbook.active
    first_sheet.title = "First"
    first_sheet.append(["first", "sheet"])

    second_sheet = workbook.create_sheet("Second")
    second_sheet.append(["second", "sheet"])

    third_sheet = workbook.create_sheet("Third")
    third_sheet.append(["third", "sheet"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "three_sheets.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False, sheets=["Third"])
    docs = reader.read(file_path)

    assert len(docs) == 1
    assert docs[0].meta_data["sheet_name"] == "Third"
    assert docs[0].meta_data["sheet_index"] == 3


def test_multiple_filtered_sheets_have_original_indices(tmp_path: Path):
    """When filtering multiple sheets, indices reflect original positions."""
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    for i, name in enumerate(["A", "B", "C", "D", "E"]):
        if i == 0:
            sheet = workbook.active
            sheet.title = name
        else:
            sheet = workbook.create_sheet(name)
        sheet.append([f"{name}_data"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    file_path = tmp_path / "five_sheets.xlsx"
    file_path.write_bytes(buffer.getvalue())

    reader = ExcelReader(chunk=False, sheets=["B", "D"])
    docs = reader.read(file_path)

    assert len(docs) == 2

    b_doc = next(d for d in docs if d.meta_data["sheet_name"] == "B")
    d_doc = next(d for d in docs if d.meta_data["sheet_name"] == "D")

    assert b_doc.meta_data["sheet_index"] == 2
    assert d_doc.meta_data["sheet_index"] == 4


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

    reader = ExcelReader(chunk=False, sheets=["First", 2])
    docs = reader.read(file_path)

    assert len(docs) == 2
    assert {doc.meta_data["sheet_name"] for doc in docs} == {"First", "Third"}
