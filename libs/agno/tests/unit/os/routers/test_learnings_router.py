"""Tests for the learnings REST API router."""

import time
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import BaseDb
from agno.learn.utils import _user_key_segment, build_learning_id
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
    db.update_learning = MagicMock(return_value=True)
    db.delete_learning = MagicMock(return_value=True)
    db.delete_user_learnings = MagicMock(return_value=3)
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

    def test_db_error_returns_500(self, client, mock_db):
        # A DB error must surface as 500, not a misleading empty 200 page.
        mock_db.list_learnings.side_effect = RuntimeError("boom")
        resp = client.get("/learnings")
        assert resp.status_code == 500

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
    def test_create_uses_deterministic_id_for_identity_keyed_type(self, client, mock_db):
        created = _make_learning(learning_id="user_profile_user-1", content={"hello": "world"})
        # existence check -> None (not present), then readback -> created
        mock_db.get_learning_by_id = MagicMock(side_effect=[None, created])
        resp = client.post(
            "/learnings",
            json={"learning_type": "user_profile", "content": {"hello": "world"}, "user_id": "user-1"},
        )
        assert resp.status_code == 201
        assert resp.json()["learning_id"] == "user_profile_user-1"
        # Persisted under the deterministic id (reconciles with the agent's store), not a uuid.
        assert mock_db.upsert_learning.call_args[1]["id"] == "user_profile_user-1"

    def test_create_conflict_when_identity_record_exists(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(learning_id="user_profile_user-1"))
        resp = client.post(
            "/learnings",
            json={"learning_type": "user_profile", "content": {}, "user_id": "user-1"},
        )
        assert resp.status_code == 409
        mock_db.upsert_learning.assert_not_called()

    def test_create_identity_type_missing_field_is_422(self, client, mock_db):
        # user_profile is keyed by user_id; without it the id can't be derived -> reject.
        resp = client.post("/learnings", json={"learning_type": "user_profile", "content": {}})
        assert resp.status_code == 422
        mock_db.upsert_learning.assert_not_called()

    def test_create_generated_id_for_non_identity_type(self, client, mock_db):
        created = _make_learning(learning_id="generated", learning_type="decision_log")
        mock_db.get_learning_by_id = MagicMock(return_value=created)
        resp = client.post(
            "/learnings",
            json={"learning_type": "decision_log", "content": {"d": 1}, "user_id": "user-1"},
        )
        assert resp.status_code == 201
        # decision_log uses a generated uuid; no existence pre-check (only the readback call).
        assert mock_db.upsert_learning.called
        upsert_id = mock_db.upsert_learning.call_args[1]["id"]
        assert upsert_id not in ("decision_log_user-1",) and len(upsert_id) == 36

    def test_create_missing_learning_type_is_422(self, client):
        resp = client.post("/learnings", json={"content": {}})
        assert resp.status_code == 422

    def test_create_entity_user_namespace_without_user_id_is_422(self, client, mock_db):
        # The entity key embeds the user under namespace="user"; without a
        # user_id no id can be derived and the row would be unreachable.
        resp = client.post(
            "/learnings",
            json={
                "learning_type": "entity_memory",
                "content": {},
                "entity_id": "acme",
                "entity_type": "company",
                "namespace": "user",
            },
        )
        assert resp.status_code == 422
        mock_db.upsert_learning.assert_not_called()

    def test_create_entity_user_namespace_422_names_user_id(self, client, mock_db):
        # The caller supplied both entity fields, so the generic "provide the required
        # field(s)" wording reads as already satisfied; the message has to say user_id.
        resp = client.post(
            "/learnings",
            json={
                "learning_type": "entity_memory",
                "content": {},
                "entity_id": "acme",
                "entity_type": "company",
                "namespace": "user",
            },
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "user_id" in detail
        assert 'namespace="user"' in detail

    def test_create_entity_defaults_stored_namespace_to_global(self, client, mock_db):
        # The derived key defaults a missing namespace to "global"; the stored
        # column must agree or the store's namespace-filtered reads never find
        # the row.
        created = _make_learning(
            learning_id="entity_global_company_acme",
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
        )
        mock_db.get_learning_by_id = MagicMock(side_effect=[None, created])
        resp = client.post(
            "/learnings",
            json={
                "learning_type": "entity_memory",
                "content": {},
                "entity_id": "acme",
                "entity_type": "company",
            },
        )
        assert resp.status_code == 201
        kwargs = mock_db.upsert_learning.call_args[1]
        assert kwargs["id"] == "entity_global_company_acme"
        assert kwargs["namespace"] == "global"

    def test_create_entity_empty_namespace_defaults_to_global(self, client, mock_db):
        # The derived key treats any falsy namespace as "global", so an empty string
        # must land in the column as "global" too -- storing "" would key the row
        # global while filtering it under "", which no read ever asks for.
        created = _make_learning(
            learning_id="entity_global_company_acme",
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
        )
        mock_db.get_learning_by_id = MagicMock(side_effect=[None, created])
        resp = client.post(
            "/learnings",
            json={
                "learning_type": "entity_memory",
                "content": {},
                "entity_id": "acme",
                "entity_type": "company",
                "namespace": "",
            },
        )
        assert resp.status_code == 201
        kwargs = mock_db.upsert_learning.call_args[1]
        assert kwargs["namespace"] == "global"
        assert kwargs["id"] == build_learning_id("entity_memory", entity_id="acme", entity_type="company", namespace="")

    def test_create_entity_rejects_digest_shaped_namespace(self, client, mock_db):
        # "user_<16 hex>" reaches the generic branch of the key builder and
        # reproduces the victim's namespace="user" key byte for byte.
        forged_namespace = "user_" + _user_key_segment("victim")
        assert build_learning_id(
            "entity_memory", entity_id="acme", entity_type="company", namespace=forged_namespace
        ) == build_learning_id(
            "entity_memory", user_id="victim", entity_id="acme", entity_type="company", namespace="user"
        )
        resp = client.post(
            "/learnings",
            json={
                "learning_type": "entity_memory",
                "content": {"stolen": True},
                "entity_id": "acme",
                "entity_type": "company",
                "namespace": forged_namespace,
            },
        )
        assert resp.status_code == 422
        assert "reserved" in resp.json()["detail"]
        mock_db.upsert_learning.assert_not_called()

    @pytest.mark.parametrize(
        "namespace",
        [
            "user_team",
            "user_c6c289e49e9c05",
            "user_C6C289E49E9C05B2",
            "user_c6c289e49e9c05b2x",
            "global",
            "workspace",
        ],
    )
    def test_create_entity_allows_ordinary_namespaces(self, client, mock_db, namespace):
        # Only the exact digest shape is reserved; anything else is a custom
        # namespace and keeps working.
        expected_id = build_learning_id("entity_memory", entity_id="acme", entity_type="company", namespace=namespace)
        created = _make_learning(
            learning_id=expected_id,
            learning_type="entity_memory",
            namespace=namespace,
            entity_id="acme",
            entity_type="company",
        )
        mock_db.get_learning_by_id = MagicMock(side_effect=[None, created])
        resp = client.post(
            "/learnings",
            json={
                "learning_type": "entity_memory",
                "content": {},
                "entity_id": "acme",
                "entity_type": "company",
                "namespace": namespace,
            },
        )
        assert resp.status_code == 201
        kwargs = mock_db.upsert_learning.call_args[1]
        assert kwargs["id"] == expected_id
        assert kwargs["namespace"] == namespace

    def test_create_failure_when_get_returns_none(self, client, mock_db):
        # identity record absent (None on existence) and readback also None -> 500
        mock_db.get_learning_by_id = MagicMock(side_effect=[None, None])
        resp = client.post(
            "/learnings",
            json={"learning_type": "user_profile", "content": {}, "user_id": "user-1"},
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

    def test_db_error_returns_500_not_404(self, client, mock_db):
        # A DB error is not "not found" -- surface it as 500, not a misleading 404.
        mock_db.get_learning_by_id = MagicMock(side_effect=RuntimeError("boom"))
        resp = client.get("/learnings/lrn-1")
        assert resp.status_code == 500


class TestUpdateLearning:
    def test_update_replaces_content(self, client, mock_db):
        existing = _make_learning(content={"old": True})
        updated = _make_learning(content={"new": True})
        # fetch (scope) then re-read (response)
        mock_db.get_learning_by_id = MagicMock(side_effect=[existing, updated])
        resp = client.patch("/learnings/lrn-1", json={"content": {"new": True}})
        assert resp.status_code == 200
        assert resp.json()["content"] == {"new": True}
        # update-only: no upsert (no insert) -> no resurrection/destruction
        mock_db.upsert_learning.assert_not_called()
        assert mock_db.update_learning.call_args[0][0] == "lrn-1"
        assert mock_db.update_learning.call_args[1]["content"] == {"new": True}

    def test_update_not_found(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=None)
        resp = client.patch("/learnings/missing", json={"content": {}})
        assert resp.status_code == 404

    def test_update_no_op(self, client, mock_db):
        existing = _make_learning()
        mock_db.get_learning_by_id = MagicMock(return_value=existing)
        resp = client.patch("/learnings/lrn-1", json={})
        assert resp.status_code == 200
        mock_db.update_learning.assert_not_called()

    def test_update_rejects_null_content(self, client, mock_db):
        # content is NOT NULL in the underlying schema; reject an explicit null.
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning())
        resp = client.patch("/learnings/lrn-1", json={"content": None})
        assert resp.status_code == 422
        mock_db.update_learning.assert_not_called()

    def test_update_concurrent_delete_returns_404_without_destroying(self, client, mock_db):
        # The row is deleted between our fetch and the update. update_learning never inserts,
        # so it matches nothing -> 404. Crucially the router must NOT delete anything (the old
        # TOCTOU guard used to delete the row, destroying a concurrent agent re-create).
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning())
        mock_db.update_learning = MagicMock(return_value=False)  # no row matched
        resp = client.patch("/learnings/lrn-1", json={"content": {"x": 1}})
        assert resp.status_code == 404
        mock_db.delete_learning.assert_not_called()

    def test_update_metadata_only_replaces_content_from_fetch(self, client, mock_db):
        existing = _make_learning(content={"keep": "this"})
        updated = _make_learning(content={"keep": "this"}, metadata={"new": "meta"})
        mock_db.get_learning_by_id = MagicMock(side_effect=[existing, updated])
        resp = client.patch("/learnings/lrn-1", json={"metadata": {"new": "meta"}})
        assert resp.status_code == 200
        kwargs = mock_db.update_learning.call_args[1]
        assert kwargs["content"] == {"keep": "this"}
        assert kwargs["metadata"] == {"new": "meta"}

    def test_update_db_error_returns_500(self, client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning())
        mock_db.update_learning = MagicMock(side_effect=RuntimeError("boom"))
        resp = client.patch("/learnings/lrn-1", json={"content": {"x": 1}})
        assert resp.status_code == 500


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


