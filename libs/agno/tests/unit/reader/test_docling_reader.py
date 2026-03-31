import asyncio
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agno.knowledge.document.base import Document
from agno.knowledge.reader.docling_reader import DoclingReader


@pytest.fixture
def mock_docling_result():
    """Mock a Docling conversion result"""
    mock_document = Mock()
    mock_document.export_to_markdown.return_value = "# Test Document\n\nThis is a test document."
    mock_document.export_to_text.return_value = "Test Document\n\nThis is a test document."
    mock_document.export_to_dict.return_value = {"content": "Test Document"}
    mock_document.export_to_html.return_value = "<html><body>Test Document</body></html>"
    mock_document.export_to_doctags.return_value = "<doctags>Test Document</doctags>"
    mock_document.export_to_vtt.return_value = "WEBVTT\n\nTest Document"

    mock_result = Mock()
    mock_result.document = mock_document
    return mock_result


@pytest.fixture
def mock_converter(mock_docling_result):
    """Mock a DocumentConverter"""
    mock_conv = Mock()
    mock_conv.convert.return_value = mock_docling_result
    return mock_conv


def test_read_file(mock_converter):
    """Test reading a file with DoclingReader"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader()
        documents = reader.read(Path("test.pdf"))

        assert len(documents) == 1
        assert documents[0].name == "test"
        assert "Test Document" in documents[0].content
        mock_converter.convert.assert_called_once()


def test_markdown_output(mock_converter):
    """Test markdown output format"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader(output_format="markdown")
        documents = reader.read(Path("test.pdf"))

        assert len(documents) == 1
        assert "# Test Document" in documents[0].content


def test_text_output(mock_converter, mock_docling_result):
    """Test text output format"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader(output_format="text")
        documents = reader.read(Path("test.pdf"))

        assert len(documents) == 1
        mock_docling_result.document.export_to_text.assert_called_once()


def test_json_output(mock_converter, mock_docling_result):
    """Test JSON output format"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader(output_format="json")
        documents = reader.read(Path("test.pdf"))

        assert len(documents) == 1
        mock_docling_result.document.export_to_dict.assert_called_once()
        assert '{"content": "Test Document"}' in documents[0].content


def test_vtt_output(mock_converter, mock_docling_result):
    """Test VTT output format"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader(output_format="vtt")
        documents = reader.read(Path("test.pdf"))

        assert len(documents) == 1
        assert "WEBVTT" in documents[0].content


def test_html_output(mock_converter, mock_docling_result):
    """Test HTML output format"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader(output_format="html")
        documents = reader.read(Path("test.pdf"))

        assert len(documents) == 1
        mock_docling_result.document.export_to_html.assert_called_once()
        assert "<html>" in documents[0].content


def test_doctags_output(mock_converter, mock_docling_result):
    """Test Doctags output format"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader(output_format="doctags")
        documents = reader.read(Path("test.pdf"))

        assert len(documents) == 1
        mock_docling_result.document.export_to_doctags.assert_called_once()
        assert "<doctags>" in documents[0].content


@pytest.mark.asyncio
async def test_async_read(mock_converter):
    """Test async reading with DoclingReader"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader()
        documents = await reader.async_read(Path("test.pdf"))

        assert len(documents) == 1
        assert documents[0].name == "test"
        mock_converter.convert.assert_called_once()


def test_reader_with_chunking(mock_converter):
    """Test reading with chunking enabled"""
    chunked_docs = [
        Document(name="test", id="test_1", content="Chunk 1"),
        Document(name="test", id="test_2", content="Chunk 2"),
    ]

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader()
        reader.chunk = True
        reader.chunk_document = Mock(return_value=chunked_docs)

        documents = reader.read(Path("test.pdf"))

        reader.chunk_document.assert_called_once()
        assert len(documents) == 2
        assert documents[0].content == "Chunk 1"
        assert documents[1].content == "Chunk 2"


def test_reading_from_bytesio(mock_converter):
    """Test reading from BytesIO"""
    file_obj = BytesIO(b"test content@123")
    file_obj.name = "test.pdf"

    with patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter):
        reader = DoclingReader()
        documents = reader.read(file_obj)

        assert len(documents) == 1
        assert documents[0].name == "test"
        assert "# Test Document" in documents[0].content


def test_invalid_file():
    """Test reading a non-existent file"""
    with patch("pathlib.Path.exists", return_value=False):
        reader = DoclingReader()
        with pytest.raises(FileNotFoundError, match="Could not find file: nonexistent.pdf"):
            reader.read(Path("nonexistent.pdf"))


