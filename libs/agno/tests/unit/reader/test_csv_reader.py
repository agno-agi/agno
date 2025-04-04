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

CSV_URL = "https://agno-public.s3.amazonaws.com/csvs/employees.csv"


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
def csv_file(temp_dir):
    file_path = temp_dir / "test.csv"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(SAMPLE_CSV)
    return file_path


@pytest.fixture
def complex_csv_file(temp_dir):
    file_path = temp_dir / "complex.csv"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(SAMPLE_CSV_COMPLEX)
    return file_path


@pytest.fixture
def csv_reader():
    return CSVReader()


def test_read_path(csv_reader, csv_file):
    documents = csv_reader.read(csv_file)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].id == "test_1"

    expected_content = "name, age, city John, 30, New York Jane, 25, San Francisco Bob, 40, Chicago "
    assert documents[0].content == expected_content


def test_read_file_object(csv_reader):
    file_obj = io.BytesIO(SAMPLE_CSV.encode("utf-8"))
    file_obj.name = "memory.csv"

    documents = csv_reader.read(file_obj)

    assert len(documents) == 1
    assert documents[0].name == "memory"
    assert documents[0].id == "memory_1"

    expected_content = "name, age, city John, 30, New York Jane, 25, San Francisco Bob, 40, Chicago "
    assert documents[0].content == expected_content


def test_read_complex_csv(csv_reader, complex_csv_file):
    documents = csv_reader.read(complex_csv_file, delimiter=",", quotechar='"')

    assert len(documents) == 1
    assert documents[0].id == "complex_1"

    expected_content = "product, description with, comma, price Laptop, Pro, High performance, ultra-thin, 1200.99 Phone XL, 5G compatible, water resistant, 899.50 "
    assert documents[0].content == expected_content


def test_read_nonexistent_file(csv_reader, temp_dir):
    nonexistent_path = temp_dir / "nonexistent.csv"
    documents = csv_reader.read(nonexistent_path)
    assert documents == []


def test_read_with_chunking(csv_reader, csv_file):
    def mock_chunk(doc):
        return [
            Document(name=f"{doc.name}_chunk1", id=f"{doc.id}_chunk1", content="Chunk 1 content"),
            Document(name=f"{doc.name}_chunk2", id=f"{doc.id}_chunk2", content="Chunk 2 content"),
        ]

    csv_reader.chunk = True
    csv_reader.chunk_document = mock_chunk

    documents = csv_reader.read(csv_file)

    assert len(documents) == 2
    assert documents[0].name == "test_chunk1"
    assert documents[0].id == "test_chunk1"
    assert documents[1].name == "test_chunk2"
    assert documents[1].id == "test_chunk2"
    assert documents[0].content == "Chunk 1 content"
    assert documents[1].content == "Chunk 2 content"


@pytest.mark.asyncio
async def test_async_read_path(csv_reader, csv_file):
    documents = await csv_reader.async_read(csv_file)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].id == "test_1"
    assert documents[0].content == "name, age, city John, 30, New York Jane, 25, San Francisco Bob, 40, Chicago"


@pytest.fixture
def multi_page_csv_file(temp_dir):
    content = """name,age,city
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

    file_path = temp_dir / "multi_page.csv"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return file_path


@pytest.mark.asyncio
async def test_async_read_multi_page_csv(csv_reader, multi_page_csv_file):
    documents = await csv_reader.async_read(multi_page_csv_file, page_size=5)

    assert len(documents) == 3

    # Check first page
    assert documents[0].name == "multi_page"
    assert documents[0].id == "multi_page_page1_1"
    assert documents[0].meta_data["page"] == 1
    assert documents[0].meta_data["start_row"] == 1
    assert documents[0].meta_data["rows"] == 5

    # Check second page
    assert documents[1].id == "multi_page_page2_1"
    assert documents[1].meta_data["page"] == 2
    assert documents[1].meta_data["start_row"] == 6
    assert documents[1].meta_data["rows"] == 5

    # Check third page
    assert documents[2].id == "multi_page_page3_1"
    assert documents[2].meta_data["page"] == 3
    assert documents[2].meta_data["start_row"] == 11
    assert documents[2].meta_data["rows"] == 1


@pytest.mark.asyncio
async def test_async_read_with_chunking(csv_reader, csv_file):
    def mock_chunk(doc):
        return [
            Document(name=f"{doc.name}_chunk1", id=f"{doc.id}_chunk1", content=f"{doc.content}_chunked1"),
            Document(name=f"{doc.name}_chunk2", id=f"{doc.id}_chunk2", content=f"{doc.content}_chunked2"),
        ]

    csv_reader.chunk = True
    csv_reader.chunk_document = mock_chunk

    documents = await csv_reader.async_read(csv_file)

    assert len(documents) == 2
    assert documents[0].id == "test_chunk1"
    assert documents[0].name == "test_chunk1"
    assert documents[1].id == "test_chunk2"
    assert documents[1].name == "test_chunk2"


@pytest.mark.asyncio
async def test_async_read_empty_file(csv_reader, temp_dir):
    empty_path = temp_dir / "empty.csv"
    empty_path.touch()

    documents = await csv_reader.async_read(empty_path)
    assert documents == []


@pytest.fixture
def csv_url_reader():
    return CSVUrlReader()


def test_read_url(csv_url_reader):
    documents = csv_url_reader.read(CSV_URL)

    assert len(documents) == 2
    assert documents[0].name == "employees"
    assert documents[0].id == "employees_1"

    content = documents[0].content
    assert all(field in content for field in ["EmployeeID", "FirstName", "LastName", "Department"])
    assert all(value in content for value in ["John", "Doe", "Engineering", "Software Engineer", "75000"])


@pytest.mark.asyncio
async def test_async_read_url(csv_url_reader):
    documents = await csv_url_reader.async_read(CSV_URL)

    assert len(documents) == 2
    assert documents[0].name == "employees"
    assert documents[0].id == "employees_page1_1"
    assert documents[1].id == "employees_page1_2"

    expected_first_row = "EmployeeID, FirstName, LastName, Department, Role, Age, Salary, StartDate"
    expected_second_row = "101, John, Doe, Engineering, Software Engineer, 28, 75000, 2018-06-15"

    assert expected_first_row in documents[0].content
    assert expected_second_row in documents[0].content
