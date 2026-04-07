import io
import tempfile
from pathlib import Path

import pytest

from agno.knowledge.reader.field_labeled_csv_reader import FieldLabeledCSVReader

# Sample CSV data
SAMPLE_CSV = """name,age,city
John,30,New York
Jane,25,San Francisco
Bob,40,Chicago"""

SAMPLE_CSV_COMPLEX = """product,"description with, comma",price
"Laptop, Pro","High performance, ultra-thin",1200.99
"Phone XL","5G compatible, water resistant",899.50"""

SAMPLE_CSV_WITH_UNDERSCORES = """product_name,unit_price,product_category
Product123,15.99,Electronics
Product456,29.99,Books"""


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
def underscore_csv_file(temp_dir):
    file_path = temp_dir / "underscore.csv"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(SAMPLE_CSV_WITH_UNDERSCORES)
    return file_path


@pytest.fixture
def field_labeled_reader():
    return FieldLabeledCSVReader()


@pytest.fixture
def field_labeled_reader_with_config():
    return FieldLabeledCSVReader(
        chunk_title="📄 Entry",
        field_names=["Full Name", "Age in Years", "City Location"],
        format_headers=True,
        skip_empty_fields=True,
    )


def test_read_path_basic(field_labeled_reader, csv_file):
    """Test basic reading from file path with default configuration."""
    documents = field_labeled_reader.read(csv_file)

    assert len(documents) == 3  # 3 data rows (excluding header)
    assert documents[0].name == "test"
    assert documents[0].id == "test_row_1"

    # Check first document content
    expected_content_1 = "Name: John\nAge: 30\nCity: New York"
    assert documents[0].content == expected_content_1

    # Check second document content
    expected_content_2 = "Name: Jane\nAge: 25\nCity: San Francisco"
    assert documents[1].content == expected_content_2

    # Check third document content
    expected_content_3 = "Name: Bob\nAge: 40\nCity: Chicago"
    assert documents[2].content == expected_content_3


def test_read_with_custom_field_names(field_labeled_reader_with_config, csv_file):
    """Test reading with custom field names and title."""
    documents = field_labeled_reader_with_config.read(csv_file)

    assert len(documents) == 3
    assert documents[0].name == "test"
    assert documents[0].id == "test_row_1"

    # Check content with custom field names and title
    expected_content = """📄 Entry
Full Name: John
Age in Years: 30
City Location: New York"""
    assert documents[0].content == expected_content

    # Check metadata
    assert documents[0].meta_data["row_index"] == 0
    assert documents[0].meta_data["headers"] == ["name", "age", "city"]
    assert documents[0].meta_data["total_rows"] == 3
    assert documents[0].meta_data["source"] == "field_labeled_csv_reader"


def test_read_file_object(
    field_labeled_reader,
):
    """Test reading from file-like object."""
    file_obj = io.BytesIO(SAMPLE_CSV.encode("utf-8"))
    file_obj.name = "memory.csv"

    documents = field_labeled_reader.read(file_obj)

    assert len(documents) == 3
    assert documents[0].name == "memory"
    assert documents[0].id == "memory_row_1"

    expected_content = "Name: John\nAge: 30\nCity: New York"
    assert documents[0].content == expected_content


def test_read_complex_csv_with_commas(field_labeled_reader, complex_csv_file):
    """Test reading CSV with commas inside quoted fields."""
    documents = field_labeled_reader.read(complex_csv_file, delimiter=",", quotechar='"')

    assert len(documents) == 2
    assert documents[0].id == "complex_row_1"

    # Verify that commas within fields are preserved
    expected_content_1 = """Product: Laptop, Pro
Description With, Comma: High performance, ultra-thin
Price: 1200.99"""
    assert documents[0].content == expected_content_1

    expected_content_2 = """Product: Phone XL
Description With, Comma: 5G compatible, water resistant
Price: 899.50"""
    assert documents[1].content == expected_content_2