def test_conversion_error(mock_converter):
    """Test handling of conversion errors"""
    mock_converter.convert.side_effect = Exception("Conversion error")

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader()
        documents = reader.read(Path("test.pdf"))
        assert len(documents) == 0


@pytest.mark.asyncio
async def test_async_reader_processing(mock_converter):
    """Test concurrent async processing"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader()
        tasks = [reader.async_read(Path("test.pdf")) for _ in range(3)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 3
        assert all(len(docs) == 1 for docs in results)
        assert all(docs[0].name == "test" for docs in results)


@pytest.mark.asyncio
async def test_async_with_chunking(mock_converter):
    """Test async reading with chunking enabled"""
    chunked_docs = [
        Document(name="test", id="test_1", content="Chunk 1"),
        Document(name="test", id="test_2", content="Chunk 2"),
    ]

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader()
        reader.chunk = True
        reader.chunk_document = Mock(return_value=chunked_docs)

        documents = await reader.async_read(Path("test.pdf"))

        reader.chunk_document.assert_called_once()
        assert len(documents) == 2
        assert documents[0].content == "Chunk 1"
        assert documents[1].content == "Chunk 2"


def test_custom_name(mock_converter):
    """Test providing a custom document name"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader()
        documents = reader.read(Path("test.pdf"), name="custom_name")

        assert len(documents) == 1
        assert documents[0].name == "custom_name"


def test_input_url_http(mock_converter):
    """Test reading from HTTP URL"""
    with patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter):
        reader = DoclingReader()
        documents = reader.read("http://example.com/document.pdf")

        assert len(documents) == 1
        assert documents[0].name == "document"


def test_input_url_https(mock_converter):
    """Test reading from HTTPS URL"""
    with patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter):
        reader = DoclingReader()
        documents = reader.read("https://example.com/research/paper.pdf")

        assert len(documents) == 1
        assert documents[0].name == "paper"


def test_input_url_with_query_params(mock_converter):
    """Test reading from URL with query parameters"""
    with patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter):
        reader = DoclingReader()
        documents = reader.read("https://example.com/doc.pdf?token=abc123&version=2")

        assert len(documents) == 1
        assert documents[0].name == "doc"


def test_url_custom_name(mock_converter):
    """Test reading from URL with custom name"""
    with patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter):
        reader = DoclingReader()
        documents = reader.read("https://example.com/document.pdf", name="custom_name")

        assert len(documents) == 1
        assert documents[0].name == "custom_name"


def test_url_without_extension(mock_converter):
    """Test reading from URL without file extension"""
    with patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter):
        reader = DoclingReader()
        documents = reader.read("https://arxiv.org/pdf/2408.09869")

        assert len(documents) == 1
        assert documents[0].name == "2408"


@pytest.mark.asyncio
async def test_async_url(mock_converter):
    """Test async reading from URL"""
    with patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter):
        reader = DoclingReader()
        documents = await reader.async_read("https://example.com/document.pdf")

        assert len(documents) == 1
        assert documents[0].name == "document"


def test_default_output_format(mock_converter):
    """Test that default output format is markdown"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.docling_reader.DocumentConverter", return_value=mock_converter),
    ):
        reader = DoclingReader()
        documents = reader.read(Path("test.pdf"))

        assert len(documents) == 1
        assert "# Test Document" in documents[0].content


def test_unknown_output_format_raises_value_error():
    """Test that unknown output format raises ValueError"""
    with pytest.raises(ValueError, match="Invalid output format: 'random_format'"):
        DoclingReader(output_format="random_format")


def test_docling_reader_chunk_size_propagation():
    """Test that chunk_size is propagated to default chunking strategy"""
    from agno.knowledge.chunking.document import DocumentChunking

    reader = DoclingReader(chunk_size=800)
    assert reader.chunk_size == 800
    assert reader.chunking_strategy.chunk_size == 800
    assert isinstance(reader.chunking_strategy, DocumentChunking)


def test_docling_reader_default_chunk_size():
    """Test default chunk_size is 5000"""
    from agno.knowledge.chunking.document import DocumentChunking

    reader = DoclingReader()
    assert reader.chunk_size == 5000
    assert reader.chunking_strategy.chunk_size == 5000
    assert isinstance(reader.chunking_strategy, DocumentChunking)
