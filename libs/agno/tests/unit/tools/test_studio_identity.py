"""Identity and ownership threading through StudioTools.

Studio 3.0 phase 1 (specs/agno/studio-3.0/spec-v0.md section 3.1): every
mutating tool and every user-scoped read consumes the framework-injected
``_agno_run_context``; the acting user owns what it creates, cannot touch
another owner's rows, and cannot modify shared (unowned) rows. Without a
run context the toolkit behaves exactly as before: unowned writes,
unscoped reads.

Uses a real SqliteDb so the ownership filters in the adapter are exercised,
not mocked. Refusals are asserted by stable error code: another owner's row
answers component_not_found (its existence is not disclosed); a shared row
answers shared_component (the honest refusal).
"""

import json
from typing import Any, Dict

import pytest

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.run.base import RunContext
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioTools

ALICE = RunContext(run_id="run-a", session_id="sess-a", user_id="alice")
BOB = RunContext(run_id="run-b", session_id="sess-b", user_id="bob")


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="studio-identity-db", db_file=str(tmp_path / "studio_identity.db"))


@pytest.fixture
def registry(db):
    return Registry(
        name="Identity Registry",
        tools=[CalculatorTools()],
        models=[OpenAIResponses(id="gpt-5.5")],
        dbs=[db],
    )


@pytest.fixture
def studio(registry, db):
    return StudioTools(registry=registry, db=db, teams=True, workflows=True, schedules=True)


def _loads(s: str) -> Dict[str, Any]:
    return json.loads(s)


def _data(s: str) -> Dict[str, Any]:
    out = json.loads(s)
    assert out.get("ok") is True, out
    return out["data"]


def _error(s: str) -> Dict[str, Any]:
    out = json.loads(s)
    assert out.get("ok") is False, out
    return out["error"]


def _create(studio: StudioTools, name: str, run_context=None, publish=False) -> Dict[str, Any]:
    return _data(
        studio.create_agent(name=name, instructions="Say hello.", publish=publish, _agno_run_context=run_context)
    )


# ----------------------------------------------------------------------
# Writes carry the actor
# ----------------------------------------------------------------------


class TestCreateOwnership:
    def test_create_with_context_owns_the_row(self, studio, db):
        created = _create(studio, "Owned Agent", ALICE)
        row = db.get_component(created["id"])
        assert row is not None
        assert row["user_id"] == "alice"

    def test_create_without_context_is_unowned(self, studio, db):
        created = _create(studio, "Shared Agent")
        row = db.get_component(created["id"])
        assert row is not None
        assert row["user_id"] is None

    def test_create_stamps_actor_metadata(self, studio, db):
        created = _create(studio, "Stamped Agent", ALICE)
        row = db.get_component(created["id"])
        stamp = (row.get("metadata") or {}).get("studio") or {}
        assert stamp.get("created_by") == "alice"
        assert stamp.get("created_run_id") == "run-a"
        assert stamp.get("created_session_id") == "sess-a"
        assert stamp.get("last_action") == "create"

    def test_create_without_context_has_no_stamp(self, studio, db):
        created = _create(studio, "Plain Agent")
        row = db.get_component(created["id"])
        assert (row.get("metadata") or {}).get("studio") is None

    def test_team_and_workflow_creates_own_their_rows(self, studio, db):
        member = _create(studio, "Member Agent", ALICE)
        studio.publish_component(member["id"], _agno_run_context=ALICE)
        team = _data(
            studio.create_team(
                name="Owned Team",
                instructions="Coordinate.",
                member_ids=[member["id"]],
                _agno_run_context=ALICE,
            )
        )
        assert db.get_component(team["id"])["user_id"] == "alice"
        workflow = _data(
            studio.create_workflow(
                name="Owned Workflow",
                description="One step.",
                steps=[{"name": "s1", "agent_id": member["id"]}],
                _agno_run_context=ALICE,
            )
        )
        assert db.get_component(workflow["id"])["user_id"] == "alice"


# ----------------------------------------------------------------------
# Mutations respect ownership
# ----------------------------------------------------------------------