class TestDeleteLearningUser:
    def test_delete_success_all_types(self, client, mock_db):
        resp = client.delete("/learnings/users/user-1")
        assert resp.status_code == 204
        mock_db.delete_user_learnings.assert_called_once_with("user-1", learning_type=None)

    def test_delete_scoped_to_learning_type(self, client, mock_db):
        resp = client.delete("/learnings/users/user-1?learning_type=user_memory")
        assert resp.status_code == 204
        mock_db.delete_user_learnings.assert_called_once_with("user-1", learning_type="user_memory")

    def test_delete_with_no_records_still_204(self, client, mock_db):
        mock_db.delete_user_learnings = MagicMock(return_value=0)
        resp = client.delete("/learnings/users/nobody")
        assert resp.status_code == 204

    def test_does_not_collide_with_delete_by_id(self, client, mock_db):
        # "/learnings/users/{user_id}" must route to the bulk-by-user handler,
        # not delete_learning(learning_id="users").
        client.delete("/learnings/users/user-1")
        mock_db.delete_user_learnings.assert_called_once_with("user-1", learning_type=None)
        mock_db.delete_learning.assert_not_called()

    def test_not_implemented_returns_501(self, client, mock_db):
        mock_db.delete_user_learnings.side_effect = NotImplementedError
        resp = client.delete("/learnings/users/user-1")
        assert resp.status_code == 501

    def test_db_error_returns_500_not_false_204(self, client, mock_db):
        # The destructive bulk delete must NOT report success when the DB call fails.
        mock_db.delete_user_learnings.side_effect = RuntimeError("boom")
        resp = client.delete("/learnings/users/user-1")
        assert resp.status_code == 500


