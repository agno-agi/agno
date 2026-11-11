"""Liveness guards on the component catalog, and the schedule cascade.

Four shapes the catalog has to hold, none of which the stage machinery alone
gives it:

1. A gate that reads a config's STAGE has not read whether the component
   behind it is still live: a config keeps its published stage after its
   component is archived. Promoting a version that pins an archived child - or
   pointing current_version at one - ships a parent that loads with that member
   missing.
2. A pin belongs to an ACTIVE parent. A parent that is archived cannot
   dispatch, so it must not hold a child's draft hostage; a parent whose rows
   are merely absent keeps its pin, because absence is not evidence.
3. Archiving a component and silencing the schedules aimed at it are one
   transaction on every surface that archives, not only on the surfaces that
   remember to call the cascade.
4. Every guard above is a read, and a read is only worth what the write that
   follows it re-asserts.

The concurrency tests interleave deterministically, never probabilistically:
one writer is held at its first write by a before_cursor_execute hook while
the counterpart commits on a second connection, then resumed.
"""

import threading
import time

import pytest
from sqlalchemy import event, select

from agno.db.base import (
    DELETED_CONFIG_STAGE,
    ComponentArchivedError,
    ComponentDependencyError,
    ComponentDraftRequiredError,
    ComponentLastConfigError,
    ComponentType,
)
from agno.db.schemas.scheduler import build_run_endpoint
from agno.db.sqlite import SqliteDb


def _agent(db, component_id, stage="published"):
    db.create_component_with_config(
        component_id=component_id,
        component_type=ComponentType.AGENT,
        name=component_id,
        config={"name": component_id, "id": component_id},
        stage=stage,
    )


def _team(db, component_id, stage="published", links=None):
    db.create_component_with_config(
        component_id=component_id,
        component_type=ComponentType.TEAM,
        name=component_id,
        config={"name": component_id, "id": component_id},
        stage=stage,
        links=links,
    )


def _config_stages(db, component_id):
    """Raw (version, stage) rows: the readers hide an archived component."""
    configs_table = db._get_table(table_type="component_configs")
    with db.Session() as sess:
        rows = sess.execute(
            select(configs_table.c.version, configs_table.c.stage)
            .where(configs_table.c.component_id == component_id)
            .order_by(configs_table.c.version)
        ).fetchall()
    return [(row.version, row.stage) for row in rows]


def _member(child_id, version=1):
    return {
        "link_kind": "member",
        "link_key": child_id,
        "child_component_id": child_id,
        "child_version": version,
        "position": 0,
    }


class _HoldFirstWrite:
    """Hold a writer at its first write so a counterpart can commit under it.

    SQLite opens the transaction at that write, so everything the writer read
    before it was read outside any transaction: this is the exact interleave a
    check-then-write guard loses.
    """

    def __init__(self, engine):
        self.engine = engine
        self.reached = threading.Event()
        self.resume = threading.Event()
        self._armed = True
        self.statement = None

    def _hook(self, conn, cursor, statement, parameters, context, executemany):
        if self._armed and statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            self._armed = False
            self.statement = statement.splitlines()[0]
            self.reached.set()
            assert self.resume.wait(timeout=20), "counterpart never committed"

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._hook)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._hook)
        return False


def _interleave(writer_db, writer_fn, counterpart_fn):
    """Run writer_fn held at its first write; counterpart_fn commits between."""
    outcome: dict = {}

    def writer():
        try:
            outcome["result"] = writer_fn()
        except Exception as e:
            outcome["error"] = e
        finally:
            writer_db.Session.remove()

    with _HoldFirstWrite(writer_db.db_engine) as hold:
        thread = threading.Thread(target=writer)
        thread.start()
        assert hold.reached.wait(timeout=20), "writer never reached its first write"
        counterpart_fn()
        hold.resume.set()
        thread.join(timeout=30)
        assert not thread.is_alive()
    return outcome


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="liveness-guards", db_file=str(tmp_path / "liveness.db"))


@pytest.fixture
def dbs(tmp_path):
    """Two adapters on one file: two connections, two transactions."""
    path = str(tmp_path / "liveness-race.db")
    return SqliteDb(id="liveness-a", db_file=path), SqliteDb(id="liveness-b", db_file=path)


