"""Identity and ownership threading through StudioTools.

The Studio 3.0 identity contract: every
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
    return StudioTools(registry=registry, db=db, schedules=True)


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


# ----------------------------------------------------------------------
# Composition, dispatch, and scheduling respect visibility
# ----------------------------------------------------------------------


class TestComposeAndDispatchVisibility:
    """Stage decides who may reach a component.

    A draft is the owner's alone: invisible to compose, run, schedule and name
    lookup on every surface, and its refusal is the same not-found an absent id
    produces, so the draft's existence is never disclosed. Publishing puts the
    component on the platform, and from then on any actor may compose, run and
    schedule it -- while still being unable to edit it. Shared (unowned) rows
    stay usable by everyone; the owner keeps full use of their own."""

    def _draft_agent(self, studio):
        """Alice's draft-only agent: on the platform for nobody but Alice."""
        return _create(studio, "Private Agent", ALICE, publish=False)["id"]

    def _published_agent(self, studio, name="Published Agent"):
        return _create(studio, name, ALICE, publish=True)["id"]

    def test_team_compose_with_foreign_draft_is_not_found(self, studio):
        draft_id = self._draft_agent(studio)
        out = _loads(
            studio.create_team(name="bob-team", instructions="i", member_ids=[draft_id], _agno_run_context=BOB)
        )
        assert out["error"]["code"] == "component_not_found", out

    def test_team_compose_with_foreign_published_member_succeeds(self, studio):
        published_id = self._published_agent(studio)
        out = _loads(
            studio.create_team(
                name="bob-team", instructions="i", member_ids=[published_id], publish=True, _agno_run_context=BOB
            )
        )
        assert out["ok"], out

    def test_edit_team_with_foreign_draft_member_is_not_found(self, studio):
        draft_id = self._draft_agent(studio)
        own = _create(studio, "Bobs Member", BOB, publish=True)["id"]
        team = _data(
            studio.create_team(
                name="bob-editable", instructions="i", member_ids=[own], publish=True, _agno_run_context=BOB
            )
        )
        out = _loads(studio.edit_team(team["id"], member_ids=[own, draft_id], _agno_run_context=BOB))
        assert out["error"]["code"] == "component_not_found", out

    def test_edit_team_can_add_a_foreign_published_member(self, studio):
        published_id = self._published_agent(studio)
        own = _create(studio, "Bobs Member", BOB, publish=True)["id"]
        team = _data(
            studio.create_team(
                name="bob-editable", instructions="i", member_ids=[own], publish=True, _agno_run_context=BOB
            )
        )
        out = _loads(studio.edit_team(team["id"], member_ids=[own, published_id], _agno_run_context=BOB))
        assert out["ok"], out

    def test_workflow_step_with_foreign_draft_agent_is_not_found(self, studio):
        draft_id = self._draft_agent(studio)
        out = _loads(
            studio.create_workflow(name="bob-flow", steps=[{"name": "s1", "agent_id": draft_id}], _agno_run_context=BOB)
        )
        assert out["error"]["code"] == "component_not_found", out

    def test_workflow_step_with_foreign_published_agent_succeeds(self, studio):
        published_id = self._published_agent(studio)
        out = _loads(
            studio.create_workflow(
                name="bob-flow",
                steps=[{"name": "s1", "agent_id": published_id}],
                publish=True,
                _agno_run_context=BOB,
            )
        )
        assert out["ok"], out

    def test_run_answers_identical_not_found_for_a_foreign_draft_and_an_absent_id(self, studio):
        """The disclosure oracle, on the half that still holds.

        A published component is now findable by design, so the pairing that
        matters is a foreign draft against an id that was never minted: those
        two must stay byte-identical, or the refusal reveals that the draft
        exists."""
        draft_id = self._draft_agent(studio)
        run_draft = _loads(studio.run_agent(draft_id, "hi", _agno_run_context=BOB))
        run_absent = _loads(studio.run_agent("never-minted", "hi", _agno_run_context=BOB))
        assert run_draft["error"] == f"Agent not found: {draft_id}"
        assert run_absent["error"] == "Agent not found: never-minted"

    def test_run_reaches_a_foreign_published_component(self, studio):
        """Resolution, not the model, is what this pins: the dispatch gate lets
        another owner's published component through. What the model does next is
        another layer's concern (and needs credentials this suite has not got)."""
        published_id = self._published_agent(studio)
        out = _loads(studio.run_agent(published_id, "hi", _agno_run_context=BOB))
        assert out.get("error") != f"Agent not found: {published_id}", out

    @pytest.mark.asyncio
    async def test_async_run_is_gated_for_a_foreign_draft(self, studio):
        draft_id = self._draft_agent(studio)
        out = _loads(await studio._runner_tools.arun_agent(draft_id, "hi", _agno_run_context=BOB))
        assert out["error"] == f"Agent not found: {draft_id}"

    @pytest.mark.asyncio
    async def test_async_run_reaches_a_foreign_published_component(self, studio):
        published_id = self._published_agent(studio)
        out = _loads(await studio._runner_tools.arun_agent(published_id, "hi", _agno_run_context=BOB))
        assert out.get("error") != f"Agent not found: {published_id}", out

    def test_schedule_target_is_gated_for_a_foreign_draft(self, studio):
        draft_id = self._draft_agent(studio)
        out = _loads(
            studio.create_schedule(
                name="bob-sched",
                cron="0 9 * * *",
                target_type="agent",
                target_id=draft_id,
                message="m",
                _agno_run_context=BOB,
            )
        )
        assert out["error"]["code"] == "component_not_found", out

    def test_b_schedules_a_foreign_published_component(self, studio):
        published_id = self._published_agent(studio)
        out = _loads(
            studio.create_schedule(
                name="bob-sched",
                cron="0 9 * * *",
                target_type="agent",
                target_id=published_id,
                message="m",
                _agno_run_context=BOB,
            )
        )
        assert out["ok"], out

    def test_shared_component_stays_composable_and_runnable(self, studio):
        shared_id = _create(studio, "Shared Agent", None, publish=True)["id"]
        team = _loads(
            studio.create_team(
                name="bob-shared-team",
                instructions="i",
                member_ids=[shared_id],
                publish=True,
                _agno_run_context=BOB,
            )
        )
        assert team["ok"], team

    def test_owner_composes_own_private_member(self, studio):
        # Alice's draft is hers to build on. The team stays a draft too: the
        # separate publish gate refuses a published parent pinning a draft
        # child, and that rule is not what this test is about.
        draft_id = self._draft_agent(studio)
        team = _loads(
            studio.create_team(
                name="alice-own-team",
                instructions="i",
                member_ids=[draft_id],
                publish=False,
                _agno_run_context=ALICE,
            )
        )
        assert team["ok"], team

    def test_foreign_draft_name_does_not_resolve(self, studio):
        # A draft is invisible by name as well as by id: name lookup resolves
        # inside the caller's visibility, and a draft is not in it.
        self._draft_agent(studio)
        out = _loads(
            studio.create_team(
                name="bob-name-team", instructions="i", member_ids=["Private Agent"], _agno_run_context=BOB
            )
        )
        assert out["error"]["code"] == "component_not_found", out

    def test_foreign_published_name_resolves(self, studio):
        self._published_agent(studio, name="Radar")
        out = _loads(
            studio.create_team(
                name="bob-name-team",
                instructions="i",
                member_ids=["Radar"],
                publish=True,
                _agno_run_context=BOB,
            )
        )
        assert out["ok"], out

    def test_archive_refusal_names_only_visible_dependents(self, studio, db):
        """A dependent Alice cannot see is a count, never a name.

        Bob's dependent is left a DRAFT on purpose: a published one would be
        visible to Alice under the platform rule, and naming it would then be
        correct rather than a leak."""
        published_id = self._published_agent(studio)
        _data(
            studio.create_team(
                name="alice-dep-team",
                instructions="i",
                member_ids=[published_id],
                publish=True,
                _agno_run_context=ALICE,
            )
        )
        _data(
            studio.create_team(
                name="bob-dep-team",
                instructions="i",
                member_ids=[published_id],
                publish=False,
                _agno_run_context=BOB,
            )
        )
        out = _loads(studio.archive_component(published_id, _agno_run_context=ALICE))
        assert out["error"]["code"] == "dependency_conflict", out
        assert "alice-dep-team" in out["error"]["message"]
        assert "bob-dep-team" not in out["error"]["message"]
        assert "1 other component" in out["error"]["message"]

    def test_runner_listing_shows_published_and_hides_foreign_drafts(self, studio):
        draft_id = self._draft_agent(studio)
        published_id = self._published_agent(studio)
        shared_id = _create(studio, "Listed Shared", None, publish=True)["id"]
        listed = _loads(studio._runner_tools.list_agents(_agno_run_context=BOB))
        ids = {row["id"] for row in listed["agents"]}
        assert shared_id in ids
        assert published_id in ids
        assert draft_id not in ids


