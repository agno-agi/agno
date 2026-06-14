"""Tests for build_learning_id, the single source of truth for learning record PKs.

The learning stores delegate their `_build_*_id` helpers here, so the REST create endpoint
can compute the same deterministic id and records reconcile with what the agent reads/writes.
"""

import asyncio
from unittest.mock import MagicMock

from agno.learn.config import EntityMemoryConfig
from agno.learn.stores.entity_memory import EntityMemoryStore
from agno.learn.stores.session_context import SessionContextStore
from agno.learn.stores.user_memory import UserMemoryStore
from agno.learn.stores.user_profile import UserProfileStore
from agno.learn.utils import IDENTITY_KEYED_LEARNING_TYPES, build_learning_id


class TestBuildLearningId:
    def test_identity_keyed_types(self):
        assert build_learning_id("user_profile", user_id="u1") == "user_profile_u1"
        assert build_learning_id("user_memory", user_id="u1") == "memories_u1"
        assert build_learning_id("session_context", session_id="s1") == "session_context_s1"
        assert (
            build_learning_id("entity_memory", entity_id="acme", entity_type="company") == "entity_global_company_acme"
        )
        assert (
            build_learning_id("entity_memory", entity_id="acme", entity_type="company", namespace="user", user_id="u1")
            == "entity_user_u1_company_acme"
        )

    def test_missing_identity_fields_returns_none(self):
        assert build_learning_id("user_profile") is None
        assert build_learning_id("user_memory") is None
        assert build_learning_id("session_context") is None
        assert build_learning_id("entity_memory", entity_id="acme") is None  # needs entity_type too
        assert build_learning_id("entity_memory", entity_id="acme", entity_type="company", namespace="user") is None

    def test_non_identity_types_return_none(self):
        assert build_learning_id("decision_log", user_id="u1") is None
        assert build_learning_id("something_custom", user_id="u1") is None

    def test_identity_keyed_set_matches_helper(self):
        # Every type in the set must be derivable when its fields are present, and the
        # decision_log (generated-id) type must not be in the set.
        assert IDENTITY_KEYED_LEARNING_TYPES == {
            "user_profile",
            "user_memory",
            "session_context",
            "entity_memory",
        }
        assert "decision_log" not in IDENTITY_KEYED_LEARNING_TYPES


class TestStoresDelegateToHelper:
    """The stores' private id builders must produce exactly what build_learning_id returns,
    so a REST create lands on the same row the agent uses."""

    def test_user_profile_store(self):
        store = UserProfileStore.__new__(UserProfileStore)
        assert store._build_profile_id("u1") == build_learning_id("user_profile", user_id="u1")

    def test_user_memory_store(self):
        store = UserMemoryStore.__new__(UserMemoryStore)
        assert store._build_memories_id("u1") == build_learning_id("user_memory", user_id="u1")

    def test_session_context_store(self):
        store = SessionContextStore.__new__(SessionContextStore)
        assert store._build_context_id("s1") == build_learning_id("session_context", session_id="s1")

    def test_entity_memory_store(self):
        store = EntityMemoryStore.__new__(EntityMemoryStore)
        assert store._build_entity_db_id("acme", "company", "global") == build_learning_id(
            "entity_memory", entity_id="acme", entity_type="company", namespace="global"
        )
        assert store._build_entity_db_id("acme", "company", "user", user_id="u1") == build_learning_id(
            "entity_memory", entity_id="acme", entity_type="company", namespace="user", user_id="u1"
        )


class TestEntityMemoryTenantScopedIds:
    def test_user_namespace_includes_user_id_in_entity_learning_id(self):
        db = MagicMock()
        db.get_learning_by_id.return_value = None
        db.get_learning.return_value = None
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, namespace="user"))

        assert store.create_entity(entity_id="john_smith", entity_type="person", name="John Smith", user_id="user-a")
        assert store.create_entity(entity_id="john_smith", entity_type="person", name="John Smith", user_id="user-b")

        upsert_ids = [call.kwargs["id"] for call in db.upsert_learning.call_args_list]
        assert upsert_ids == ["entity_user_user-a_person_john_smith", "entity_user_user-b_person_john_smith"]
        assert len(set(upsert_ids)) == 2

    def test_user_namespace_get_requires_user_id(self):
        db = MagicMock()
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, namespace="user"))

        assert store.get(entity_id="john_smith", entity_type="person") is None
        db.get_learning_by_id.assert_not_called()
        db.get_learning.assert_not_called()

    def test_user_namespace_search_requires_user_id(self):
        db = MagicMock()
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, namespace="user"))

        assert store.search(query="john") == []
        db.get_learnings.assert_not_called()

    def test_user_namespace_async_get_and_search_require_user_id(self):
        db = MagicMock()
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, namespace="user"))

        assert asyncio.run(store.aget(entity_id="john_smith", entity_type="person")) is None
        assert asyncio.run(store.asearch(query="john")) == []
        db.get_learning_by_id.assert_not_called()
        db.get_learning.assert_not_called()
        db.get_learnings.assert_not_called()

    def test_user_namespace_get_prefers_scoped_id_over_legacy_filtered_lookup(self):
        db = MagicMock()
        scoped_entity = EntityMemoryStore().schema(
            entity_id="john_smith", entity_type="person", name="Scoped John", user_id="user-a", namespace="user"
        )
        db.get_learning_by_id.return_value = {"content": scoped_entity.to_dict()}
        db.get_learning.return_value = {
            "content": {"entity_id": "john_smith", "entity_type": "person", "name": "Legacy John"}
        }
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, namespace="user"))

        entity = store.get(entity_id="john_smith", entity_type="person", user_id="user-a")

        assert entity is not None
        assert entity.name == "Scoped John"
        db.get_learning_by_id.assert_called_once_with("entity_user_user-a_person_john_smith")
        db.get_learning.assert_not_called()

    def test_user_namespace_mutation_without_user_id_does_not_read_or_write(self):
        db = MagicMock()
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, namespace="user"))

        assert not store.update_entity(entity_id="john_smith", entity_type="person", name="John Smith")
        db.get_learning_by_id.assert_not_called()
        db.get_learning.assert_not_called()
        db.upsert_learning.assert_not_called()

    def test_saving_user_namespace_entity_does_not_delete_potentially_foreign_legacy_id(self):
        db = MagicMock()
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, namespace="user"))
        entity = store.schema(entity_id="john_smith", entity_type="person", name="John Smith", user_id="user-a")

        assert store._save_entity(entity=entity, user_id="user-a", namespace="user")

        assert db.upsert_learning.call_args.kwargs["id"] == "entity_user_user-a_person_john_smith"
        db.delete_learning.assert_not_called()