class TestPromoteGateReadsChildLiveness:
    """A version cannot go live pinning an archived child."""

    def _squad_with_archived_member(self, db):
        # v1 has no members, so archiving the parent, then the child, then
        # restoring the parent is the sanctioned sequence; v2 keeps the pin.
        _agent(db, "member-a")
        _team(db, "squad", stage="published")
        db.upsert_config("squad", config={"name": "squad", "id": "squad"}, stage="draft", links=[_member("member-a")])
        assert db.delete_component("squad") is True
        assert db.delete_component("member-a") is True
        assert db.restore_component("squad") is True
        assert db.get_component("member-a", include_deleted=True)["deleted_at"] is not None

    def test_publish_refuses_a_version_that_pins_an_archived_child(self, db):
        self._squad_with_archived_member(db)

        with pytest.raises(ComponentDependencyError, match="member-a"):
            db.upsert_config("squad", version=2, stage="published")

        assert db.get_component("squad")["current_version"] == 1
        assert db.get_config("squad", version=2)["stage"] == "draft"

    def test_set_current_version_refuses_a_version_that_pins_an_archived_child(self, db):
        _agent(db, "member-b")
        _team(db, "mom", stage="published", links=[_member("member-b")])
        db.upsert_config("mom", config={"name": "mom", "id": "mom"}, stage="published", links=[])
        assert db.get_component("mom")["current_version"] == 2
        assert db.delete_component("mom") is True
        assert db.delete_component("member-b") is True
        assert db.restore_component("mom") is True

        with pytest.raises(ComponentDependencyError, match="member-b"):
            db.set_current_version("mom", 1)

        assert db.get_component("mom")["current_version"] == 2

    def test_publish_and_pointer_moves_still_work_with_a_live_child(self, db):
        _agent(db, "member-c")
        _team(db, "crew", stage="published", links=[_member("member-c")])
        db.upsert_config("crew", config={"name": "crew", "id": "crew"}, stage="draft", links=[_member("member-c")])

        assert db.upsert_config("crew", version=2, stage="published")["stage"] == "published"
        assert db.set_current_version("crew", 1) is True
        assert db.get_component("crew")["current_version"] == 1

    def test_a_child_with_no_catalog_row_stays_writable(self, db):
        # A code-defined member has no components row. Absence is not an
        # archive: the liveness predicate keys on a row that exists.
        _team(db, "hybrid", stage="draft")
        assert db.get_component("code-defined", include_deleted=True) is None

        config = db.upsert_config(
            "hybrid",
            config={"name": "hybrid", "id": "hybrid"},
            stage="draft",
            links=[_member("code-defined")],
        )
        assert config["stage"] == "draft"


class TestOnlyActiveParentsPinAVersion:
    """delete_config releases a pin only when the parent is proven inactive."""

    def _worker_pinned_by(self, db, parent_id, parent_stage="draft"):
        _agent(db, "worker")
        db.upsert_config("worker", config={"name": "worker", "id": "worker", "v": 2}, stage="draft")
        _team(db, parent_id, stage=parent_stage, links=[_member("worker", version=2)])

    def test_an_archived_parent_no_longer_pins_a_draft(self, db):
        self._worker_pinned_by(db, "old-team")
        assert db.delete_component("old-team") is True

        assert db.delete_config("worker", 2) is True
        assert db.get_config("worker", version=2, include_deleted=True)["stage"] == DELETED_CONFIG_STAGE

    def test_a_live_draft_parent_still_pins(self, db):
        self._worker_pinned_by(db, "live-team")

        with pytest.raises(ComponentDependencyError, match="live-team"):
            db.delete_config("worker", 2)

    def test_a_missing_parent_config_row_does_not_release_the_pin(self, db):
        # The parent's own config row goes; its component row and the link stay.
        # Nothing there says the parent is gone, so the pin holds.
        self._worker_pinned_by(db, "live-team")
        configs_table = db._get_table(table_type="component_configs")
        with db.Session() as sess, sess.begin():
            sess.execute(configs_table.delete().where(configs_table.c.component_id == "live-team"))

        with pytest.raises(ComponentDependencyError, match="live-team"):
            db.delete_config("worker", 2)

    def test_the_pin_check_runs_on_the_open_transaction(self, db):
        # A nested self.get_dependents() would begin a second transaction on
        # this scoped session and raise InvalidRequestError instead.
        self._worker_pinned_by(db, "old-team")
        assert db.delete_component("old-team") is True
        assert db.delete_config("worker", 2) is True


