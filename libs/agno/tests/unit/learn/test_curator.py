from types import SimpleNamespace
from agno.learn.curate import Curator
from agno.learn.schemas import Memories


def test_curator_prune_and_deduplicate_user_memory():
    dupes = Memories(
        user_id="alice",
        memories=[
            {"content": "Prefers concise answers", "created_at": "2024-01-01T00:00:00Z"},
            {"content": "prefers concise answers!", "created_at": "2024-01-02T00:00:00Z"},
        ],
    )
    saved_calls = []

    def mock_save(user_id, entity):
        saved_calls.append((user_id, entity))

    mem_store = SimpleNamespace(get=lambda user_id: dupes, save=mock_save)
    curator = Curator(machine=SimpleNamespace(stores={"user_memory": mem_store}))

    removed_dedup = curator.deduplicate(user_id="alice", store_key="user_memory")
    assert removed_dedup == 1
    assert len(dupes.memories) == 1
    assert len(saved_calls) == 1

    removed_prune = curator.prune(user_id="alice", max_count=0, max_age_days=1, store_key="user_memory")
    assert removed_prune == 1
    assert len(dupes.memories) == 0


def test_curator_nonexistent_store_returns_zero():
    curator = Curator(machine=SimpleNamespace(stores={}))
    assert curator.deduplicate(user_id="bob", store_key="unknown") == 0
    assert curator.prune(user_id="bob", store_key="unknown") == 0
