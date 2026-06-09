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
    db.get_learnings_user_stats = MagicMock(return_value=([], 0))
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

    def test_default_sort_passed_through(self, client, mock_db):
        client.get("/learnings")
        kwargs = mock_db.list_learnings.call_args[1]
        assert kwargs["sort_by"] is None
        assert kwargs["sort_order"] == "desc"

    def test_sort_passed_through(self, client, mock_db):
        client.get("/learnings?sort_by=created_at&sort_order=asc")
        kwargs = mock_db.list_learnings.call_args[1]
        assert kwargs["sort_by"] == "created_at"
        assert kwargs["sort_order"] == "asc"

    def test_invalid_sort_order_rejected(self, client, mock_db):
        resp = client.get("/learnings?sort_order=sideways")
        assert resp.status_code == 422

    def test_table_without_db_id_rejected(self, client, mock_db):
        resp = client.get("/learnings?table=some_learnings")
        assert resp.status_code == 400


class TestListLearningUsers:
    def test_empty(self, client, mock_db):
        resp = client.get("/learnings/users")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["meta"]["total_count"] == 0

    def test_returns_user_stats(self, client, mock_db):
        stats = [
            {"user_id": "user-1", "last_learning_updated_at": 1714560000},
            {"user_id": "user-2", "last_learning_updated_at": 1714000000},
        ]
        mock_db.get_learnings_user_stats = MagicMock(return_value=(stats, 2))
        resp = client.get("/learnings/users")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert [r["user_id"] for r in data] == ["user-1", "user-2"]
        assert data[0]["last_learning_updated_at"] == 1714560000

    def test_does_not_collide_with_get_by_id(self, client, mock_db):
        # "/learnings/users" must route to the stats endpoint, not get_learning(learning_id="users")
        mock_db.get_learnings_user_stats = MagicMock(return_value=([], 0))
        resp = client.get("/learnings/users")
        assert resp.status_code == 200
        mock_db.get_learnings_user_stats.assert_called_once()
        mock_db.get_learning_by_id.assert_not_called()

    def test_filters_passed_through(self, client, mock_db):
        client.get("/learnings/users?learning_type=user_profile&user_id=u1&page=2&limit=5")
        kwargs = mock_db.get_learnings_user_stats.call_args[1]
        assert kwargs["learning_type"] == "user_profile"
        assert kwargs["user_id"] == "u1"
        assert kwargs["page"] == 2
        assert kwargs["limit"] == 5

    def test_pagination_meta(self, client, mock_db):
        stats = [{"user_id": "u", "last_learning_updated_at": 1}]
        mock_db.get_learnings_user_stats = MagicMock(return_value=(stats, 25))
        resp = client.get("/learnings/users?limit=10")
        meta = resp.json()["meta"]
        assert meta["total_count"] == 25
        assert meta["total_pages"] == 3

    def test_not_implemented_returns_501(self, client, mock_db):
        mock_db.get_learnings_user_stats.side_effect = NotImplementedError
        resp = client.get("/learnings/users")
        assert resp.status_code == 501

    def test_db_error_returns_500(self, client, mock_db):
        # The stats method surfaces DB errors (matching get_user_memory_stats); the
        # router converts them to a 500 rather than masking them as an empty page.
        mock_db.get_learnings_user_stats.side_effect = RuntimeError("boom")
        resp = client.get("/learnings/users")
        assert resp.status_code == 500

    def test_default_sort_passed_through(self, client, mock_db):
        client.get("/learnings/users")
        kwargs = mock_db.get_learnings_user_stats.call_args[1]
        assert kwargs["sort_by"] is None
        assert kwargs["sort_order"] == "desc"

    def test_sort_passed_through(self, client, mock_db):
        client.get("/learnings/users?sort_by=user_id&sort_order=asc")
        kwargs = mock_db.get_learnings_user_stats.call_args[1]
        assert kwargs["sort_by"] == "user_id"
        assert kwargs["sort_order"] == "asc"

    def test_table_without_db_id_rejected(self, client, mock_db):
        resp = client.get("/learnings/users?table=some_learnings")
        assert resp.status_code == 400


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

    def test_update_detects_concurrent_delete_and_rolls_back(self, client, mock_db):
        # Simulate: fetch returns existing, DELETE happens elsewhere, upsert re-inserts
        # the row (created_at advances because the INSERT branch ran), follow-up fetch
        # returns the freshly-created row. Router must detect this and 404 + clean up.
        existing = _make_learning(created_at=1000)
        recreated = _make_learning(created_at=5000)
        mock_db.get_learning_by_id = MagicMock(side_effect=[existing, recreated])
        resp = client.patch("/learnings/lrn-1", json={"content": {"x": 1}})
        assert resp.status_code == 404
        mock_db.delete_learning.assert_called_once_with("lrn-1")

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
    """When a JWT subject is present on request.state, the router enforces ownership-based scoping.

    Rules:
      - LIST: bind user_id filter to JWT subject; include records with user_id IS NULL
        (global / non-user-scoped); reject explicit user_id query that mismatches with 403.
      - CREATE: allow body.user_id to be null (global record) or match the JWT subject;
        reject mismatch with 403.
      - GET/PATCH/DELETE single record: allow if record.user_id is None (global); 404 on
        cross-user access (no 403 — avoids leaking existence).
    """

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

    def test_list_no_filter_binds_subject_with_global(self, jwt_client, mock_db):
        jwt_client.get("/learnings")
        kwargs = mock_db.list_learnings.call_args[1]
        assert kwargs["user_id"] == "user-A"
        assert kwargs["include_global"] is True

    def test_list_matching_user_id_allowed(self, jwt_client, mock_db):
        resp = jwt_client.get("/learnings?user_id=user-A")
        assert resp.status_code == 200
        kwargs = mock_db.list_learnings.call_args[1]
        assert kwargs["user_id"] == "user-A"
        assert kwargs["include_global"] is True

    def test_list_mismatched_user_id_rejected(self, jwt_client, mock_db):
        resp = jwt_client.get("/learnings?user_id=user-B")
        assert resp.status_code == 403
        mock_db.list_learnings.assert_not_called()

    def test_create_null_user_id_creates_global(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=None))
        resp = jwt_client.post(
            "/learnings",
            json={"learning_type": "agent_memory", "content": {"hello": "world"}, "agent_id": "ag-1"},
        )
        assert resp.status_code == 201
        kwargs = mock_db.upsert_learning.call_args[1]
        assert kwargs["user_id"] is None
        assert kwargs["agent_id"] == "ag-1"

    def test_create_matching_user_id_allowed(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id="user-A"))
        resp = jwt_client.post(
            "/learnings",
            json={"learning_type": "user_profile", "content": {}, "user_id": "user-A"},
        )
        assert resp.status_code == 201
        kwargs = mock_db.upsert_learning.call_args[1]
        assert kwargs["user_id"] == "user-A"

    def test_create_mismatched_user_id_rejected(self, jwt_client, mock_db):
        resp = jwt_client.post(
            "/learnings",
            json={"learning_type": "user_profile", "content": {}, "user_id": "user-B"},
        )
        assert resp.status_code == 403
        mock_db.upsert_learning.assert_not_called()

    def test_get_global_record_accessible(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=None, agent_id="ag-1"))
        resp = jwt_client.get("/learnings/lrn-1")
        assert resp.status_code == 200
        assert resp.json()["user_id"] is None

    def test_patch_global_record_accessible(self, jwt_client, mock_db):
        existing = _make_learning(user_id=None, agent_id="ag-1")
        updated = _make_learning(user_id=None, agent_id="ag-1", content={"new": True})
        mock_db.get_learning_by_id = MagicMock(side_effect=[existing, updated])
        resp = jwt_client.patch("/learnings/lrn-1", json={"content": {"new": True}})
        assert resp.status_code == 200

    def test_delete_global_record_accessible(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=None))
        resp = jwt_client.delete("/learnings/lrn-1")
        assert resp.status_code == 204

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

    def test_list_users_binds_subject(self, jwt_client, mock_db):
        jwt_client.get("/learnings/users")
        kwargs = mock_db.get_learnings_user_stats.call_args[1]
        assert kwargs["user_id"] == "user-A"

    def test_list_users_matching_user_id_allowed(self, jwt_client, mock_db):
        resp = jwt_client.get("/learnings/users?user_id=user-A")
        assert resp.status_code == 200
        kwargs = mock_db.get_learnings_user_stats.call_args[1]
        assert kwargs["user_id"] == "user-A"

    def test_list_users_mismatched_user_id_rejected(self, jwt_client, mock_db):
        resp = jwt_client.get("/learnings/users?user_id=user-B")
        assert resp.status_code == 403
        mock_db.get_learnings_user_stats.assert_not_called()
