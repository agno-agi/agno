import asyncio
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agno.knowledge.document.base import Document
from agno.knowledge.reader.pptx_reader import PPTXReader


@pytest.fixture
def mock_pptx():
    """Mock a PPTX presentation with some slides and shapes"""
    # Create mock shapes with text
    mock_shape1 = Mock()
    mock_shape1.text = "First slide content"
    mock_shape2 = Mock()
    mock_shape2.text = "Second slide content"

    # Create mock slides
    mock_slide1 = Mock()
    mock_slide1.shapes = [mock_shape1]

    mock_slide2 = Mock()
    mock_slide2.shapes = [mock_shape2]

    # Create mock presentation
    mock_presentation = Mock()
    mock_presentation.slides = [mock_slide1, mock_slide2]

    return mock_presentation


def test_pptx_reader_read_file(mock_pptx):
    """Test reading a PPTX file"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.pptx_reader.Presentation", return_value=mock_pptx),
    ):
        reader = PPTXReader()
        documents = reader.read(Path("test.pptx"))

        assert len(documents) == 1
        assert documents[0].name == "test"
        expected_content = "Slide 1:\nFirst slide content\n\nSlide 2:\nSecond slide content"
        assert documents[0].content == expected_content


@pytest.mark.asyncio
async def test_pptx_reader_async_read_file(mock_pptx):
    """Test reading a PPTX file asynchronously"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.pptx_reader.Presentation", return_value=mock_pptx),
    ):
        reader = PPTXReader()
        documents = await reader.async_read(Path("test.pptx"))

        assert len(documents) == 1
        assert documents[0].name == "test"
        expected_content = "Slide 1:\nFirst slide content\n\nSlide 2:\nSecond slide content"
        assert documents[0].content == expected_content


def test_pptx_reader_with_chunking():
    """Test reading a PPTX file with chunking enabled"""
    # Create mock presentation with one slide
    mock_shape = Mock()
    mock_shape.text = "Test content"
    mock_slide = Mock()
    mock_slide.shapes = [mock_shape]
    mock_presentation = Mock()
    mock_presentation.slides = [mock_slide]

    chunked_docs = [
        Document(name="test", id="test_1", content="Chunk 1"),
        Document(name="test", id="test_2", content="Chunk 2"),
    ]

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.pptx_reader.Presentation", return_value=mock_presentation),
    ):
        reader = PPTXReader()
        reader.chunk = True
        reader.chunk_document = Mock(return_value=chunked_docs)

        documents = reader.read(Path("test.pptx"))

        reader.chunk_document.assert_called_once()
        assert len(documents) == 2
        assert documents[0].content == "Chunk 1"
        assert documents[1].content == "Chunk 2"


def test_pptx_reader_bytesio(mock_pptx):
    """Test reading a PPTX from BytesIO"""
    file_obj = BytesIO(b"dummy content")
    file_obj.name = "test.pptx"

    with patch("agno.knowledge.reader.pptx_reader.Presentation", return_value=mock_pptx):
        reader = PPTXReader()
        documents = reader.read(file_obj)

        assert len(documents) == 1
        assert documents[0].name == "test"
        expected_content = "Slide 1:\nFirst slide content\n\nSlide 2:\nSecond slide content"
        assert documents[0].content == expected_content


def test_pptx_reader_invalid_file():
    """Test reading an invalid file"""
    with patch("pathlib.Path.exists", return_value=False):
        reader = PPTXReader()
        documents = reader.read(Path("nonexistent.pptx"))
        assert len(documents) == 0


def test_pptx_reader_file_error():
    """Test handling of file reading errors"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.pptx_reader.Presentation", side_effect=Exception("File error")),
    ):
        reader = PPTXReader()
        documents = reader.read(Path("test.pptx"))
        assert len(documents) == 0


@pytest.mark.asyncio
async def test_async_pptx_processing(mock_pptx):
    """Test concurrent async processing"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.pptx_reader.Presentation", return_value=mock_pptx),
    ):
        reader = PPTXReader()
        tasks = [reader.async_read(Path("test.pptx")) for _ in range(3)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 3
        assert all(len(docs) == 1 for docs in results)
        assert all(docs[0].name == "test" for docs in results)
        expected_content = "Slide 1:\nFirst slide content\n\nSlide 2:\nSecond slide content"
        assert all(docs[0].content == expected_content for docs in results)


@pytest.mark.asyncio
async def test_pptx_reader_async_with_chunking():
    """Test async reading with chunking enabled"""
    # Create mock presentation with one slide
    mock_shape = Mock()
    mock_shape.text = "Test content"
    mock_slide = Mock()
    mock_slide.shapes = [mock_shape]
    mock_presentation = Mock()
    mock_presentation.slides = [mock_slide]

    # Create a chunked document
    chunked_docs = [
        Document(name="test", id="test_1", content="Chunk 1"),
        Document(name="test", id="test_2", content="Chunk 2"),
    ]

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.pptx_reader.Presentation", return_value=mock_presentation),
    ):
        reader = PPTXReader()
        reader.chunk = True
        # Mock the chunk_document method to return our predefined chunks
        reader.chunk_document = Mock(return_value=chunked_docs)

        documents = await reader.async_read(Path("test.pptx"))

        reader.chunk_document.assert_called_once()
        assert len(documents) == 2
        assert documents[0].content == "Chunk 1"
        assert documents[1].content == "Chunk 2"


def test_pptx_reader_metadata(mock_pptx):
    """Test document metadata"""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.pptx_reader.Presentation", return_value=mock_pptx),
    ):
        reader = PPTXReader()
        documents = reader.read(Path("test_doc.pptx"))

        assert len(documents) == 1
        assert documents[0].name == "test_doc"
        expected_content = "Slide 1:\nFirst slide content\n\nSlide 2:\nSecond slide content"
        assert documents[0].content == expected_content


def test_pptx_reader_empty_slides():
    """Test reading PPTX with slides that have no text content"""
    # Create mock shapes with no text (empty strings)
    mock_shape1 = Mock()
    mock_shape1.text = ""
    mock_shape2 = Mock()
    mock_shape2.text = "   "  # whitespace only

    # Create mock slides
    mock_slide1 = Mock()
    mock_slide1.shapes = [mock_shape1]
    mock_slide2 = Mock()
    mock_slide2.shapes = [mock_shape2]

    # Create mock presentation
    mock_presentation = Mock()
    mock_presentation.slides = [mock_slide1, mock_slide2]

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.pptx_reader.Presentation", return_value=mock_presentation),
    ):
        reader = PPTXReader()
        documents = reader.read(Path("empty.pptx"))

        assert len(documents) == 1
        expected_content = "Slide 1:\n(No text content)\n\nSlide 2:\n(No text content)"
        assert documents[0].content == expected_content


def test_pptx_reader_shapes_without_text():
    """Test reading PPTX with shapes that don't have text attribute"""
    # Create mock shapes without text attribute (like images, charts, etc.)
    mock_shape1 = Mock()
    del mock_shape1.text  # Remove text attribute
    mock_shape2 = Mock()
    mock_shape2.text = "Valid text"

    # Create mock slides
    mock_slide1 = Mock()
    mock_slide1.shapes = [mock_shape1, mock_shape2]

    # Create mock presentation
    mock_presentation = Mock()
    mock_presentation.slides = [mock_slide1]

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("agno.knowledge.reader.pptx_reader.Presentation", return_value=mock_presentation),
    ):
        reader = PPTXReader()
        documents = reader.read(Path("mixed.pptx"))

        assert len(documents) == 1
        expected_content = "Slide 1:\nValid text"
        assert documents[0].content == expected_content
