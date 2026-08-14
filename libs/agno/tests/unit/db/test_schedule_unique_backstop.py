"""Per-owner schedule-name uniqueness is DB-backed, not just router-checked.

The router's check-then-insert races under concurrent creates. The schema now
declares a unique (user_id, name) constraint plus a partial unique index for
the unowned bucket (NULLs are distinct in unique constraints), the v3_0_0
migration adds both to existing tables (duplicate-tolerant), and the router
maps the race-loser's integrity error to the same 409 as the pre-check.
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

        # Must not raise: legacy rows are all unowned, so the owned-bucket
        # constraint still lands; the unowned partial index warns and skips.
        _migrate_sqlite_user_id(db, "schedules", table)

        names = self._index_names(db, table)
        assert f"{table}_uq_user_name" in names
        assert f"{table}_uq_unowned_name" not in names


class TestRouterMapsRaceTo409:
    def _client(self, mock_db, raise_server_exceptions=True):
        app = FastAPI()
        app.include_router(get_schedule_router(os_db=mock_db, settings=AgnoAPISettings()))
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    def _post_body(self):
        return {"name": "daily", "cron_expr": "0 9 * * *", "method": "POST", "endpoint": "/agents/a/runs"}

    def test_integrity_error_after_passed_check_becomes_409(self):
        mock_db = MagicMock()
        mock_db.get_schedule_by_name = MagicMock(return_value=None)  # the race: check passes
        mock_db.create_schedule = MagicMock(
            side_effect=Exception("UNIQUE constraint failed: agno_schedules.user_id, agno_schedules.name")
        )
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
