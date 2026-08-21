from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Optional

import pytest

pytest.importorskip("surrealdb")

from agno.db.migrations.manager import MigrationManager  # noqa: E402
from agno.db.surrealdb.surrealdb import SurrealDb  # noqa: E402
from agno.exceptions import MigrationRequiredError  # noqa: E402


class _FakeSurrealClient:
    def __init__(self, *, tables: Optional[set[str]] = None) -> None:
        self.tables = set(tables or set())
        self.versions: Dict[str, str] = {}

    @staticmethod
    def _record_id(record: Any) -> str:
        record_id = getattr(record, "id", None)
        if record_id is not None:
            return str(record_id)
        return str(record).rsplit(":", 1)[-1].strip("⟨⟩")

    def query(self, query: str, vars: Optional[Dict[str, Any]] = None) -> Any:
        vars = vars or {}
        if query == "INFO FOR DB":
            return {"tables": {table_name: {} for table_name in self.tables}}
        if query.startswith("SELECT version FROM ONLY"):
            table_name = self._record_id(vars["record"])
            version = self.versions.get(table_name)
            return {"version": version} if version is not None else None
        if query.startswith("UPSERT ONLY"):
            content = vars["content"]
            if "table_name" in content and "version" in content:
                self.versions[str(content["table_name"])] = str(content["version"])
            return content
        if query.startswith("SELECT * FROM"):
            return []

        for table_name in re.findall(r"DEFINE TABLE(?: OVERWRITE)?\s+([A-Za-z0-9_]+)", query):
            self.tables.add(table_name)
        return None


def _new_db(client: _FakeSurrealClient) -> SurrealDb:
    return SurrealDb(
        client=client,  # type: ignore[arg-type]
        db_url="memory://schema-guard",
        db_creds={},
        db_ns="test",
        db_db="test",
    )


def test_fresh_table_is_stamped() -> None:
    client = _FakeSurrealClient()
    db = _new_db(client)

    assert db._get_table("sessions") == db.session_table_name
    assert db.session_table_name in client.tables
    assert db.get_latest_schema_version(db.session_table_name) == "3.0.0"


def test_stale_table_refuses_then_migration_restores_access() -> None:
    client = _FakeSurrealClient(tables={"agno_sessions"})
    db = _new_db(client)

    with pytest.raises(MigrationRequiredError):
        db._get_table("sessions")

    asyncio.run(MigrationManager(db).up(table_type="sessions"))

    assert db.get_latest_schema_version(db.session_table_name) == "3.0.0"
    assert db._get_table("sessions") == db.session_table_name


def test_non_migratable_table_is_not_blocked() -> None:
    client = _FakeSurrealClient(tables={"agno_runs"})
    db = _new_db(client)

    assert db._get_table("runs", create_table_if_not_found=False) == db.runs_table_name
    assert db.get_latest_schema_version(db.runs_table_name) == "2.0.0"