def test_format_headers(underscore_csv_file):
    """Test header formatting functionality."""
    reader = FieldLabeledCSVReader(format_headers=True)
    documents = reader.read(underscore_csv_file)

    assert len(documents) == 2

    # Check that underscores are replaced with spaces and title cased
    expected_content = """Product Name: Product123
Unit Price: 15.99
Product Category: Electronics"""
    assert documents[0].content == expected_content


def test_skip_empty_fields():
    """Test skipping empty fields functionality."""
    csv_with_empty = """name,description,price
Product A,,19.99
Product B,Good product,
Product C,Great product,29.99"""

    reader = FieldLabeledCSVReader(skip_empty_fields=True)
    file_obj = io.BytesIO(csv_with_empty.encode("utf-8"))
    file_obj.name = "empty_fields.csv"

    documents = reader.read(file_obj)

    assert len(documents) == 3

    # First product - missing description
    expected_content_1 = "Name: Product A\nPrice: 19.99"
    assert documents[0].content == expected_content_1

    # Second product - missing price
    expected_content_2 = "Name: Product B\nDescription: Good product"
    assert documents[1].content == expected_content_2

    # Third product - all fields present
    expected_content_3 = "Name: Product C\nDescription: Great product\nPrice: 29.99"
    assert documents[2].content == expected_content_3


def test_dont_skip_empty_fields():
    """Test including empty fields functionality."""
    csv_with_empty = """name,description,price
Product A,,19.99"""

    reader = FieldLabeledCSVReader(skip_empty_fields=False)
    file_obj = io.BytesIO(csv_with_empty.encode("utf-8"))
    file_obj.name = "empty_fields.csv"

    documents = reader.read(file_obj)

    assert len(documents) == 1

    # Should include empty description field
    expected_content = "Name: Product A\nDescription: \nPrice: 19.99"
    assert documents[0].content == expected_content


def test_title_rotation():
    """Test title rotation with list of titles."""
    csv_data = """name,value
Item1,Value1
Item2,Value2
Item3,Value3"""

    reader = FieldLabeledCSVReader(chunk_title=["🔵 Entry A", "🔴 Entry B"], format_headers=True)
    file_obj = io.BytesIO(csv_data.encode("utf-8"))
    file_obj.name = "rotation.csv"

    documents = reader.read(file_obj)

    assert len(documents) == 3

    # Check title rotation
    assert documents[0].content.startswith("🔵 Entry A")
    assert documents[1].content.startswith("🔴 Entry B")
    assert documents[2].content.startswith("🔵 Entry A")  # Rotates back


def test_read_nonexistent_file(field_labeled_reader, temp_dir):
    """Test reading nonexistent file raises FileNotFoundError."""
    nonexistent_path = temp_dir / "nonexistent.csv"
    with pytest.raises(FileNotFoundError):
        field_labeled_reader.read(nonexistent_path)


def test_read_empty_csv_file(field_labeled_reader, temp_dir):
    """Test reading empty CSV file."""
    empty_path = temp_dir / "empty.csv"
    empty_path.touch()

    documents = field_labeled_reader.read(empty_path)
    assert documents == []


def test_read_headers_only_csv(field_labeled_reader, temp_dir):
    """Test reading CSV with headers but no data rows."""
    headers_only_path = temp_dir / "headers_only.csv"
    with open(headers_only_path, "w", encoding="utf-8") as f:
        f.write("name,age,city")

    documents = field_labeled_reader.read(headers_only_path)
    assert documents == []


def test_field_names_mismatch():
    """Test behavior when field_names length doesn't match CSV columns."""
    csv_data = """name,age,city
John,30,New York"""

    # Fewer field names than columns
    reader = FieldLabeledCSVReader(
        field_names=["Full Name", "Age"]  # Missing third field name
    )
    file_obj = io.BytesIO(csv_data.encode("utf-8"))
    file_obj.name = "mismatch.csv"

    documents = reader.read(file_obj)

    assert len(documents) == 1

    # Should use custom names for first 2, formatted header for 3rd
    expected_content = "Full Name: John\nAge: 30\nCity: New York"
    assert documents[0].content == expected_content


