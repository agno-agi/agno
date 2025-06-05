"""
Unit tests for playground file upload functionality.
"""

import io
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIChat
from agno.playground import Playground
from agno.run.response import RunResponse

# --- Fixtures ---


@pytest.fixture
def mock_pdf_reader():
    """Mock the PDFReader to avoid actual PDF parsing."""
    with patch("agno.document.reader.pdf_reader.PDFReader") as mock:
        # Configure the mock to return some dummy text content
        mock.return_value.read.return_value = ["This is mock PDF content"]
        yield mock


@pytest.fixture
def mock_agent():
    """Creates a mock agent with knowledge base disabled."""
    agent = Agent(
        name="Test Agent",
        agent_id="test-agent",
        model=OpenAIChat(id="gpt-4"),
    )
    # Create mock run method
    mock_run = Mock(return_value=RunResponse(content="Mocked response"))
    agent.run = mock_run

    # Create a copy of the agent that will be returned by deep_copy
    copied_agent = Agent(
        name="Test Agent",
        agent_id="test-agent",
        model=OpenAIChat(id="gpt-4"),
    )
    copied_agent.run = mock_run  # Use the same mock for the copy

    # Mock deep_copy to return our prepared copy
    agent.deep_copy = Mock(return_value=copied_agent)

    return agent


@pytest.fixture
def mock_agent_with_knowledge(mock_agent):
    """Creates a mock agent with knowledge base enabled."""
    mock_agent.knowledge = Mock()
    mock_agent.knowledge.load_documents = Mock()

    # Ensure the deep_copied agent also has knowledge
    copied_agent = mock_agent.deep_copy()
    copied_agent.knowledge = Mock()
    copied_agent.knowledge.load_documents = Mock()
    mock_agent.deep_copy.return_value = copied_agent

    return mock_agent


@pytest.fixture
def test_app(mock_agent):
    """Creates a TestClient with our playground router."""
    app = Playground(agents=[mock_agent]).get_app(use_async=False)
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

    # Get the copied agent that was actually used
    copied_agent = mock_agent.deep_copy()
    # Verify agent.run was called with an image
    copied_agent.run.assert_called_once()
    call_args = copied_agent.run.call_args[1]
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

    # Get the copied agent that was actually used
    copied_agent = mock_agent.deep_copy()
    # Verify agent.run was called with multiple images
    copied_agent.run.assert_called_once()
    call_args = copied_agent.run.call_args[1]
    assert len(call_args["images"]) == 3
    assert all(isinstance(img, Image) for img in call_args["images"])
    assert call_args["audio"] is None
    assert call_args["videos"] is None


def test_pdf_upload_with_knowledge(test_app, mock_agent_with_knowledge, mock_pdf_file, mock_pdf_reader):
    """Test uploading a PDF file with knowledge base enabled."""
    data = {
        "message": "Analyze this PDF",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }
    files = [mock_pdf_file]
    response = test_app.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
    assert response.status_code == 200

    # Verify knowledge.load_documents was called
    mock_agent_with_knowledge.knowledge.load_documents.assert_called_once_with(["This is mock PDF content"])
    mock_agent_with_knowledge.run.assert_called_once()


def test_pdf_upload_without_knowledge(test_app, mock_pdf_file):
    """Test uploading a PDF file without knowledge base."""
    data = {
        "message": "Analyze this PDF",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }
    files = [mock_pdf_file]
    response = test_app.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
    assert response.status_code == 404
    assert "KnowledgeBase not found" in response.json()["detail"]


def test_mixed_file_upload(test_app, mock_agent_with_knowledge, mock_image_file, mock_pdf_file, mock_pdf_reader):
    """Test uploading both image and PDF files."""
    data = {
        "message": "Analyze these files",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }
    files = [mock_image_file, mock_pdf_file]
    response = test_app.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
    assert response.status_code == 200

    # Verify knowledge.load_documents was called for PDF
    mock_agent_with_knowledge.knowledge.load_documents.assert_called_once_with(["This is mock PDF content"])
    # Verify agent.run was called with image
    mock_agent_with_knowledge.run.assert_called_once()
    call_args = mock_agent_with_knowledge.run.call_args[1]
    assert len(call_args["images"]) == 1
    assert isinstance(call_args["images"][0], Image)
    assert call_args["audio"] is None
    assert call_args["videos"] is None


def test_unsupported_file_type(test_app, mock_agent_with_knowledge):
    """Test uploading an unsupported file type."""
    data = {
        "message": "Analyze this file",
        "stream": "false",
        "monitor": "false",
        "user_id": "test_user",
    }
    files = [("files", ("test.xyz", io.BytesIO(b"content"), "application/xyz"))]
    response = test_app.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
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


def test_document_upload_with_knowledge(test_app, mock_agent_with_knowledge):
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
        response = test_app.post("/v1/playground/agents/test-agent/runs", data=data, files=files)
        assert response.status_code == 200
