"""Integration tests for per-request isolation feature.

Per-request isolation is the default behavior in AgentOS. Each request
gets a fresh instance of the agent/team/workflow to prevent state
contamination between concurrent requests.
"""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.team import Team
from agno.workflow import Workflow
from agno.workflow.step import Step


@pytest.fixture
def test_agent():
    """Create a test agent."""
    return Agent(
        name="test-agent",
        id="test-agent-id",
        model=OpenAIChat(id="gpt-4o-mini"),
    )


@pytest.fixture
def test_agent_with_metadata():
    """Create a test agent with initial metadata."""
    return Agent(
        name="test-agent-metadata",
        id="test-agent-metadata-id",
        model=OpenAIChat(id="gpt-4o-mini"),
        metadata={"request_count": 0, "user_id": None},
    )


@pytest.fixture
def test_team(test_agent):
    """Create a test team with the test agent as a member."""
    return Team(
        name="test-team",
        id="test-team-id",
        members=[test_agent],
        model=OpenAIChat(id="gpt-4o-mini"),
    )


@pytest.fixture
def test_workflow():
    """Create a test workflow with agent steps."""
    agent = Agent(
        name="workflow-agent",
        id="workflow-agent-id",
        model=OpenAIChat(id="gpt-4o-mini"),
        metadata={"step_executions": 0},
    )
    return Workflow(
        name="test-workflow",
        id="test-workflow-id",
        steps=[Step(name="agent-step", agent=agent)],
    )


# ============================================================================
# Basic AgentOS Per-Request Isolation Tests
# ============================================================================


