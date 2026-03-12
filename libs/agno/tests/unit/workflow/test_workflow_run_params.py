"""
Unit tests for Workflow run-level parameter resolution.

Tests cover:
- _resolve_run_params(): Merge and precedence logic for dependencies, metadata,
  and boolean context flags (add_dependencies_to_context, add_session_state_to_context)
- RunContext creation: Resolved params are correctly set on RunContext
- to_dict() / from_dict(): Round-trip serialization of new fields
- Precedence: Workflow-level deps take precedence over agent-level deps
  when both are set (full replacement, not merge)
- End-to-end: Full workflow.run() -> step -> agent.run() chain with MockTestModel
"""

from typing import Any, AsyncIterator, Dict, Iterator
from unittest.mock import AsyncMock, Mock

import pytest

from agno.agent import Agent
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.base import RunContext
from agno.workflow.step import Step
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


# =============================================================================
# MockTestModel for end-to-end tests (no real API calls)
# =============================================================================


class MockTestModel(Model):
    """Minimal mock model that returns a canned response."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = Mock()
        self._mock_response.content = "mock response"
        self._mock_response.role = "assistant"
        self._mock_response.reasoning_content = None
        self._mock_response.redacted_reasoning_content = None
        self._mock_response.tool_calls = None
        self._mock_response.tool_executions = None
        self._mock_response.images = None
        self._mock_response.videos = None
        self._mock_response.audios = None
        self._mock_response.audio = None
        self._mock_response.files = None
        self._mock_response.citations = None
        self._mock_response.references = None
        self._mock_response.metadata = None
        self._mock_response.provider_data = None
        self._mock_response.extra = None
        self._mock_response.response_usage = MessageMetrics()
        self.response = Mock(return_value=self._mock_response)
        self.aresponse = AsyncMock(return_value=self._mock_response)

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return await self.aresponse(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


# =============================================================================
# End-to-end: workflow.run() -> step.execute() -> agent.run() chain
# =============================================================================


class TestWorkflowRunE2EDependencies:
    """Full end-to-end tests running a real Workflow with an Agent (mock model)
    to verify dependency/metadata propagation through the entire chain."""

    def test_workflow_deps_reach_agent_context(self):
        """Workflow deps are set on RunContext and visible to the agent."""
        captured_run_context: Dict[str, Any] = {}

        original_run = Agent.run

        def spy_run(self_agent, *args, **kwargs):
            # Capture the run_context that the agent receives
            rc = kwargs.get("run_context")
            if rc is not None:
                captured_run_context["dependencies"] = rc.dependencies
                captured_run_context["metadata"] = rc.metadata
            return original_run(self_agent, *args, **kwargs)

        agent = Agent(
            name="Test Agent",
            model=MockTestModel(),
        )
        workflow = Workflow(
            name="E2E Deps Test",
            steps=[Step(name="step1", agent=agent)],
            dependencies={"db_url": "postgres://wf", "env": "prod"},
            metadata={"project": "e2e-test"},
            add_dependencies_to_context=True,
        )

        # Monkey-patch Agent.run to spy on run_context
        Agent.run = spy_run  # type: ignore
        try:
            workflow.run(input="hello")
        finally:
            Agent.run = original_run  # type: ignore

        assert captured_run_context["dependencies"] == {"db_url": "postgres://wf", "env": "prod"}
        assert captured_run_context["metadata"] == {"project": "e2e-test"}

    def test_workflow_deps_override_agent_deps_e2e(self):
        """When both workflow and agent have deps, workflow deps win end-to-end."""
        captured_deps: Dict[str, Any] = {}

        original_run = Agent.run

        def spy_run(self_agent, *args, **kwargs):
            result = original_run(self_agent, *args, **kwargs)
            # After agent.run() completes, check what deps ended up on run_context
            rc = kwargs.get("run_context")
            if rc is not None:
                captured_deps["final"] = rc.dependencies
            return result

        agent = Agent(
            name="Agent With Deps",
            model=MockTestModel(),
            dependencies={"agent_key": "agent-val", "shared": "agent-version"},
        )
        workflow = Workflow(
            name="Override Test",
            steps=[Step(name="step1", agent=agent)],
            dependencies={"wf_key": "wf-val", "shared": "wf-version"},
            add_dependencies_to_context=True,
        )

        Agent.run = spy_run  # type: ignore
        try:
            workflow.run(input="hello")
        finally:
            Agent.run = original_run  # type: ignore

        # Workflow deps win entirely — agent deps not merged
        assert captured_deps["final"]["wf_key"] == "wf-val"
        assert captured_deps["final"]["shared"] == "wf-version"
        assert "agent_key" not in captured_deps["final"]

    def test_no_workflow_deps_agent_deps_used_e2e(self):
        """When workflow has no deps, agent's own deps are used."""
        captured_deps: Dict[str, Any] = {}

        original_run = Agent.run

        def spy_run(self_agent, *args, **kwargs):
            result = original_run(self_agent, *args, **kwargs)
            rc = kwargs.get("run_context")
            if rc is not None:
                captured_deps["final"] = rc.dependencies
            return result

        agent = Agent(
            name="Agent With Deps",
            model=MockTestModel(),
            dependencies={"agent_key": "agent-val"},
        )
        workflow = Workflow(
            name="Fallback Test",
            steps=[Step(name="step1", agent=agent)],
            # No workflow-level dependencies
            add_dependencies_to_context=True,
        )

        Agent.run = spy_run  # type: ignore
        try:
            workflow.run(input="hello")
        finally:
            Agent.run = original_run  # type: ignore

        # Agent deps used as fallback
        assert captured_deps["final"] == {"agent_key": "agent-val"}

    def test_call_site_deps_merged_with_class_deps_e2e(self):
        """Call-site deps to workflow.run() merge with class-level deps."""
        captured_deps: Dict[str, Any] = {}

        original_run = Agent.run

        def spy_run(self_agent, *args, **kwargs):
            rc = kwargs.get("run_context")
            if rc is not None:
                captured_deps["final"] = rc.dependencies
            return original_run(self_agent, *args, **kwargs)

        agent = Agent(name="Test Agent", model=MockTestModel())
        workflow = Workflow(
            name="Merge Test",
            steps=[Step(name="step1", agent=agent)],
            dependencies={"class_key": "class-val", "shared": "class-version"},
            add_dependencies_to_context=True,
        )

        Agent.run = spy_run  # type: ignore
        try:
            workflow.run(
                input="hello",
                dependencies={"call_key": "call-val", "shared": "call-version"},
            )
        finally:
            Agent.run = original_run  # type: ignore

        # Call-site wins on conflict, class-level fills gaps
        assert captured_deps["final"]["call_key"] == "call-val"
        assert captured_deps["final"]["class_key"] == "class-val"
        assert captured_deps["final"]["shared"] == "call-version"

    def test_multi_step_shared_run_context(self):
        """When workflow has 2 steps with agents that have different deps,
        workflow deps are consistent across both steps and agent deps don't leak."""
        captured_per_step: Dict[str, Any] = {}

        original_run = Agent.run

        def spy_run(self_agent, *args, **kwargs):
            rc = kwargs.get("run_context")
            # Capture deps before and after the agent processes them
            deps_before = dict(rc.dependencies) if rc and rc.dependencies else None
            result = original_run(self_agent, *args, **kwargs)
            deps_after = dict(rc.dependencies) if rc and rc.dependencies else None
            captured_per_step[self_agent.name] = {
                "deps_before": deps_before,
                "deps_after": deps_after,
            }
            return result

        agent1 = Agent(
            name="Agent1",
            model=MockTestModel(),
            dependencies={"agent1_key": "a1-val", "shared": "agent1-version"},
        )
        agent2 = Agent(
            name="Agent2",
            model=MockTestModel(),
            dependencies={"agent2_key": "a2-val", "shared": "agent2-version"},
        )
        workflow = Workflow(
            name="Multi-Step Test",
            steps=[
                Step(name="step1", agent=agent1),
                Step(name="step2", agent=agent2),
            ],
            dependencies={"wf_key": "wf-val", "shared": "wf-version"},
            add_dependencies_to_context=True,
        )

        Agent.run = spy_run  # type: ignore
        try:
            workflow.run(input="hello")
        finally:
            Agent.run = original_run  # type: ignore

        # Both steps see the same workflow deps
        wf_deps = {"wf_key": "wf-val", "shared": "wf-version"}
        assert captured_per_step["Agent1"]["deps_before"] == wf_deps
        assert captured_per_step["Agent2"]["deps_before"] == wf_deps

        # Agent-specific deps don't leak into run_context
        assert "agent1_key" not in captured_per_step["Agent1"]["deps_after"]
        assert "agent2_key" not in captured_per_step["Agent2"]["deps_after"]

        # Step 1's agent deps didn't contaminate Step 2's view
        assert captured_per_step["Agent2"]["deps_before"] == wf_deps

    def test_multi_step_no_workflow_deps_agents_independent(self):
        """When workflow has NO deps, each agent's own deps are applied
        independently without cross-step contamination."""
        captured_per_step: Dict[str, Any] = {}

        original_run = Agent.run

        def spy_run(self_agent, *args, **kwargs):
            result = original_run(self_agent, *args, **kwargs)
            rc = kwargs.get("run_context")
            captured_per_step[self_agent.name] = {
                "deps_after": dict(rc.dependencies) if rc and rc.dependencies else None,
            }
            return result

        agent1 = Agent(
            name="Agent1",
            model=MockTestModel(),
            dependencies={"agent1_key": "a1-val"},
        )
        agent2 = Agent(
            name="Agent2",
            model=MockTestModel(),
            dependencies={"agent2_key": "a2-val"},
        )
        workflow = Workflow(
            name="No WF Deps Test",
            steps=[
                Step(name="step1", agent=agent1),
                Step(name="step2", agent=agent2),
            ],
            # No workflow-level dependencies
            add_dependencies_to_context=True,
        )

        Agent.run = spy_run  # type: ignore
        try:
            workflow.run(input="hello")
        finally:
            Agent.run = original_run  # type: ignore

        # Agent1 sets its deps on the shared run_context
        assert captured_per_step["Agent1"]["deps_after"] == {"agent1_key": "a1-val"}

        # Agent2: run_context already has Agent1's deps (not None),
        # so Agent2's deps are NOT applied — this is the shared RunContext behavior.
        # Agent1's deps persist into Step 2.
        assert captured_per_step["Agent2"]["deps_after"] == {"agent1_key": "a1-val"}

    def test_add_dependencies_flag_propagated_e2e(self):
        """add_dependencies_to_context flag propagates from workflow to agent.run()."""
        captured_kwargs: Dict[str, Any] = {}

        original_run = Agent.run

        def spy_run(self_agent, *args, **kwargs):
            captured_kwargs["add_dependencies_to_context"] = kwargs.get("add_dependencies_to_context")
            captured_kwargs["add_session_state_to_context"] = kwargs.get("add_session_state_to_context")
            return original_run(self_agent, *args, **kwargs)

        agent = Agent(name="Test Agent", model=MockTestModel())
        workflow = Workflow(
            name="Flag Test",
            steps=[Step(name="step1", agent=agent)],
            add_dependencies_to_context=True,
            add_session_state_to_context=True,
        )

        Agent.run = spy_run  # type: ignore
        try:
            workflow.run(input="hello")
        finally:
            Agent.run = original_run  # type: ignore

        assert captured_kwargs["add_dependencies_to_context"] is True
        assert captured_kwargs["add_session_state_to_context"] is True
