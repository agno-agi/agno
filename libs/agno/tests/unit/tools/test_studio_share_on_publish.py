"""Share-on-publish: stage is the visibility model.

Drafts are owner-private; published components are platform-visible and
platform-runnable; mutation stays owner-scoped. These are the cross-user
cases -- one owner builds, another reads, runs, schedules and composes --
that no single-actor test can reach.

Two properties carry most of the weight and are pinned repeatedly:

* Visibility is not readable depth. Publishing puts a component on the
  platform, but it publishes one version; a newer draft above the live
  pointer stays the owner's, on every read path that could return it.
* A refusal must not become an existence oracle. What a caller cannot see
  answers the same not-found an absent id answers, byte for byte; what it
  can see but not touch answers structurally, with the real obstacle.

Uses a real SqliteDb so the adapter predicate is exercised, not mocked.
"""

import json
from typing import Any, Dict

import pytest
from sqlalchemy import text

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
    return SqliteDb(id="share-db", db_file=str(tmp_path / "share.db"))


@pytest.fixture
def studio(db):
    registry = Registry(
        name="Share Registry",
        tools=[CalculatorTools()],
        models=[OpenAIResponses(id="gpt-5.5")],
        dbs=[db],
    )
    return StudioTools(registry=registry, db=db, schedules=True)


def _loads(raw: str) -> Dict[str, Any]:
    return json.loads(raw)


def _data(raw: str) -> Dict[str, Any]:
    out = json.loads(raw)
    assert out.get("ok") is True, out
    return out["data"]


def _error(raw: str) -> Dict[str, Any]:
    out = json.loads(raw)
    assert out.get("ok") is False, out
    return out["error"]


@pytest.fixture
def radar(studio):
    """Alice's published agent with a newer draft above the live pointer.

    The shape the whole feature turns on: v1 is what the platform runs, v2 is
    Alice's work in progress.
    """
    created = _data(studio.create_agent(name="Radar", instructions="v1", publish=True, _agno_run_context=ALICE))
    studio.edit_agent(created["id"], instructions="v2 draft", _agno_run_context=ALICE)
    return created["id"]


@pytest.fixture
def secret(studio):
    """Alice's draft-only agent: on the platform for nobody."""
    return _data(studio.create_agent(name="Secret", instructions="s", publish=False, _agno_run_context=ALICE))["id"]


class TestVisibility:
    def test_b_sees_a_published_component(self, studio, radar):
        assert _data(studio.get_component(radar, _agno_run_context=BOB))["id"] == radar

    def test_b_does_not_see_a_draft_only_component(self, studio, secret):
        assert _error(studio.get_component(secret, _agno_run_context=BOB))["code"] == "component_not_found"

    def test_a_draft_only_404_is_byte_identical_with_an_absent_id(self, studio, secret):
        """The disclosure oracle. The ids differ, so the messages differ by id
        and nothing else -- compare with the id substituted out."""
        draft = studio.get_component(secret, _agno_run_context=BOB)
        absent = studio.get_component("never-minted", _agno_run_context=BOB)
        assert draft.replace(secret, "X") == absent.replace("never-minted", "X")

    def test_b_sees_a_published_component_in_listings(self, studio, radar, secret):
        listed = _data(studio.list_components(_agno_run_context=BOB))
        ids = {row["id"] for row in listed["components"]}
        assert radar in ids
        assert secret not in ids

    def test_b_resolves_a_published_component_by_display_name(self, studio, radar):
        assert _data(studio.get_component("Radar", _agno_run_context=BOB))["id"] == radar

    def test_archived_components_are_invisible_to_b_even_when_published(self, studio, db, radar):
        assert _loads(studio.archive_component(radar, _agno_run_context=ALICE))["ok"]
        assert _error(studio.get_component(radar, _agno_run_context=BOB))["code"] == "component_not_found"
        assert db.get_component(radar, user_id="bob", include_deleted=True) is None
        # The owner keeps her own history under the flag.
        assert db.get_component(radar, user_id="alice", include_deleted=True) is not None

    def test_a_tombstoned_component_is_invisible_to_b(self, studio, db, radar):
        assert db.delete_component(radar, hard_delete=True, user_id="alice") is True
        assert _error(studio.get_component(radar, _agno_run_context=BOB))["code"] == "component_not_found"


