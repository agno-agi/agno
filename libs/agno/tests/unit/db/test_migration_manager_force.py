"""``MigrationManager.up(force=True)`` must re-run the migrations on a table that is already stamped.

The stub below is the whole adapter surface the manager touches; ``_up_migration`` is recorded
instead of executed, so no database is involved.
"""

import asyncio
import importlib

from agno.db.migrations.manager import MigrationManager

TABLE_ATTRS = {
    "memory_table_name": "memories",
    "session_table_name": "sessions",
    "metrics_table_name": "metrics",
    "eval_table_name": "evals",
    "knowledge_table_name": "knowledge",
    "approvals_table_name": "approvals",
    "components_table_name": "components",
    "schedules_table_name": "schedules",
    "schedule_runs_table_name": "schedule_runs",
    "learnings_table_name": "learnings",
}


class StubDb:
    def __init__(self, stamped_version: str):
        self.stamped_version = stamped_version
        self.stored_versions: list[tuple[str, str]] = []
        for attr, name in TABLE_ATTRS.items():
            setattr(self, attr, name)

    def get_latest_schema_version(self, table_name: str) -> str:
        return self.stamped_version

    def upsert_schema_version(self, table_name: str, version: str) -> None:
        self.stored_versions.append((table_name, version))


class RecordingMigrationManager(MigrationManager):
    def __init__(self, db: StubDb):
        super().__init__(db)  # type: ignore[arg-type]
        self.applied: list[str] = []

    async def _up_migration(self, version: str, table_type: str, table_name: str) -> bool:
        self.applied.append(version)
        return True


def _run_up(stamped_version: str, **kwargs) -> tuple[RecordingMigrationManager, StubDb]:
    db = StubDb(stamped_version)
    manager = RecordingMigrationManager(db)
    asyncio.run(manager.up(table_type="sessions", **kwargs))
    return manager, db


def test_up_skips_a_table_already_at_the_target():
    manager, db = _run_up("3.0.0")

    assert manager.applied == []
    assert db.stored_versions == []


def test_up_with_force_reruns_every_migration_up_to_the_target():
    manager, db = _run_up("3.0.0", force=True)

    assert manager.applied == [version for version, _ in manager.available_versions[1:]]
    assert db.stored_versions == [("sessions", manager.latest_schema_version.public)]
    # The baseline entry has no module behind it; everything the forced run applies must be loadable.
    for version in manager.applied:
        importlib.import_module(f"agno.db.migrations.versions.{version}")


def test_up_with_force_honours_an_explicit_target():
    manager, db = _run_up("2.5.6", target_version="2.5.6", force=True)

    assert manager.applied == ["v2_3_0", "v2_5_0", "v2_5_6"]
    assert db.stored_versions == [("sessions", "2.5.6")]


def test_up_with_force_rejects_a_target_below_the_current_version():
    # up() has no revert step, so replaying older migrations and stamping the older
    # version would misdescribe the schema. That is down()'s job.
    manager, db = _run_up("3.0.0", target_version="2.5.6", force=True)

    assert manager.applied == []
    assert db.stored_versions == []


def test_up_without_force_still_applies_only_the_missing_migrations():
    manager, db = _run_up("2.5.0")

    assert manager.applied == ["v2_5_6", "v3_0_0"]
    assert db.stored_versions == [("sessions", manager.latest_schema_version.public)]