@pytest.mark.asyncio
async def test_async_read_small_file(field_labeled_reader, csv_file):
    """Test async reading of small files (≤10 rows)."""
    documents = await field_labeled_reader.async_read(csv_file)

    assert len(documents) == 3
    assert documents[0].name == "test"
    assert documents[0].id == "test_row_1"

    expected_content = "Name: John\nAge: 30\nCity: New York"
    assert documents[0].content == expected_content


@pytest.fixture
def large_csv_file(temp_dir):
    """Create CSV file with >10 rows for testing pagination."""
    content = ["name,age,city"]
    for i in range(1, 16):  # 15 data rows
        content.append(f"Person{i},{20 + i},City{i}")

    file_path = temp_dir / "large.csv"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(content))
    return file_path


@pytest.mark.asyncio
async def test_async_read_large_file(field_labeled_reader, large_csv_file):
    """Test async reading of large files with pagination."""
    documents = await field_labeled_reader.async_read(large_csv_file, page_size=5)

    assert len(documents) == 15  # 15 data rows
    assert documents[0].name == "large"
    assert documents[0].id == "large_row_1"

    # Check first document
    expected_content_1 = "Name: Person1\nAge: 21\nCity: City1"
    assert documents[0].content == expected_content_1

    # Check last document
    expected_content_15 = "Name: Person15\nAge: 35\nCity: City15"
    assert documents[14].content == expected_content_15

    # Check metadata includes page info for large files
    assert documents[0].meta_data["page"] == 1
    assert documents[5].meta_data["page"] == 2  # Second page
    assert documents[10].meta_data["page"] == 3  # Third page


@pytest.mark.asyncio
async def test_async_read_with_custom_config(large_csv_file):
    """Test async reading with custom configuration."""
    reader = FieldLabeledCSVReader(
        chunk_title="👤 Person Info",
        field_names=["Full Name", "Years Old", "Location"],
        format_headers=False,
        skip_empty_fields=True,
    )

    documents = await reader.async_read(large_csv_file, page_size=3)

    assert len(documents) == 15
    assert documents[0].id == "large_row_1"

    # Check custom field names and title are applied
    expected_content = """👤 Person Info
Full Name: Person1
Years Old: 21
Location: City1"""
    assert documents[0].content == expected_content


@pytest.mark.asyncio
async def test_async_read_empty_file(field_labeled_reader, temp_dir):
    """Test async reading of empty file."""
    empty_path = temp_dir / "empty.csv"
    empty_path.touch()

    documents = await field_labeled_reader.async_read(empty_path)
    assert documents == []


@pytest.mark.asyncio
async def test_async_read_nonexistent_file(field_labeled_reader, temp_dir):
    """Test async reading of nonexistent file raises FileNotFoundError."""
    nonexistent_path = temp_dir / "nonexistent.csv"
    with pytest.raises(FileNotFoundError):
        await field_labeled_reader.async_read(nonexistent_path)


def test_custom_delimiter():
    """Test reading CSV with custom delimiter."""
    csv_data = """name;age;city
John;30;New York
Jane;25;San Francisco"""

    reader = FieldLabeledCSVReader()
    file_obj = io.BytesIO(csv_data.encode("utf-8"))
    file_obj.name = "semicolon.csv"

    documents = reader.read(file_obj, delimiter=";")

    assert len(documents) == 2
    expected_content = "Name: John\nAge: 30\nCity: New York"
    assert documents[0].content == expected_content