class TestMutationOwnership:
    def test_owner_edits_own_component(self, studio, db):
        created = _create(studio, "Editable", ALICE)
        edited = _loads(studio.edit_agent(created["id"], instructions="Say goodbye.", _agno_run_context=ALICE))
        assert edited.get("status") == "edited", edited
        stamp = (db.get_component(created["id"]).get("metadata") or {}).get("studio") or {}
        # Publish syncs the row on publish; the draft stamp lives in the config.
        assert stamp.get("created_by") == "alice"

    def test_other_owner_cannot_edit_and_learns_nothing(self, studio):
        created = _create(studio, "Private Agent", ALICE)
        error = _error(studio.edit_agent(created["id"], instructions="Hijack.", _agno_run_context=BOB))
        assert error["code"] == "component_not_found"
        assert created["id"] in error["message"]

    def test_scoped_actor_cannot_edit_shared_component(self, studio):
        created = _create(studio, "Communal Agent")
        error = _error(studio.edit_agent(created["id"], instructions="Claim.", _agno_run_context=ALICE))
        assert error["code"] == "shared_component"

    def test_unscoped_caller_edits_anything(self, studio):
        created = _create(studio, "Anyones Agent", ALICE)
        edited = _loads(studio.edit_agent(created["id"], instructions="Operator edit."))
        assert edited.get("status") == "edited", edited

    def test_other_owner_cannot_archive(self, studio, db):
        created = _create(studio, "Sturdy Agent", ALICE)
        error = _error(studio.archive_component(created["id"], _agno_run_context=BOB))
        assert error["code"] == "component_not_found"
        assert db.get_component(created["id"]) is not None

    def test_owner_archives_own(self, studio, db):
        created = _create(studio, "Doomed Agent", ALICE)
        archived = _loads(studio.archive_component(created["id"], _agno_run_context=ALICE))
        assert archived.get("status") == "archived", archived
        assert db.get_component(created["id"]) is None

    def test_other_owner_cannot_restore_an_archived_component(self, studio, db):
        created = _create(studio, "Recoverable Agent", ALICE)
        studio.archive_component(created["id"], _agno_run_context=ALICE)

        error = _error(studio.restore_component(created["id"], _agno_run_context=BOB))
        assert error["code"] == "component_not_found"
        assert db.get_component(created["id"]) is None  # still archived

        restored = _loads(studio.restore_component(created["id"], _agno_run_context=ALICE))
        assert restored.get("status") == "restored", restored
        assert db.get_component(created["id"]) is not None

    def test_other_owner_archive_of_an_archived_row_learns_nothing(self, studio):
        created = _create(studio, "Ghosted Agent", ALICE)
        studio.archive_component(created["id"], _agno_run_context=ALICE)
        # The owner sees the idempotent status; another owner sees not-found.
        assert _loads(studio.archive_component(created["id"], _agno_run_context=ALICE))["status"] == "already_archived"
        error = _error(studio.archive_component(created["id"], _agno_run_context=BOB))
        assert error["code"] == "component_not_found"

    def test_lifecycle_tools_are_gated(self, studio):
        created = _create(studio, "Guarded Agent", ALICE)
        edited = _data(studio.edit_agent(created["id"], instructions="v2", _agno_run_context=ALICE))
        assert edited.get("stage") == "draft"
        for call in (
            lambda: studio.publish_component(created["id"], _agno_run_context=BOB),
            lambda: studio.set_current_version(created["id"], 1, _agno_run_context=BOB),
            lambda: studio.delete_version(created["id"], edited["draft_version"], _agno_run_context=BOB),
        ):
            error = _error(call())
            assert error["code"] == "component_not_found", error
        published = _loads(studio.publish_component(created["id"], _agno_run_context=ALICE))
        assert published.get("status") == "published", published


# ----------------------------------------------------------------------
# Reads are scoped
# ----------------------------------------------------------------------


