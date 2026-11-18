import io
import re
import tempfile
from pathlib import Path

import pytest

from agno.knowledge.chunking.row import RowChunking
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


def test_read_str_path(csv_reader, csv_file):
    documents = csv_reader.read(str(csv_file))

    assert len(documents) == 4
    assert documents[0].name == "test"
    assert documents[0].content == "name, age, city"
    assert documents[1].content == "John, 30, New York"
    assert documents[2].content == "Jane, 25, San Francisco"
    assert documents[3].content == "Bob, 40, Chicago"


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


def test_read_nonexistent_str_path(csv_reader, temp_dir):
    nonexistent_path = temp_dir / "nonexistent.csv"
    with pytest.raises(FileNotFoundError, match="Could not find file"):
        csv_reader.read(str(nonexistent_path))


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

    # RowChunking splits newline-joined content into one doc per row
    assert len(documents) == 4
    assert documents[0].name == "test"
    assert documents[0].content == "name, age, city"
    assert documents[1].content == "John, 30, New York"
    assert documents[2].content == "Jane, 25, San Francisco"
    assert documents[3].content == "Bob, 40, Chicago"


@pytest.mark.asyncio
async def test_async_read_str_path(csv_reader, csv_file):
    documents = await csv_reader.async_read(str(csv_file))

    assert len(documents) == 4
    assert documents[0].name == "test"
    assert documents[0].content == "name, age, city"
    assert documents[1].content == "John, 30, New York"
    assert documents[2].content == "Jane, 25, San Francisco"
    assert documents[3].content == "Bob, 40, Chicago"


@pytest.mark.asyncio
async def test_async_read_nonexistent_str_path(csv_reader, temp_dir):
    nonexistent_path = temp_dir / "nonexistent.csv"
    with pytest.raises(FileNotFoundError, match="Could not find file"):
        await csv_reader.async_read(str(nonexistent_path))


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
@pytest.mark.parametrize("page_size", [-1, -10])
@pytest.mark.parametrize("row_count", [0, 3, 12])
@pytest.mark.parametrize("source_type", ["path", "stream"])
async def test_async_read_rejects_negative_page_size(tmp_path, page_size, row_count, source_type):
    content = "name,age\n" + "\n".join(f"row{i},{i}" for i in range(row_count))
    if source_type == "path":
        source = tmp_path / "input.csv"
        source.write_text(content, encoding="utf-8")
    else:
        source = io.BytesIO(content.encode("utf-8"))
        source.seek(3)

    with pytest.raises(ValueError, match=re.escape("page_size cannot be a negative value.")):
        await CSVReader().async_read(source, page_size=page_size)

    if source_type == "stream":
        assert source.tell() == 3
        assert not source.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size", [1, 5, 1000])
async def test_async_read_positive_page_size_preserves_stream_rows(page_size):
    content = "name,age\n" + "\n".join(f"row{i},{i}" for i in range(12))
    source = io.BytesIO(content.encode("utf-8"))

    documents = await CSVReader().async_read(source, page_size=page_size)

    assert [document.content for document in documents] == ["name, age"] + [f"row{i}, {i}" for i in range(12)]
    assert [document.meta_data["row_number"] for document in documents] == list(range(1, 14))


