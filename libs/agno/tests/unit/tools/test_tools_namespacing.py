"""
Unit tests for tool name and session state namespacing in KnowledgeTools, MemoryTools, and WorkflowTools.

Verifies that when multiple instances of the same toolkit are registered on an agent,
their tool names and session state keys don't collide. Also tests:
- sanitize_tool_name produces valid identifiers from arbitrary strings
- MemoryTools memory_name is keyword-only for backward compatibility
- WorkflowTools keeps think/analyze as exact names for _response.py detection
- _response.py helpers detect both exact and namespaced think/analyze tools
"""

from typing import Optional
from unittest.mock import MagicMock

from agno.tools.knowledge import KnowledgeTools
from agno.tools.memory import MemoryTools
from agno.tools.workflow import WorkflowTools
from agno.utils.string import sanitize_tool_name


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
# sanitize_tool_name
# ===========================================================================


class TestSanitizeToolName:
    def test_simple_name(self):
        assert sanitize_tool_name("memory") == "memory"

    def test_name_with_spaces(self):
        assert sanitize_tool_name("My Knowledge Base") == "my_knowledge_base"

    def test_name_with_punctuation(self):
        assert sanitize_tool_name("user's notes!") == "user_s_notes"

    def test_name_with_special_chars(self):
        assert sanitize_tool_name("docs@v2.0") == "docs_v2_0"

    def test_name_with_consecutive_underscores(self):
        assert sanitize_tool_name("a   b") == "a_b"

    def test_name_with_leading_trailing_underscores(self):
        assert sanitize_tool_name("  name  ") == "name"

    def test_name_with_hyphens_preserved(self):
        assert sanitize_tool_name("my-knowledge") == "my-knowledge"

    def test_empty_after_sanitize(self):
        assert sanitize_tool_name("!!!") == ""

    def test_already_valid(self):
        assert sanitize_tool_name("valid_name_123") == "valid_name_123"

    def test_camel_case_lowered(self):
        assert sanitize_tool_name("MyKnowledgeBase") == "myknowledgebase"


# ===========================================================================
# KnowledgeTools namespacing
# ===========================================================================


class TestKnowledgeToolsNamespacing:
    def test_tool_names_use_sanitized_knowledge_name(self):
        """Tool names should include the sanitized knowledge base name."""
        kt = KnowledgeTools(knowledge=_make_knowledge("Regulations"))
        registered_names = set(kt.functions.keys())
        assert "search_regulations" in registered_names
        assert "think_regulations" in registered_names
        assert "analyze_regulations" in registered_names

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
        assert kt._thoughts_key == "thoughts_regulations"
        assert kt._analysis_key == "analysis_regulations"

    def test_two_instances_have_distinct_session_keys(self):
        """Two KnowledgeTools should use different session state keys."""
        kt1 = KnowledgeTools(knowledge=_make_knowledge("Regulations"))
        kt2 = KnowledgeTools(knowledge=_make_knowledge("Workspace Docs"))
        assert kt1._thoughts_key != kt2._thoughts_key
        assert kt1._analysis_key != kt2._analysis_key

    def test_instructions_contain_actual_tool_names(self):
        """Instructions should reference the actual namespaced tool names."""
        kt = KnowledgeTools(knowledge=_make_knowledge("Regulations"))
        assert "search_regulations" in kt.instructions
        assert "think_regulations" in kt.instructions
        assert "analyze_regulations" in kt.instructions

    def test_toolkit_name_is_namespaced(self):
        """The toolkit name itself should be namespaced."""
        kt = KnowledgeTools(knowledge=_make_knowledge("Regulations"))
        assert kt.name == "regulations_tools"

    def test_selective_tool_registration(self):
        """Only enabled tools should be registered."""
        kt = KnowledgeTools(
            knowledge=_make_knowledge("Regulations"),
            enable_think=False,
            enable_search=True,
            enable_analyze=False,
        )
        registered_names = set(kt.functions.keys())
        assert "search_regulations" in registered_names
        assert "think_regulations" not in registered_names
        assert "analyze_regulations" not in registered_names

    def test_backwards_compatible_with_no_name(self):
        """Existing code passing knowledge without a name should still work."""
        kt = KnowledgeTools(knowledge=_make_knowledge(None))
        assert len(kt.functions) == 3  # think, search, analyze all registered
        assert kt.name == "knowledge_tools"

    def test_name_with_spaces_sanitized(self):
        """Names with spaces should be sanitized to valid identifiers."""
        kt = KnowledgeTools(knowledge=_make_knowledge("Regulations Knowledge Base"))
        registered_names = set(kt.functions.keys())
        assert "search_regulations_knowledge_base" in registered_names

    def test_name_with_punctuation_sanitized(self):
        """Names with punctuation should be sanitized."""
        kt = KnowledgeTools(knowledge=_make_knowledge("user's docs (v2)"))
        registered_names = set(kt.functions.keys())
        assert "search_user_s_docs_v2" in registered_names


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

    def test_memory_name_keyword_only(self):
        """memory_name must be keyword-only to preserve backward compatibility.

        MemoryTools(db, False, ...) should set enable_get_memories=False,
        NOT memory_name=False.
        """
        mt = MemoryTools(_make_db(), False)
        registered_names = set(mt.functions.keys())
        # get_memories should NOT be registered (enable_get_memories=False)
        assert "get_memories_memory" not in registered_names
        # think should still be there (default enabled)
        assert "think_memory" in registered_names

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

    def test_memory_name_with_spaces_sanitized(self):
        """Names with spaces should be sanitized."""
        mt = MemoryTools(db=_make_db(), memory_name="User Preferences!")
        registered_names = set(mt.functions.keys())
        assert "think_user_preferences" in registered_names
        assert "get_memories_user_preferences" in registered_names