# ----------------------------------------------------------------------
# Disclosure oracles
# ----------------------------------------------------------------------


class TestDisclosureOracles:
    def test_id_containing_shared_is_not_misclassified(self, studio):
        # The denial code travels structurally; an id containing the word
        # "shared" must not turn a foreign-row refusal into shared_component.
        created = _data(
            studio.create_agent(
                name="Shared Notes Keeper",
                component_id="shared-notes-keeper",
                instructions="i",
                _agno_run_context=ALICE,
            )
        )
        out = _loads(studio.edit_agent(created["id"], instructions="x", _agno_run_context=BOB))
        assert out["error"]["code"] == "component_not_found", out

    def test_restore_answers_not_found_for_a_foreign_draft(self, studio):
        created = _create(studio, "Draft Agent", ALICE, publish=False)
        out = _loads(studio.restore_component(created["id"], _agno_run_context=BOB))
        assert out["error"]["code"] == "component_not_found", out
        assert "not archived" not in str(out["error"]["message"])

    def test_restore_of_a_foreign_published_row_refuses_on_ownership_not_state(self, studio):
        """Bob can see Alice's published component, so hiding it would be a lie.
        What he must not learn is its lifecycle state: "not archived" answers a
        question he was never entitled to ask, and restoring it was not on offer
        either way."""
        created = _create(studio, "Alive Agent", ALICE, publish=True)
        out = _loads(studio.restore_component(created["id"], _agno_run_context=BOB))
        assert out["error"]["code"] == "not_owner", out
        assert "not archived" not in str(out["error"]["message"])

    def test_scoped_caller_resolves_own_name_despite_foreign_duplicate(self, studio):
        _data(
            studio.create_agent(
                name="Report Bot", component_id="alice-report-bot", instructions="i", _agno_run_context=ALICE
            )
        )
        _data(
            studio.create_agent(
                name="Report Bot", component_id="bob-report-bot", instructions="i", _agno_run_context=BOB
            )
        )
        got = _loads(studio.get_component("Report Bot", _agno_run_context=ALICE))
        assert got["ok"], got
        assert got["data"]["id"] == "alice-report-bot"

    def test_ambiguity_candidates_never_name_foreign_rows(self, studio):
        # Two shared rows with one name are genuinely ambiguous for bob; a
        # foreign private row must not appear among the candidates.
        _data(studio.create_agent(name="Same Name", component_id="shared-one", instructions="i"))
        _data(
            studio.create_team(
                name="Same Name",
                component_id="shared-two",
                instructions="i",
                member_ids=["shared-one"],
                _agno_run_context=None,
            )
        )
        _data(
            studio.create_agent(
                name="Same Name", component_id="alices-hidden", instructions="i", _agno_run_context=ALICE
            )
        )
        out = _loads(studio.get_component("Same Name", _agno_run_context=BOB))
        assert out["error"]["code"] == "ambiguous_reference", out
        assert "alices-hidden" not in out["error"].get("details", {}).get("candidates", [])


