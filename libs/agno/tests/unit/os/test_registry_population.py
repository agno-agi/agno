"""
Unit tests for AgentOS registry population and deduplication logic.

Covers:
- _populate_registry_managers(): discovery of memory/session managers from
  agents and teams, deduplication by manager id, owner metadata tagging
- _populate_registry_knowledge(): copying discovered knowledge into the registry
- Bidirectional knowledge: registry knowledge is surfaced as a knowledge
  instance via _auto_discover_knowledge_instances()
"""

from unittest.mock import MagicMock

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.memory.manager import MemoryManager
from agno.os import AgentOS
from agno.registry import Registry
from agno.session.summary import SessionSummaryManager

# =============================================================================
# _populate_registry_managers()
# =============================================================================


class TestPopulateRegistryManagers:
    """Tests for AgentOS._populate_registry_managers()."""

    def test_discovers_managers_from_agent(self):
        """Memory and session managers on an agent are added to the registry."""
        mm = MemoryManager(id="mm-1")
        sm = SessionSummaryManager(id="sm-1")
        agent = Agent(name="A1", id="a1", memory_manager=mm, session_summary_manager=sm, telemetry=False)

        os = AgentOS(agents=[agent], telemetry=False)
        os._populate_registry_managers()

        assert mm in os.registry.memory_managers
        assert sm in os.registry.session_summary_managers

    def test_tags_owner_metadata(self):
        """Discovered managers are tagged with owner id and type."""
        mm = MemoryManager(id="mm-1")
        sm = SessionSummaryManager(id="sm-1")
        agent = Agent(
            name="A1",
            id="a1",
            memory_manager=mm,
            session_summary_manager=sm,
            telemetry=False,
        )

        os = AgentOS(agents=[agent], telemetry=False)
        os._populate_registry_managers()

        assert mm.owner_id == "a1"
        assert mm.owner_type == "agent"
        assert sm.owner_id == "a1"
        assert sm.owner_type == "agent"

    def test_owner_fields_default_to_none(self):
        """Owner fields are None on managers not registered through an owner."""
        mm = MemoryManager(id="mm-1")
        sm = SessionSummaryManager(id="sm-1")

        assert mm.owner_id is None
        assert mm.owner_type is None
        assert sm.owner_id is None
        assert sm.owner_type is None

    def test_dedupes_by_manager_id(self):
        """The same manager id is not added twice across repeated calls."""
        mm = MemoryManager(id="shared-mm")
        agent = Agent(name="A1", id="a1", memory_manager=mm, telemetry=False)

        os = AgentOS(agents=[agent], telemetry=False)
        os._populate_registry_managers()
        os._populate_registry_managers()

        ids = [m.id for m in os.registry.memory_managers]
        assert ids.count("shared-mm") == 1

    def test_distinct_managers_not_collapsed(self):
        """Two managers with different ids both end up in the registry."""
        mm1 = MemoryManager(id="mm-1")
        mm2 = MemoryManager(id="mm-2")
        a1 = Agent(name="A1", id="a1", memory_manager=mm1, telemetry=False)
        a2 = Agent(name="A2", id="a2", memory_manager=mm2, telemetry=False)

        os = AgentOS(agents=[a1, a2], telemetry=False)
        os._populate_registry_managers()

        assert os.registry.get_memory_manager_ids() == {"mm-1", "mm-2"}

    def test_no_managers_is_safe(self):
        """Agents without managers do not break population."""
        agent = Agent(name="A1", id="a1", telemetry=False)

        os = AgentOS(agents=[agent], telemetry=False)
        os._populate_registry_managers()

        assert os.registry.memory_managers == []
        assert os.registry.session_summary_managers == []

    def test_preexisting_registry_manager_is_preserved(self):
        """Managers passed directly via Registry are kept and not duplicated."""
        existing = MemoryManager(id="reg-mm")
        registry = Registry(memory_managers=[existing])
        agent = Agent(name="A1", id="a1", telemetry=False)

        os = AgentOS(agents=[agent], registry=registry, telemetry=False)
        os._populate_registry_managers()

        ids = [m.id for m in os.registry.memory_managers]
        assert ids.count("reg-mm") == 1