@pytest.mark.asyncio
async def test_async_read_multi_page_csv(csv_reader, multi_page_csv_file):
    documents = await csv_reader.async_read(multi_page_csv_file, page_size=5)

    # RowChunking splits newline-joined content into one doc per row (11 rows total)
    assert len(documents) == 11
    assert documents[0].name == "multi_page"
    assert documents[0].content == "name, age, city"
    assert documents[1].content == "row1, 30, City1"
    assert documents[10].content == "row10, 39, City10"

    # Pagination metadata should still be present on chunked docs from page 1
    assert documents[0].meta_data["page"] == 1
    assert documents[0].meta_data["start_row"] == 1
    assert documents[0].meta_data["rows"] == 5
    # Docs from page 2 (rows 6-10)
    assert documents[5].meta_data["page"] == 2
    assert documents[5].meta_data["start_row"] == 6
    assert documents[5].meta_data["rows"] == 5
    # Doc from page 3 (row 11)
    assert documents[10].meta_data["page"] == 3
    assert documents[10].meta_data["start_row"] == 11
    assert documents[10].meta_data["rows"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("skip_header", [False, True])
@pytest.mark.parametrize("page_size", [1, 5, 1000])
async def test_async_read_multi_page_csv_preserves_rows_and_numbers(multi_page_csv_file, skip_header, page_size):
    reader = CSVReader(chunking_strategy=RowChunking(skip_header=skip_header))

    sync_documents = reader.read(multi_page_csv_file)
    async_documents = await reader.async_read(multi_page_csv_file, page_size=page_size)

    assert [document.content for document in async_documents] == [document.content for document in sync_documents]
    assert [document.meta_data["row_number"] for document in async_documents] == list(
        range(2 if skip_header else 1, 12)
    )


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


def test_default_chunking_strategy_is_not_shared_between_instances():
    """Each CSVReader() created without an explicit chunking_strategy must get
    its own RowChunking instance, not a shared mutable default constructed
    once at import time."""
    reader_a = CSVReader()
    reader_b = CSVReader()

    assert reader_a.chunking_strategy is not reader_b.chunking_strategy

    reader_a.chunking_strategy.skip_header = True

    assert reader_b.chunking_strategy.skip_header is False


# ---------------------------------------------------------------------------
# File-like inputs that are already text
# ---------------------------------------------------------------------------
# Both read paths used to call `.decode()` on whatever `file.read()` returned. For a
# `StringIO`, or a file opened in text mode, that value is already a `str`, so the call
# raised `AttributeError`, the surrounding `except Exception` swallowed it, and the
# reader returned an empty list with no signal to the caller.


def test_read_text_stream(csv_reader):
    """A StringIO must be read like a binary stream rather than silently yield nothing."""
    documents = csv_reader.read(io.StringIO(SAMPLE_CSV))

    # The default fixture chunks by row: header plus the three data rows.
    assert len(documents) == 4
    assert [doc.content for doc in documents] == [
        "name, age, city",
        "John, 30, New York",
        "Jane, 25, San Francisco",
        "Bob, 40, Chicago",
    ]


def test_read_text_stream_unchunked_matches_binary(csv_reader):
    """The same content is produced whether the stream is text or bytes."""
    text_docs = CSVReader(chunk=False).read(io.StringIO(SAMPLE_CSV))
    binary_docs = CSVReader(chunk=False).read(io.BytesIO(SAMPLE_CSV.encode("utf-8")))

    assert len(text_docs) == 1
    assert len(binary_docs) == 1
    assert text_docs[0].content == binary_docs[0].content
    assert "John" in text_docs[0].content
    assert "Chicago" in text_docs[0].content


def test_read_file_opened_in_text_mode(csv_reader, csv_file):
    """A file handle opened with mode="r" already yields str, so it must not be decoded."""
    with open(csv_file, "r", encoding="utf-8", newline="") as handle:
        documents = csv_reader.read(handle)

    assert len(documents) == 4
    assert "John" in documents[1].content


@pytest.fixture(params=["temporary", "spooled"], ids=["temporary-file", "spooled-file"])
def temporary_csv_stream(request):
    if request.param == "temporary":
        stream = tempfile.TemporaryFile(mode="w+b")
    else:
        stream = tempfile.SpooledTemporaryFile(max_size=1024, mode="w+b")

    stream.write(SAMPLE_CSV.encode("utf-8"))
    stream.seek(0)
    yield stream
    stream.close()


def _expected_stream_name(stream):
    return stream.name.split(".")[0] if isinstance(stream.name, str) else "csv_file"


@pytest.mark.parametrize("use_default_chunking", [False, True], ids=["unchunked", "default-chunked"])
def test_read_temporary_stream_with_non_string_name(temporary_csv_stream, use_default_chunking):
    """Temporary streams with an absent or non-string name use a stable fallback."""
    reader = CSVReader() if use_default_chunking else CSVReader(chunk=False)
    documents = reader.read(temporary_csv_stream)

    expected_contents = SAMPLE_CSV.replace(",", ", ").splitlines()
    assert [document.name for document in documents] == [_expected_stream_name(temporary_csv_stream)] * len(
        expected_contents if use_default_chunking else [SAMPLE_CSV]
    )
    assert [document.content for document in documents] == (
        expected_contents if use_default_chunking else [SAMPLE_CSV.replace(",", ", ")]
    )
    assert not temporary_csv_stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("use_default_chunking", [False, True], ids=["unchunked", "default-chunked"])
async def test_async_read_temporary_stream_with_non_string_name(temporary_csv_stream, use_default_chunking):
    """The async reader handles the same real temporary stream variants."""
    reader = CSVReader() if use_default_chunking else CSVReader(chunk=False)
    documents = await reader.async_read(temporary_csv_stream)

    expected_contents = SAMPLE_CSV.replace(",", ", ").splitlines()
    assert [document.name for document in documents] == [_expected_stream_name(temporary_csv_stream)] * len(
        expected_contents if use_default_chunking else [SAMPLE_CSV]
    )
    assert [document.content for document in documents] == (
        expected_contents if use_default_chunking else [SAMPLE_CSV.replace(",", ", ")]
    )
    assert not temporary_csv_stream.closed


def test_read_non_string_stream_name_allows_name_override():
    stream = io.BytesIO(SAMPLE_CSV.encode("utf-8"))
    stream.name = 12345

    documents = CSVReader(chunk=False).read(stream)
    assert documents[0].name == "csv_file"

    stream.seek(0)
    overridden_documents = CSVReader(chunk=False).read(stream, name="people")
    assert overridden_documents[0].name == "people"
    assert not stream.closed


@pytest.mark.asyncio
async def test_async_read_non_string_stream_name_allows_name_override():
    stream = io.BytesIO(SAMPLE_CSV.encode("utf-8"))
    stream.name = 12345

    documents = await CSVReader(chunk=False).async_read(stream)
    assert documents[0].name == "csv_file"

    stream.seek(0)
    overridden_documents = await CSVReader(chunk=False).async_read(stream, name="people")
    assert overridden_documents[0].name == "people"
    assert not stream.closed


@pytest.mark.asyncio
async def test_async_read_named_stream_uses_name_stem():
    stream = io.BytesIO(SAMPLE_CSV.encode("utf-8"))
    stream.name = "people.csv"

    documents = await CSVReader(chunk=False).async_read(stream)

    assert len(documents) == 1
    assert documents[0].name == "people"
    assert not stream.closed


def test_read_text_stream_honours_encoding():
    """A non-utf-8 byte stream is still decoded with the reader's encoding."""
    documents = CSVReader(chunk=False, encoding="latin-1").read(
        io.BytesIO("name,city\nAndré,München".encode("latin-1"))
    )

    assert len(documents) == 1
    assert "André" in documents[0].content
    assert "München" in documents[0].content


@pytest.mark.asyncio
async def test_async_read_text_stream(csv_reader):
    """The async path has the same contract for text streams."""
    documents = await csv_reader.async_read(io.StringIO(SAMPLE_CSV))

    assert len(documents) == 4
    assert "John" in documents[1].content


@pytest.mark.asyncio
async def test_async_read_text_stream_unchunked_matches_binary():
    text_docs = await CSVReader(chunk=False).async_read(io.StringIO(SAMPLE_CSV))
    binary_docs = await CSVReader(chunk=False).async_read(io.BytesIO(SAMPLE_CSV.encode("utf-8")))

    assert len(text_docs) == 1
    assert len(binary_docs) == 1
    assert text_docs[0].content == binary_docs[0].content
    assert "John" in text_docs[0].content
