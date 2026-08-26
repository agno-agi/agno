"""Per-owner schedule-name uniqueness is DB-backed, not just router-checked.

The router's check-then-insert races under concurrent creates. The schema now
declares two partial unique indexes (owned bucket + unowned bucket, since NULLs
are distinct in a plain unique index). The v3_0_0 migration adds both to
existing tables and RAISES on pre-existing duplicates (so the version is not
stamped and a later re-run can finish). The router maps the race-loser's
integrity error — matched by exception TYPE, not message text — to the same 409
as the pre-check, on both create and rename.
"""

import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from agno.db.sqlite import SqliteDb
from agno.os.routers.schedules.router import get_schedule_router
from agno.os.settings import AgnoAPISettings

pytest.importorskip("croniter", reason="croniter not installed")
pytest.importorskip("pytz", reason="pytz not installed")


def _schedule_dict(name, user_id=None):
    now = int(time.time())
    return {
        "id": str(uuid4()),
        "user_id": user_id,
        "name": name,
        "description": None,
        "method": "POST",
        "endpoint": "/agents/a/runs",
        "payload": None,
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "next_run_at": now + 3600,
        "locked_by": None,
        "locked_at": None,
        "created_at": now,
        "updated_at": None,
    }


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "schedules.db"))


class TestFreshTableBackstop:
    def test_same_owner_same_name_is_rejected(self, db):
        db.create_schedule(_schedule_dict("daily", user_id="alice"))
        with pytest.raises(Exception, match="(?i)unique"):
            db.create_schedule(_schedule_dict("daily", user_id="alice"))

    def test_unowned_bucket_is_also_unique(self, db):
        db.create_schedule(_schedule_dict("daily"))
        with pytest.raises(Exception, match="(?i)unique"):
            db.create_schedule(_schedule_dict("daily"))

    def test_different_owners_can_reuse_a_name(self, db):
        db.create_schedule(_schedule_dict("daily", user_id="alice"))
        db.create_schedule(_schedule_dict("daily", user_id="bob"))
        db.create_schedule(_schedule_dict("daily"))  # unowned bucket
        rows, total = db.get_schedules()
        assert total == 3


V2_SCHEDULES_DDL = """
CREATE TABLE {table} (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    method TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    payload TEXT,
    cron_expr TEXT NOT NULL,
    timezone TEXT NOT NULL,
    timeout_seconds BIGINT NOT NULL,
    max_retries BIGINT NOT NULL,
    retry_delay_seconds BIGINT NOT NULL,
    enabled BOOLEAN NOT NULL,
    next_run_at BIGINT,
    locked_by TEXT,
    locked_at BIGINT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT
)
"""


