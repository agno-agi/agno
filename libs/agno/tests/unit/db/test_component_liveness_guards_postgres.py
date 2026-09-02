"""Liveness guards and the schedule cascade on the PostgreSQL adapter.

Mirror of the state-based half of test_component_liveness_guards.py (the
SQLite suite) against a live Postgres (cookbook/scripts/run_pgvector.sh, port
5532): the promote and pointer gates read a pinned child's liveness, only an
ACTIVE parent pins a version, and delete_component silences the schedules
aimed at the target in its own transaction.

The deterministic interleaves stay in the SQLite suite: Postgres serializes
those writers on the component row (FOR UPDATE), so a counterpart holding one
side would simply block on the other rather than interleave.

Each test runs in its own schema, dropped on teardown. The whole module skips
when psycopg is missing or the server is unreachable.
"""

import time
import uuid

import pytest
from sqlalchemy import create_engine, select, text

from agno.db.base import (
    DELETED_CONFIG_STAGE,
    ComponentDependencyError,
    ComponentType,
)
from agno.db.postgres import PostgresDb
from agno.db.schemas.scheduler import build_run_endpoint

pytest.importorskip("psycopg")

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _server_reachable() -> bool:
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _postgres_server():
    if not _server_reachable():
        pytest.skip(f"Postgres server not reachable at {DB_URL}")


@pytest.fixture
def db(_postgres_server):
    schema = f"liveness_guards_{uuid.uuid4().hex[:8]}"
    database = PostgresDb(db_url=DB_URL, db_schema=schema, id=f"liveness-guards-{schema}")
    yield database
    database.Session.remove()
    with database.db_engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()
    database.db_engine.dispose()


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


def _member(child_id, version=1):
    return {
        "link_kind": "member",
        "link_key": child_id,
        "child_component_id": child_id,
        "child_version": version,
        "position": 0,
    }


def _arm_schedule(db, schedule_id, target_type, target_id, tagged=True):
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


class TestPromoteGateReadsChildLiveness:
    def test_publish_refuses_a_version_that_pins_an_archived_child(self, db):
        _agent(db, "member-a")
        _team(db, "squad", stage="published")
        db.upsert_config("squad", config={"name": "squad", "id": "squad"}, stage="draft", links=[_member("member-a")])
        assert db.delete_component("squad") is True
        assert db.delete_component("member-a") is True
        assert db.restore_component("squad") is True

        with pytest.raises(ComponentDependencyError, match="member-a"):
            db.upsert_config("squad", version=2, stage="published")

        assert db.get_component("squad")["current_version"] == 1
        assert db.get_config("squad", version=2)["stage"] == "draft"

    def test_set_current_version_refuses_a_version_that_pins_an_archived_child(self, db):
        _agent(db, "member-b")
        _team(db, "mom", stage="published", links=[_member("member-b")])
        db.upsert_config("mom", config={"name": "mom", "id": "mom"}, stage="published", links=[])
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


class TestOnlyActiveParentsPinAVersion:
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
        # The composite foreign key would refuse this state on a table created
        # by this version of the schema, but not on one created before it, and
        # the guard must not depend on that.
        self._worker_pinned_by(db, "live-team")
        configs_table = db._get_table(table_type="component_configs")
        links_table = db._get_table(table_type="component_links")
        with db.Session() as sess, sess.begin():
            sess.execute(
                text(
                    f'ALTER TABLE "{db.db_schema}".{links_table.name} '
                    "DROP CONSTRAINT IF EXISTS "
                    "agno_component_links_parent_component_id_parent_version_fkey"
                )
            )
            sess.execute(configs_table.delete().where(configs_table.c.component_id == "live-team"))

        with pytest.raises(ComponentDependencyError, match="live-team"):
            db.delete_config("worker", 2)


class TestDeleteComponentCascadesSchedules:
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

    def test_a_cascade_failure_rolls_the_delete_back(self, db, monkeypatch):
        _agent(db, "brittle")
        _arm_schedule(db, "sched-brittle", "agent", "brittle")

        def boom(*args, **kwargs):
            raise RuntimeError("schedules table unavailable")

        monkeypatch.setattr(PostgresDb, "_disable_schedules_for_target_in_session", boom)

        with pytest.raises(RuntimeError):
            db.delete_component("brittle")

        assert db.get_component("brittle") is not None
        assert db.get_schedule("sched-brittle")["enabled"] in (True, 1)

    def test_a_component_without_any_schedules_table_still_archives(self, db):
        _agent(db, "lonely")
        assert db._get_table(table_type="schedules") is None

        assert db.delete_component("lonely") is True
        assert db.get_component("lonely") is None


def test_dependents_read_shares_one_query_with_the_public_reader(db):
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
