import pytest

from agno.vectordb.lightrag import LightRag

TEST_SERVER_URL = "http://localhost:9621"
TEST_API_KEY = "test_api_key"


@pytest.fixture
def lightrag_db():
    """Fixture to create a LightRag instance"""
    db = LightRag(
        server_url=TEST_SERVER_URL,
        api_key=TEST_API_KEY,
    )
    yield db


def test_initialization():
    """Test basic initialization with defaults"""
    db = LightRag()

    assert db.server_url == "http://localhost:9621"
    assert db.api_key is None


def test_initialization_with_params():
    """Test initialization with custom parameters"""
    db = LightRag(
        server_url="http://custom:8080",
        api_key="secret",
        name="test_db",
        description="Test database",
    )

    assert db.server_url == "http://custom:8080"
    assert db.api_key == "secret"
    assert db.name == "test_db"
    assert db.description == "Test database"


def test_get_headers_with_api_key(lightrag_db):
    """Test headers include API key when configured"""
    headers = lightrag_db._get_headers()

    assert headers["Content-Type"] == "application/json"
    assert headers["X-API-KEY"] == TEST_API_KEY


def test_get_headers_without_api_key():
    """Test headers without API key"""
    db = LightRag(server_url=TEST_SERVER_URL)
    headers = db._get_headers()

    assert headers["Content-Type"] == "application/json"
    assert "X-API-KEY" not in headers


def test_get_auth_headers(lightrag_db):
    """Test auth headers for file uploads"""
    headers = lightrag_db._get_auth_headers()

    assert "Content-Type" not in headers
    assert headers["X-API-KEY"] == TEST_API_KEY


def test_custom_auth_header_format():
    """Test custom auth header name and format"""
    db = LightRag(
        server_url=TEST_SERVER_URL,
        api_key="my_key",
        auth_header_name="Authorization",
        auth_header_format="Bearer {api_key}",
    )
    headers = db._get_headers()

    assert headers["Authorization"] == "Bearer my_key"


def test_format_response_with_references(lightrag_db):
    """Test that references are preserved in meta_data"""
    result = {
        "response": "Jordan Mitchell has skills in Python and JavaScript.",
        "references": [
            {"reference_id": "1", "file_path": "cv_1.pdf", "content": None},
            {"reference_id": "2", "file_path": "cv_2.pdf", "content": None},
        ],
    }

    documents = lightrag_db._format_lightrag_response(result, "What skills?", "hybrid")

    assert len(documents) == 1
    assert documents[0].content == "Jordan Mitchell has skills in Python and JavaScript."
    assert documents[0].meta_data["source"] == "lightrag"
    assert documents[0].meta_data["query"] == "What skills?"
    assert documents[0].meta_data["mode"] == "hybrid"
    assert "references" in documents[0].meta_data
    assert len(documents[0].meta_data["references"]) == 2
    assert documents[0].meta_data["references"][0]["file_path"] == "cv_1.pdf"


def test_format_response_without_references(lightrag_db):
    """Test backward compatibility when no references in response"""
    result = {"response": "Some content without references."}

    documents = lightrag_db._format_lightrag_response(result, "query", "local")

    assert len(documents) == 1
    assert documents[0].content == "Some content without references."
    assert "references" not in documents[0].meta_data


def test_format_response_list_with_content(lightrag_db):
    """Test formatting list response with content field"""
    result = [
        {"content": "First document", "metadata": {"source": "custom"}},
        {"content": "Second document"},
    ]

    documents = lightrag_db._format_lightrag_response(result, "query", "global")

    assert len(documents) == 2
    assert documents[0].content == "First document"
    assert documents[0].meta_data["source"] == "custom"


def test_format_response_list_plain_strings(lightrag_db):
    """Test formatting list response with plain strings"""
    result = ["plain text item 1", "plain text item 2"]

    documents = lightrag_db._format_lightrag_response(result, "query", "hybrid")

    assert len(documents) == 2
    assert documents[0].content == "plain text item 1"
    assert documents[0].meta_data["source"] == "lightrag"


def test_format_response_string(lightrag_db):
    """Test formatting plain string response"""
    result = "Just a plain string response"

    documents = lightrag_db._format_lightrag_response(result, "query", "hybrid")

    assert len(documents) == 1
    assert documents[0].content == "Just a plain string response"
    assert documents[0].meta_data["source"] == "lightrag"
