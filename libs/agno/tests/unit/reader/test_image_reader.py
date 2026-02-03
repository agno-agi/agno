import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image as PillowImage

from agno.knowledge.reader.image_reader import ImageProcessingMode, ImageReader


class MockModelResponse:
    def __init__(self, content: str):
        self.content = content


class MockVisionModel:
    """A mock model that simulates sync and async responses."""

    def __init__(self, response_text: str = "A detailed description of the image."):
        self.response_text = response_text
        self.response = MagicMock(return_value=MockModelResponse(response_text))
        self.aresponse = AsyncMock(return_value=MockModelResponse(response_text))


# =================================================================
# ==                         PYTEST FIXTURES                       ==
# =================================================================


@pytest.fixture
def mock_rapidocr(mocker):
    """Mocks the RapidOCR engine."""
    mock_engine_instance = MagicMock()
    # Simulate a successful OCR result
    mock_engine_instance.return_value = ([(None, "Hello", 1.0), (None, "World", 1.0)], 0.1)

    # Patch the class so that when ImageReader calls rapidocr.RapidOCR(),
    # it gets our mock instance.
    return mocker.patch("agno.knowledge.reader.image_reader.rapidocr.RapidOCR", return_value=mock_engine_instance)


@pytest.fixture
def mock_vision_model():
    """Provides a mock vision model instance."""
    return MockVisionModel(response_text="A vibrant sunset over a calm sea.")


@pytest.fixture
def sample_image_path(tmp_path):
    """Creates a temporary dummy image file and returns its path."""
    path = tmp_path / "test.png"
    img = PillowImage.new("RGB", (100, 50), color="red")
    img.save(path)
    return path


@pytest.fixture
def sample_image_io(sample_image_path):
    """Creates an in-memory BytesIO stream of a dummy image."""
    with open(sample_image_path, "rb") as f:
        return io.BytesIO(f.read())


# =================================================================
# ==                        INITIALIZATION TESTS                   ==
# =================================================================


class TestImageReaderInitialization:
    def test_init_ocr_mode(self, mock_rapidocr):
        """Tests successful initialization in OCR mode."""
        reader = ImageReader(mode=ImageProcessingMode.OCR)
        assert reader.mode == ImageProcessingMode.OCR
        assert reader.ocr_engine is not None
        mock_rapidocr.assert_called_once()

    def test_init_vision_mode(self, mock_vision_model):
        """Tests successful initialization in VISION mode."""
        reader = ImageReader(mode=ImageProcessingMode.VISION, vision_model=mock_vision_model)
        assert reader.mode == ImageProcessingMode.VISION
        assert reader.vision_model is not None

    def test_init_vision_mode_no_model_raises_error(self):
        """Tests that ValueError is raised if no model is provided for VISION mode."""
        with pytest.raises(ValueError, match="A 'vision_model' instance is required for VISION mode."):
            ImageReader(mode=ImageProcessingMode.VISION)


# =================================================================
# ==                   SYNCHRONOUS (`read`) TESTS                  ==
# =================================================================


class TestImageReaderSync:
    def test_read_ocr_from_path(self, mock_rapidocr, sample_image_path):
        """Tests synchronous OCR reading from a file path."""
        reader = ImageReader(mode=ImageProcessingMode.OCR)
        documents = reader.read(sample_image_path)

        assert len(documents) == 1
        assert documents[0].content == "Hello World"
        assert documents[0].meta_data["source_file"] == str(sample_image_path)

    def test_read_ocr_from_io(self, mock_rapidocr, sample_image_io):
        """Tests synchronous OCR reading from a file-like object."""
        reader = ImageReader(mode=ImageProcessingMode.OCR)
        documents = reader.read(sample_image_io, name="test_io_file.png")

        assert len(documents) == 1
        assert documents[0].content == "Hello World"
        assert documents[0].name == "test_io_file.png"

    def test_read_vision_from_path(self, mock_vision_model, sample_image_path):
        """Tests synchronous VISION reading from a file path."""
        reader = ImageReader(mode=ImageProcessingMode.VISION, vision_model=mock_vision_model)
        documents = reader.read(sample_image_path)

        assert len(documents) == 1
        assert documents[0].content == "A vibrant sunset over a calm sea."
        mock_vision_model.response.assert_called_once()

    def test_read_ocr_no_text_found(self, mock_rapidocr, sample_image_path):
        """Failure Test: Asserts an empty list is returned if OCR finds no text."""
        # Configure mock to return empty result
        mock_rapidocr.return_value.return_value = ([], 0.0)
        reader = ImageReader(mode=ImageProcessingMode.OCR)
        documents = reader.read(sample_image_path)
        assert documents == []

    def test_read_file_not_found(self, mock_rapidocr):
        """Failure Test: Asserts an empty list is returned for a non-existent file."""
        reader = ImageReader(mode=ImageProcessingMode.OCR)
        documents = reader.read("non_existent_file.png")
        assert documents == []


# =================================================================
# ==                 ASYNCHRONOUS (`async_read`) TESTS             ==
# =================================================================


@pytest.mark.asyncio
class TestImageReaderAsync:
    async def test_async_read_ocr_from_path(self, mock_rapidocr, sample_image_path):
        """Tests asynchronous OCR reading from a file path."""
        reader = ImageReader(mode=ImageProcessingMode.OCR)
        documents = await reader.async_read(sample_image_path)

        assert len(documents) == 1
        assert documents[0].content == "Hello World"
        assert documents[0].meta_data["source_file"] == str(sample_image_path)

    async def test_async_read_ocr_from_io(self, mock_rapidocr, sample_image_io):
        """Tests asynchronous OCR reading from a file-like object."""
        reader = ImageReader(mode=ImageProcessingMode.OCR)
        documents = await reader.async_read(sample_image_io, name="test_io_file.png")

        assert len(documents) == 1
        assert documents[0].content == "Hello World"

    async def test_async_read_vision_from_path(self, mock_vision_model, sample_image_path):
        """Tests asynchronous VISION reading from a file path."""
        reader = ImageReader(mode=ImageProcessingMode.VISION, vision_model=mock_vision_model)
        documents = await reader.async_read(sample_image_path)

        assert len(documents) == 1
        assert documents[0].content == "A vibrant sunset over a calm sea."
        mock_vision_model.aresponse.assert_called_once()

    async def test_async_read_vision_no_description(self, mock_vision_model, sample_image_path):
        """Failure Test: Asserts an empty list is returned if the vision model provides no content."""
        mock_vision_model.aresponse.return_value = MockModelResponse(content="")
        reader = ImageReader(mode=ImageProcessingMode.VISION, vision_model=mock_vision_model)
        documents = await reader.async_read(sample_image_path)
        assert documents == []

    async def test_async_read_file_not_found(self, mock_rapidocr):
        """Failure Test: Asserts an empty list is returned for a non-existent file in async mode."""
        reader = ImageReader(mode=ImageProcessingMode.OCR)
        documents = await reader.async_read("non_existent_file.png")
        assert documents == []
