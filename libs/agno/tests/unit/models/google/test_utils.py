"""Unit tests for ``agno.models.google.utils.media_to_content_item``."""

from unittest.mock import MagicMock, patch

import pytest

from agno.media import Image
from agno.models.google.utils import media_to_content_item

MAX_BYTES = 25 * 1024 * 1024


def _fake_response(body: bytes = b"img", content_length: str | None = None, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"content-length": content_length} if content_length else {}
    resp.iter_bytes.return_value = iter([body])
    return resp


def _mock_client(resp):
    client = MagicMock()
    client.stream.return_value.__enter__.return_value = resp
    return client


def test_media_url_download_ok():
    """A small HTTP body is downloaded and base64-encoded."""
    body = b"fake-image-bytes"
    client = _mock_client(_fake_response(body=body))
    with patch("agno.models.google.utils.httpx.Client", return_value=client):
        item = media_to_content_item(Image(url="https://example.com/img.png"), "image", "image/png")
    import base64

    assert item["data"] == base64.b64encode(body).decode()
    assert item["type"] == "image"


def test_media_url_content_length_over_limit():
    """A body whose Content-Length exceeds the cap is rejected and falls back to uri."""
    client = _mock_client(_fake_response(body=b"x", content_length=str(MAX_BYTES + 1)))
    with patch("agno.models.google.utils.httpx.Client", return_value=client):
        item = media_to_content_item(Image(url="https://example.com/big.png"), "image", "image/png")
    assert item["uri"] == "https://example.com/big.png"
    assert "data" not in item


def test_media_url_stream_over_limit():
    """A chunked body (no Content-Length) that exceeds the cap mid-stream is rejected."""
    client = _mock_client(_fake_response(body=b"y" * (MAX_BYTES + 1)))
    with patch("agno.models.google.utils.httpx.Client", return_value=client):
        item = media_to_content_item(Image(url="https://example.com/huge.png"), "image", "image/png")
    assert item["uri"] == "https://example.com/huge.png"
    assert "data" not in item


def test_media_url_chunked_under_limit_ok():
    """A multi-chunk body under the cap is still downloaded successfully."""
    chunk_a = b"z" * (10 * 1024 * 1024)
    chunk_b = b"z" * (10 * 1024 * 1024)
    resp = _fake_response()
    resp.iter_bytes.return_value = iter([chunk_a, chunk_b])
    client = _mock_client(resp)
    with patch("agno.models.google.utils.httpx.Client", return_value=client):
        item = media_to_content_item(Image(url="https://example.com/mid.png"), "image", "image/png")
    import base64

    assert item["data"] == base64.b64encode(chunk_a + chunk_b).decode()


def test_media_gcs_uri_passthrough():
    """GCS URIs are passed through without download."""
    item = media_to_content_item(Image(url="gs://bucket/file.png"), "image", "image/png")
    assert item["uri"] == "gs://bucket/file.png"
    assert "data" not in item


def test_media_gemini_file_api_uri_passthrough():
    """Gemini File API URIs are passed through without download."""
    url = "https://generativelanguage.googleapis.com/v1beta/files/abc"
    item = media_to_content_item(Image(url=url), "image", "image/png")
    assert item["uri"] == url
    assert "data" not in item


def test_media_download_http_error_falls_back():
    """An HTTP error during download falls back to uri (existing error path)."""
    client = _mock_client(_fake_response(status=404))
    with patch("agno.models.google.utils.httpx.Client", return_value=client):
        item = media_to_content_item(Image(url="https://example.com/404.png"), "image", "image/png")
    assert item["uri"] == "https://example.com/404.png"
    assert "data" not in item


@pytest.mark.parametrize("url", ["not-a-url", "", None])
def test_media_no_url_source(url):
    """No URL, no content, no filepath, no external -> warning path returns None."""
    if url is None:
        media = Image()
    else:
        media = Image(url=url)
    item = media_to_content_item(media, "image", "image/png")
    assert item is None or item.get("uri") == url
