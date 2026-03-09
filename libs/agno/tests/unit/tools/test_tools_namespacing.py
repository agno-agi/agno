"""
Unit tests for tool name and session state namespacing in KnowledgeTools, MemoryTools, and WorkflowTools.

Verifies that when multiple instances of the same toolkit are registered on an agent,
their tool names and session state keys don't collide.
"""

from typing import Optional
from unittest.mock import MagicMock

from agno.tools.knowledge import KnowledgeTools
from agno.tools.memory import MemoryTools
from agno.tools.workflow import WorkflowTools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_knowledge(name: Optional[str] = None) -> MagicMock:
    """Create a mock Knowledge with the given name."""
    kb = MagicMock()
    kb.name = name
    return kb


def _make_workflow(name: str = "my_workflow") -> MagicMock:
    """Create a mock Workflow with the given name."""
    wf = MagicMock()
    wf.name = name
    return wf


def _make_db() -> MagicMock:
    """Create a mock DB for MemoryTools."""
    return MagicMock()


# ===========================================================================
# KnowledgeTools namespacing
# ===========================================================================


class TestKnowledgeToolsNamespacing:
    def test_tool_names_use_knowledge_name(self):
        """Tool names should include the knowledge base name."""
        kt = KnowledgeTools(knowledge=_make_knowledge("Regulations"))
        registered_names = set(kt.functions.keys())
        assert "search_Regulations" in registered_names
        assert "think_Regulations" in registered_names
        assert "analyze_Regulations" in registered_names

    def test_default_name_when_knowledge_name_is_none(self):
        """When knowledge.name is None, fall back to 'knowledge'."""
        kt = KnowledgeTools(knowledge=_make_knowledge(None))
        registered_names = set(kt.functions.keys())
        assert "search_knowledge" in registered_names

    def test_two_instances_have_distinct_tool_names(self):
        """Two KnowledgeTools with different names should register different tool names."""
        kt1 = KnowledgeTools(knowledge=_make_knowledge("Regulations"))
        kt2 = KnowledgeTools(knowledge=_make_knowledge("Workspace Docs"))

        names1 = set(kt1.functions.keys())
        names2 = set(kt2.functions.keys())
        assert names1.isdisjoint(names2), f"Tool name collision: {names1 & names2}"

    def test_session_state_keys_are_namespaced(self):
        """Session state keys should be namespaced to avoid collisions."""
        kt = KnowledgeTools(knowledge=_make_knowledge("Regulations"))
        assert kt._thoughts_key == "thoughts_Regulations"
        assert kt._analysis_key == "analysis_Regulations"

    def test_two_instances_have_distinct_session_keys(self):
        """Two KnowledgeTools should use different session state keys."""
        kt1 = KnowledgeTools(knowledge=_make_knowledge("Regulations"))
        kt2 = KnowledgeTools(knowledge=_make_knowledge("Workspace Docs"))
        assert kt1._thoughts_key != kt2._thoughts_key
        assert kt1._analysis_key != kt2._analysis_key

    def test_instructions_contain_actual_tool_names(self):
        """Instructions should reference the actual namespaced tool names."""
        kt = KnowledgeTools(knowledge=_make_knowledge("Regulations"))
        assert "search_Regulations" in kt.instructions
        assert "think_Regulations" in kt.instructions
        assert "analyze_Regulations" in kt.instructions

    def test_toolkit_name_is_namespaced(self):
        """The toolkit name itself should be namespaced."""
        kt = KnowledgeTools(knowledge=_make_knowledge("Regulations"))
        assert kt.name == "Regulations_tools"

    def test_selective_tool_registration(self):
        """Only enabled tools should be registered."""
        kt = KnowledgeTools(
            knowledge=_make_knowledge("Regulations"),
            enable_think=False,
            enable_search=True,
            enable_analyze=False,
        )
        registered_names = set(kt.functions.keys())
        assert "search_Regulations" in registered_names
        assert "think_Regulations" not in registered_names
        assert "analyze_Regulations" not in registered_names

    def test_backwards_compatible_with_no_name(self):
        """Existing code passing knowledge without a name should still work."""
        kt = KnowledgeTools(knowledge=_make_knowledge(None))
        assert len(kt.functions) == 3  # think, search, analyze all registered
        assert kt.name == "knowledge_tools"


# ===========================================================================
# MemoryTools namespacing
# ===========================================================================


