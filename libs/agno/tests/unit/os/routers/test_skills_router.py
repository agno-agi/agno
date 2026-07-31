"""Tests for the skills REST API router."""

import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import BaseDb
from agno.os.routers.skills import get_skills_router
from agno.os.settings import AgnoAPISettings
from agno.skills.errors import SkillError, SkillValidationError


def _make_skill_row(**overrides):
    now = int(time.time())
    d = {
        "id": "skill-1",
        "name": "demo-skill",
        "user_id": None,
        "description": "A demo skill",
        "source_type": "local",
        "instructions": "Use the demo skill",
        "scripts": {"run.py": "print('hi')"},
        "references": {"guide.md": "# Guide"},
        "metadata": None,
        "license": None,
        "compatibility": None,
        "allowed_tools": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    d.update(overrides)
    return d


def _make_skill_summary(**overrides):
    """A metadata-only row, as get_skills returns it (no heavy content columns)."""
    row = _make_skill_row(**overrides)
    for heavy in ("instructions", "scripts", "references"):
        row.pop(heavy, None)
    return row


def _create_body(**overrides):
    d = {
        "name": "demo-skill",
        "description": "A demo skill",
        "instructions": "Use the demo skill",
    }
    d.update(overrides)
    return d


@pytest.fixture
def mock_db():
    db = MagicMock(spec=BaseDb)
    db.get_skill = MagicMock(return_value=None)
    db.get_skills = MagicMock(return_value=([], 0))
    db.create_skill = MagicMock(return_value=_make_skill_row())
    db.update_skill = MagicMock(return_value=None)
    db.delete_skill = MagicMock(return_value=True)
    return db


@pytest.fixture
def settings():
    return AgnoAPISettings()


@pytest.fixture
def client(mock_db, settings):
    app = FastAPI()
    router = get_skills_router(dbs={"default": [mock_db]}, settings=settings)
    app.include_router(router)
    return TestClient(app)


class TestListSkills:
    def test_empty(self, client, mock_db):
        resp = client.get("/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["meta"]["total_count"] == 0

    def test_returns_records(self, client, mock_db):
        records = [_make_skill_summary(id="a", name="skill-a"), _make_skill_summary(id="b", name="skill-b")]
        mock_db.get_skills = MagicMock(return_value=(records, 2))
        resp = client.get("/skills")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert [r["name"] for r in data] == ["skill-a", "skill-b"]

    def test_list_is_metadata_only(self, client, mock_db):
        # The list never carries content (spec: metadata only, no instructions,
        # scripts or references) -- even if a backend were to return full rows.
        mock_db.get_skills = MagicMock(return_value=([_make_skill_row()], 1))
        resp = client.get("/skills")
        assert resp.status_code == 200
        item = resp.json()["data"][0]
        assert "instructions" not in item
        assert "scripts" not in item
        assert "references" not in item
        # The metadata fields are all present.
        for field in ("id", "name", "description", "source_type", "version", "created_at", "updated_at"):
            assert field in item

    def test_filters_passed_through(self, client, mock_db):
        client.get("/skills?user_id=u1&page=2&limit=50")
        kwargs = mock_db.get_skills.call_args[1]
        assert kwargs["user_id"] == "u1"
        assert kwargs["page"] == 2
        assert kwargs["limit"] == 50

    def test_pagination_meta(self, client, mock_db):
        mock_db.get_skills = MagicMock(return_value=([_make_skill_summary()], 25))
        resp = client.get("/skills?limit=10")
        meta = resp.json()["meta"]
        assert meta["total_count"] == 25
        assert meta["total_pages"] == 3
        assert meta["limit"] == 10

    def test_not_implemented_returns_501(self, client, mock_db):
        mock_db.get_skills.side_effect = NotImplementedError
        resp = client.get("/skills")
        assert resp.status_code == 501

    def test_db_error_returns_500(self, client, mock_db):
        # A DB error must surface as 500, not a misleading empty 200 page.
        mock_db.get_skills.side_effect = RuntimeError("boom")
        resp = client.get("/skills")
        assert resp.status_code == 500

    def test_table_without_db_id_rejected(self, client, mock_db):
        resp = client.get("/skills?table=some_skills")
        assert resp.status_code == 400


class TestGetSkill:
    def test_get_success_returns_full_content(self, client, mock_db):
        row = _make_skill_row(name="demo-skill")
        mock_db.get_skill = MagicMock(return_value=row)
        resp = client.get("/skills/demo-skill")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "demo-skill"
        # Detail is the full-content shape: instructions plus both content dicts,
        # returned verbatim as {filename: text}.
        assert body["instructions"] == "Use the demo skill"
        assert body["scripts"] == {"run.py": "print('hi')"}
        assert body["references"] == {"guide.md": "# Guide"}
        assert mock_db.get_skill.call_args[0][0] == "demo-skill"

    def test_get_not_found(self, client, mock_db):
        mock_db.get_skill = MagicMock(return_value=None)
        resp = client.get("/skills/nope")
        assert resp.status_code == 404

    def test_get_not_implemented_returns_501(self, client, mock_db):
        mock_db.get_skill.side_effect = NotImplementedError
        resp = client.get("/skills/demo-skill")
        assert resp.status_code == 501

    def test_db_error_returns_500_not_404(self, client, mock_db):
        # A DB error is not "not found" -- surface it as 500, not a misleading 404.
        mock_db.get_skill = MagicMock(side_effect=RuntimeError("boom"))
        resp = client.get("/skills/demo-skill")
        assert resp.status_code == 500


class TestCreateSkill:
    def test_create_success(self, client, mock_db):
        mock_db.create_skill = MagicMock(return_value=_make_skill_row(version=1))
        resp = client.post("/skills", json=_create_body())
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "demo-skill"
        assert body["version"] == 1
        assert "instructions" in body
        skill_data = mock_db.create_skill.call_args[0][0]
        assert skill_data["name"] == "demo-skill"
        assert skill_data["description"] == "A demo skill"
        assert skill_data["instructions"] == "Use the demo skill"

    def test_create_defaults(self, client, mock_db):
        # Content dicts default to empty, source_type to the column default, and
        # id/version are server-managed -- the router must not send them.
        client.post("/skills", json=_create_body())
        skill_data = mock_db.create_skill.call_args[0][0]
        assert skill_data["scripts"] == {}
        assert skill_data["references"] == {}
        assert skill_data["source_type"] == "local"
        assert skill_data["user_id"] is None
        assert "id" not in skill_data
        assert "version" not in skill_data

    def test_create_content_passed_verbatim(self, client, mock_db):
        body = _create_body(
            scripts={"run.py": "print('hi')"},
            references={"guide.md": "# Guide"},
        )
        client.post("/skills", json=body)
        skill_data = mock_db.create_skill.call_args[0][0]
        assert skill_data["scripts"] == {"run.py": "print('hi')"}
        assert skill_data["references"] == {"guide.md": "# Guide"}

    def test_create_duplicate_name_returns_409(self, client, mock_db):
        mock_db.create_skill = MagicMock(side_effect=SkillError("name is already taken"))
        resp = client.post("/skills", json=_create_body())
        assert resp.status_code == 409

    def test_create_invalid_content_returns_422(self, client, mock_db):
        mock_db.create_skill = MagicMock(side_effect=SkillValidationError("bad content", errors=["bad content"]))
        resp = client.post("/skills", json=_create_body())
        assert resp.status_code == 422

    def test_create_missing_required_field_is_422(self, client, mock_db):
        resp = client.post("/skills", json={"description": "no name or instructions"})
        assert resp.status_code == 422
        mock_db.create_skill.assert_not_called()

    def test_create_not_implemented_returns_501(self, client, mock_db):
        mock_db.create_skill = MagicMock(side_effect=NotImplementedError)
        resp = client.post("/skills", json=_create_body())
        assert resp.status_code == 501

    def test_create_db_error_returns_500(self, client, mock_db):
        mock_db.create_skill = MagicMock(side_effect=RuntimeError("boom"))
        resp = client.post("/skills", json=_create_body())
        assert resp.status_code == 500


class TestUpdateSkill:
    def test_update_success(self, client, mock_db):
        existing = _make_skill_row(version=5)
        updated = _make_skill_row(version=6, description="new description")
        mock_db.get_skill = MagicMock(return_value=existing)
        mock_db.update_skill = MagicMock(return_value=updated)
        resp = client.patch("/skills/demo-skill", json={"version": 5, "description": "new description"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == 6
        assert body["description"] == "new description"
        assert mock_db.update_skill.call_args[0][0] == "demo-skill"
        kwargs = mock_db.update_skill.call_args[1]
        assert kwargs["expected_version"] == 5
        assert kwargs["description"] == "new description"

    def test_update_passes_only_set_fields(self, client, mock_db):
        # Partial update: unset fields must not be splatted as None over the row.
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(version=1))
        mock_db.update_skill = MagicMock(return_value=_make_skill_row(version=2, metadata={"a": 1}))
        client.patch("/skills/demo-skill", json={"version": 1, "metadata": {"a": 1}})
        kwargs = mock_db.update_skill.call_args[1]
        assert set(kwargs) == {"expected_version", "metadata"}

    def test_update_requires_version(self, client, mock_db):
        # The update names the version it is editing; without it the request is invalid.
        resp = client.patch("/skills/demo-skill", json={"description": "new"})
        assert resp.status_code == 422
        mock_db.update_skill.assert_not_called()

    def test_update_not_found(self, client, mock_db):
        mock_db.get_skill = MagicMock(return_value=None)
        resp = client.patch("/skills/missing", json={"version": 1, "description": "new"})
        assert resp.status_code == 404
        mock_db.update_skill.assert_not_called()

    def test_update_stale_version_returns_409_with_current_version(self, client, mock_db):
        # The guarded update matched nothing but the row still exists: its version has
        # moved. 409, with the current version in the response so the caller can retry.
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(version=7))
        mock_db.update_skill = MagicMock(return_value=None)
        resp = client.patch("/skills/demo-skill", json={"version": 5, "description": "new"})
        assert resp.status_code == 409
        assert "current version is 7" in resp.json()["detail"]

    @pytest.mark.parametrize("field", ["description", "instructions", "scripts", "references", "source_type"])
    def test_update_rejects_explicit_null_for_non_nullable_field(self, client, mock_db, field):
        # These columns are NOT NULL in the table; an explicit null can never be
        # stored and must be rejected up front, not surface as a bogus 409.
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(version=1))
        resp = client.patch("/skills/demo-skill", json={"version": 1, field: None})
        assert resp.status_code == 422
        mock_db.update_skill.assert_not_called()

    def test_update_null_metadata_allowed(self, client, mock_db):
        # metadata is a nullable column; an explicit null clears it.
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(version=1, metadata={"a": 1}))
        mock_db.update_skill = MagicMock(return_value=_make_skill_row(version=2, metadata=None))
        resp = client.patch("/skills/demo-skill", json={"version": 1, "metadata": None})
        assert resp.status_code == 200
        assert mock_db.update_skill.call_args[1]["metadata"] is None

    def test_update_none_with_unmoved_version_returns_500(self, client, mock_db):
        # update_skill returning None while the version has not moved is a swallowed
        # DB error, not a conflict: a 409 telling the caller to retry with the
        # version they already sent could never succeed.
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(version=5))
        mock_db.update_skill = MagicMock(return_value=None)
        resp = client.patch("/skills/demo-skill", json={"version": 5, "description": "new"})
        assert resp.status_code == 500

    def test_update_gone_after_guard_returns_404(self, client, mock_db):
        # The row vanished between the pre-fetch and the guarded update: 404, not 409.
        mock_db.get_skill = MagicMock(side_effect=[_make_skill_row(version=5), None])
        mock_db.update_skill = MagicMock(return_value=None)
        resp = client.patch("/skills/demo-skill", json={"version": 5, "description": "new"})
        assert resp.status_code == 404

    def test_update_invalid_content_returns_422(self, client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(version=1))
        mock_db.update_skill = MagicMock(side_effect=SkillValidationError("bad content", errors=["bad content"]))
        resp = client.patch("/skills/demo-skill", json={"version": 1, "scripts": {"run.py": "x"}})
        assert resp.status_code == 422

    def test_update_db_error_returns_500(self, client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(version=1))
        mock_db.update_skill = MagicMock(side_effect=RuntimeError("boom"))
        resp = client.patch("/skills/demo-skill", json={"version": 1, "description": "new"})
        assert resp.status_code == 500


