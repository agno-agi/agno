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


def test_name_round_trips_and_leads_repr() -> None:
    """A registry name is identity: it survives the config round-trip and is
    the first thing the repr shows."""
    machine = LearningMachine(name="shared-brain", user_memory=True)
    payload = machine.to_dict()
    assert payload["name"] == "shared-brain"

    rebuilt = LearningMachine.from_dict(payload)
    assert rebuilt.name == "shared-brain"
    assert rebuilt.user_memory is True
    assert repr(rebuilt).startswith("LearningMachine(name='shared-brain', ")


def test_unnamed_machine_writes_no_name_and_legacy_dicts_load_unnamed() -> None:
    """Configs written before the name existed carry no name key, and an
    unnamed machine must not start writing one: the serializer keys a
    registry reference on ``{"name": ...}`` alone, so ``{}`` and every
    store-carrying dict have to stay inline machines."""
    assert "name" not in LearningMachine(user_memory=True).to_dict()
    assert LearningMachine().to_dict() == {}

    legacy = LearningMachine.from_dict({"user_profile": True, "user_memory": True})
    assert legacy.name is None
    assert legacy.user_memory is True

    empty = LearningMachine.from_dict({})
    assert empty.name is None
    assert empty.to_dict() == {}

    # A blank name is no name.
    assert LearningMachine.from_dict({"name": "", "user_memory": True}).name is None


def test_bool_learned_knowledge_inherits_machine_namespace() -> None:
    """The machine namespace is the default for BOTH namespaced stores. A
    bool-enabled learned_knowledge used to stay on "global" while
    entity_memory followed the machine, so a deployer who set one namespace
    got two."""
    from agno.learn.config import LearnedKnowledgeConfig

    machine = LearningMachine(
        db=RecordingLearningDb(),  # type: ignore[arg-type]
        namespace="team_west",
        entity_memory=True,
        learned_knowledge=True,
        knowledge=object(),
    )
    assert machine.stores["entity_memory"].config.namespace == "team_west"  # type: ignore[attr-defined]
    assert machine.stores["learned_knowledge"].config.namespace == "team_west"  # type: ignore[attr-defined]

    # An explicit store namespace still wins over the machine's.
    explicit = LearningMachine(
        db=RecordingLearningDb(),  # type: ignore[arg-type]
        namespace="team_west",
        learned_knowledge=LearnedKnowledgeConfig(namespace="ops"),
        knowledge=object(),
    )
    assert explicit.stores["learned_knowledge"].config.namespace == "ops"  # type: ignore[attr-defined]


def test_positional_construction_keeps_db_first_and_only_a_real_name_serializes() -> None:
    """name is declared after the public fields, so the positional signature
    (db, model, knowledge, ...) is unchanged; and only a non-empty str name is
    written by to_dict, which is also the only name the storage layer treats
    as a registry reference."""
    db = RecordingLearningDb()
    machine = LearningMachine(db)  # type: ignore[arg-type]
    assert machine.db is db
    assert machine.name is None

    assert "name" not in LearningMachine(name="").to_dict()
    assert "name" not in LearningMachine(name=123).to_dict()  # type: ignore[arg-type]
    assert LearningMachine(name="brain").to_dict() == {"name": "brain"}


def test_describe_learning_machine_reads_declared_fields_only() -> None:
    """The listing summary never builds the stores, reports a pre-built Store
    instance's own namespace, and lists custom stores by name."""
    from agno.learn.config import EntityMemoryConfig
    from agno.learn.machine import describe_learning_machine
    from agno.learn.stores.entity_memory import EntityMemoryStore

    class TinyStore:
        def recall(self, **kwargs: Any) -> None:
            return None

    machine = LearningMachine(
        name="brain",
        namespace="team_west",
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        entity_memory=EntityMemoryStore(config=EntityMemoryConfig()),
        learned_knowledge=True,
        knowledge=object(),
        custom_stores={"tiny": TinyStore()},  # type: ignore[dict-item]
    )
    summary = describe_learning_machine(machine)
    assert machine._stores is None
    assert summary["name"] == "brain"
    assert summary["namespace"] == "team_west"
    assert summary["stores"] == {
        "user_memory": {"mode": "agentic"},
        "entity_memory": {"mode": "agentic", "namespace": "global"},
        "learned_knowledge": {"mode": "agentic", "namespace": "team_west"},
    }
    assert summary["custom_stores"] == ["tiny"]
    assert summary["model_id"] is None and summary["db"] is False and summary["knowledge"] is True
    # The Store instance really does keep its own namespace at run time.
    assert machine.stores["entity_memory"].config.namespace == "global"  # type: ignore[attr-defined]