def test_custom_quotechar():
    """Test reading CSV with custom quote character."""
    csv_data = """name,description,price
'Product A','Description with, comma',19.99
'Product B','Another description',29.99"""

    reader = FieldLabeledCSVReader()
    file_obj = io.BytesIO(csv_data.encode("utf-8"))
    file_obj.name = "quotes.csv"

    documents = reader.read(file_obj, quotechar="'")

    assert len(documents) == 2
    expected_content = "Name: Product A\nDescription: Description with, comma\nPrice: 19.99"
    assert documents[0].content == expected_content


def test_row_length_normalization():
    """Test handling rows with different lengths."""
    csv_data = """name,age,city
John,30,New York
Jane,25
Bob,40,Chicago,Extra"""

    reader = FieldLabeledCSVReader()
    file_obj = io.BytesIO(csv_data.encode("utf-8"))
    file_obj.name = "irregular.csv"

    documents = reader.read(file_obj)

    assert len(documents) == 3

    # Jane has missing city (should be empty)
    expected_content_jane = "Name: Jane\nAge: 25"  # City skipped due to skip_empty_fields
    assert documents[1].content == expected_content_jane

    # Bob has extra field (should be truncated)
    expected_content_bob = "Name: Bob\nAge: 40\nCity: Chicago"
    assert documents[2].content == expected_content_bob


def test_no_title():
    """Test reading without any title."""
    reader = FieldLabeledCSVReader(chunk_title=None)
    file_obj = io.BytesIO(SAMPLE_CSV.encode("utf-8"))
    file_obj.name = "no_title.csv"

    documents = reader.read(file_obj)

    assert len(documents) == 3

    # Should not have title line
    expected_content = "Name: John\nAge: 30\nCity: New York"
    assert documents[0].content == expected_content


def test_format_headers_disabled(underscore_csv_file):
    """Test with header formatting disabled."""
    reader = FieldLabeledCSVReader(format_headers=False)
    documents = reader.read(underscore_csv_file)

    assert len(documents) == 2

    # Headers should remain with underscores
    expected_content = "product_name: Product123\nunit_price: 15.99\nproduct_category: Electronics"
    assert documents[0].content == expected_content


def test_get_supported_content_types():
    """Test supported content types - CSV only (Excel uses ExcelReader)."""
    content_types = FieldLabeledCSVReader.get_supported_content_types()

    from agno.knowledge.types import ContentType

    expected_types = [ContentType.CSV]
    assert content_types == expected_types


def test_metadata_structure(field_labeled_reader, csv_file):
    """Test that metadata contains all expected fields."""
    documents = field_labeled_reader.read(csv_file)

    metadata = documents[0].meta_data

    # Check required metadata fields
    assert "row_index" in metadata
    assert "headers" in metadata
    assert "total_rows" in metadata
    assert "source" in metadata

    assert metadata["row_index"] == 0
    assert metadata["headers"] == ["name", "age", "city"]
    assert metadata["total_rows"] == 3
    assert metadata["source"] == "field_labeled_csv_reader"


def test_document_id_generation(field_labeled_reader, csv_file):
    """Test document ID generation patterns."""
    documents = field_labeled_reader.read(csv_file)

    assert documents[0].id == "test_row_1"
    assert documents[1].id == "test_row_2"
    assert documents[2].id == "test_row_3"


@pytest.mark.asyncio
async def test_async_read_pagination_metadata(field_labeled_reader, large_csv_file):
    """Test that pagination metadata is correct in async mode."""
    documents = await field_labeled_reader.async_read(large_csv_file, page_size=5)

    # Check page metadata for documents from different pages
    page_1_docs = [d for d in documents if d.meta_data.get("page") == 1]
    page_2_docs = [d for d in documents if d.meta_data.get("page") == 2]
    page_3_docs = [d for d in documents if d.meta_data.get("page") == 3]

    assert len(page_1_docs) == 5  # First 5 rows
    assert len(page_2_docs) == 5  # Next 5 rows
    assert len(page_3_docs) == 5  # Last 5 rows

    # Check row indices are correct across pages
    assert page_1_docs[0].meta_data["row_index"] == 0
    assert page_2_docs[0].meta_data["row_index"] == 5
    assert page_3_docs[0].meta_data["row_index"] == 10


