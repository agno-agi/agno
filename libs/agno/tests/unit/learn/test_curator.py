"""Curator must maintain persisted user memories, not structured profile fields."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from agno.db.sqlite import SqliteDb
from agno.learn import LearningMachine
from agno.learn.schemas import Memories, UserProfile


@pytest.fixture
def learning(tmp_path):
    machine = LearningMachine(
        db=SqliteDb(db_file=str(tmp_path / "learning.db")),
        user_profile=True,
        user_memory=True,
    )
    yield machine
    machine.db.db_engine.dispose()


def seed(machine, user_id="alice"):
    now = datetime.now(timezone.utc)
    entries = [
        {"id": "old", "content": "Likes Python", "created_at": (now - timedelta(days=100)).isoformat()},
        {"id": "new", "content": "likes python!", "created_at": (now - timedelta(days=1)).isoformat()},
        {"id": "other", "content": "Uses Linux", "created_at": now.isoformat()},
    ]
    machine.stores["user_memory"].save(user_id=user_id, memories=Memories(user_id=user_id, memories=entries))
    machine.stores["user_profile"].save(user_id=user_id, profile=UserProfile(user_id=user_id, name=user_id))
    return entries


@pytest.mark.parametrize(
    "options,expected_ids",
    [
        ({"max_age_days": 90}, ["new", "other"]),
        ({"max_count": 1}, ["other"]),
        ({"max_age_days": 90, "max_count": 1}, ["other"]),
    ],
)
def test_prune_persists_filtered_memories_and_preserves_other_user(learning, options, expected_ids):
    seed(learning)
    bob_entries = seed(learning, "bob")

    assert learning.curator.prune("alice", **options) == 3 - len(expected_ids)
    saved = learning.stores["user_memory"].get("alice")
    assert [entry["id"] for entry in saved.memories] == expected_ids
    assert learning.stores["user_memory"].get("bob").memories == bob_entries
    assert learning.stores["user_profile"].get("alice").name == "alice"
    assert learning.curator.prune("alice", **options) == 0


def test_deduplicate_persists_first_entry_and_its_metadata(learning):
    entries = seed(learning)
    bob_entries = seed(learning, "bob")

    assert learning.curator.deduplicate("alice") == 1
    assert learning.stores["user_memory"].get("alice").memories == [entries[0], entries[2]]
    assert learning.stores["user_memory"].get("bob").memories == bob_entries
    assert learning.stores["user_profile"].get("alice").name == "alice"
    assert learning.curator.deduplicate("alice") == 0


def test_prune_can_persist_an_empty_memory_list(learning):
    old = {"id": "old", "content": "Old fact", "created_at": "2000-01-01T00:00:00Z"}
    learning.stores["user_memory"].save("alice", Memories(user_id="alice", memories=[old]))
    assert learning.curator.prune("alice", max_age_days=1) == 1
    assert learning.stores["user_memory"].get("alice").memories == []


@pytest.mark.parametrize("method", ["prune", "deduplicate"])
def test_missing_and_empty_memory_do_not_save(learning, method):
    store = learning.stores["user_memory"]
    with patch.object(store, "save", wraps=store.save) as save:
        assert getattr(learning.curator, method)("missing") == 0
        save.assert_not_called()
    store.save("alice", Memories(user_id="alice"))
    with patch.object(store, "save", wraps=store.save) as save:
        assert getattr(learning.curator, method)("alice") == 0
        save.assert_not_called()


def test_disabled_memory_leaves_profile_alone(learning):
    seed(learning)
    del learning.stores["user_memory"]
    assert learning.curator.prune("alice", max_count=1) == 0
    assert learning.curator.deduplicate("alice") == 0
    assert learning.stores["user_profile"].get("alice").name == "alice"


def test_prune_without_limits_does_not_write(learning):
    entries = seed(learning)
    store = learning.stores["user_memory"]
    with patch.object(store, "save", wraps=store.save) as save:
        assert learning.curator.prune("alice") == 0
        save.assert_not_called()
    assert store.get("alice").memories == entries


def test_memory_maintenance_does_not_require_a_profile_store(learning):
    seed(learning)
    memory_only = LearningMachine(db=learning.db, user_memory=True)
    assert "user_profile" not in memory_only.stores
    assert memory_only.curator.deduplicate("alice") == 1
    assert memory_only.curator.prune("alice", max_count=1) == 1
    assert [entry["id"] for entry in memory_only.stores["user_memory"].get("alice").memories] == ["other"]
