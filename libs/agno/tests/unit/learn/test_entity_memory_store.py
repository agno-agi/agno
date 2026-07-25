"""Unit tests for the revamped EntityMemoryStore.

Entity memory is AGENTIC-only: the agent records through four tools
(remember_about, link_entities, search_entities, forget) and there is no
extraction pass. These tests run offline against a recording fake db.
"""

from typing import Any, Dict, List, Optional

import pytest

from agno.learn.config import EntityMemoryConfig, LearningMode
from agno.learn.stores.entity_memory import EntityMemoryStore


class RecordingLearningDb:
    """In-memory fake of the learnings table, keyed by learning_id."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    def get_learning(self, **kwargs: Any) -> Optional[Dict[str, Any]]:
        learning_type = kwargs.get("learning_type")
        entity_id = kwargs.get("entity_id")
        entity_type = kwargs.get("entity_type")
        namespace = kwargs.get("namespace")
        for row in self.rows.values():
            if (
                row.get("learning_type") == learning_type
                and row.get("entity_id") == entity_id
                and row.get("entity_type") == entity_type
                and row.get("namespace") == namespace
            ):
                return row
        return None

    def upsert_learning(self, id: str, **kwargs: Any) -> None:
        import time

        existing = self.rows.get(id, {})
        row = {**existing, **kwargs, "learning_id": id}
        row["updated_at"] = int(time.time())
        self.rows[id] = row

    def get_learnings(self, **kwargs: Any) -> List[Dict[str, Any]]:
        learning_type = kwargs.get("learning_type")
        entity_type = kwargs.get("entity_type")
        namespace = kwargs.get("namespace")
        limit = kwargs.get("limit")
        rows = [
            row
            for row in self.rows.values()
            if (learning_type is None or row.get("learning_type") == learning_type)
            and (entity_type is None or row.get("entity_type") == entity_type)
            and (namespace is None or row.get("namespace") == namespace)
        ]
        rows.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
        if limit is not None:
            rows = rows[:limit]
        return rows

    def delete_learning(self, id: str) -> bool:
        return self.rows.pop(id, None) is not None


@pytest.fixture
def db() -> RecordingLearningDb:
    return RecordingLearningDb()


@pytest.fixture
def store(db: RecordingLearningDb) -> EntityMemoryStore:
    return EntityMemoryStore(config=EntityMemoryConfig(db=db))  # type: ignore[arg-type]


class TestAgenticOnly:
    def test_default_mode_is_agentic(self) -> None:
        assert EntityMemoryConfig().mode is LearningMode.AGENTIC

    @pytest.mark.parametrize("mode", [LearningMode.ALWAYS, LearningMode.PROPOSE, LearningMode.HITL])
    def test_non_agentic_mode_raises(self, mode: LearningMode) -> None:
        with pytest.raises(ValueError, match="AGENTIC-only"):
            EntityMemoryStore(config=EntityMemoryConfig(mode=mode))

    def test_extraction_api_is_gone(self, store: EntityMemoryStore) -> None:
        for name in (
            "extract_and_save",
            "aextract_and_save",
            "_get_extraction_tools",
            "_aget_extraction_tools",
            "_get_extraction_system_message",
        ):
            assert not hasattr(store, name)

    def test_process_is_a_noop(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.process(messages=[object()], user_id="user-1")
        assert db.rows == {}
        assert store.was_updated is False

    async def test_aprocess_is_a_noop(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        await store.aprocess(messages=[object()], user_id="user-1")
        assert db.rows == {}
        assert store.was_updated is False

    def test_machine_bool_input_builds_agentic_store(self, db: RecordingLearningDb) -> None:
        from agno.learn import LearningMachine

        machine = LearningMachine(db=db, entity_memory=True)  # type: ignore[arg-type]
        entity_store = machine.entity_memory_store
        assert entity_store is not None
        assert entity_store.config.mode is LearningMode.AGENTIC
