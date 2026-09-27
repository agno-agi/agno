"""The v3.0.0 migration re-keys namespace="user" entity_memory rows.

Before 3.0 the entity_memory key under namespace="user" carried no user
component, so two users recording the same entity name and type shared one row.
The migration moves each surviving row onto its owner's user-scoped key. It runs
with every other table migration, through MigrationManager.
"""

from typing import Any, Dict, Optional

import pytest

from agno.db.migrations.manager import MigrationManager
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.learn.config import EntityMemoryConfig
from agno.learn.stores.entity_memory import EntityMemoryStore
from agno.learn.utils import build_learning_id, legacy_entity_learning_id

ALICE = "alice@corp.com"
BOB = "bob@corp.com"
QUARANTINE_NAMESPACE = "quarantined_user"


def _content(entity_id: str, user_id: str, fact: str) -> Dict[str, Any]:
    return {
        "entity_id": entity_id,
        "entity_type": "company",
        "name": entity_id.title(),
        "user_id": user_id,
        "facts": [{"id": "f1", "content": fact}],
        "events": [],
        "relationships": [],
        "aliases": [],
        "properties": {},
    }


@pytest.fixture
def db(tmp_path) -> SqliteDb:
    database = SqliteDb(db_file=str(tmp_path / "learnings.db"))
    # A table created by a 2.x deployment carries its 2.x stamp; a table created
    # fresh is already current and is skipped.
    database.upsert_learning(
        id="seed",
        learning_type="entity_memory",
        namespace="global",
        entity_id="seed",
        entity_type="company",
        content={},
    )
    database.delete_learning(id="seed")
    database.upsert_schema_version(database.learnings_table_name, "2.9.0")
    return database


def _seed_legacy(db: SqliteDb, entity_id: str, owner: Optional[str], content_user: str, fact: str) -> str:
    legacy_id = legacy_entity_learning_id(entity_id, "company", "user")
    db.upsert_learning(
        id=legacy_id,
        learning_type="entity_memory",
        namespace="user",
        user_id=owner,
        entity_id=entity_id,
        entity_type="company",
        content=_content(entity_id, content_user, fact),
    )
    return legacy_id


class TestRekeyRunsWithTheOtherMigrations:
    async def test_a_clean_row_moves_to_its_owners_key(self, db: SqliteDb) -> None:
        legacy_id = _seed_legacy(db, "acme", ALICE, ALICE, "renewal at 50k")

        await MigrationManager(db).up()

        expected = build_learning_id(
            "entity_memory", entity_id="acme", entity_type="company", namespace="user", user_id=ALICE
        )
        assert db.get_learning_by_id(legacy_id) is None
        moved = db.get_learning_by_id(expected)
        assert moved is not None
        assert moved["content"]["facts"][0]["content"] == "renewal at 50k"

    async def test_the_owner_reads_the_entity_back_after_the_migration(self, db: SqliteDb) -> None:
        _seed_legacy(db, "acme", ALICE, ALICE, "renewal at 50k")

        await MigrationManager(db).up()

        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))  # type: ignore[arg-type]
        entity = store.get(entity_id="acme", entity_type="company", user_id=ALICE)
        assert entity is not None
        assert [f["content"] for f in entity.facts] == ["renewal at 50k"]

    async def test_the_table_is_stamped_at_the_new_version(self, db: SqliteDb) -> None:
        _seed_legacy(db, "acme", ALICE, ALICE, "renewal at 50k")

        await MigrationManager(db).up()

        assert db.get_latest_schema_version(db.learnings_table_name) == "3.0.0"

    async def test_a_table_already_at_the_new_version_is_left_alone(self, db: SqliteDb) -> None:
        legacy_id = _seed_legacy(db, "acme", ALICE, ALICE, "renewal at 50k")
        db.upsert_schema_version(db.learnings_table_name, "3.0.0")

        await MigrationManager(db).up()

        assert db.get_learning_by_id(legacy_id) is not None


