"""Cross-user isolation for entity memory under namespace="user" (issue #9319).

Before the fix the row key had no user component, so two users recording the
same entity name and type shared one physical row: the first writer's facts
were silently replaced by the second writer's (which then leaked into the
first writer's reads and prompt context), and the second writer could never
read their own data back. These tests pin the isolation property end to end,
including the legacy-row self-heal for rows written under the old key.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

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


class TestLegacyRowSelfHeal:
    """Rows written before the key embedded the user keep matching the owner's
    column-filtered reads next to the new row. The owner's first write must
    merge the legacy content into the user-scoped row and retire the old one;
    other users' writes must leave it alone."""

    def _seed_legacy_row(self, db: RecordingLearningDb, owner: str, fact: str) -> str:
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        db.upsert_learning(
            id=legacy_id,
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="user",
            user_id=owner,
            content={
                "entity_id": "acme",
                "entity_type": "company",
                "name": "Acme",
                "facts": [{"id": "f1", "content": fact}],
                "namespace": "user",
                "user_id": owner,
            },
        )
        return legacy_id

    def test_owners_write_merges_and_retires_legacy_row(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        legacy_id = self._seed_legacy_row(db, ALICE, ALICE_FACT)

        store.remember_about(entity="Acme", entity_type="company", facts=["New note"], user_id=ALICE)

        assert legacy_id not in db.rows
        new_row = db.rows[_user_key("acme", "company", ALICE)]
        content = str(new_row.get("content"))
        assert ALICE_FACT in content
        assert "New note" in content

    def test_other_users_write_leaves_legacy_row_alone(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        legacy_id = self._seed_legacy_row(db, ALICE, ALICE_FACT)

        store.remember_about(entity="Acme", entity_type="company", facts=[BOB_FACT], user_id=BOB)

        assert legacy_id in db.rows
        assert db.rows[legacy_id].get("user_id") == ALICE
        assert ALICE_FACT in str(db.rows[legacy_id].get("content"))
        assert BOB_FACT in str(db.rows[_user_key("acme", "company", BOB)].get("content"))

    def test_owners_delete_also_removes_legacy_row(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        legacy_id = self._seed_legacy_row(db, ALICE, ALICE_FACT)

        assert store.delete(entity_id="acme", entity_type="company", user_id=ALICE) is True
        assert legacy_id not in db.rows

    async def test_async_write_heals_legacy_row(self, db: RecordingLearningDb) -> None:
        # An AsyncBaseDb wrapper so the awaited self-heal branch actually runs.
        from agno.db.base import AsyncBaseDb

        inner = db

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
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=FakeAsyncDb()))
        legacy_id = self._seed_legacy_row(db, ALICE, ALICE_FACT)

        await store.aremember_about(entity="Acme", entity_type="company", facts=["New note"], user_id=ALICE)

        assert legacy_id not in db.rows
        assert ALICE_FACT in str(db.rows[_user_key("acme", "company", ALICE)].get("content"))

        assert await store.adelete(entity_id="acme", entity_type="company", user_id=ALICE) is True
        assert len(db.rows) == 0

    def test_unmerged_legacy_row_is_not_deleted(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        # Both a user-scoped row and a legacy row exist (a migration conflict, or
        # a rolling deploy). The column-filtered resolution read is not guaranteed
        # to pick the legacy row -- here the fake returns the user-scoped one --
        # so the write must not delete legacy content it never merged.
        new_id = _user_key("acme", "company", ALICE)
        db.upsert_learning(
            id=new_id,
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="user",
            user_id=ALICE,
            content={
                "entity_id": "acme",
                "entity_type": "company",
                "name": "Acme",
                "facts": [{"id": "n1", "content": "kept fact"}],
                "namespace": "user",
                "user_id": ALICE,
            },
        )
        legacy_id = self._seed_legacy_row(db, ALICE, "legacy fact worth money")

        store.remember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert legacy_id in db.rows
        assert "legacy fact worth money" in str(db.rows[legacy_id].get("content"))

    def test_contaminated_legacy_row_is_left_for_the_migration(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # Column owner and content-recorded user disagree: the row provably holds
        # another user's data, and the migration is the surface that reports and
        # purges it -- the write path must not destroy the evidence.
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        db.upsert_learning(
            id=legacy_id,
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="user",
            user_id=ALICE,
            content={
                "entity_id": "acme",
                "entity_type": "company",
                "name": "Acme",
                "facts": [{"id": "f1", "content": BOB_FACT}],
                "namespace": "user",
                "user_id": BOB,
            },
        )

        store.remember_about(entity="Acme", entity_type="company", facts=["a new note"], user_id=ALICE)

        assert legacy_id in db.rows
        assert BOB_FACT in str(db.rows[legacy_id].get("content"))

    def test_digest_shaped_entity_type_cannot_delete_a_user_scoped_row(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # A user-scoped id parses as a legacy id whose entity_type is the digest
        # segment, so a write naming that digest as its entity_type computes a
        # legacy id equal to an existing row's key. The column cross-check must
        # keep the row: forget only archives and delete is not a tool, so the
        # write path must not hand the model a hard-delete primitive.
        store.remember_about(entity="Bob Smith", entity_type="person", facts=["victim fact"], user_id=ALICE)
        target_id = _user_key("bob_smith", "person", ALICE)
        assert target_id in db.rows
        digest = target_id.split("_")[2]

        store.remember_about(entity="person bob smith", entity_type=digest, facts=["attack"], user_id=ALICE)

        assert target_id in db.rows
        assert "victim fact" in str(db.rows[target_id].get("content"))

    def test_failed_save_keeps_legacy_row(self) -> None:
        # The adapters' upsert_learning swallows failures, so the save path
        # verifies the new row landed before retiring the legacy one.
        new_id = _user_key("acme", "company", ALICE)

        class DroppyDb(RecordingLearningDb):
            def upsert_learning(self, id: str, **kwargs: Any) -> None:
                if id == new_id:
                    return
                super().upsert_learning(id=id, **kwargs)

        db = DroppyDb()
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))  # type: ignore[arg-type]
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        db.upsert_learning(
            id=legacy_id,
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="user",
            user_id=ALICE,
            content={
                "entity_id": "acme",
                "entity_type": "company",
                "name": "Acme",
                "facts": [{"id": "f1", "content": ALICE_FACT}],
                "namespace": "user",
                "user_id": ALICE,
            },
        )

        store.remember_about(entity="Acme", entity_type="company", facts=["lost note"], user_id=ALICE)

        assert legacy_id in db.rows
        assert ALICE_FACT in str(db.rows[legacy_id].get("content"))

    def test_backend_without_get_learning_by_id_still_saves(self) -> None:
        class NoByIdDb(RecordingLearningDb):
            def get_learning_by_id(self, id: str) -> Any:
                raise NotImplementedError

        db = NoByIdDb()
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))  # type: ignore[arg-type]

        message = store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)

        assert "Recorded" in message
        assert _user_key("acme", "company", ALICE) in db.rows


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
        assert dirty in db.rows

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
        assert clean not in inner.rows and dirty in inner.rows

        second = await arekey_user_entity_learnings(AsyncPagingDb(), dry_run=False)
        assert second["rekeyed"] == []
