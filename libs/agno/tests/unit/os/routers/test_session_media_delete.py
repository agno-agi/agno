"""Unit tests for the media sweep on the session delete routes."""

import tempfile
import time
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.media import Image
from agno.media.storage.local import LocalMediaStorage
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession
from agno.utils.media_offload import offload_run_media

IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"payload" * 8


def _build_client(db, media_storage=None):
    from agno.os.routers.session.session import attach_routes

    app = FastAPI()
    router = APIRouter()
    attach_routes(router, {"default": [db]}, media_storage=media_storage)
    app.include_router(router)
    return TestClient(app)


def _seed(db, storage, session_id, user_id="u-1", content=IMAGE_BYTES):
    """Persist a session holding one run whose image has been offloaded to storage."""
    run = RunOutput(
        run_id=f"run-{session_id}",
        agent_id="a-1",
        session_id=session_id,
        user_id=user_id,
        status=RunStatus.completed,
        images=[Image(id=f"img-{session_id}", mime_type="image/png", content=content)],
    )
    offload_run_media(run, storage, session_id)
    now = int(time.time())
    db.upsert_session(
        AgentSession(
            session_id=session_id,
            agent_id="a-1",
            user_id=user_id,
            runs=[run],
            created_at=now,
            updated_at=now,
        )
    )
    return run.images[0].media_reference.storage_key


@pytest.fixture
def storage_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def _objects(storage_dir):
    return {p.name for p in Path(storage_dir).rglob("*") if p.is_file() and not p.name.endswith(".meta.json")}


def test_delete_media_removes_the_session_objects(storage_dir):
    storage = LocalMediaStorage(base_path=storage_dir)
    db = InMemoryDb()
    key = _seed(db, storage, "s-1")
    client = _build_client(db, storage)

    response = client.delete("/sessions/s-1?delete_media=true&user_id=u-1")

    assert response.status_code == 204
    assert storage.exists(key) is False
    assert _objects(storage_dir) == set()


def test_media_is_kept_unless_the_caller_asks(storage_dir):
    """Deleting a session leaves its objects behind by default; the sweep is opt-in."""
    storage = LocalMediaStorage(base_path=storage_dir)
    db = InMemoryDb()
    key = _seed(db, storage, "s-1")
    client = _build_client(db, storage)

    response = client.delete("/sessions/s-1?user_id=u-1")

    assert response.status_code == 204
    assert storage.exists(key) is True


def test_only_the_deleted_sessions_objects_are_swept(storage_dir):
    """The sweep is scoped to the session named in the request, not the whole bucket."""
    storage = LocalMediaStorage(base_path=storage_dir)
    db = InMemoryDb()
    doomed = _seed(db, storage, "s-1", content=IMAGE_BYTES)
    kept = _seed(db, storage, "s-2", content=IMAGE_BYTES + b"other")
    client = _build_client(db, storage)

    client.delete("/sessions/s-1?delete_media=true&user_id=u-1")

    assert storage.exists(doomed) is False
    assert storage.exists(kept) is True


def test_keys_are_read_before_the_rows_that_name_them(storage_dir):
    """The reference is the only record of which object belongs to which session, so a
    caller that deletes the rows first can never find the objects again."""
    order: list = []

    class RecordingStorage(LocalMediaStorage):
        def delete_many(self, storage_keys):
            order.append(("delete_media", list(storage_keys)))
            return super().delete_many(storage_keys)

    class RecordingDb(InMemoryDb):
        def delete_session(self, session_id, user_id=None):
            order.append(("delete_rows", session_id))
            return super().delete_session(session_id, user_id=user_id)

    storage = RecordingStorage(base_path=storage_dir)
    db = RecordingDb()
    key = _seed(db, storage, "s-1")
    client = _build_client(db, storage)

    client.delete("/sessions/s-1?delete_media=true&user_id=u-1")

    assert [step for step, _ in order] == ["delete_rows", "delete_media"]
    # The keys handed to storage were collected while the rows still existed.
    assert order[1][1] == [key]


def test_storage_failure_does_not_fail_the_request(storage_dir):
    """The rows are already gone by then, so answering an error would tell the caller
    nothing was deleted when in fact the session is."""

    class FailingStorage(LocalMediaStorage):
        def delete_many(self, storage_keys):
            raise RuntimeError("bucket unreachable")

    storage = FailingStorage(base_path=storage_dir)
    db = InMemoryDb()
    _seed(db, storage, "s-1")
    client = _build_client(db, storage)

    response = client.delete("/sessions/s-1?delete_media=true&user_id=u-1")

    assert response.status_code == 204
    assert db.get_session(session_id="s-1", user_id="u-1") is None


def test_delete_media_without_a_backend_is_refused(storage_dir):
    """Answering 204 would report objects deleted that nothing was configured to delete."""
    storage = LocalMediaStorage(base_path=storage_dir)
    db = InMemoryDb()
    key = _seed(db, storage, "s-1")
    client = _build_client(db, media_storage=None)

    response = client.delete("/sessions/s-1?delete_media=true&user_id=u-1")

    assert response.status_code == 503
    assert storage.exists(key) is True
    assert db.get_session(session_id="s-1", user_id="u-1") is not None