class TestDeleteSkill:
    def test_delete_success(self, client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row())
        resp = client.delete("/skills/demo-skill")
        assert resp.status_code == 204
        assert mock_db.delete_skill.call_args[0][0] == "demo-skill"
        assert mock_db.delete_skill.call_args[1]["user_id"] is None

    def test_delete_not_found(self, client, mock_db):
        mock_db.get_skill = MagicMock(return_value=None)
        resp = client.delete("/skills/missing")
        assert resp.status_code == 404
        mock_db.delete_skill.assert_not_called()

    def test_delete_user_filter_passed_through(self, client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="u1"))
        resp = client.delete("/skills/demo-skill?user_id=u1")
        assert resp.status_code == 204
        assert mock_db.delete_skill.call_args[1]["user_id"] == "u1"

    def test_delete_filter_mismatch_returns_404(self, client, mock_db):
        # The row exists but is owned by someone else: the user_id filter matches
        # nothing at the DB layer, so nothing is deleted.
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="u2"))
        mock_db.delete_skill = MagicMock(return_value=False)
        resp = client.delete("/skills/demo-skill?user_id=u1")
        assert resp.status_code == 404

    def test_delete_not_implemented_returns_501(self, client, mock_db):
        mock_db.get_skill = MagicMock(side_effect=NotImplementedError)
        resp = client.delete("/skills/demo-skill")
        assert resp.status_code == 501