class TestIDORScoping:
    """For a scoped (non-admin) JWT caller with user_isolation enabled, the router enforces
    ownership-based scoping via get_scoped_user_id.

    Rules:
      - LIST: bind user_id filter to the subject; include records with user_id IS NULL
        (global / non-user-scoped); reject explicit user_id query that mismatches with 403.
      - CREATE: allow body.user_id to be null (global record) or match the subject;
        reject mismatch with 403.
      - GET/PATCH/DELETE single record: allow if record.user_id is None (global); 404 on
        cross-user access (no 403 — avoids leaking existence).
    """

    @pytest.fixture
    def jwt_app(self, mock_db, settings):
        app = FastAPI()

        @app.middleware("http")
        async def add_jwt_user(request, call_next):
            # Regular (non-admin) user with user isolation enabled.
            request.state.user_isolation_enabled = True
            request.state.user_id = "user-A"
            request.state.scopes = []
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
        # existence check -> None (not present), then readback -> created
        mock_db.get_learning_by_id = MagicMock(side_effect=[None, _make_learning(user_id="user-A")])
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
        # Reads of null-owner (shared) records remain open to any authenticated caller.
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=None, agent_id="ag-1"))
        resp = jwt_client.get("/learnings/lrn-1")
        assert resp.status_code == 200
        assert resp.json()["user_id"] is None

    def test_patch_global_record_forbidden_for_non_admin(self, jwt_client, mock_db):
        # Mutating a null-owner record is admin-only.
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=None, agent_id="ag-1"))
        resp = jwt_client.patch("/learnings/lrn-1", json={"content": {"new": True}})
        assert resp.status_code == 403
        mock_db.update_learning.assert_not_called()

    def test_delete_global_record_forbidden_for_non_admin(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=None))
        resp = jwt_client.delete("/learnings/lrn-1")
        assert resp.status_code == 403
        mock_db.delete_learning.assert_not_called()

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

    def test_delete_own_user_allowed(self, jwt_client, mock_db):
        resp = jwt_client.delete("/learnings/users/user-A")
        assert resp.status_code == 204
        mock_db.delete_user_learnings.assert_called_once_with("user-A", learning_type=None)

    def test_delete_other_user_rejected(self, jwt_client, mock_db):
        resp = jwt_client.delete("/learnings/users/user-B")
        assert resp.status_code == 403
        mock_db.delete_user_learnings.assert_not_called()