def test_bulk_delete_sweeps_every_named_session(storage_dir):
    storage = LocalMediaStorage(base_path=storage_dir)
    db = InMemoryDb()
    first = _seed(db, storage, "s-1", content=IMAGE_BYTES)
    second = _seed(db, storage, "s-2", content=IMAGE_BYTES + b"second")
    untouched = _seed(db, storage, "s-3", content=IMAGE_BYTES + b"third")
    client = _build_client(db, storage)

    response = client.request(
        "DELETE",
        "/sessions?delete_media=true&user_id=u-1",
        json={"session_ids": ["s-1", "s-2"], "session_types": ["agent", "agent"]},
    )

    assert response.status_code == 204
    assert storage.exists(first) is False
    assert storage.exists(second) is False
    assert storage.exists(untouched) is True


def test_bulk_delete_media_without_a_backend_is_refused(storage_dir):
    storage = LocalMediaStorage(base_path=storage_dir)
    db = InMemoryDb()
    key = _seed(db, storage, "s-1")
    client = _build_client(db, media_storage=None)

    response = client.request(
        "DELETE",
        "/sessions?delete_media=true&user_id=u-1",
        json={"session_ids": ["s-1"], "session_types": ["agent"]},
    )

    assert response.status_code == 503
    assert storage.exists(key) is True


def test_a_fork_does_not_delete_the_media_it_borrowed(storage_dir):
    """A fork copies the reference verbatim, so its sweep must leave the source's object alone."""
    import copy

    db = InMemoryDb()
    storage = LocalMediaStorage(base_path=storage_dir)
    key = _seed(db, storage, "source")

    source = db.get_session(session_id="source", user_id="u-1")
    forked_run = copy.deepcopy(source.runs[0])
    forked_run.run_id = "run-fork"
    forked_run.session_id = "fork"
    now = int(time.time())
    db.upsert_session(
        AgentSession(
            session_id="fork",
            agent_id="a-1",
            user_id="u-1",
            runs=[forked_run],
            created_at=now,
            updated_at=now,
        )
    )
    assert forked_run.images[0].media_reference.storage_key == key

    client = _build_client(db, media_storage=storage)
    assert client.delete("/sessions/fork?delete_media=true").status_code == 204

    assert _objects(storage_dir) == {Path(key).name}


def test_a_session_still_deletes_the_media_it_owns(storage_dir):
    db = InMemoryDb()
    storage = LocalMediaStorage(base_path=storage_dir)
    _seed(db, storage, "source")

    client = _build_client(db, media_storage=storage)
    assert client.delete("/sessions/source?delete_media=true").status_code == 204

    assert _objects(storage_dir) == set()


def test_a_delete_without_the_flag_hints_at_delete_media(storage_dir, monkeypatch):
    """The objects outlive the row by default, so the operator is told the flag that sweeps them exists."""
    from agno.os.routers.session import session as session_router

    messages: list = []
    monkeypatch.setattr(session_router, "log_debug", lambda msg, *a, **kw: messages.append(str(msg)))

    storage = LocalMediaStorage(base_path=storage_dir)
    db = InMemoryDb()
    _seed(db, storage, "s-1")
    _seed(db, storage, "s-2", content=IMAGE_BYTES + b"second")
    client = _build_client(db, storage)

    assert client.delete("/sessions/s-1?user_id=u-1").status_code == 204
    assert [m for m in messages if "pass delete_media=True" in m] == [
        "delete_media=False, keeping any offloaded media, pass delete_media=True to delete it too"
    ]

    messages.clear()
    assert client.delete("/sessions/s-2?delete_media=true&user_id=u-1").status_code == 204
    assert [m for m in messages if "pass delete_media=True" in m] == []


def test_a_bulk_delete_without_the_flag_hints_once(storage_dir, monkeypatch):
    """One request, one hint: repeating it per session id would drown the log on a bulk delete."""
    from agno.os.routers.session import session as session_router

    messages: list = []
    monkeypatch.setattr(session_router, "log_debug", lambda msg, *a, **kw: messages.append(str(msg)))

    storage = LocalMediaStorage(base_path=storage_dir)
    db = InMemoryDb()
    _seed(db, storage, "s-1")
    _seed(db, storage, "s-2", content=IMAGE_BYTES + b"second")
    client = _build_client(db, storage)

    response = client.request(
        "DELETE",
        "/sessions?user_id=u-1",
        json={"session_ids": ["s-1", "s-2"], "session_types": ["agent", "agent"]},
    )

    assert response.status_code == 204
    assert [m for m in messages if "pass delete_media=True" in m] == [
        "delete_media=False, keeping any offloaded media, pass delete_media=True to delete it too"
    ]
