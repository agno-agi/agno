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


def test_hitl_mode_warns_unsupported_without_deprecating(caplog) -> None:
    from agno.learn.config import LearningMode, UserMemoryConfig
    from agno.learn.stores.user_memory import UserMemoryStore

    with caplog.at_level(logging.WARNING):
        UserMemoryStore(config=UserMemoryConfig(db=RecordingLearningDb(), mode=LearningMode.HITL))  # type: ignore[arg-type]
    messages = [r.getMessage() for r in caplog.records]
    assert any("does not support HITL mode" in m for m in messages)
    assert not any("deprecated" in m for m in messages)


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


def test_backend_without_search_warns_once_on_the_write_path(caplog, tmp_path) -> None:
    """A backend with no search_learnings degrades RESOLUTION, not just search.

    Past ~50 entities an alias stops resolving and the write mints a second
    entity for the same thing, with no unmerge - so the warning has to reach
    the write path, and has to name that consequence.
    """
    import asyncio

    from agno.db.sqlite import AsyncSqliteDb
    from agno.learn.config import EntityMemoryConfig, LearningMode
    from agno.learn.stores.entity_memory import EntityMemoryStore

    db = AsyncSqliteDb(db_file=str(tmp_path / "a.db"))
    store = EntityMemoryStore(
        config=EntityMemoryConfig(db=db, mode=LearningMode.AGENTIC, namespace="global")  # type: ignore[arg-type]
    )

    async def write_three() -> None:
        for i in range(3):
            await store.aremember_about(
                entity=f"Thing {i}", entity_type="company", aliases=[f"T{i}"], namespace="global"
            )

    with caplog.at_level(logging.WARNING):
        asyncio.run(write_three())

    warnings = [r.getMessage() for r in caplog.records if "no search_learnings implementation" in r.getMessage()]
    assert len(warnings) == 1, warnings
    assert "SECOND entity" in warnings[0]
    assert "SqliteDb, PostgresDb and AsyncPostgresDb" in warnings[0]


def test_the_three_first_tier_backends_implement_search() -> None:
    from agno.db.postgres import AsyncPostgresDb, PostgresDb
    from agno.db.sqlite import SqliteDb

    for backend in (SqliteDb, PostgresDb, AsyncPostgresDb):
        assert "search_learnings" in backend.__dict__, backend.__name__


def test_manual_door_without_a_model_says_capture_is_off(caplog, tmp_path) -> None:
    """The manual door injects nothing, so a hand-built machine keeps model=None.

    Capture is a model call: the tools return "No model provided" and entity
    memory retires nothing, while the guidance block promises the opposite.
    """
    from agno.db.sqlite import SqliteDb
    from agno.learn.config import LearningMode, UserMemoryConfig

    machine = LearningMachine(
        db=SqliteDb(db_file=str(tmp_path / "a.db")),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        entity_memory=True,
    )
    with caplog.at_level(logging.WARNING):
        machine.get_tools(user_id="composer@example.com")
        machine.get_tools(user_id="composer@example.com")

    warnings = [r.getMessage() for r in caplog.records if "LearningMachine has no model" in r.getMessage()]
    assert len(warnings) == 1, warnings
    assert "user_memory" in warnings[0] and "entity_memory" in warnings[0]


def test_the_automatic_door_is_quiet_because_the_agent_injects_its_model(caplog, tmp_path) -> None:
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.learn.config import LearningMode, UserMemoryConfig

    machine = LearningMachine(user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC), entity_memory=True)
    agent = Agent(model="openai:gpt-5.5", db=SqliteDb(db_file=str(tmp_path / "b.db")), learning=machine)
    with caplog.at_level(logging.WARNING):
        agent.initialize_agent()
        machine.get_tools(user_id="composer@example.com")

    assert not any("LearningMachine has no model" in r.getMessage() for r in caplog.records)


def test_agent_knowledge_does_not_conjure_a_learned_knowledge_store(tmp_path) -> None:
    """`knowledge=` on the agent must not add stores the machine never asked for.

    The copy exists to repair a round trip (from_dict cannot carry a knowledge
    base). Unconditional, it turned any `Agent(knowledge=kb, learning=machine)`
    into two extra tools - `save_learning` writes into the user's production
    index - plus a second guidance block competing with the machine's own.
    """
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.learn import EntityMemoryConfig, LearningMode, UserMemoryConfig

    class FakeKnowledge:
        name = "kb"

    machine = LearningMachine(
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC), entity_memory=EntityMemoryConfig()
    )
    agent = Agent(
        model="openai:gpt-5.5",
        db=SqliteDb(db_file=str(tmp_path / "a.db")),
        knowledge=FakeKnowledge(),
        learning=machine,
        user_id="u1",
    )
    agent.initialize_agent()

    assert sorted(machine.stores) == ["entity_memory", "user_memory"]
    assert "save_learning" not in {t.__name__ for t in machine.get_tools(user_id="u1")}


def test_a_wanted_learned_knowledge_store_still_gets_the_agents_knowledge(tmp_path) -> None:
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.learn import LearningMode, UserMemoryConfig

    class FakeKnowledge:
        name = "kb"

    machine = LearningMachine(user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC), learned_knowledge=True)
    agent = Agent(
        model="openai:gpt-5.5",
        db=SqliteDb(db_file=str(tmp_path / "b.db")),
        knowledge=FakeKnowledge(),
        learning=machine,
        user_id="u1",
    )
    agent.initialize_agent()

    assert machine.knowledge is not None
    assert "learned_knowledge" in machine.stores


def test_a_configured_capture_policy_survives_the_execute_contract(tmp_path) -> None:
    """`instructions` is the capture-policy knob, and the tool path is the only
    path AGENTIC mode takes. The execute contract replaces the store's own
    gatekeeping, not the operator's policy."""
    from agno.db.sqlite import SqliteDb
    from agno.learn.config import LearningMode, UserMemoryConfig
    from agno.learn.stores.user_memory import UserMemoryStore

    store = UserMemoryStore(
        config=UserMemoryConfig(
            db=SqliteDb(db_file=str(tmp_path / "m.db")),
            mode=LearningMode.AGENTIC,
            instructions="House policy: never record salaries.",
        )
    )
    instructed = store._get_system_message(existing_data=[], instructed=True).content
    passive = store._get_system_message(existing_data=[], instructed=False).content

    assert "House policy: never record salaries." in instructed
    assert "House policy: never record salaries." in passive
    assert "Carry out that" in instructed
