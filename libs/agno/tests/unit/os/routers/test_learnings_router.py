"""Tests for the learnings REST API router."""

import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import BaseDb
from agno.os.routers.learnings import get_learnings_router
from agno.os.settings import AgnoAPISettings


def _make_learning(**overrides):
    now = int(time.time())
    d = {
        "learning_id": "lrn-1",
        "learning_type": "user_profile",
        "namespace": "global",
        "user_id": "user-1",
        "agent_id": None,
        "team_id": None,
        "session_id": None,
        "entity_id": None,
        "entity_type": None,
        "content": {"key": "value"},
        "metadata": None,
        "created_at": now,
        "updated_at": now,
    }
    d.update(overrides)
    return d


@pytest.fixture
def mock_db():
    db = MagicMock(spec=BaseDb)
    db.list_learnings = MagicMock(return_value=([], 0))
    db.get_learning_by_id = MagicMock(return_value=None)
    db.upsert_learning = MagicMock(return_value=None)
    db.delete_learning = MagicMock(return_value=True)
    return db


@pytest.fixture
def settings():
    return AgnoAPISettings()


@pytest.fixture
def client(mock_db, settings):
    app = FastAPI()
    router = get_learnings_router(dbs={"default": [mock_db]}, settings=settings)
    app.include_router(router)
    return TestClient(app)


