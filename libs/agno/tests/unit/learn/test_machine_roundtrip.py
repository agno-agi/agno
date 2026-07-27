"""Unit tests for the lossless LearningMachine config round-trip (spec §3.9).

Verified live before the fix: an AGENTIC machine round-tripped through
Agent.save()/load() came back as ALWAYS and get_tools() returned [] - the
agent silently lost its entire learning tool surface.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agno.learn import LearningMachine, UserProfile
from agno.learn.config import (
    EntityMemoryConfig,
    LearningMode,
    UserMemoryConfig,
)


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


@dataclass
class ExtendedProfile(UserProfile):
    company: Optional[str] = field(default=None, metadata={"description": "Where they work"})


def test_round_trip_preserves_mode_and_tools() -> None:
    """The §8 bullet: from_dict(to_dict()) keeps AGENTIC, and the rebuilt
    machine still has its tool surface."""
    machine = LearningMachine(
        db=RecordingLearningDb(),  # type: ignore[arg-type]
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        entity_memory=EntityMemoryConfig(namespace="global", supersession_threshold=0.9),
    )
    rebuilt = LearningMachine.from_dict(machine.to_dict())
    rebuilt.db = RecordingLearningDb()  # type: ignore[assignment]

    assert isinstance(rebuilt.user_memory, UserMemoryConfig)
    assert rebuilt.user_memory.mode is LearningMode.AGENTIC
    assert isinstance(rebuilt.entity_memory, EntityMemoryConfig)
    assert rebuilt.entity_memory.supersession_threshold == 0.9

    tools = rebuilt.get_tools(user_id="u1")
    names = {t.__name__ for t in tools}
    assert "update_user_memory" in names
    assert {"remember_about", "link_entities", "search_entities", "forget"} <= names


def test_round_trip_preserves_prompts_limits_and_namespace() -> None:
    machine = LearningMachine(
        db=RecordingLearningDb(),  # type: ignore[arg-type]
        user_memory=UserMemoryConfig(
            mode=LearningMode.AGENTIC,
            instructions="capture durable facts",
            additional_instructions="ignore small talk",
            max_updates_per_run=7,
            enable_delete_memory=False,
        ),
        namespace="team_west",
        max_updates_per_run=25,
    )
    rebuilt = LearningMachine.from_dict(machine.to_dict())

    assert rebuilt.namespace == "team_west"
    assert rebuilt.max_updates_per_run == 25
    assert isinstance(rebuilt.user_memory, UserMemoryConfig)
    assert rebuilt.user_memory.instructions == "capture durable facts"
    assert rebuilt.user_memory.additional_instructions == "ignore small talk"
    assert rebuilt.user_memory.max_updates_per_run == 7
    assert rebuilt.user_memory.enable_delete_memory is False


def test_round_trip_preserves_schema_by_import_path() -> None:
    machine = LearningMachine(
        db=RecordingLearningDb(),  # type: ignore[arg-type]
        user_profile=__import__("agno.learn.config", fromlist=["UserProfileConfig"]).UserProfileConfig(
            mode=LearningMode.AGENTIC, schema=ExtendedProfile
        ),
    )
    payload = machine.to_dict()
    assert payload["user_profile"]["schema"].endswith("ExtendedProfile")

    rebuilt = LearningMachine.from_dict(payload)
    assert rebuilt.user_profile.schema is ExtendedProfile  # type: ignore[union-attr]


def test_from_dict_accepts_old_boolean_payloads() -> None:
    rebuilt = LearningMachine.from_dict(
        {"user_profile": True, "user_memory": True, "namespace": "global", "debug_mode": False}
    )
    assert rebuilt.user_profile is True
    assert rebuilt.user_memory is True
    assert rebuilt.entity_memory is False


def test_store_instance_serializes_its_config() -> None:
    from agno.learn.stores.entity_memory import EntityMemoryStore

    store = EntityMemoryStore(config=EntityMemoryConfig(db=RecordingLearningDb(), namespace="ops"))  # type: ignore[arg-type]
    machine = LearningMachine(db=RecordingLearningDb(), entity_memory=store)  # type: ignore[arg-type]
    payload = machine.to_dict()
    assert payload["entity_memory"]["namespace"] == "ops"

    rebuilt = LearningMachine.from_dict(payload)
    assert isinstance(rebuilt.entity_memory, EntityMemoryConfig)
    assert rebuilt.entity_memory.namespace == "ops"


def test_custom_stores_round_trip_as_logged_refs(caplog) -> None:
    class TinyStore:
        learning_type = "tiny"
        schema = dict
        was_updated = False

        def recall(self, **kwargs: Any) -> Any:
            return None

        async def arecall(self, **kwargs: Any) -> Any:
            return None

        def process(self, messages: Any, **kwargs: Any) -> None:
            pass

        async def aprocess(self, messages: Any, **kwargs: Any) -> None:
            pass

        def build_context(self, data: Any) -> str:
            return ""

        def instructions(self) -> str:
            return ""

        def get_tools(self, **kwargs: Any) -> List[Any]:
            return []

        async def aget_tools(self, **kwargs: Any) -> List[Any]:
            return []

    machine = LearningMachine(db=RecordingLearningDb(), custom_stores={"tiny": TinyStore()})  # type: ignore[arg-type]
    payload = machine.to_dict()
    assert "tiny" in payload["custom_stores"]

    with caplog.at_level(logging.WARNING):
        rebuilt = LearningMachine.from_dict(payload)
    assert rebuilt.custom_stores is None
    assert any("cannot be rebuilt" in r.getMessage() for r in caplog.records)


def test_agent_save_load_keeps_the_tool_surface(tmp_path) -> None:
    """End to end through the real Agent storage path (the launch-blocking bug:
    an AGENTIC machine reloaded as ALWAYS and lost its tools)."""
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.models.openai import OpenAIResponses

    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    machine = LearningMachine(
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        entity_memory=True,
    )
    agent = Agent(
        id="round-trip-agent",
        db=db,
        model=OpenAIResponses(id="gpt-5.5"),
        learning=machine,
    )
    agent.save()

    loaded = Agent.load(id="round-trip-agent", db=db)
    assert loaded is not None
    assert isinstance(loaded.learning, LearningMachine)
    assert isinstance(loaded.learning.user_memory, UserMemoryConfig)
    assert loaded.learning.user_memory.mode is LearningMode.AGENTIC

    loaded.learning.db = db
    tools = loaded.learning.get_tools(user_id="u1")
    names = {t.__name__ for t in tools}
    assert "update_user_memory" in names
    assert "remember_about" in names
