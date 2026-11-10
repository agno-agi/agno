"""Local upload admission rejects requests with no content source."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.knowledge.knowledge import Knowledge
from agno.os.routers.knowledge import knowledge as routes
from agno.remote.base import RemoteKnowledge


@pytest.fixture
def upload(monkeypatch):
    knowledge = Knowledge(name="upload-validation")
    process = AsyncMock()
    content_hash = Mock(wraps=knowledge._build_content_hash)
    monkeypatch.setattr(knowledge, "_build_content_hash", content_hash)
    monkeypatch.setattr(routes, "process_content", process)
    app = FastAPI()
    app.include_router(routes.get_knowledge_router([knowledge]))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, process, content_hash


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"name": "name-only"},
        {"description": "no source"},
        {"metadata": '{"tag":"test"}'},
        {"text_content": ""},
        {"url": " "},
        {"url": "null"},
        {"url": "[]"},
    ],
)
def test_missing_source_does_not_admit_background_work(upload, data):
    client, process, content_hash = upload
    response = client.post("/knowledge/content", data=data)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]
    content_hash.assert_not_called()
    process.assert_not_called()


@pytest.mark.parametrize(
    "data,files,expected_bytes,expected_url",
    [
        ({"text_content": "hello"}, None, b"hello", None),
        ({"text_content": " "}, None, b" ", None),
        ({}, {"file": ("note.txt", b"hello", "text/plain")}, b"hello", None),
        ({}, {"file": ("empty.txt", b"", "text/plain")}, b"", None),
        ({"url": "https://example.invalid/note"}, None, None, "https://example.invalid/note"),
        ({"url": '"https://example.invalid/note"'}, None, None, "https://example.invalid/note"),
    ],
)
def test_supported_sources_still_reach_processing(upload, data, files, expected_bytes, expected_url):
    client, process, content_hash = upload
    response = client.post("/knowledge/content", data=data, files=files)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "processing"
    content_hash.assert_called_once()
    process.assert_awaited_once()
    content = process.call_args.args[1]
    assert content.url == expected_url
    assert (content.file_data.content if content.file_data else None) == expected_bytes


def test_remote_upload_keeps_remote_validation(monkeypatch):
    remote_client = Mock()
    remote_client.upload_knowledge_content = AsyncMock(return_value={"id": "remote-id", "status": "processing"})
    remote = RemoteKnowledge(client=remote_client, knowledge_id="remote-kb")
    process = AsyncMock()
    monkeypatch.setattr(routes, "process_content", process)
    app = FastAPI()
    app.include_router(routes.get_knowledge_router([remote]))
    with TestClient(app) as client:
        response = client.post("/knowledge/content", data={"name": "remote"})
    assert response.status_code == 202, response.text
    remote_client.upload_knowledge_content.assert_awaited_once()
    assert remote_client.upload_knowledge_content.call_args.kwargs["name"] == "remote"
    process.assert_not_called()