class TestContaminatedRowsLeaveTheReadableNamespace:
    """A row whose content records a user other than its owner held two users'
    data before the fix. It is not separable, so the migration preserves it
    where no user-filtered read reaches it."""

    async def test_a_contaminated_row_moves_under_the_quarantine_namespace(self, db: SqliteDb) -> None:
        legacy_id = _seed_legacy(db, "globex", ALICE, BOB, "BOB PRIVATE: they churned")

        await MigrationManager(db).up()

        quarantined = legacy_entity_learning_id("globex", "company", QUARANTINE_NAMESPACE)
        assert db.get_learning_by_id(legacy_id) is None
        row = db.get_learning_by_id(quarantined)
        assert row is not None
        assert row["namespace"] == QUARANTINE_NAMESPACE
        assert row["content"]["facts"][0]["content"] == "BOB PRIVATE: they churned"

    async def test_the_owner_cannot_read_a_contaminated_row(self, db: SqliteDb) -> None:
        _seed_legacy(db, "globex", ALICE, BOB, "BOB PRIVATE: they churned")

        await MigrationManager(db).up()

        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))  # type: ignore[arg-type]
        assert store.get(entity_id="globex", entity_type="company", user_id=ALICE) is None
        assert store.list_entities(user_id=ALICE) == []
        context = store.build_context(store.recall(message="What about Globex?", user_id=ALICE))
        assert "BOB PRIVATE" not in context

    async def test_a_clean_row_alongside_a_contaminated_one_still_migrates(self, db: SqliteDb) -> None:
        _seed_legacy(db, "acme", ALICE, ALICE, "renewal at 50k")
        _seed_legacy(db, "globex", ALICE, BOB, "BOB PRIVATE: they churned")

        await MigrationManager(db).up()

        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))  # type: ignore[arg-type]
        entity = store.get(entity_id="acme", entity_type="company", user_id=ALICE)
        assert entity is not None
        assert [f["content"] for f in entity.facts] == ["renewal at 50k"]


class TestOtherTablesAreUntouched:
    async def test_another_table_type_does_not_run_the_rekey(self, db: SqliteDb) -> None:
        """The module also carries the runs and user_id work. Migrating another
        table must leave the learnings rows alone."""
        from agno.db.migrations.versions import v3_0_0

        legacy_id = _seed_legacy(db, "acme", ALICE, ALICE, "renewal at 50k")

        v3_0_0.up(db, "memories", db.memory_table_name)

        assert db.get_learning_by_id(legacy_id) is not None

    async def test_the_rekey_has_no_reverse(self, db: SqliteDb) -> None:
        legacy_id = _seed_legacy(db, "acme", ALICE, ALICE, "renewal at 50k")
        from agno.db.migrations.versions import v3_0_0

        assert v3_0_0.down(db, "learnings", db.learnings_table_name) is False
        assert db.get_learning_by_id(legacy_id) is not None


@pytest.fixture
async def async_db(tmp_path) -> AsyncSqliteDb:
    database = AsyncSqliteDb(db_file=str(tmp_path / "learnings_async.db"))
    # A table created by a 2.x deployment carries its 2.x stamp; a table created
    # fresh is already current and is skipped.
    await database.upsert_learning(
        id="seed",
        learning_type="entity_memory",
        namespace="global",
        entity_id="seed",
        entity_type="company",
        content={},
    )
    await database.delete_learning(id="seed")
    await database.upsert_schema_version(database.learnings_table_name, "2.9.0")
    return database


async def _seed_legacy_async(
    db: AsyncSqliteDb, entity_id: str, owner: Optional[str], content_user: str, fact: str
) -> str:
    legacy_id = legacy_entity_learning_id(entity_id, "company", "user")
    await db.upsert_learning(
        id=legacy_id,
        learning_type="entity_memory",
        namespace="user",
        user_id=owner,
        entity_id=entity_id,
        entity_type="company",
        content=_content(entity_id, content_user, fact),
    )
    return legacy_id


