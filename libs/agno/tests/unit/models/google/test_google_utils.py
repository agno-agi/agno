"""Unit tests for agno.models.google.utils."""

import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agno.media import Image
from agno.models.google import utils as google_utils
from agno.models.google.utils import media_to_content_item

CHUNK = 64 * 1024
SMALL_BODY = b"\x89PNG\r\n\x1a\n" + b"a" * 100


class _State:
    def __init__(self, total: int) -> None:
        self.total = total
        self.bytes_written = 0


class _MediaHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the test output clean
        pass

    def do_GET(self):  # noqa: N802
        state = self.server.state  # type: ignore[attr-defined]

        if self.path == "/small":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(SMALL_BODY)))
            self.end_headers()
            self.wfile.write(SMALL_BODY)
            return

        if self.path == "/declared-huge":
            # Honest, oversized Content-Length: must be refused before any body is read.
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(state.total))
            self.end_headers()
            self._pump(state)
            return

        if self.path == "/chunked-huge":
            # No Content-Length at all: only a running byte count can stop this.
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            chunk = b"a" * CHUNK
            framed = b"%x\r\n" % len(chunk) + chunk + b"\r\n"
            try:
                for _ in range(state.total // CHUNK):
                    self.wfile.write(framed)
                    self.wfile.flush()
                    state.bytes_written += len(chunk)
                self.wfile.write(b"0\r\n\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _pump(self, state):
        chunk = b"a" * CHUNK
        try:
            remaining = state.total
            while remaining > 0:
                piece = chunk[: min(CHUNK, remaining)]
                self.wfile.write(piece)
                self.wfile.flush()
                state.bytes_written += len(piece)
                remaining -= len(piece)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture
def media_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MediaHandler)
    server.state = _State(total=16 * 1024 * 1024)  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _url(server, path: str) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}{path}"


class TestMediaDownloadSizeLimit:
    """A remote media URL must not be able to pull an unbounded body into memory."""

    def test_declared_oversize_body_is_refused(self, media_server, monkeypatch):
        monkeypatch.setattr(google_utils, "MAX_MEDIA_DOWNLOAD_BYTES", 1024 * 1024)
        url = _url(media_server, "/declared-huge")

        item = media_to_content_item(Image(url=url), "image", "image/jpeg")

        assert item is not None
        assert "data" not in item
        assert item["uri"] == url
        assert media_server.state.bytes_written <= media_server.state.total // 2

    def test_undeclared_oversize_body_is_cut_off_mid_stream(self, media_server, monkeypatch):
        monkeypatch.setattr(google_utils, "MAX_MEDIA_DOWNLOAD_BYTES", 1024 * 1024)
        url = _url(media_server, "/chunked-huge")

        item = media_to_content_item(Image(url=url), "image", "image/jpeg")

        assert item is not None
        assert "data" not in item
        assert item["uri"] == url
        # The download was abandoned in flight rather than buffered in full.
        assert media_server.state.bytes_written <= media_server.state.total // 2

    def test_explicit_max_bytes_argument_is_honoured(self, media_server):
        url = _url(media_server, "/chunked-huge")

        item = media_to_content_item(Image(url=url), "image", "image/jpeg", max_bytes=1024 * 1024)

        assert item is not None
        assert "data" not in item


class TestMediaDownloadCompatibility:
    """Downloads that fit the limit keep behaving exactly as before."""

    def test_small_body_is_downloaded_and_encoded(self, media_server):
        url = _url(media_server, "/small")

        item = media_to_content_item(Image(url=url), "image", "image/jpeg")

        assert item is not None
        assert base64.b64decode(item["data"]) == SMALL_BODY
        assert item["mime_type"] == "image/jpeg"
        assert "uri" not in item

    def test_body_exactly_at_the_limit_is_accepted(self, media_server, monkeypatch):
        monkeypatch.setattr(google_utils, "MAX_MEDIA_DOWNLOAD_BYTES", len(SMALL_BODY))
        url = _url(media_server, "/small")

        item = media_to_content_item(Image(url=url), "image", "image/jpeg")

        assert item is not None
        assert base64.b64decode(item["data"]) == SMALL_BODY

    def test_gcs_uri_is_passed_through_without_download(self):
        item = media_to_content_item(Image(url="gs://bucket/cat.png"), "image", "image/jpeg")

        assert item == {"type": "image", "mime_type": "image/jpeg", "uri": "gs://bucket/cat.png"}

    def test_file_api_uri_is_passed_through_without_download(self):
        url = "https://generativelanguage.googleapis.com/v1beta/files/abc"
        item = media_to_content_item(Image(url=url), "image", "image/jpeg")

        assert item == {"type": "image", "mime_type": "image/jpeg", "uri": url}

    def test_default_limit_is_the_gemini_inline_ceiling(self):
        assert google_utils.MAX_MEDIA_DOWNLOAD_BYTES == 20 * 1024 * 1024