class TestMemoryToolsNamespacing:
    def test_tool_names_use_memory_name(self):
        """Tool names should include the memory name."""
        mt = MemoryTools(db=_make_db(), memory_name="user_prefs")
        registered_names = set(mt.functions.keys())
        assert "think_user_prefs" in registered_names
        assert "get_memories_user_prefs" in registered_names
        assert "add_memory_user_prefs" in registered_names
        assert "update_memory_user_prefs" in registered_names
        assert "delete_memory_user_prefs" in registered_names
        assert "analyze_user_prefs" in registered_names

    def test_default_memory_name(self):
        """Default memory_name should be 'memory' for backwards compatibility."""
        mt = MemoryTools(db=_make_db())
        registered_names = set(mt.functions.keys())
        assert "get_memories_memory" in registered_names
        assert mt.name == "memory_tools"

    def test_two_instances_have_distinct_tool_names(self):
        """Two MemoryTools with different names should not collide."""
        mt1 = MemoryTools(db=_make_db(), memory_name="user_prefs")
        mt2 = MemoryTools(db=_make_db(), memory_name="conversation")

        names1 = set(mt1.functions.keys())
        names2 = set(mt2.functions.keys())
        assert names1.isdisjoint(names2), f"Tool name collision: {names1 & names2}"

    def test_session_state_keys_are_namespaced(self):
        """Session state keys should be namespaced."""
        mt = MemoryTools(db=_make_db(), memory_name="user_prefs")
        assert mt._thoughts_key == "memory_thoughts_user_prefs"
        assert mt._operations_key == "memory_operations_user_prefs"
        assert mt._analysis_key == "memory_analysis_user_prefs"

    def test_instructions_contain_actual_tool_names(self):
        """Instructions should reference the actual namespaced tool names."""
        mt = MemoryTools(db=_make_db(), memory_name="user_prefs")
        assert "think_user_prefs" in mt.instructions
        assert "get_memories_user_prefs" in mt.instructions
        assert "add_memory_user_prefs" in mt.instructions

    def test_selective_tool_registration(self):
        """Only enabled tools should be registered."""
        mt = MemoryTools(
            db=_make_db(),
            memory_name="user_prefs",
            enable_think=False,
            enable_get_memories=True,
            enable_add_memory=True,
            enable_update_memory=False,
            enable_delete_memory=False,
            enable_analyze=False,
        )
        registered_names = set(mt.functions.keys())
        assert "get_memories_user_prefs" in registered_names
        assert "add_memory_user_prefs" in registered_names
        assert "think_user_prefs" not in registered_names
        assert "update_memory_user_prefs" not in registered_names


# ===========================================================================
# WorkflowTools namespacing
# ===========================================================================


class TestWorkflowToolsNamespacing:
    def test_tool_names_use_workflow_name(self):
        """Tool names should include the workflow name."""
        wt = WorkflowTools(workflow=_make_workflow("data_pipeline"), all=True)
        registered_names = set(wt.functions.keys())
        assert "think_data_pipeline" in registered_names
        assert "run_data_pipeline" in registered_names
        assert "analyze_data_pipeline" in registered_names

    def test_two_instances_have_distinct_tool_names(self):
        """Two WorkflowTools with different names should not collide."""
        wt1 = WorkflowTools(workflow=_make_workflow("data_pipeline"))
        wt2 = WorkflowTools(workflow=_make_workflow("report_gen"))

        names1 = set(wt1.functions.keys())
        names2 = set(wt2.functions.keys())
        assert names1.isdisjoint(names2), f"Tool name collision: {names1 & names2}"

    def test_session_state_keys_are_namespaced(self):
        """Session state keys should be namespaced."""
        wt = WorkflowTools(workflow=_make_workflow("data_pipeline"))
        assert wt._thoughts_key == "workflow_thoughts_data_pipeline"
        assert wt._results_key == "workflow_results_data_pipeline"
        assert wt._analysis_key == "workflow_analysis_data_pipeline"

    def test_instructions_contain_actual_tool_names(self):
        """Instructions should reference the actual namespaced tool names."""
        wt = WorkflowTools(workflow=_make_workflow("data_pipeline"))
        assert "think_data_pipeline" in wt.instructions
        assert "run_data_pipeline" in wt.instructions
        assert "analyze_data_pipeline" in wt.instructions

    def test_toolkit_name_is_namespaced(self):
        """The toolkit name itself should be namespaced."""
        wt = WorkflowTools(workflow=_make_workflow("data_pipeline"))
        assert wt.name == "data_pipeline_tools"

    def test_selective_tool_registration(self):
        """Only enabled tools should be registered."""
        wt = WorkflowTools(
            workflow=_make_workflow("data_pipeline"),
            enable_think=False,
            enable_run_workflow=True,
            enable_analyze=False,
        )
        registered_names = set(wt.functions.keys())
        assert "run_data_pipeline" in registered_names
        assert "think_data_pipeline" not in registered_names
        assert "analyze_data_pipeline" not in registered_names