class TestRoundThreeTenancy:
    def test_scoped_owner_edits_own_component_by_name(self, studio):
        # B5: two owners, same display name; each resolves their OWN by name.
        _data(
            studio.create_agent(name="Report Bot", component_id="alice-bot", instructions="i", _agno_run_context=ALICE)
        )
        _data(studio.create_agent(name="Report Bot", component_id="bob-bot", instructions="i", _agno_run_context=BOB))
        out = _loads(studio.edit_agent("Report Bot", description="mine", _agno_run_context=ALICE))
        assert out["ok"], out
        assert out["data"]["id"] == "alice-bot"
        other = _loads(studio.edit_agent("Report Bot", description="hers", _agno_run_context=BOB))
        assert other["data"]["id"] == "bob-bot"

    def test_delete_version_cannot_touch_foreign_draft_under_archive(self, studio):
        # B6: an archived component's owner check must still fire.
        _data(
            studio.create_agent(
                name="a", component_id="alice-a", instructions="i", publish=True, _agno_run_context=ALICE
            )
        )
        _data(studio.edit_agent("alice-a", instructions="v2", _agno_run_context=ALICE))
        _data(studio.archive_component("alice-a", _agno_run_context=ALICE))
        out = _loads(studio.delete_version("alice-a", 2, _agno_run_context=BOB))
        assert out["error"]["code"] == "component_not_found"
        # The owner is refused too, but for the honest reason: an archived
        # component's history is frozen so restore can bring every version
        # back. The two refusals differ, which is the point - a foreign caller
        # still learns nothing about the row.
        owner = _loads(studio.delete_version("alice-a", 2, _agno_run_context=ALICE))
        assert owner["error"]["code"] == "component_archived"
        # ...and restoring first makes it work again.
        assert _loads(studio.restore_component("alice-a", _agno_run_context=ALICE))["ok"]
        assert _loads(studio.delete_version("alice-a", 2, _agno_run_context=ALICE))["ok"]


