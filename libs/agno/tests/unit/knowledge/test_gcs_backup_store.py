"""Tests for GCSBackupStore."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.store.backup_store import GrepResult


class MockBlob:
    """Mock GCS blob with in-memory storage."""

    def __init__(self, name, storage):
        self.name = name
        self._storage = storage

    def upload_from_string(self, data, content_type=None):
        if isinstance(data, str):
            self._storage[self.name] = data.encode("utf-8")
        else:
            self._storage[self.name] = data

    def exists(self):
        return self.name in self._storage

    def download_as_text(self, encoding="utf-8"):
        return self._storage[self.name].decode(encoding)


class MockBucket:
    """Mock GCS bucket with in-memory storage."""

    def __init__(self):
        self._storage = {}

    def blob(self, name):
        return MockBlob(name, self._storage)

    def list_blobs(self, prefix=""):
        blobs = []
        for key in sorted(self._storage.keys()):
            if key.startswith(prefix):
                blob = MagicMock()
                blob.name = key
                blobs.append(blob)
        return blobs


@pytest.fixture
def mock_bucket():
    return MockBucket()


@pytest.fixture
def store(mock_bucket):
    """Create a GCSBackupStore with mocked GCS client."""
    with patch("agno.knowledge.store.gcs_backup_store.GCSBackupStore._get_bucket", return_value=mock_bucket):
        from agno.knowledge.store.gcs_backup_store import GCSBackupStore

        s = GCSBackupStore(bucket_name="test-bucket", prefix="backups")
        s._mock_bucket = mock_bucket
        yield s


class TestStore:
    def test_store_writes_parsed_text(self, store, mock_bucket):
        with patch.object(store, "_get_bucket", return_value=mock_bucket):
            store.store(content_id="doc1", parsed_text="Hello world\nLine 2")

        assert b"Hello world\nLine 2" == mock_bucket._storage["backups/doc1/parsed.txt"]

    def test_store_writes_raw_bytes(self, store, mock_bucket):
        with patch.object(store, "_get_bucket", return_value=mock_bucket):
            store.store(content_id="doc1", parsed_text="text", raw_bytes=b"raw pdf data", file_extension=".pdf")

        assert b"raw pdf data" == mock_bucket._storage["backups/doc1/raw.pdf"]

    def test_store_writes_metadata(self, store, mock_bucket):
        with patch.object(store, "_get_bucket", return_value=mock_bucket):
            store.store(content_id="doc1", parsed_text="text", metadata={"name": "test.pdf"})

        meta = json.loads(mock_bucket._storage["backups/doc1/metadata.json"].decode())
        assert meta["name"] == "test.pdf"

    def test_store_extension_normalization(self, store, mock_bucket):
        with patch.object(store, "_get_bucket", return_value=mock_bucket):
            store.store(content_id="doc1", parsed_text="text", raw_bytes=b"data", file_extension="txt")

        assert "backups/doc1/raw.txt" in mock_bucket._storage


class TestRead:
    def test_read_full_document(self, store, mock_bucket):
        mock_bucket._storage["backups/doc1/parsed.txt"] = b"Line 1\nLine 2\nLine 3"

        with patch.object(store, "_get_bucket", return_value=mock_bucket):
            result = store.read("doc1")

        assert result is not None
        assert "[Lines 1-3 of 3]" in result
        assert "1: Line 1" in result

    def test_read_with_pagination(self, store, mock_bucket):
        lines = "\n".join(f"Line {i}" for i in range(1, 11))
        mock_bucket._storage["backups/doc1/parsed.txt"] = lines.encode()

        with patch.object(store, "_get_bucket", return_value=mock_bucket):
            result = store.read("doc1", offset=3, limit=4)

        assert result is not None
        assert "[Lines 4-7 of 10]" in result

    def test_read_nonexistent_returns_none(self, store, mock_bucket):
        with patch.object(store, "_get_bucket", return_value=mock_bucket):
            result = store.read("nonexistent")

        assert result is None


class TestGrep:
    def test_grep_finds_pattern(self, store, mock_bucket):
        mock_bucket._storage["backups/doc1/parsed.txt"] = b"apple\nbanana\ncherry"

        with patch.object(store, "_get_bucket", return_value=mock_bucket):
            results = store.grep("doc1", "cherry")

        assert len(results) == 1
        assert results[0].line_number == 3
        assert results[0].line == "cherry"

    def test_grep_nonexistent_document(self, store, mock_bucket):
        with patch.object(store, "_get_bucket", return_value=mock_bucket):
            results = store.grep("nonexistent", "pattern")

        assert results == []


class TestGrepAll:
    def test_grep_all_searches_multiple_docs(self, store, mock_bucket):
        mock_bucket._storage["backups/doc1/parsed.txt"] = b"apple pie"
        mock_bucket._storage["backups/doc2/parsed.txt"] = b"apple sauce"

        with patch.object(store, "_get_bucket", return_value=mock_bucket):
            results = store.grep_all("apple")

        assert len(results) == 2


class TestGetTools:
    def test_get_tools_returns_two_tools(self, store):
        tools = store.get_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "read_backup" in names
        assert "grep_backup" in names


class TestBlobNameGeneration:
    def test_blob_name_format(self, store):
        assert store._blob_name("doc1", "parsed.txt") == "backups/doc1/parsed.txt"

    def test_blob_name_strips_trailing_slash(self):
        from agno.knowledge.store.gcs_backup_store import GCSBackupStore

        s = GCSBackupStore(bucket_name="test", prefix="backups/")
        assert s._blob_name("doc1", "parsed.txt") == "backups/doc1/parsed.txt"
