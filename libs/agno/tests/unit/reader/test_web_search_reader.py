import httpx
import pytest

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.reader import web_search_reader
from agno.knowledge.reader.utils.url_validation import is_host_allowed
from agno.knowledge.reader.web_search_reader import WebSearchReader


def test_web_search_reader_chunk_size_propagation():
    """Test that chunk_size is propagated to default chunking strategy"""
    from agno.knowledge.chunking.semantic import SemanticChunking

    reader = WebSearchReader(chunk_size=900)
    assert reader.chunk_size == 900
    assert reader.chunking_strategy.chunk_size == 900
    assert isinstance(reader.chunking_strategy, SemanticChunking)


def test_web_search_reader_default_chunk_size():
    """Test default chunk_size is 5000"""
    from agno.knowledge.chunking.semantic import SemanticChunking

    reader = WebSearchReader()
    assert reader.chunk_size == 5000
    assert reader.chunking_strategy.chunk_size == 5000
    assert isinstance(reader.chunking_strategy, SemanticChunking)


def test_web_search_reader_explicit_strategy_preserved():
    """Test that explicit chunking_strategy is not overridden"""
    from agno.knowledge.chunking.fixed import FixedSizeChunking

    custom_strategy = FixedSizeChunking(chunk_size=1000)
    reader = WebSearchReader(chunk_size=500, chunking_strategy=custom_strategy)
    assert reader.chunk_size == 500
    assert reader.chunking_strategy is custom_strategy
    assert reader.chunking_strategy.chunk_size == 1000


# ---------------------------------------------------------------------------
# allowed_hosts (SSRF hardening)
# ---------------------------------------------------------------------------


def test_allowed_hosts_default_is_none():
    reader = WebSearchReader()
    assert reader.allowed_hosts is None
    assert is_host_allowed("https://example.com/x", reader.allowed_hosts) is True
    assert is_host_allowed("http://127.0.0.1:8000/admin", reader.allowed_hosts) is True


def test_allowed_hosts_lowercases_input():
    reader = WebSearchReader(allowed_hosts=["EXAMPLE.COM"])
    assert reader.allowed_hosts == ["example.com"]
    assert is_host_allowed("https://EXAMPLE.com/x", reader.allowed_hosts) is True


def test_allowed_hosts_rejects_unlisted():
    reader = WebSearchReader(allowed_hosts=["example.com"])
    assert is_host_allowed("http://127.0.0.1:8000/admin", reader.allowed_hosts) is False
    assert is_host_allowed("http://169.254.169.254/latest/meta-data", reader.allowed_hosts) is False


def test_is_valid_url_enforces_allowlist():
    """_is_valid_url should reject URLs whose host is not in the allowlist."""
    reader = WebSearchReader(allowed_hosts=["example.com"])
    assert reader._is_valid_url("https://example.com/page") is True
    assert reader._is_valid_url("http://127.0.0.1/admin") is False
    assert reader._is_valid_url("http://169.254.169.254/latest/meta-data") is False


def test_allowed_hosts_rejects_str_input():
    """Passing a single string (instead of a list) must raise error."""
    with pytest.raises(TypeError, match="must be a list"):
        WebSearchReader(allowed_hosts="example.com")


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("chunk", [False, True], ids=["whole-pages", "chunks"])
@pytest.mark.parametrize("failed_result", [False, True], ids=["successful", "failed-first"])
async def test_max_results_counts_pages_not_chunks(monkeypatch, use_async, chunk, failed_result):
    urls = [f"https://example.test/{name}" for name in ["first", "second", "third"]]
    failed_url = "https://example.test/missing"
    results = [{"href": url, "title": url} for url in urls]
    # Duplicate matches should not consume another page from the limit.
    results.insert(1, results[0])
    if failed_result:
        results.insert(0, {"href": failed_url, "title": "Missing"})

    class FakeSearch:
        def __init__(self, **kwargs):
            pass

        def text(self, query, max_results):
            assert query == "test query"
            assert max_results == 2
            return results

    requested = []

    def respond(request):
        url = str(request.url)
        requested.append(url)
        if url == failed_url:
            return httpx.Response(404)
        return httpx.Response(200, text="alpha beta gamma delta", headers={"content-type": "text/plain"})

    transport = httpx.MockTransport(respond)
    original_client = httpx.Client
    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(web_search_reader, "DDGS", FakeSearch)
    monkeypatch.setattr(
        web_search_reader.httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs)
    )
    monkeypatch.setattr(
        web_search_reader.httpx, "AsyncClient", lambda **kwargs: original_async_client(transport=transport, **kwargs)
    )
    reader = WebSearchReader(
        max_results=2,
        chunk=chunk,
        chunking_strategy=FixedSizeChunking(chunk_size=8),
        allowed_hosts=["example.test"],
        delay_between_requests=0,
        search_delay=0,
        max_retries=1,
    )

    documents = await reader.async_read("test query") if use_async else reader.read("test query")

    assert list(dict.fromkeys(document.meta_data["url"] for document in documents)) == urls[:2]
    assert requested == ([failed_url] if failed_result else []) + urls[:2]
    if chunk:
        assert len(documents) > reader.max_results
    else:
        assert [document.content for document in documents] == ["alpha beta gamma delta"] * 2