def test_encoding_parameter(temp_dir):
    """Test custom encoding support."""
    # Create CSV with non-ASCII characters
    csv_content = """name,description
Café,Très bien
Naïve,Résumé"""

    file_path = temp_dir / "utf8.csv"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(csv_content)

    reader = FieldLabeledCSVReader(encoding="utf-8")
    documents = reader.read(file_path)

    assert len(documents) == 2
    expected_content = "Name: Café\nDescription: Très bien"
    assert documents[0].content == expected_content


def test_get_supported_chunking_strategies():
    """Test that chunking is not supported (each row is already a logical unit)."""
    strategies = FieldLabeledCSVReader.get_supported_chunking_strategies()
    assert strategies == []


def test_reader_factory_integration():
    """Test that the reader is properly integrated with ReaderFactory."""
    from agno.knowledge.reader.reader_factory import ReaderFactory

    # Test that the reader can be created through the factory
    reader = ReaderFactory.create_reader("field_labeled_csv")

    assert isinstance(reader, FieldLabeledCSVReader)
    assert reader.name == "Field Labeled CSV Reader"
    assert "field-labeled text format" in reader.description


LATIN1_CSV = "name,city\nJosé,São Paulo\nFrançois,Montréal"


def test_read_bytesio_with_custom_encoding():
    """Test reading BytesIO with custom encoding (Latin-1)."""
    latin1_bytes = LATIN1_CSV.encode("latin-1")
    file_obj = io.BytesIO(latin1_bytes)
    file_obj.name = "latin1.csv"

    reader = FieldLabeledCSVReader(encoding="latin-1")
    documents = reader.read(file_obj)

    assert len(documents) == 2
    content = documents[0].content

    # Verify accented characters are correctly decoded
    assert "José" in content
    assert "São Paulo" in content


def test_read_bytesio_wrong_encoding_fails():
    """Test that reading Latin-1 bytes as UTF-8 fails or corrupts data.

    This demonstrates why the encoding parameter is important.
    """
    latin1_bytes = LATIN1_CSV.encode("latin-1")
    file_obj = io.BytesIO(latin1_bytes)
    file_obj.name = "latin1.csv"

    reader = FieldLabeledCSVReader()  # Uses UTF-8 by default

    # This should either raise an error or produce corrupted output
    documents = reader.read(file_obj)

    # If it didn't raise, the content should be corrupted (mojibake)
    if documents:
        content = documents[0].content
        # The accented characters should NOT be correctly decoded
        assert "José" not in content or "São Paulo" not in content


@pytest.mark.asyncio
async def test_async_read_bytesio_with_custom_encoding():
    """Test async reading BytesIO with custom encoding (Latin-1)."""
    latin1_bytes = LATIN1_CSV.encode("latin-1")
    file_obj = io.BytesIO(latin1_bytes)
    file_obj.name = "latin1.csv"

    reader = FieldLabeledCSVReader(encoding="latin-1")
    documents = await reader.async_read(file_obj)

    assert len(documents) == 2
    content = documents[0].content
    assert "José" in content
    assert "São Paulo" in content


def test_read_csv_carriage_return_normalized():
    """Test that carriage returns in CSV cells are normalized to spaces."""
    csv_content = 'name,notes\nAlice,"line1\rline2"\nBob,"line1\r\nline2"'

    file_obj = io.BytesIO(csv_content.encode("utf-8"))
    file_obj.name = "cr_test.csv"

    reader = FieldLabeledCSVReader()
    documents = reader.read(file_obj)

    assert len(documents) == 2
    # CR and CRLF should be converted to spaces
    assert documents[0].content == "Name: Alice\nNotes: line1 line2"
    assert documents[1].content == "Name: Bob\nNotes: line1 line2"
