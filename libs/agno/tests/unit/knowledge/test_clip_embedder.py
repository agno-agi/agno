import base64
from io import BytesIO
from pathlib import Path

import pytest

from agno.knowledge.document.base import Document
from agno.knowledge.reader.image_reader import ImageReader


def test_read_image_file_path(tmp_path):
    """Test reading an image file from a Path."""
    image_path = tmp_path / "test.jpg"
    fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    image_path.write_bytes(fake_image)

    reader = ImageReader()
    documents = reader.read(image_path)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].content == base64.b64encode(fake_image).decode("utf-8")
    assert documents[0].meta_data["image_format"] == ".jpg"
    assert documents[0].meta_data["image_size_bytes"] == len(fake_image)
    assert documents[0].meta_data["content_type"] == "image"


def test_read_image_bytesio():
    """Test reading an image from a BytesIO object."""
    fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    image_bytes = BytesIO(fake_image)
    image_bytes.name = "test.png"

    reader = ImageReader()
    documents = reader.read(image_bytes)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].content == base64.b64encode(fake_image).decode("utf-8")
    assert documents[0].meta_data["content_type"] == "image"


def test_no_chunking():
    """Test that images are never chunked."""
    fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 10000
    image_bytes = BytesIO(fake_image)
    image_bytes.name = "large.jpg"

    reader = ImageReader()
    assert reader.chunk is False

    documents = reader.read(image_bytes)
    assert len(documents) == 1


def test_file_not_found():
    """Test reading a nonexistent file returns empty list."""
    reader = ImageReader()
    documents = reader.read(Path("nonexistent.jpg"))
    assert len(documents) == 0


def test_supported_content_types():
    """Test that supported content types include image formats."""
    from agno.knowledge.types import ContentType

    content_types = ImageReader.get_supported_content_types()
    assert ContentType.IMAGE_PNG in content_types
    assert ContentType.IMAGE_JPEG in content_types
    assert ContentType.IMAGE_JPG in content_types


def test_supported_chunking_strategies():
    """Test that no chunking strategies are supported."""
    assert ImageReader.get_supported_chunking_strategies() == []


def test_read_png_file(tmp_path):
    """Test reading a PNG file."""
    image_path = tmp_path / "image.png"
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    image_path.write_bytes(fake_png)

    reader = ImageReader()
    documents = reader.read(image_path)

    assert len(documents) == 1
    assert documents[0].meta_data["image_format"] == ".png"


def test_custom_name(tmp_path):
    """Test passing a custom name."""
    image_path = tmp_path / "photo.jpg"
    fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 50
    image_path.write_bytes(fake_image)

    reader = ImageReader()
    documents = reader.read(image_path, name="my_custom_name")

    assert len(documents) == 1
    assert documents[0].name == "my_custom_name"


@pytest.mark.asyncio
async def test_async_read_image_file(tmp_path):
    """Test async reading of an image file."""
    image_path = tmp_path / "test.jpg"
    fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    image_path.write_bytes(fake_image)

    reader = ImageReader()
    documents = await reader.async_read(image_path)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].content == base64.b64encode(fake_image).decode("utf-8")


@pytest.mark.asyncio
async def test_async_file_not_found():
    """Test async reading of a nonexistent file."""
    reader = ImageReader()
    documents = await reader.async_read(Path("nonexistent.png"))
    assert len(documents) == 0