class TestUserScoping:
    """For a scoped (non-admin) JWT caller with user_isolation enabled, the router enforces
    ownership-based scoping via get_scoped_user_id.

    Rules (spec section 3.8, following the learnings router):
      - LIST: bind the user_id filter to the subject; reject an explicit user_id query
        that mismatches with 403.
      - CREATE: allow body.user_id to be null (a shared skill) or match the subject;
        reject mismatch with 403.
      - GET single skill: a NULL-owner (shared) skill stays readable by anyone; a skill
        owned by another user returns 404 (not 403 -- avoids leaking existence).
      - PATCH/DELETE: a NULL-owner skill is mutable only by an admin (403); a skill
        owned by another user returns 404.
    """

    @pytest.fixture
    def jwt_client(self, mock_db, settings):
        app = FastAPI()

        @app.middleware("http")
        async def add_jwt_user(request, call_next):
            # Regular (non-admin) user with user isolation enabled.
            request.state.user_isolation_enabled = True
            request.state.user_id = "user-A"
            request.state.scopes = []
            return await call_next(request)

        router = get_skills_router(dbs={"default": [mock_db]}, settings=settings)
        app.include_router(router)
        return TestClient(app)

    def test_list_binds_subject(self, jwt_client, mock_db):
        jwt_client.get("/skills")
        assert mock_db.get_skills.call_args[1]["user_id"] == "user-A"

    def test_list_matching_user_id_allowed(self, jwt_client, mock_db):
        resp = jwt_client.get("/skills?user_id=user-A")
        assert resp.status_code == 200
        assert mock_db.get_skills.call_args[1]["user_id"] == "user-A"

    def test_list_mismatched_user_id_rejected(self, jwt_client, mock_db):
        resp = jwt_client.get("/skills?user_id=user-B")
        assert resp.status_code == 403
        mock_db.get_skills.assert_not_called()

    def test_create_null_user_id_creates_shared_skill(self, jwt_client, mock_db):
        mock_db.create_skill = MagicMock(return_value=_make_skill_row(user_id=None))
        resp = jwt_client.post("/skills", json=_create_body())
        assert resp.status_code == 201
        assert mock_db.create_skill.call_args[0][0]["user_id"] is None

    def test_create_matching_user_id_allowed(self, jwt_client, mock_db):
        mock_db.create_skill = MagicMock(return_value=_make_skill_row(user_id="user-A"))
        resp = jwt_client.post("/skills", json=_create_body(user_id="user-A"))
        assert resp.status_code == 201
        assert mock_db.create_skill.call_args[0][0]["user_id"] == "user-A"

    def test_create_mismatched_user_id_rejected(self, jwt_client, mock_db):
        resp = jwt_client.post("/skills", json=_create_body(user_id="user-B"))
        assert resp.status_code == 403
        mock_db.create_skill.assert_not_called()

    def test_get_shared_skill_accessible(self, jwt_client, mock_db):
        # Reads of NULL-owner (shared) skills remain open to any authenticated caller.
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id=None))
        resp = jwt_client.get("/skills/demo-skill")
        assert resp.status_code == 200
        assert resp.json()["user_id"] is None

    def test_get_own_skill_accessible(self, jwt_client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-A"))
        resp = jwt_client.get("/skills/demo-skill")
        assert resp.status_code == 200

    def test_get_other_users_skill_returns_404(self, jwt_client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-B"))
        resp = jwt_client.get("/skills/demo-skill")
        assert resp.status_code == 404

    def test_patch_shared_skill_forbidden_for_non_admin(self, jwt_client, mock_db):
        # Mutating a NULL-owner skill is admin-only.
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id=None))
        resp = jwt_client.patch("/skills/demo-skill", json={"version": 1, "description": "new"})
        assert resp.status_code == 403
        mock_db.update_skill.assert_not_called()

    def test_patch_own_skill_allowed(self, jwt_client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-A", version=1))
        mock_db.update_skill = MagicMock(return_value=_make_skill_row(user_id="user-A", version=2))
        resp = jwt_client.patch("/skills/demo-skill", json={"version": 1, "description": "new"})
        assert resp.status_code == 200

    def test_patch_other_users_skill_returns_404(self, jwt_client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-B"))
        resp = jwt_client.patch("/skills/demo-skill", json={"version": 1, "description": "new"})
        assert resp.status_code == 404
        mock_db.update_skill.assert_not_called()

    @pytest.mark.parametrize("sent_user_id", ["user-A", "user-B", None])
    def test_patch_body_user_id_is_rejected(self, jwt_client, mock_db, sent_user_id):
        """Ownership is set at create and never moves: it is not an updatable field.

        A skill's owner decides who may read and mutate it, so silently ignoring a
        user_id here would let a caller believe a transfer happened. The field does not
        exist on the update model, and unknown fields are refused rather than dropped.
        """
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-A", version=1))
        resp = jwt_client.patch("/skills/demo-skill", json={"version": 1, "user_id": sent_user_id})
        assert resp.status_code == 422
        mock_db.update_skill.assert_not_called()

    def test_patch_write_is_scoped_to_the_caller(self, jwt_client, mock_db):
        """The write itself must carry the ownership predicate, not just the pre-check.

        Checking ownership on a fetched row and then writing unscoped is a TOCTOU: the row
        can be replaced between the check and the write. Passing user_id to update_skill
        makes the write refuse a row the caller does not own.
        """
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-A", version=1))
        mock_db.update_skill = MagicMock(return_value=_make_skill_row(user_id="user-A", version=2))

        resp = jwt_client.patch("/skills/demo-skill", json={"version": 1, "description": "new"})

        assert resp.status_code == 200
        assert mock_db.update_skill.call_args[1]["user_id"] == "user-A"

    def test_patch_write_cannot_land_on_another_users_row(self, jwt_client, mock_db):
        """The reproduced race: the row is swapped for another user's between check and write.

        The pre-check sees user-A's row; by the time the write runs the name belongs to
        user-B at the same version. A scoped write matches no row, so nothing is
        overwritten and the caller gets a conflict rather than a silent cross-user write.
        """
        rows = [_make_skill_row(user_id="user-A", version=1), _make_skill_row(user_id="user-B", version=1)]
        mock_db.get_skill = MagicMock(side_effect=lambda *a, **k: rows.pop(0) if rows else None)
        # A scoped update against a row owned by someone else matches nothing.
        mock_db.update_skill = MagicMock(return_value=None)

        resp = jwt_client.patch("/skills/demo-skill", json={"version": 1, "description": "hijack"})

        assert mock_db.update_skill.call_args[1]["user_id"] == "user-A", (
            "the write must be scoped, or it lands on whatever row now holds the name"
        )
        assert resp.status_code != 200, "a write that matched no row must not report success"

    def test_patch_409_refetch_does_not_leak_another_users_version(self, jwt_client, mock_db):
        """The stale-version 409 re-fetch must be scoped too, or it leaks a foreign row."""
        rows = [_make_skill_row(user_id="user-A", version=1), _make_skill_row(user_id="user-B", version=77)]

        def scoped_get_skill(name, user_id=None):
            # Model the DB: an ownership filter excludes a row owned by someone else.
            row = rows.pop(0) if rows else None
            if row is not None and user_id is not None and row["user_id"] != user_id:
                return None
            return row

        mock_db.get_skill = MagicMock(side_effect=scoped_get_skill)
        mock_db.update_skill = MagicMock(return_value=None)

        resp = jwt_client.patch("/skills/demo-skill", json={"version": 1, "description": "new"})

        assert "77" not in resp.text, "must not disclose another user's version"
        assert mock_db.get_skill.call_args[1].get("user_id") == "user-A", "the re-fetch must be scoped to the caller"

    def test_delete_write_is_scoped_to_the_caller(self, jwt_client, mock_db):
        """The delete itself must carry the ownership predicate, not just the pre-check.

        Checking ownership on a fetched row and then deleting by name alone is a TOCTOU:
        the name can be re-owned between the check and the write.
        """
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-A"))
        resp = jwt_client.delete("/skills/demo-skill")
        assert resp.status_code == 204
        assert mock_db.delete_skill.call_args[1]["user_id"] == "user-A"

    def test_cross_user_404_is_indistinguishable_from_a_missing_skill(self, jwt_client, mock_db):
        """A 404 for another user's skill must be byte-identical to a 404 for a name that
        does not exist, or the response itself discloses which names are taken."""
        for method, kwargs in (
            ("get", {}),
            ("delete", {}),
            ("patch", {"json": {"version": 1, "description": "x"}}),
        ):
            mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-B"))
            foreign = getattr(jwt_client, method)("/skills/demo-skill", **kwargs)
            mock_db.get_skill = MagicMock(return_value=None)
            missing = getattr(jwt_client, method)("/skills/no-such-skill", **kwargs)

            assert foreign.status_code == 404, method
            assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json()), method

    def test_delete_shared_skill_forbidden_for_non_admin(self, jwt_client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id=None))
        resp = jwt_client.delete("/skills/demo-skill")
        assert resp.status_code == 403
        mock_db.delete_skill.assert_not_called()

    def test_delete_own_skill_allowed(self, jwt_client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-A"))
        resp = jwt_client.delete("/skills/demo-skill")
        assert resp.status_code == 204

    def test_delete_other_users_skill_returns_404(self, jwt_client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-B"))
        resp = jwt_client.delete("/skills/demo-skill")
        assert resp.status_code == 404
        mock_db.delete_skill.assert_not_called()

    def test_delete_mismatched_user_id_param_rejected(self, jwt_client, mock_db):
        resp = jwt_client.delete("/skills/demo-skill?user_id=user-B")
        assert resp.status_code == 403
        mock_db.delete_skill.assert_not_called()


def _scoped_client(mock_db, settings, **state):
    """Build a TestClient whose middleware stamps the given request.state attrs."""
    app = FastAPI()

    @app.middleware("http")
    async def add_state(request, call_next):
        for k, v in state.items():
            setattr(request.state, k, v)
        return await call_next(request)

    app.include_router(get_skills_router(dbs={"default": [mock_db]}, settings=settings))
    return TestClient(app)


class TestAdminAndUnscopedAccess:
    """get_scoped_user_id returns None for admins and when user_isolation is off, so those
    callers are not bound to their own user_id."""

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

    def test_admin_list_not_scoped(self, admin_client, mock_db):
        admin_client.get("/skills")
        assert mock_db.get_skills.call_args[1]["user_id"] is None

    def test_admin_can_read_other_users_skill(self, admin_client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-B"))
        resp = admin_client.get("/skills/demo-skill")
        assert resp.status_code == 200

    def test_admin_can_mutate_shared_skill(self, admin_client, mock_db):
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id=None, version=1))
        mock_db.update_skill = MagicMock(return_value=_make_skill_row(user_id=None, version=2))
        assert admin_client.patch("/skills/demo-skill", json={"version": 1, "description": "new"}).status_code == 200

        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id=None))
        assert admin_client.delete("/skills/demo-skill").status_code == 204

    def test_isolation_off_is_unscoped(self, isolation_off_client, mock_db):
        # Even with a JWT subject, isolation-off means user_id is a plain filter.
        isolation_off_client.get("/skills?user_id=user-B")
        assert mock_db.get_skills.call_args[1]["user_id"] == "user-B"
        # And a cross-user single skill is accessible (no 404).
        mock_db.get_skill = MagicMock(return_value=_make_skill_row(user_id="user-B"))
        assert isolation_off_client.get("/skills/demo-skill").status_code == 200


