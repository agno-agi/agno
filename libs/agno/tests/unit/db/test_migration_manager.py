import pytest

from agno.db.migrations.manager import MigrationManager


class DummyDb:
    memory_table_name = "agno_memories"
    session_table_name = "agno_sessions"
    metrics_table_name = "agno_metrics"
    eval_table_name = "agno_evals"
    knowledge_table_name = "agno_knowledge"
    culture_table_name = "agno_culture"
    approvals_table_name = "agno_approvals"

    def __init__(self, schema_version: str):
        self.schema_version = schema_version
        self.schema_version_requests = []
        self.upserted_versions = []

    def get_latest_schema_version(self, table_name: str) -> str:
        self.schema_version_requests.append(table_name)
        return self.schema_version

    def upsert_schema_version(self, table_name: str, version: str) -> None:
        self.upserted_versions.append((table_name, version))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table_type", "expected_table_type", "expected_table_name"),
    [
        ("memory", "memories", "agno_memories"),
        ("session", "sessions", "agno_sessions"),
        ("eval", "evals", "agno_evals"),
    ],
)
async def test_up_accepts_singular_table_type_aliases(
    monkeypatch, table_type, expected_table_type, expected_table_name
):
    db = DummyDb(schema_version="2.0.0")
    manager = MigrationManager(db)  # type: ignore[arg-type]
    migration_calls = []

    async def fake_up_migration(version: str, table_type: str, table_name: str) -> bool:
        migration_calls.append((version, table_type, table_name))
        return True

    monkeypatch.setattr(manager, "_up_migration", fake_up_migration)

    await manager.up(target_version="2.3.0", table_type=table_type)

    assert migration_calls == [("v2_3_0", expected_table_type, expected_table_name)]
    assert db.schema_version_requests == [expected_table_name]
    assert db.upserted_versions == [(expected_table_name, "2.3.0")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table_type", "expected_table_type", "expected_table_name"),
    [
        ("memory", "memories", "agno_memories"),
        ("session", "sessions", "agno_sessions"),
        ("eval", "evals", "agno_evals"),
    ],
)
async def test_down_accepts_singular_table_type_aliases(
    monkeypatch, table_type, expected_table_type, expected_table_name
):
    db = DummyDb(schema_version="2.5.6")
    manager = MigrationManager(db)  # type: ignore[arg-type]
    migration_calls = []

    async def fake_down_migration(version: str, table_type: str, table_name: str) -> bool:
        migration_calls.append((version, table_type, table_name))
        return True

    monkeypatch.setattr(manager, "_down_migration", fake_down_migration)

    await manager.down(target_version="2.5.0", table_type=table_type)

    assert migration_calls == [("v2_5_6", expected_table_type, expected_table_name)]
    assert db.schema_version_requests == [expected_table_name]
    assert db.upserted_versions == [(expected_table_name, "2.5.0")]
