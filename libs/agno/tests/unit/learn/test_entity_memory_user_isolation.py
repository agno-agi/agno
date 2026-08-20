"""Cross-user isolation for entity memory under namespace="user" (issue #9319).

Before the fix the row key had no user component, so two users recording the
same entity name and type shared one physical row: the first writer's facts
were silently replaced by the second writer's (which then leaked into the
first writer's reads and prompt context), and the second writer could never
read their own data back. These tests pin the isolation property end to end,
including the legacy-row self-heal for rows written under the old key.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agno.db.base import AsyncBaseDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
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

    def test_coexisting_rows_merge_without_losing_either_side(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # Both a user-scoped row and a legacy row exist (a migration conflict,
        # or a rolling deploy). The write path reads BOTH by primary key and
        # merges, so no matter which row the backend's unordered column read
        # would have returned, a write loses neither the user-scoped row's
        # newer facts nor the legacy row's - and the merged save carries the
        # legacy content, so the legacy row is retired.
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
                "facts": [{"id": "n1", "content": "post-upgrade fact worth money"}],
                "namespace": "user",
                "user_id": ALICE,
            },
        )
        legacy_id = self._seed_legacy_row(db, ALICE, "legacy fact worth money")

        store.remember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert legacy_id not in db.rows
        content = str(db.rows[new_id].get("content"))
        assert "post-upgrade fact worth money" in content
        assert "legacy fact worth money" in content
        assert "today's note" in content

    def test_coexisting_rows_merge_when_the_column_read_prefers_the_legacy_row(self, db: RecordingLearningDb) -> None:
        # Same pair, but the fake resolves column-filtered single-row reads to
        # the OLDEST insertion (the direction real backends take: the legacy
        # row predates the user-scoped one, so an unordered fetchone returns
        # it). The keyed pair read must make the outcome identical.
        legacy_id = self._seed_legacy_row(db, ALICE, "legacy fact worth money")
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
                "facts": [{"id": "n1", "content": "post-upgrade fact worth money"}],
                "namespace": "user",
                "user_id": ALICE,
            },
        )
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))

        store.remember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert legacy_id not in db.rows
        content = str(db.rows[new_id].get("content"))
        assert "post-upgrade fact worth money" in content
        assert "legacy fact worth money" in content
        assert "today's note" in content

    def test_legacy_description_note_and_aliases_survive_the_merge(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # A legacy row whose whole value lives outside facts/events/
        # relationships: description, the note pointer and aliases must be
        # carried into the user-scoped row, not destroyed with the legacy row.
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
                "description": "Enterprise customer since 2024",
                "properties": {"note": "notes/acme.md"},
                "aliases": ["Acme Inc"],
                "facts": [],
                "namespace": "user",
                "user_id": ALICE,
            },
        )

        store.remember_about(entity="Acme", entity_type="company", facts=["renewal in Q3"], user_id=ALICE)

        assert legacy_id not in db.rows
        new_row = db.rows[_user_key("acme", "company", ALICE)]
        content = str(new_row.get("content"))
        assert "Enterprise customer since 2024" in content
        assert "notes/acme.md" in content
        assert "Acme Inc" in content

    def test_forget_is_not_reversed_by_the_legacy_row(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        # forget physically removes events, which makes the saved row a strict
        # subset of the legacy row. The write's own resolution read merged that
        # row, so the removal is intentional and the legacy row must go with
        # it - otherwise the forgotten event keeps rendering and the next
        # write resurrects it.
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
                "facts": [],
                "events": [{"content": "signed the pilot", "date": "2026-05-01"}],
                "namespace": "user",
                "user_id": ALICE,
            },
        )

        result = store.forget(entity="Acme", fact="signed the pilot", user_id=ALICE)

        assert "signed the pilot" in result
        assert legacy_id not in db.rows
        remaining = [str(row.get("content")) for row in db.rows.values()]
        assert all("signed the pilot" not in content for content in remaining)

        followup = store.remember_about(entity="Acme", entity_type="company", facts=["stayed on"], user_id=ALICE)
        assert "Updated" in followup or "Created" in followup
        remaining = [str(row.get("content")) for row in db.rows.values()]
        assert all("signed the pilot" not in content for content in remaining)

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
        # The write must not have absorbed the other user's data either: the
        # contaminated row is excluded from the merge, not just from deletion.
        assert BOB_FACT not in str(db.rows[_user_key("acme", "company", ALICE)].get("content"))

    def test_contaminated_legacy_row_is_invisible_to_the_owners_reads(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # Until the migration runs, a collided row (column owner Alice, content
        # recorded for Bob) sits in Alice's column-filtered result sets. Every
        # read surface must refuse to render it - this is the leak the PR
        # exists to close, and it must be closed for pre-fix rows too.
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

        assert store.get(entity_id="acme", entity_type="company", user_id=ALICE) is None
        assert store.list_entities(user_id=ALICE) == []
        assert store.search(query="acme", user_id=ALICE) == []
        context = store.build_context(store.recall(message="what do we know about Acme?", user_id=ALICE))
        assert BOB_FACT not in str(context)
        # The row itself is untouched: it is the migration's evidence.
        assert legacy_id in db.rows

    def test_pre_fix_unknown_placeholder_is_retired_on_type_upgrade(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # link_entities on any pre-fix release minted placeholder rows keyed
        # entity_user_unknown_<id>. When a later write supplies the real type,
        # the placeholder must be retired like any other legacy row - not left
        # to double the directory and make the name ambiguous forever.
        placeholder_id = legacy_entity_learning_id("radar", "unknown", "user")
        db.upsert_learning(
            id=placeholder_id,
            learning_type="entity_memory",
            entity_id="radar",
            entity_type="unknown",
            namespace="user",
            user_id=ALICE,
            content={
                "entity_id": "radar",
                "entity_type": "unknown",
                "name": "Radar",
                "facts": [{"id": "f1", "content": "queue prototype"}],
                "namespace": "user",
                "user_id": ALICE,
            },
        )

        store.remember_about(entity="Radar", entity_type="project", facts=["ships weekly"], user_id=ALICE)

        assert placeholder_id not in db.rows
        entities = store.list_entities(user_id=ALICE)
        assert [(e.entity_type, e.entity_id) for e in entities] == [("project", "radar")]
        content = str(db.rows[_user_key("radar", "project", ALICE)].get("content"))
        assert "queue prototype" in content
        assert "ships weekly" in content
        assert "matches more than one entity" not in store.forget(entity="Radar", user_id=ALICE)

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


class TestUnkeyableRowPairReadsAsAbsent:
    """The pair read runs before get()'s own error handling, and the combine
    builds identity sets from content-supplied values. Content arrives as
    arbitrary JSON over the REST create route, so a value that cannot be
    hashed must read as absent instead of raising out of the read surface."""

    def _seed_pair(self, db: RecordingLearningDb, legacy_fact: Dict[str, Any]) -> Tuple[str, str]:
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
                "facts": [legacy_fact],
                "namespace": "user",
                "user_id": ALICE,
            },
        )
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
                "facts": [{"id": "f1", "content": ALICE_FACT}],
                "namespace": "user",
                "user_id": ALICE,
            },
        )
        return legacy_id, new_id

    def test_get_returns_none_for_a_fact_whose_identity_is_unhashable(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # A null id falls back to content for identity, and a list content is
        # unhashable: keying it raises out of the merge.
        self._seed_pair(db, {"id": None, "content": ["a", "b"]})

        assert store.get(entity_id="acme", entity_type="company", user_id=ALICE) is None

    async def test_aget_returns_none_for_a_fact_whose_identity_is_unhashable(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        self._seed_pair(db, {"id": None, "content": ["a", "b"]})

        assert await store.aget(entity_id="acme", entity_type="company", user_id=ALICE) is None

    def test_ordinary_facts_still_merge_across_the_row_pair(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        self._seed_pair(db, {"id": "f0", "content": "legacy fact"})

        entity = store.get(entity_id="acme", entity_type="company", user_id=ALICE)

        assert entity is not None
        assert [f["content"] for f in entity.facts] == [ALICE_FACT, "legacy fact"]

    async def test_ordinary_facts_still_merge_across_the_row_pair_async(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        self._seed_pair(db, {"id": "f0", "content": "legacy fact"})

        entity = await store.aget(entity_id="acme", entity_type="company", user_id=ALICE)

        assert entity is not None
        assert [f["content"] for f in entity.facts] == [ALICE_FACT, "legacy fact"]


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


class TestLegacyRetirementRequiresTheSavedContent:
    """A legacy row is retired only once the row replacing it carries this
    write's content. A legacy row and a user-scoped row coexist whenever a
    re-key hit a conflict or a deploy is mid-roll, so a row already sits at the
    replacing id and its presence alone says nothing about this write - and a
    hard delete of the legacy row then destroys the only copy of the merge."""

    def _seed_pair(self, db: RecordingLearningDb) -> Tuple[str, str]:
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        new_id = _user_key("acme", "company", ALICE)
        for row_id, fact_id, fact in ((legacy_id, "l1", LEGACY_FACT), (new_id, "n1", CURRENT_FACT)):
            db.upsert_learning(
                id=row_id,
                learning_type="entity_memory",
                entity_id="acme",
                entity_type="company",
                namespace="user",
                user_id=ALICE,
                content={
                    "entity_id": "acme",
                    "entity_type": "company",
                    "name": "Acme",
                    "facts": [{"id": fact_id, "content": fact}],
                    "namespace": "user",
                    "user_id": ALICE,
                },
            )
        return legacy_id, new_id

    def test_silently_failed_save_keeps_the_legacy_row_next_to_the_older_replacement(self) -> None:
        db = _SilentUpsertDb()
        legacy_id, new_id = self._seed_pair(db)
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))  # type: ignore[arg-type]
        db.writes_land = False

        store.remember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert legacy_id in db.rows
        assert LEGACY_FACT in str(db.rows[legacy_id].get("content"))
        assert LEGACY_FACT not in str(db.rows[new_id].get("content"))

        db.writes_land = True
        store.remember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        entity = store.get(entity_id="acme", entity_type="company", user_id=ALICE)
        assert entity is not None
        facts = [f["content"] for f in entity.facts]
        assert LEGACY_FACT in facts
        assert CURRENT_FACT in facts

    async def test_async_silently_failed_save_keeps_the_legacy_row_next_to_the_older_replacement(self) -> None:
        inner = _SilentUpsertDb()
        legacy_id, new_id = self._seed_pair(inner)
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=_async_facade(inner)))
        inner.writes_land = False

        await store.aremember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert legacy_id in inner.rows
        assert LEGACY_FACT in str(inner.rows[legacy_id].get("content"))
        assert LEGACY_FACT not in str(inner.rows[new_id].get("content"))

        inner.writes_land = True
        await store.aremember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        entity = await store.aget(entity_id="acme", entity_type="company", user_id=ALICE)
        assert entity is not None
        facts = [f["content"] for f in entity.facts]
        assert LEGACY_FACT in facts
        assert CURRENT_FACT in facts

    def test_landed_save_retires_the_legacy_row(self) -> None:
        db = _SilentUpsertDb()
        legacy_id, new_id = self._seed_pair(db)
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))  # type: ignore[arg-type]

        store.remember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert legacy_id not in db.rows
        content = str(db.rows[new_id].get("content"))
        assert LEGACY_FACT in content
        assert CURRENT_FACT in content
        assert "today's note" in content

    async def test_async_landed_save_retires_the_legacy_row(self) -> None:
        inner = _SilentUpsertDb()
        legacy_id, new_id = self._seed_pair(inner)
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=_async_facade(inner)))

        await store.aremember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert legacy_id not in inner.rows
        content = str(inner.rows[new_id].get("content"))
        assert LEGACY_FACT in content
        assert CURRENT_FACT in content
        assert "today's note" in content


class TestAsyncGetMatchesSyncGet:
    """aget resolves a "user"-namespace entity through the same deterministic
    pair read and contamination gate as get: it never serves a row get refuses,
    never depends on which row an unordered column read reaches first, and never
    feeds a half of the pair into a save that would overwrite the other half."""

    def _seed_legacy_row(self, db: RecordingLearningDb, owner: str, content_user: str, fact: str) -> str:
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
                "user_id": content_user,
            },
        )
        return legacy_id

    def _seed_user_row(self, db: RecordingLearningDb, owner: str, fact: str) -> str:
        row_id = _user_key("acme", "company", owner)
        db.upsert_learning(
            id=row_id,
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="user",
            user_id=owner,
            content={
                "entity_id": "acme",
                "entity_type": "company",
                "name": "Acme",
                "facts": [{"id": "n1", "content": fact}],
                "namespace": "user",
                "user_id": owner,
            },
        )
        return row_id

    async def test_contaminated_legacy_row_is_refused_by_aget(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # Column owner Alice, content recorded for Bob: the row provably holds
        # another user's data and sits in Alice's column-filtered result set
        # until the migration runs.
        legacy_id = self._seed_legacy_row(db, ALICE, BOB, BOB_FACT)

        assert await store.aget(entity_id="acme", entity_type="company", user_id=ALICE) is None
        assert store.get(entity_id="acme", entity_type="company", user_id=ALICE) is None
        # The row itself is the migration's evidence, so the read leaves it.
        assert legacy_id in db.rows

    async def test_contaminated_legacy_row_is_refused_by_aget_on_an_async_backend(
        self, db: RecordingLearningDb
    ) -> None:
        from agno.db.base import AsyncBaseDb

        inner = db

        class FakeAsyncDb(AsyncBaseDb):
            def __init__(self) -> None:
                pass

            async def get_learning(self, **kwargs: Any) -> Any:
                return inner.get_learning(**kwargs)

            async def get_learnings(self, **kwargs: Any) -> Any:
                return inner.get_learnings(**kwargs)

            async def upsert_learning(self, **kwargs: Any) -> None:
                inner.upsert_learning(**kwargs)

            async def get_learning_by_id(self, id: str) -> Any:
                return inner.get_learning_by_id(id)

            async def delete_learning(self, id: str) -> bool:
                return inner.delete_learning(id)

        FakeAsyncDb.__abstractmethods__ = frozenset()  # type: ignore[attr-defined]
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=FakeAsyncDb()))
        self._seed_legacy_row(db, ALICE, BOB, BOB_FACT)

        assert await store.aget(entity_id="acme", entity_type="company", user_id=ALICE) is None

    @pytest.mark.parametrize("legacy_first", [True, False])
    async def test_aget_merges_the_coexisting_pair_in_either_insertion_order(
        self, store: EntityMemoryStore, db: RecordingLearningDb, legacy_first: bool
    ) -> None:
        # A legacy row and a user-scoped row coexist (a migration conflict, or
        # a rolling deploy). Both orders are seeded because the column-filtered
        # single-row read resolves by insertion, so an order-dependent aget
        # returns a different half of the pair for each.
        if legacy_first:
            self._seed_legacy_row(db, ALICE, ALICE, "legacy fact worth money")
            self._seed_user_row(db, ALICE, "post-upgrade fact worth money")
        else:
            self._seed_user_row(db, ALICE, "post-upgrade fact worth money")
            self._seed_legacy_row(db, ALICE, ALICE, "legacy fact worth money")

        entity = await store.aget(entity_id="acme", entity_type="company", user_id=ALICE)
        sync_entity = store.get(entity_id="acme", entity_type="company", user_id=ALICE)

        assert entity is not None and sync_entity is not None
        facts = sorted(f["content"] for f in entity.facts)
        assert facts == ["legacy fact worth money", "post-upgrade fact worth money"]
        assert facts == sorted(f["content"] for f in sync_entity.facts)

    async def test_a_save_after_aget_keeps_both_halves_of_the_pair(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # Read-modify-write over a coexisting pair: the saved row replaces the
        # user-scoped row and retires the legacy one, so a read that carried
        # only one half destroys the other half permanently.
        legacy_id = self._seed_legacy_row(db, ALICE, ALICE, "legacy fact worth money")
        row_id = self._seed_user_row(db, ALICE, "post-upgrade fact worth money")

        entity = await store.aget(entity_id="acme", entity_type="company", user_id=ALICE)
        assert entity is not None
        entity.facts.append({"id": "f9", "content": "today's note"})
        assert await store._asave_entity(entity=entity, user_id=ALICE) is True

        content = str(db.rows[row_id].get("content"))
        assert "legacy fact worth money" in content
        assert "post-upgrade fact worth money" in content
        assert "today's note" in content
        assert legacy_id not in db.rows

    async def test_healthy_user_scoped_row_reads_back_through_aget(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        await store.aremember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)

        entity = await store.aget(entity_id="acme", entity_type="company", user_id=ALICE)
        sync_entity = store.get(entity_id="acme", entity_type="company", user_id=ALICE)

        assert entity is not None and sync_entity is not None
        assert entity.name == "Acme"
        assert [f["content"] for f in entity.facts] == [ALICE_FACT]
        assert [f["content"] for f in sync_entity.facts] == [ALICE_FACT]
        assert await store.aget(entity_id="nowhere", entity_type="company", user_id=ALICE) is None


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


class TestErasureRefusesTheAbsentCache:
    """A delete always re-probes the pre-user-scoped-key id for the entity.

    The absent set is a process-local negative cache with no invalidation: once
    a store instance has read the legacy id and found nothing, it skips that
    probe for the rest of its life. Another process on an older build can write
    a legacy-keyed row after that, so an erasure that trusted the cache would
    report success while the row survived and the next process served the
    entity back.
    """

    def _seed_legacy_row(self, db: RecordingLearningDb, fact: str) -> str:
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
                "facts": [{"id": "f1", "content": fact}],
                "namespace": "user",
                "user_id": ALICE,
            },
        )
        return legacy_id

    def test_delete_removes_a_legacy_row_written_after_the_probe(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        assert legacy_id in store._legacy_absent
        self._seed_legacy_row(db, ALICE_FACT)

        assert store.delete(entity_id="acme", entity_type="company", user_id=ALICE) is True

        assert legacy_id not in db.rows
        assert db.rows == {}
        fresh = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))  # type: ignore[arg-type]
        assert fresh.get(entity_id="acme", entity_type="company", user_id=ALICE) is None

    async def test_adelete_removes_a_legacy_row_written_after_the_probe(self, db: RecordingLearningDb) -> None:
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=_AsyncLearningDb(db)))
        await store.aremember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        assert legacy_id in store._legacy_absent
        self._seed_legacy_row(db, ALICE_FACT)

        assert await store.adelete(entity_id="acme", entity_type="company", user_id=ALICE) is True

        assert legacy_id not in db.rows
        assert db.rows == {}
        fresh = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=_AsyncLearningDb(db)))
        assert await fresh.aget(entity_id="acme", entity_type="company", user_id=ALICE) is None

    def test_save_keeps_skipping_the_probe_for_a_cached_absent_id(self) -> None:
        # The cache still does its job on the save path: a second write for an
        # entity with no legacy row reads only the user-scoped id.
        db = _ProbeCountingDb()
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))  # type: ignore[arg-type]
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)
        assert legacy_id in store._legacy_absent
        db.by_id_reads.clear()

        store.remember_about(entity="Acme", entity_type="company", facts=["second note"], user_id=ALICE)

        assert db.by_id_reads.count(legacy_id) == 0
        content = str(db.rows[_user_key("acme", "company", ALICE)].get("content"))
        assert ALICE_FACT in content
        assert "second note" in content

    def test_delete_without_a_legacy_row_still_reports_success(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)

        assert store.delete(entity_id="acme", entity_type="company", user_id=ALICE) is True
        assert db.rows == {}

    async def test_adelete_without_a_legacy_row_still_reports_success(self, db: RecordingLearningDb) -> None:
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=_AsyncLearningDb(db)))
        await store.aremember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=ALICE)

        assert await store.adelete(entity_id="acme", entity_type="company", user_id=ALICE) is True
        assert db.rows == {}


class TestFarEndWritesRetireTheLegacyRow:
    """A write that edits the far end of an edge reads that far end on the write
    path, so the same save retires its pre-user-scoped-key row. A far row left
    in place re-injects the edge into every later read of the far entity."""

    def _seed_legacy(
        self,
        db: RecordingLearningDb,
        entity_id: str,
        name: str,
        entity_type: str,
        relationships: List[Dict[str, Any]],
    ) -> str:
        """Write one pre-user-scoped-key row for ALICE and return its id.

        Content is JSON text, the way the adapters store it: a dict handed to
        the fake is the same object the store parses back, so an in-place edit
        to a relationship would reach the stored row.
        """
        legacy_id = legacy_entity_learning_id(entity_id, entity_type, "user")
        db.upsert_learning(
            id=legacy_id,
            learning_type="entity_memory",
            entity_id=entity_id,
            entity_type=entity_type,
            namespace="user",
            user_id=ALICE,
            content=json.dumps(
                {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "name": name,
                    "relationships": relationships,
                    "namespace": "user",
                    "user_id": ALICE,
                }
            ),
        )
        return legacy_id

    def _seed_partners(self, db: RecordingLearningDb) -> Tuple[str, str]:
        """Acme and Globex, linked both ways, both on the pre-fix key."""
        acme = self._seed_legacy(
            db,
            "acme",
            "Acme",
            "company",
            [{"entity_id": "globex", "entity_type": "company", "relation": "partner_of", "direction": "outgoing"}],
        )
        globex = self._seed_legacy(
            db,
            "globex",
            "Globex",
            "company",
            [{"entity_id": "acme", "entity_type": "company", "relation": "partner_of", "direction": "incoming"}],
        )
        return acme, globex

    def _seed_unknown_pair(self, db: RecordingLearningDb) -> Tuple[str, str]:
        """Radar and Postgres as pre-fix link_entities left them: both typed
        "unknown", linked both ways, both on the pre-fix key."""
        radar = self._seed_legacy(
            db,
            "radar",
            "Radar",
            "unknown",
            [{"entity_id": "postgres", "entity_type": "unknown", "relation": "runs_on", "direction": "outgoing"}],
        )
        postgres = self._seed_legacy(
            db,
            "postgres",
            "Postgres",
            "unknown",
            [{"entity_id": "radar", "entity_type": "unknown", "relation": "runs_on", "direction": "incoming"}],
        )
        return radar, postgres

    @staticmethod
    def _fresh(db: RecordingLearningDb) -> EntityMemoryStore:
        """A store with empty in-process caches, so reads come off the db."""
        return EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))  # type: ignore[arg-type]

    def test_forget_retires_the_far_ends_legacy_row(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        _, globex_legacy = self._seed_partners(db)

        message = store.forget(entity="Acme", fact="partner_of Globex", user_id=ALICE)

        assert "Removed relationship" in message
        assert globex_legacy not in db.rows
        assert _user_key("globex", "company", ALICE) in db.rows

    def test_detached_far_end_reads_empty_from_a_new_store(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        self._seed_partners(db)

        store.forget(entity="Acme", fact="partner_of Globex", user_id=ALICE)

        globex = self._fresh(db).get(entity_id="globex", entity_type="company", user_id=ALICE)
        assert globex is not None
        assert globex.relationships == []

    async def test_async_forget_detaches_the_far_end_durably(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        _, globex_legacy = self._seed_partners(db)

        message = await store.aforget(entity="Acme", fact="partner_of Globex", user_id=ALICE)

        assert "Removed relationship" in message
        assert globex_legacy not in db.rows
        globex = await self._fresh(db).aget(entity_id="globex", entity_type="company", user_id=ALICE)
        assert globex is not None
        assert globex.relationships == []

    def test_type_promotion_leaves_the_far_end_one_edge(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        _, postgres_legacy = self._seed_unknown_pair(db)

        store.remember_about(entity="Radar", entity_type="project", facts=["ships weekly"], user_id=ALICE)

        assert postgres_legacy not in db.rows
        postgres = self._fresh(db).get(entity_id="postgres", entity_type="unknown", user_id=ALICE)
        assert postgres is not None
        assert [(r.get("entity_id"), r.get("entity_type")) for r in postgres.relationships] == [("radar", "project")]

    async def test_async_type_promotion_leaves_the_far_end_one_edge(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        _, postgres_legacy = self._seed_unknown_pair(db)

        await store.aremember_about(entity="Radar", entity_type="project", facts=["ships weekly"], user_id=ALICE)

        assert postgres_legacy not in db.rows
        postgres = await self._fresh(db).aget(entity_id="postgres", entity_type="unknown", user_id=ALICE)
        assert postgres is not None
        assert [(r.get("entity_id"), r.get("entity_type")) for r in postgres.relationships] == [("radar", "project")]

    def test_far_end_with_no_legacy_row_still_detaches(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.link_entities(entity="Radar", relation="runs_on", related_entity="Postgres", user_id=ALICE)

        message = store.forget(entity="Radar", fact="runs_on -> Postgres", user_id=ALICE)

        assert "Removed relationship" in message
        postgres = self._fresh(db).get(entity_id="postgres", entity_type="unknown", user_id=ALICE)
        assert postgres is not None
        assert postgres.relationships == []

    def test_far_ends_other_relationships_survive(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        self._seed_legacy(
            db,
            "acme",
            "Acme",
            "company",
            [{"entity_id": "globex", "entity_type": "company", "relation": "partner_of", "direction": "outgoing"}],
        )
        self._seed_legacy(
            db,
            "globex",
            "Globex",
            "company",
            [
                {"entity_id": "acme", "entity_type": "company", "relation": "partner_of", "direction": "incoming"},
                {"entity_id": "initech", "entity_type": "company", "relation": "vendor_of", "direction": "outgoing"},
            ],
        )

        store.forget(entity="Acme", fact="partner_of Globex", user_id=ALICE)

        globex = self._fresh(db).get(entity_id="globex", entity_type="company", user_id=ALICE)
        assert globex is not None
        assert [(r.get("relation"), r.get("entity_id")) for r in globex.relationships] == [("vendor_of", "initech")]


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

    def test_integer_user_absorbs_its_own_legacy_row(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        legacy_id = self._legacy_row(db, self.INT_USER, "legacy fact")

        store.remember_about(entity="Acme", entity_type="company", facts=[ALICE_FACT], user_id=self.INT_USER)

        entity = store.get(entity_id="acme", entity_type="company", user_id=self.INT_USER)
        assert entity is not None
        assert sorted(f["content"] for f in entity.facts) == sorted([ALICE_FACT, "legacy fact"])
        assert legacy_id not in db.rows

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


class TestSnapshotRetirementKeepsUncarriedFields:
    """The merge snapshot proves this write consumed the legacy row's
    collections; it establishes nothing about the scalars. _merge_legacy_into
    hands the user-scoped side the description and every conflicting properties
    key, so a legacy description or note pointer that lost such a conflict has
    no copy anywhere else and the row holding it must survive the write.

    A real SqliteDb backs these: content round-trips through JSON, so the store
    cannot reach a stored row by reference and a snapshot comparison cannot
    collapse into an identity compare.
    """

    LEGACY_FACTS = [{"id": "L1", "content": LEGACY_FACT}]
    CURRENT_FACTS = [{"id": "n1", "content": CURRENT_FACT}]

    def test_conflicting_description_and_note_outlive_the_write(self, tmp_path: Path) -> None:
        db = SqliteDb(db_file=str(tmp_path / "conflict.db"))
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        db.upsert_learning(**_acme_row(legacy_id, self.LEGACY_FACTS, LEGACY_DESCRIPTION, LEGACY_NOTE))
        db.upsert_learning(
            **_acme_row(_user_key("acme", "company", ALICE), self.CURRENT_FACTS, CURRENT_DESCRIPTION, CURRENT_NOTE)
        )
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))

        store.remember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert db.get_learning_by_id(legacy_id) is not None
        stored = _stored_content(db.list_learnings(learning_type="entity_memory")[0])
        assert LEGACY_DESCRIPTION in stored
        assert LEGACY_NOTE in stored
        assert CURRENT_DESCRIPTION in stored
        assert CURRENT_NOTE in stored
        assert LEGACY_FACT in stored
        assert CURRENT_FACT in stored

    async def test_conflicting_description_and_note_outlive_the_async_write(self, tmp_path: Path) -> None:
        db = AsyncSqliteDb(db_file=str(tmp_path / "conflict_async.db"))
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        await db.upsert_learning(**_acme_row(legacy_id, self.LEGACY_FACTS, LEGACY_DESCRIPTION, LEGACY_NOTE))
        await db.upsert_learning(
            **_acme_row(_user_key("acme", "company", ALICE), self.CURRENT_FACTS, CURRENT_DESCRIPTION, CURRENT_NOTE)
        )
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))

        await store.aremember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert await db.get_learning_by_id(legacy_id) is not None
        rows, _ = await db.list_learnings(learning_type="entity_memory")
        stored = _stored_content(rows)
        assert LEGACY_DESCRIPTION in stored
        assert LEGACY_NOTE in stored
        assert CURRENT_DESCRIPTION in stored
        assert CURRENT_NOTE in stored
        assert LEGACY_FACT in stored
        assert CURRENT_FACT in stored

    def test_a_conflicting_description_outlives_the_write_when_the_notes_agree(self, tmp_path: Path) -> None:
        # The description is the half the merge only ever uses to fill a gap,
        # so a user-scoped row that already has one keeps its own.
        db = SqliteDb(db_file=str(tmp_path / "description.db"))
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        db.upsert_learning(**_acme_row(legacy_id, self.LEGACY_FACTS, LEGACY_DESCRIPTION, LEGACY_NOTE))
        db.upsert_learning(
            **_acme_row(_user_key("acme", "company", ALICE), self.CURRENT_FACTS, CURRENT_DESCRIPTION, LEGACY_NOTE)
        )
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))

        store.remember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert db.get_learning_by_id(legacy_id) is not None
        stored = _stored_content(db.list_learnings(learning_type="entity_memory")[0])
        assert LEGACY_DESCRIPTION in stored
        assert CURRENT_DESCRIPTION in stored

    def test_a_conflicting_note_outlives_the_write_when_the_descriptions_agree(self, tmp_path: Path) -> None:
        # The properties map is the half that carries the note pointer, and it
        # loses every key conflict independently of the description.
        db = SqliteDb(db_file=str(tmp_path / "note.db"))
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        db.upsert_learning(**_acme_row(legacy_id, self.LEGACY_FACTS, LEGACY_DESCRIPTION, LEGACY_NOTE))
        db.upsert_learning(
            **_acme_row(_user_key("acme", "company", ALICE), self.CURRENT_FACTS, LEGACY_DESCRIPTION, CURRENT_NOTE)
        )
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))

        store.remember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert db.get_learning_by_id(legacy_id) is not None
        stored = _stored_content(db.list_learnings(learning_type="entity_memory")[0])
        assert LEGACY_NOTE in stored
        assert CURRENT_NOTE in stored

    def test_forget_still_retires_the_legacy_row(self, tmp_path: Path) -> None:
        # A forget empties a collection on purpose, so subsumption fails and
        # only the snapshot can authorise the retire. A legacy row left behind
        # keeps rendering the forgotten event and the next write resurrects it.
        db = SqliteDb(db_file=str(tmp_path / "forget.db"))
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        db.upsert_learning(
            **_acme_row(
                legacy_id,
                self.LEGACY_FACTS,
                LEGACY_DESCRIPTION,
                LEGACY_NOTE,
                events=[{"content": PILOT_EVENT, "date": "2026-05-01"}],
            )
        )
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))

        result = store.forget(entity="Acme", fact=PILOT_EVENT, user_id=ALICE)

        assert PILOT_EVENT in result
        assert db.get_learning_by_id(legacy_id) is None
        stored = _stored_content(db.list_learnings(learning_type="entity_memory")[0])
        assert PILOT_EVENT not in stored
        assert LEGACY_DESCRIPTION in stored
        assert LEGACY_NOTE in stored
        assert LEGACY_FACT in stored

    async def test_aforget_still_retires_the_legacy_row(self, tmp_path: Path) -> None:
        db = AsyncSqliteDb(db_file=str(tmp_path / "forget_async.db"))
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        await db.upsert_learning(
            **_acme_row(
                legacy_id,
                self.LEGACY_FACTS,
                LEGACY_DESCRIPTION,
                LEGACY_NOTE,
                events=[{"content": PILOT_EVENT, "date": "2026-05-01"}],
            )
        )
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))

        result = await store.aforget(entity="Acme", fact=PILOT_EVENT, user_id=ALICE)

        assert PILOT_EVENT in result
        assert await db.get_learning_by_id(legacy_id) is None
        rows, _ = await db.list_learnings(learning_type="entity_memory")
        stored = _stored_content(rows)
        assert PILOT_EVENT not in stored
        assert LEGACY_DESCRIPTION in stored
        assert LEGACY_NOTE in stored
        assert LEGACY_FACT in stored

    def test_self_heal_retires_the_legacy_row_when_every_field_is_carried(self, tmp_path: Path) -> None:
        # The user-scoped row holds no description and no note, so the merge
        # takes the legacy row's: nothing is left behind and the row retires.
        db = SqliteDb(db_file=str(tmp_path / "selfheal.db"))
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        new_id = _user_key("acme", "company", ALICE)
        db.upsert_learning(**_acme_row(legacy_id, self.LEGACY_FACTS, LEGACY_DESCRIPTION, LEGACY_NOTE))
        db.upsert_learning(**_acme_row(new_id, self.CURRENT_FACTS))
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))

        store.remember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert db.get_learning_by_id(legacy_id) is None
        row = db.get_learning_by_id(new_id)
        assert row is not None
        content = json.loads(row["content"]) if isinstance(row["content"], str) else row["content"]
        assert content["description"] == LEGACY_DESCRIPTION
        assert content["properties"]["note"] == LEGACY_NOTE
        assert sorted(f["content"] for f in content["facts"]) == sorted([LEGACY_FACT, CURRENT_FACT, "today's note"])

    async def test_async_self_heal_retires_the_legacy_row_when_every_field_is_carried(self, tmp_path: Path) -> None:
        db = AsyncSqliteDb(db_file=str(tmp_path / "selfheal_async.db"))
        legacy_id = legacy_entity_learning_id("acme", "company", "user")
        new_id = _user_key("acme", "company", ALICE)
        await db.upsert_learning(**_acme_row(legacy_id, self.LEGACY_FACTS, LEGACY_DESCRIPTION, LEGACY_NOTE))
        await db.upsert_learning(**_acme_row(new_id, self.CURRENT_FACTS))
        store = EntityMemoryStore(config=EntityMemoryConfig(namespace="user", db=db))

        await store.aremember_about(entity="Acme", entity_type="company", facts=["today's note"], user_id=ALICE)

        assert await db.get_learning_by_id(legacy_id) is None
        row = await db.get_learning_by_id(new_id)
        assert row is not None
        content = json.loads(row["content"]) if isinstance(row["content"], str) else row["content"]
        assert content["description"] == LEGACY_DESCRIPTION
        assert content["properties"]["note"] == LEGACY_NOTE
        assert sorted(f["content"] for f in content["facts"]) == sorted([LEGACY_FACT, CURRENT_FACT, "today's note"])


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