class TestAsyncBackendDispatch:
    """Spec section 3.8: on an async backend the route calls the async twin."""

    @pytest.fixture
    def async_mock_db(self):
        from unittest.mock import AsyncMock

        from agno.db.base import AsyncBaseDb

        db = MagicMock(spec=AsyncBaseDb)
        db.get_skill = AsyncMock(return_value=_make_skill_row())
        db.get_skills = AsyncMock(return_value=([], 0))
        db.create_skill = AsyncMock(return_value=_make_skill_row())
        db.update_skill = AsyncMock(return_value=_make_skill_row(version=2))
        db.delete_skill = AsyncMock(return_value=True)
        return db

    @pytest.fixture
    def async_client(self, async_mock_db, settings):
        app = FastAPI()
        app.include_router(get_skills_router(dbs={"default": [async_mock_db]}, settings=settings))
        return TestClient(app)

    def test_list_awaits_async_method(self, async_client, async_mock_db):
        assert async_client.get("/skills").status_code == 200
        async_mock_db.get_skills.assert_awaited_once()

    def test_get_awaits_async_method(self, async_client, async_mock_db):
        assert async_client.get("/skills/demo-skill").status_code == 200
        async_mock_db.get_skill.assert_awaited_once()

    def test_create_awaits_async_method(self, async_client, async_mock_db):
        assert async_client.post("/skills", json=_create_body()).status_code == 201
        async_mock_db.create_skill.assert_awaited_once()

    def test_update_awaits_async_method(self, async_client, async_mock_db):
        assert async_client.patch("/skills/demo-skill", json={"version": 1, "description": "new"}).status_code == 200
        async_mock_db.update_skill.assert_awaited_once()

    def test_delete_awaits_async_method(self, async_client, async_mock_db):
        assert async_client.delete("/skills/demo-skill").status_code == 204
        async_mock_db.delete_skill.assert_awaited_once()