def _arm_schedule(db, schedule_id, target_type, target_id, tagged=True):
    """An enabled, already-due schedule aimed at a component."""
    row = {
        "id": schedule_id,
        "name": schedule_id,
        "user_id": "u1",
        "cron_expr": "* * * * *",
        "endpoint": build_run_endpoint(target_type, target_id),
        "method": "POST",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "next_run_at": int(time.time()) - 60,
        "created_at": int(time.time()),
    }
    if tagged:
        row.update({"managed_by": "studio", "target_type": target_type, "target_id": target_id})
    db.create_schedule(row)
    return schedule_id


class TestDeleteComponentCascadesSchedules:
    """The cascade rides the delete, so every delete surface carries it."""

    def test_archive_disables_the_schedules_aimed_at_the_target(self, db):
        _agent(db, "analyst")
        _arm_schedule(db, "sched-tagged", "agent", "analyst")

        assert db.delete_component("analyst") is True

        row = db.get_schedule("sched-tagged")
        assert row["enabled"] in (False, 0)
        assert row["disabled_reason"] == "target_archived:agent:analyst"
        assert db.claim_due_schedule(worker_id="poller-1") is None

    def test_hard_delete_disables_them_too(self, db):
        _agent(db, "gone")
        _arm_schedule(db, "sched-hard", "agent", "gone")

        assert db.delete_component("gone", hard_delete=True) is True

        assert db.get_schedule("sched-hard")["enabled"] in (False, 0)

    def test_untagged_rows_on_the_run_endpoint_are_disabled_as_well(self, db):
        _agent(db, "endpointed")
        _arm_schedule(db, "sched-generic", "agent", "endpointed", tagged=False)

        assert db.delete_component("endpointed") is True

        assert db.get_schedule("sched-generic")["enabled"] in (False, 0)

    def test_the_sdk_delete_carries_the_cascade(self, db):
        from agno.agent import Agent

        agent = Agent(id="sdk-agent", name="SDK Agent", db=db)
        agent.save(db=db)
        _arm_schedule(db, "sched-sdk", "agent", "sdk-agent")

        agent.delete(db=db)

        assert db.get_component("sdk-agent") is None
        assert db.get_schedule("sched-sdk")["enabled"] in (False, 0)

    def test_a_cascade_failure_rolls_the_delete_back(self, db, monkeypatch):
        # Half-applied is the state the guard exists to prevent: an archived
        # component whose schedules are still armed.
        _agent(db, "brittle")
        _arm_schedule(db, "sched-brittle", "agent", "brittle")

        def boom(*args, **kwargs):
            raise RuntimeError("schedules table unavailable")

        monkeypatch.setattr(SqliteDb, "_disable_schedules_for_target_in_session", boom)

        with pytest.raises(RuntimeError):
            db.delete_component("brittle")

        assert db.get_component("brittle") is not None
        assert db.get_schedule("sched-brittle")["enabled"] in (True, 1)

    def test_a_component_without_any_schedules_table_still_archives(self, db):
        _agent(db, "lonely")
        assert db._get_table(table_type="schedules") is None

        assert db.delete_component("lonely") is True
        assert db.get_component("lonely") is None


