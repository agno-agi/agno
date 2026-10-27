"""URL admission and scalar processing through the real knowledge HTTP routes."""

import hashlib
import json
import socket

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.os.routers.knowledge import knowledge as routes
from agno.utils.string import generate_id

A = "https://example.invalid/a"
B = "https://example.invalid/b"


class LocalReader(Reader):
    def __init__(self):
        super().__init__()
        self.calls = []

    @classmethod
    def get_supported_content_types(cls):
        return [ContentType.URL]

    def read(self, obj, name=None, password=None):
        self.calls.append(obj)
        if obj.endswith("/fail"):
            raise ValueError("offline reader failure")
        return [Document(content="local document", meta_data={"url": obj})]

    async def async_read(self, obj, name=None, password=None):
        return self.read(obj, name, password)


class LocalVectors:
    """Only the adapter boundary is fake; loader and status persistence execute."""

    embedder = None

    def __init__(self):
        self.rows = {}
        self.writes = 0

    def update_metadata(self, content_id, metadata):
        for documents in self.rows.values():
            for doc in documents:
                if doc.content_id == content_id:
                    doc.meta_data.update(metadata)

    def exists(self):
        return True

    def upsert_available(self):
        return False

    def content_hash_exists(self, content_hash, user_id=None):
        return (user_id, content_hash) in self.rows

    async def async_insert(self, content_hash, documents, filters=None, user_id=None):
        self.writes += 1
        for doc in documents:
            doc.embedding = [1.0, 0.0]
        self.rows[user_id, content_hash] = documents


@pytest.fixture
def local(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket, "create_connection", no_network)
    reader, vectors = LocalReader(), LocalVectors()
    kb = Knowledge(
        name="offline",
        contents_db=SqliteDb(db_file=str(tmp_path / "local.db")),
        vector_db=vectors,
        readers={"local": reader},
    )
    app = FastAPI()

    @app.middleware("http")
    async def scope(request, call_next):
        request.state.user_isolation_enabled = True
        request.state.user_id = request.headers.get("x-test-owner", "alice")
        return await call_next(request)

    app.include_router(routes.get_knowledge_router([kb]))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, kb, reader, vectors


@pytest.mark.parametrize("name", [None, "explicit"])
@pytest.mark.parametrize("value", [json.dumps([A]), json.dumps([A, B]), "[]", "{}", "true", "1", "null", '""', '"   "'])
def test_non_scalar_url_is_rejected_before_processing(local, name, value):
    client, kb, reader, vectors = local
    data = {"url": value, "reader_id": "local"}
    if name:
        data["name"] = name
    response = client.post("/knowledge/content", data=data)
    assert response.status_code == 400, response.text
    assert "single non-empty string" in response.json()["detail"]
    assert not reader.calls
    assert vectors.writes == 0
    assert kb.contents_db.get_knowledge_contents()[0] == []


@pytest.mark.parametrize("value", [A, json.dumps(A)])
def test_scalar_url_completes(local, value):
    client, kb, reader, vectors = local
    response = client.post("/knowledge/content", data={"url": value, "reader_id": "local"})
    assert response.status_code == 202, response.text
    status = client.get("/knowledge/content/" + response.json()["id"] + "/status")
    assert status.json()["status"] == "completed"
    assert reader.calls == [A]
    assert vectors.writes == 1


def test_scalar_identity_completion_dedup_and_owner(local):
    client, kb, reader, vectors = local

    def upload(owner="alice", **extra):
        response = client.post(
            "/knowledge/content", data={"url": A, "reader_id": "local", **extra}, headers={"x-test-owner": owner}
        )
        assert response.status_code == 202, response.text
        return response.json()["id"]

    first = upload()
    expected_hash = hashlib.sha256((hashlib.sha256(b"alice").hexdigest()[:16] + ":" + A + ":" + A).encode()).hexdigest()
    assert first == generate_id(expected_hash)
    assert upload() == first
    assert len(reader.calls) == vectors.writes == 1
    named = upload(name="named")
    other = upload("bob")
    assert len({first, named, other}) == 3
    assert vectors.writes == 3
    assert client.get(f"/knowledge/content/{first}/status").json()["status"] == "completed"
    assert client.get(f"/knowledge/content/{first}/status", headers={"x-test-owner": "bob"}).status_code == 404
    assert (
        client.get(f"/knowledge/content/{other}/status", headers={"x-test-owner": "bob"}).json()["status"]
        == "completed"
    )


def test_reader_failure_status(local):
    client, kb, reader, vectors = local
    response = client.post("/knowledge/content", data={"url": A + "/fail", "reader_id": "local"})
    assert response.status_code == 202
    status = client.get("/knowledge/content/" + response.json()["id"] + "/status")
    assert status.status_code == 200
    assert status.json()["status"] == "failed"
    assert "offline reader failure" in status.json()["status_message"]
    assert vectors.writes == 0


def test_remote_array_is_forwarded_unchanged(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from agno.remote.base import RemoteKnowledge

    remote_client = Mock()
    remote_client.upload_knowledge_content = AsyncMock(return_value={"id": "remote-id", "status": "processing"})
    app = FastAPI()
    app.include_router(routes.get_knowledge_router([RemoteKnowledge(client=remote_client)]))
    value = json.dumps([A, B])
    with TestClient(app) as client:
        response = client.post("/knowledge/content", data={"url": value})
    assert response.status_code == 202
    assert remote_client.upload_knowledge_content.call_args.kwargs["url"] == value
