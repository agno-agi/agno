import io
import tempfile
from pathlib import Path

import pytest

from agno.knowledge.document.base import Document
from agno.knowledge.reader.csv_reader import CSVReader

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

    assert len(documents) == 4
    assert documents[0].name == "test"
    assert documents[0].id.endswith("_1")

    expected_content_1 = "name, age, city"
    assert documents[0].content == expected_content_1

    expected_content_2 = "John, 30, New York"
    assert documents[1].content == expected_content_2

    expected_content_3 = "Jane, 25, San Francisco"
    assert documents[2].content == expected_content_3

    expected_content_4 = "Bob, 40, Chicago"
    assert documents[3].content == expected_content_4


def test_read_file_object(csv_reader):
    file_obj = io.BytesIO(SAMPLE_CSV.encode("utf-8"))
    file_obj.name = "memory.csv"

    documents = csv_reader.read(file_obj)

    assert len(documents) == 4
    assert documents[0].name == "memory"
    assert documents[0].id.endswith("_1")

    expected_content_1 = "name, age, city"
    assert documents[0].content == expected_content_1

    expected_content_2 = "John, 30, New York"
    assert documents[1].content == expected_content_2

    expected_content_3 = "Jane, 25, San Francisco"
    assert documents[2].content == expected_content_3

    expected_content_4 = "Bob, 40, Chicago"
    assert documents[3].content == expected_content_4


def test_read_complex_csv(csv_reader, complex_csv_file):
    documents = csv_reader.read(complex_csv_file, delimiter=",", quotechar='"')

    assert len(documents) == 3
    assert documents[0].id.endswith("_1")

    expected_content_1 = "product, description with, comma, price"
    assert documents[0].content == expected_content_1

    expected_content_2 = "Laptop, Pro, High performance, ultra-thin, 1200.99"
    assert documents[1].content == expected_content_2

    expected_content_3 = "Phone XL, 5G compatible, water resistant, 899.50"
    assert documents[2].content == expected_content_3


def test_read_nonexistent_file(csv_reader, temp_dir):
    nonexistent_path = temp_dir / "nonexistent.csv"
    with pytest.raises(FileNotFoundError, match="Could not find file"):
        csv_reader.read(nonexistent_path)


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
    assert documents[0].id.endswith("_chunk1")
    assert documents[1].name == "test_chunk2"
    assert documents[1].id.endswith("_chunk2")
    assert documents[0].content == "Chunk 1 content"
    assert documents[1].content == "Chunk 2 content"


@pytest.mark.asyncio
async def test_async_read_path(csv_reader, csv_file):
    documents = await csv_reader.async_read(csv_file)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].id.endswith("_1")
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
    assert documents[0].id is not None and isinstance(documents[0].id, str)
    assert documents[0].meta_data["page"] == 1
    assert documents[0].meta_data["start_row"] == 1
    assert documents[0].meta_data["rows"] == 5

    # Check second page
    assert documents[1].id is not None and isinstance(documents[1].id, str)
    assert documents[1].meta_data["page"] == 2
    assert documents[1].meta_data["start_row"] == 6
    assert documents[1].meta_data["rows"] == 5

    # Check third page
    assert documents[2].id is not None and isinstance(documents[2].id, str)
    assert documents[2].meta_data["page"] == 3
    assert documents[2].meta_data["start_row"] == 11
    assert documents[2].meta_data["rows"] == 1


@pytest.mark.asyncio
async def test_async_read_with_chunking(csv_reader, csv_file):
    async def mock_achunk(doc):
        return [
            Document(name=f"{doc.name}_chunk1", id=f"{doc.id}_chunk1", content=f"{doc.content}_chunked1"),
            Document(name=f"{doc.name}_chunk2", id=f"{doc.id}_chunk2", content=f"{doc.content}_chunked2"),
        ]

    csv_reader.chunk = True
    csv_reader.achunk_document = mock_achunk

    documents = await csv_reader.async_read(csv_file)

    assert len(documents) == 2
    assert documents[0].id.endswith("_chunk1")
    assert documents[0].name == "test_chunk1"
    assert documents[1].id.endswith("_chunk2")
    assert documents[1].name == "test_chunk2"


@pytest.mark.asyncio
async def test_async_read_empty_file(csv_reader, temp_dir):
    empty_path = temp_dir / "empty.csv"
    empty_path.touch()

    documents = await csv_reader.async_read(empty_path)
    assert documents == []


LATIN1_CSV = "name,city\nJosé,São Paulo\nFrançois,Montréal"


def test_read_bytesio_with_custom_encoding():
    """Test reading BytesIO with custom encoding (Latin-1).

    This tests the fix for BUG-007 where BytesIO reads were hardcoded to UTF-8.
    """
    # Encode as Latin-1 (single-byte encoding for accented chars)
    latin1_bytes = LATIN1_CSV.encode("latin-1")
    file_obj = io.BytesIO(latin1_bytes)
    file_obj.name = "latin1.csv"

    # Create reader with Latin-1 encoding
    reader = CSVReader(encoding="latin-1", chunk=False)
    documents = reader.read(file_obj)

    assert len(documents) == 1
    content = documents[0].content

    # Verify accented characters are correctly decoded
    assert "José" in content
    assert "São Paulo" in content
    assert "François" in content
    assert "Montréal" in content


def test_read_bytesio_wrong_encoding_fails():
    """Test that reading Latin-1 bytes as UTF-8 fails or corrupts data.

    This demonstrates why the encoding parameter is important.
    """
    # Encode as Latin-1
    latin1_bytes = LATIN1_CSV.encode("latin-1")
    file_obj = io.BytesIO(latin1_bytes)
    file_obj.name = "latin1.csv"

    # Try to read with default UTF-8 encoding (should fail or corrupt)
    reader = CSVReader(chunk=False)  # Uses UTF-8 by default

    # This should either raise an error or produce corrupted output
    documents = reader.read(file_obj)

    # If it didn't raise, the content should be corrupted (mojibake)
    if documents:
        content = documents[0].content
        # The accented characters should NOT be correctly decoded
        assert "José" not in content or "São Paulo" not in content


def test_read_path_with_custom_encoding(temp_dir):
    """Test reading Path with custom encoding."""
    file_path = temp_dir / "latin1.csv"
    with open(file_path, "w", encoding="latin-1") as f:
        f.write(LATIN1_CSV)

    reader = CSVReader(encoding="latin-1", chunk=False)
    documents = reader.read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "José" in content
    assert "São Paulo" in content


@pytest.mark.asyncio
async def test_async_read_bytesio_with_custom_encoding():
    """Test async reading BytesIO with custom encoding (Latin-1).

    This tests the fix for BUG-007 in the async path.
    """
    latin1_bytes = LATIN1_CSV.encode("latin-1")
    file_obj = io.BytesIO(latin1_bytes)
    file_obj.name = "latin1.csv"

    reader = CSVReader(encoding="latin-1", chunk=False)
    documents = await reader.async_read(file_obj)

    assert len(documents) == 1
    content = documents[0].content
    assert "José" in content
    assert "São Paulo" in content


@pytest.mark.asyncio
async def test_async_read_path_with_custom_encoding(temp_dir):
    """Test async reading Path with custom encoding.

    This tests the fix for BUG-007 in the async path with Path input.
    """
    file_path = temp_dir / "latin1.csv"
    with open(file_path, "w", encoding="latin-1") as f:
        f.write(LATIN1_CSV)

    reader = CSVReader(encoding="latin-1", chunk=False)
    documents = await reader.async_read(file_path)

    assert len(documents) == 1
    content = documents[0].content
    assert "José" in content
    assert "São Paulo" in content
