"""Cross-user isolation for entity memory under namespace="user" (issue #9319).

Before the fix the row key had no user component, so two users recording the
same entity name and type shared one physical row: the first writer's facts
were silently replaced by the second writer's (which then leaked into the
first writer's reads and prompt context), and the second writer could never
read their own data back. These tests pin the isolation property end to end,
including the legacy-row self-heal for rows written under the old key.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agno.db.base import AsyncBaseDb
from agno.learn.config import EntityMemoryConfig
from agno.learn.stores.entity_memory import EntityMemoryStore
from agno.learn.utils import build_learning_id, legacy_entity_learning_id

from .test_entity_memory_store import RecordingLearningDb

ALICE = "alice@corp.com"
BOB = "bob@corp.com"
ALICE_FACT = "Alice's private note: renewal at 50k"
BOB_FACT = "Bob's private note: they churned"


def _user_key(entity_id: str, entity_type: str, user_id: str) -> str:
    key = build_learning_id(
        "entity_memory", entity_id=entity_id, entity_type=entity_type, namespace="user", user_id=user_id
    )
    assert key is not None
    return key


@pytest.fixture
def db() -> RecordingLearningDb:
    return RecordingLearningDb()


@pytest.fixture
def store(db: RecordingLearningDb) -> EntityMemoryStore:
    return EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))  # type: ignore[arg-type]


class TestUserNamespaceIsolation:
    def test_same_named_entities_get_distinct_rows(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        store.remember_about(entity="Acme", entity_type="company", facts=[BOB_FACT], user_id=BOB)

        assert len(db.rows) == 2
        assert _user_key("acme", "company", ALICE) in db.rows
        assert _user_key("acme", "company", BOB) in db.rows

    def test_each_user_reads_only_their_own_facts(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        store.remember_about(entity="Acme", entity_type="company", facts=[BOB_FACT], user_id=BOB)

        alice_entity = store.get(entity_id="acme", entity_type="company", user_id=ALICE)
        bob_entity = store.get(entity_id="acme", entity_type="company", user_id=BOB)

        assert alice_entity is not None and bob_entity is not None
        alice_facts = [f["content"] for f in alice_entity.facts]
        bob_facts = [f["content"] for f in bob_entity.facts]
        assert alice_facts == [ALICE_FACT]
        assert bob_facts == [BOB_FACT]

    def test_first_writers_facts_survive_second_write(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        store.remember_about(entity="Acme", entity_type="company", facts=[BOB_FACT], user_id=BOB)

        alice_row = db.rows[_user_key("acme", "company", ALICE)]
        assert alice_row.get("user_id") == ALICE
        assert ALICE_FACT in str(alice_row.get("content"))
        assert BOB_FACT not in str(alice_row.get("content"))

    def test_recall_context_excludes_other_users_facts(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        store.remember_about(entity="Acme", entity_type="company", facts=[BOB_FACT], user_id=BOB)

        recalled = store.recall(message="What do we know about Acme?", user_id=ALICE)
        context = store.build_context(recalled)
        assert BOB_FACT not in context
        assert ALICE_FACT in context

    def test_list_entities_is_per_user(self, store: EntityMemoryStore) -> None:
        # Same name and type on both sides: the exact collision the key change
        # exists for, so each user must see their own single row.
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        store.remember_about(entity="Acme", entity_type="company", facts=[BOB_FACT], user_id=BOB)

        alice_entities = store.list_entities(user_id=ALICE)
        bob_entities = store.list_entities(user_id=BOB)
        assert [e.name for e in alice_entities] == ["Acme"]
        assert [e.name for e in bob_entities] == ["Acme"]
        assert [f["content"] for f in alice_entities[0].facts] == [ALICE_FACT]
        assert [f["content"] for f in bob_entities[0].facts] == [BOB_FACT]

    def test_search_entities_is_per_user(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        store.remember_about(entity="Acme", entity_type="company", facts=[BOB_FACT], user_id=BOB)

        alice_results = store.search_entities(query="Acme", user_id=ALICE)
        assert ALICE_FACT in alice_results
        assert BOB_FACT not in alice_results

    def test_forget_does_not_cross_users(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        store.remember_about(entity="Acme", entity_type="company", facts=[BOB_FACT], user_id=BOB)

        store.forget(entity="Acme", user_id=BOB)

        alice_content = db.rows[_user_key("acme", "company", ALICE)]["content"]
        assert [f["content"] for f in alice_content["facts"]] == [ALICE_FACT]
        assert alice_content.get("archived_at") is None

    def test_delete_does_not_cross_users(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        store.remember_about(entity="Acme", entity_type="company", facts=[BOB_FACT], user_id=BOB)

        assert store.delete(entity_id="acme", entity_type="company", user_id=BOB) is True
        assert _user_key("acme", "company", ALICE) in db.rows
        assert _user_key("acme", "company", BOB) not in db.rows

    async def test_async_paths_are_isolated_too(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        await store.aremember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        await store.aremember_about(entity="Acme", entity_type="company", facts=[BOB_FACT], user_id=BOB)

        assert len(db.rows) == 2
        alice_entity = await store.aget(entity_id="acme", entity_type="company", user_id=ALICE)
        bob_entity = await store.aget(entity_id="acme", entity_type="company", user_id=BOB)
        assert alice_entity is not None and [f["content"] for f in alice_entity.facts] == [ALICE_FACT]
        assert bob_entity is not None and [f["content"] for f in bob_entity.facts] == [BOB_FACT]


class TestUserNamespaceFailsClosed:
    """Every entry point must refuse namespace="user" without a user_id instead
    of falling through to an unfiltered read or an unkeyed write."""

    def test_get_refused_without_user_id(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        assert store.get(entity_id="acme", entity_type="company") is None

    async def test_aget_refused_without_user_id(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        assert await store.aget(entity_id="acme", entity_type="company") is None

    def test_delete_refused_without_user_id(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        assert store.delete(entity_id="acme", entity_type="company") is False
        assert len(db.rows) == 1

    async def test_adelete_refused_without_user_id(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        assert await store.adelete(entity_id="acme", entity_type="company") is False
        assert len(db.rows) == 1

    def test_remember_refused_without_user_id(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        message = store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT])
        assert "user_id" in message
        assert len(db.rows) == 0


class TestUserNamespaceRelationships:
    def test_links_and_far_edge_detach_stay_per_user(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.link_entities(entity="Radar", relation="runs_on", related_entity="Postgres", user_id=ALICE)
        store.link_entities(entity="Radar", relation="runs_on", related_entity="Postgres", user_id=BOB)
        assert len(db.rows) == 4

        message = store.forget(entity="Radar", fact="runs_on -> Postgres", user_id=ALICE)
        assert "Removed relationship" in message

        alice_far = store.get(entity_id="postgres", entity_type="unknown", user_id=ALICE)
        bob_near = store.get(entity_id="radar", entity_type="unknown", user_id=BOB)
        bob_far = store.get(entity_id="postgres", entity_type="unknown", user_id=BOB)
        assert alice_far is not None and alice_far.relationships == []
        assert bob_near is not None and len(bob_near.relationships) == 1
        assert bob_far is not None and len(bob_far.relationships) == 1

    def test_unknown_type_upgrade_rekeys_within_user(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        # link_entities mints "unknown"-typed placeholders; a later remember_about
        # with the real type must replace this user's placeholder row only.
        store.link_entities(entity="Radar", relation="runs_on", related_entity="Postgres", user_id=ALICE)
        store.link_entities(entity="Radar", relation="runs_on", related_entity="Postgres", user_id=BOB)

        store.remember_about(entity="Radar", entity_type="project", facts=["ships weekly"], user_id=ALICE)

        assert _user_key("radar", "unknown", ALICE) not in db.rows
        assert _user_key("radar", "project", ALICE) in db.rows
        assert _user_key("radar", "unknown", BOB) in db.rows


class _PagingLearningDb(RecordingLearningDb):
    """Adds the paginated listing surface the re-key migration walks."""

    def list_learnings(self, **kwargs: Any) -> Tuple[List[Dict[str, Any]], int]:
        learning_type = kwargs.get("learning_type")
        namespace = kwargs.get("namespace")
        limit = kwargs.get("limit") or 100
        page = kwargs.get("page") or 1
        rows = [
            dict(row)
            for row in self.rows.values()
            if (learning_type is None or row.get("learning_type") == learning_type)
            and (namespace is None or row.get("namespace") == namespace)
        ]
        start = (page - 1) * limit
        return rows[start : start + limit], len(rows)


class TestRekeyMigration:
    def _seed(self, db: _PagingLearningDb, entity_id: str, owner: Optional[str], content_user: Optional[str]) -> str:
        legacy_id = legacy_entity_learning_id(entity_id, "company", "user")
        db.upsert_learning(
            id=legacy_id,
            learning_type="entity_memory",
            entity_id=entity_id,
            entity_type="company",
            namespace="user",
            user_id=owner,
            content={"entity_id": entity_id, "entity_type": "company", "name": entity_id, "user_id": content_user},
        )
        return legacy_id

    def test_dry_run_reports_without_writing(self) -> None:
        from agno.learn.migrations import rekey_user_entity_learnings

        db = _PagingLearningDb()
        clean = self._seed(db, "acme", ALICE, ALICE)
        dirty = self._seed(db, "initech", ALICE, BOB)
        unowned = self._seed(db, "hooli", None, None)

        report = rekey_user_entity_learnings(db, dry_run=True)  # type: ignore[arg-type]

        assert report["rekeyed"] == [clean]
        assert report["contaminated"] == [dirty]
        assert report["unowned"] == [unowned]
        assert set(db.rows) == {clean, dirty, unowned}

    def test_rekey_moves_clean_rows_only(self) -> None:
        from agno.learn.migrations import rekey_user_entity_learnings

        db = _PagingLearningDb()
        clean = self._seed(db, "acme", ALICE, ALICE)
        dirty = self._seed(db, "initech", ALICE, BOB)

        report = rekey_user_entity_learnings(db, dry_run=False)  # type: ignore[arg-type]

        new_id = _user_key("acme", "company", ALICE)
        assert report["rekeyed"] == [clean]
        assert clean not in db.rows and new_id in db.rows
        assert db.rows[new_id].get("user_id") == ALICE
        # A contaminated row is not separable, so it moves under the quarantine
        # namespace: out of every user-filtered read, content preserved.
        quarantined = legacy_entity_learning_id("initech", "company", "quarantined_user")
        assert dirty not in db.rows
        assert quarantined in db.rows

    def test_purge_removes_contaminated_and_unowned_rows(self) -> None:
        from agno.learn.migrations import rekey_user_entity_learnings

        db = _PagingLearningDb()
        dirty = self._seed(db, "initech", ALICE, BOB)
        unowned = self._seed(db, "hooli", None, None)

        report = rekey_user_entity_learnings(db, dry_run=False, purge_unrecoverable=True)  # type: ignore[arg-type]

        assert sorted(report["purged"]) == sorted([dirty, unowned])
        assert len(db.rows) == 0

    def test_existing_target_row_is_a_conflict(self) -> None:
        from agno.learn.migrations import rekey_user_entity_learnings

        db = _PagingLearningDb()
        legacy = self._seed(db, "acme", ALICE, ALICE)
        new_id = _user_key("acme", "company", ALICE)
        db.upsert_learning(
            id=new_id,
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="user",
            user_id=ALICE,
            content={"entity_id": "acme", "entity_type": "company", "user_id": ALICE},
        )

        report = rekey_user_entity_learnings(db, dry_run=False)  # type: ignore[arg-type]

        assert report["conflicts"] == [legacy]
        assert legacy in db.rows and new_id in db.rows

    def test_rekey_is_idempotent(self) -> None:
        from agno.learn.migrations import rekey_user_entity_learnings

        db = _PagingLearningDb()
        self._seed(db, "acme", ALICE, ALICE)

        first = rekey_user_entity_learnings(db, dry_run=False)  # type: ignore[arg-type]
        second = rekey_user_entity_learnings(db, dry_run=False)  # type: ignore[arg-type]

        assert len(first["rekeyed"]) == 1
        assert second["rekeyed"] == []
        assert second["scanned"] == 1

    def test_rekey_walks_multiple_pages(self) -> None:
        from agno.learn.migrations import _PAGE_SIZE, rekey_user_entity_learnings

        db = _PagingLearningDb()
        seeded = [self._seed(db, f"entity{i}", ALICE, ALICE) for i in range(_PAGE_SIZE + 1)]

        report = rekey_user_entity_learnings(db, dry_run=False)  # type: ignore[arg-type]

        assert sorted(report["rekeyed"]) == sorted(seeded)
        assert len(db.rows) == len(seeded)

    def test_failed_upsert_keeps_source_row(self) -> None:
        # The adapters' upsert_learning swallows failures, so the migration must
        # read the re-keyed row back before deleting the original.
        from agno.learn.migrations import rekey_user_entity_learnings

        new_id = _user_key("acme", "company", ALICE)

        class DroppyPagingDb(_PagingLearningDb):
            def upsert_learning(self, id: str, **kwargs: Any) -> None:
                if id == new_id:
                    return
                super().upsert_learning(id=id, **kwargs)

        db = DroppyPagingDb()
        legacy = self._seed(db, "acme", ALICE, ALICE)

        report = rekey_user_entity_learnings(db, dry_run=False)  # type: ignore[arg-type]

        assert report["failed"] == [legacy]
        assert report["rekeyed"] == []
        assert legacy in db.rows

    def test_malformed_rows_are_reported_never_purged(self) -> None:
        from agno.learn.migrations import rekey_user_entity_learnings

        db = _PagingLearningDb()
        db.upsert_learning(
            id="entity_user_broken",
            learning_type="entity_memory",
            entity_id=None,
            entity_type=None,
            namespace="user",
            user_id=ALICE,
            content={},
        )

        report = rekey_user_entity_learnings(db, dry_run=False, purge_unrecoverable=True)  # type: ignore[arg-type]

        assert report["malformed"] == ["entity_user_broken"]
        assert report["purged"] == []
        assert "entity_user_broken" in db.rows

    async def test_async_rekey_matches_sync(self) -> None:
        from agno.db.base import AsyncBaseDb
        from agno.learn.migrations import arekey_user_entity_learnings

        inner = _PagingLearningDb()

        class AsyncPagingDb(AsyncBaseDb):
            def __init__(self) -> None:
                pass

            async def list_learnings(self, **kwargs: Any) -> Any:
                return inner.list_learnings(**kwargs)

            async def get_learning_by_id(self, id: str) -> Any:
                return inner.get_learning_by_id(id)

            async def upsert_learning(self, **kwargs: Any) -> None:
                inner.upsert_learning(**kwargs)

            async def delete_learning(self, id: str) -> bool:
                return inner.delete_learning(id)

        AsyncPagingDb.__abstractmethods__ = frozenset()  # type: ignore[attr-defined]
        clean = self._seed(inner, "acme", ALICE, ALICE)
        dirty = self._seed(inner, "initech", ALICE, BOB)

        report = await arekey_user_entity_learnings(AsyncPagingDb(), dry_run=False)

        assert report["rekeyed"] == [clean]
        assert report["contaminated"] == [dirty]
        assert _user_key("acme", "company", ALICE) in inner.rows
        quarantined = legacy_entity_learning_id("initech", "company", "quarantined_user")
        assert clean not in inner.rows
        assert dirty not in inner.rows and quarantined in inner.rows

        second = await arekey_user_entity_learnings(AsyncPagingDb(), dry_run=False)
        assert second["rekeyed"] == []


class _SilentUpsertDb(RecordingLearningDb):
    """Models the adapters: upsert_learning can write nothing and still return.

    Every adapter catches its own write exception and log_debugs it, so the
    caller sees a normal return from a save that never reached the table.
    """

    def __init__(self) -> None:
        super().__init__()
        self.writes_land = True

    def upsert_learning(self, id: str, **kwargs: Any) -> None:
        if not self.writes_land:
            return
        super().upsert_learning(id=id, **kwargs)


def _async_facade(inner: RecordingLearningDb) -> Any:
    """AsyncBaseDb facade over the recording fake so the awaited paths run."""
    from agno.db.base import AsyncBaseDb

    class FakeAsyncDb(AsyncBaseDb):
        def __init__(self) -> None:
            pass

        async def get_learning(self, **kwargs: Any) -> Any:
            return inner.get_learning(**kwargs)

        async def get_learnings(self, **kwargs: Any) -> Any:
            return inner.get_learnings(**kwargs)

        async def search_learnings(self, query: str, **kwargs: Any) -> Any:
            return inner.search_learnings(query, **kwargs)

        async def upsert_learning(self, **kwargs: Any) -> None:
            inner.upsert_learning(**kwargs)

        async def get_learning_by_id(self, id: str) -> Any:
            return inner.get_learning_by_id(id)

        async def delete_learning(self, id: str) -> bool:
            return inner.delete_learning(id)

    FakeAsyncDb.__abstractmethods__ = frozenset()  # type: ignore[attr-defined]
    return FakeAsyncDb()


LEGACY_FACT = "legacy fact worth money"
CURRENT_FACT = "post-upgrade fact worth money"


class TestKeyedRowIdentityColumns:
    """A row fetched by primary key is served only when its identity columns
    name this caller's entity. The user-scoped key embeds a digest of the
    owner, but the REST create route derives that same id from a
    caller-supplied namespace, so the key alone does not prove ownership."""

    def _seed(self, db: RecordingLearningDb, **overrides: Any) -> str:
        """Put a row at ALICE's user-scoped key for acme/company, with the
        identity columns and content the caller overrides."""
        row_id = _user_key("acme", "company", ALICE)
        columns: Dict[str, Any] = {
            "learning_type": "entity_memory",
            "entity_id": "acme",
            "entity_type": "company",
            "namespace": "user",
            "user_id": ALICE,
            "content": {
                "entity_id": "acme",
                "entity_type": "company",
                "name": "Acme",
                "facts": [{"id": "f1", "content": ALICE_FACT}],
                "namespace": "user",
                "user_id": ALICE,
            },
        }
        columns.update(overrides)
        db.upsert_learning(id=row_id, **columns)
        return row_id

    def _foreign_content(self) -> Dict[str, Any]:
        return {
            "entity_id": "acme",
            "entity_type": "company",
            "name": "Acme",
            "facts": [{"id": "f1", "content": BOB_FACT}],
            "namespace": "user",
            "user_id": BOB,
        }

    def test_row_owned_by_another_user_is_not_served(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        row_id = self._seed(db, user_id=BOB, content=self._foreign_content())

        assert store.get(entity_id="acme", entity_type="company", user_id=ALICE) is None
        # The row is another user's data, not evidence to clean up.
        assert row_id in db.rows
        assert BOB_FACT in str(db.rows[row_id].get("content"))

    async def test_row_owned_by_another_user_is_not_served_by_the_async_read(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        self._seed(db, user_id=BOB, content=self._foreign_content())

        assert await store.aget(entity_id="acme", entity_type="company", user_id=ALICE) is None

    def test_row_carrying_another_namespace_is_not_served(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # The digest segment of the key is what the REST create route derives
        # from the caller's namespace, so a namespace of "user_<digest>_company"
        # lands a row on this exact key without being a "user"-namespace row.
        digest = _user_key("acme", "company", ALICE).split("_")[2]
        self._seed(db, namespace=f"user_{digest}_company", user_id=BOB, content=self._foreign_content())

        assert store.get(entity_id="acme", entity_type="company", user_id=ALICE) is None

    async def test_row_carrying_another_namespace_is_not_served_by_the_async_read(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        digest = _user_key("acme", "company", ALICE).split("_")[2]
        self._seed(db, namespace=f"user_{digest}_company", user_id=BOB, content=self._foreign_content())

        assert await store.aget(entity_id="acme", entity_type="company", user_id=ALICE) is None

    def test_row_naming_another_entity_id_is_not_served(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        self._seed(
            db,
            entity_id="initech",
            content={
                "entity_id": "initech",
                "entity_type": "company",
                "name": "Initech",
                "facts": [{"id": "f1", "content": "wrong entity fact"}],
                "namespace": "user",
                "user_id": ALICE,
            },
        )

        assert store.get(entity_id="acme", entity_type="company", user_id=ALICE) is None

    def test_row_naming_another_entity_type_is_not_served(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        self._seed(
            db,
            entity_type="project",
            content={
                "entity_id": "acme",
                "entity_type": "project",
                "name": "Acme",
                "facts": [{"id": "f1", "content": "wrong type fact"}],
                "namespace": "user",
                "user_id": ALICE,
            },
        )

        assert store.get(entity_id="acme", entity_type="company", user_id=ALICE) is None

    def test_row_carrying_another_learning_type_is_not_served(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        self._seed(db, learning_type="user_memory", user_id=BOB, content=self._foreign_content())

        assert store.get(entity_id="acme", entity_type="company", user_id=ALICE) is None

    def test_row_owned_by_another_user_never_reaches_the_prompt_context(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        self._seed(db, user_id=BOB, content=self._foreign_content())

        recalled = store.recall(entity_id="acme", entity_type="company", user_id=ALICE)
        context = store.build_context(recalled)
        assert BOB_FACT not in str(context)

    async def test_row_owned_by_another_user_never_reaches_the_async_prompt_context(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        self._seed(db, user_id=BOB, content=self._foreign_content())

        recalled = await store.arecall(entity_id="acme", entity_type="company", user_id=ALICE)
        context = store.build_context(recalled)
        assert BOB_FACT not in str(context)

    def test_contaminated_keyed_row_is_served_in_full_to_its_owner(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # The owner's first post-upgrade write merged a contaminated legacy row
        # into their user-scoped row and carried the other user's recorded
        # user_id in the content along with it. The columns are the owner's, the
        # row holds the owner's own facts, and the migration only ever reports
        # it - so the owner keeps reading all of it.
        row_id = self._seed(
            db,
            content={
                "entity_id": "acme",
                "entity_type": "company",
                "name": "Acme",
                "facts": [
                    {"id": "f1", "content": ALICE_FACT},
                    {"id": "f2", "content": "merged legacy note: pilot signed"},
                ],
                "namespace": "user",
                "user_id": BOB,
            },
        )

        entity = store.get(entity_id="acme", entity_type="company", user_id=ALICE)

        assert entity is not None
        assert [f["content"] for f in entity.facts] == [ALICE_FACT, "merged legacy note: pilot signed"]
        context = store.build_context(store.recall(entity_id="acme", entity_type="company", user_id=ALICE))
        assert ALICE_FACT in context
        assert "merged legacy note: pilot signed" in context
        assert row_id in db.rows

    async def test_contaminated_keyed_row_is_served_in_full_by_the_async_read(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        self._seed(
            db,
            content={
                "entity_id": "acme",
                "entity_type": "company",
                "name": "Acme",
                "facts": [
                    {"id": "f1", "content": ALICE_FACT},
                    {"id": "f2", "content": "merged legacy note: pilot signed"},
                ],
                "namespace": "user",
                "user_id": BOB,
            },
        )

        entity = await store.aget(entity_id="acme", entity_type="company", user_id=ALICE)

        assert entity is not None
        assert [f["content"] for f in entity.facts] == [ALICE_FACT, "merged legacy note: pilot signed"]

    def test_owners_own_row_still_reads_back(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)

        entity = store.get(entity_id="acme", entity_type="company", user_id=ALICE)
        assert entity is not None
        assert [f["content"] for f in entity.facts] == [ALICE_FACT]

        followup = store.remember_about(entity="Acme", entity_type="company", facts=["renewal in Q3"], user_id=ALICE)
        assert "Updated" in followup or "Recorded" in followup
        entity = store.get(entity_id="acme", entity_type="company", user_id=ALICE)
        assert entity is not None
        assert [f["content"] for f in entity.facts] == [ALICE_FACT, "renewal in Q3"]

    async def test_owners_own_row_still_reads_back_async(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)

        entity = await store.aget(entity_id="acme", entity_type="company", user_id=ALICE)
        assert entity is not None
        assert [f["content"] for f in entity.facts] == [ALICE_FACT]


class _AsyncLearningDb(AsyncBaseDb):
    """Async facade over the in-memory fake so the awaited branches run."""

    def __init__(self, inner: RecordingLearningDb) -> None:
        self.inner = inner

    async def get_learning(self, **kwargs: Any) -> Any:
        return self.inner.get_learning(**kwargs)

    async def get_learnings(self, **kwargs: Any) -> Any:
        return self.inner.get_learnings(**kwargs)

    async def search_learnings(self, query: str, **kwargs: Any) -> Any:
        return self.inner.search_learnings(query, **kwargs)

    async def upsert_learning(self, **kwargs: Any) -> None:
        self.inner.upsert_learning(**kwargs)

    async def get_learning_by_id(self, id: str) -> Any:
        return self.inner.get_learning_by_id(id)

    async def delete_learning(self, id: str) -> bool:
        return self.inner.delete_learning(id)


_AsyncLearningDb.__abstractmethods__ = frozenset()  # type: ignore[attr-defined]


class _ProbeCountingDb(RecordingLearningDb):
    """Records every primary-key read so the skipped legacy probe is observable."""

    def __init__(self) -> None:
        super().__init__()
        self.by_id_reads: List[str] = []

    def get_learning_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        self.by_id_reads.append(id)
        return super().get_learning_by_id(id)


class TestNonStringUserIds:
    """The owner column is a string column, so a non-string user id reads back as
    its ``str()``. The entity key applies the same coercion, so an integer user id
    must still match its own rows on every gated read.
    """

    INT_USER = 42

    def _legacy_row(self, db: RecordingLearningDb, owner: Any, fact: str) -> str:
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        db.upsert_learning(
            id=legacy_id,
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="user",
            user_id=str(owner),
            content={
                "entity_id": "acme",
                "entity_type": "company",
                "name": "Acme",
                "user_id": owner,
                "facts": [{"id": "L1", "content": fact}],
                "events": [],
                "relationships": [],
                "aliases": [],
                "properties": {},
            },
        )
        return legacy_id

    def test_integer_user_reads_back_its_own_entity(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=self.INT_USER)

        entity = store.get(entity_id="acme", entity_type="company", user_id=self.INT_USER)

        assert entity is not None
        assert [f["content"] for f in entity.facts] == [ALICE_FACT]

    async def test_integer_user_reads_back_its_own_entity_async(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=self.INT_USER)

        entity = await store.aget(entity_id="acme", entity_type="company", user_id=self.INT_USER)

        assert entity is not None
        assert [f["content"] for f in entity.facts] == [ALICE_FACT]

    def test_integer_user_does_not_reach_another_users_row(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # A different user whose id coerces to a different string stays separate.
        self._legacy_row(db, 43, BOB_FACT)

        entity = store.get(entity_id="acme", entity_type="company", user_id=self.INT_USER)

        assert entity is None


LEGACY_DESCRIPTION = "Enterprise customer since 2024"
CURRENT_DESCRIPTION = "Renewal owned by the platform team"
LEGACY_NOTE = "notes/acme-legacy.md"
CURRENT_NOTE = "notes/acme-current.md"
PILOT_EVENT = "signed the pilot"


def _acme_row(
    row_id: str,
    facts: List[Dict[str, Any]],
    description: Optional[str] = None,
    note: Optional[str] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Columns for one ALICE-owned acme/company row, ready to splat into upsert_learning."""
    return {
        "id": row_id,
        "learning_type": "entity_memory",
        "entity_id": "acme",
        "entity_type": "company",
        "namespace": "user",
        "user_id": ALICE,
        "content": {
            "entity_id": "acme",
            "entity_type": "company",
            "name": "Acme",
            "description": description,
            "properties": {"note": note} if note else {},
            "facts": facts,
            "events": events or [],
            "namespace": "user",
            "user_id": ALICE,
        },
    }


