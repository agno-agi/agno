"""Unit tests for WebTools class."""

from unittest.mock import Mock, patch

import pytest

from agno.tools.webtools import WebTools, _is_safe_url


@pytest.fixture
def web_tools():
    """Fixture to create a WebTools instance."""
    return WebTools(retries=3)


# ---------------------------------------------------------------------------
# _is_safe_url unit tests
# ---------------------------------------------------------------------------


def test_is_safe_url_blocks_loopback():
    with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 80))]):
        safe, reason = _is_safe_url("http://localhost/admin")
    assert not safe
    assert "private" in reason


def test_is_safe_url_blocks_link_local():
    with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("169.254.169.254", 80))]):
        safe, reason = _is_safe_url("http://metadata.internal/")
    assert not safe
    assert "private" in reason


def test_is_safe_url_blocks_private_rfc1918():
    for ip in ("10.0.0.1", "172.16.0.1", "192.168.1.1"):
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, (ip, 80))]):
            safe, reason = _is_safe_url(f"http://{ip}/secret")
        assert not safe, f"{ip} should be blocked"


def test_is_safe_url_blocks_file_scheme():
    safe, reason = _is_safe_url("file:///etc/passwd")
    assert not safe
    assert "scheme" in reason


def test_is_safe_url_allows_public_ip():
    with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 80))]):
        safe, reason = _is_safe_url("http://example.com/page")
    assert safe
    assert reason == ""


# ---------------------------------------------------------------------------
# expand_url integration tests
# ---------------------------------------------------------------------------


def test_expand_url_success(web_tools):
    """Test successful expansion of a public URL."""
    mock_url = "https://tinyurl.com/k2fkfxra"
    final_url = "https://github.com/agno-agi/agno"

    mock_response = Mock()
    mock_response.is_redirect = False
    mock_response.url = final_url

    with (
        patch("agno.tools.webtools._is_safe_url", return_value=(True, "")),
        patch("httpx.head", return_value=mock_response) as mock_head,
    ):
        result = web_tools.expand_url(mock_url)

    assert result == final_url
    # redirects are now followed manually (follow_redirects=False for security)
    mock_head.assert_called_once_with(mock_url, follow_redirects=False, timeout=5)


def test_expand_url_blocks_private_ip(web_tools):
    """expand_url must refuse to probe private/internal addresses."""
    with patch("agno.tools.webtools._is_safe_url", return_value=(False, "resolves to private/reserved IP 127.0.0.1")):
        result = web_tools.expand_url("http://localhost/admin")
    assert result == "http://localhost/admin"


def test_expand_url_blocks_metadata_endpoint(web_tools):
    """expand_url must not reach cloud metadata endpoints."""
    with patch(
        "agno.tools.webtools._is_safe_url",
        return_value=(False, "resolves to private/reserved IP 169.254.169.254"),
    ):
        result = web_tools.expand_url("http://169.254.169.254/latest/meta-data/")
    assert result == "http://169.254.169.254/latest/meta-data/"


def test_expand_url_blocks_redirect_to_private(web_tools):
    """expand_url must not follow redirects that lead to internal addresses."""
    redirect_response = Mock()
    redirect_response.is_redirect = True
    redirect_response.headers = {"location": "http://10.0.0.1/internal"}

    def safe_side_effect(url):
        if "evil.com" in url:
            return (True, "")
        return (False, "resolves to private/reserved IP 10.0.0.1")

    with (
        patch("agno.tools.webtools._is_safe_url", side_effect=safe_side_effect),
        patch("httpx.head", return_value=redirect_response),
    ):
        result = web_tools.expand_url("http://evil.com/redirect")

    assert result == "http://evil.com/redirect"


def test_toolkit_registration(web_tools):
    """Test that the expand_url method is registered correctly."""
    assert "expand_url" in [func.name for func in web_tools.functions.values()]