class TestDispatchVisibilityAllSurfaces:
    """Mutation-killers: the stage gate must hold on EVERY run and list
    surface, not just run_agent. A leak here passed the prior suite.

    Each surface is pinned twice -- a foreign draft is refused, a foreign
    published component is reached -- because a gate that refuses everything
    passes the first half on its own."""

    def _alice_member(self, studio):
        return _data(
            studio.create_agent(
                name="Sec M", component_id="sec-m", instructions="m", publish=True, _agno_run_context=ALICE
            )
        )["id"]

    def _alice(self, studio, kind="agent", publish=False):
        """Alice's component of ``kind``. A draft parent keeps a published
        member, so only the parent's own stage is under test."""
        if kind == "agent":
            return _data(
                studio.create_agent(
                    name="Sec A",
                    component_id="sec-a",
                    instructions="ALICE",
                    publish=publish,
                    _agno_run_context=ALICE,
                )
            )["id"]
        member = self._alice_member(studio)
        if kind == "team":
            return _data(
                studio.create_team(
                    name="Sec T",
                    component_id="sec-t",
                    instructions="i",
                    member_ids=[member],
                    publish=publish,
                    _agno_run_context=ALICE,
                )
            )["id"]
        return _data(
            studio.create_workflow(
                name="Sec W",
                component_id="sec-w",
                steps=[{"name": "s", "agent_id": member}],
                publish=publish,
                _agno_run_context=ALICE,
            )
        )["id"]

    def test_run_team_gated_for_a_foreign_draft(self, studio):
        tid = self._alice(studio, "team")
        assert _loads(studio.run_team(tid, "hi", _agno_run_context=BOB))["error"] == f"Team not found: {tid}"

    def test_run_team_reaches_a_foreign_published_team(self, studio):
        tid = self._alice(studio, "team", publish=True)
        out = _loads(studio.run_team(tid, "hi", _agno_run_context=BOB))
        assert out.get("error") != f"Team not found: {tid}", out

    def test_run_workflow_gated_for_a_foreign_draft(self, studio):
        wid = self._alice(studio, "workflow")
        assert _loads(studio.run_workflow(wid, "hi", _agno_run_context=BOB))["error"] == f"Workflow not found: {wid}"

    def test_run_workflow_reaches_a_foreign_published_workflow(self, studio):
        wid = self._alice(studio, "workflow", publish=True)
        out = _loads(studio.run_workflow(wid, "hi", _agno_run_context=BOB))
        assert out.get("error") != f"Workflow not found: {wid}", out

    @pytest.mark.asyncio
    async def test_async_run_team_gated_for_a_foreign_draft(self, studio):
        tid = self._alice(studio, "team")
        out = _loads(await studio.arun_team(tid, "hi", _agno_run_context=BOB))
        assert out["error"] == f"Team not found: {tid}"

    @pytest.mark.asyncio
    async def test_async_run_team_reaches_a_foreign_published_team(self, studio):
        tid = self._alice(studio, "team", publish=True)
        out = _loads(await studio.arun_team(tid, "hi", _agno_run_context=BOB))
        assert out.get("error") != f"Team not found: {tid}", out

    def test_list_teams_hides_foreign_drafts(self, studio):
        tid = self._alice(studio, "team")
        listed = _loads(studio._runner_tools.list_teams(_agno_run_context=BOB))
        assert all(row["id"] != tid for row in listed["teams"])

    def test_list_teams_shows_foreign_published(self, studio):
        tid = self._alice(studio, "team", publish=True)
        listed = _loads(studio._runner_tools.list_teams(_agno_run_context=BOB))
        assert any(row["id"] == tid for row in listed["teams"])

    def test_edit_workflow_with_foreign_draft_step_member_not_found(self, studio):
        member = _data(
            studio.create_agent(
                name="Priv Step", component_id="priv-step", instructions="i", publish=False, _agno_run_context=ALICE
            )
        )["id"]
        own = _data(
            studio.create_agent(
                name="Bob Step", component_id="bob-step", instructions="i", publish=True, _agno_run_context=BOB
            )
        )["id"]
        wf = _data(
            studio.create_workflow(
                name="Bob WF",
                component_id="bob-wf",
                steps=[{"name": "s", "agent_id": own}],
                publish=True,
                _agno_run_context=BOB,
            )
        )["id"]
        out = _loads(studio.edit_workflow(wf, steps=[{"name": "s", "agent_id": member}], _agno_run_context=BOB))
        assert out["error"]["code"] == "component_not_found"

    def test_edit_workflow_can_use_a_foreign_published_step_member(self, studio):
        member = _data(
            studio.create_agent(
                name="Pub Step", component_id="pub-step", instructions="i", publish=True, _agno_run_context=ALICE
            )
        )["id"]
        own = _data(
            studio.create_agent(
                name="Bob Step", component_id="bob-step", instructions="i", publish=True, _agno_run_context=BOB
            )
        )["id"]
        wf = _data(
            studio.create_workflow(
                name="Bob WF",
                component_id="bob-wf",
                steps=[{"name": "s", "agent_id": own}],
                publish=True,
                _agno_run_context=BOB,
            )
        )["id"]
        out = _loads(studio.edit_workflow(wf, steps=[{"name": "s", "agent_id": member}], _agno_run_context=BOB))
        assert out["ok"], out