class TestPublishedStageOnly:
    def test_b_reads_the_published_config_not_the_newer_draft(self, studio, radar):
        read = _data(studio.get_component(radar, _agno_run_context=BOB))
        assert (read["version"], read["stage"]) == (1, "published")

    def test_a_reads_her_own_newer_draft(self, studio, radar):
        read = _data(studio.get_component(radar, _agno_run_context=ALICE))
        assert (read["version"], read["stage"]) == (2, "draft")

    def test_b_cannot_pin_a_read_to_a_draft_version(self, studio, radar):
        assert _error(studio.get_component(radar, version=2, _agno_run_context=BOB))["code"] == "version_not_found"

    def test_b_can_pin_a_read_to_a_published_version(self, studio, radar):
        assert _data(studio.get_component(radar, version=1, _agno_run_context=BOB))["stage"] == "published"

    def test_b_sees_only_published_version_history(self, studio, radar):
        versions = _data(studio.list_versions(radar, _agno_run_context=BOB))["versions"]
        assert [(v["version"], v["stage"]) for v in versions] == [(1, "published")]

    def test_a_sees_her_whole_version_history(self, studio, radar):
        versions = _data(studio.list_versions(radar, _agno_run_context=ALICE))["versions"]
        assert [(v["version"], v["stage"]) for v in versions] == [(2, "draft"), (1, "published")]

    def test_listing_does_not_disclose_that_a_newer_draft_exists(self, studio, radar):
        row = next(r for r in _data(studio.list_components(_agno_run_context=BOB))["components"] if r["id"] == radar)
        assert row["latest_version"] == 1
        assert row["latest_stage"] == "published"

    def test_the_owners_listing_still_shows_the_draft(self, studio, radar):
        row = next(r for r in _data(studio.list_components(_agno_run_context=ALICE))["components"] if r["id"] == radar)
        assert (row["latest_version"], row["latest_stage"]) == (2, "draft")

    def test_b_cannot_validate_a_draft_version(self, studio, radar):
        assert _error(studio.validate_component(radar, version=2, _agno_run_context=BOB))["code"] == "version_not_found"

    def test_an_unscoped_caller_still_reads_every_stage(self, studio, radar):
        """Direct Python use and tests keep the old semantics."""
        assert _data(studio.get_component(radar))["stage"] == "draft"

    def test_a_shared_components_drafts_stay_readable_by_everyone(self, studio):
        shared = _data(studio.create_agent(name="Shared", instructions="v1", publish=True))["id"]
        studio.edit_agent(shared, instructions="v2")
        read = _data(studio.get_component(shared, _agno_run_context=BOB))
        assert (read["version"], read["stage"]) == (2, "draft")


class TestMutationRefusals:
    @pytest.mark.parametrize(
        "call",
        ["edit_agent", "publish_component", "archive_component", "restore_component", "delete_version"],
    )
    def test_b_is_refused_structurally_on_a_published_component(self, studio, radar, call):
        kwargs = {"_agno_run_context": BOB}
        if call == "edit_agent":
            kwargs["instructions"] = "mine now"
        if call == "delete_version":
            kwargs["version"] = 2
        assert _error(getattr(studio, call)(radar, **kwargs))["code"] == "not_owner"

    def test_the_refusal_names_the_remedy(self, studio, radar):
        message = _error(studio.edit_agent(radar, instructions="x", _agno_run_context=BOB))["message"]
        assert "owned by another user" in message
        assert "ask them or an operator" in message

    def test_a_draft_only_component_still_answers_not_found_on_mutation(self, studio, secret):
        assert (
            _error(studio.edit_agent(secret, instructions="x", _agno_run_context=BOB))["code"] == "component_not_found"
        )

    def test_the_owner_is_unaffected(self, studio, radar):
        assert _loads(studio.edit_agent(radar, instructions="v3", _agno_run_context=ALICE))["ok"]