class TestMigrationAddsBackstop:
    def _make_legacy_table(self, db, table="legacy_schedules"):
        with db.Session() as sess, sess.begin():
            sess.execute(text(V2_SCHEDULES_DDL.format(table=table)))
        return table

    def _index_names(self, db, table):
        with db.Session() as sess:
            return {r[1] for r in sess.execute(text(f"PRAGMA index_list({table})")).fetchall()}

    def test_migration_creates_unique_indexes_on_legacy_table(self, db):
        from agno.db.migrations.versions.v3_0_0 import _migrate_sqlite_user_id

        table = self._make_legacy_table(db)
        assert _migrate_sqlite_user_id(db, "schedules", table) is True

        names = self._index_names(db, table)
        assert f"{table}_uq_user_name" in names
        assert f"{table}_uq_unowned_name" in names

        # Idempotent
        _migrate_sqlite_user_id(db, "schedules", table)

    def test_migration_tolerates_pre_existing_duplicates(self, db, caplog):
        from agno.db.migrations.versions.v3_0_0 import _migrate_sqlite_user_id

        table = self._make_legacy_table(db)
        with db.Session() as sess, sess.begin():
            for _ in range(2):
                d = _schedule_dict("dup-name")
                sess.execute(
                    text(
                        f"INSERT INTO {table} (id, name, method, endpoint, cron_expr, timezone, timeout_seconds,"
                        f" max_retries, retry_delay_seconds, enabled, created_at)"
                        f" VALUES (:id, :name, :method, :endpoint, :cron_expr, :timezone, :timeout_seconds,"
                        f" :max_retries, :retry_delay_seconds, :enabled, :created_at)"
                    ),
                    {
                        k: d[k]
                        for k in (
                            "id",
                            "name",
                            "method",
                            "endpoint",
                            "cron_expr",
                            "timezone",
                            "timeout_seconds",
                            "max_retries",
                            "retry_delay_seconds",
                            "enabled",
                            "created_at",
                        )
                    },
                )

        # Must RAISE so the migration is not stamped as applied: a swallowed warning
        # would advance the version, and the index could never be created afterward
        # (a re-run skips an already-stamped version). The owned-bucket index still
        # lands first, but the unowned index cannot be built over the duplicates.
        from agno.db.migrations.versions.v3_0_0 import ScheduleDuplicateNamesError

        with pytest.raises(ScheduleDuplicateNamesError, match="[Rr]esolve the duplicates"):
            _migrate_sqlite_user_id(db, "schedules", table)

    def test_migration_reruns_after_duplicates_resolved(self, db):
        from agno.db.migrations.versions.v3_0_0 import ScheduleDuplicateNamesError, _migrate_sqlite_user_id

        table = self._make_legacy_table(db)

        def _insert(name):
            with db.Session() as sess, sess.begin():
                d = _schedule_dict(name)
                sess.execute(
                    text(
                        f"INSERT INTO {table} (id, name, method, endpoint, cron_expr, timezone, timeout_seconds,"
                        f" max_retries, retry_delay_seconds, enabled, created_at)"
                        f" VALUES (:id, :name, :method, :endpoint, :cron_expr, :timezone, :timeout_seconds,"
                        f" :max_retries, :retry_delay_seconds, :enabled, :created_at)"
                    ),
                    {
                        k: d[k]
                        for k in (
                            "id",
                            "name",
                            "method",
                            "endpoint",
                            "cron_expr",
                            "timezone",
                            "timeout_seconds",
                            "max_retries",
                            "retry_delay_seconds",
                            "enabled",
                            "created_at",
                        )
                    },
                )

        _insert("dup-name")
        dup_id = _schedule_dict("dup-name")["id"]
        with db.Session() as sess, sess.begin():
            d = _schedule_dict("dup-name")
            d["id"] = dup_id
            sess.execute(
                text(
                    f"INSERT INTO {table} (id, name, method, endpoint, cron_expr, timezone, timeout_seconds,"
                    f" max_retries, retry_delay_seconds, enabled, created_at)"
                    f" VALUES (:id, :name, :method, :endpoint, :cron_expr, :timezone, :timeout_seconds,"
                    f" :max_retries, :retry_delay_seconds, :enabled, :created_at)"
                ),
                {
                    k: d[k]
                    for k in (
                        "id",
                        "name",
                        "method",
                        "endpoint",
                        "cron_expr",
                        "timezone",
                        "timeout_seconds",
                        "max_retries",
                        "retry_delay_seconds",
                        "enabled",
                        "created_at",
                    )
                },
            )

        with pytest.raises(ScheduleDuplicateNamesError):
            _migrate_sqlite_user_id(db, "schedules", table)

        # Operator resolves the duplicate, then re-runs: the backstop now lands.
        with db.Session() as sess, sess.begin():
            sess.execute(text(f"DELETE FROM {table} WHERE id = :i"), {"i": dup_id})
        _migrate_sqlite_user_id(db, "schedules", table)

        names = self._index_names(db, table)
        assert f"{table}_uq_user_name" in names
        assert f"{table}_uq_unowned_name" in names


