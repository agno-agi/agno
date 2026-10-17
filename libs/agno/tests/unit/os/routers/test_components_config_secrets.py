"""Tests that component config resolution never leaks backend DB credentials (#8706).

_resolve_db_in_config expands a db id-reference into resolved_db.to_dict(), which
for PostgresDb/SqliteDb carries db_url (and a Postgres URL embeds the password).
That expanded config is persisted and returned by GET /components/*/configs* under
the non-admin components:read scope. These tests assert the secret-bearing fields
are stripped from the resolved config when the db is an id-reference.
"""

from typing import Any, Dict

from sqlalchemy import create_engine

from agno.db.postgres.postgres import PostgresDb
from agno.db.sqlite.sqlite import SqliteDb
from agno.os.routers.components.components import _resolve_db_in_config


class _FakeRegistry:
    def __init__(self, db=None):
        self._db = db

    def get_db(self, db_id):
        if self._db is not None and getattr(self._db, "id", None) == db_id:
            return self._db
        return None


# --- Postgres: db_url (password) must not leak when resolved by id ---


def test_postgres_db_url_stripped_from_resolved_config():
    engine = create_engine("sqlite:///:memory:")
    os_db = PostgresDb(
        db_url="postgresql://agno_admin:SuperSecretDbPassw0rd@prod-db.internal:5432/agno_prod",
        db_engine=engine,
        db_schema="ai",
    )
    registry = _FakeRegistry(os_db)

    config: Dict[str, Any] = {"db": {"id": os_db.id}}
    resolved = _resolve_db_in_config(config, os_db, registry=registry)

    resolved_db = resolved["db"]
    # The connection secret must never appear in the persisted/returned config.
    assert "db_url" not in resolved_db
    assert "SuperSecretDbPassw0rd" not in str(resolved_db)
    # The non-secret id reference and table overrides are preserved.
    assert resolved_db.get("id") == os_db.id
    assert resolved_db.get("type") == "postgres"


def test_postgres_table_overrides_preserved_without_secrets():
    engine = create_engine("sqlite:///:memory:")
    os_db = PostgresDb(
        db_url="postgresql://u:p@host/db",
        db_engine=engine,
    )
    registry = _FakeRegistry(os_db)

    config = {"db": {"id": os_db.id, "session_table": "custom_sessions", "memory_table": "custom_memories"}}
    resolved = _resolve_db_in_config(config, os_db, registry=registry)

    resolved_db = resolved["db"]
    assert "db_url" not in resolved_db
    assert resolved_db["session_table"] == "custom_sessions"
    assert resolved_db["memory_table"] == "custom_memories"


# --- SQLite: db_file / db_url must not leak when resolved by id ---


def test_sqlite_db_file_and_url_stripped_from_resolved_config(tmp_path):
    os_db = SqliteDb(db_file=str(tmp_path / "os.db"))
    registry = _FakeRegistry(os_db)

    config = {"db": {"id": os_db.id}}
    resolved = _resolve_db_in_config(config, os_db, registry=registry)

    resolved_db = resolved["db"]
    assert "db_file" not in resolved_db
    assert "db_url" not in resolved_db
    assert resolved_db.get("id") == os_db.id
    assert resolved_db.get("type") == "sqlite"


def test_sqlite_table_overrides_preserved_without_secrets(tmp_path):
    os_db = SqliteDb(db_file=str(tmp_path / "os.db"))
    registry = _FakeRegistry(os_db)

    config = {"db": {"id": os_db.id, "session_table": "s", "memory_table": "m"}}
    resolved = _resolve_db_in_config(config, os_db, registry=registry)

    resolved_db = resolved["db"]
    assert "db_file" not in resolved_db
    assert resolved_db["session_table"] == "s"
    assert resolved_db["memory_table"] == "m"


# --- OS db resolution path (id matches os_db) ---


def test_os_db_match_strips_secrets(tmp_path):
    os_db = SqliteDb(db_file=str(tmp_path / "os.db"))

    # id references the OS db directly (no registry needed)
    config = {"db": {"id": os_db.id}}
    resolved = _resolve_db_in_config(config, os_db, registry=None)

    resolved_db = resolved["db"]
    assert "db_file" not in resolved_db
    assert "db_url" not in resolved_db
    assert resolved_db.get("id") == os_db.id


# --- config without a db id is left intact (caller-supplied connection) ---


def test_inline_db_without_id_is_left_intact(tmp_path):
    """A db dict with no id is caller-supplied connection info, not an expansion
    of an OS/registry secret — leave it alone (no secret exfiltration occurs)."""
    config = {"db": {"type": "sqlite", "db_file": str(tmp_path / "inline.db")}}
    resolved = _resolve_db_in_config(config, os_db=SqliteDb(db_file=str(tmp_path / "os.db")), registry=None)

    assert resolved["db"]["db_file"] == str(tmp_path / "inline.db")


def test_unresolvable_id_logs_error_and_leaves_config(tmp_path):
    os_db = SqliteDb(db_file=str(tmp_path / "os.db"))
    registry = _FakeRegistry(None)  # nothing registered

    config = {"db": {"id": "does-not-exist"}}
    resolved = _resolve_db_in_config(config, os_db, registry=registry)

    # The original (id-only, secret-free) db reference is preserved unchanged.
    assert resolved["db"] == {"id": "does-not-exist"}


def test_no_db_key_passes_through(tmp_path):
    os_db = SqliteDb(db_file=str(tmp_path / "os.db"))
    config: Dict[str, Any] = {"some_field": "value"}
    resolved = _resolve_db_in_config(config, os_db, registry=None)
    assert resolved == {"some_field": "value"}
