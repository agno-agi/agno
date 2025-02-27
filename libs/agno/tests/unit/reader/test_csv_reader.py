import io
import tempfile
from pathlib import Path

import pytest

from agno.document.base import Document
from agno.document.reader.csv_reader import CSVReader, CSVUrlReader

# Sample CSV data
SAMPLE_CSV = """name,age,city
John,30,New York
Jane,25,San Francisco
Bob,40,Chicago"""

SAMPLE_CSV_COMPLEX = """product,"description with, comma",price
"Laptop, Pro","High performance, ultra-thin",1200.99
"Phone XL","5G compatible, water resistant",899.50"""


class TestCSVReader:
    def setup_method(self):
        # Create a temporary file for testing
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_file_path = Path(self.temp_dir.name) / "test.csv"
        with open(self.temp_file_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_CSV)

        # Create another temp file with complex CSV content
        self.complex_csv_path = Path(self.temp_dir.name) / "complex.csv"
        with open(self.complex_csv_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_CSV_COMPLEX)

    def teardown_method(self):
        self.temp_dir.cleanup()

    def test_read_path(self):
        # Test reading from a Path
        reader = CSVReader()
        documents = reader.read(self.temp_file_path)

        assert len(documents) == 1
        assert documents[0].name == "test"
        assert documents[0].id == "test_1"

        expected_content = "name, age, city John, 30, New York Jane, 25, San Francisco Bob, 40, Chicago "
        assert documents[0].content == expected_content

    def test_read_file_object(self):
        # Test reading from a file-like object
        file_obj = io.BytesIO(SAMPLE_CSV.encode("utf-8"))
        file_obj.name = "memory.csv"

        reader = CSVReader()
        documents = reader.read(file_obj)

        assert len(documents) == 1
        assert documents[0].name == "memory"
        assert documents[0].id == "memory_1"

        # Test content - rows are separated by spaces, not newlines
        expected_content = "name, age, city John, 30, New York Jane, 25, San Francisco Bob, 40, Chicago "
        assert documents[0].content == expected_content

    def test_read_complex_csv(self):
        # Test reading CSV with quotes and commas inside fields
        reader = CSVReader()
        documents = reader.read(self.complex_csv_path, delimiter=",", quotechar='"')

        assert len(documents) == 1
        assert documents[0].id == "complex_1"

        expected_content = "product, description with, comma, price Laptop, Pro, High performance, ultra-thin, 1200.99 Phone XL, 5G compatible, water resistant, 899.50 "
        assert documents[0].content == expected_content

    def test_read_nonexistent_file(self):
        # Test reading non-existent file
        reader = CSVReader()
        nonexistent_path = Path(self.temp_dir.name) / "nonexistent.csv"
        documents = reader.read(nonexistent_path)

        assert documents == []

    def test_read_with_chunking(self):
        # Mock chunk_document to return multiple documents from a single one
        reader = CSVReader()

        def mock_chunk(doc):
            # Create two chunks from the original document
            return [
                Document(name=f"{doc.name}_chunk1", id=f"{doc.id}_chunk1", content="Chunk 1 content"),
                Document(name=f"{doc.name}_chunk2", id=f"{doc.id}_chunk2", content="Chunk 2 content"),
            ]

        reader.chunk = True
        reader.chunk_document = mock_chunk

        documents = reader.read(self.temp_file_path)

        assert len(documents) == 2
        assert documents[0].name == "test_chunk1"
        assert documents[0].id == "test_chunk1"  # Corrected ID format
        assert documents[1].name == "test_chunk2"
        assert documents[1].id == "test_chunk2"  # Corrected ID format
        assert documents[0].content == "Chunk 1 content"
        assert documents[1].content == "Chunk 2 content"

    @pytest.mark.asyncio
    async def test_async_read_path(self):
        reader = CSVReader()
        documents = await reader.async_read(self.temp_file_path)

        # SAMPLE_CSV has 4 rows  => <10 rows = 1 page
        assert len(documents) == 1

        # Check first document (header row)
        assert documents[0].name == "test"
        assert documents[0].id == "test_1"
        assert documents[0].content == "name, age, city John, 30, New York Jane, 25, San Francisco Bob, 40, Chicago"

    @pytest.mark.asyncio
    async def test_async_read_multi_page_csv(self):
        """Test async_read with a CSV that has 11 rows (which triggers page-based processing)."""
        # Create a CSV with 11 rows
        multi_page_csv = """name,age,city
    row1,30,City1
    row2,31,City2
    row3,32,City3
    row4,33,City4
    row5,34,City5
    row6,35,City6
    row7,36,City7
    row8,37,City8
    row9,38,City9
    row10,39,City10"""

        multi_page_path = Path(self.temp_dir.name) / "multi_page.csv"
        with open(multi_page_path, "w", encoding="utf-8") as f:
            f.write(multi_page_csv)

        reader = CSVReader()
        documents = await reader.async_read(multi_page_path, page_size=5)  # Set page size to 5 for testing

        # With 11 rows and page_size=5, we should get 3 pages: [0-4], [5-9], [10]
        assert len(documents) == 3

        # Check first page (first 5 rows)
        assert documents[0].name == "multi_page"
        assert documents[0].id == "multi_page_page1_1"
        assert "page" in documents[0].meta_data
        assert documents[0].meta_data["page"] == 1
        assert documents[0].meta_data["start_row"] == 1
        assert documents[0].meta_data["rows"] == 5

        # First page should contain rows 1-5
        assert "name, age, city" in documents[0].content
        assert "row1, 30, City1" in documents[0].content
        assert "row2, 31, City2" in documents[0].content
        assert "row3, 32, City3" in documents[0].content
        assert "row4, 33, City4" in documents[0].content

        # Check second page (next 5 rows)
        assert documents[1].name == "multi_page"
        assert documents[1].id == "multi_page_page2_1"
        assert documents[1].meta_data["page"] == 2
        assert documents[1].meta_data["start_row"] == 6
        assert documents[1].meta_data["rows"] == 5

        # Second page should contain rows 6-10
        assert "row5, 34, City5" in documents[1].content
        assert "row6, 35, City6" in documents[1].content
        assert "row7, 36, City7" in documents[1].content
        assert "row8, 37, City8" in documents[1].content
        assert "row9, 38, City9" in documents[1].content

        # Check third page (remaining 1 row)
        assert documents[2].name == "multi_page"
        assert documents[2].id == "multi_page_page3_1"
        assert documents[2].meta_data["page"] == 3
        assert documents[2].meta_data["start_row"] == 11
        assert documents[2].meta_data["rows"] == 1

        # Third page should contain the last row
        assert "row10, 39, City10" in documents[2].content

        @pytest.mark.asyncio
        async def test_async_read_file_object(self):
            file_obj = io.BytesIO(SAMPLE_CSV.encode("utf-8"))
            file_obj.name = "memory.csv"

            reader = CSVReader()
            documents = await reader.async_read(file_obj)

            # SAMPLE_CSV has 4 rows (header + 3 data rows)
            assert len(documents) == 4
            assert documents[0].name == "memory"
            assert documents[0].id == "memory_1_1"
            assert documents[0].content == "name, age, city"

            # Check all rows
            assert documents[1].id == "memory_2_1"
            assert documents[1].content == "John, 30, New York"
            assert documents[2].id == "memory_3_1"
            assert documents[2].content == "Jane, 25, San Francisco"
            assert documents[3].id == "memory_4_1"
            assert documents[3].content == "Bob, 40, Chicago"

    @pytest.mark.asyncio
    async def test_async_read_with_chunking(self):
        reader = CSVReader()

        # Define a mock chunk_document
        def mock_chunk(doc):
            # Create two chunks from the original document
            return [
                Document(name=f"{doc.name}_chunk1", id=f"{doc.id}_chunk1", content=f"{doc.content}_chunked1"),
                Document(name=f"{doc.name}_chunk2", id=f"{doc.id}_chunk2", content=f"{doc.content}_chunked2"),
            ]

        reader.chunk = True
        reader.chunk_document = mock_chunk

        documents = await reader.async_read(self.temp_file_path)

        # Each row produces 2 chunks, and we have 4 rows
        assert len(documents) == 2  # 4 rows * 2 chunks per row

        # Check document structure for first row
        assert documents[0].id == "test_chunk1"  # First chunk of first row (corrected ID)
        assert documents[0].name == "test_chunk1"
        assert (
            documents[0].content
            == "name, age, city John, 30, New York Jane, 25, San Francisco Bob, 40, Chicago_chunked1"
        )

        assert documents[1].id == "test_chunk2"  # Second chunk of first row (corrected ID)
        assert documents[1].name == "test_chunk2"
        assert (
            documents[1].content
            == "name, age, city John, 30, New York Jane, 25, San Francisco Bob, 40, Chicago_chunked2"
        )

    @pytest.mark.asyncio
    async def test_async_read_empty_file(self):
        # Create an empty file
        empty_path = Path(self.temp_dir.name) / "empty.csv"
        with open(empty_path, "w", encoding="utf-8") as f:
            pass

        reader = CSVReader()
        documents = await reader.async_read(empty_path)

        assert documents == []


