"""Tests for LocalMediaStorage."""

import tempfile
from pathlib import Path

from agno.media_storage.local import LocalMediaStorage


def test_upload_download():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        content = b"hello world"
        key = storage.upload("test-1", content, mime_type="text/plain")
        assert storage.exists(key)
        downloaded = storage.download(key)
        assert downloaded == content


def test_upload_with_filename():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        content = b"\x89PNG\r\n"
        key = storage.upload("img-1", content, filename="photo.png")
        assert key.endswith(".png")
        assert storage.exists(key)


def test_get_url_file_uri():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        content = b"data"
        key = storage.upload("test-2", content)
        url = storage.get_url(key)
        assert url.startswith("file://")


def test_get_url_with_base_url():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir, base_url="http://localhost:8080/media")
        content = b"data"
        key = storage.upload("test-3", content)
        url = storage.get_url(key)
        assert url.startswith("http://localhost:8080/media/")


def test_delete():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        content = b"to delete"
        key = storage.upload("test-4", content, mime_type="text/plain")
        assert storage.exists(key)
        assert storage.delete(key)
        assert not storage.exists(key)


def test_metadata_sidecar():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        content = b"with meta"
        key = storage.upload(
            "meta-1",
            content,
            mime_type="application/pdf",
            filename="report.pdf",
            metadata={"department": "finance"},
        )
        sidecar_path = Path(tmpdir) / (key + ".meta.json")
        assert sidecar_path.exists()

        import json

        meta = json.loads(sidecar_path.read_text())
        assert meta["original_filename"] == "report.pdf"
        assert meta["mime_type"] == "application/pdf"
        assert meta["department"] == "finance"
        assert "content_sha256" in meta
        assert meta["size"] == len(content)
