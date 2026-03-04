import pytest

from agno.knowledge.external_provider.lightrag import LightRagBackend

TEST_SERVER_URL = "http://localhost:9621"
TEST_API_KEY = "test_api_key"


@pytest.fixture
def lightrag_backend():
    """Fixture to create a LightRagBackend instance"""
    backend = LightRagBackend(
        server_url=TEST_SERVER_URL,
        api_key=TEST_API_KEY,
    )
    yield backend


def test_initialization():
    """Test basic initialization with defaults"""
    backend = LightRagBackend()

    assert backend.server_url == "http://localhost:9621"
    assert backend.api_key is None


def test_initialization_with_params():
    """Test initialization with custom parameters"""
    backend = LightRagBackend(
        server_url="http://custom:8080",
        api_key="secret",
    )

    assert backend.server_url == "http://custom:8080"
    assert backend.api_key == "secret"


def test_get_headers_with_api_key(lightrag_backend):
    """Test headers include API key when configured"""
    headers = lightrag_backend._get_headers()

    assert headers["Content-Type"] == "application/json"
    assert headers["X-API-KEY"] == TEST_API_KEY


def test_get_headers_without_api_key():
    """Test headers without API key"""
    backend = LightRagBackend(server_url=TEST_SERVER_URL)
    headers = backend._get_headers()

    assert headers["Content-Type"] == "application/json"
    assert "X-API-KEY" not in headers


def test_get_auth_headers(lightrag_backend):
    """Test auth headers for file uploads"""
    headers = lightrag_backend._get_auth_headers()

    assert "Content-Type" not in headers
    assert headers["X-API-KEY"] == TEST_API_KEY


def test_custom_auth_header_format():
    """Test custom auth header name and format"""
    backend = LightRagBackend(
        server_url=TEST_SERVER_URL,
        api_key="my_key",
        auth_header_name="Authorization",
        auth_header_format="Bearer {api_key}",
    )
    headers = backend._get_headers()

    assert headers["Authorization"] == "Bearer my_key"


def test_format_response_with_references(lightrag_backend):
    """Test that references are preserved in meta_data"""
    result = {
        "response": "Jordan Mitchell has skills in Python and JavaScript.",
        "references": [
            {"reference_id": "1", "file_path": "cv_1.pdf", "content": None},
            {"reference_id": "2", "file_path": "cv_2.pdf", "content": None},
        ],
    }

    documents = lightrag_backend._format_response(result, "What skills?", "hybrid")

    assert len(documents) == 1
    assert documents[0].content == "Jordan Mitchell has skills in Python and JavaScript."
    assert documents[0].meta_data["source"] == "lightrag"
    assert documents[0].meta_data["query"] == "What skills?"
    assert documents[0].meta_data["mode"] == "hybrid"
    assert "references" in documents[0].meta_data
    assert len(documents[0].meta_data["references"]) == 2
    assert documents[0].meta_data["references"][0]["file_path"] == "cv_1.pdf"


def test_format_response_without_references(lightrag_backend):
    """Test backward compatibility when no references in response"""
    result = {"response": "Some content without references."}

    documents = lightrag_backend._format_response(result, "query", "local")

    assert len(documents) == 1
    assert documents[0].content == "Some content without references."
    assert "references" not in documents[0].meta_data


def test_format_response_list_with_content(lightrag_backend):
    """Test formatting list response with content field"""
    result = [
        {"content": "First document", "metadata": {"source": "custom"}},
        {"content": "Second document"},
    ]

    documents = lightrag_backend._format_response(result, "query", "global")

    assert len(documents) == 2
    assert documents[0].content == "First document"
    assert documents[0].meta_data["source"] == "custom"


def test_format_response_list_plain_strings(lightrag_backend):
    """Test formatting list response with plain strings"""
    result = ["plain text item 1", "plain text item 2"]

    documents = lightrag_backend._format_response(result, "query", "hybrid")

    assert len(documents) == 2
    assert documents[0].content == "plain text item 1"
    assert documents[0].meta_data["source"] == "lightrag"


def test_format_response_string(lightrag_backend):
    """Test formatting plain string response"""
    result = "Just a plain string response"

    documents = lightrag_backend._format_response(result, "query", "hybrid")

    assert len(documents) == 1
    assert documents[0].content == "Just a plain string response"
    assert documents[0].meta_data["source"] == "lightrag"