class TestNonStringOwnerScoping:
    """Owner ids are compared as strings, because only the SQL adapters type the user_id
    column and coerce on write -- MongoDb, AsyncMongoDb and ValkeyDb store whatever the
    writer passed, so an agent that ran with a non-string user_id leaves a non-string in
    that column while the request always carries the JWT subject string.

    An id that is genuinely someone else's is still 404, and None still owns nothing.
    """

    @pytest.fixture
    def jwt_client(self, mock_db, settings):
        # Regular (non-admin) user with user isolation enabled; JWT subject "123".
        return _scoped_client(mock_db, settings, user_isolation_enabled=True, user_id="123", scopes=[])

    def test_get_own_string_owned_record(self, jwt_client, mock_db):
        # False-refusal guard: the ordinary string-owned record must stay reachable.
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id="123"))
        assert jwt_client.get("/learnings/lrn-1").status_code == 200

    def test_get_own_int_owned_record(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=123))
        resp = jwt_client.get("/learnings/lrn-1")
        assert resp.status_code == 200
        assert resp.json()["learning_id"] == "lrn-1"

    def test_patch_own_int_owned_record(self, jwt_client, mock_db):
        existing = _make_learning(user_id=123)
        updated = _make_learning(user_id=123, content={"new": True})
        mock_db.get_learning_by_id = MagicMock(side_effect=[existing, updated])
        resp = jwt_client.patch("/learnings/lrn-1", json={"content": {"new": True}})
        assert resp.status_code == 200
        assert mock_db.update_learning.call_args[1]["content"] == {"new": True}

    def test_delete_own_int_owned_record(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=123))
        assert jwt_client.delete("/learnings/lrn-1").status_code == 204
        mock_db.delete_learning.assert_called_once_with("lrn-1")

    def test_get_own_uuid_owned_record(self, mock_db, settings):
        owner = UUID("2f8a1b7c-0d3e-4f5a-9b6c-7d8e9f0a1b2c")
        client = _scoped_client(mock_db, settings, user_isolation_enabled=True, user_id=str(owner), scopes=[])
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=owner))
        assert client.get("/learnings/lrn-1").status_code == 200

    def test_other_users_int_owned_record_still_404(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=456))
        assert jwt_client.get("/learnings/lrn-1").status_code == 404

    def test_other_users_int_owned_record_not_mutable(self, jwt_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=456))
        assert jwt_client.patch("/learnings/lrn-1", json={"content": {"x": 1}}).status_code == 404
        mock_db.update_learning.assert_not_called()

        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=456))
        assert jwt_client.delete("/learnings/lrn-1").status_code == 404
        mock_db.delete_learning.assert_not_called()

    def test_prefix_of_the_subject_is_not_the_owner(self, jwt_client, mock_db):
        # Coercion is str(), not a substring or numeric comparison.
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=12))
        assert jwt_client.get("/learnings/lrn-1").status_code == 404

    def test_non_string_subject_reaches_a_string_owned_record(self, mock_db, settings):
        # The same coercion in the other direction: the subject claim carries the non-string.
        client = _scoped_client(mock_db, settings, user_isolation_enabled=True, user_id=123, scopes=[])
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id="123"))
        assert client.get("/learnings/lrn-1").status_code == 200

    def test_non_string_subject_still_404s_on_another_owner(self, mock_db, settings):
        client = _scoped_client(mock_db, settings, user_isolation_enabled=True, user_id=123, scopes=[])
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id="456"))
        assert client.get("/learnings/lrn-1").status_code == 404

    def test_null_owner_record_unchanged(self, jwt_client, mock_db):
        # None is "no owner": readable by any caller, mutable only by an admin.
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=None))
        assert jwt_client.get("/learnings/lrn-1").status_code == 200

        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=None))
        assert jwt_client.patch("/learnings/lrn-1", json={"content": {"x": 1}}).status_code == 403

        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=None))
        assert jwt_client.delete("/learnings/lrn-1").status_code == 403

    def test_caller_without_identity_never_matches_a_record(self, mock_db, settings):
        # Isolation on with no subject fails closed at get_scoped_user_id (403), so a
        # null-identity caller never reaches a record, matching or not.
        client = _scoped_client(mock_db, settings, user_isolation_enabled=True, user_id=None, scopes=[])
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=None))
        assert client.get("/learnings/lrn-1").status_code == 403

    def test_admin_unchanged_for_int_owned_record(self, mock_db, settings):
        client = _scoped_client(
            mock_db, settings, user_isolation_enabled=True, user_id="admin-1", scopes=["agent_os:admin"]
        )
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=456))
        assert client.get("/learnings/lrn-1").status_code == 200

    def test_isolation_off_unchanged_for_int_owned_record(self, mock_db, settings):
        client = _scoped_client(mock_db, settings, user_isolation_enabled=False, user_id="123", scopes=[])
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=456))
        assert client.get("/learnings/lrn-1").status_code == 200

    def test_explicit_user_id_guards_still_reject_a_different_user(self, jwt_client, mock_db):
        # The collection guards compare two request-supplied values and are untouched.
        assert jwt_client.get("/learnings?user_id=456").status_code == 403
        assert jwt_client.get("/learnings/users?user_id=456").status_code == 403
        assert jwt_client.delete("/learnings/users/456").status_code == 403
        assert (
            jwt_client.post(
                "/learnings", json={"learning_type": "user_profile", "content": {}, "user_id": "456"}
            ).status_code
            == 403
        )
        mock_db.delete_user_learnings.assert_not_called()
        mock_db.upsert_learning.assert_not_called()

    def test_create_body_user_id_must_still_be_a_string(self, jwt_client, mock_db):
        # Request-side strictness is unchanged: the body is validated before the guard runs.
        resp = jwt_client.post("/learnings", json={"learning_type": "user_profile", "content": {}, "user_id": 123})
        assert resp.status_code == 422
        mock_db.upsert_learning.assert_not_called()

    def test_list_renders_an_int_owner(self, mock_db, settings):
        # A non-string owner in the page must not fail the whole response.
        client = _scoped_client(
            mock_db, settings, user_isolation_enabled=True, user_id="admin-1", scopes=["agent_os:admin"]
        )
        mock_db.list_learnings = MagicMock(return_value=([_make_learning(user_id=123)], 1))
        resp = client.get("/learnings")
        assert resp.status_code == 200
        assert resp.json()["data"][0]["user_id"] == "123"

    def test_list_users_renders_an_int_owner(self, mock_db, settings):
        client = _scoped_client(
            mock_db, settings, user_isolation_enabled=True, user_id="admin-1", scopes=["agent_os:admin"]
        )
        mock_db.get_learnings_user_stats = MagicMock(
            return_value=([{"user_id": 123, "last_learning_updated_at": 5}], 1)
        )
        resp = client.get("/learnings/users")
        assert resp.status_code == 200
        assert resp.json()["data"][0]["user_id"] == "123"


