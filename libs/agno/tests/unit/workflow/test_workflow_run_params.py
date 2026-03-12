"""
Unit tests for Workflow run-level parameter resolution.

Tests cover:
- _resolve_run_params(): Merge and precedence logic for dependencies, metadata,
  and boolean context flags (add_dependencies_to_context, add_session_state_to_context)
- RunContext creation: Resolved params are correctly set on RunContext
- to_dict() / from_dict(): Round-trip serialization of new fields
- Precedence: Workflow-level deps take precedence over agent-level deps
  when both are set (full replacement, not merge)
"""

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from agno.run.base import RunContext
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def workflow_with_deps():
    """Workflow with class-level dependencies."""
    return Workflow(
        id="deps-workflow",
        name="Deps Workflow",
        dependencies={"db_url": "postgres://localhost", "api_version": "v2"},
    )


@pytest.fixture
def workflow_with_metadata():
    """Workflow with class-level metadata."""
    return Workflow(
        id="meta-workflow",
        name="Meta Workflow",
        metadata={"project": "blog", "version": "1.0"},
    )


@pytest.fixture
def workflow_with_all_params():
    """Workflow with all run-level params configured."""
    return Workflow(
        id="all-params-workflow",
        name="All Params Workflow",
        dependencies={"db_url": "postgres://localhost"},
        metadata={"project": "blog"},
        add_dependencies_to_context=True,
        add_session_state_to_context=True,
    )


# =============================================================================
# _resolve_run_params() — Dependencies
# =============================================================================


class TestResolveRunParamsDependencies:
    """Tests for dependency resolution precedence."""

    def test_no_deps_anywhere(self):
        """No deps on class or call-site returns None."""
        wf = Workflow(id="wf")
        resolved = wf._resolve_run_params()
        assert resolved["dependencies"] is None

    def test_class_level_only(self, workflow_with_deps):
        """Class-level deps returned when no call-site deps."""
        resolved = workflow_with_deps._resolve_run_params()
        assert resolved["dependencies"] == {"db_url": "postgres://localhost", "api_version": "v2"}

    def test_call_site_only(self):
        """Call-site deps returned when no class-level deps."""
        wf = Workflow(id="wf")
        resolved = wf._resolve_run_params(dependencies={"api_key": "sk-123"})
        assert resolved["dependencies"] == {"api_key": "sk-123"}

    def test_merge_call_site_wins_on_conflict(self, workflow_with_deps):
        """Call-site deps win on key conflicts when merged with class-level."""
        resolved = workflow_with_deps._resolve_run_params(
            dependencies={"api_version": "v3", "feature_flag": "new_ui"},
        )
        assert resolved["dependencies"]["api_version"] == "v3"  # call-site wins
        assert resolved["dependencies"]["db_url"] == "postgres://localhost"  # class-level preserved
        assert resolved["dependencies"]["feature_flag"] == "new_ui"  # call-site added

    def test_class_deps_not_mutated(self, workflow_with_deps):
        """Resolving deps does not mutate self.dependencies."""
        original = workflow_with_deps.dependencies.copy()
        workflow_with_deps._resolve_run_params(dependencies={"api_version": "v3"})
        assert workflow_with_deps.dependencies == original


# =============================================================================
# _resolve_run_params() — Metadata
# =============================================================================


class TestResolveRunParamsMetadata:
    """Tests for metadata resolution precedence."""

    def test_no_metadata_anywhere(self):
        """No metadata on class or call-site returns None."""
        wf = Workflow(id="wf")
        resolved = wf._resolve_run_params()
        assert resolved["metadata"] is None

    def test_class_level_only(self, workflow_with_metadata):
        """Class-level metadata returned when no call-site metadata."""
        resolved = workflow_with_metadata._resolve_run_params()
        assert resolved["metadata"] == {"project": "blog", "version": "1.0"}

    def test_call_site_only(self):
        """Call-site metadata returned when no class-level metadata."""
        wf = Workflow(id="wf")
        resolved = wf._resolve_run_params(metadata={"campaign": "launch"})
        assert resolved["metadata"] == {"campaign": "launch"}

    def test_merge_class_wins_on_conflict(self, workflow_with_metadata):
        """Class-level metadata wins on key conflicts (opposite of dependencies)."""
        resolved = workflow_with_metadata._resolve_run_params(
            metadata={"project": "docs", "campaign": "launch"},
        )
        assert resolved["metadata"]["project"] == "blog"  # class-level wins
        assert resolved["metadata"]["version"] == "1.0"  # class-level preserved
        assert resolved["metadata"]["campaign"] == "launch"  # call-site added

    def test_class_metadata_not_mutated(self, workflow_with_metadata):
        """Resolving metadata does not mutate self.metadata."""
        original = workflow_with_metadata.metadata.copy()
        workflow_with_metadata._resolve_run_params(metadata={"campaign": "launch"})
        assert workflow_with_metadata.metadata == original


