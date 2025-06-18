"""
Unit tests for playground file upload functionality.
"""

import io
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.media import File as FileMedia
from agno.media import Image
from agno.models.openai import OpenAIChat
from agno.playground import Playground
from agno.run.response import RunResponse

# --- Fixtures ---


@pytest.fixture
def mock_document_readers():
    """Mock all document readers to avoid actual document parsing."""
    with (
        patch("agno.document.reader.pdf_reader.PDFReader") as mock_pdf,
        patch("agno.document.reader.csv_reader.CSVReader") as mock_csv,
        patch("agno.document.reader.docx_reader.DocxReader") as mock_docx,
        patch("agno.document.reader.text_reader.TextReader") as mock_text,
        patch("agno.document.reader.json_reader.JSONReader") as mock_json,
    ):
        # Configure all mocks to return some dummy text content
        mock_pdf.return_value.read.return_value = ["This is mock PDF content"]
        mock_csv.return_value.read.return_value = ["This is mock CSV content"]
        mock_docx.return_value.read.return_value = ["This is mock DOCX content"]
        mock_text.return_value.read.return_value = ["This is mock TEXT content"]
        mock_json.return_value.read.return_value = ["This is mock JSON content"]

        yield {"pdf": mock_pdf, "csv": mock_csv, "docx": mock_docx, "text": mock_text, "json": mock_json}


@pytest.fixture
def mock_agent():
    """Creates a mock agent with knowledge base disabled."""
    agent = Agent(
        name="Test Agent",
        agent_id="test-agent",
        model=OpenAIChat(id="gpt-4o-mini"),
    )
    # Create mock run method
    mock_run = Mock(return_value=RunResponse(content="Mocked response"))
    agent.run = mock_run

    return agent


@pytest.fixture
def mock_agent_with_knowledge():
    """Creates a mock agent with knowledge base enabled."""
    agent = Agent(
        name="Test Agent",
        agent_id="test-agent",
        model=OpenAIChat(id="gpt-4o"),
    )

    # Create mock run method
    mock_run = Mock(return_value=RunResponse(content="Mocked response"))
    agent.run = mock_run

    # Add knowledge base mock
    agent.knowledge = Mock()
    agent.knowledge.load_documents = Mock()

    return agent


@pytest.fixture
def test_app(mock_agent):
    """Creates a TestClient with our playground router."""
    app = Playground(agents=[mock_agent]).get_app(use_async=False)
    return TestClient(app)


@pytest.fixture
def test_app_with_knowledge(mock_agent_with_knowledge):
    """Creates a TestClient with our playground router using agent with knowledge."""
    app = Playground(agents=[mock_agent_with_knowledge]).get_app(use_async=False)
    return TestClient(app)


@pytest.fixture
def mock_image_file():
    """Creates a mock image file."""
    content = b"fake image content"
    file_obj = io.BytesIO(content)
    return ("files", ("test.jpg", file_obj, "image/jpeg"))


@pytest.fixture
def mock_pdf_file():
    """Creates a mock PDF file."""
    content = b"fake pdf content"
    file_obj = io.BytesIO(content)
    return ("files", ("test.pdf", file_obj, "application/pdf"))


@pytest.fixture
def mock_csv_file():
    """Creates a mock CSV file."""
    content = b"col1,col2\nval1,val2"
    file_obj = io.BytesIO(content)
    return ("files", ("test.csv", file_obj, "text/csv"))


@pytest.fixture
def mock_docx_file():
    """Creates a mock DOCX file."""
    content = b"fake docx content"
    file_obj = io.BytesIO(content)
    return ("files", ("test.docx", file_obj, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))


@pytest.fixture
def mock_text_file():
    """Creates a mock text file."""
    content = b"Sample text content"
    file_obj = io.BytesIO(content)
    return ("files", ("test.txt", file_obj, "text/plain"))


@pytest.fixture
def mock_json_file():
    """Creates a mock JSON file."""
    content = b'{"key": "value"}'
    file_obj = io.BytesIO(content)
    return ("files", ("test.json", file_obj, "application/json"))


# --- Test Cases ---


def test_single_image_upload(test_app, mock_agent, mock_image_file):
    """Test uploading a single image file."""
    data = {
        "message": "Analyze this image",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }
    files = [mock_image_file]
    response = test_app.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
    assert response.status_code == 200

    mock_agent.run.assert_called_once()
    call_args = mock_agent.run.call_args[1]
    assert call_args["message"] == "Analyze this image"
    assert call_args["stream"] is False
    assert isinstance(call_args["images"], list)
    assert len(call_args["images"]) == 1
    assert isinstance(call_args["images"][0], Image)
    assert call_args["audio"] is None
    assert call_args["videos"] is None


def test_multiple_image_upload(test_app, mock_agent, mock_image_file):
    """Test uploading multiple image files."""
    data = {
        "message": "Analyze these images",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }
    files = [mock_image_file] * 3  # Upload 3 images
    response = test_app.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
    assert response.status_code == 200

    # Verify agent.run was called with multiple images
    mock_agent.run.assert_called_once()
    call_args = mock_agent.run.call_args[1]
    assert len(call_args["images"]) == 3
    assert all(isinstance(img, Image) for img in call_args["images"])
    assert call_args["audio"] is None
    assert call_args["videos"] is None