CSV_URL = "https://agno-public.s3.amazonaws.com/csvs/employees.csv"

# Expected content from the first employee
EXPECTED_FIRST_ROW = "EmployeeID, FirstName, LastName, Department, Role, Age, Salary, StartDate"
EXPECTED_SECOND_ROW = "101, John, Doe, Engineering, Software Engineer, 28, 75000, 2018-06-15"


class TestCSVUrlReaderWithURL:
    """Tests for CSVUrlReader using a CSV URL."""

    def test_read_url(self):
        """Test the synchronous read method with an actual URL."""
        reader = CSVUrlReader()
        documents = reader.read(CSV_URL)

        # Basic validation
        assert len(documents) == 2
        assert documents[0].name == "employees"
        assert documents[0].id == "employees_1"  # Corrected ID format

        # Content validation - check for expected fields in the content
        content = documents[0].content
        assert "EmployeeID" in content
        assert "FirstName" in content
        assert "LastName" in content
        assert "John" in content
        assert "Doe" in content
        assert "Engineering" in content
        assert "Software Engineer" in content
        assert "75000" in content

    @pytest.mark.asyncio
    async def test_async_read_url(self):
        """Test the asynchronous read method with an actual URL."""
        reader = CSVUrlReader()
        documents = await reader.async_read(CSV_URL)

        # In async mode, each page becomes a separate document
        assert len(documents) == 2

        # Validate header row
        assert documents[0].name == "employees"
        assert documents[0].id == "employees_page1_1"  # Corrected ID format
        assert EXPECTED_FIRST_ROW in documents[0].content
        assert EXPECTED_SECOND_ROW in documents[0].content

        # Validate first data row
        assert documents[1].name == "employees"
        assert documents[1].id == "employees_page1_2"  # Corrected ID format


if __name__ == "__main__":
    pytest.main(["-v"])
