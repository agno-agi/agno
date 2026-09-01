"""Integration tests for ValkeyDb learning methods against a real Valkey server.

Requires a running Valkey instance on localhost:6379.
Run with: pytest libs/agno/tests/integration/db/valkey/test_learnings.py -v
"""

import time

from agno.db.valkey.valkey import ValkeyDb


def _seed(valkey_db: ValkeyDb) -> None:
    valkey_db.upsert_learning(
        id="l1",
        learning_type="user_profile",
        content={"summary": "prefers python"},
        user_id="alice",
        namespace="user",
    )
    valkey_db.upsert_learning(
        id="l2",
        learning_type="user_profile",
        content={"summary": "prefers rust"},
        user_id="bob",
        namespace="user",
    )
    valkey_db.upsert_learning(
        id="l3",
        learning_type="session_context",
        content={"topic": "billing"},
        user_id="alice",
        session_id="s1",
    )
    valkey_db.upsert_learning(
        id="l4",
        learning_type="entity_memory",
        content={"facts": ["acme is a customer"]},
        entity_id="acme",
        entity_type="company",
        namespace="global",
    )


class TestUpsertAndGet:
    def test_get_learning_filters_to_single_record(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        result = valkey_db.get_learning(learning_type="user_profile", user_id="alice")
        assert result == {"content": {"summary": "prefers python"}}

    def test_get_learning_returns_none_when_no_match(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        assert valkey_db.get_learning(learning_type="user_profile", user_id="carol") is None

    def test_get_learning_entity_filters(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        result = valkey_db.get_learning(learning_type="entity_memory", entity_id="acme", entity_type="company")
        assert result == {"content": {"facts": ["acme is a customer"]}}

    def test_upsert_updates_content_and_preserves_identity(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        original = valkey_db.get_learning_by_id("l1")
        assert original is not None

        valkey_db.upsert_learning(
            id="l1",
            learning_type="user_profile",
            content={"summary": "prefers go"},
            user_id="someone-else",
            metadata={"source": "test"},
        )
        updated = valkey_db.get_learning_by_id("l1")
        assert updated is not None
        assert updated["content"] == {"summary": "prefers go"}
        assert updated["metadata"] == {"source": "test"}
        # Identity fields and created_at keep their stored values on update
        assert updated["user_id"] == "alice"
        assert updated["created_at"] == original["created_at"]

    def test_get_learning_by_id_missing_returns_none(self, valkey_db: ValkeyDb):
        assert valkey_db.get_learning_by_id("nope") is None


class TestGetLearnings:
    def test_filters_by_type_and_user(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        results = valkey_db.get_learnings(learning_type="user_profile")
        assert {r["learning_id"] for r in results} == {"l1", "l2"}

        results = valkey_db.get_learnings(user_id="alice")
        assert {r["learning_id"] for r in results} == {"l1", "l3"}

    def test_sorted_by_updated_at_desc(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        time.sleep(1.1)
        valkey_db.upsert_learning(id="l1", learning_type="user_profile", content={"summary": "updated"})
        results = valkey_db.get_learnings()
        assert results[0]["learning_id"] == "l1"

    def test_limit(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        assert len(valkey_db.get_learnings(limit=2)) == 2

    def test_empty_db_returns_empty_list(self, valkey_db: ValkeyDb):
        assert valkey_db.get_learnings() == []


class TestDelete:
    def test_delete_learning(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        assert valkey_db.delete_learning("l1") is True
        assert valkey_db.get_learning_by_id("l1") is None
        assert valkey_db.delete_learning("l1") is False

    def test_delete_user_learnings(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        deleted = valkey_db.delete_user_learnings(user_id="alice")
        assert deleted == 2
        assert {r["learning_id"] for r in valkey_db.get_learnings()} == {"l2", "l4"}

    def test_delete_user_learnings_scoped_to_type(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        deleted = valkey_db.delete_user_learnings(user_id="alice", learning_type="session_context")
        assert deleted == 1
        assert valkey_db.get_learning_by_id("l1") is not None

    def test_delete_user_learnings_ignores_unowned(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        valkey_db.delete_user_learnings(user_id="alice")
        # The unowned (user_id None) entity learning is not affected
        assert valkey_db.get_learning_by_id("l4") is not None


class TestUpdateLearning:
    def test_update_existing(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        assert valkey_db.update_learning("l1", content={"summary": "patched"}, metadata={"v": 2}) is True
        updated = valkey_db.get_learning_by_id("l1")
        assert updated is not None
        assert updated["content"] == {"summary": "patched"}
        assert updated["metadata"] == {"v": 2}

    def test_update_missing_does_not_insert(self, valkey_db: ValkeyDb):
        assert valkey_db.update_learning("ghost", content={"x": 1}) is False
        assert valkey_db.get_learning_by_id("ghost") is None


class TestListLearnings:
    def test_pagination_and_count(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        records, total = valkey_db.list_learnings(limit=2, page=1)
        assert total == 4
        assert len(records) == 2
        records_page2, _ = valkey_db.list_learnings(limit=2, page=2)
        assert {r["learning_id"] for r in records}.isdisjoint({r["learning_id"] for r in records_page2})

    def test_include_global_adds_unowned(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        records, total = valkey_db.list_learnings(user_id="alice", include_global=True)
        assert {r["learning_id"] for r in records} == {"l1", "l3", "l4"}
        assert total == 3

        records, total = valkey_db.list_learnings(user_id="alice", include_global=False)
        assert {r["learning_id"] for r in records} == {"l1", "l3"}
        assert total == 2

    def test_sorting(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        records, _ = valkey_db.list_learnings(sort_by="learning_id", sort_order="asc")
        assert [r["learning_id"] for r in records] == ["l1", "l2", "l3", "l4"]


class TestUserStats:
    def test_stats_group_by_user(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        stats, total = valkey_db.get_learnings_user_stats()
        assert total == 2
        assert {s["user_id"] for s in stats} == {"alice", "bob"}
        for s in stats:
            assert s["last_learning_updated_at"] > 0

    def test_stats_filter_by_user_and_type(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        stats, total = valkey_db.get_learnings_user_stats(user_id="alice")
        assert total == 1
        assert stats[0]["user_id"] == "alice"

        stats, total = valkey_db.get_learnings_user_stats(learning_type="session_context")
        assert total == 1
        assert stats[0]["user_id"] == "alice"

    def test_stats_pagination(self, valkey_db: ValkeyDb):
        _seed(valkey_db)
        stats, total = valkey_db.get_learnings_user_stats(limit=1, page=1)
        assert total == 2
        assert len(stats) == 1
