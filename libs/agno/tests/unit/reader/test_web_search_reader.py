import pytest

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