# ===========================================================================
# WorkflowTools namespacing
# ===========================================================================


class TestWorkflowToolsNamespacing:
    def test_run_workflow_namespaced(self):
        """run_workflow tool name should include the workflow name."""
        wt = WorkflowTools(workflow=_make_workflow("data_pipeline"))
        registered_names = set(wt.functions.keys())
        assert "run_workflow_data_pipeline" in registered_names

    def test_think_analyze_not_namespaced(self):
        """think and analyze should keep exact names for _response.py detection."""
        wt = WorkflowTools(workflow=_make_workflow("data_pipeline"), enable_think=True, enable_analyze=True)
        registered_names = set(wt.functions.keys())
        assert "think" in registered_names
        assert "analyze" in registered_names
        # NOT namespaced
        assert "think_data_pipeline" not in registered_names
        assert "analyze_data_pipeline" not in registered_names

    def test_two_instances_have_distinct_run_tool_names(self):
        """Two WorkflowTools with different names should not collide on run_workflow."""
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
        assert "run_workflow_data_pipeline" in registered_names
        assert "think" not in registered_names
        assert "analyze" not in registered_names

    def test_workflow_name_sanitized(self):
        """Workflow names with special chars should be sanitized."""
        wt = WorkflowTools(workflow=_make_workflow("My Workflow (v2)!"))
        registered_names = set(wt.functions.keys())
        assert "run_workflow_my_workflow_v2" in registered_names


# ===========================================================================
# _response.py detection of namespaced think/analyze
# ===========================================================================


class TestResponseReasoningDetection:
    def test_is_think_tool_exact(self):
        from agno.agent._response import _is_think_tool

        assert _is_think_tool("think") is True
        assert _is_think_tool("Think") is True
        assert _is_think_tool("THINK") is True

    def test_is_think_tool_namespaced(self):
        from agno.agent._response import _is_think_tool

        assert _is_think_tool("think_memory") is True
        assert _is_think_tool("think_regulations_knowledge_base") is True
        assert _is_think_tool("Think_Prefs") is True

    def test_is_think_tool_negative(self):
        from agno.agent._response import _is_think_tool

        assert _is_think_tool("rethink") is False
        assert _is_think_tool("search_knowledge") is False
        assert _is_think_tool("thinking") is False

    def test_is_analyze_tool_exact(self):
        from agno.agent._response import _is_analyze_tool

        assert _is_analyze_tool("analyze") is True
        assert _is_analyze_tool("Analyze") is True

    def test_is_analyze_tool_namespaced(self):
        from agno.agent._response import _is_analyze_tool

        assert _is_analyze_tool("analyze_memory") is True
        assert _is_analyze_tool("analyze_regulations_knowledge_base") is True

    def test_is_analyze_tool_negative(self):
        from agno.agent._response import _is_analyze_tool

        assert _is_analyze_tool("reanalyze") is False
        assert _is_analyze_tool("analysis") is False

    def test_team_response_helpers_exist(self):
        from agno.team._response import _is_analyze_tool, _is_think_tool

        assert _is_think_tool("think_memory") is True
        assert _is_analyze_tool("analyze_kb") is True