def _stored_content(rows: List[Dict[str, Any]]) -> str:
    """Every learning row's content as one JSON blob, for "survives anywhere" checks."""
    return json.dumps([row.get("content") for row in rows], default=str)


class TestNonStringEntityTypeInStoredContent:
    """Resolution reads entity_type out of a row's content.

    Content is arbitrary JSON over the REST create route, so entity_type is not
    always a string there. The name-matching path compares it against the type
    on the call, and every tool that resolves by name reaches that comparison.
    """

    def _seed_numeric_type(self, db: RecordingLearningDb) -> None:
        db.upsert_learning(
            id="entity_global_company_acme",
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="global",
            content={
                "entity_id": "acme",
                "entity_type": 123,
                "name": "Acme",
                "facts": [],
                "events": [],
                "relationships": [],
                "aliases": [],
                "properties": {},
            },
        )

    def test_link_entities_resolves_by_name_without_raising(self, db: RecordingLearningDb) -> None:
        self._seed_numeric_type(db)
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db))  # type: ignore[arg-type]

        result = store.link_entities(entity="Acme", relation="partner_of", related_entity="Globex")

        assert isinstance(result, str)

    def test_forget_resolves_by_name_without_raising(self, db: RecordingLearningDb) -> None:
        self._seed_numeric_type(db)
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db))  # type: ignore[arg-type]

        result = store.forget(entity="Acme")

        assert isinstance(result, str)

    def test_a_string_entity_type_still_normalizes(self, db: RecordingLearningDb) -> None:
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db))  # type: ignore[arg-type]

        store.remember_about(entity="Sarah", entity_type="People", facts=["likes tea"])

        assert "entity_global_person_sarah" in db.rows
