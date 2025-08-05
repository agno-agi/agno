import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import tempfile
import os

from agno.document.reader.universal_reader import UniversalDocumentReader
from agno.document.base import Document


class TestUniversalDocumentReader:
    def setup_method(self):
        """Setup test environment"""
        self.reader = UniversalDocumentReader()

    def test_init(self):
        """Test reader initialization"""
        assert isinstance(self.reader, UniversalDocumentReader)
        assert hasattr(self.reader, "available_readers")

    def test_dependency_check_no_deps(self):
        """Test dependency checking when no dependencies are available"""
        with patch.dict("sys.modules", {"pypdf": None, "fitz": None, "docx": None, "pytesseract": None, "PIL": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                reader = UniversalDocumentReader()
                assert reader.available_readers == {}

    @patch("builtins.__import__")
    def test_dependency_check_with_pypdf(self, mock_import):
        """Test dependency checking when pypdf is available"""

        def mock_import_func(name, *args, **kwargs):
            if name == "pypdf":
                return MagicMock()
            else:
                raise ImportError()

        mock_import.side_effect = mock_import_func
        reader = UniversalDocumentReader()
        assert "pdf" in reader.available_readers
        assert reader.available_readers["pdf"] == "pypdf"

    def test_read_nonexistent_file(self):
        """Test reading a file that doesn't exist"""
        result = self.reader.read("/nonexistent/file.pdf")
        assert result == []

    def test_read_text_file(self):
        """Test reading a plain text file"""
        test_content = "This is a test file content"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as temp_file:
            temp_file.write(test_content)
            temp_file_path = temp_file.name

        try:
            result = self.reader.read(temp_file_path)
            assert len(result) == 1
            assert isinstance(result[0], Document)
            assert result[0].content == test_content
            assert result[0].meta_data["format"] == "text"
        finally:
            os.unlink(temp_file_path)

    @patch("agno.document.reader.universal_reader.UniversalDocumentReader._read_pdf")
    def test_read_pdf_file(self, mock_read_pdf):
        """Test reading a PDF file"""
        mock_doc = Document(name="test", id="test-id", content="PDF content")
        mock_read_pdf.return_value = [mock_doc]

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            temp_file_path = temp_file.name

        try:
            result = self.reader.read(temp_file_path)
            assert len(result) == 1
            assert result[0] == mock_doc
            mock_read_pdf.assert_called_once()
        finally:
            os.unlink(temp_file_path)

    def test_read_pdf_no_reader_available(self):
        """Test reading PDF when no PDF reader is available"""
        self.reader.available_readers = {}

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            temp_file_path = temp_file.name

        try:
            result = self.reader._read_pdf(Path(temp_file_path))
            assert result == []
        finally:
            os.unlink(temp_file_path)

    @patch("pypdf.PdfReader")
    def test_read_pdf_with_pypdf(self, mock_pdf_reader):
        """Test reading PDF with pypdf"""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Test PDF content"

        mock_reader_instance = MagicMock()
        mock_reader_instance.pages = [mock_page]
        mock_pdf_reader.return_value = mock_reader_instance

        self.reader.available_readers = {"pdf": "pypdf"}

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            temp_file_path = temp_file.name

        try:
            result = self.reader._read_pdf(Path(temp_file_path))
            assert len(result) == 1
            assert result[0].content == "Test PDF content\n"
        finally:
            os.unlink(temp_file_path)

    def test_read_docx_no_reader_available(self):
        """Test reading DOCX when python-docx is not available"""
        self.reader.available_readers = {}

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp_file:
            temp_file_path = temp_file.name

        try:
            result = self.reader._read_docx(Path(temp_file_path))
            assert result == []
        finally:
            os.unlink(temp_file_path)

    def test_read_rtf_without_striprtf(self):
        """Test reading RTF file without striprtf library"""
        rtf_content = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Times New Roman;}}Hello World!}"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".rtf", delete=False) as temp_file:
            temp_file.write(rtf_content)
            temp_file_path = temp_file.name

        try:
            with patch("builtins.__import__", side_effect=ImportError):
                result = self.reader._read_rtf(Path(temp_file_path))
                assert len(result) == 1
                assert "Hello World!" in result[0].content
        finally:
            os.unlink(temp_file_path)

    def test_read_image_ocr_no_deps(self):
        """Test reading image when OCR dependencies are not available"""
        self.reader.available_readers = {}

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            temp_file_path = temp_file.name

        try:
            result = self.reader._read_image_ocr(Path(temp_file_path))
            assert result == []
        finally:
            os.unlink(temp_file_path)

    def test_read_fallback(self):
        """Test fallback reader for unknown file types"""
        test_content = "Unknown file content"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".unknown", delete=False) as temp_file:
            temp_file.write(test_content)
            temp_file_path = temp_file.name

        try:
            result = self.reader._read_fallback(Path(temp_file_path))
            assert len(result) == 1
            assert result[0].content == test_content
            assert result[0].meta_data["format"] == "unknown"
        finally:
            os.unlink(temp_file_path)

    def test_read_binary_fallback(self):
        """Test fallback reader with binary content"""
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as temp_file:
            temp_file.write(b"Binary content")
            temp_file_path = temp_file.name

        try:
            with patch(
                "builtins.open",
                side_effect=[
                    FileNotFoundError(),  # First attempt fails
                    mock_open(read_data=b"Binary content")(),  # Second attempt succeeds
                ],
            ):
                result = self.reader._read_fallback(Path(temp_file_path))
                assert len(result) == 1
        finally:
            os.unlink(temp_file_path)

    def test_chunking_enabled(self):
        """Test document chunking when enabled"""
        self.reader.chunk = True
        mock_chunked_doc = Document(name="chunk1", id="chunk1", content="chunk content")

        with patch.object(self.reader, "chunk_document", return_value=[mock_chunked_doc]):
            test_content = "This is a test file for chunking"

            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as temp_file:
                temp_file.write(test_content)
                temp_file_path = temp_file.name

            try:
                result = self.reader.read(temp_file_path)
                assert len(result) == 1
                assert result[0] == mock_chunked_doc
            finally:
                os.unlink(temp_file_path)

    @pytest.mark.asyncio
    async def test_async_read(self):
        """Test asynchronous reading"""
        test_content = "Async test content"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as temp_file:
            temp_file.write(test_content)
            temp_file_path = temp_file.name

        try:
            result = await self.reader.async_read(temp_file_path)
            assert len(result) == 1
            assert result[0].content == test_content
        finally:
            os.unlink(temp_file_path)

    def test_error_handling(self):
        """Test error handling for various failure scenarios"""
        with patch("builtins.open", side_effect=PermissionError("Access denied")):
            result = self.reader.read("test.txt")
            assert result == []

    def test_file_extension_matching(self):
        """Test that file extensions are properly matched to readers"""
        test_cases = [
            (".pdf", "_read_pdf"),
            (".docx", "_read_docx"),
            (".doc", "_read_docx"),
            (".txt", "_read_text"),
            (".text", "_read_text"),
            (".rtf", "_read_rtf"),
            (".png", "_read_image_ocr"),
            (".jpg", "_read_image_ocr"),
            (".jpeg", "_read_image_ocr"),
            (".tiff", "_read_image_ocr"),
            (".bmp", "_read_image_ocr"),
            (".unknown", "_read_fallback"),
        ]

        for extension, expected_method in test_cases:
            with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temp_file:
                temp_file_path = temp_file.name

            try:
                with patch.object(self.reader, expected_method, return_value=[]) as mock_method:
                    self.reader.read(temp_file_path)
                    mock_method.assert_called_once()
            finally:
                os.unlink(temp_file_path)
