"""Unit tests for the 2.8.4 deprecation warnings and visibility guards."""

import logging
from typing import Any, Dict, List, Optional

from agno.learn import LearningMachine


class RecordingLearningDb:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    def get_learning(self, **kwargs: Any) -> Optional[Dict[str, Any]]:
        return None

    def upsert_learning(self, id: str, **kwargs: Any) -> None:
        self.rows[id] = {**kwargs, "learning_id": id}

    def get_learnings(self, **kwargs: Any) -> List[Dict[str, Any]]:
        return []

    def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        return []

    def delete_learning(self, id: str) -> bool:
        return self.rows.pop(id, None) is not None


def test_enable_user_memories_is_quiet(caplog, tmp_path) -> None:
    """enable_user_memories still aliases update_memory_on_run and says nothing.

    Every rebuild path passes the alias explicitly (deep_copy from the attribute,
    Agent.load with a False default), so a deprecation warning here fires on
    agents whose author never wrote the parameter.
    """
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb

    with caplog.at_level(logging.WARNING):
        agent = Agent(db=SqliteDb(db_file=str(tmp_path / "a.db")), enable_user_memories=True)
        agent.deep_copy()
    assert agent.update_memory_on_run is True
    assert not any("enable_user_memories" in r.getMessage() for r in caplog.records)


def test_hitl_mode_warns_deprecated(caplog) -> None:
    from agno.learn.config import LearningMode, UserMemoryConfig
    from agno.learn.stores.user_memory import UserMemoryStore

    with caplog.at_level(logging.WARNING):
        UserMemoryStore(config=UserMemoryConfig(db=RecordingLearningDb(), mode=LearningMode.HITL))  # type: ignore[arg-type]
    assert any("HITL" in r.getMessage() and "deprecated" in r.getMessage() for r in caplog.records)


def test_agentic_memory_collision_is_quiet(caplog, tmp_path) -> None:
    """set_learning_machine runs on every run, so a guard that logs there logs
    once per run. The collision is documented instead."""
    from agno.agent import Agent
    from agno.agent._init import set_learning_machine
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "b.db"))
    agent = Agent(db=db, learning=True, enable_agentic_memory=True)
    with caplog.at_level(logging.WARNING):
        set_learning_machine(agent)
        set_learning_machine(agent)
    assert not any("silently dropped" in r.getMessage() for r in caplog.records)


def test_missing_user_id_with_per_user_stores_warns_once(caplog) -> None:
    machine = LearningMachine(db=RecordingLearningDb(), user_memory=True, user_profile=True)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        machine.get_tools(user_id=None)
        machine.get_tools(user_id=None)
    warnings = [r for r in caplog.records if "no user_id" in r.getMessage()]
    assert len(warnings) == 1
    assert "user_profile" in warnings[0].getMessage() and "user_memory" in warnings[0].getMessage()


def test_no_missing_user_id_warning_when_user_present_or_no_per_user_stores(caplog) -> None:
    machine = LearningMachine(db=RecordingLearningDb(), user_memory=True)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        machine.get_tools(user_id="u1")
    assert not any("no user_id" in r.getMessage() for r in caplog.records)

    entity_only = LearningMachine(db=RecordingLearningDb(), entity_memory=True)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        entity_only.get_tools(user_id=None)
    assert not any("no user_id" in r.getMessage() for r in caplog.records)
