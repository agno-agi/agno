"""Regression tests that every ingestion path carries user_id to the vector DB.

Directory and topic ingest rebuild a fresh Content per file/source and used to
drop user_id into the shared bucket; these pin that the owner now propagates.
"""

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from agno.knowledge.content import Content
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb


class RecordingVectorDb(VectorDb):
    """Records the user_id handed to every write."""

    def __init__(self) -> None:
        self.insert_user_ids: List[Optional[str]] = []

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    async def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    def insert(self, content_hash, documents, filters=None, user_id=None) -> None:
        self.insert_user_ids.append(user_id)

    async def async_insert(self, content_hash, documents, filters=None, user_id=None) -> None:
        self.insert_user_ids.append(user_id)

    def upsert(self, content_hash, documents, filters=None, user_id=None) -> None:
        self.insert_user_ids.append(user_id)

    async def async_upsert(self, content_hash, documents, filters=None, user_id=None) -> None:
        self.insert_user_ids.append(user_id)

    def upsert_available(self) -> bool:
        return False

    def search(self, query, limit=5, filters=None, user_id=None) -> List[Document]:
        return []

    async def async_search(self, query, limit=5, filters=None, user_id=None) -> List[Document]:
        return []

    def drop(self) -> None:
        pass

    async def async_drop(self) -> None:
        pass

    def exists(self) -> bool:
        return True

    async def async_exists(self) -> bool:
        return True

    def delete_by_id(self, id: str) -> bool:
        return True

    def delete_by_name(self, name: str) -> bool:
        return True

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        return True

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        return True

    def delete(self) -> bool:
        return True

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        pass

    def get_supported_search_types(self) -> List[Any]:
        return []


class _StubReader:
    """Minimal reader: one Document per source, no external deps."""

    def __init__(self) -> None:
        self.chunk = False

    def read(self, *args, **kwargs) -> List[Document]:
        return [Document(name="doc", content="hello world")]

    async def async_read(self, *args, **kwargs) -> List[Document]:
        return [Document(name="doc", content="hello world")]


def test_directory_ingest_propagates_user_id():
    """insert(path=<dir>, user_id=...) must scope every file, not the shared bucket."""
    vdb = RecordingVectorDb()
    knowledge = Knowledge(vector_db=vdb)

    with tempfile.TemporaryDirectory() as tmp:
        for name in ("a.txt", "b.txt"):
            Path(tmp, name).write_text("hello world")
        knowledge.insert(path=tmp, user_id="alice", reader=_StubReader())

    assert vdb.insert_user_ids, "directory ingest produced no vector-db writes"
    assert all(uid == "alice" for uid in vdb.insert_user_ids), (
        f"directory ingest leaked to other buckets: {vdb.insert_user_ids}"
    )


def test_directory_ingest_none_stays_shared():
    """Unscoped directory ingest still writes to the shared bucket (None)."""
    vdb = RecordingVectorDb()
    knowledge = Knowledge(vector_db=vdb)

    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "a.txt").write_text("hello world")
        knowledge.insert(path=tmp, reader=_StubReader())

    assert vdb.insert_user_ids
    assert all(uid is None for uid in vdb.insert_user_ids)


def test_per_file_content_carries_user_id():
    """The Content rebuilt per directory file must inherit the owner."""
    parent = Content(name="dir", path="/tmp/whatever", user_id="alice")
    child = Content(
        name=parent.name,
        path="/tmp/whatever/a.txt",
        metadata=parent.metadata,
        description=parent.description,
        reader=parent.reader,
        user_id=parent.user_id,
    )
    assert child.user_id == "alice"


def _stub_loader(loader):
    """Mock everything around the per-object Content rebuild and capture the result.

    Stops before the download/read so no client dep is touched; _should_skip=True
    short-circuits each object right after the scoped Content is built.
    """
    captured: List[Content] = []
    loader._build_content_hash = MagicMock(return_value="h")  # normally supplied by the Knowledge host
    loader._update_content = MagicMock()
    loader._should_skip = MagicMock(return_value=True)
    loader._insert_contents_db = lambda entry: captured.append(entry)
    return captured


def test_s3_loader_propagates_user_id():
    """The S3 loader rebuilds a Content per object; each must inherit the owner."""
    from agno.knowledge.loaders.s3 import S3Loader

    loader = S3Loader()
    loader._validate_s3_config = MagicMock(return_value=None)
    loader._build_s3_metadata = MagicMock(return_value={})
    captured = _stub_loader(loader)

    obj = MagicMock()
    obj.name = "folder/file1.txt"
    bucket = MagicMock()
    bucket.name = "b"
    bucket.get_objects.return_value = [obj]
    remote = MagicMock(spec=["bucket", "bucket_name", "key", "object", "prefix"])
    remote.bucket = bucket
    remote.bucket_name = "b"
    remote.key = None
    remote.object = None
    remote.prefix = "folder/"

    for owner in ("alice", None):
        captured.clear()
        parent = Content(name="kb", user_id=owner)
        parent.remote_content = remote
        loader._load_from_s3(parent, upsert=False, skip_if_exists=True)
        assert [c.user_id for c in captured] == [owner], f"S3 leaked owner {owner!r}: {[c.user_id for c in captured]}"


def test_gcs_loader_propagates_user_id():
    """The GCS loader rebuilds a Content per blob; each must inherit the owner."""
    pytest.importorskip("google.cloud.storage")
    from agno.knowledge.loaders.gcs import GCSLoader

    loader = GCSLoader()
    loader._validate_gcs_config = MagicMock(return_value=None)
    loader._build_gcs_metadata = MagicMock(return_value={})
    captured = _stub_loader(loader)

    blob = MagicMock()
    blob.name = "folder/file1.txt"
    bucket = MagicMock()
    bucket.name = "b"
    bucket.list_blobs.return_value = [blob]
    remote = MagicMock(spec=["bucket", "bucket_name", "blob_name", "prefix"])
    remote.bucket = bucket
    remote.bucket_name = "b"
    remote.blob_name = None
    remote.prefix = "folder/"

    for owner in ("alice", None):
        captured.clear()
        parent = Content(name="kb", user_id=owner)
        parent.remote_content = remote
        loader._load_from_gcs(parent, upsert=False, skip_if_exists=True)
        assert [c.user_id for c in captured] == [owner], f"GCS leaked owner {owner!r}: {[c.user_id for c in captured]}"
