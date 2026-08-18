"""Identity and ownership threading through StudioTools.

Studio 3.0 phase 1 (specs/agno/studio-3.0/spec-v0.md section 3.1): every
mutating tool and every user-scoped read consumes the framework-injected
``_agno_run_context``; the acting user owns what it creates, cannot touch
another owner's rows, and cannot modify shared (unowned) rows. Without a
run context the toolkit behaves exactly as before: unowned writes,
unscoped reads.

Uses a real SqliteDb so the ownership filters in the adapter are exercised,
not mocked.
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
    return StudioTools(registry=registry, db=db, versions=True, schedules=True)


def _loads(s: str) -> Dict[str, Any]:
    return json.loads(s)


def _create(studio: StudioTools, name: str, run_context=None) -> Dict[str, Any]:
    result = _loads(studio.create_agent(name=name, instructions="Say hello.", _agno_run_context=run_context))
    assert result.get("status") == "created", result
    return result


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
        team = _loads(
            studio.create_team(
                name="Owned Team",
                instructions="Coordinate.",
                member_ids=[member["id"]],
                _agno_run_context=ALICE,
            )
        )
        assert team.get("status") == "created", team
        assert db.get_component(team["id"])["user_id"] == "alice"
        workflow = _loads(
            studio.create_workflow(
                name="Owned Workflow",
                description="One step.",
                step_specs=[{"name": "s1", "agent_id": member["id"]}],
                _agno_run_context=ALICE,
            )
        )
        assert workflow.get("status") == "created", workflow
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
        denied = _loads(studio.edit_agent(created["id"], instructions="Hijack.", _agno_run_context=BOB))
        assert denied.get("error") == f"Agent not found: {created['id']}"

    def test_scoped_actor_cannot_edit_shared_component(self, studio):
        created = _create(studio, "Communal Agent")
        denied = _loads(studio.edit_agent(created["id"], instructions="Claim.", _agno_run_context=ALICE))
        assert "shared" in denied.get("error", "")

    def test_unscoped_caller_edits_anything(self, studio):
        created = _create(studio, "Anyones Agent", ALICE)
        edited = _loads(studio.edit_agent(created["id"], instructions="Operator edit."))
        assert edited.get("status") == "edited", edited

    def test_other_owner_cannot_delete(self, studio, db):
        created = _create(studio, "Sturdy Agent", ALICE)
        denied = _loads(studio.delete_agent(created["id"], _agno_run_context=BOB))
        assert denied.get("error") == f"Agent not found: {created['id']}"
        assert db.get_component(created["id"]) is not None

    def test_owner_deletes_own(self, studio, db):
        created = _create(studio, "Doomed Agent", ALICE)
        deleted = _loads(studio.delete_agent(created["id"], _agno_run_context=ALICE))
        assert deleted.get("status") == "deleted", deleted
        assert db.get_component(created["id"]) is None

    def test_lifecycle_tools_are_gated(self, studio):
        created = _create(studio, "Guarded Agent", ALICE)
        edited = _loads(studio.edit_agent(created["id"], instructions="v2", _agno_run_context=ALICE))
        assert edited.get("stage") == "draft"
        for call in (
            lambda: studio.publish_component(created["id"], _agno_run_context=BOB),
            lambda: studio.set_current_version(created["id"], 1, _agno_run_context=BOB),
            lambda: studio.delete_version(created["id"], edited["draft_version"], _agno_run_context=BOB),
        ):
            denied = _loads(call())
            assert denied.get("error") == f"Component not found: {created['id']}", denied
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
        listed = _loads(studio.list_agents(_agno_run_context=ALICE))
        ids = {a["id"] for a in listed["agents"] if a.get("source") == "db"}
        assert "alices-agent" in ids
        assert "shared-listing-agent" in ids
        assert "bobs-agent" not in ids
        unscoped = _loads(studio.list_agents())
        assert {"alices-agent", "bobs-agent", "shared-listing-agent"} <= {
            a["id"] for a in unscoped["agents"] if a.get("source") == "db"
        }

    def test_scoped_get_hides_other_owners(self, studio):
        created = _create(studio, "Hidden Agent", ALICE)
        denied = _loads(studio.get_agent(created["id"], _agno_run_context=BOB))
        assert denied.get("error") == f"Agent not found: {created['id']}"
        shared = _create(studio, "Visible Shared Agent")
        visible = _loads(studio.get_agent(shared["id"], _agno_run_context=BOB))
        assert visible.get("id") == shared["id"]

    def test_version_reads_are_gated(self, studio):
        created = _create(studio, "Versioned Agent", ALICE)
        for call in (
            lambda: studio.list_versions(created["id"], _agno_run_context=BOB),
            lambda: studio.get_version(created["id"], _agno_run_context=BOB),
        ):
            denied = _loads(call())
            assert denied.get("error") == f"Component not found: {created['id']}", denied
        own = _loads(studio.list_versions(created["id"], _agno_run_context=ALICE))
        assert own.get("count") == 1


# ----------------------------------------------------------------------
# Schedules: the builder can see what it created
# ----------------------------------------------------------------------


class TestScheduleOwnership:
    def test_schedule_is_owned_and_visible_to_its_creator(self, studio, db):
        created = _create(studio, "Scheduled Agent", ALICE)
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
        row = db.get_schedule(made["id"])
        assert row is not None and row["user_id"] == "alice"
        # The regression this phase exists for: the owner-scoped management
        # tools Studio mounts must see the schedule Studio just created for
        # the same actor. They are registered functions, not methods.
        list_schedules = studio.functions["list_schedules"].entrypoint
        listed = _loads(list_schedules(run_context=ALICE))
        assert any(s["id"] == made["id"] for s in listed["schedules"]), listed
        other = _loads(list_schedules(run_context=BOB))
        assert not any(s["id"] == made["id"] for s in other.get("schedules", [])), other

    def test_schedule_without_context_is_unowned(self, studio, db):
        created = _create(studio, "Cron Target")
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
        assert db.get_schedule(made["id"])["user_id"] is None


# ----------------------------------------------------------------------
# Internal service token
# ----------------------------------------------------------------------


class TestInternalServiceScopes:
    def test_internal_token_cannot_mutate_schedules(self):
        from agno.os.auth import INTERNAL_SERVICE_SCOPES

        assert "schedules:write" not in INTERNAL_SERVICE_SCOPES
        assert "schedules:delete" not in INTERNAL_SERVICE_SCOPES
        assert "schedules:read" in INTERNAL_SERVICE_SCOPES
