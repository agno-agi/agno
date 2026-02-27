"""Tests for S3BackupStore."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.store.backup_store import GrepResult


@pytest.fixture
def mock_s3_client():
    """Create a mock S3 client with in-memory storage."""
    storage = {}

    client = MagicMock()

    def put_object(Bucket, Key, Body, **kwargs):
        if isinstance(Body, bytes):
            storage[Key] = Body
        elif isinstance(Body, str):
            storage[Key] = Body.encode("utf-8")
        else:
            storage[Key] = Body

    def get_object(Bucket, Key):
        if Key not in storage:
            error = type("NoSuchKey", (Exception,), {})
            raise client.exceptions.NoSuchKey({}, "NoSuchKey")
        body = MagicMock()
        body.read.return_value = storage[Key]
        return {"Body": body}

    # Set up paginator for list operations
    def get_paginator(operation):
        paginator = MagicMock()

        def paginate(Bucket, Prefix, Delimiter="/"):
            # Find all "directories" under the prefix
            common_prefixes = set()
            for key in storage:
                if key.startswith(Prefix):
                    relative = key[len(Prefix) :]
                    parts = relative.split("/", 1)
                    if len(parts) > 1:
                        common_prefixes.add(Prefix + parts[0] + "/")

            return [{"CommonPrefixes": [{"Prefix": cp} for cp in sorted(common_prefixes)]}]

        paginator.paginate = paginate
        return paginator

    # Set up exceptions
    no_such_key = type("NoSuchKey", (Exception,), {})
    client.exceptions = MagicMock()
    client.exceptions.NoSuchKey = no_such_key

    client.put_object = put_object
    client.get_object = get_object
    client.get_paginator = get_paginator
    client._storage = storage  # Expose for test assertions

    return client


@pytest.fixture
def store(mock_s3_client):
    """Create an S3BackupStore with mocked S3 client."""
    with patch("agno.knowledge.store.s3_backup_store.S3BackupStore._get_client", return_value=mock_s3_client):
        from agno.knowledge.store.s3_backup_store import S3BackupStore

        s = S3BackupStore(bucket_name="test-bucket", prefix="backups")
        s._mock_client = mock_s3_client
        yield s


class TestStore:
    def test_store_writes_parsed_text(self, store, mock_s3_client):
        with patch.object(store, "_get_client", return_value=mock_s3_client):
            store.store(content_id="doc1", parsed_text="Hello world\nLine 2")

        assert b"Hello world\nLine 2" == mock_s3_client._storage["backups/doc1/parsed.txt"]

    def test_store_writes_raw_bytes(self, store, mock_s3_client):
        with patch.object(store, "_get_client", return_value=mock_s3_client):
            store.store(content_id="doc1", parsed_text="text", raw_bytes=b"raw pdf data", file_extension=".pdf")

        assert b"raw pdf data" == mock_s3_client._storage["backups/doc1/raw.pdf"]

    def test_store_writes_metadata(self, store, mock_s3_client):
        with patch.object(store, "_get_client", return_value=mock_s3_client):
            store.store(content_id="doc1", parsed_text="text", metadata={"name": "test.pdf"})

        meta = json.loads(mock_s3_client._storage["backups/doc1/metadata.json"].decode())
        assert meta["name"] == "test.pdf"

    def test_store_extension_normalization(self, store, mock_s3_client):
        with patch.object(store, "_get_client", return_value=mock_s3_client):
            store.store(content_id="doc1", parsed_text="text", raw_bytes=b"data", file_extension="txt")

        assert "backups/doc1/raw.txt" in mock_s3_client._storage


class TestRead:
    def test_read_full_document(self, store, mock_s3_client):
        mock_s3_client._storage["backups/doc1/parsed.txt"] = b"Line 1\nLine 2\nLine 3"

        with patch.object(store, "_get_client", return_value=mock_s3_client):
            result = store.read("doc1")

        assert result is not None
        assert "[Lines 1-3 of 3]" in result
        assert "1: Line 1" in result

    def test_read_with_pagination(self, store, mock_s3_client):
        lines = "\n".join(f"Line {i}" for i in range(1, 11))
        mock_s3_client._storage["backups/doc1/parsed.txt"] = lines.encode()

        with patch.object(store, "_get_client", return_value=mock_s3_client):
            result = store.read("doc1", offset=3, limit=4)

        assert result is not None
        assert "[Lines 4-7 of 10]" in result

    def test_read_nonexistent_returns_none(self, store, mock_s3_client):
        with patch.object(store, "_get_client", return_value=mock_s3_client):
            result = store.read("nonexistent")

        assert result is None


class TestGrep:
    def test_grep_finds_pattern(self, store, mock_s3_client):
        mock_s3_client._storage["backups/doc1/parsed.txt"] = b"apple\nbanana\ncherry"

        with patch.object(store, "_get_client", return_value=mock_s3_client):
            results = store.grep("doc1", "cherry")

        assert len(results) == 1
        assert results[0].line_number == 3
        assert results[0].line == "cherry"

    def test_grep_nonexistent_document(self, store, mock_s3_client):
        with patch.object(store, "_get_client", return_value=mock_s3_client):
            results = store.grep("nonexistent", "pattern")

        assert results == []


class TestGrepAll:
    def test_grep_all_searches_multiple_docs(self, store, mock_s3_client):
        mock_s3_client._storage["backups/doc1/parsed.txt"] = b"apple pie"
        mock_s3_client._storage["backups/doc2/parsed.txt"] = b"apple sauce"

        with patch.object(store, "_get_client", return_value=mock_s3_client):
            with patch.object(store, "_list_content_ids", return_value=["doc1", "doc2"]):
                results = store.grep_all("apple")

        assert len(results) == 2


class TestGetTools:
    def test_get_tools_returns_two_tools(self, store):
        tools = store.get_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "read_backup" in names
        assert "grep_backup" in names


class TestKeyGeneration:
    def test_key_format(self, store):
        assert store._key("doc1", "parsed.txt") == "backups/doc1/parsed.txt"

    def test_key_strips_trailing_slash(self):
        from agno.knowledge.store.s3_backup_store import S3BackupStore

        s = S3BackupStore(bucket_name="test", prefix="backups/")
        assert s._key("doc1", "parsed.txt") == "backups/doc1/parsed.txt"