# =============================================================================
# _populate_registry_knowledge()
# =============================================================================


class TestPopulateRegistryKnowledge:
    """Tests for AgentOS._populate_registry_knowledge()."""

    def test_discovered_knowledge_added_to_registry(self, tmp_path):
        """Knowledge attached to an agent is copied into the registry."""
        db = SqliteDb(db_file=str(tmp_path / "kb.db"))
        kb = Knowledge(name="Docs KB", contents_db=db, vector_db=MagicMock())
        agent = Agent(name="A1", id="a1", knowledge=kb, telemetry=False)

        os = AgentOS(agents=[agent], telemetry=False)
        os._auto_discover_knowledge_instances()
        os._populate_registry_knowledge()

        assert any(getattr(k, "name", None) == "Docs KB" for k in os.registry.knowledge)

    def test_dedupes_by_knowledge_name(self, tmp_path):
        """Repeated population does not duplicate a knowledge instance by name."""
        db = SqliteDb(db_file=str(tmp_path / "kb.db"))
        kb = Knowledge(name="Docs KB", contents_db=db, vector_db=MagicMock())
        agent = Agent(name="A1", id="a1", knowledge=kb, telemetry=False)

        os = AgentOS(agents=[agent], telemetry=False)
        os._auto_discover_knowledge_instances()
        os._populate_registry_knowledge()
        os._populate_registry_knowledge()

        names = [getattr(k, "name", None) for k in os.registry.knowledge]
        assert names.count("Docs KB") == 1

    def test_knowledge_populated_after_init_without_get_app(self, tmp_path):
        """Knowledge is in the registry right after __init__ (before get_app/resync).

        Regression: early GET /registry?resource_type=knowledge must not be empty.
        """
        db = SqliteDb(db_file=str(tmp_path / "kb.db"))
        kb = Knowledge(name="Early KB", contents_db=db, vector_db=MagicMock())
        agent = Agent(name="A1", id="a1", knowledge=kb, telemetry=False)

        # Only construct AgentOS; do not call get_app() or resync().
        os = AgentOS(agents=[agent], telemetry=False)

        assert any(getattr(k, "name", None) == "Early KB" for k in os.registry.knowledge)


# =============================================================================
# Bidirectional knowledge: registry -> knowledge_instances
# =============================================================================


class TestBidirectionalKnowledge:
    """Knowledge passed only via Registry should still be discovered."""

    def test_registry_only_knowledge_is_discovered(self, tmp_path):
        """A Knowledge instance only in the registry surfaces in knowledge_instances."""
        db = SqliteDb(db_file=str(tmp_path / "kb.db"))
        kb = Knowledge(name="Registry KB", contents_db=db, vector_db=MagicMock())
        registry = Registry(knowledge=[kb])
        agent = Agent(name="A1", id="a1", telemetry=False)

        os = AgentOS(agents=[agent], registry=registry, telemetry=False)
        os._auto_discover_knowledge_instances()

        assert any(getattr(k, "name", None) == "Registry KB" for k in os.knowledge_instances)

    def test_registry_knowledge_without_contents_db_is_filtered(self, tmp_path):
        """Registry knowledge without a contents_db is not surfaced (existing filter)."""
        kb = Knowledge(name="No DB KB", vector_db=MagicMock())
        registry = Registry(knowledge=[kb])
        agent = Agent(name="A1", id="a1", telemetry=False)

        os = AgentOS(agents=[agent], registry=registry, telemetry=False)
        os._auto_discover_knowledge_instances()

        assert all(getattr(k, "name", None) != "No DB KB" for k in os.knowledge_instances)