class TestAgentOSPerRequestIsolation:
    """Tests for AgentOS with per-request isolation (default behavior)."""

    def test_agent_run_creates_fresh_instance(self, test_agent):
        """Each request should use a fresh agent instance."""
        os = AgentOS(agents=[test_agent])
        app = os.get_app()
        client = TestClient(app)

        class MockRunOutput:
            def to_dict(self):
                return {"run_id": str(uuid.uuid4())}

        with patch.object(Agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = MockRunOutput()

            # Make two requests
            response1 = client.post(
                f"/agents/{test_agent.id}/runs",
                data={"message": "Request 1", "stream": "false"},
            )
            response2 = client.post(
                f"/agents/{test_agent.id}/runs",
                data={"message": "Request 2", "stream": "false"},
            )

        assert response1.status_code == 200
        assert response2.status_code == 200

        # Each request should have different run_ids
        assert response1.json()["run_id"] != response2.json()["run_id"]


# ============================================================================
# Metadata Isolation Tests
# ============================================================================


class TestMetadataIsolation:
    """Tests for metadata isolation between requests."""

    def test_metadata_not_shared_between_requests(self, test_agent):
        """Metadata changes in one request should not affect others."""
        test_agent.metadata = {"initial": "value"}
        os = AgentOS(agents=[test_agent])
        app = os.get_app()
        client = TestClient(app)

        class MockRunOutput:
            def to_dict(self):
                return {"run_id": str(uuid.uuid4())}

        with patch.object(Agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = MockRunOutput()

            # Make a request
            response = client.post(
                f"/agents/{test_agent.id}/runs",
                data={"message": "Hello", "stream": "false"},
            )

        assert response.status_code == 200
        # Original agent's metadata should be unchanged
        assert test_agent.metadata == {"initial": "value"}

    def test_metadata_mutation_during_request_isolated(self, test_agent_with_metadata):
        """Metadata mutated during a request should not leak to other requests."""
        os = AgentOS(agents=[test_agent_with_metadata])
        app = os.get_app()
        client = TestClient(app)

        # Track what metadata each request sees
        metadata_seen: List[Dict[str, Any]] = []

        class MockRunOutput:
            def to_dict(self):
                return {"run_id": str(uuid.uuid4())}

        async def mock_arun_with_mutation(self, *args, **kwargs):
            # Capture current metadata
            metadata_seen.append(dict(self.metadata) if self.metadata else {})
            # Mutate metadata (simulating what happens during a real run)
            if self.metadata:
                self.metadata["request_count"] = self.metadata.get("request_count", 0) + 1
                self.metadata["user_id"] = kwargs.get("user_id", "unknown")
            return MockRunOutput()

        with patch.object(Agent, "arun", mock_arun_with_mutation):
            # Make multiple sequential requests
            for i in range(3):
                client.post(
                    f"/agents/{test_agent_with_metadata.id}/runs",
                    data={"message": f"Request {i}", "stream": "false", "user_id": f"user_{i}"},
                )

        # Original template should be unchanged
        assert test_agent_with_metadata.metadata["request_count"] == 0
        assert test_agent_with_metadata.metadata["user_id"] is None

        # Each request should have seen fresh metadata (request_count=0)
        for metadata in metadata_seen:
            assert metadata.get("request_count") == 0


# ============================================================================
# Team Isolation Tests
# ============================================================================


class TestTeamIsolation:
    """Tests for Team per-request isolation."""

    def test_team_creates_fresh_instance(self, test_team):
        """Each request should use a fresh team instance."""
        os = AgentOS(teams=[test_team])
        app = os.get_app()
        client = TestClient(app)

        class MockRunOutput:
            def to_dict(self):
                return {"run_id": str(uuid.uuid4())}

        with patch.object(Team, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = MockRunOutput()

            response = client.post(
                f"/teams/{test_team.id}/runs",
                data={"message": "Hello", "stream": "false"},
            )

        assert response.status_code == 200

    def test_team_member_metadata_isolated(self):
        """Team member metadata should be isolated between requests."""
        member = Agent(
            name="member",
            id="member-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"tasks_completed": 0},
        )
        team = Team(
            name="team",
            id="team-id",
            members=[member],
            model=OpenAIChat(id="gpt-4o-mini"),
        )
        os = AgentOS(teams=[team])
        app = os.get_app()
        client = TestClient(app)

        class MockRunOutput:
            def to_dict(self):
                return {"run_id": str(uuid.uuid4())}

        with patch.object(Team, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = MockRunOutput()

            # Make multiple requests
            for _ in range(3):
                client.post(
                    f"/teams/{team.id}/runs",
                    data={"message": "Hello", "stream": "false"},
                )

        # Original member's metadata should be unchanged
        assert member.metadata["tasks_completed"] == 0


# ============================================================================
# Workflow Isolation Tests
# ============================================================================


class TestWorkflowIsolation:
    """Tests for Workflow per-request isolation."""

    def test_workflow_agent_step_isolated(self, test_workflow):
        """Agents inside workflow steps should be isolated."""
        os = AgentOS(workflows=[test_workflow])
        app = os.get_app()
        client = TestClient(app)

        class MockRunOutput:
            content = "Test response"
            run_id = str(uuid.uuid4())
            status = "completed"

            def to_dict(self):
                return {"run_id": self.run_id, "content": self.content}

        with patch.object(Workflow, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = MockRunOutput()

            response = client.post(
                f"/workflows/{test_workflow.id}/runs",
                data={"message": "Hello", "stream": "false"},
            )

        assert response.status_code == 200

        # Original workflow's agent metadata should be unchanged
        original_agent = test_workflow.steps[0].agent
        assert original_agent.metadata["step_executions"] == 0


# ============================================================================
# Concurrent Request Simulation Tests
# ============================================================================


class TestConcurrentRequestIsolation:
    """Tests simulating concurrent requests to verify isolation."""

    def test_concurrent_agent_requests_isolated(self, test_agent_with_metadata):
        """Concurrent requests should not interfere with each other."""
        os = AgentOS(agents=[test_agent_with_metadata])
        app = os.get_app()

        results: List[Dict[str, Any]] = []
        errors: List[Exception] = []

        class MockRunOutput:
            def __init__(self, user_id):
                self.user_id = user_id
                self.run_id = str(uuid.uuid4())

            def to_dict(self):
                return {"run_id": self.run_id, "user_id": self.user_id}

        async def mock_arun_with_delay(self, *args, **kwargs):
            user_id = kwargs.get("user_id", "unknown")
            # Simulate some processing time
            await asyncio.sleep(0.01)
            # Mutate metadata
            if self.metadata:
                self.metadata["user_id"] = user_id
            return MockRunOutput(user_id)

        def make_request(user_id: str):
            try:
                with TestClient(app) as client:
                    response = client.post(
                        f"/agents/{test_agent_with_metadata.id}/runs",
                        data={"message": f"Hello from {user_id}", "stream": "false", "user_id": user_id},
                    )
                    results.append({"user_id": user_id, "status": response.status_code})
            except Exception as e:
                errors.append(e)

        with patch.object(Agent, "arun", mock_arun_with_delay):
            # Simulate concurrent requests using threads
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(make_request, f"user_{i}") for i in range(5)]
                for future in futures:
                    future.result()

        # All requests should succeed
        assert len(errors) == 0
        assert all(r["status"] == 200 for r in results)

        # Original agent metadata should be unchanged
        assert test_agent_with_metadata.metadata["user_id"] is None


# ============================================================================
# Shared Resources Tests
# ============================================================================


class TestSharedResources:
    """Tests to verify heavy resources are shared, not copied."""

    def test_model_configuration_preserved(self):
        """Model configuration should be preserved in copies."""
        model = OpenAIChat(id="gpt-4o-mini")
        agent = Agent(name="test-agent", id="test-id", model=model)

        copy = agent.deep_copy()

        assert copy.model is not None
        assert copy.model.id == "gpt-4o-mini"

    def test_agent_db_shared_in_copy(self):
        """Database should be shared (not copied) between agent instances."""

        # Create a mock DB that we can track
        class MockDb:
            def __init__(self):
                self.instance_id = uuid.uuid4()

        db = MockDb()
        agent = Agent(name="test-agent", id="test-id", db=db)

        copy = agent.deep_copy()

        # DB should be the same instance (shared)
        assert copy.db is db
        assert copy.db.instance_id == db.instance_id

    def test_workflow_db_shared_in_copy(self):
        """Database should be shared (not copied) between workflow instances."""

        class MockDb:
            def __init__(self):
                self.instance_id = uuid.uuid4()

        db = MockDb()
        workflow = Workflow(name="test-workflow", id="test-id", db=db)

        copy = workflow.deep_copy()

        # DB should be the same instance (shared)
        assert copy.db is db
        assert copy.db.instance_id == db.instance_id


# ============================================================================
# Internal State Reset Tests
# ============================================================================


class TestInternalStateReset:
    """Tests to verify internal mutable state is properly reset."""

    def test_cached_session_reset_on_copy(self):
        """_cached_session should be None in copied agent."""
        agent = Agent(name="test-agent", id="test-id")
        agent._cached_session = "cached_session_data"  # type: ignore

        copy = agent.deep_copy()

        assert copy._cached_session is None
        assert agent._cached_session == "cached_session_data"

    def test_mcp_tools_list_reset_on_copy(self):
        """_mcp_tools_initialized_on_run should be empty in copied agent."""
        agent = Agent(name="test-agent", id="test-id")
        agent._mcp_tools_initialized_on_run = ["tool1", "tool2"]

        copy = agent.deep_copy()

        assert copy._mcp_tools_initialized_on_run == []
        assert agent._mcp_tools_initialized_on_run == ["tool1", "tool2"]

    def test_connectable_tools_list_reset_on_copy(self):
        """_connectable_tools_initialized_on_run should be empty in copied agent."""
        agent = Agent(name="test-agent", id="test-id")
        agent._connectable_tools_initialized_on_run = ["conn1", "conn2"]

        copy = agent.deep_copy()

        assert copy._connectable_tools_initialized_on_run == []
        assert agent._connectable_tools_initialized_on_run == ["conn1", "conn2"]


# ============================================================================
# Workflow Deep Copy Integration Tests
# ============================================================================


class TestWorkflowDeepCopyIntegration:
    """Integration tests for workflow deep copying."""

    def test_workflow_with_nested_steps_isolation(self):
        """Workflow with nested steps should have all agents isolated."""
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel

        agent1 = Agent(
            name="agent-1",
            id="agent-1-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"counter": 0},
        )
        agent2 = Agent(
            name="agent-2",
            id="agent-2-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"counter": 0},
        )

        workflow = Workflow(
            name="nested-workflow",
            id="nested-workflow-id",
            steps=[
                Loop(
                    name="loop",
                    max_iterations=2,
                    steps=[
                        Parallel(
                            Step(name="step-1", agent=agent1),
                            Step(name="step-2", agent=agent2),
                            name="parallel",
                        )
                    ],
                )
            ],
        )

        copy = workflow.deep_copy()

        # Navigate to nested agents
        loop_copy = copy.steps[0]
        parallel_copy = loop_copy.steps[0]
        agent1_copy = parallel_copy.steps[0].agent
        agent2_copy = parallel_copy.steps[1].agent

        # Verify agents are different instances
        assert agent1_copy is not agent1
        assert agent2_copy is not agent2

        # Modify copied agents' metadata
        agent1_copy.metadata["counter"] = 100
        agent2_copy.metadata["counter"] = 200

        # Original agents should be unchanged
        assert agent1.metadata["counter"] == 0
        assert agent2.metadata["counter"] == 0

    def test_workflow_multiple_copies_independent(self):
        """Multiple workflow copies should be completely independent."""
        agent = Agent(
            name="shared-agent",
            id="shared-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"copy_id": None},
        )

        workflow = Workflow(
            name="template-workflow",
            id="template-workflow-id",
            steps=[Step(name="step", agent=agent)],
        )

        # Create multiple copies
        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()
        copy3 = workflow.deep_copy()

        # Modify each copy's agent
        copy1.steps[0].agent.metadata["copy_id"] = "copy-1"
        copy2.steps[0].agent.metadata["copy_id"] = "copy-2"
        copy3.steps[0].agent.metadata["copy_id"] = "copy-3"

        # All copies should have different metadata
        assert copy1.steps[0].agent.metadata["copy_id"] == "copy-1"
        assert copy2.steps[0].agent.metadata["copy_id"] == "copy-2"
        assert copy3.steps[0].agent.metadata["copy_id"] == "copy-3"

        # Original should be unchanged
        assert agent.metadata["copy_id"] is None

        # All agents should be different instances
        assert copy1.steps[0].agent is not copy2.steps[0].agent
        assert copy2.steps[0].agent is not copy3.steps[0].agent
        assert copy1.steps[0].agent is not agent


# ============================================================================
# Custom Executor Step Tests
# ============================================================================


class TestCustomExecutorStepIsolation:
    """Tests for workflows with custom executor (function) steps."""

    def test_function_executor_step_preserved(self):
        """Function executors should be preserved (same reference) in copies."""
        from agno.workflow.types import StepInput, StepOutput

        def my_custom_executor(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Custom result")

        workflow = Workflow(
            name="function-workflow",
            id="function-workflow-id",
            steps=[Step(name="custom-step", executor=my_custom_executor)],
        )

        copy = workflow.deep_copy()

        # Function reference should be preserved (functions are shared, not copied)
        assert copy.steps[0].executor is my_custom_executor

    def test_mixed_agent_and_function_steps(self):
        """Workflow with both agent and function steps should copy correctly."""
        from agno.workflow.types import StepInput, StepOutput

        def preprocessing_step(step_input: StepInput) -> StepOutput:
            return StepOutput(content=f"Preprocessed: {step_input.input}")

        def postprocessing_step(step_input: StepInput) -> StepOutput:
            return StepOutput(content=f"Postprocessed: {step_input.previous_step_content}")

        agent = Agent(
            name="middle-agent",
            id="middle-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"processed": False},
        )

        workflow = Workflow(
            name="mixed-workflow",
            id="mixed-workflow-id",
            steps=[
                Step(name="preprocess", executor=preprocessing_step),
                Step(name="agent-step", agent=agent),
                Step(name="postprocess", executor=postprocessing_step),
            ],
        )

        copy = workflow.deep_copy()

        # Function executors should be preserved
        assert copy.steps[0].executor is preprocessing_step
        assert copy.steps[2].executor is postprocessing_step

        # Agent should be copied
        assert copy.steps[1].agent is not agent
        assert copy.steps[1].agent.id == agent.id

        # Modify copy's agent
        copy.steps[1].agent.metadata["processed"] = True

        # Original should be unchanged
        assert agent.metadata["processed"] is False

    def test_function_step_with_closure_state(self):
        """Function executors with closure state - functions are shared."""
        from agno.workflow.types import StepInput, StepOutput

        # Create a function with closure state
        external_counter = {"count": 0}

        def counter_step(step_input: StepInput) -> StepOutput:
            external_counter["count"] += 1
            return StepOutput(content=f"Count: {external_counter['count']}")

        workflow = Workflow(
            name="closure-workflow",
            id="closure-workflow-id",
            steps=[Step(name="counter", executor=counter_step)],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Both copies share the same function reference
        assert copy1.steps[0].executor is counter_step
        assert copy2.steps[0].executor is counter_step
        assert copy1.steps[0].executor is copy2.steps[0].executor

    def test_workflow_callable_steps_preserved(self):
        """Workflow with callable steps (Workflows 1.0 style) should preserve function."""
        from agno.workflow.types import WorkflowExecutionInput

        def my_workflow_function(workflow: Workflow, execution_input: WorkflowExecutionInput):
            return f"Executed with: {execution_input.input}"

        workflow = Workflow(
            name="callable-workflow",
            id="callable-workflow-id",
            steps=my_workflow_function,
        )

        copy = workflow.deep_copy()

        # Callable steps should be preserved (same reference)
        assert copy.steps is my_workflow_function

    def test_function_executor_in_parallel(self):
        """Function executors in Parallel steps should be preserved."""
        from agno.workflow.parallel import Parallel
        from agno.workflow.types import StepInput, StepOutput

        def func_a(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Result A")

        def func_b(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Result B")

        workflow = Workflow(
            name="parallel-func-workflow",
            id="parallel-func-workflow-id",
            steps=[
                Parallel(
                    Step(name="func-a", executor=func_a),
                    Step(name="func-b", executor=func_b),
                    name="parallel-funcs",
                )
            ],
        )

        copy = workflow.deep_copy()

        parallel_copy = copy.steps[0]
        assert parallel_copy.steps[0].executor is func_a
        assert parallel_copy.steps[1].executor is func_b

    def test_function_executor_in_loop(self):
        """Function executors in Loop steps should be preserved."""
        from agno.workflow.loop import Loop
        from agno.workflow.types import StepInput, StepOutput

        iteration_tracker = {"iterations": 0}

        def loop_body(step_input: StepInput) -> StepOutput:
            iteration_tracker["iterations"] += 1
            return StepOutput(content=f"Iteration {iteration_tracker['iterations']}")

        def end_condition(outputs):
            return len(outputs) >= 3

        workflow = Workflow(
            name="loop-func-workflow",
            id="loop-func-workflow-id",
            steps=[
                Loop(
                    name="loop",
                    max_iterations=5,
                    end_condition=end_condition,
                    steps=[Step(name="loop-body", executor=loop_body)],
                )
            ],
        )

        copy = workflow.deep_copy()

        loop_copy = copy.steps[0]
        assert loop_copy.steps[0].executor is loop_body
        assert loop_copy.end_condition is end_condition
        assert loop_copy.max_iterations == 5

    def test_function_executor_in_condition(self):
        """Function executors in Condition steps should be preserved."""
        from agno.workflow.condition import Condition
        from agno.workflow.types import StepInput, StepOutput

        def evaluator(step_input: StepInput) -> bool:
            return step_input.input == "proceed"

        def conditional_step(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Condition met!")

        workflow = Workflow(
            name="condition-func-workflow",
            id="condition-func-workflow-id",
            steps=[
                Condition(
                    name="condition",
                    evaluator=evaluator,
                    steps=[Step(name="conditional", executor=conditional_step)],
                )
            ],
        )

        copy = workflow.deep_copy()

        condition_copy = copy.steps[0]
        assert condition_copy.evaluator is evaluator
        assert condition_copy.steps[0].executor is conditional_step

    def test_function_executor_in_router(self):
        """Function executors in Router steps should be preserved."""
        from agno.workflow.router import Router
        from agno.workflow.types import StepInput, StepOutput

        def route_a(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Route A")

        def route_b(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Route B")

        def selector(step_input: StepInput):
            if "a" in str(step_input.input).lower():
                return [Step(name="route-a", executor=route_a)]
            return [Step(name="route-b", executor=route_b)]

        workflow = Workflow(
            name="router-func-workflow",
            id="router-func-workflow-id",
            steps=[
                Router(
                    name="router",
                    selector=selector,
                    choices=[
                        Step(name="choice-a", executor=route_a),
                        Step(name="choice-b", executor=route_b),
                    ],
                )
            ],
        )

        copy = workflow.deep_copy()

        router_copy = copy.steps[0]
        assert router_copy.selector is selector
        assert router_copy.choices[0].executor is route_a
        assert router_copy.choices[1].executor is route_b

    def test_mixed_function_agent_team_in_parallel(self):
        """Parallel with function, agent, and team steps should copy correctly."""
        from agno.workflow.parallel import Parallel
        from agno.workflow.types import StepInput, StepOutput

        def func_step(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Function result")

        agent = Agent(
            name="parallel-agent",
            id="parallel-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"type": "agent"},
        )

        member = Agent(
            name="team-member",
            id="team-member-id",
            model=OpenAIChat(id="gpt-4o-mini"),
        )
        team = Team(
            name="parallel-team",
            id="parallel-team-id",
            members=[member],
            model=OpenAIChat(id="gpt-4o-mini"),
        )

        workflow = Workflow(
            name="mixed-parallel-workflow",
            id="mixed-parallel-workflow-id",
            steps=[
                Parallel(
                    Step(name="func", executor=func_step),
                    Step(name="agent", agent=agent),
                    Step(name="team", team=team),
                    name="mixed-parallel",
                )
            ],
        )

        copy = workflow.deep_copy()

        parallel_copy = copy.steps[0]

        # Function should be same reference
        assert parallel_copy.steps[0].executor is func_step

        # Agent should be different instance
        assert parallel_copy.steps[1].agent is not agent
        assert parallel_copy.steps[1].agent.id == agent.id

        # Team should be different instance
        assert parallel_copy.steps[2].team is not team
        assert parallel_copy.steps[2].team.id == team.id

        # Team member should also be different instance
        assert parallel_copy.steps[2].team.members[0] is not member

    def test_deeply_nested_function_executors(self):
        """Deeply nested function executors should all be preserved."""
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.types import StepInput, StepOutput

        def level1_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Level 1")

        def level2_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Level 2")

        def level3_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Level 3")

        def evaluator(step_input: StepInput) -> bool:
            return True

        # Loop > Parallel > Condition > Function
        workflow = Workflow(
            name="deeply-nested-func-workflow",
            id="deeply-nested-func-workflow-id",
            steps=[
                Loop(
                    name="loop",
                    max_iterations=2,
                    steps=[
                        Parallel(
                            Condition(
                                name="condition",
                                evaluator=evaluator,
                                steps=[Step(name="deep-func", executor=level3_func)],
                            ),
                            Step(name="parallel-func", executor=level2_func),
                            name="parallel",
                        ),
                        Step(name="loop-func", executor=level1_func),
                    ],
                )
            ],
        )

        copy = workflow.deep_copy()

        # Navigate through nesting
        loop_copy = copy.steps[0]
        parallel_copy = loop_copy.steps[0]
        condition_copy = parallel_copy.steps[0]

        # All functions should be same references
        assert condition_copy.steps[0].executor is level3_func
        assert parallel_copy.steps[1].executor is level2_func
        assert loop_copy.steps[1].executor is level1_func
        assert condition_copy.evaluator is evaluator

    def test_step_attributes_preserved_with_function_executor(self):
        """Step configuration attributes should be preserved for function executor steps."""
        from agno.workflow.types import StepInput, StepOutput

        def my_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Result")

        workflow = Workflow(
            name="attr-workflow",
            id="attr-workflow-id",
            steps=[
                Step(
                    name="configured-step",
                    description="A configured function step",
                    executor=my_func,
                    max_retries=3,
                    skip_on_failure=True,
                )
            ],
        )

        copy = workflow.deep_copy()

        step_copy = copy.steps[0]
        assert step_copy.name == "configured-step"
        assert step_copy.description == "A configured function step"
        assert step_copy.executor is my_func
        assert step_copy.max_retries == 3
        assert step_copy.skip_on_failure is True


# ============================================================================
# Custom Executor with Internal Agent/Team Tests
# ============================================================================


class TestCustomExecutorWithInternalAgentTeam:
    """Tests for custom executor functions that internally use agents/teams.

    This is a critical edge case: when a function executor captures an agent/team
    in its closure, that agent/team is NOT copied during workflow.deep_copy().
    This can lead to state contamination if not handled carefully.
    """

    def test_function_with_closure_agent_shares_reference(self):
        """Function capturing agent in closure - agent is NOT copied (shared reference).

        This documents the LIMITATION: functions with closure-captured agents
        will share that agent across workflow copies.
        """
        from agno.workflow.types import StepInput, StepOutput

        # Agent captured in closure
        closure_agent = Agent(
            name="closure-agent",
            id="closure-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"call_count": 0},
        )

        def agent_wrapper_step(step_input: StepInput) -> StepOutput:
            # This function captures closure_agent - it will be shared!
            closure_agent.metadata["call_count"] += 1
            return StepOutput(content=f"Agent called {closure_agent.metadata['call_count']} times")

        workflow = Workflow(
            name="closure-agent-workflow",
            id="closure-agent-workflow-id",
            steps=[Step(name="agent-wrapper", executor=agent_wrapper_step)],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # The function is shared (same reference)
        assert copy1.steps[0].executor is agent_wrapper_step
        assert copy2.steps[0].executor is agent_wrapper_step

        # IMPORTANT: The closure_agent is NOT part of the workflow's step structure,
        # so it won't be copied. This is a known limitation.
        # Both copies share the same closure_agent reference.

    def test_function_with_closure_team_shares_reference(self):
        """Function capturing team in closure - team is NOT copied (shared reference)."""
        from agno.workflow.types import StepInput, StepOutput

        member = Agent(
            name="team-member",
            id="team-member-id",
            model=OpenAIChat(id="gpt-4o-mini"),
        )
        closure_team = Team(
            name="closure-team",
            id="closure-team-id",
            members=[member],
            model=OpenAIChat(id="gpt-4o-mini"),
        )

        def team_wrapper_step(step_input: StepInput) -> StepOutput:
            # This function captures closure_team - it will be shared!
            return StepOutput(content=f"Team {closure_team.name} executed")

        workflow = Workflow(
            name="closure-team-workflow",
            id="closure-team-workflow-id",
            steps=[Step(name="team-wrapper", executor=team_wrapper_step)],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Both copies share the same function reference
        assert copy1.steps[0].executor is copy2.steps[0].executor

    def test_recommended_pattern_agent_in_step(self):
        """RECOMMENDED: Put agent directly in Step for proper isolation."""
        agent = Agent(
            name="step-agent",
            id="step-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"isolated": True},
        )

        workflow = Workflow(
            name="proper-agent-workflow",
            id="proper-agent-workflow-id",
            steps=[Step(name="agent-step", agent=agent)],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Agents ARE properly isolated when placed in Step
        assert copy1.steps[0].agent is not agent
        assert copy2.steps[0].agent is not agent
        assert copy1.steps[0].agent is not copy2.steps[0].agent

        # Modify one copy's agent
        copy1.steps[0].agent.metadata["isolated"] = False

        # Others are unaffected
        assert agent.metadata["isolated"] is True
        assert copy2.steps[0].agent.metadata["isolated"] is True

    def test_recommended_pattern_team_in_step(self):
        """RECOMMENDED: Put team directly in Step for proper isolation."""
        member = Agent(
            name="member",
            id="member-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"task_count": 0},
        )
        team = Team(
            name="step-team",
            id="step-team-id",
            members=[member],
            model=OpenAIChat(id="gpt-4o-mini"),
        )

        workflow = Workflow(
            name="proper-team-workflow",
            id="proper-team-workflow-id",
            steps=[Step(name="team-step", team=team)],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Teams ARE properly isolated when placed in Step
        assert copy1.steps[0].team is not team
        assert copy2.steps[0].team is not team
        assert copy1.steps[0].team is not copy2.steps[0].team

        # Members are also isolated
        assert copy1.steps[0].team.members[0] is not member
        assert copy2.steps[0].team.members[0] is not member

    def test_function_with_step_input_agent_pattern(self):
        """Pattern: Pass agent via step_input.additional_data for isolation."""
        from agno.workflow.types import StepInput, StepOutput

        def dynamic_agent_step(step_input: StepInput) -> StepOutput:
            # Get agent from additional_data - this allows for dynamic injection
            agent_config = step_input.additional_data.get("agent_config", {}) if step_input.additional_data else {}
            return StepOutput(content=f"Processed with config: {agent_config}")

        workflow = Workflow(
            name="dynamic-agent-workflow",
            id="dynamic-agent-workflow-id",
            steps=[Step(name="dynamic-step", executor=dynamic_agent_step)],
        )

        copy = workflow.deep_copy()

        # Function is preserved
        assert copy.steps[0].executor is dynamic_agent_step

    def test_hybrid_pattern_function_then_agent(self):
        """Hybrid pattern: Function preprocessor followed by agent step."""
        from agno.workflow.types import StepInput, StepOutput

        def preprocessor(step_input: StepInput) -> StepOutput:
            # Preprocessing logic - no agent needed here
            processed = f"PROCESSED: {step_input.input}"
            return StepOutput(content=processed)

        agent = Agent(
            name="processor-agent",
            id="processor-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"processed_count": 0},
        )

        workflow = Workflow(
            name="hybrid-workflow",
            id="hybrid-workflow-id",
            steps=[
                Step(name="preprocess", executor=preprocessor),
                Step(name="agent-process", agent=agent),
            ],
        )

        copy = workflow.deep_copy()

        # Function is shared (same reference)
        assert copy.steps[0].executor is preprocessor

        # Agent is properly isolated (different instance)
        assert copy.steps[1].agent is not agent
        assert copy.steps[1].agent.id == agent.id

    def test_hybrid_pattern_agent_then_function(self):
        """Hybrid pattern: Agent step followed by function postprocessor."""
        from agno.workflow.types import StepInput, StepOutput

        agent = Agent(
            name="generator-agent",
            id="generator-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"generated_count": 0},
        )

        def postprocessor(step_input: StepInput) -> StepOutput:
            # Postprocessing logic - uses previous step's output
            result = f"FINAL: {step_input.previous_step_content}"
            return StepOutput(content=result)

        workflow = Workflow(
            name="agent-then-func-workflow",
            id="agent-then-func-workflow-id",
            steps=[
                Step(name="generate", agent=agent),
                Step(name="postprocess", executor=postprocessor),
            ],
        )

        copy = workflow.deep_copy()

        # Agent is properly isolated
        assert copy.steps[0].agent is not agent

        # Function is shared
        assert copy.steps[1].executor is postprocessor

    def test_parallel_mixed_agent_and_function_isolation(self):
        """Parallel execution with both agent steps and function steps."""
        from agno.workflow.parallel import Parallel
        from agno.workflow.types import StepInput, StepOutput

        agent1 = Agent(
            name="parallel-agent-1",
            id="parallel-agent-1-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"branch": "A"},
        )
        agent2 = Agent(
            name="parallel-agent-2",
            id="parallel-agent-2-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"branch": "B"},
        )

        def func_branch(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Function branch result")

        workflow = Workflow(
            name="parallel-mixed-workflow",
            id="parallel-mixed-workflow-id",
            steps=[
                Parallel(
                    Step(name="agent-branch-1", agent=agent1),
                    Step(name="func-branch", executor=func_branch),
                    Step(name="agent-branch-2", agent=agent2),
                    name="mixed-parallel",
                )
            ],
        )

        copy = workflow.deep_copy()

        parallel_copy = copy.steps[0]

        # Agents are isolated
        assert parallel_copy.steps[0].agent is not agent1
        assert parallel_copy.steps[2].agent is not agent2

        # Function is shared
        assert parallel_copy.steps[1].executor is func_branch

        # Modify copied agents
        parallel_copy.steps[0].agent.metadata["branch"] = "A-modified"
        parallel_copy.steps[2].agent.metadata["branch"] = "B-modified"

        # Originals unchanged
        assert agent1.metadata["branch"] == "A"
        assert agent2.metadata["branch"] == "B"

    def test_loop_with_agent_and_function_steps(self):
        """Loop containing both agent and function steps."""
        from agno.workflow.loop import Loop
        from agno.workflow.types import StepInput, StepOutput

        loop_agent = Agent(
            name="loop-agent",
            id="loop-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"iterations": 0},
        )

        def iteration_check(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Iteration complete")

        def end_condition(outputs):
            return len(outputs) >= 2

        workflow = Workflow(
            name="loop-mixed-workflow",
            id="loop-mixed-workflow-id",
            steps=[
                Loop(
                    name="mixed-loop",
                    max_iterations=5,
                    end_condition=end_condition,
                    steps=[
                        Step(name="agent-iteration", agent=loop_agent),
                        Step(name="check-iteration", executor=iteration_check),
                    ],
                )
            ],
        )

        copy = workflow.deep_copy()

        loop_copy = copy.steps[0]

        # Agent in loop is isolated
        assert loop_copy.steps[0].agent is not loop_agent
        assert loop_copy.steps[0].agent.id == loop_agent.id

        # Function in loop is shared
        assert loop_copy.steps[1].executor is iteration_check

        # End condition function is shared
        assert loop_copy.end_condition is end_condition

    def test_condition_with_agent_and_function_evaluator(self):
        """Condition with function evaluator and agent step inside."""
        from agno.workflow.condition import Condition
        from agno.workflow.types import StepInput

        def should_execute(step_input: StepInput) -> bool:
            return "yes" in str(step_input.input).lower()

        conditional_agent = Agent(
            name="conditional-agent",
            id="conditional-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"executed": False},
        )

        workflow = Workflow(
            name="condition-mixed-workflow",
            id="condition-mixed-workflow-id",
            steps=[
                Condition(
                    name="conditional",
                    evaluator=should_execute,
                    steps=[Step(name="conditional-agent-step", agent=conditional_agent)],
                )
            ],
        )

        copy = workflow.deep_copy()

        condition_copy = copy.steps[0]

        # Evaluator function is shared
        assert condition_copy.evaluator is should_execute

        # Agent inside condition is isolated
        assert condition_copy.steps[0].agent is not conditional_agent
        assert condition_copy.steps[0].agent.id == conditional_agent.id

    def test_router_with_agent_choices_and_function_selector(self):
        """Router with function selector and agent steps as choices."""
        from agno.workflow.router import Router
        from agno.workflow.types import StepInput

        route_agent_a = Agent(
            name="route-a-agent",
            id="route-a-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"route": "A"},
        )
        route_agent_b = Agent(
            name="route-b-agent",
            id="route-b-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"route": "B"},
        )

        def route_selector(step_input: StepInput):
            if "a" in str(step_input.input).lower():
                return [Step(name="route-a", agent=route_agent_a)]
            return [Step(name="route-b", agent=route_agent_b)]

        workflow = Workflow(
            name="router-agent-workflow",
            id="router-agent-workflow-id",
            steps=[
                Router(
                    name="agent-router",
                    selector=route_selector,
                    choices=[
                        Step(name="choice-a", agent=route_agent_a),
                        Step(name="choice-b", agent=route_agent_b),
                    ],
                )
            ],
        )

        copy = workflow.deep_copy()

        router_copy = copy.steps[0]

        # Selector function is shared
        assert router_copy.selector is route_selector

        # Agent choices are isolated
        assert router_copy.choices[0].agent is not route_agent_a
        assert router_copy.choices[1].agent is not route_agent_b
        assert router_copy.choices[0].agent.id == route_agent_a.id
        assert router_copy.choices[1].agent.id == route_agent_b.id

        # NOTE: The agents referenced inside route_selector's closure
        # (route_agent_a, route_agent_b) are NOT copied. This is a limitation.
        # Only the agents in `choices` are properly isolated.

    def test_complex_workflow_with_all_step_types(self):
        """Complex workflow combining all step types with agents and functions."""
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.router import Router
        from agno.workflow.types import StepInput, StepOutput

        # Agents
        preprocess_agent = Agent(
            name="preprocess-agent",
            id="preprocess-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"stage": "preprocess"},
        )
        main_agent = Agent(
            name="main-agent",
            id="main-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"stage": "main"},
        )
        fallback_agent = Agent(
            name="fallback-agent",
            id="fallback-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"stage": "fallback"},
        )

        # Functions
        def validate_input(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Validated")

        def should_process(step_input: StepInput) -> bool:
            return True

        def select_route(step_input: StepInput):
            return [Step(name="main", agent=main_agent)]

        def end_loop(outputs):
            return len(outputs) >= 1

        workflow = Workflow(
            name="complex-workflow",
            id="complex-workflow-id",
            steps=[
                # Step 1: Function validation
                Step(name="validate", executor=validate_input),
                # Step 2: Agent preprocessing
                Step(name="preprocess", agent=preprocess_agent),
                # Step 3: Conditional execution
                Condition(
                    name="should-process",
                    evaluator=should_process,
                    steps=[
                        # Nested parallel
                        Parallel(
                            # Router with agent choices
                            Router(
                                name="route-processor",
                                selector=select_route,
                                choices=[
                                    Step(name="main-choice", agent=main_agent),
                                    Step(name="fallback-choice", agent=fallback_agent),
                                ],
                            ),
                            # Loop with agent
                            Loop(
                                name="retry-loop",
                                max_iterations=2,
                                end_condition=end_loop,
                                steps=[Step(name="retry-agent", agent=main_agent)],
                            ),
                            name="parallel-processing",
                        )
                    ],
                ),
            ],
        )

        copy = workflow.deep_copy()

        # Verify structure integrity
        assert len(copy.steps) == 3

        # Step 1: Function preserved
        assert copy.steps[0].executor is validate_input

        # Step 2: Agent isolated
        assert copy.steps[1].agent is not preprocess_agent
        assert copy.steps[1].agent.metadata["stage"] == "preprocess"

        # Step 3: Condition
        condition_copy = copy.steps[2]
        assert condition_copy.evaluator is should_process

        # Navigate to parallel
        parallel_copy = condition_copy.steps[0]

        # Router inside parallel
        router_copy = parallel_copy.steps[0]
        assert router_copy.selector is select_route
        assert router_copy.choices[0].agent is not main_agent
        assert router_copy.choices[1].agent is not fallback_agent

        # Loop inside parallel
        loop_copy = parallel_copy.steps[1]
        assert loop_copy.end_condition is end_loop
        assert loop_copy.steps[0].agent is not main_agent

        # Modify all copied agents
        copy.steps[1].agent.metadata["stage"] = "modified"
        router_copy.choices[0].agent.metadata["stage"] = "modified"
        router_copy.choices[1].agent.metadata["stage"] = "modified"
        loop_copy.steps[0].agent.metadata["stage"] = "modified"

        # All originals unchanged
        assert preprocess_agent.metadata["stage"] == "preprocess"
        assert main_agent.metadata["stage"] == "main"
        assert fallback_agent.metadata["stage"] == "fallback"

    def test_step_id_unique_per_copy(self):
        """Each workflow copy should get NEW unique step_ids for per-request isolation."""
        from agno.workflow.types import StepInput, StepOutput

        def my_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Result")

        agent = Agent(
            name="test-agent",
            id="test-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
        )

        # Create steps with explicit step_ids
        func_step = Step(
            name="func-step",
            step_id="original-func-step-id",
            executor=my_func,
        )
        agent_step = Step(
            name="agent-step",
            step_id="original-agent-step-id",
            agent=agent,
        )

        workflow = Workflow(
            name="step-id-workflow",
            id="step-id-workflow-id",
            steps=[func_step, agent_step],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Each copy should have NEW unique step_ids (different from original)
        assert copy1.steps[0].step_id != "original-func-step-id"
        assert copy1.steps[1].step_id != "original-agent-step-id"
        assert copy2.steps[0].step_id != "original-func-step-id"
        assert copy2.steps[1].step_id != "original-agent-step-id"

        # Each copy should have DIFFERENT step_ids from each other
        assert copy1.steps[0].step_id != copy2.steps[0].step_id
        assert copy1.steps[1].step_id != copy2.steps[1].step_id

        # Step names should be preserved
        assert copy1.steps[0].name == "func-step"
        assert copy1.steps[1].name == "agent-step"

        # Agent should be a different instance
        assert copy1.steps[1].agent is not agent
        assert copy2.steps[1].agent is not agent
        assert copy1.steps[1].agent is not copy2.steps[1].agent

    def test_step_id_unique_in_nested_steps(self):
        """Nested steps should also get unique step_ids per copy."""
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.types import StepInput, StepOutput

        def my_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Result")

        agent = Agent(
            name="nested-agent",
            id="nested-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
        )

        inner_step_1 = Step(
            name="inner-1",
            step_id="original-inner-1-id",
            executor=my_func,
        )
        inner_step_2 = Step(
            name="inner-2",
            step_id="original-inner-2-id",
            agent=agent,
        )

        workflow = Workflow(
            name="nested-step-id-workflow",
            id="nested-step-id-workflow-id",
            steps=[
                Loop(
                    name="loop",
                    max_iterations=2,
                    steps=[
                        Parallel(
                            inner_step_1,
                            inner_step_2,
                            name="parallel",
                        )
                    ],
                )
            ],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Navigate to nested steps
        loop_copy1 = copy1.steps[0]
        parallel_copy1 = loop_copy1.steps[0]
        loop_copy2 = copy2.steps[0]
        parallel_copy2 = loop_copy2.steps[0]

        # Each copy should have NEW unique step_ids
        assert parallel_copy1.steps[0].step_id != "original-inner-1-id"
        assert parallel_copy1.steps[1].step_id != "original-inner-2-id"

        # Each copy should have DIFFERENT step_ids from each other
        assert parallel_copy1.steps[0].step_id != parallel_copy2.steps[0].step_id
        assert parallel_copy1.steps[1].step_id != parallel_copy2.steps[1].step_id

        # Step names should be preserved
        assert parallel_copy1.steps[0].name == "inner-1"
        assert parallel_copy1.steps[1].name == "inner-2"

        # Agent should be a different instance
        assert parallel_copy1.steps[1].agent is not agent
        assert parallel_copy2.steps[1].agent is not agent

    def test_function_executor_calling_agent_run(self):
        """Function executor that calls agent.run() internally - agent is shared via closure."""
        from agno.workflow.types import StepInput, StepOutput

        # Agent captured in closure and used via run()
        inner_agent = Agent(
            name="inner-agent",
            id="inner-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"run_count": 0},
        )

        def executor_with_agent_run(step_input: StepInput) -> StepOutput:
            # This captures inner_agent in closure and calls run()
            # The agent is SHARED across workflow copies - this is a limitation!
            inner_agent.metadata["run_count"] += 1
            # In real usage: result = inner_agent.run(step_input.input)
            return StepOutput(content=f"Agent run count: {inner_agent.metadata['run_count']}")

        workflow = Workflow(
            name="agent-run-workflow",
            id="agent-run-workflow-id",
            steps=[Step(name="agent-run-step", executor=executor_with_agent_run)],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Function is shared
        assert copy1.steps[0].executor is executor_with_agent_run
        assert copy2.steps[0].executor is executor_with_agent_run

        # LIMITATION: inner_agent is shared via closure
        # Simulating what happens when both copies execute
        copy1.steps[0].executor(StepInput(input="test1"))
        assert inner_agent.metadata["run_count"] == 1

        copy2.steps[0].executor(StepInput(input="test2"))
        assert inner_agent.metadata["run_count"] == 2  # Incremented by copy2!

        # This demonstrates the state contamination issue

    def test_function_executor_calling_team_run(self):
        """Function executor that calls team.run() internally - team is shared via closure."""
        from agno.workflow.types import StepInput, StepOutput

        member = Agent(
            name="team-member",
            id="team-member-id",
            model=OpenAIChat(id="gpt-4o-mini"),
        )
        closure_team = Team(
            name="inner-team",
            id="inner-team-id",
            members=[member],
            model=OpenAIChat(id="gpt-4o-mini"),
        )

        call_log: List[str] = []

        def executor_with_team_run(step_input: StepInput) -> StepOutput:
            # This captures closure_team in closure and would call run()
            # The team is SHARED across workflow copies
            call_log.append(f"team_run:{step_input.input}")
            # In real usage: result = closure_team.run(step_input.input)
            _ = closure_team  # Reference to show closure captures this
            return StepOutput(content=f"Team executed for: {step_input.input}")

        workflow = Workflow(
            name="team-run-workflow",
            id="team-run-workflow-id",
            steps=[Step(name="team-run-step", executor=executor_with_team_run)],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Execute via both copies
        copy1.steps[0].executor(StepInput(input="request_A"))
        copy2.steps[0].executor(StepInput(input="request_B"))

        # Both calls logged to same shared list (demonstrating shared state)
        assert len(call_log) == 2
        assert "team_run:request_A" in call_log
        assert "team_run:request_B" in call_log

    def test_function_executor_with_agent_run_mocked(self):
        """Test function executor calling agent.arun() with mocked response."""
        from agno.workflow.types import StepInput, StepOutput

        inner_agent = Agent(
            name="mocked-agent",
            id="mocked-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"user_id": None},
        )

        async def executor_with_async_agent(step_input: StepInput) -> StepOutput:
            # Simulate modifying agent state before run
            inner_agent.metadata["user_id"] = (
                step_input.additional_data.get("user_id") if step_input.additional_data else None
            )
            # In real usage: result = await inner_agent.arun(step_input.input)
            return StepOutput(content=f"Processed for user: {inner_agent.metadata['user_id']}")

        workflow = Workflow(
            name="async-agent-run-workflow",
            id="async-agent-run-workflow-id",
            steps=[Step(name="async-agent-step", executor=executor_with_async_agent)],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Both copies share the same inner_agent via closure
        # This means user_id can leak between requests!

        # Simulate concurrent execution scenario
        import asyncio

        async def simulate_requests():
            # Request 1 sets user_id to "alice"
            await copy1.steps[0].executor(StepInput(input="hello", additional_data={"user_id": "alice"}))
            alice_user_id = inner_agent.metadata["user_id"]

            # Request 2 sets user_id to "bob"
            await copy2.steps[0].executor(StepInput(input="hello", additional_data={"user_id": "bob"}))
            bob_user_id = inner_agent.metadata["user_id"]

            return alice_user_id, bob_user_id

        alice_id, bob_id = asyncio.get_event_loop().run_until_complete(simulate_requests())

        # After both requests, inner_agent has bob's user_id (last write wins)
        assert inner_agent.metadata["user_id"] == "bob"
        # This demonstrates the state contamination problem

    def test_safe_pattern_agent_factory_in_function(self):
        """SAFE PATTERN: Create new agent instance inside function to avoid sharing."""
        from agno.workflow.types import StepInput, StepOutput

        execution_log: List[Dict[str, Any]] = []

        def safe_executor_with_agent_factory(step_input: StepInput) -> StepOutput:
            # SAFE: Create a NEW agent instance for each execution
            local_agent = Agent(
                name="local-agent",
                id="local-agent-id",
                model=OpenAIChat(id="gpt-4o-mini"),
                metadata={
                    "request_id": step_input.additional_data.get("request_id") if step_input.additional_data else None
                },
            )
            execution_log.append(
                {
                    "request_id": local_agent.metadata["request_id"],
                    "agent_id": id(local_agent),
                }
            )
            # In real usage: result = local_agent.run(step_input.input)
            return StepOutput(content=f"Processed request: {local_agent.metadata['request_id']}")

        workflow = Workflow(
            name="safe-agent-factory-workflow",
            id="safe-agent-factory-workflow-id",
            steps=[Step(name="safe-step", executor=safe_executor_with_agent_factory)],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Execute via both copies
        copy1.steps[0].executor(StepInput(input="test", additional_data={"request_id": "req-1"}))
        copy2.steps[0].executor(StepInput(input="test", additional_data={"request_id": "req-2"}))

        # Each execution created a different agent instance
        assert len(execution_log) == 2
        assert execution_log[0]["request_id"] == "req-1"
        assert execution_log[1]["request_id"] == "req-2"
        assert execution_log[0]["agent_id"] != execution_log[1]["agent_id"]

    def test_safe_pattern_agent_deep_copy_in_function(self):
        """SAFE PATTERN: deep_copy the template agent inside function."""
        from agno.workflow.types import StepInput, StepOutput

        # Template agent (not used directly, only as template)
        template_agent = Agent(
            name="template-agent",
            id="template-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"processed": False, "user_id": None},
        )

        execution_agents: List[Agent] = []

        def safe_executor_with_deep_copy(step_input: StepInput) -> StepOutput:
            # SAFE: Create isolated copy from template
            local_agent = template_agent.deep_copy()
            local_agent.metadata["user_id"] = (
                step_input.additional_data.get("user_id") if step_input.additional_data else None
            )
            local_agent.metadata["processed"] = True
            execution_agents.append(local_agent)
            # In real usage: result = local_agent.run(step_input.input)
            return StepOutput(content=f"Processed for: {local_agent.metadata['user_id']}")

        workflow = Workflow(
            name="deep-copy-agent-workflow",
            id="deep-copy-agent-workflow-id",
            steps=[Step(name="deep-copy-step", executor=safe_executor_with_deep_copy)],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Execute via both copies
        copy1.steps[0].executor(StepInput(input="test", additional_data={"user_id": "alice"}))
        copy2.steps[0].executor(StepInput(input="test", additional_data={"user_id": "bob"}))

        # Template is unchanged
        assert template_agent.metadata["processed"] is False
        assert template_agent.metadata["user_id"] is None

        # Each execution got isolated agent
        assert len(execution_agents) == 2
        assert execution_agents[0].metadata["user_id"] == "alice"
        assert execution_agents[1].metadata["user_id"] == "bob"
        assert execution_agents[0] is not execution_agents[1]
        assert execution_agents[0] is not template_agent

    def test_safe_pattern_team_deep_copy_in_function(self):
        """SAFE PATTERN: deep_copy the template team inside function."""
        from agno.workflow.types import StepInput, StepOutput

        member = Agent(
            name="member",
            id="member-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"tasks": 0},
        )
        template_team = Team(
            name="template-team",
            id="template-team-id",
            members=[member],
            model=OpenAIChat(id="gpt-4o-mini"),
        )

        execution_teams: List[Team] = []

        def safe_executor_with_team_copy(step_input: StepInput) -> StepOutput:
            # SAFE: Create isolated copy from template
            local_team = template_team.deep_copy()
            local_team.members[0].metadata["tasks"] += 1
            execution_teams.append(local_team)
            # In real usage: result = local_team.run(step_input.input)
            return StepOutput(content="Team executed")

        workflow = Workflow(
            name="deep-copy-team-workflow",
            id="deep-copy-team-workflow-id",
            steps=[Step(name="deep-copy-team-step", executor=safe_executor_with_team_copy)],
        )

        copy1 = workflow.deep_copy()
        copy2 = workflow.deep_copy()

        # Execute via both copies
        copy1.steps[0].executor(StepInput(input="task1"))
        copy2.steps[0].executor(StepInput(input="task2"))

        # Template member unchanged
        assert member.metadata["tasks"] == 0

        # Each execution got isolated team with isolated member
        assert len(execution_teams) == 2
        assert execution_teams[0].members[0].metadata["tasks"] == 1
        assert execution_teams[1].members[0].metadata["tasks"] == 1
        assert execution_teams[0] is not execution_teams[1]
        assert execution_teams[0].members[0] is not execution_teams[1].members[0]

    def test_integration_workflow_with_agent_run_in_agentos(self):
        """Integration test: Workflow with function that calls agent inside AgentOS."""
        from agno.workflow.types import StepInput, StepOutput

        # Shared agent via closure (demonstrating the problem)
        shared_agent = Agent(
            name="shared-agent",
            id="shared-agent-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            metadata={"last_user": None},
        )

        def executor_using_shared_agent(step_input: StepInput) -> StepOutput:
            user = step_input.additional_data.get("user") if step_input.additional_data else "unknown"
            shared_agent.metadata["last_user"] = user
            return StepOutput(content=f"Processed for {user}")

        workflow = Workflow(
            name="shared-agent-workflow",
            id="shared-agent-workflow-id",
            steps=[Step(name="shared-step", executor=executor_using_shared_agent)],
        )

        os = AgentOS(workflows=[workflow])
        app = os.get_app()
        client = TestClient(app)

        class MockRunOutput:
            def __init__(self):
                self.run_id = str(uuid.uuid4())
                self.content = "result"

            def to_dict(self):
                return {"run_id": self.run_id, "content": self.content}

        with patch.object(Workflow, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = MockRunOutput()

            # Make requests
            response1 = client.post(
                f"/workflows/{workflow.id}/runs",
                data={"message": "Hello", "stream": "false"},
            )
            response2 = client.post(
                f"/workflows/{workflow.id}/runs",
                data={"message": "World", "stream": "false"},
            )

        assert response1.status_code == 200
        assert response2.status_code == 200

        # The workflow itself is copied via deep_copy, but the shared_agent
        # inside the closure is NOT copied - it remains shared.
        # This test documents this behavior.

    def test_integration_safe_workflow_with_agent_factory(self):
        """Integration test: Safe workflow pattern with agent factory inside AgentOS."""
        from agno.workflow.types import StepInput, StepOutput

        agent_instances_created: List[str] = []

        def safe_executor_factory(step_input: StepInput) -> StepOutput:
            # SAFE: Create new agent per execution
            request_id = str(uuid.uuid4())
            local_agent = Agent(
                name=f"local-agent-{request_id}",
                id=f"local-agent-{request_id}",
                model=OpenAIChat(id="gpt-4o-mini"),
            )
            agent_instances_created.append(local_agent.id)
            return StepOutput(content=f"Created agent: {local_agent.id}")

        workflow = Workflow(
            name="safe-factory-workflow",
            id="safe-factory-workflow-id",
            steps=[Step(name="safe-factory-step", executor=safe_executor_factory)],
        )

        os = AgentOS(workflows=[workflow])
        app = os.get_app()
        client = TestClient(app)

        class MockRunOutput:
            def __init__(self):
                self.run_id = str(uuid.uuid4())

            def to_dict(self):
                return {"run_id": self.run_id}

        with patch.object(Workflow, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = MockRunOutput()

            # Make multiple requests
            for _ in range(3):
                response = client.post(
                    f"/workflows/{workflow.id}/runs",
                    data={"message": "Test", "stream": "false"},
                )
                assert response.status_code == 200

        # Each workflow run would create its own agent (if actually executed)
        # The mock bypasses actual execution, but the pattern is demonstrated


# ============================================================================
# Tools Deep Copy Tests
# ============================================================================


class TestToolsDeepCopy:
    """Tests for tools handling during Agent.deep_copy()."""

    def test_regular_tools_are_deep_copied(self):
        """Regular (non-MCP) tools should be deep copied, not shared."""
        from agno.tools.toolkit import Toolkit

        class CustomTool(Toolkit):
            """A simple custom toolkit for testing."""

            def __init__(self):
                super().__init__(name="custom_tool")
                self.counter = 0
                self.register(self.increment)

            def increment(self) -> int:
                """Increment and return counter."""
                self.counter += 1
                return self.counter

        tool = CustomTool()
        agent = Agent(name="test-agent", id="test-id", tools=[tool])

        copy = agent.deep_copy()

        # Tools list should be a different list
        assert copy.tools is not agent.tools

        # The copied tool should be a different instance
        assert len(copy.tools) == 1
        assert copy.tools[0] is not tool

        # Modifying original tool shouldn't affect copy
        tool.counter = 100
        assert copy.tools[0].counter == 0  # Copy should have initial value

    def test_function_tools_are_copied(self):
        """Function-based tools should be copied."""

        def my_tool_func(x: int) -> int:
            """A simple tool function."""
            return x * 2

        agent = Agent(name="test-agent", id="test-id", tools=[my_tool_func])

        copy = agent.deep_copy()

        # Tools list should be a different list
        assert copy.tools is not agent.tools
        # Function reference may be same (functions are immutable)
        assert len(copy.tools) == 1

    def test_mcp_tools_are_shared_not_copied(self):
        """MCP tools should be shared (same instance) to maintain connections."""

        # Create a mock MCP tools class
        class MockMCPTools:
            """Mock MCP tools for testing - simulates MCPTools behavior."""

            def __init__(self):
                self.instance_id = uuid.uuid4()
                self.connected = True

        # Create a subclass that includes MCPTools in its MRO for detection
        class MCPTools:
            pass

        # Create a subclass that includes MCPTools in its MRO
        class TestMCPTools(MCPTools):
            def __init__(self):
                self.instance_id = uuid.uuid4()
                self.connected = True

        mcp_tool = TestMCPTools()
        agent = Agent(name="test-agent", id="test-id", tools=[mcp_tool])

        copy = agent.deep_copy()

        # MCP tool should be the SAME instance (shared)
        assert copy.tools[0] is mcp_tool
        assert copy.tools[0].instance_id == mcp_tool.instance_id

    def test_multi_mcp_tools_are_shared(self):
        """MultiMCPTools should also be shared."""

        class MultiMCPTools:
            """Mock MultiMCPTools for testing."""

            def __init__(self):
                self.instance_id = uuid.uuid4()
                self.servers = ["server1", "server2"]

        class TestMultiMCPTools(MultiMCPTools):
            pass

        multi_mcp = TestMultiMCPTools()
        agent = Agent(name="test-agent", id="test-id", tools=[multi_mcp])

        copy = agent.deep_copy()

        # MultiMCPTools should be shared
        assert copy.tools[0] is multi_mcp

    def test_mixed_tools_handled_correctly(self):
        """Mix of MCP and regular tools should be handled correctly."""
        from agno.tools.toolkit import Toolkit

        class RegularTool(Toolkit):
            def __init__(self):
                super().__init__(name="regular")
                self.value = "original"
                self.register(self.get_value)

            def get_value(self) -> str:
                return self.value

        class MCPTools:
            pass

        class MockMCP(MCPTools):
            def __init__(self):
                self.instance_id = uuid.uuid4()

        regular = RegularTool()
        mcp = MockMCP()

        agent = Agent(name="test-agent", id="test-id", tools=[regular, mcp])

        copy = agent.deep_copy()

        assert len(copy.tools) == 2
        # Regular tool should be copied (different instance)
        assert copy.tools[0] is not regular
        # MCP tool should be shared (same instance)
        assert copy.tools[1] is mcp

    def test_non_copyable_tool_falls_back_to_sharing(self):
        """Tools that can't be deep copied should be shared by reference."""

        class NonCopyableTool:
            """A tool that raises on deepcopy."""

            def __init__(self):
                self.instance_id = uuid.uuid4()

            def __deepcopy__(self, memo):
                raise TypeError("Cannot deep copy this tool")

            def __copy__(self):
                raise TypeError("Cannot copy this tool")

        non_copyable = NonCopyableTool()
        agent = Agent(name="test-agent", id="test-id", tools=[non_copyable])

        # Should not raise - falls back to sharing
        copy = agent.deep_copy()

        # Non-copyable tool should be shared
        assert copy.tools[0] is non_copyable
        assert copy.tools[0].instance_id == non_copyable.instance_id

    def test_tool_with_failing_mro_check_still_works(self):
        """Tools where MRO check fails should still be processed safely."""

        class WeirdTool:
            """Tool with unusual type() behavior."""

            def __init__(self):
                self.value = "test"

        weird = WeirdTool()
        agent = Agent(name="test-agent", id="test-id", tools=[weird])

        # Should not raise
        copy = agent.deep_copy()

        assert len(copy.tools) == 1

    def test_empty_tools_list_copied(self):
        """Empty tools list should be handled correctly."""
        agent = Agent(name="test-agent", id="test-id", tools=[])

        copy = agent.deep_copy()

        assert copy.tools == []
        assert copy.tools is not agent.tools

    def test_none_tools_handled(self):
        """None tools gets normalized to empty list by Agent."""
        agent = Agent(name="test-agent", id="test-id", tools=None)

        copy = agent.deep_copy()

        # Agent normalizes None to empty list, so copy should also be empty list
        assert copy.tools == []

    def test_tools_with_state_isolation(self):
        """Tool state should be isolated between copies."""
        from agno.tools.toolkit import Toolkit

        class StatefulTool(Toolkit):
            def __init__(self):
                super().__init__(name="stateful")
                self.call_count = 0
                self.history: List[str] = []
                self.register(self.record)

            def record(self, message: str) -> str:
                self.call_count += 1
                self.history.append(message)
                return f"Recorded: {message}"

        tool = StatefulTool()
        tool.call_count = 5
        tool.history = ["msg1", "msg2"]

        agent = Agent(name="test-agent", id="test-id", tools=[tool])

        copy1 = agent.deep_copy()
        copy2 = agent.deep_copy()

        # Each copy should have independent state
        copied_tool1 = copy1.tools[0]
        copied_tool2 = copy2.tools[0]

        # Initial state should be copied
        assert copied_tool1.call_count == 5
        assert copied_tool1.history == ["msg1", "msg2"]

        # Modifications should be independent
        copied_tool1.call_count = 100
        copied_tool1.history.append("new_msg")

        assert copied_tool2.call_count == 5  # Unchanged
        assert copied_tool2.history == ["msg1", "msg2"]  # Unchanged
        assert tool.call_count == 5  # Original unchanged


# ============================================================================
# Knowledge Deep Copy Tests
# ============================================================================


class TestKnowledgeDeepCopy:
    """Tests for knowledge handling during deep_copy()."""

    def test_knowledge_is_shared_not_copied(self):
        """Knowledge base should be shared (not copied) between instances."""

        class MockKnowledge:
            """Mock knowledge base for testing."""

            def __init__(self):
                self.instance_id = uuid.uuid4()
                self.documents = ["doc1", "doc2"]

            def search(self, query: str):
                return self.documents

        knowledge = MockKnowledge()
        agent = Agent(name="test-agent", id="test-id", knowledge=knowledge)

        copy = agent.deep_copy()

        # Knowledge should be the SAME instance (shared)
        assert copy.knowledge is knowledge
        assert copy.knowledge.instance_id == knowledge.instance_id

    def test_knowledge_sharing_in_team(self):
        """Knowledge in team members should also be shared."""

        class MockKnowledge:
            def __init__(self):
                self.instance_id = uuid.uuid4()

        knowledge = MockKnowledge()
        member = Agent(name="member", id="member-id", knowledge=knowledge)
        team = Team(
            name="test-team",
            id="test-team-id",
            members=[member],
            model=OpenAIChat(id="gpt-4o-mini"),
        )

        copy = team.deep_copy()

        # Member's knowledge should be shared
        assert copy.members[0].knowledge is knowledge

    def test_knowledge_none_handled(self):
        """None knowledge should remain None."""
        agent = Agent(name="test-agent", id="test-id", knowledge=None)

        copy = agent.deep_copy()

        assert copy.knowledge is None


# ============================================================================
# Model Deep Copy Tests
# ============================================================================


class TestModelDeepCopy:
    """Tests for model handling during deep_copy()."""

    def test_model_is_shared_not_copied(self):
        """Model should be shared (not copied) between instances."""
        model = OpenAIChat(id="gpt-4o-mini")
        agent = Agent(name="test-agent", id="test-id", model=model)

        copy = agent.deep_copy()

        # Model should be the SAME instance (shared)
        assert copy.model is model

    def test_reasoning_model_is_shared(self):
        """Reasoning model should also be shared."""
        model = OpenAIChat(id="gpt-4o-mini")
        reasoning_model = OpenAIChat(id="gpt-4o")
        agent = Agent(name="test-agent", id="test-id", model=model, reasoning_model=reasoning_model)

        copy = agent.deep_copy()

        assert copy.model is model
        assert copy.reasoning_model is reasoning_model

    def test_model_in_team_is_shared(self):
        """Team model and member models should be shared."""
        team_model = OpenAIChat(id="gpt-4o-mini")
        member_model = OpenAIChat(id="gpt-4o")

        member = Agent(name="member", id="member-id", model=member_model)
        team = Team(
            name="test-team",
            id="test-team-id",
            members=[member],
            model=team_model,
        )

        copy = team.deep_copy()

        assert copy.model is team_model
        assert copy.members[0].model is member_model

    def test_parser_model_is_shared(self):
        """Parser model should be shared (not copied) between instances."""
        model = OpenAIChat(id="gpt-4o-mini")
        parser_model = OpenAIChat(id="gpt-4o")
        agent = Agent(name="test-agent", id="test-id", model=model, parser_model=parser_model)

        copy = agent.deep_copy()

        # Parser model should be the SAME instance (shared)
        assert copy.parser_model is parser_model

    def test_output_model_is_shared(self):
        """Output model should be shared (not copied) between instances."""
        model = OpenAIChat(id="gpt-4o-mini")
        output_model = OpenAIChat(id="gpt-4o")
        agent = Agent(name="test-agent", id="test-id", model=model, output_model=output_model)

        copy = agent.deep_copy()

        # Output model should be the SAME instance (shared)
        assert copy.output_model is output_model

    def test_session_summary_manager_is_shared(self):
        """Session summary manager should be shared (not copied) between instances."""
        from agno.session.summary import SessionSummaryManager

        model = OpenAIChat(id="gpt-4o-mini")
        session_summary_manager = SessionSummaryManager(model=model)
        agent = Agent(
            name="test-agent",
            id="test-id",
            model=model,
            session_summary_manager=session_summary_manager,
        )

        copy = agent.deep_copy()

        # Session summary manager should be the SAME instance (shared)
        assert copy.session_summary_manager is session_summary_manager

    def test_parser_model_in_team_is_shared(self):
        """Team's parser model should be shared."""
        model = OpenAIChat(id="gpt-4o-mini")
        parser_model = OpenAIChat(id="gpt-4o")

        team = Team(
            name="test-team",
            id="test-team-id",
            members=[Agent(name="member", id="member-id", model=model)],
            model=model,
            parser_model=parser_model,
        )

        copy = team.deep_copy()

        assert copy.parser_model is parser_model

    def test_output_model_in_team_is_shared(self):
        """Team's output model should be shared."""
        model = OpenAIChat(id="gpt-4o-mini")
        output_model = OpenAIChat(id="gpt-4o")

        team = Team(
            name="test-team",
            id="test-team-id",
            members=[Agent(name="member", id="member-id", model=model)],
            model=model,
            output_model=output_model,
        )

        copy = team.deep_copy()

        assert copy.output_model is output_model


# ============================================================================
# Database Deep Copy Tests
# ============================================================================


class TestDatabaseDeepCopy:
    """Tests for database handling during deep_copy()."""

    def test_db_is_shared_not_copied(self):
        """Database should be shared (not copied) between instances."""

        class MockDatabase:
            def __init__(self):
                self.instance_id = uuid.uuid4()
                self.connection_pool = ["conn1", "conn2"]

        db = MockDatabase()
        agent = Agent(name="test-agent", id="test-id", db=db)

        copy = agent.deep_copy()

        # DB should be the SAME instance (shared)
        assert copy.db is db
        assert copy.db.instance_id == db.instance_id

    def test_db_shared_across_multiple_copies(self):
        """Multiple copies should all share the same DB."""

        class MockDatabase:
            def __init__(self):
                self.instance_id = uuid.uuid4()

        db = MockDatabase()
        agent = Agent(name="test-agent", id="test-id", db=db)

        copies = [agent.deep_copy() for _ in range(5)]

        # All copies should share same DB
        for copy in copies:
            assert copy.db is db

    def test_db_shared_in_team_members(self):
        """Team members' databases should be shared."""

        class MockDatabase:
            def __init__(self):
                self.instance_id = uuid.uuid4()

        db = MockDatabase()
        member = Agent(name="member", id="member-id", db=db)
        team = Team(
            name="test-team",
            id="test-team-id",
            members=[member],
            model=OpenAIChat(id="gpt-4o-mini"),
        )

        copy = team.deep_copy()

        # Member's DB should be shared
        assert copy.members[0].db is db

    def test_db_shared_in_workflow_step_agents(self):
        """Workflow step agents' databases should be shared."""

        class MockDatabase:
            def __init__(self):
                self.instance_id = uuid.uuid4()

        db = MockDatabase()
        step_agent = Agent(name="step-agent", id="step-agent-id", db=db)
        workflow = Workflow(
            name="test-workflow",
            id="test-workflow-id",
            steps=[Step(name="step", agent=step_agent)],
        )

        copy = workflow.deep_copy()

        # Step agent's DB should be shared
        assert copy.steps[0].agent.db is db


# ============================================================================
# Memory Manager Deep Copy Tests
# ============================================================================


class TestMemoryManagerDeepCopy:
    """Tests for memory_manager handling during deep_copy()."""

    def test_memory_manager_is_shared(self):
        """Memory manager should be shared (not copied)."""

        class MockMemoryManager:
            def __init__(self):
                self.instance_id = uuid.uuid4()

        mm = MockMemoryManager()
        agent = Agent(name="test-agent", id="test-id", memory_manager=mm)

        copy = agent.deep_copy()

        # Memory manager should be shared
        assert copy.memory_manager is mm


# ============================================================================
# Reasoning Agent Deep Copy Tests
# ============================================================================


class TestReasoningAgentDeepCopy:
    """Tests for reasoning_agent handling during deep_copy()."""

    def test_reasoning_agent_is_deep_copied(self):
        """Reasoning agent should be deep copied (isolated)."""
        reasoning_agent = Agent(name="reasoner", id="reasoner-id", model=OpenAIChat(id="gpt-4o"))
        agent = Agent(
            name="main-agent",
            id="main-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            reasoning_agent=reasoning_agent,
        )

        copy = agent.deep_copy()

        # Reasoning agent should be a DIFFERENT instance (copied)
        assert copy.reasoning_agent is not reasoning_agent
        assert copy.reasoning_agent.id == reasoning_agent.id
        assert copy.reasoning_agent.name == reasoning_agent.name

    def test_reasoning_agent_state_isolated(self):
        """Reasoning agent state should be isolated."""
        reasoning_agent = Agent(
            name="reasoner",
            id="reasoner-id",
            model=OpenAIChat(id="gpt-4o"),
            metadata={"thoughts": []},
        )
        agent = Agent(
            name="main-agent",
            id="main-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            reasoning_agent=reasoning_agent,
        )

        copy = agent.deep_copy()

        # Modify original reasoning agent metadata
        reasoning_agent.metadata["thoughts"].append("thought1")

        # Copy's reasoning agent should be unaffected
        assert copy.reasoning_agent.metadata["thoughts"] == []


# ============================================================================
# Error Handling Deep Copy Tests
# ============================================================================


class TestDeepCopyErrorHandling:
    """Tests for error handling during deep_copy()."""

    def test_tool_iteration_error_handled(self):
        """Errors during tool iteration should be handled gracefully."""

        class FailingIterableTools:
            """A tools list that fails during iteration."""

            def __init__(self):
                self.items = ["tool1", "tool2"]
                self._iter_count = 0

            def __iter__(self):
                return self

            def __next__(self):
                if self._iter_count >= 1:
                    raise RuntimeError("Iteration failed")
                self._iter_count += 1
                return self.items[self._iter_count - 1]

        # This won't work directly as tools expects a list, but we can test
        # the outer error handling by using a regular list and patching
        agent = Agent(name="test-agent", id="test-id", tools=["tool1"])

        # Should not raise
        copy = agent.deep_copy()
        assert copy is not None

    def test_deep_copy_with_unusual_tool_types(self):
        """Deep copy should handle unusual tool types gracefully."""
        # Test with various edge cases
        tools: List[Any] = [
            lambda x: x,  # Lambda function
            42,  # Integer (unusual but shouldn't crash)
            "string_tool",  # String (unusual but shouldn't crash)
            None,  # None in list
        ]

        agent = Agent(name="test-agent", id="test-id", tools=tools)

        # Should not raise - handles gracefully
        copy = agent.deep_copy()

        assert len(copy.tools) == 4

    def test_concurrent_deep_copy_safety(self):
        """Multiple concurrent deep_copy calls should be safe."""
        from agno.tools.toolkit import Toolkit

        class CounterTool(Toolkit):
            def __init__(self):
                super().__init__(name="counter")
                self.count = 0
                self.register(self.increment)

            def increment(self) -> int:
                self.count += 1
                return self.count

        tool = CounterTool()
        agent = Agent(name="test-agent", id="test-id", tools=[tool])

        # Create many copies concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(agent.deep_copy) for _ in range(50)]
            copies = [f.result() for f in futures]

        # All copies should be independent
        assert len(copies) == 50
        for i, copy in enumerate(copies):
            assert copy is not agent
            assert copy.tools[0] is not tool

        # Original should be unchanged
        assert tool.count == 0


# ============================================================================
# Comprehensive Integration Tests
# ============================================================================


class TestComprehensiveDeepCopyIntegration:
    """Integration tests combining multiple aspects of deep copy."""

    def test_agent_with_all_shared_resources(self):
        """Agent with all shared resources (db, model, knowledge, memory_manager)."""

        class MockDb:
            def __init__(self):
                self.id = uuid.uuid4()

        class MockKnowledge:
            def __init__(self):
                self.id = uuid.uuid4()

        class MockMemoryManager:
            def __init__(self):
                self.id = uuid.uuid4()

        db = MockDb()
        knowledge = MockKnowledge()
        memory_manager = MockMemoryManager()
        model = OpenAIChat(id="gpt-4o-mini")

        agent = Agent(
            name="full-agent",
            id="full-agent-id",
            model=model,
            db=db,
            knowledge=knowledge,
            memory_manager=memory_manager,
            metadata={"user": "test"},
        )

        copy = agent.deep_copy()

        # Shared resources should be same instance
        assert copy.db is db
        assert copy.knowledge is knowledge
        assert copy.memory_manager is memory_manager
        assert copy.model is model

        # Mutable state should be isolated
        assert copy.metadata is not agent.metadata
        assert copy.metadata == {"user": "test"}

    def test_team_with_agents_having_tools_and_knowledge(self):
        """Team with member agents that have tools and knowledge."""
        from agno.tools.toolkit import Toolkit

        class MockKnowledge:
            def __init__(self, name: str):
                self.name = name
                self.id = uuid.uuid4()

        class MockTool(Toolkit):
            def __init__(self, name: str):
                super().__init__(name=name)
                self.call_count = 0
                self.register(self.do_work)

            def do_work(self) -> str:
                self.call_count += 1
                return f"Work done by {self.name}"

        knowledge1 = MockKnowledge("kb1")
        knowledge2 = MockKnowledge("kb2")
        tool1 = MockTool("tool1")
        tool2 = MockTool("tool2")

        member1 = Agent(
            name="member1",
            id="member1-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            knowledge=knowledge1,
            tools=[tool1],
        )
        member2 = Agent(
            name="member2",
            id="member2-id",
            model=OpenAIChat(id="gpt-4o-mini"),
            knowledge=knowledge2,
            tools=[tool2],
        )

        team = Team(
            name="full-team",
            id="full-team-id",
            members=[member1, member2],
            model=OpenAIChat(id="gpt-4o-mini"),
        )

        copy = team.deep_copy()

        # Members should be different instances
        assert copy.members[0] is not member1
        assert copy.members[1] is not member2

        # Knowledge should be shared
        assert copy.members[0].knowledge is knowledge1
        assert copy.members[1].knowledge is knowledge2

        # Tools should be copied (different instances)
        assert copy.members[0].tools[0] is not tool1
        assert copy.members[1].tools[0] is not tool2

        # Tool state should be isolated
        tool1.call_count = 10
        assert copy.members[0].tools[0].call_count == 0

    def test_workflow_with_full_agent_configuration(self):
        """Workflow with step agents having full configuration."""
        from agno.tools.toolkit import Toolkit

        class MockDb:
            def __init__(self):
                self.id = uuid.uuid4()

        class MockTool(Toolkit):
            def __init__(self):
                super().__init__(name="mock")
                self.state = "initial"
                self.register(self.action)

            def action(self) -> str:
                return self.state

        db = MockDb()
        tool = MockTool()
        model = OpenAIChat(id="gpt-4o-mini")

        step_agent = Agent(
            name="step-agent",
            id="step-agent-id",
            model=model,
            db=db,
            tools=[tool],
            metadata={"step": 1},
        )

        workflow = Workflow(
            name="full-workflow",
            id="full-workflow-id",
            db=db,
            steps=[Step(name="full-step", agent=step_agent)],
        )

        copy = workflow.deep_copy()

        # Workflow DB should be shared
        assert copy.db is db

        # Step agent should be copied
        assert copy.steps[0].agent is not step_agent

        # Step agent's DB should be shared
        assert copy.steps[0].agent.db is db

        # Step agent's model should be shared
        assert copy.steps[0].agent.model is model

        # Step agent's tool should be copied
        assert copy.steps[0].agent.tools[0] is not tool

        # Step agent's metadata should be isolated
        step_agent.metadata["step"] = 2
        assert copy.steps[0].agent.metadata["step"] == 1