class TestDispatchAndCompose:
    def test_b_runs_a_published_component(self, studio, radar):
        """Resolution is what this pins; the model layer needs credentials the
        suite has not got, so the assertion is that the gate did not refuse."""
        out = _loads(studio.run_agent(radar, "hi", _agno_run_context=BOB))
        assert out.get("error") != f"Agent not found: {radar}"

    def test_b_is_refused_a_version_pinned_preview_of_a_draft(self, studio, radar):
        out = _loads(studio.run_agent(radar, "hi", version=2, _agno_run_context=BOB))
        assert out["error"]["code"] == "component_not_found", out

    def test_a_may_preview_her_own_draft(self, studio, radar):
        out = _loads(studio.run_agent(radar, "hi", version=2, _agno_run_context=ALICE))
        assert out.get("error", {}) != {"code": "component_not_found"}

    def test_b_composes_a_published_component_into_a_team(self, studio, radar):
        team = _loads(
            studio.create_team(
                name="Bob Team", instructions="i", member_ids=[radar], publish=True, _agno_run_context=BOB
            )
        )
        assert team["ok"], team


class TestSchedulesAcrossOwners:
    def test_b_schedules_a_published_component_and_the_archive_disables_it(self, studio, db, radar):
        sched = _data(
            studio.create_schedule(
                name="bob-weekly",
                cron="0 9 * * 1",
                target_type="agent",
                target_id=radar,
                message="report",
                _agno_run_context=BOB,
            )
        )
        schedule_id = sched.get("schedule_id") or sched.get("id")
        archived = _loads(studio.archive_component(radar, _agno_run_context=ALICE))
        assert archived["ok"], archived
        # Alice's archive reaches Bob's schedule, and says only how many.
        assert any("schedule" in w for w in archived.get("warnings", []))
        row = db.get_schedule(schedule_id)
        assert row is not None
        assert row.get("enabled") is False or row.get("disabled_reason")


class TestDependentRedactionAcrossOwners:
    def test_a_dependent_a_cannot_see_is_a_count_not_a_name(self, studio, radar):
        _data(
            studio.create_team(
                name="alice-dep", instructions="i", member_ids=[radar], publish=True, _agno_run_context=ALICE
            )
        )
        _data(
            studio.create_team(
                name="bob-dep", instructions="i", member_ids=[radar], publish=False, _agno_run_context=BOB
            )
        )
        error = _error(studio.archive_component(radar, _agno_run_context=ALICE))
        assert error["code"] == "dependency_conflict"
        assert "alice-dep" in error["message"]
        assert "bob-dep" not in error["message"]
        assert "1 other component" in error["message"]


class TestNameCollisionsAcrossOwners:
    def test_each_owner_resolves_their_own_component_first(self, studio, radar):
        _data(
            studio.create_agent(
                name="Radar", component_id="radar-bob", instructions="bob", publish=True, _agno_run_context=BOB
            )
        )
        assert _data(studio.get_component("Radar", _agno_run_context=ALICE))["id"] == radar
        assert _data(studio.get_component("Radar", _agno_run_context=BOB))["id"] == "radar-bob"

    def test_a_collision_among_others_is_refused_with_candidates(self, studio, radar):
        _data(
            studio.create_agent(
                name="Radar",
                component_id="radar-carol",
                instructions="c",
                publish=True,
                _agno_run_context=RunContext(run_id="rc", session_id="sc", user_id="carol"),
            )
        )
        error = _error(studio.get_component("Radar", _agno_run_context=BOB))
        assert error["code"] == "ambiguous_reference"
        assert set(error["details"]["candidates"]) == {radar, "radar-carol"}

    def test_b_creating_the_same_display_name_is_refused_on_the_id_not_the_name(self, studio, radar):
        """Policy: the id namespace is global, so the collision is real -- but
        the refusal must be the one B can act on ("pass a different id"), not
        one that sends B to edit a component ownership will then refuse."""
        error = _error(studio.create_agent(name="Radar", instructions="bob", publish=True, _agno_run_context=BOB))
        assert error["code"] == "component_conflict"
        assert error["details"]["reason"] == "id"

    def test_b_can_still_claim_the_display_name_with_its_own_id(self, studio, radar):
        out = _loads(
            studio.create_agent(
                name="Radar", component_id="radar-bob", instructions="bob", publish=True, _agno_run_context=BOB
            )
        )
        assert out["ok"], out


