"""A registry LearningMachine is one instance shared by every component that
references it, so its first store initialization can be raced by two requests.
No caller may observe a partially built store map, and two first callers must
end up with the same store objects. Deterministic: threads synchronize on
Events, never on sleeps."""

import threading
from typing import Any, Dict, List, Optional

from agno.learn import LearningMachine
from agno.learn.config import LearningMode, UserMemoryConfig


class _Db:
    def get_learning(self, **kwargs: Any) -> Optional[Dict[str, Any]]:
        return None

    def upsert_learning(self, id: str, **kwargs: Any) -> None:
        return None

    def get_learnings(self, **kwargs: Any) -> List[Dict[str, Any]]:
        return []

    def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        return []

    def delete_learning(self, id: str) -> bool:
        return False


def _machine() -> LearningMachine:
    return LearningMachine(
        name="shared-brain",
        db=_Db(),  # type: ignore[arg-type]
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        entity_memory=True,
    )


def test_second_caller_waits_for_the_first_initialization_and_both_see_every_store(monkeypatch) -> None:
    """Block the first initialization mid-way (after the first store is built,
    before the rest), start a second caller, and check it neither returns early
    with a partial map nor builds a second store set."""
    machine = _machine()
    entered = threading.Event()
    release = threading.Event()
    original_resolve = LearningMachine._resolve_store
    calls: List[str] = []

    def blocking_resolve(self: LearningMachine, input_value: Any, store_type: str) -> Any:
        calls.append(store_type)
        store = original_resolve(self, input_value=input_value, store_type=store_type)
        if store_type == "user_memory":
            # First store built; hold here so a concurrent caller arrives
            # while initialization is in flight.
            entered.set()
            assert release.wait(timeout=10), "test harness never released the first initializer"
        return store

    monkeypatch.setattr(LearningMachine, "_resolve_store", blocking_resolve)

    results: Dict[str, Any] = {}
    first_done = threading.Event()
    second_done = threading.Event()

    def first() -> None:
        results["first_tools"] = {t.__name__ for t in machine.get_tools(user_id="ash", agent_id="a1")}
        results["first_stores"] = machine.stores
        first_done.set()

    def second() -> None:
        results["second_tools"] = {t.__name__ for t in machine.get_tools(user_id="ash", agent_id="a2")}
        results["second_stores"] = machine.stores
        second_done.set()

    t1 = threading.Thread(target=first, daemon=True)
    t1.start()
    assert entered.wait(timeout=10), "first initializer never reached the block point"

    t2 = threading.Thread(target=second, daemon=True)
    t2.start()
    # The second caller must be blocked behind the in-flight initialization:
    # it must not have completed while the first one is still held.
    assert not second_done.wait(timeout=0.2)
    assert "second_tools" not in results

    release.set()
    assert first_done.wait(timeout=10)
    assert second_done.wait(timeout=10)
    t1.join(timeout=10)
    t2.join(timeout=10)

    # One initialization only, one store set, seen complete by both callers.
    assert calls.count("user_memory") == 1 and calls.count("entity_memory") == 1
    assert results["first_stores"] is results["second_stores"]
    assert set(results["first_stores"]) == {"user_memory", "entity_memory"}
    expected = {"update_user_memory", "remember_about", "link_entities", "search_entities", "forget"}
    assert results["first_tools"] == expected
    assert results["second_tools"] == expected


def test_lazy_initialization_and_model_backfill_are_preserved() -> None:
    """No stores are built until first access, and a model bound after the
    stores were built is still backfilled into them on the next access."""
    from agno.models.openai import OpenAIResponses

    machine = _machine()
    assert machine._stores is None

    stores = machine.stores
    assert set(stores) == {"user_memory", "entity_memory"}
    assert machine.stores is stores
    assert all(getattr(store.config, "model", None) is None for store in stores.values())  # type: ignore[attr-defined]

    machine.model = OpenAIResponses(id="gpt-5.5")
    assert all(store.config.model is machine.model for store in machine.stores.values())  # type: ignore[attr-defined]


def test_db_and_knowledge_bound_after_the_stores_were_built_are_backfilled() -> None:
    """A registry machine is built by whichever sharer runs first. One that
    lacks knowledge builds the learned_knowledge store with knowledge=None; a
    later sharer that binds a knowledge must reach that store, or its
    search/save tools mount and silently no-op for every sharer."""

    class _Knowledge:
        pass

    machine = LearningMachine(name="shared-brain", db=_Db(), learned_knowledge=True, entity_memory=True)  # type: ignore[arg-type]
    store = machine.stores["learned_knowledge"]
    assert store.config.knowledge is None  # type: ignore[attr-defined]
    assert store.knowledge is None  # type: ignore[attr-defined]

    knowledge = _Knowledge()
    machine.knowledge = knowledge
    assert machine.stores["learned_knowledge"] is store
    assert store.config.knowledge is knowledge  # type: ignore[attr-defined]
    assert store.knowledge is knowledge  # type: ignore[attr-defined]

    # db the same way, for a store built before the machine had one.
    bare = LearningMachine(name="late-db", entity_memory=True)
    entity = bare.stores["entity_memory"]
    assert entity.config.db is None  # type: ignore[attr-defined]
    db = _Db()
    bare.db = db
    assert bare.stores["entity_memory"].config.db is db  # type: ignore[attr-defined]


def test_machine_can_be_deep_copied_and_pickled() -> None:
    """The init lock is per instance and never travels with a copy."""
    import copy
    import pickle

    machine = LearningMachine(name="shared-brain", user_memory=True, entity_memory=True)
    copied = copy.deepcopy(machine)
    assert copied.name == "shared-brain" and copied.user_memory is True
    assert copied._init_lock is not machine._init_lock

    restored = pickle.loads(pickle.dumps(machine))
    assert restored.name == "shared-brain" and restored.entity_memory is True
    assert restored._init_lock is not machine._init_lock
    assert set(restored.stores) == {"user_memory", "entity_memory"}