class TestTheRekeyRunsOnAnAsyncDb:
    """An async adapter reaches the re-key through async_up, not through up."""

    async def test_a_clean_row_moves_to_its_owners_key(self, async_db: AsyncSqliteDb) -> None:
        legacy_id = await _seed_legacy_async(async_db, "acme", ALICE, ALICE, "renewal at 50k")

        await MigrationManager(async_db).up()

        expected = build_learning_id(
            "entity_memory", entity_id="acme", entity_type="company", namespace="user", user_id=ALICE
        )
        assert await async_db.get_learning_by_id(legacy_id) is None
        moved = await async_db.get_learning_by_id(expected)
        assert moved is not None
        assert moved["content"]["facts"][0]["content"] == "renewal at 50k"

    async def test_a_contaminated_row_moves_under_the_quarantine_namespace(self, async_db: AsyncSqliteDb) -> None:
        legacy_id = await _seed_legacy_async(async_db, "globex", ALICE, BOB, "BOB PRIVATE: they churned")

        await MigrationManager(async_db).up()

        quarantined = legacy_entity_learning_id("globex", "company", QUARANTINE_NAMESPACE)
        assert await async_db.get_learning_by_id(legacy_id) is None
        row = await async_db.get_learning_by_id(quarantined)
        assert row is not None
        assert row["namespace"] == QUARANTINE_NAMESPACE
        assert row["content"]["facts"][0]["content"] == "BOB PRIVATE: they churned"

    async def test_the_table_is_stamped_at_the_new_version(self, async_db: AsyncSqliteDb) -> None:
        await _seed_legacy_async(async_db, "acme", ALICE, ALICE, "renewal at 50k")

        await MigrationManager(async_db).up()

        assert await async_db.get_latest_schema_version(async_db.learnings_table_name) == "3.0.0"

    async def test_the_rekey_has_no_reverse(self, async_db: AsyncSqliteDb) -> None:
        from agno.db.migrations.versions import v3_0_0

        legacy_id = await _seed_legacy_async(async_db, "acme", ALICE, ALICE, "renewal at 50k")

        assert await v3_0_0.async_down(async_db, "learnings", async_db.learnings_table_name) is False
        assert await async_db.get_learning_by_id(legacy_id) is not None

    async def test_a_table_already_at_the_new_version_is_left_alone(self, async_db: AsyncSqliteDb) -> None:
        legacy_id = await _seed_legacy_async(async_db, "acme", ALICE, ALICE, "renewal at 50k")
        await async_db.upsert_schema_version(async_db.learnings_table_name, "3.0.0")

        await MigrationManager(async_db).up()

        assert await async_db.get_learning_by_id(legacy_id) is not None

    async def test_another_table_type_does_not_run_the_rekey(self, async_db: AsyncSqliteDb) -> None:
        from agno.db.migrations.versions import v3_0_0

        legacy_id = await _seed_legacy_async(async_db, "acme", ALICE, ALICE, "renewal at 50k")

        await v3_0_0.async_up(async_db, "memories", async_db.memory_table_name)

        assert await async_db.get_learning_by_id(legacy_id) is not None


class TestTheStepReportsWhetherItWrote:
    """MigrationManager prints "Successfully applied" or "Skipping application"
    from what the step returns. A row that was folded into an existing row, or
    moved to the quarantine namespace, is a write."""

    def _up(self, db: SqliteDb) -> bool:
        from agno.db.migrations.versions import v3_0_0

        return v3_0_0.up(db, "learnings", db.learnings_table_name)

    async def test_a_plain_move_reports_a_write(self, db: SqliteDb) -> None:
        _seed_legacy(db, "acme", ALICE, ALICE, "renewal at 50k")

        assert self._up(db) is True

    async def test_a_fold_into_an_existing_row_reports_a_write(self, db: SqliteDb) -> None:
        _seed_legacy(db, "acme", ALICE, ALICE, "renewal at 50k")
        db.upsert_learning(
            id=build_learning_id(
                "entity_memory", entity_id="acme", entity_type="company", namespace="user", user_id=ALICE
            ),
            learning_type="entity_memory",
            namespace="user",
            user_id=ALICE,
            entity_id="acme",
            entity_type="company",
            content=_content("acme", ALICE, "written after the upgrade"),
        )

        assert self._up(db) is True

    async def test_a_quarantine_reports_a_write(self, db: SqliteDb) -> None:
        _seed_legacy(db, "globex", ALICE, BOB, "BOB PRIVATE: they churned")

        assert self._up(db) is True

    async def test_a_table_with_nothing_to_move_reports_no_write(self, db: SqliteDb) -> None:
        db.upsert_learning(
            id=build_learning_id(
                "entity_memory", entity_id="acme", entity_type="company", namespace="user", user_id=ALICE
            ),
            learning_type="entity_memory",
            namespace="user",
            user_id=ALICE,
            entity_id="acme",
            entity_type="company",
            content=_content("acme", ALICE, "already on the right key"),
        )

        assert self._up(db) is False
