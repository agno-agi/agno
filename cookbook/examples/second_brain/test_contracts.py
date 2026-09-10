"""Real learning-store persistence and explicit correction, without model calls."""

import importlib
import sys

from agno.db.sqlite import SqliteDb
from agno.learn import (
    EntityMemoryConfig,
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)


def test_learning_persistence_correction_and_isolation(tmp_path):
    path = str(tmp_path / "learning.db")
    brain = LearningMachine(
        db=SqliteDb(db_file=path),
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        entity_memory=EntityMemoryConfig(namespace="user"),
    )
    entity = brain.entity_memory_store
    tools = {tool.__name__: tool for tool in entity.get_tools(user_id="alice")}
    tools["remember_about"](entity="Harbor", entity_type="project", facts=["Lead: Jen"])
    tools["forget"](entity="Harbor", fact="Lead: Jen")
    tools["remember_about"](
        entity="Harbor", entity_type="project", facts=["Lead: Maya"]
    )
    brain.user_profile_store.save(
        user_id="alice", profile={"user_id": "alice", "name": "Alex"}
    )
    brain.user_memory_store.save(
        user_id="alice",
        memories={
            "user_id": "alice",
            "memories": [{"id": "pref", "content": "Prefers concise updates"}],
        },
    )
    restarted = LearningMachine(
        db=SqliteDb(db_file=path),
        user_profile=True,
        user_memory=True,
        entity_memory=EntityMemoryConfig(namespace="user"),
    )
    context = restarted.build_context(user_id="alice", message="Harbor")
    assert "Maya" in context and "Lead: Jen" not in context
    assert "Alex" in context and "concise" in context
    assert restarted.entity_memory_store.get("harbor", "project", user_id="bob") is None
    assert restarted.user_profile_store.recall(user_id="bob") is None
    assert restarted.user_memory_store.recall(user_id="bob") is None


def test_no_unauthenticated_app(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    sys.modules.pop("second_brain", None)
    module = importlib.import_module("second_brain")
    assert module.app is None
    assert module.second_brain.user_id is None
    assert module.brain.entity_memory_store.config.namespace == "user"