class TestDeleteRaceAgainstRealDb:
    def test_scoped_delete_cannot_destroy_another_users_skill(self, tmp_path, settings):
        """The reproduced TOCTOU, end to end against a real backend.

        The ownership check reads user-A's row; before the delete runs, the name is
        released and re-registered by user-B. Skills are keyed by name, so a name really
        can change hands. An unscoped delete removes whatever row now holds the name.
        """
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(db_file=str(tmp_path / "race.db"))
        db.create_skill({"name": "x", "description": "d", "instructions": "i", "user_id": "user-A"})

        real_get_skill = db.get_skill
        swapped = {"done": False}

        def racing_get_skill(name, user_id=None):
            row = real_get_skill(name, user_id=user_id)
            if not swapped["done"]:
                swapped["done"] = True
                SqliteDb.delete_skill(db, "x")
                db.create_skill({"name": "x", "description": "d", "instructions": "i", "user_id": "user-B"})
            return row

        db.get_skill = racing_get_skill  # type: ignore[method-assign]

        app = FastAPI()

        @app.middleware("http")
        async def add_state(request, call_next):
            request.state.user_isolation_enabled = True
            request.state.user_id = "user-A"
            request.state.scopes = []
            return await call_next(request)

        app.include_router(get_skills_router(dbs={"default": [db]}, settings=settings))
        TestClient(app).delete("/skills/x")

        db.get_skill = real_get_skill  # type: ignore[method-assign]
        survivor = db.get_skill("x")
        assert survivor is not None, "user-A's delete destroyed a row that had become user-B's"
        assert survivor["user_id"] == "user-B"


class TestRouterRegistration:
    def test_routes_registered_and_survive_resync(self, tmp_path):
        # The router must be reachable at first boot (get_app) AND after a resync
        # (_reprovision_routers rebuilds from its own list) -- missing either
        # list makes the router vanish in one of the two lifecycles.
        from agno.agent.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.os import AgentOS

        db = SqliteDb(db_file=str(tmp_path / "skills.db"))
        agent_os = AgentOS(agents=[Agent(name="test-agent", id="test-agent-id")], db=db)
        app = agent_os.get_app()
        client = TestClient(app)

        # Reachable at first boot, through the real DB layer.
        assert client.get("/skills").status_code == 200
        assert client.post("/skills", json=_create_body()).status_code == 201
        assert client.get("/skills/demo-skill").status_code == 200

        agent_os._reprovision_routers(app)
        assert client.get("/skills").status_code == 200
        assert client.get("/skills/demo-skill").status_code == 200
