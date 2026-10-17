import httpx
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


# -- async_search: a search that could not run is not a search that matched nothing --
#
# VectorDb.async_search declares -> List[Document]. LightRag declared
# Optional[List[Document]] and returned [] for two httpx errors and None for anything
# else, while the sync search() folded None back into []. So every failure - a refused
# connection, a 500, an unreadable body - reached the caller as an empty result set,
# which is what a query that genuinely matched nothing returns.


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient as an async context manager."""

    def __init__(self, on_post):
        self._on_post = on_post

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, *args, **kwargs):
        return self._on_post()


@pytest.mark.asyncio
async def test_async_search_raises_when_the_server_is_unreachable(lightrag_db, monkeypatch):
    def refuse():
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(refuse))

    with pytest.raises(httpx.ConnectError):
        await lightrag_db.async_search("anything")


@pytest.mark.asyncio
async def test_async_search_raises_on_a_server_error(lightrag_db, monkeypatch):
    def five_hundred():
        request = httpx.Request("POST", f"{TEST_SERVER_URL}/query")
        return httpx.Response(status_code=500, request=request, json={"detail": "boom"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(five_hundred))

    with pytest.raises(httpx.HTTPStatusError):
        await lightrag_db.async_search("anything")


@pytest.mark.asyncio
async def test_async_search_returns_documents_when_the_server_answers(lightrag_db, monkeypatch):
    """The other half: a server that answered still produces documents, not an exception."""

    def ok():
        request = httpx.Request("POST", f"{TEST_SERVER_URL}/query")
        return httpx.Response(status_code=200, request=request, json={"response": "an answer"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(ok))

    documents = await lightrag_db.async_search("anything")
    assert [d.content for d in documents] == ["an answer"]