# =============================================================================
# _resolve_run_params() — Boolean Flags
# =============================================================================


class TestResolveRunParamsBooleanFlags:
    """Tests for boolean flag resolution: call-site > self.<field> > None."""

    def test_defaults_to_none(self):
        """Flags default to None when not set anywhere."""
        wf = Workflow(id="wf")
        resolved = wf._resolve_run_params()
        assert resolved["add_dependencies_to_context"] is None
        assert resolved["add_session_state_to_context"] is None

    def test_class_level_flags(self, workflow_with_all_params):
        """Class-level flags returned when no call-site flags."""
        resolved = workflow_with_all_params._resolve_run_params()
        assert resolved["add_dependencies_to_context"] is True
        assert resolved["add_session_state_to_context"] is True

    def test_call_site_overrides_class(self, workflow_with_all_params):
        """Call-site flags override class-level flags."""
        resolved = workflow_with_all_params._resolve_run_params(
            add_dependencies_to_context=False,
            add_session_state_to_context=False,
        )
        assert resolved["add_dependencies_to_context"] is False
        assert resolved["add_session_state_to_context"] is False

    def test_call_site_false_overrides_class_true(self):
        """Explicit False at call-site overrides True on class."""
        wf = Workflow(id="wf", add_dependencies_to_context=True)
        resolved = wf._resolve_run_params(add_dependencies_to_context=False)
        assert resolved["add_dependencies_to_context"] is False

    def test_call_site_true_overrides_class_none(self):
        """Explicit True at call-site when class has None."""
        wf = Workflow(id="wf")
        resolved = wf._resolve_run_params(add_dependencies_to_context=True)
        assert resolved["add_dependencies_to_context"] is True


# =============================================================================
# to_dict() / from_dict() — Run-level params serialization
# =============================================================================


class TestRunParamsSerialization:
    """Tests for round-trip serialization of run-level params."""

    def test_to_dict_includes_dependencies(self, workflow_with_deps):
        """to_dict includes dependencies when set."""
        config = workflow_with_deps.to_dict()
        assert config["dependencies"] == {"db_url": "postgres://localhost", "api_version": "v2"}

    def test_to_dict_includes_context_flags(self, workflow_with_all_params):
        """to_dict includes boolean context flags when set."""
        config = workflow_with_all_params.to_dict()
        assert config["add_dependencies_to_context"] is True
        assert config["add_session_state_to_context"] is True

    def test_to_dict_omits_none_flags(self):
        """to_dict omits flags when they are None."""
        wf = Workflow(id="wf")
        config = wf.to_dict()
        assert "add_dependencies_to_context" not in config
        assert "add_session_state_to_context" not in config

    def test_to_dict_omits_none_dependencies(self):
        """to_dict omits dependencies when None."""
        wf = Workflow(id="wf")
        config = wf.to_dict()
        assert "dependencies" not in config

    def test_from_dict_restores_dependencies(self):
        """from_dict restores dependencies."""
        config = {
            "id": "wf",
            "name": "Test",
            "dependencies": {"db_url": "postgres://localhost"},
        }
        wf = Workflow.from_dict(config)
        assert wf.dependencies == {"db_url": "postgres://localhost"}

    def test_from_dict_restores_context_flags(self):
        """from_dict restores boolean context flags."""
        config = {
            "id": "wf",
            "name": "Test",
            "add_dependencies_to_context": True,
            "add_session_state_to_context": True,
        }
        wf = Workflow.from_dict(config)
        assert wf.add_dependencies_to_context is True
        assert wf.add_session_state_to_context is True

    def test_round_trip(self, workflow_with_all_params):
        """to_dict -> from_dict preserves all run-level params."""
        config = workflow_with_all_params.to_dict()
        restored = Workflow.from_dict(config)

        assert restored.dependencies == workflow_with_all_params.dependencies
        assert restored.metadata == workflow_with_all_params.metadata
        assert restored.add_dependencies_to_context == workflow_with_all_params.add_dependencies_to_context
        assert restored.add_session_state_to_context == workflow_with_all_params.add_session_state_to_context


# =============================================================================
# Workflow deps vs Agent deps precedence
# =============================================================================