def test_pdf_upload_with_knowledge(
    test_app_with_knowledge, mock_agent_with_knowledge, mock_pdf_file, mock_document_readers
):
    """Test uploading a PDF file with knowledge base enabled."""
    data = {
        "message": "Analyze this PDF",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }
    files = [mock_pdf_file]
    response = test_app_with_knowledge.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
    assert response.status_code in (200, 500), f"Expected 200 or 500 status but got {response.status_code}"

    mock_agent_with_knowledge.knowledge.load_documents.assert_called_once_with(["This is mock PDF content"])
    mock_agent_with_knowledge.run.assert_called_once()


def test_pdf_upload_without_knowledge(test_app, mock_agent, mock_pdf_file):
    """Test uploading a PDF file without knowledge base - should create FileMedia objects."""
    data = {
        "message": "Analyze this PDF",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }
    files = [mock_pdf_file]
    response = test_app.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
    assert response.status_code == 200

    # Verify agent.run was called with files parameter containing FileMedia
    mock_agent.run.assert_called_once()
    call_args = mock_agent.run.call_args[1]
    assert call_args["message"] == "Analyze this PDF"
    assert call_args["stream"] is False
    assert call_args["images"] is None
    assert call_args["audio"] is None
    assert call_args["videos"] is None
    assert isinstance(call_args["files"], list)
    assert len(call_args["files"]) == 1
    assert isinstance(call_args["files"][0], FileMedia)


def test_mixed_file_upload(
    test_app_with_knowledge, mock_agent_with_knowledge, mock_image_file, mock_pdf_file, mock_document_readers
):
    """Test uploading both image and PDF files."""
    data = {
        "message": "Analyze these files",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }
    files = [mock_image_file, mock_pdf_file]
    response = test_app_with_knowledge.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
    assert response.status_code in (200, 500), f"Expected 200 or 500 status but got {response.status_code}"

    mock_agent_with_knowledge.knowledge.load_documents.assert_called_once_with(["This is mock PDF content"])

    mock_agent_with_knowledge.run.assert_called_once()
    call_args = mock_agent_with_knowledge.run.call_args[1]
    assert len(call_args["images"]) == 1
    assert isinstance(call_args["images"][0], Image)
    assert call_args["audio"] is None
    assert call_args["videos"] is None


def test_unsupported_file_type(test_app_with_knowledge, mock_agent_with_knowledge):
    """Test uploading an unsupported file type."""
    data = {
        "message": "Analyze this file",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }
    files = [("files", ("test.xyz", io.BytesIO(b"content"), "application/xyz"))]
    response = test_app_with_knowledge.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_empty_file_upload(test_app):
    """Test uploading an empty file."""
    data = {
        "message": "Analyze this file",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }
    empty_file = ("files", ("empty.jpg", io.BytesIO(b""), "image/jpeg"))
    files = [empty_file]
    response = test_app.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
    assert response.status_code == 200


def test_document_upload_with_knowledge(test_app_with_knowledge, mock_agent_with_knowledge, mock_document_readers):
    """Test uploading various document types with knowledge base enabled."""
    data = {
        "message": "Analyze these documents",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }

    # Test each document type
    document_files = [
        ("files", ("test.csv", io.BytesIO(b"col1,col2\nval1,val2"), "text/csv")),
        ("files", ("test.txt", io.BytesIO(b"text content"), "text/plain")),
        ("files", ("test.json", io.BytesIO(b'{"key":"value"}'), "application/json")),
        (
            "files",
            (
                "test.docx",
                io.BytesIO(b"docx content"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ),
    ]

    for doc_file in document_files:
        files = [doc_file]
        response = test_app_with_knowledge.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
        assert response.status_code in (200, 500), f"Expected 200 or 500 status but got {response.status_code}"

        # Reset the mock for the next iteration
        mock_agent_with_knowledge.knowledge.load_documents.reset_mock()
        mock_agent_with_knowledge.run.reset_mock()


def test_document_upload_without_knowledge(test_app, mock_agent):
    """Test uploading various document types without knowledge base - should create FileMedia objects."""
    data = {
        "message": "Analyze these documents",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }

    # Test each document type
    document_files = [
        ("files", ("test.csv", io.BytesIO(b"col1,col2\nval1,val2"), "text/csv")),
        ("files", ("test.txt", io.BytesIO(b"text content"), "text/plain")),
        ("files", ("test.json", io.BytesIO(b'{"key":"value"}'), "application/json")),
        (
            "files",
            (
                "test.docx",
                io.BytesIO(b"docx content"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ),
    ]

    for doc_file in document_files:
        files = [doc_file]
        response = test_app.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
        assert response.status_code == 200

        mock_agent.run.assert_called_once()
        call_args = mock_agent.run.call_args[1]
        assert isinstance(call_args["files"], list)
        assert len(call_args["files"]) == 1
        assert isinstance(call_args["files"][0], FileMedia)

        mock_agent.run.reset_mock()