def _scoped_client(mock_db, settings, **state):
    """Build a TestClient whose middleware stamps the given request.state attrs."""
    app = FastAPI()

    @app.middleware("http")
    async def add_state(request, call_next):
        for k, v in state.items():
            setattr(request.state, k, v)
        return await call_next(request)

    app.include_router(get_learnings_router(dbs={"default": [mock_db]}, settings=settings))
    return TestClient(app)


class TestAdminAndUnscopedAccess:
    """get_scoped_user_id returns None for admins and when user_isolation is off, so those
    callers are NOT bound to their own user_id -- this is what lets /learnings/users report
    the real user count (not always 1) and keeps admins from being locked out."""

    @pytest.fixture
    def admin_client(self, mock_db, settings):
        # Admin: isolation enabled but the caller carries the admin scope.
        return _scoped_client(
            mock_db, settings, user_isolation_enabled=True, user_id="admin-1", scopes=["agent_os:admin"]
        )

    @pytest.fixture
    def isolation_off_client(self, mock_db, settings):
        # JWT subject present but user isolation is disabled (the opt-in flag is off).
        return _scoped_client(mock_db, settings, user_isolation_enabled=False, user_id="user-A", scopes=[])

    def test_admin_list_users_sees_all(self, admin_client, mock_db):
        stats = [
            {"user_id": "u1", "last_learning_updated_at": 3},
            {"user_id": "u2", "last_learning_updated_at": 2},
            {"user_id": "u3", "last_learning_updated_at": 1},
        ]
        mock_db.get_learnings_user_stats = MagicMock(return_value=(stats, 3))
        resp = admin_client.get("/learnings/users")
        assert resp.status_code == 200
        # Not bound to the admin's own id -> queries across all users -> total_count > 1.
        assert mock_db.get_learnings_user_stats.call_args[1]["user_id"] is None
        assert resp.json()["meta"]["total_count"] == 3

    def test_admin_list_users_can_filter_any_user(self, admin_client, mock_db):
        resp = admin_client.get("/learnings/users?user_id=user-B")
        assert resp.status_code == 200
        assert mock_db.get_learnings_user_stats.call_args[1]["user_id"] == "user-B"

    def test_admin_list_learnings_not_scoped(self, admin_client, mock_db):
        admin_client.get("/learnings")
        kwargs = mock_db.list_learnings.call_args[1]
        assert kwargs["user_id"] is None
        assert kwargs["include_global"] is False

    def test_admin_can_access_other_users_record(self, admin_client, mock_db):
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id="user-B"))
        resp = admin_client.get("/learnings/lrn-1")
        assert resp.status_code == 200

    def test_admin_can_delete_another_users_learnings(self, admin_client, mock_db):
        resp = admin_client.delete("/learnings/users/user-B")
        assert resp.status_code == 204
        mock_db.delete_user_learnings.assert_called_once_with("user-B", learning_type=None)

    def test_admin_can_mutate_null_owner_record(self, admin_client, mock_db):
        # Mutating a null-owner (shared) record is allowed for admins.
        existing = _make_learning(user_id=None, agent_id="ag-1")
        updated = _make_learning(user_id=None, agent_id="ag-1", content={"new": True})
        mock_db.get_learning_by_id = MagicMock(side_effect=[existing, updated])
        assert admin_client.patch("/learnings/lrn-1", json={"content": {"new": True}}).status_code == 200

        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id=None))
        assert admin_client.delete("/learnings/lrn-1").status_code == 204

    def test_isolation_off_is_unscoped(self, isolation_off_client, mock_db):
        # Even with a JWT subject, isolation-off means no per-user binding.
        isolation_off_client.get("/learnings/users")
        assert mock_db.get_learnings_user_stats.call_args[1]["user_id"] is None
        # And a cross-user single record is accessible (no 404).
        mock_db.get_learning_by_id = MagicMock(return_value=_make_learning(user_id="user-B"))
        assert isolation_off_client.get("/learnings/lrn-1").status_code == 200


