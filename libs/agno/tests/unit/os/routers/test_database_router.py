"""The migrate endpoints run the pending migrations and report failures faithfully.

``POST /databases/all/migrate`` answers 200 when every local database migrated,
207 with a ``failed`` map otherwise, and skips remote databases instead of failing
them. ``POST /databases/{db_id}/migrate`` answers 200, 404 for an unknown id, 400
for a remote database, and keeps an ``AgnoError``'s identity on failure.
"""

import sqlite3
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from agno.db.migrations.manager import MigrationManager
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.exceptions import MigrationRequiredError
from agno.os import AgentOS
from agno.remote.base import RemoteDb


def _client(agent_os):
    return TestClient(agent_os.get_app(), raise_server_exceptions=False)


@pytest.fixture
def sqlite_db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "migrate.db"))


@pytest.fixture
def async_sqlite_db(tmp_path):
    return AsyncSqliteDb(db_file=str(tmp_path / "migrate_async.db"))


@pytest.fixture
def stale_approvals_db(tmp_path):
    """A SqliteDb whose approvals table is at its 2.5.0 shape: ``run_status`` was added in 2.5.6."""
    db_file = tmp_path / "stale_approvals.db"
    seed = SqliteDb(db_file=str(db_file))
    seed._create_all_tables()
    seed.upsert_schema_version(seed.approvals_table_name, "2.5.0")
    with sqlite3.connect(db_file) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_agno_approvals_run_status")
        conn.execute("ALTER TABLE agno_approvals DROP COLUMN run_status")
    # A fresh instance so no Table objects reflected before the column drop are cached.
    return SqliteDb(db_file=str(db_file))


class TestMigrateAllDatabases:
    def test_fresh_sync_database_migrates_to_latest(self, sqlite_db):
        client = _client(AgentOS(id="os", db=sqlite_db))

        response = client.post("/databases/all/migrate")

        assert response.status_code == 200
        assert response.json() == {"message": "All databases migrated successfully to latest version"}

    def test_fresh_async_database_migrates_to_latest(self, async_sqlite_db):
        client = _client(AgentOS(id="os", db=async_sqlite_db))

        response = client.post("/databases/all/migrate")

        assert response.status_code == 200
        assert response.json() == {"message": "All databases migrated successfully to latest version"}

    def test_target_version_is_echoed(self, sqlite_db):
        client = _client(AgentOS(id="os", db=sqlite_db))

        response = client.post("/databases/all/migrate?target_version=2.5.6")

        assert response.status_code == 200
        assert response.json()["message"] == "All databases migrated successfully to version 2.5.6"

    def test_stale_table_is_brought_up_to_date(self, stale_approvals_db):
        client = _client(AgentOS(id="os", db=stale_approvals_db))

        response = client.post("/databases/all/migrate")

        assert response.status_code == 200
        with sqlite3.connect(stale_approvals_db.db_file) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(agno_approvals)")}
            versions = dict(conn.execute("SELECT table_name, version FROM agno_schema_versions").fetchall())
        assert "run_status" in columns
        assert versions["agno_approvals"] == str(MigrationManager(stale_approvals_db).latest_schema_version)

    def test_failure_is_reported_per_database_as_207(self, sqlite_db):
        client = _client(AgentOS(id="os", db=sqlite_db))

        async def boom(self, *args, **kwargs):
            raise RuntimeError("boom")

        with patch.object(MigrationManager, "up", boom):
            response = client.post("/databases/all/migrate")

        assert response.status_code == 207
        body = response.json()
        assert body["message"] == "Migrated 0/1 databases to latest version"
        assert body["failed"] == {sqlite_db.id: "boom"}

    def test_remote_database_is_skipped_not_failed(self, sqlite_db):
        agent_os = AgentOS(id="os", db=sqlite_db)
        client = _client(agent_os)
        agent_os.dbs["remote-1"] = [RemoteDb(id="remote-1", client=Mock())]

        response = client.post("/databases/all/migrate")

        assert response.status_code == 200
        assert response.json() == {
            "message": "All databases migrated successfully to latest version",
            "skipped": ["remote-1"],
        }

    def test_remote_database_is_skipped_with_a_target_version(self, sqlite_db):
        """The target-version branch reads the schema version off the db, which a RemoteDb lacks."""
        agent_os = AgentOS(id="os", db=sqlite_db)
        client = _client(agent_os)
        agent_os.dbs["remote-1"] = [RemoteDb(id="remote-1", client=Mock())]

        response = client.post("/databases/all/migrate?target_version=2.5.6")

        assert response.status_code == 200
        assert response.json()["skipped"] == ["remote-1"]


class TestMigrateDatabase:
    def test_fresh_database_migrates(self, sqlite_db):
        client = _client(AgentOS(id="os", db=sqlite_db))

        response = client.post(f"/databases/{sqlite_db.id}/migrate")

        assert response.status_code == 200
        assert response.json() == {"message": "Database migrated successfully to latest version"}

    def test_async_database_migrates(self, async_sqlite_db):
        client = _client(AgentOS(id="os", db=async_sqlite_db))

        response = client.post(f"/databases/{async_sqlite_db.id}/migrate")

        assert response.status_code == 200

    def test_unknown_database_is_404(self, sqlite_db):
        client = _client(AgentOS(id="os", db=sqlite_db))

        response = client.post("/databases/does-not-exist/migrate")

        assert response.status_code == 404

    def test_remote_database_is_400(self, sqlite_db):
        agent_os = AgentOS(id="os", db=sqlite_db)
        client = _client(agent_os)
        agent_os.dbs["remote-1"] = [RemoteDb(id="remote-1", client=Mock())]

        response = client.post("/databases/remote-1/migrate")

        assert response.status_code == 400
        assert "remote" in response.json()["detail"]

    def test_generic_failure_is_500_with_detail(self, sqlite_db):
        client = _client(AgentOS(id="os", db=sqlite_db))

        async def boom(self, *args, **kwargs):
            raise RuntimeError("boom")

        with patch.object(MigrationManager, "up", boom):
            response = client.post(f"/databases/{sqlite_db.id}/migrate")

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to migrate database: boom"}

    def test_agno_error_keeps_its_identity(self, sqlite_db):
        client = _client(AgentOS(id="os", db=sqlite_db))

        async def boom(self, *args, **kwargs):
            raise MigrationRequiredError(table_name="agno_sessions")

        with patch.object(MigrationManager, "up", boom):
            response = client.post(f"/databases/{sqlite_db.id}/migrate")

        assert response.status_code == 500
        body = response.json()
        assert body["error_id"] == "migration_required_error"
        assert body["detail"].startswith("Failed to migrate database: Table agno_sessions has an invalid schema")
