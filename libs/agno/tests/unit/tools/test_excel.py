"""Unit tests for ExcelTools class."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.tools.excel import ExcelTools


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
def excel_tools(temp_dir):
    """Create ExcelTools instance with temporary base directory."""
    return ExcelTools(base_dir=temp_dir)


@pytest.fixture
def excel_tools_all(temp_dir):
    """Create ExcelTools instance with all tools enabled."""
    return ExcelTools(base_dir=temp_dir, all=True)


class TestExcelToolsInit:
    """Tests for ExcelTools initialization."""

    def test_init_with_default_tools(self, temp_dir):
        """Test initialization with default tools."""
        tools = ExcelTools(base_dir=temp_dir)
        function_names = [func.name for func in tools.functions.values()]

        assert "create_workbook" in function_names
        assert "write_data" in function_names
        assert "read_data" in function_names
        assert "add_sheet" in function_names
        assert "list_sheets" in function_names
        # Disabled by default
        assert "add_formula" not in function_names
        assert "format_cells" not in function_names

    def test_init_with_all_tools(self, temp_dir):
        """Test initialization with all tools enabled."""
        tools = ExcelTools(base_dir=temp_dir, all=True)
        function_names = [func.name for func in tools.functions.values()]

        assert "create_workbook" in function_names
        assert "write_data" in function_names
        assert "read_data" in function_names
        assert "add_sheet" in function_names
        assert "list_sheets" in function_names
        assert "add_formula" in function_names
        assert "format_cells" in function_names

    def test_init_with_selective_tools(self, temp_dir):
        """Test initialization with only selected tools."""
        tools = ExcelTools(
            base_dir=temp_dir,
            enable_create_workbook=True,
            enable_write_data=False,
            enable_read_data=True,
            enable_add_sheet=False,
            enable_list_sheets=True,
        )
        function_names = [func.name for func in tools.functions.values()]

        assert "create_workbook" in function_names
        assert "write_data" not in function_names
        assert "read_data" in function_names
        assert "add_sheet" not in function_names
        assert "list_sheets" in function_names

    def test_init_default_base_dir(self):
        """Test initialization uses current directory as default."""
        tools = ExcelTools()
        assert tools.base_dir == Path.cwd().resolve()


class TestCreateWorkbook:
    """Tests for create_workbook method."""

    def test_create_workbook_success(self, excel_tools, temp_dir):
        """Test successful workbook creation."""
        result = excel_tools.create_workbook("test.xlsx")
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["file"] == "test.xlsx"
        assert (temp_dir / "test.xlsx").exists()

    def test_create_workbook_adds_extension(self, excel_tools, temp_dir):
        """Test that .xlsx extension is added if missing."""
        result = excel_tools.create_workbook("test")
        result_data = json.loads(result)

        assert result_data["file"] == "test.xlsx"
        assert (temp_dir / "test.xlsx").exists()

    def test_create_workbook_with_sheet_name(self, excel_tools, temp_dir):
        """Test workbook creation with custom sheet name."""
        result = excel_tools.create_workbook("test.xlsx", sheet_name="MySheet")
        result_data = json.loads(result)

        assert result_data["sheet"] == "MySheet"

    def test_create_workbook_no_overwrite(self, excel_tools, temp_dir):
        """Test that existing file is not overwritten by default."""
        excel_tools.create_workbook("test.xlsx")
        result = excel_tools.create_workbook("test.xlsx")
        result_data = json.loads(result)

        assert "error" in result_data
        assert "already exists" in result_data["error"]

    def test_create_workbook_with_overwrite(self, excel_tools, temp_dir):
        """Test that existing file can be overwritten."""
        excel_tools.create_workbook("test.xlsx")
        result = excel_tools.create_workbook("test.xlsx", overwrite=True)
        result_data = json.loads(result)

        assert result_data["success"] is True

    def test_create_workbook_path_escape(self, excel_tools):
        """Test that path escape attempts are blocked."""
        result = excel_tools.create_workbook("../escape.xlsx")
        result_data = json.loads(result)

        assert "error" in result_data


class TestWriteData:
    """Tests for write_data method."""

    def test_write_data_success(self, excel_tools, temp_dir):
        """Test successful data writing."""
        excel_tools.create_workbook("test.xlsx")

        data = [["Name", "Age"], ["Alice", 30], ["Bob", 25]]
        result = excel_tools.write_data("test.xlsx", data)
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["rows_written"] == 3
        assert result_data["columns_written"] == 2

    def test_write_data_to_specific_sheet(self, excel_tools, temp_dir):
        """Test writing data to a specific sheet."""
        excel_tools.create_workbook("test.xlsx")
        excel_tools.add_sheet("test.xlsx", "Data")

        data = [["Value"], [100]]
        result = excel_tools.write_data("test.xlsx", data, sheet_name="Data")
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["sheet"] == "Data"

    def test_write_data_with_start_cell(self, excel_tools, temp_dir):
        """Test writing data starting from a specific cell."""
        excel_tools.create_workbook("test.xlsx")

        data = [["X", "Y"]]
        result = excel_tools.write_data("test.xlsx", data, start_cell="C3")
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["start_cell"] == "C3"

    def test_write_data_file_not_found(self, excel_tools):
        """Test writing to non-existent file."""
        result = excel_tools.write_data("missing.xlsx", [["data"]])
        result_data = json.loads(result)

        assert "error" in result_data
        assert "not found" in result_data["error"]

    def test_write_data_sheet_not_found(self, excel_tools, temp_dir):
        """Test writing to non-existent sheet."""
        excel_tools.create_workbook("test.xlsx")

        result = excel_tools.write_data("test.xlsx", [["data"]], sheet_name="Missing")
        result_data = json.loads(result)

        assert "error" in result_data
        assert "not found" in result_data["error"]


class TestReadData:
    """Tests for read_data method."""

    def test_read_data_success(self, excel_tools, temp_dir):
        """Test successful data reading."""
        excel_tools.create_workbook("test.xlsx")
        excel_tools.write_data("test.xlsx", [["A", "B"], [1, 2]])

        result = excel_tools.read_data("test.xlsx")
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["data"] == [["A", "B"], [1, 2]]
        assert result_data["rows"] == 2

    def test_read_data_from_specific_sheet(self, excel_tools, temp_dir):
        """Test reading data from a specific sheet."""
        excel_tools.create_workbook("test.xlsx")
        excel_tools.add_sheet("test.xlsx", "Data")
        excel_tools.write_data("test.xlsx", [["Test"]], sheet_name="Data")

        result = excel_tools.read_data("test.xlsx", sheet_name="Data")
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["sheet"] == "Data"

    def test_read_data_file_not_found(self, excel_tools):
        """Test reading from non-existent file."""
        result = excel_tools.read_data("missing.xlsx")
        result_data = json.loads(result)

        assert "error" in result_data
        assert "not found" in result_data["error"]


class TestAddSheet:
    """Tests for add_sheet method."""

    def test_add_sheet_success(self, excel_tools, temp_dir):
        """Test successful sheet addition."""
        excel_tools.create_workbook("test.xlsx")

        result = excel_tools.add_sheet("test.xlsx", "NewSheet")
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["new_sheet"] == "NewSheet"
        assert "NewSheet" in result_data["all_sheets"]

    def test_add_sheet_at_position(self, excel_tools, temp_dir):
        """Test adding sheet at specific position."""
        excel_tools.create_workbook("test.xlsx")
        excel_tools.add_sheet("test.xlsx", "Second")

        result = excel_tools.add_sheet("test.xlsx", "First", position=0)
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["all_sheets"][0] == "First"

    def test_add_sheet_duplicate_name(self, excel_tools, temp_dir):
        """Test adding sheet with duplicate name."""
        excel_tools.create_workbook("test.xlsx", sheet_name="MySheet")

        result = excel_tools.add_sheet("test.xlsx", "MySheet")
        result_data = json.loads(result)

        assert "error" in result_data
        assert "already exists" in result_data["error"]

    def test_add_sheet_file_not_found(self, excel_tools):
        """Test adding sheet to non-existent file."""
        result = excel_tools.add_sheet("missing.xlsx", "Sheet")
        result_data = json.loads(result)

        assert "error" in result_data
        assert "not found" in result_data["error"]


class TestListSheets:
    """Tests for list_sheets method."""

    def test_list_sheets_success(self, excel_tools, temp_dir):
        """Test successful sheet listing."""
        excel_tools.create_workbook("test.xlsx")
        excel_tools.add_sheet("test.xlsx", "Sheet2")
        excel_tools.add_sheet("test.xlsx", "Sheet3")

        result = excel_tools.list_sheets("test.xlsx")
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["count"] == 3
        assert "Sheet2" in result_data["sheets"]
        assert "Sheet3" in result_data["sheets"]

    def test_list_sheets_file_not_found(self, excel_tools):
        """Test listing sheets from non-existent file."""
        result = excel_tools.list_sheets("missing.xlsx")
        result_data = json.loads(result)

        assert "error" in result_data
        assert "not found" in result_data["error"]


class TestAddFormula:
    """Tests for add_formula method."""

    def test_add_formula_success(self, excel_tools_all, temp_dir):
        """Test successful formula addition."""
        excel_tools_all.create_workbook("test.xlsx")
        excel_tools_all.write_data("test.xlsx", [[10, 20]])

        result = excel_tools_all.add_formula("test.xlsx", "C1", "=SUM(A1:B1)")
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["cell"] == "C1"
        assert result_data["formula"] == "=SUM(A1:B1)"

    def test_add_formula_without_equals(self, excel_tools_all, temp_dir):
        """Test that formula without = gets it added."""
        excel_tools_all.create_workbook("test.xlsx")

        result = excel_tools_all.add_formula("test.xlsx", "A1", "SUM(B1:C1)")
        result_data = json.loads(result)

        assert result_data["formula"] == "=SUM(B1:C1)"

    def test_add_formula_file_not_found(self, excel_tools_all):
        """Test adding formula to non-existent file."""
        result = excel_tools_all.add_formula("missing.xlsx", "A1", "=1+1")
        result_data = json.loads(result)

        assert "error" in result_data
        assert "not found" in result_data["error"]


class TestFormatCells:
    """Tests for format_cells method."""

    def test_format_cells_bold(self, excel_tools_all, temp_dir):
        """Test applying bold formatting."""
        excel_tools_all.create_workbook("test.xlsx")
        excel_tools_all.write_data("test.xlsx", [["Header"]])

        result = excel_tools_all.format_cells("test.xlsx", "A1", bold=True)
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["cells_formatted"] == 1

    def test_format_cells_range(self, excel_tools_all, temp_dir):
        """Test formatting a range of cells."""
        excel_tools_all.create_workbook("test.xlsx")
        excel_tools_all.write_data("test.xlsx", [["A", "B"], ["C", "D"]])

        result = excel_tools_all.format_cells("test.xlsx", "A1:B2", bold=True, font_size=14)
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["cells_formatted"] == 4

    def test_format_cells_file_not_found(self, excel_tools_all):
        """Test formatting in non-existent file."""
        result = excel_tools_all.format_cells("missing.xlsx", "A1", bold=True)
        result_data = json.loads(result)

        assert "error" in result_data
        assert "not found" in result_data["error"]


class TestPathSecurity:
    """Tests for path security."""

    def test_path_escape_blocked_create(self, excel_tools):
        """Test path escape is blocked for create."""
        result = excel_tools.create_workbook("../../escape.xlsx")
        result_data = json.loads(result)
        assert "error" in result_data

    def test_path_escape_blocked_read(self, excel_tools):
        """Test path escape is blocked for read."""
        result = excel_tools.read_data("../../escape.xlsx")
        result_data = json.loads(result)
        assert "error" in result_data

    def test_path_escape_blocked_write(self, excel_tools):
        """Test path escape is blocked for write."""
        result = excel_tools.write_data("../../escape.xlsx", [["data"]])
        result_data = json.loads(result)
        assert "error" in result_data


class TestOpenpyxlNotInstalled:
    """Tests for handling missing openpyxl."""

    def test_openpyxl_not_installed(self, temp_dir):
        """Test error message when openpyxl is not installed."""
        tools = ExcelTools(base_dir=temp_dir)

        with patch.dict("sys.modules", {"openpyxl": None}):
            with patch.object(
                tools,
                "_get_openpyxl",
                side_effect=ImportError("openpyxl not installed"),
            ):
                result = tools.create_workbook("test.xlsx")
                result_data = json.loads(result)

                assert "error" in result_data
                assert "openpyxl" in result_data["error"].lower()