class TestRouterMapsRaceTo409:
    def _client(self, mock_db, raise_server_exceptions=True):
        app = FastAPI()
        app.include_router(get_schedule_router(os_db=mock_db, settings=AgnoAPISettings()))
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    def _post_body(self):
        return {"name": "daily", "cron_expr": "0 9 * * *", "method": "POST", "endpoint": "/agents/a/runs"}

    def _integrity_error(self):
        from sqlalchemy.exc import IntegrityError

        return IntegrityError("INSERT ...", params={}, orig=Exception("UNIQUE constraint failed"))

    def test_integrity_error_after_passed_check_becomes_409(self):
        mock_db = MagicMock()
        mock_db.get_schedule_by_name = MagicMock(return_value=None)  # the race: check passes
        mock_db.create_schedule = MagicMock(side_effect=self._integrity_error())
        with (
            patch("agno.scheduler.cron._require_pytz"),
            patch("agno.scheduler.cron._require_croniter"),
        ):
            resp = self._client(mock_db).post("/schedules", json=self._post_body())
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_unrelated_db_error_is_not_masked_as_409(self):
        mock_db = MagicMock()
        mock_db.get_schedule_by_name = MagicMock(return_value=None)
        mock_db.create_schedule = MagicMock(side_effect=Exception("connection refused"))
        with (
            patch("agno.scheduler.cron._require_pytz"),
            patch("agno.scheduler.cron._require_croniter"),
        ):
            client = self._client(mock_db, raise_server_exceptions=False)
            resp = client.post("/schedules", json=self._post_body())
        assert resp.status_code == 500

    def test_check_violation_with_unique_in_message_is_not_409(self):
        # A CheckViolation (NOT a unique violation) whose bound params contain the
        # word "unique" must surface as 500, not a false name-conflict 409.
        from sqlalchemy.exc import DataError

        mock_db = MagicMock()
        mock_db.get_schedule_by_name = MagicMock(return_value=None)
        err = DataError(
            "INSERT ...",
            params={"description": "this run must be unique per tenant"},
            orig=Exception('violates check constraint "ck_timeout" ... unique per tenant'),
        )
        mock_db.create_schedule = MagicMock(side_effect=err)
        with (
            patch("agno.scheduler.cron._require_pytz"),
            patch("agno.scheduler.cron._require_croniter"),
        ):
            client = self._client(mock_db, raise_server_exceptions=False)
            resp = client.post(
                "/schedules",
                json={**self._post_body(), "description": "this run must be unique per tenant"},
            )
        assert resp.status_code == 500

    def test_rename_integrity_error_becomes_409(self):
        # The rename pre-check scopes to the caller but the row is stamped creator_user_id;
        # with isolation off the check can miss and the DB backstop fires -> must be 409.
        from agno.scheduler.cron import compute_next_run  # noqa: F401

        mock_db = MagicMock()
        existing = _schedule_dict("old-name")
        mock_db.get_schedule = MagicMock(return_value=existing)
        mock_db.get_schedule_by_name = MagicMock(return_value=None)  # pre-check misses
        mock_db.update_schedule = MagicMock(side_effect=self._integrity_error())
        with (
            patch("agno.scheduler.cron._require_pytz"),
            patch("agno.scheduler.cron._require_croniter"),
        ):
            resp = self._client(mock_db).patch(f"/schedules/{existing['id']}", json={"name": "taken-name"})
        assert resp.status_code == 409


class TestUpdateScheduleReRaisesOnlyUniqueViolations:
    """update_schedule swallows most DB errors to None (callers rely on that), but
    must RE-RAISE a unique violation so the router's rename mapping is reachable.
    Without this the router except is dead code and a rename collision returns 500."""

    def test_adapter_reraises_unique_violation(self, db):
        db.create_schedule(_schedule_dict("taken", user_id="alice"))
        s = db.create_schedule(_schedule_dict("mine", user_id="alice"))
        with pytest.raises(Exception, match="(?i)unique"):
            db.update_schedule(s["id"], user_id="alice", name="taken")

    def test_adapter_swallows_other_errors_to_none(self, db, monkeypatch):
        s = db.create_schedule(_schedule_dict("mine", user_id="alice"))

        # A non-integrity failure inside the write must still return None, not raise,
        # so resilient callers (the executor's enabled=False) are unaffected.
        def _boom(*a, **k):
            raise RuntimeError("transient db blip")

        monkeypatch.setattr(db, "get_schedule", _boom)
        assert db.update_schedule(s["id"], user_id="alice", enabled=False) is None


class TestRenameCollisionEndToEnd:
    """Real adapter (not a mock) proves the full path the reported bug broke:
    update_schedule used to swallow the IntegrityError to None, so the router
    fell through to 500. It must now return 409."""

    def _client(self, db):
        app = FastAPI()
        app.include_router(get_schedule_router(os_db=db, settings=AgnoAPISettings()))
        return TestClient(app, raise_server_exceptions=False)

    def test_rename_onto_taken_name_returns_409_not_500(self, db):
        # Two unowned schedules (isolation off): the router pre-check scopes to None but
        # a rename onto the other's name still hits the DB unique index.
        db.create_schedule(_schedule_dict("taken"))
        mine = db.create_schedule(_schedule_dict("mine"))

        with (
            patch("agno.scheduler.cron._require_pytz"),
            patch("agno.scheduler.cron._require_croniter"),
        ):
            resp = self._client(db).patch(f"/schedules/{mine['id']}", json={"name": "taken"})
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_normal_rename_still_succeeds(self, db):
        mine = db.create_schedule(_schedule_dict("mine"))
        with (
            patch("agno.scheduler.cron._require_pytz"),
            patch("agno.scheduler.cron._require_croniter"),
        ):
            resp = self._client(db).patch(f"/schedules/{mine['id']}", json={"name": "renamed"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "renamed"