class TestListLearnings:
    def test_empty(self, client, mock_db):
        resp = client.get("/learnings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["meta"]["total_count"] == 0

    def test_returns_records(self, client, mock_db):
        records = [_make_learning(learning_id="a"), _make_learning(learning_id="b")]
        mock_db.list_learnings = MagicMock(return_value=(records, 2))
        resp = client.get("/learnings")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert [r["learning_id"] for r in data] == ["a", "b"]

    def test_filters_passed_through(self, client, mock_db):
        client.get("/learnings?learning_type=user_profile&user_id=u1&namespace=global&page=2&limit=50")
        kwargs = mock_db.list_learnings.call_args[1]
        assert kwargs["learning_type"] == "user_profile"
        assert kwargs["user_id"] == "u1"
        assert kwargs["namespace"] == "global"
        assert kwargs["page"] == 2
        assert kwargs["limit"] == 50

    def test_pagination_meta(self, client, mock_db):
        mock_db.list_learnings = MagicMock(return_value=([_make_learning()], 25))
        resp = client.get("/learnings?limit=10")
        meta = resp.json()["meta"]
        assert meta["total_count"] == 25
        assert meta["total_pages"] == 3
        assert meta["limit"] == 10

    def test_not_implemented_returns_501(self, client, mock_db):
        mock_db.list_learnings.side_effect = NotImplementedError
        resp = client.get("/learnings")
        assert resp.status_code == 501


class TestCreateLearning:
    def test_create_success(self, client, mock_db):
        created = _make_learning(learning_id="new-id", content={"hello": "world"})
        mock_db.get_learning_by_id = MagicMock(return_value=created)
        resp = client.post(
            "/learnings",
            json={"learning_type": "user_profile", "content": {"hello": "world"}, "user_id": "user-1"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["learning_type"] == "user_profile"
        assert body["content"] == {"hello": "world"}
        assert mock_db.upsert_learning.called

    def test_create_missing_required_field(self, client):
        resp = client.post("/learnings", json={"content": {}})
        assert resp.status_code == 422

    def test_create_failure_when_get_returns_none(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=None)
        resp = client.post(
            "/learnings",
            json={"learning_type": "user_profile", "content": {}},
        )
        assert resp.status_code == 500


class TestGetLearning:
    def test_get_success(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(learning_id="lrn-9"))
        resp = client.get("/learnings/lrn-9")
        assert resp.status_code == 200
        assert resp.json()["learning_id"] == "lrn-9"

    def test_get_not_found(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=None)
        resp = client.get("/learnings/nope")
        assert resp.status_code == 404


class TestUpdateLearning:
    def test_update_replaces_content(self, client, mock_db):
        existing = _make_learning(content={"old": True})
        updated = _make_learning(content={"new": True})
        mock_db.get_learning_by_id = MagicMock(side_effect=[existing, updated])
        resp = client.patch("/learnings/lrn-1", json={"content": {"new": True}})
        assert resp.status_code == 200
        assert resp.json()["content"] == {"new": True}
        upsert_kwargs = mock_db.upsert_learning.call_args[1]
        assert upsert_kwargs["content"] == {"new": True}
        # Identity field is preserved from existing
        assert upsert_kwargs["user_id"] == existing["user_id"]
        assert upsert_kwargs["learning_type"] == existing["learning_type"]

    def test_update_not_found(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=None)
        resp = client.patch("/learnings/missing", json={"content": {}})
        assert resp.status_code == 404

    def test_update_no_op(self, client, mock_db):
        existing = _make_learning()
        mock_db.get_learning_by_id = MagicMock(return_value=existing)
        resp = client.patch("/learnings/lrn-1", json={})
        assert resp.status_code == 200
        mock_db.upsert_learning.assert_not_called()

    def test_update_rejects_null_content(self, client, mock_db):
        # content is NOT NULL in the underlying schema; explicit null would silently
        # fail at the DB level (the upsert swallows exceptions), so the router must reject it.
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning())
        resp = client.patch("/learnings/lrn-1", json={"content": None})
        assert resp.status_code == 422
        mock_db.upsert_learning.assert_not_called()

    def test_update_metadata_only_preserves_content(self, client, mock_db):
        existing = _make_learning(content={"keep": "this"})
        updated = _make_learning(content={"keep": "this"}, metadata={"new": "meta"})
        mock_db.get_learning_by_id = MagicMock(side_effect=[existing, updated])
        resp = client.patch("/learnings/lrn-1", json={"metadata": {"new": "meta"}})
        assert resp.status_code == 200
        upsert_kwargs = mock_db.upsert_learning.call_args[1]
        assert upsert_kwargs["content"] == {"keep": "this"}
        assert upsert_kwargs["metadata"] == {"new": "meta"}


class TestDeleteLearning:
    def test_delete_success(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning())
        resp = client.delete("/learnings/lrn-1")
        assert resp.status_code == 204
        mock_db.delete_learning.assert_called_once_with("lrn-1")

    def test_delete_not_found(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=None)
        resp = client.delete("/learnings/missing")
        assert resp.status_code == 404


class TestIDORScoping:
    """When a JWT subject is present on request.state, results are scoped to that user_id."""

    @pytest.fixture
    def jwt_app(self, mock_db, settings):
        app = FastAPI()

        @app.middleware("http")
        async def add_jwt_user(request, call_next):
            request.state.user_id = "user-A"
            return await call_next(request)

        router = get_learnings_router(dbs={"default": [mock_db]}, settings=settings)
        app.include_router(router)
        return app

    @pytest.fixture
    def jwt_client(self, jwt_app):
        return TestClient(jwt_app)

    def test_list_overrides_user_id(self, jwt_client, mock_db):
        jwt_client.get("/learnings?user_id=user-B")
        kwargs = mock_db.list_learnings.call_args[1]
        assert kwargs["user_id"] == "user-A"

    def test_create_overrides_user_id(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id="user-A"))
        jwt_client.post(
            "/learnings",
            json={"learning_type": "user_profile", "content": {}, "user_id": "user-B"},
        )
        kwargs = mock_db.upsert_learning.call_args[1]
        assert kwargs["user_id"] == "user-A"

    def test_get_other_users_record_returns_404(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id="user-B"))
        resp = jwt_client.get("/learnings/lrn-1")
        assert resp.status_code == 404

    def test_delete_other_users_record_returns_404(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id="user-B"))
        resp = jwt_client.delete("/learnings/lrn-1")
        assert resp.status_code == 404
        mock_db.delete_learning.assert_not_called()

    def test_patch_other_users_record_returns_404(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id="user-B"))
        resp = jwt_client.patch("/learnings/lrn-1", json={"content": {"x": 1}})
        assert resp.status_code == 404