class TestCreateEntityReservedNamespaceSegments:
    """The reserved namespace shape is the user digest plus any trailing segments, so an
    entity_memory namespace can never absorb part of another user's key and re-split into it."""

    @pytest.fixture
    def scoped_client(self, mock_db, settings):
        app = FastAPI()

        @app.middleware("http")
        async def add_jwt_user(request, call_next):
            # Regular (non-admin) user with user isolation enabled.
            request.state.user_isolation_enabled = True
            request.state.user_id = "attacker"
            request.state.scopes = []
            return await call_next(request)

        router = get_learnings_router(dbs={"default": [mock_db]}, settings=settings)
        app.include_router(router)
        return TestClient(app)

    def test_create_entity_rejects_namespace_that_absorbs_the_entity_type_segment(self, client, mock_db):
        # The key is "entity_<namespace>_<entity_type>_<entity_id>" by plain interpolation and
        # entity ids are slugs ("Acme Corp" -> "acme_corp"), so an entity id holding an
        # underscore lets a namespace of "user_<digest>_<entity_type>" move every split one
        # segment right and land on the victim's namespace="user" key.
        victim_key = build_learning_id(
            "entity_memory",
            user_id="victim",
            entity_id="acme_corp",
            entity_type="company",
            namespace="user",
        )
        forged_namespace = "user_" + _user_key_segment("victim") + "_company"
        assert (
            build_learning_id("entity_memory", entity_id="corp", entity_type="acme", namespace=forged_namespace)
            == victim_key
        )
        # Seeded so that a create reaching the db would answer 201 with the victim's row.
        mock_db.get_learning_by_id = MagicMock(
            side_effect=[None, _make_learning(learning_id=victim_key, learning_type="entity_memory")]
        )
        resp = client.post(
            "/learnings",
            json={
                "learning_type": "entity_memory",
                "content": {"stolen": True},
                "entity_id": "corp",
                "entity_type": "acme",
                "namespace": forged_namespace,
            },
        )
        mock_db.upsert_learning.assert_not_called()
        assert resp.status_code == 422
        assert "reserved" in resp.json()["detail"]

    def test_create_entity_rejects_namespace_that_absorbs_several_segments(self, client, mock_db):
        # A longer victim slug ("Acme Corp Holdings") gives the namespace more segments to
        # swallow; the shift is bounded only by the underscore count in the entity id.
        victim_key = build_learning_id(
            "entity_memory",
            user_id="victim",
            entity_id="acme_corp_holdings",
            entity_type="company",
            namespace="user",
        )
        forged_namespace = "user_" + _user_key_segment("victim") + "_company_acme"
        assert (
            build_learning_id("entity_memory", entity_id="holdings", entity_type="corp", namespace=forged_namespace)
            == victim_key
        )
        mock_db.get_learning_by_id = MagicMock(
            side_effect=[None, _make_learning(learning_id=victim_key, learning_type="entity_memory")]
        )
        resp = client.post(
            "/learnings",
            json={
                "learning_type": "entity_memory",
                "content": {"stolen": True},
                "entity_id": "holdings",
                "entity_type": "corp",
                "namespace": forged_namespace,
            },
        )
        mock_db.upsert_learning.assert_not_called()
        assert resp.status_code == 422
        assert "reserved" in resp.json()["detail"]

    def test_create_entity_rejects_bare_digest_and_every_trailing_segment_form(self, client, mock_db):
        # The bare digest and the digest carrying any suffix are one reserved family: each
        # interpolates into a key that opens on some user's digest.
        digest = _user_key_segment("victim")
        for namespace in (
            "user_" + digest,
            "user_" + digest + "_",
            "user_" + digest + "_company",
            "user_" + digest + "_company_acme",
        ):
            mock_db.upsert_learning.reset_mock()
            mock_db.get_learning_by_id = MagicMock(
                side_effect=[None, _make_learning(learning_type="entity_memory", namespace=namespace)]
            )
            resp = client.post(
                "/learnings",
                json={
                    "learning_type": "entity_memory",
                    "content": {},
                    "entity_id": "corp",
                    "entity_type": "acme",
                    "namespace": namespace,
                },
            )
            mock_db.upsert_learning.assert_not_called()
            assert resp.status_code == 422, namespace
            assert "reserved" in resp.json()["detail"], namespace

    def test_scoped_caller_cannot_reach_another_users_entity_key_via_namespace(self, scoped_client, mock_db):
        # body.user_id names the caller, so the ownership check passes; namespace is the only
        # remaining field that can carry another user's digest into the derived id.
        victim_key = build_learning_id(
            "entity_memory",
            user_id="victim",
            entity_id="acme_corp",
            entity_type="company",
            namespace="user",
        )
        forged_namespace = "user_" + _user_key_segment("victim") + "_company"
        mock_db.get_learning_by_id = MagicMock(
            side_effect=[None, _make_learning(learning_id=victim_key, learning_type="entity_memory")]
        )
        resp = scoped_client.post(
            "/learnings",
            json={
                "learning_type": "entity_memory",
                "content": {"stolen": True},
                "user_id": "attacker",
                "entity_id": "corp",
                "entity_type": "acme",
                "namespace": forged_namespace,
            },
        )
        mock_db.upsert_learning.assert_not_called()
        assert resp.status_code == 422
        assert "reserved" in resp.json()["detail"]

    @pytest.mark.parametrize(
        "namespace",
        [
            "user_team",
            "user_team_shared",
            "user_c6c289e49e9c05",
            "user_c6c289e49e9c05_company",
            "user_C6C289E49E9C05B2",
            "user_C6C289E49E9C05B2_company",
            "user_c6c289e49e9c05b2x",
            "user_c6c289e49e9c05b2x_company",
            "users_c6c289e49e9c05b2",
            "workspace_c6c289e49e9c05b2_company",
        ],
    )
    def test_create_entity_allows_namespaces_that_only_resemble_the_digest(self, client, mock_db, namespace):
        # Reserved is 16 lowercase hex directly after "user_", ending at a segment boundary.
        # A shorter digest, uppercase hex, a longer run, or a different prefix is an ordinary
        # custom namespace and still creates.
        expected_id = build_learning_id("entity_memory", entity_id="acme", entity_type="company", namespace=namespace)
        created = _make_learning(
            learning_id=expected_id,
            learning_type="entity_memory",
            namespace=namespace,
            entity_id="acme",
            entity_type="company",
        )
        mock_db.get_learning_by_id = MagicMock(side_effect=[None, created])
        resp = client.post(
            "/learnings",
            json={
                "learning_type": "entity_memory",
                "content": {},
                "entity_id": "acme",
                "entity_type": "company",
                "namespace": namespace,
            },
        )
        assert resp.status_code == 201
        kwargs = mock_db.upsert_learning.call_args[1]
        assert kwargs["id"] == expected_id
        assert kwargs["namespace"] == namespace
