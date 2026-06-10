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
from agno.models.base import Model
from agno.os import AgentOS
from agno.registry import Registry
from agno.session.summary import SessionSummaryManager
from agno.team.team import Team
from agno.tools.toolkit import Toolkit
from agno.vectordb.base import VectorDb
from agno.workflow.condition import Condition
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


def _mock_model_class():
    """Build a concrete Model subclass with all abstract methods stubbed."""
    abstract_methods = {
        name: MagicMock() for name in dir(Model) if getattr(getattr(Model, name, None), "__isabstractmethod__", False)
    }
    return type("MockModel", (Model,), abstract_methods)


def _mock_vector_db_class():
    """Build a concrete VectorDb subclass with all abstract methods stubbed."""
    abstract_methods = {
        name: MagicMock()
        for name in dir(VectorDb)
        if getattr(getattr(VectorDb, name, None), "__isabstractmethod__", False)
    }
    return type("MockVectorDb", (VectorDb,), abstract_methods)


def _model(model_id, provider="openai"):
    """Create a mock model instance with the given id/provider."""
    model = _mock_model_class()(id=model_id)
    model.provider = provider
    return model


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


# =============================================================================
# _populate_registry_components()
# =============================================================================


def _model_keys(registry):
    return {(getattr(m, "provider", None), getattr(m, "id", None)) for m in registry.models}


def _tool_names(registry):
    return {getattr(t, "name", None) or getattr(t, "__name__", None) for t in registry.tools}


class TestPopulateRegistryComponentsAgents:
    """Components are discovered from agents."""

    def test_model_collected_from_agent(self):
        agent = Agent(name="A1", id="a1", model=_model("gpt-5.4"), telemetry=False)

        os = AgentOS(agents=[agent], telemetry=False)

        assert ("openai", "gpt-5.4") in _model_keys(os.registry)

    def test_reasoning_and_fallback_models_collected(self):
        agent = Agent(
            name="A1",
            id="a1",
            model=_model("gpt-5.4"),
            reasoning_model=_model("o5"),
            fallback_models=[_model("claude", provider="anthropic")],
            telemetry=False,
        )

        os = AgentOS(agents=[agent], telemetry=False)

        keys = _model_keys(os.registry)
        assert ("openai", "gpt-5.4") in keys
        assert ("openai", "o5") in keys
        assert ("anthropic", "claude") in keys

    def test_tool_collected_from_agent(self):
        def my_tool(x: str) -> str:
            """Echo."""
            return x

        agent = Agent(name="A1", id="a1", tools=[my_tool], telemetry=False)

        os = AgentOS(agents=[agent], telemetry=False)

        assert "my_tool" in _tool_names(os.registry)

    def test_db_collected_from_agent(self, tmp_path):
        db = SqliteDb(db_file=str(tmp_path / "a.db"), id="db-1")
        agent = Agent(name="A1", id="a1", db=db, telemetry=False)

        os = AgentOS(agents=[agent], telemetry=False)

        assert db in os.registry.dbs

    def test_vector_db_collected_from_knowledge(self, tmp_path):
        vector_db = _mock_vector_db_class()()
        contents_db = SqliteDb(db_file=str(tmp_path / "kb.db"))
        kb = Knowledge(name="KB", contents_db=contents_db, vector_db=vector_db)
        agent = Agent(name="A1", id="a1", knowledge=kb, telemetry=False)

        os = AgentOS(agents=[agent], telemetry=False)

        assert vector_db in os.registry.vector_dbs


class TestPopulateRegistryComponentsDedup:
    """Deduplication semantics during merge."""

    def test_shared_model_instance_collected_once(self):
        shared = _model("gpt-5.4")
        a1 = Agent(name="A1", id="a1", model=shared, telemetry=False)
        a2 = Agent(name="A2", id="a2", model=shared, telemetry=False)

        os = AgentOS(agents=[a1, a2], telemetry=False)

        gpt = [m for m in os.registry.models if m.id == "gpt-5.4"]
        assert len(gpt) == 1

    def test_distinct_instances_same_id_collapsed(self):
        a1 = Agent(name="A1", id="a1", model=_model("gpt-5.4"), telemetry=False)
        a2 = Agent(name="A2", id="a2", model=_model("gpt-5.4"), telemetry=False)

        os = AgentOS(agents=[a1, a2], telemetry=False)

        gpt = [m for m in os.registry.models if m.id == "gpt-5.4"]
        assert len(gpt) == 1

    def test_preexisting_registry_model_preserved_not_duplicated(self):
        existing = _model("gpt-5.4")
        registry = Registry(models=[existing])
        agent = Agent(name="A1", id="a1", model=_model("gpt-5.4"), telemetry=False)

        os = AgentOS(agents=[agent], registry=registry, telemetry=False)

        gpt = [m for m in os.registry.models if m.id == "gpt-5.4"]
        assert len(gpt) == 1
        assert existing in os.registry.models

    def test_idempotent_across_repeated_population(self):
        agent = Agent(name="A1", id="a1", model=_model("gpt-5.4"), telemetry=False)

        os = AgentOS(agents=[agent], telemetry=False)
        os._populate_registry_components()
        os._populate_registry_components()

        gpt = [m for m in os.registry.models if m.id == "gpt-5.4"]
        assert len(gpt) == 1


