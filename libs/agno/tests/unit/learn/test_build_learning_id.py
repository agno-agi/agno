"""Tests for build_learning_id, the single source of truth for learning record PKs.

The learning stores delegate their `_build_*_id` helpers here, so the REST create endpoint
can compute the same deterministic id and records reconcile with what the agent reads/writes.
"""

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
            build_learning_id("entity_memory", entity_id="acme", entity_type="company", namespace="user")
            == "entity_user_company_acme"
        )

    def test_missing_identity_fields_returns_none(self):
        assert build_learning_id("user_profile") is None
        assert build_learning_id("user_memory") is None
        assert build_learning_id("session_context") is None
        assert build_learning_id("entity_memory", entity_id="acme") is None  # needs entity_type too

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
