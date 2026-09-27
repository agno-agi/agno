"""A table left behind by an older schema answers with a distinguishable error.

The database adapters raise ``MigrationRequiredError`` when an existing table is
missing columns this version expects. Over HTTP the owned-app handlers put its
``error_id`` in the body so a client can branch on it instead of parsing the
message; on a caller-supplied app the status code and detail still survive.
"""

import sqlite3
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.db.utils import table_schema_mismatch_error
from agno.exceptions import AgnoError, MigrationRequiredError, SchemaMismatchError
from agno.os import AgentOS
from agno.os.utils import AgnoHTTPException


@pytest.fixture
def stale_db(tmp_path):
    """A SqliteDb whose metrics table predates the current schema (missing most columns)."""
    db_file = tmp_path / "stale.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE agno_metrics (id TEXT PRIMARY KEY, date TEXT)")
    return SqliteDb(db_file=str(db_file), metrics_table="agno_metrics")


def _client(app):
    return TestClient(app, raise_server_exceptions=False)


class TestMigrationRequiredError:
    def test_is_an_agno_error_with_a_stable_id(self):
        error = MigrationRequiredError(table_name="public.agno_metrics")

        assert isinstance(error, AgnoError)
        assert error.status_code == 500
        assert error.error_id == "migration_required_error"
        assert error.type == "migration_required_error"
        assert error.table_name == "public.agno_metrics"
        assert "public.agno_metrics has an invalid schema" in str(error)
        assert "POST /databases/all/migrate" in str(error)

    def test_is_a_schema_mismatch_error(self):
        assert issubclass(MigrationRequiredError, SchemaMismatchError)
        assert SchemaMismatchError(table_name="t").error_id == "schema_mismatch_error"

    def test_helper_picks_migration_required_for_migratable_tables(self):
        error = table_schema_mismatch_error("public.agno_metrics", table_type="metrics")

        assert type(error) is MigrationRequiredError
        assert "POST /databases/all/migrate" in str(error)

    def test_helper_picks_plain_mismatch_for_tables_no_migration_covers(self):
        """Migration advice for a table no migration touches would send the user in a circle."""
        error = table_schema_mismatch_error("agno_traces", table_type="traces")

        assert type(error) is SchemaMismatchError
        assert error.error_id == "schema_mismatch_error"
        assert "No Agno migration covers this table" in str(error)
        assert "MigrationManager" not in str(error)

    def test_custom_message_is_kept(self):
        error = MigrationRequiredError(table_name="t", message="custom")

        assert str(error) == "custom"
        assert error.error_id == "migration_required_error"

    def test_adapter_raises_it_for_a_stale_table(self, stale_db):
        with pytest.raises(MigrationRequiredError) as exc_info:
            stale_db.get_metrics()

        assert exc_info.value.table_name == "agno_metrics"

    def test_inspection_failure_is_not_read_as_a_stale_schema(self, stale_db):
        """A table that cannot be inspected is an operational error, not a pending migration."""
        with patch("agno.db.sqlite.utils.inspect", side_effect=RuntimeError("no metadata access")):
            with pytest.raises(RuntimeError, match="no metadata access"):
                stale_db.get_metrics()


class TestAgnoHTTPException:
    def test_carries_status_and_identity_of_the_wrapped_error(self):
        http_error = AgnoHTTPException(MigrationRequiredError(table_name="agno_metrics"))

        assert http_error.status_code == 500
        assert http_error.error_id == "migration_required_error"
        assert http_error.error_type == "migration_required_error"
        assert "agno_metrics has an invalid schema" in http_error.detail

    def test_detail_override(self):
        http_error = AgnoHTTPException(MigrationRequiredError(table_name="t"), detail="short")

        assert http_error.detail == "short"
        assert http_error.error_id == "migration_required_error"


class TestMigrationRequiredOverHttp:
    def test_owned_app_answers_with_error_id(self, stale_db):
        client = _client(AgentOS(id="stale-os", db=stale_db).get_app())

        response = client.get("/metrics")

        assert response.status_code == 500
        body = response.json()
        assert body["error_id"] == "migration_required_error"
        assert body["error_type"] == "migration_required_error"
        assert "agno_metrics has an invalid schema" in body["detail"]

    def test_caller_supplied_app_keeps_status_and_detail(self, stale_db):
        """AgentOS registers no handlers on a caller-supplied app, so the status
        has to come from the router; the body is FastAPI's default shape."""
        client = _client(AgentOS(id="mounted-os", db=stale_db, base_app=FastAPI()).get_app())

        response = client.get("/metrics")

        assert response.status_code == 500
        assert "agno_metrics has an invalid schema" in response.json()["detail"]

    def test_plain_errors_do_not_grow_an_error_id(self, stale_db):
        """Only errors that carry an identity get one in the body; a 404 stays as it was."""
        client = _client(AgentOS(id="stale-os", db=stale_db).get_app())

        response = client.get("/sessions/does-not-exist")

        assert response.status_code == 404
        assert "error_id" not in response.json()