class TestCorruptPointer:
    def test_a_component_whose_live_version_is_tombstoned_is_visible_but_unreadable(self, studio, db, radar):
        """No API path can produce this -- delete_config refuses a published
        version -- so it is reached by raw SQL, the way legacy data would.
        Visibility keys off the pointer alone, so the row stays on the roster
        and fails at read time rather than costing every catalog read a join."""
        with db.Session() as sess, sess.begin():
            sess.execute(
                text("UPDATE agno_component_configs SET stage = '_deleted' WHERE component_id = :cid AND version = 1"),
                {"cid": radar},
            )
        assert db.get_component(radar, user_id="bob") is not None
        assert _error(studio.get_component(radar, _agno_run_context=BOB))["code"] == "component_not_found"


class TestTheWriteItselfIsOwnerScoped:
    """The python gate is not the only thing standing between a foreign
    caller and the row.

    ``_check_component_access`` reads the component in one call and the
    writers run in a later transaction, so a row that appears in that window
    was never gated. Every writer therefore carries the owner scope into the
    write itself. These neutralise the gate to prove the second layer holds
    on its own -- with the gate as the only guard, all four cases mutate
    Alice's component.
    """

    @pytest.fixture
    def ungated(self, studio, monkeypatch):
        monkeypatch.setattr(type(studio), "_check_component_access", lambda *a, **k: None)
        return studio

    def test_publish_cannot_promote_another_owners_draft(self, ungated, db, radar):
        before = db.get_component(radar)["current_version"]
        out = _loads(ungated.publish_component(radar, _agno_run_context=BOB))
        assert out.get("ok") is False, out
        assert db.get_component(radar)["current_version"] == before

    def test_repoint_cannot_move_another_owners_pointer(self, ungated, db, radar):
        before = db.get_component(radar)["current_version"]
        out = _loads(ungated.set_current_version(radar, version=1, _agno_run_context=BOB))
        assert out.get("ok") is False, out
        assert db.get_component(radar)["current_version"] == before

    def test_delete_version_cannot_tombstone_another_owners_draft(self, ungated, db, radar):
        before = [(c["version"], c["stage"]) for c in db.list_configs(radar, include_config=False)]
        draft = max(v for v, stage in before if stage == "draft")
        out = _loads(ungated.delete_version(radar, version=draft, _agno_run_context=BOB))
        assert out.get("ok") is False, out
        assert [(c["version"], c["stage"]) for c in db.list_configs(radar, include_config=False)] == before

    def test_edit_cannot_append_a_draft_to_another_owners_component(self, ungated, db, radar):
        before = [c["version"] for c in db.list_configs(radar, include_config=False)]
        out = _loads(ungated.edit_agent(radar, instructions="mine now", _agno_run_context=BOB))
        assert out.get("ok") is False, out
        assert [c["version"] for c in db.list_configs(radar, include_config=False)] == before

    def test_the_owner_is_unaffected(self, ungated, db, radar):
        """The scope refuses a foreign writer, not every writer."""
        out = _loads(ungated.publish_component(radar, _agno_run_context=ALICE))
        assert out.get("ok") is True, out


class TestANameLookupFindsTheCallersOwnRow:
    """Display-name resolution reads a window of newest-first rows and filters
    for the caller's own afterwards. Share-on-publish makes same-named rows
    from other owners ordinary, so a caller whose component is older than a
    window's worth of them stopped being able to reach it by name.
    """

    def test_an_owned_row_behind_a_page_of_others_still_resolves(self, studio, db):
        mine = _data(studio.create_agent(name="Radar", instructions="mine", _agno_run_context=ALICE))["id"]
        for index in range(25):
            _data(
                studio.create_agent(
                    name="Radar",
                    component_id=f"bob-radar-{index}",
                    instructions="theirs",
                    publish=True,
                    _agno_run_context=BOB,
                )
            )

        out = _loads(studio.get_component("Radar", _agno_run_context=ALICE))
        assert out.get("ok") is True, out
        assert out["data"]["id"] == mine
