"""A Studio-built component wired to a Registry LearningMachine, end to end.

Registry declares the machine -> StudioTools stores a reference by name ->
AgentOS rehydrates the component with the SAME machine, the framework injects
the component's db and model into it, and the learning tools mount on a run
that carries a user_id. Also pins strict vs lenient on a missing reference,
the shared-instance contract, and that configs stored before Studio authored
learning by reference (inlined machine, legacy memory pair) still load.
"""

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import ComponentRehydrationError
from agno.learn import LearningMachine
from agno.learn.config import LearningMode, UserMemoryConfig
from agno.models.openai import OpenAIResponses
from agno.os.utils import get_agent_by_id
from agno.registry import Registry
from agno.tools.studio import StudioTools


def _registry(db, machine):
    return Registry(
        name="Learning Registry",
        models=[OpenAIResponses(id="gpt-5.5"), OpenAIResponses(id="gpt-5.4")],
        dbs=[db],
        learning=[machine],
    )


def _build(studio, name: str, model_id: str = "gpt-5.5") -> None:
    out = studio.create_agent(
        name=name, instructions="Learn about the user.", model_id=model_id, learning_name="shared-brain", publish=True
    )
    assert '"ok": true' in out, out


def test_build_publish_rehydrate_yields_the_registered_machine_with_db_and_model(tmp_path):
    from agno.agent._init import initialize_agent

    db = SqliteDb(db_file=str(tmp_path / "learning_os.db"))
    machine = LearningMachine(name="shared-brain", user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC))
    registry = _registry(db, machine)
    _build(StudioTools(registry=registry, db=db), "learner")

    # The stored config is a reference, not the machine.
    assert db.get_config(component_id="learner", version=1)["config"]["learning"] == {"name": "shared-brain"}

    # AgentOS resolves the published component through the registry.
    agent = get_agent_by_id("learner", agents=None, db=db, registry=registry)
    assert agent.learning is machine

    # Init injects the component's db and model into the machine it was left without.
    initialize_agent(agent)
    assert agent.learning_machine is machine
    assert machine.db is not None
    assert machine.model is not None and machine.model.id == "gpt-5.5"

    # The learning tools mount on a run that carries a user id, and only then.
    with_user = {t.__name__ for t in machine.get_tools(user_id="ash", agent_id=agent.id)}
    assert "update_user_memory" in with_user
    assert machine.get_tools(user_id=None, agent_id=agent.id) == []


def test_missing_reference_refuses_strict_and_degrades_lenient(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "learning_missing.db"))
    machine = LearningMachine(name="shared-brain", user_memory=True)
    _build(StudioTools(registry=_registry(db, machine), db=db), "learner")

    # A registry without the machine: dispatch (strict) refuses rather than
    # serving the component with no learning; cancel/history (lenient) get a
    # degraded handle.
    bare = Registry(models=[OpenAIResponses(id="gpt-5.5")], dbs=[db])
    with pytest.raises(ComponentRehydrationError, match="shared-brain"):
        get_agent_by_id("learner", agents=None, db=db, registry=bare)

    degraded = get_agent_by_id("learner", agents=None, db=db, registry=bare, strict=False)
    assert degraded.learning is None


def test_two_built_components_share_one_machine_instance(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "learning_shared.db"))
    machine = LearningMachine(name="shared-brain", user_memory=True)
    registry = _registry(db, machine)
    studio = StudioTools(registry=registry, db=db)
    _build(studio, "first", model_id="gpt-5.5")
    _build(studio, "second", model_id="gpt-5.4")

    first = get_agent_by_id("first", agents=None, db=db, registry=registry)
    second = get_agent_by_id("second", agents=None, db=db, registry=registry)
    assert first.learning is machine
    assert second.learning is machine


def test_configs_stored_before_reference_learning_still_load(tmp_path):
    """A config stored before Studio authored learning by reference can carry
    the legacy memory pair and an inlined machine; Studio no longer authors
    these shapes, and AgentOS must keep loading them."""
    from agno.memory.manager import MemoryManager

    db = SqliteDb(db_file=str(tmp_path / "learning_legacy.db"))
    manager = MemoryManager(id="mm-stable")
    Agent(
        id="legacy",
        name="Legacy",
        model=OpenAIResponses(id="gpt-5.5"),
        enable_agentic_memory=True,
        memory_manager=manager,
        learning=LearningMachine(user_memory=True),
    ).save(db=db)
    stored = db.get_config(component_id="legacy", version=1)["config"]
    assert stored["enable_agentic_memory"] is True
    assert stored["memory_manager"] == {"registry_id": "mm-stable"}
    assert stored["learning"] == {"user_memory": True}

    registry = Registry(models=[OpenAIResponses(id="gpt-5.5")], dbs=[db], memory_managers=[manager])
    agent = get_agent_by_id("legacy", agents=None, db=db, registry=registry)
    assert agent.enable_agentic_memory is True
    assert agent.memory_manager is manager
    assert isinstance(agent.learning, LearningMachine)
    assert agent.learning.name is None
    assert agent.learning.user_memory is True