class TestGuardsRideTheWrite:
    """Each guard is re-asserted by, or over, the write it protects."""

    def _versioned(self, db, cid):
        _agent(db, cid)
        db.upsert_config(cid, config={"name": cid, "v": 2}, stage="draft")
        return cid

    def test_a_publish_overtaken_by_an_archive_is_rolled_back(self, dbs):
        writer, archiver = dbs
        cid = self._versioned(writer, "pub-race")

        outcome = _interleave(
            writer,
            lambda: writer.upsert_config(cid, version=2, config={"name": "renamed-late"}, stage="published"),
            lambda: archiver.delete_component(cid),
        )

        assert isinstance(outcome.get("error"), ComponentArchivedError), outcome
        row = archiver.get_component(cid, include_deleted=True)
        assert row["name"] == cid  # the archived row kept its pre-archive state
        assert row["current_version"] == 1
        assert _config_stages(archiver, cid) == [(1, "published"), (2, "draft")]

    def test_an_append_overtaken_by_an_archive_is_rolled_back(self, dbs):
        writer, archiver = dbs
        cid = self._versioned(writer, "append-race")

        outcome = _interleave(
            writer,
            lambda: writer.upsert_config(cid, config={"name": cid, "v": 3}, stage="draft"),
            lambda: archiver.delete_component(cid),
        )

        assert isinstance(outcome.get("error"), ComponentArchivedError), outcome
        assert _config_stages(archiver, cid) == [(1, "published"), (2, "draft")]

    def _hold_after_commit(self, writer, first_write_prefix):
        """Arm a barrier that pauses `writer` between its COMMIT and its read-back."""
        state = {"armed": False, "fired": False}
        committed, resume = threading.Event(), threading.Event()

        def arm(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(first_write_prefix):
                state["armed"] = True

        def after_commit(sess):
            if state["armed"] and not state["fired"]:
                state["fired"] = True
                committed.set()
                assert resume.wait(timeout=20)

        event.listen(writer.db_engine, "before_cursor_execute", arm)
        event.listen(writer.Session, "after_commit", after_commit)
        return (
            committed,
            resume,
            (
                lambda: (
                    event.remove(writer.Session, "after_commit", after_commit),
                    event.remove(writer.db_engine, "before_cursor_execute", arm),
                )
            ),
        )

    def _run_across_commit(self, writer, work, first_write_prefix, archiver, cid):
        """Run `work` on a thread, archive `cid` after it commits, return its outcome."""
        committed, resume, unhook = self._hold_after_commit(writer, first_write_prefix)
        outcome: dict = {}

        def run():
            try:
                outcome["result"] = work()
            except Exception as e:
                outcome["error"] = e
            finally:
                writer.Session.remove()

        thread = threading.Thread(target=run)
        thread.start()
        try:
            assert committed.wait(timeout=20), "the write never committed"
            assert archiver.delete_component(cid) is True
            resume.set()
            thread.join(timeout=30)
            assert not thread.is_alive()
        finally:
            unhook()
        return outcome

    def test_a_committed_component_upsert_is_not_reported_as_a_failure(self, dbs):
        # upsert_component read its answer back through get_component, which
        # hides archived rows: an archive landing in the post-commit window
        # turned a landed write into "Failed to get component ...".
        writer, archiver = dbs
        _agent(writer, "postcommit-upsert")

        outcome = self._run_across_commit(
            writer,
            lambda: writer.upsert_component(
                component_id="postcommit-upsert",
                component_type=ComponentType.AGENT,
                name="renamed-late",
            ),
            "UPDATE AGNO_COMPONENTS ",
            archiver,
            "postcommit-upsert",
        )

        assert "error" not in outcome, outcome
        assert outcome["result"]["name"] == "renamed-late"

    def test_a_committed_creation_is_not_reported_as_a_failure(self, dbs):
        # Same shape in create_component_with_config, which read BOTH halves of
        # its answer back through the archived-filtering readers.
        writer, archiver = dbs

        outcome = self._run_across_commit(
            writer,
            lambda: writer.create_component_with_config(
                component_id="postcommit-create",
                component_type=ComponentType.AGENT,
                name="postcommit-create",
                config={"name": "postcommit-create"},
                stage="published",
            ),
            "INSERT INTO AGNO_COMPONENTS ",
            archiver,
            "postcommit-create",
        )

        assert "error" not in outcome, outcome
        component, config = outcome["result"]
        assert component["component_id"] == "postcommit-create"
        assert config["version"] == 1

    def test_a_committed_publish_is_not_reported_as_a_failure(self, dbs):
        # The answer is read inside the transaction that wrote it: an archive
        # landing after the commit must not turn a landed publish into an error
        # the routes hand back as a 4xx.
        writer, archiver = dbs
        cid = self._versioned(writer, "postcommit")

        state = {"armed": False, "fired": False}
        committed, resume = threading.Event(), threading.Event()

        def arm(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("UPDATE AGNO_COMPONENTS "):
                state["armed"] = True

        def after_commit(sess):
            if state["armed"] and not state["fired"]:
                state["fired"] = True
                committed.set()
                assert resume.wait(timeout=20)

        event.listen(writer.db_engine, "before_cursor_execute", arm)
        event.listen(writer.Session, "after_commit", after_commit)
        outcome: dict = {}

        def publish():
            try:
                outcome["result"] = writer.upsert_config(cid, version=2, config={"name": "live"}, stage="published")
            except Exception as e:
                outcome["error"] = e

        thread = threading.Thread(target=publish)
        thread.start()
        try:
            assert committed.wait(timeout=20), "the publish never committed"
            assert archiver.delete_component(cid) is True
            resume.set()
            thread.join(timeout=30)
            assert not thread.is_alive()
        finally:
            event.remove(writer.Session, "after_commit", after_commit)
            event.remove(writer.db_engine, "before_cursor_execute", arm)

        assert "error" not in outcome, outcome
        assert outcome["result"]["version"] == 2
        assert outcome["result"]["stage"] == "published"

    def test_delete_config_loses_to_a_publish_of_the_same_version(self, dbs):
        deleter, publisher = dbs
        cid = self._versioned(deleter, "ptr-tomb")
        deleter.upsert_config(cid, config={"name": cid, "v": 3}, stage="draft")

        outcome = _interleave(
            deleter,
            lambda: deleter.delete_config(cid, 2),
            lambda: publisher.upsert_config(cid, version=2, stage="published"),
        )

        assert isinstance(outcome.get("error"), ComponentDraftRequiredError), outcome
        assert publisher.get_component(cid)["current_version"] == 2
        assert publisher.get_config(cid, version=2)["stage"] == "published"
        assert publisher.get_current_config(cid) is not None

    def test_two_deletes_cannot_remove_the_last_visible_version(self, dbs):
        first, second = dbs
        cid = "last-cfg"
        _agent(first, cid, stage="draft")
        first.upsert_config(cid, config={"name": cid, "v": 2}, stage="draft")

        outcome = _interleave(
            first,
            lambda: first.delete_config(cid, 1),
            lambda: second.delete_config(cid, 2),
        )

        assert isinstance(outcome.get("error"), ComponentLastConfigError), outcome
        assert [c["version"] for c in second.list_configs(cid)] == [1]
        assert second.get_latest_config(cid) is not None

    def test_publishing_a_member_link_loses_to_the_archive_of_that_child(self, dbs):
        parent_db, archiver = dbs
        _agent(parent_db, "child-x")
        _team(parent_db, "team-p", stage="draft")
        parent_db.upsert_config("team-p", config={"name": "team-p", "v": 2}, stage="draft")

        outcome = _interleave(
            parent_db,
            lambda: parent_db.upsert_config(
                "team-p", version=2, config={"name": "team-p"}, stage="published", links=[_member("child-x")]
            ),
            lambda: archiver.delete_component("child-x"),
        )

        assert isinstance(outcome.get("error"), ComponentDependencyError), outcome
        assert archiver.get_links("team-p", version=2) == []
        assert archiver.get_component("team-p")["current_version"] is None

    def test_restore_loses_to_the_archive_of_a_pinned_child(self, dbs):
        parent_db, archiver = dbs
        _agent(parent_db, "child-y")
        _team(parent_db, "team-q", stage="published", links=[_member("child-y")])
        assert parent_db.delete_component("team-q") is True

        outcome = _interleave(
            parent_db,
            lambda: parent_db.restore_component("team-q"),
            lambda: archiver.delete_component("child-y"),
        )

        assert isinstance(outcome.get("error"), ComponentDependencyError), outcome
        assert archiver.get_component("team-q") is None  # still archived
        assert archiver.get_component("team-q", include_deleted=True)["deleted_at"] is not None

    def test_a_claim_does_not_overtake_the_archive_cascade(self, dbs):
        worker_db, control_plane = dbs
        _agent(worker_db, "agent-z")
        _arm_schedule(worker_db, "sched-z", "agent", "agent-z")

        outcome = _interleave(
            worker_db,
            lambda: worker_db.claim_due_schedule(worker_id="poller-1"),
            lambda: control_plane.delete_component("agent-z"),
        )

        assert outcome.get("result") is None, outcome
        row = control_plane.get_schedule("sched-z")
        assert row["enabled"] in (False, 0)
        assert row["locked_by"] is None

    def test_a_live_schedule_is_still_claimed(self, dbs):
        worker_db, _ = dbs
        _agent(worker_db, "agent-live")
        _arm_schedule(worker_db, "sched-live", "agent", "agent-live")

        claimed = worker_db.claim_due_schedule(worker_id="poller-1")

        assert claimed is not None
        assert claimed["id"] == "sched-live"
        assert claimed["locked_by"] == "poller-1"
        assert claimed["enabled"] in (True, 1)


def test_dependents_read_shares_one_query_with_the_public_reader(db):
    # delete_component runs the dependents read on its own open transaction;
    # it must give the same answer as the public reader that takes its own.
    _agent(db, "leaf")
    _team(db, "root", stage="draft", links=[_member("leaf")])
    links_table = db._get_table(table_type="component_links")
    components_table = db._get_table(table_type="components")
    configs_table = db._get_table(table_type="component_configs")

    with db.Session() as sess:
        in_session = db._dependents_in_session(
            sess, links_table, components_table, configs_table, "leaf", active_parents_only=True
        )
        assert sess.execute(select(links_table.c.parent_component_id)).fetchall()

    assert [d["parent_component_id"] for d in in_session] == ["root"]
    assert in_session == db.get_dependents("leaf", active_parents_only=True)


class TestAComponentsTypeIsFixedAtCreation:
    """The archive cascade matches schedules on (target_type, target_id), so a
    rewritable type would let a component drift out from under the very
    schedules the cascade exists to disable.

    Widening the cascade to match on the id alone looked like the fix and is
    not: a schedule's target need not be in the catalog at all -- a
    code-defined component of another type can hold the same id -- so an
    id-only match disables other people's working schedules. The type is kept
    honest at the writer instead.
    """

    def test_the_type_cannot_be_rewritten(self, db):
        _agent(db, "fixed")
        with pytest.raises(ValueError, match="fixed at creation"):
            db.upsert_component(component_id="fixed", component_type=ComponentType.TEAM, name="fixed")

    def test_re_upserting_the_same_type_is_fine(self, db):
        """The storage layer re-upserts the type on every save."""
        _agent(db, "steady")
        db.upsert_component(component_id="steady", component_type=ComponentType.AGENT, name="steady renamed")
        assert db.get_component("steady")["name"] == "steady renamed"

    def test_omitting_the_type_is_fine(self, db):
        _agent(db, "quiet")
        db.upsert_component(component_id="quiet", name="quiet renamed")
        assert db.get_component("quiet")["component_type"] == "agent"

    def test_the_cascade_still_disables_its_own_schedules(self, db):
        _agent(db, "cascader")
        _arm_schedule(db, "sched-cascade", "agent", "cascader")
        assert db.delete_component("cascader") is True
        assert db.get_schedule("sched-cascade")["enabled"] in (False, 0)

    def test_a_schedule_on_another_type_with_the_same_id_is_untouched(self, db):
        """The id is unique in the catalog, but a code-defined component of
        another type can hold it -- and its schedules are not this archive's
        to disable."""
        _agent(db, "shared-id")
        _arm_schedule(db, "sched-agent", "agent", "shared-id")
        _arm_schedule(db, "sched-team", "team", "shared-id")

        assert db.delete_component("shared-id") is True

        assert db.get_schedule("sched-agent")["enabled"] in (False, 0)
        assert db.get_schedule("sched-team")["enabled"] in (True, 1)


class TestTheEnableGuardCrossesOwnersLikeTheCascadeDoes:
    """The cascade disables every schedule aimed at the archived component,
    whoever owns it. The enable guard has to read the same target the same
    way, or the one caller whose schedule was disabled is exactly the caller
    allowed to re-arm it.

    Share-on-publish makes this reachable: bob may legitimately schedule
    alice's published agent, and an archived row is invisible to bob.
    """

    def _bobs_schedule_on_alices_archived_agent(self, db):
        db.create_component_with_config(
            component_id="alice-pub",
            component_type=ComponentType.AGENT,
            name="alice-pub",
            config={"name": "alice-pub"},
            stage="published",
            user_id="alice",
        )
        _arm_schedule(db, "bob-sched", "agent", "alice-pub")
        assert db.delete_component("alice-pub", user_id="alice") is True
        return "bob-sched"

    def test_the_cascade_reaches_the_other_owners_schedule(self, db):
        schedule_id = self._bobs_schedule_on_alices_archived_agent(db)
        assert db.get_schedule(schedule_id)["enabled"] in (False, 0)

    def test_the_other_owner_cannot_re_arm_it(self, db):
        from agno.db.schemas.scheduler import Schedule
        from agno.tools.scheduler import archived_target_refusal

        schedule_id = self._bobs_schedule_on_alices_archived_agent(db)
        schedule = Schedule.from_dict(db.get_schedule(schedule_id))

        # bob cannot see the archived row at all -- that is the whole point.
        assert db.get_component("alice-pub", user_id="bob", include_deleted=True) is None
        assert archived_target_refusal(db, schedule, user_id="bob") == ("agent", "alice-pub")

    def test_a_live_target_is_still_enableable(self, db):
        from agno.db.schemas.scheduler import Schedule
        from agno.tools.scheduler import archived_target_refusal

        db.create_component_with_config(
            component_id="alice-live",
            component_type=ComponentType.AGENT,
            name="alice-live",
            config={"name": "alice-live"},
            stage="published",
            user_id="alice",
        )
        _arm_schedule(db, "bob-live", "agent", "alice-live")
        schedule = Schedule.from_dict(db.get_schedule("bob-live"))
        assert archived_target_refusal(db, schedule, user_id="bob") is None


class TestTheVetoIsScopedToParentsTheCallerCanActOn:
    """Publishing shares a component for composing, so any other tenant can
    pin it -- and can do so from a private draft the owner will never see.
    An unscoped veto turns that into a permanent hold on someone else's
    component, with the blocking id redacted and no surface to clear it.

    A parent the caller cannot act on does not get to veto. One it can --
    its own, or an unowned shared one -- still does, and an operator with no
    scope still sees every parent.
    """

    def _pinned(self, db, child_owner, parent_owner):
        db.create_component_with_config(
            component_id="child",
            component_type=ComponentType.AGENT,
            name="child",
            config={"name": "child"},
            stage="published",
            user_id=child_owner,
        )
        db.create_component_with_config(
            component_id="parent",
            component_type=ComponentType.TEAM,
            name="parent",
            config={"name": "parent"},
            stage="draft",
            links=[_member("child")],
            user_id=parent_owner,
        )

    def test_another_owners_parent_does_not_block(self, db):
        self._pinned(db, child_owner="alice", parent_owner="bob")
        assert db.delete_component("child", user_id="alice") is True

    def test_the_callers_own_parent_still_blocks(self, db):
        self._pinned(db, child_owner="alice", parent_owner="alice")
        with pytest.raises(ComponentDependencyError):
            db.delete_component("child", user_id="alice")

    def test_a_shared_parent_still_blocks(self, db):
        self._pinned(db, child_owner="alice", parent_owner=None)
        with pytest.raises(ComponentDependencyError):
            db.delete_component("child", user_id="alice")

    def test_an_unscoped_operator_still_sees_every_parent(self, db):
        self._pinned(db, child_owner="alice", parent_owner="bob")
        with pytest.raises(ComponentDependencyError):
            db.delete_component("child")

    def test_the_hard_delete_is_scoped_the_same_way(self, db):
        self._pinned(db, child_owner="alice", parent_owner="bob")
        assert db.delete_component("child", user_id="alice", hard_delete=True) is True


class TestTheHardDeleteReAssertsItsGuardToo:
    """The friendly dependents read runs before the transaction opens, so a
    parent that pins this component in the gap is invisible to it. The
    archive branch re-asserts inside the write transaction; the hard-delete
    branch did not, and silently deleted the link rows that were the
    evidence.
    """

    def test_a_dependent_added_in_the_gap_rolls_the_hard_delete_back(self, dbs):
        first, second = dbs
        _agent(first, "victim")
        _team(second, "late-parent", stage="draft")

        outcome = _interleave(
            first,
            lambda: first.delete_component("victim", hard_delete=True),
            lambda: second.upsert_config(
                "late-parent", config={"name": "late-parent"}, stage="draft", links=[_member("victim")]
            ),
        )

        assert isinstance(outcome.get("error"), ComponentDependencyError), outcome
        assert second.get_component("victim") is not None


class TestCreatingAPublishedParentReAssertsItsPins:
    """create_component_with_config runs its pin checks before any write and
    takes no lock, so a child archived in the gap left a brand-new PUBLISHED
    parent pinning an archived child -- exactly what upsert_config's publish
    gate raises to prevent, on the one surface that skipped it.
    """

    def test_a_child_archived_in_the_gap_rolls_the_creation_back(self, dbs):
        first, second = dbs
        _agent(second, "doomed-child")

        outcome = _interleave(
            first,
            lambda: first.create_component_with_config(
                component_id="fresh-team",
                component_type=ComponentType.TEAM,
                name="fresh-team",
                config={"name": "fresh-team"},
                stage="published",
                links=[_member("doomed-child")],
            ),
            lambda: second.delete_component("doomed-child"),
        )

        assert isinstance(outcome.get("error"), ComponentDependencyError), outcome
        assert second.get_component("fresh-team", include_deleted=True) is None

    def test_a_live_child_still_creates(self, db):
        _agent(db, "live-child")
        component, _config = db.create_component_with_config(
            component_id="fine-team",
            component_type=ComponentType.TEAM,
            name="fine-team",
            config={"name": "fine-team"},
            stage="published",
            links=[_member("live-child")],
        )
        assert component["current_version"] == 1


class TestTheSdkDeleteHasAnOptOut:
    """delete_component gained require_no_dependents=True in this release, so
    an SDK delete that used to return True now raises. The three SDK entry
    points passed nothing, which left callers with a new failure and no way
    to ask for the old behaviour -- while REST and StudioTools both catch the
    error and map it.
    """

    def test_the_default_still_refuses(self, db):
        from agno.agent import Agent

        _agent(db, "sdk-child")
        _team(db, "sdk-parent", stage="draft", links=[_member("sdk-child")])

        with pytest.raises(ComponentDependencyError):
            Agent(id="sdk-child", name="sdk-child").delete(db=db)

    def test_the_opt_out_deletes_anyway(self, db):
        from agno.agent import Agent

        _agent(db, "sdk-child-2")
        _team(db, "sdk-parent-2", stage="draft", links=[_member("sdk-child-2")])

        assert Agent(id="sdk-child-2", name="sdk-child-2").delete(db=db, require_no_dependents=False) is True
        assert db.get_component("sdk-child-2") is None


class TestTheOwnershipScopeRidesTheLockedRow:
    """The friendly scope read runs on its own connection, before the write
    transaction opens. Component ids are caller-chosen and reusable, so an id
    freed and re-claimed by another owner in that gap would be deleted under
    the first caller's authority unless the scope is re-asserted on the
    locked row.
    """

    def test_a_recreated_row_under_a_new_owner_is_not_deleted(self, dbs):
        first, second = dbs
        first.create_component_with_config(
            component_id="reused",
            component_type=ComponentType.AGENT,
            name="reused",
            config={"name": "reused"},
            stage="published",
            user_id="alice",
        )

        def recreate_under_bob():
            second.delete_component("reused", user_id="alice", hard_delete=True)
            second.create_component_with_config(
                component_id="reused",
                component_type=ComponentType.AGENT,
                name="reused",
                config={"name": "reused"},
                stage="published",
                user_id="bob",
            )

        outcome = _interleave(
            first,
            lambda: first.delete_component("reused", user_id="alice"),
            recreate_under_bob,
        )

        assert outcome.get("result") is False, outcome
        row = second.get_component("reused")
        assert row is not None and row["user_id"] == "bob"

    def test_the_owner_still_deletes_their_own(self, db):
        db.create_component_with_config(
            component_id="mine-alone",
            component_type=ComponentType.AGENT,
            name="mine-alone",
            config={"name": "mine-alone"},
            stage="published",
            user_id="alice",
        )
        assert db.delete_component("mine-alone", user_id="alice") is True