class TestReadScoping:
    def test_scoped_list_hides_other_owners(self, studio):
        _create(studio, "Alices Agent", ALICE)
        _create(studio, "Bobs Agent", BOB)
        _create(studio, "Shared Listing Agent")
        listed = _data(studio.list_components(component_type="agent", _agno_run_context=ALICE))
        ids = {row["id"] for row in listed["components"] if row.get("source") == "db"}
        assert "alices-agent" in ids
        assert "shared-listing-agent" in ids
        assert "bobs-agent" not in ids
        unscoped = _data(studio.list_components(component_type="agent"))
        assert {"alices-agent", "bobs-agent", "shared-listing-agent"} <= {
            row["id"] for row in unscoped["components"] if row.get("source") == "db"
        }

    def test_scoped_get_hides_other_owners(self, studio):
        created = _create(studio, "Hidden Agent", ALICE)
        error = _error(studio.get_component(created["id"], _agno_run_context=BOB))
        assert error["code"] == "component_not_found"
        shared = _create(studio, "Visible Shared Agent")
        visible = _data(studio.get_component(shared["id"], _agno_run_context=BOB))
        assert visible.get("id") == shared["id"]

    def test_version_reads_are_gated(self, studio):
        created = _create(studio, "Versioned Agent", ALICE)
        for call in (
            lambda: studio.list_versions(created["id"], _agno_run_context=BOB),
            lambda: studio.get_component(created["id"], version=1, _agno_run_context=BOB),
        ):
            error = _error(call())
            assert error["code"] == "component_not_found", error
        own = _data(studio.list_versions(created["id"], _agno_run_context=ALICE))
        assert own.get("count") == 1


# ----------------------------------------------------------------------
# Schedules: the builder can see what it created
# ----------------------------------------------------------------------


class TestScheduleOwnership:
    def test_schedule_is_owned_and_visible_to_its_creator(self, studio, db):
        created = _create(studio, "Scheduled Agent", ALICE, publish=True)
        made = _loads(
            studio.create_schedule(
                name="alices-daily",
                cron="0 9 * * *",
                target_type="agent",
                target_id=created["id"],
                message="Run the brief.",
                _agno_run_context=ALICE,
            )
        )
        assert made.get("status") == "created", made
        row = db.get_schedule(made["data"]["id"])
        assert row is not None and row["user_id"] == "alice"
        # The regression this phase exists for: the owner-scoped management
        # tools Studio mounts must see the schedule Studio just created for
        # the same actor. They are registered functions, not methods.
        list_schedules = studio.functions["list_schedules"].entrypoint
        listed = _loads(list_schedules(run_context=ALICE))
        assert any(s["id"] == made["data"]["id"] for s in listed["schedules"]), listed
        other = _loads(list_schedules(run_context=BOB))
        assert not any(s["id"] == made["data"]["id"] for s in other.get("schedules", [])), other

    def test_update_schedule_is_owner_scoped(self, studio, db):
        created = _create(studio, "Scoped Sched Agent", ALICE, publish=True)
        made = _loads(
            studio.create_schedule(
                name="alices-cadence",
                cron="0 9 * * *",
                target_type="agent",
                target_id=created["id"],
                message="Run.",
                _agno_run_context=ALICE,
            )
        )
        sched_id = made["data"]["id"]

        hijack = _loads(studio.update_schedule(sched_id, cron="0 4 * * *", _agno_run_context=BOB))
        assert hijack["error"]["code"] == "schedule_not_found", hijack
        assert db.get_schedule(sched_id)["cron_expr"] == "0 9 * * *"

        allowed = _loads(studio.update_schedule(sched_id, cron="0 4 * * *", _agno_run_context=ALICE))
        assert allowed["ok"], allowed
        assert db.get_schedule(sched_id)["cron_expr"] == "0 4 * * *"

    def test_schedule_without_context_is_unowned(self, studio, db):
        created = _create(studio, "Cron Target", publish=True)
        made = _loads(
            studio.create_schedule(
                name="ownerless-daily",
                cron="0 9 * * *",
                target_type="agent",
                target_id=created["id"],
                message="Run.",
            )
        )
        assert made.get("status") == "created", made
        assert db.get_schedule(made["data"]["id"])["user_id"] is None


# ----------------------------------------------------------------------
# Internal service token
# ----------------------------------------------------------------------


class TestInternalServiceScopes:
    def test_internal_token_cannot_mutate_schedules(self):
        from agno.os.auth import INTERNAL_SERVICE_SCOPES

        assert "schedules:write" not in INTERNAL_SERVICE_SCOPES
        assert "schedules:delete" not in INTERNAL_SERVICE_SCOPES
        assert "schedules:read" in INTERNAL_SERVICE_SCOPES