class TestWorkflowAgentDepsPrecedence:
    """Tests verifying that workflow-level dependencies on RunContext
    take precedence over agent-level dependencies in apply_to_context.

    When a workflow sets run_context.dependencies, the agent's
    apply_to_context() sees run_context.dependencies is not None
    and skips overwriting — so workflow deps fully replace agent deps.
    """

    def test_workflow_deps_replace_agent_deps(self):
        """When workflow sets deps on RunContext, agent deps are not applied."""
        from agno.agent._run_options import ResolvedRunOptions

        # Simulate agent having its own resolved deps
        agent_options = ResolvedRunOptions(
            stream=False,
            stream_events=False,
            yield_run_output=False,
            add_history_to_context=False,
            add_dependencies_to_context=True,
            add_session_state_to_context=False,
            dependencies={"agent_key": "agent-value", "shared_key": "agent-wins"},
            knowledge_filters=None,
            metadata=None,
            output_schema=None,
        )

        # Workflow already set deps on run_context
        run_context = RunContext(
            run_id="run-1",
            session_id="sess-1",
            dependencies={"workflow_key": "wf-value", "shared_key": "wf-wins"},
        )

        # Agent apply_to_context with dependencies_provided=False
        # (this is what happens when step.py calls agent.run() — it does NOT
        # pass dependencies= kwarg, so dependencies_provided is False)
        agent_options.apply_to_context(
            run_context,
            dependencies_provided=False,
        )

        # Workflow deps are preserved, agent deps NOT merged
        assert run_context.dependencies == {"workflow_key": "wf-value", "shared_key": "wf-wins"}
        assert "agent_key" not in run_context.dependencies

    def test_no_workflow_deps_agent_deps_applied(self):
        """When workflow sets no deps, agent deps are applied as fallback."""
        from agno.agent._run_options import ResolvedRunOptions

        agent_options = ResolvedRunOptions(
            stream=False,
            stream_events=False,
            yield_run_output=False,
            add_history_to_context=False,
            add_dependencies_to_context=True,
            add_session_state_to_context=False,
            dependencies={"agent_key": "agent-value"},
            knowledge_filters=None,
            metadata=None,
            output_schema=None,
        )

        # Workflow did NOT set deps — run_context.dependencies is None
        run_context = RunContext(
            run_id="run-1",
            session_id="sess-1",
            dependencies=None,
        )

        agent_options.apply_to_context(
            run_context,
            dependencies_provided=False,
        )

        # Agent deps applied as fallback
        assert run_context.dependencies == {"agent_key": "agent-value"}

    def test_explicit_agent_run_deps_override_workflow(self):
        """When dependencies= is explicitly passed to agent.run(),
        it overrides workflow deps (dependencies_provided=True)."""
        from agno.agent._run_options import ResolvedRunOptions

        agent_options = ResolvedRunOptions(
            stream=False,
            stream_events=False,
            yield_run_output=False,
            add_history_to_context=False,
            add_dependencies_to_context=True,
            add_session_state_to_context=False,
            dependencies={"explicit_key": "explicit-value"},
            knowledge_filters=None,
            metadata=None,
            output_schema=None,
        )

        # Workflow set deps on run_context
        run_context = RunContext(
            run_id="run-1",
            session_id="sess-1",
            dependencies={"workflow_key": "wf-value"},
        )

        # dependencies_provided=True means agent.run(dependencies=...) was called explicitly
        agent_options.apply_to_context(
            run_context,
            dependencies_provided=True,
        )

        # Explicit deps override workflow deps
        assert run_context.dependencies == {"explicit_key": "explicit-value"}


# =============================================================================
# Same precedence pattern for metadata
# =============================================================================


class TestWorkflowAgentMetadataPrecedence:
    """Workflow metadata on RunContext vs agent metadata in apply_to_context."""

    def test_workflow_metadata_preserved(self):
        """When workflow sets metadata on RunContext, agent metadata is not applied."""
        from agno.agent._run_options import ResolvedRunOptions

        agent_options = ResolvedRunOptions(
            stream=False,
            stream_events=False,
            yield_run_output=False,
            add_history_to_context=False,
            add_dependencies_to_context=False,
            add_session_state_to_context=False,
            dependencies=None,
            knowledge_filters=None,
            metadata={"agent_tag": "agent-meta"},
            output_schema=None,
        )

        run_context = RunContext(
            run_id="run-1",
            session_id="sess-1",
            metadata={"workflow_tag": "wf-meta"},
        )

        agent_options.apply_to_context(run_context, metadata_provided=False)

        assert run_context.metadata == {"workflow_tag": "wf-meta"}
        assert "agent_tag" not in run_context.metadata

    def test_no_workflow_metadata_agent_applied(self):
        """When workflow sets no metadata, agent metadata is applied."""
        from agno.agent._run_options import ResolvedRunOptions

        agent_options = ResolvedRunOptions(
            stream=False,
            stream_events=False,
            yield_run_output=False,
            add_history_to_context=False,
            add_dependencies_to_context=False,
            add_session_state_to_context=False,
            dependencies=None,
            knowledge_filters=None,
            metadata={"agent_tag": "agent-meta"},
            output_schema=None,
        )

        run_context = RunContext(
            run_id="run-1",
            session_id="sess-1",
            metadata=None,
        )

        agent_options.apply_to_context(run_context, metadata_provided=False)

        assert run_context.metadata == {"agent_tag": "agent-meta"}