class TestPopulateRegistryComponentsNested:
    """Recursive traversal across teams and workflow step trees."""

    def test_nested_team_members_traversed(self):
        inner_agent = Agent(name="Inner", id="inner", model=_model("inner-model"), telemetry=False)
        inner_team = Team(name="Inner Team", id="it", members=[inner_agent], telemetry=False)
        outer_agent = Agent(name="Outer", id="outer", model=_model("outer-model"), telemetry=False)
        outer_team = Team(
            name="Outer Team",
            id="ot",
            members=[outer_agent, inner_team],
            model=_model("coordinator-model"),
            telemetry=False,
        )

        os = AgentOS(teams=[outer_team], telemetry=False)

        keys = _model_keys(os.registry)
        assert ("openai", "inner-model") in keys
        assert ("openai", "outer-model") in keys
        assert ("openai", "coordinator-model") in keys

    def test_workflow_condition_and_router_branches_traversed(self):
        # Each agent carries a uniquely-identifiable model so we can assert it
        # was reached through the corresponding branch/route.
        if_agent = Agent(name="If", id="if", model=_model("if-model"), telemetry=False)
        else_agent = Agent(name="Else", id="else", model=_model("else-model"), telemetry=False)
        route_agent = Agent(name="Route", id="route", model=_model("route-model"), telemetry=False)

        condition = Condition(
            steps=[Step(name="if-step", agent=if_agent)],
            else_steps=[Step(name="else-step", agent=else_agent)],
            evaluator=True,
        )
        router = Router(choices=[Step(name="route-step", agent=route_agent)], selector=lambda _: [])

        workflow = Workflow(name="WF", id="wf", steps=[condition, router])

        os = AgentOS(workflows=[workflow], telemetry=False)

        keys = _model_keys(os.registry)
        # The else branch and the router choices must not be missed
        assert ("openai", "if-model") in keys
        assert ("openai", "else-model") in keys
        assert ("openai", "route-model") in keys


class TestPopulateRegistryComponentsSafety:
    """The walk degrades gracefully and never breaks construction."""

    def test_agent_without_components_is_safe(self):
        # A model-less agent still receives a default model at init, which is
        # collected; it just has no tools, dbs or vector dbs.
        agent = Agent(name="A1", id="a1", telemetry=False)

        os = AgentOS(agents=[agent], telemetry=False)

        assert os.registry.tools == []
        assert os.registry.dbs == []
        assert os.registry.vector_dbs == []


class TestPopulateRegistryComponentsToolDedup:
    """Tools dedupe by object identity, never by name."""

    def test_distinct_tools_sharing_a_name_are_both_kept(self):
        # Two toolkit instances with the same name are distinct objects; keying
        # by name would silently drop one (and break rehydration of its agent).
        class _NamedToolkit(Toolkit):
            def __init__(self):
                super().__init__(name="shared_name", tools=[])

        toolkit_alpha = _NamedToolkit()
        toolkit_beta = _NamedToolkit()
        a = Agent(name="A1", id="a1", tools=[toolkit_alpha], telemetry=False)
        b = Agent(name="A2", id="a2", tools=[toolkit_beta], telemetry=False)

        os = AgentOS(agents=[a, b], telemetry=False)

        assert toolkit_alpha in os.registry.tools
        assert toolkit_beta in os.registry.tools

    def test_same_tool_instance_collected_once(self):
        # The same shared object across agents is collected a single time.
        shared_toolkit = Toolkit(name="shared", tools=[])
        a = Agent(name="A1", id="a1", tools=[shared_toolkit], telemetry=False)
        b = Agent(name="A2", id="a2", tools=[shared_toolkit], telemetry=False)

        os = AgentOS(agents=[a, b], telemetry=False)

        assert os.registry.tools.count(shared_toolkit) == 1


class TestPopulateRegistryComponentsCacheInvalidation:
    """The entrypoint lookup cache is rebuilt when discovered tools change."""

    def test_entrypoint_lookup_sees_tools_discovered_after_priming(self):
        def tool_a(x: str) -> str:
            """Tool A."""
            return x

        agent_a = Agent(name="A1", id="a1", tools=[tool_a], telemetry=False)
        os = AgentOS(agents=[agent_a], telemetry=False)

        # Prime (cache) the entrypoint lookup, as rehydrate_function() would
        assert "tool_a" in os.registry._entrypoint_lookup

        # A later resync discovers a new agent with a new tool
        def tool_b(x: str) -> str:
            """Tool B."""
            return x

        os.agents.append(Agent(name="A2", id="a2", tools=[tool_b], telemetry=False))
        os._populate_registry_components()

        # The cached lookup must have been invalidated and rebuilt with tool_b
        assert "tool_b" in os.registry._entrypoint_lookup
