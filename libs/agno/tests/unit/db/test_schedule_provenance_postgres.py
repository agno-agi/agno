"""Postgres mirror of test_schedule_provenance.py.

Runs against the live pgvector container (localhost:5532) with a unique
schema per run; skips cleanly when psycopg or the server is absent.
"""

import uuid

import pytest

from agno.db.schemas.scheduler import (
    SCHEDULE_MUTABLE_COLUMNS,
    STUDIO_SCHEDULE_MANAGED_BY,
    validate_schedule_update,
)

psycopg = pytest.importorskip("psycopg")

from agno.db.postgres import PostgresDb  # noqa: E402

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _server_reachable() -> bool:
    # A raw probe, not an adapter call: adapter methods catch and log
    # connection errors, so they cannot signal an absent server.
    from sqlalchemy import create_engine, text

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
    schema = f"sched_prov_{uuid.uuid4().hex[:8]}"
    database = PostgresDb(db_url=DB_URL, db_schema=schema)
    yield database
    with database.Session() as sess, sess.begin():
        from sqlalchemy import text

        sess.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def _mk(db, name, endpoint="/agents/analyst/runs", **extra):
    data = {
        "id": f"sched-{name}",
        "name": name,
        "cron_expr": "0 9 * * *",
        "endpoint": endpoint,
        "method": "POST",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "created_at": 1,
    }
    data.update(extra)
    return db.create_schedule(data)


class TestUpdateAllowList:
    def test_provenance_columns_are_rejected(self, db):
        _mk(db, "guarded")
        for column in ("managed_by", "target_type", "target_id", "created_by_run_id", "updated_by_run_id"):
            with pytest.raises(ValueError, match="update_schedule cannot modify"):
                db.update_schedule("sched-guarded", **{column: "x"})

    def test_user_id_is_a_filter_never_a_write(self, db):
        # update_schedule's user_id parameter scopes the WHERE clause; it can
        # never move a row between owners.
        _mk(db, "owned", user_id="alice")
        assert db.update_schedule("sched-owned", user_id="bob", description="hijack") is None
        row = db.get_schedule("sched-owned")
        assert row["user_id"] == "alice" and row["description"] is None

    def test_mutable_columns_pass(self, db):
        _mk(db, "mutable")
        row = db.update_schedule("sched-mutable", cron_expr="0 10 * * *", description="new")
        assert row is not None and row["cron_expr"] == "0 10 * * *"

    def test_the_allow_list_is_exactly_the_public_surface(self):
        assert SCHEDULE_MUTABLE_COLUMNS == {
            "name",
            "description",
            "method",
            "endpoint",
            "payload",
            "cron_expr",
            "timezone",
            "timeout_seconds",
            "max_retries",
            "retry_delay_seconds",
            "enabled",
            "next_run_at",
            "disabled_reason",
        }

    def test_validator_names_the_dedicated_path(self):
        with pytest.raises(ValueError, match="dedicated APIs"):
            validate_schedule_update({"locked_by": "w"})


class TestProvenanceStamp:
    def test_stamp_writes_control_plane_columns(self, db):
        _mk(db, "stamped")
        assert db.stamp_schedule_provenance(
            "sched-stamped",
            managed_by=STUDIO_SCHEDULE_MANAGED_BY,
            target_type="agent",
            target_id="analyst",
            created_by_run_id="run-1",
        )
        row = db.get_schedule("sched-stamped")
        assert row["managed_by"] == "studio"
        assert row["target_type"] == "agent" and row["target_id"] == "analyst"
        assert row["created_by_run_id"] == "run-1"

    def test_stamp_refuses_everything_else(self, db):
        _mk(db, "sneaky")
        with pytest.raises(ValueError, match="cannot write"):
            db.stamp_schedule_provenance("sched-sneaky", enabled=False)
        with pytest.raises(ValueError, match="cannot write"):
            db.stamp_schedule_provenance("sched-sneaky", user_id="mallory")

    def test_stamp_missing_row_returns_false(self, db):
        assert db.stamp_schedule_provenance("ghost", managed_by="studio") is False


class TestDisableForTarget:
    def test_disables_tagged_and_generic_rows_across_owners(self, db):
        _mk(db, "alices", user_id="alice")
        db.stamp_schedule_provenance("sched-alices", managed_by="studio", target_type="agent", target_id="analyst")
        _mk(db, "bobs", user_id="bob")
        db.stamp_schedule_provenance("sched-bobs", managed_by="studio", target_type="agent", target_id="analyst")
        _mk(db, "generic-same-endpoint")  # untagged, same endpoint
        _mk(db, "unrelated", endpoint="/agents/other/runs")

        count = db.disable_schedules_for_target("agent", "analyst", reason="target_archived:agent:analyst")
        assert count == 3
        for sid in ("sched-alices", "sched-bobs", "sched-generic-same-endpoint"):
            row = db.get_schedule(sid)
            assert row["enabled"] in (False, 0), sid
            assert row["disabled_reason"] == "target_archived:agent:analyst", sid
        assert db.get_schedule("sched-unrelated")["enabled"] in (True, 1)

    def test_second_call_counts_zero(self, db):
        _mk(db, "once")
        db.stamp_schedule_provenance("sched-once", managed_by="studio", target_type="agent", target_id="analyst")
        assert db.disable_schedules_for_target("agent", "analyst") == 1
        assert db.disable_schedules_for_target("agent", "analyst") == 0

    def test_enable_clears_the_reason(self, db):
        _mk(db, "revivable")
        db.disable_schedules_for_target("agent", "analyst", reason="target_archived:agent:analyst")
        row = db.update_schedule("sched-revivable", enabled=True)
        assert row["enabled"] in (True, 1)
        assert row["disabled_reason"] is None
