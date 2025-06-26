"""Test Router functionality in workflows."""

import pytest
from typing import List

from agno.agent.agent import Agent
from agno.storage.workflow.sqlite import SqliteWorkflowStorage
from agno.workflow.v2.router import Router
from agno.workflow.v2.step import Step
from agno.workflow.v2.types import StepInput, StepOutput
from agno.workflow.v2.workflow import Workflow, WorkflowRunResponse
from agno.run.base import RunStatus

# Mock step functions for testing


def research_step_function(step_input: StepInput) -> StepOutput:
    """Simple research function step."""
    message = step_input.previous_step_content or step_input.message or ""
    return StepOutput(
        step_name="research_step_function",
        content=f"Research results: {message[:50]}...",
    )


def hackernews_research_function(step_input: StepInput) -> StepOutput:
    """HackerNews research function step."""
    message = step_input.previous_step_content or step_input.message or ""
    return StepOutput(
        step_name="hackernews_research_function",
        content=f"HackerNews research on: {message[:50]}... Found latest tech discussions.",
    )


def web_research_function(step_input: StepInput) -> StepOutput:
    """Web research function step."""
    message = step_input.previous_step_content or step_input.message or ""
    return StepOutput(
        step_name="web_research_function",
        content=f"Web research on: {message[:50]}... Found comprehensive information.",
    )


def summarize_function(step_input: StepInput) -> StepOutput:
    """Summarize function step."""
    previous_content = step_input.previous_step_content or ""
    return StepOutput(
        step_name="summarize_function",
        content=f"Summary: {previous_content[:100]}... Key insights and findings.",
    )


def publish_function(step_input: StepInput) -> StepOutput:
    """Publish function step."""
    previous_content = step_input.previous_step_content or ""
    return StepOutput(
        step_name="publish_function",
        content=f"Published content based on: {previous_content[:100]}...",
    )

# Router selector functions


def tech_topic_router(step_input: StepInput) -> List[Step]:
    """Route based on whether topic is tech-related."""
    topic = step_input.previous_step_content or step_input.message or ""
    topic = topic.lower()

    tech_keywords = [
        "startup", "programming", "ai", "machine learning", "software",
        "developer", "coding", "tech", "blockchain", "cryptocurrency"
    ]

    hackernews_step = Step(name="hackernews_research",
                           executor=hackernews_research_function)
    web_step = Step(name="web_research", executor=web_research_function)

    if any(keyword in topic for keyword in tech_keywords):
        return [hackernews_step]
    else:
        return [web_step]


def multi_step_router(step_input: StepInput) -> List[Step]:
    """Router that returns multiple steps for complex topics."""
    topic = step_input.previous_step_content or step_input.message or ""
    topic = topic.lower()

    hackernews_step = Step(name="hackernews_research",
                           executor=hackernews_research_function)
    web_step = Step(name="web_research", executor=web_research_function)

    if "comprehensive" in topic:
        # Return multiple steps for comprehensive research
        return [hackernews_step, web_step]
    elif "tech" in topic:
        return [hackernews_step]
    else:
        return [web_step]


def empty_router(step_input: StepInput) -> List[Step]:
    """Router that returns empty list."""
    return []


def single_step_router(step_input: StepInput) -> Step:
    """Router that returns a single Step (not List[Step])."""
    web_step = Step(name="web_research", executor=web_research_function)
    return web_step


def failing_router(step_input: StepInput) -> List[Step]:
    """Router that raises an exception."""
    raise ValueError("Router failed!")

# Router evaluators


def always_use_hackernews(step_input: StepInput) -> bool:
    """Always route to HackerNews."""
    return True


def never_use_hackernews(step_input: StepInput) -> bool:
    """Never route to HackerNews."""
    return False

# Test fixtures


@pytest.fixture
def workflow_storage():
    """Create a workflow storage for testing."""
    return SqliteWorkflowStorage(
        table_name="test_router_workflow_runs",
        db_file=":memory:",
    )


@pytest.fixture
def simple_agent():
    """Create a simple agent for testing."""
    return Agent(
        name="TestAgent",
        instructions="You are a test agent.",
    )


class TestRouterSteps:
    """Test Router functionality."""

    def test_router_tech_topic_non_streaming(self, workflow_storage):
        """Test router with tech topic (non-streaming)."""
        research_step = Step(name="research", executor=research_step_function)

        workflow = Workflow(
            name="Tech Router Workflow",
            storage=workflow_storage,
            steps=[
                research_step,
                Router(
                    name="tech_router",
                    selector=tech_topic_router,
                    choices=[],  # Choices are handled in selector
                    description="Route based on tech topic",
                ),
                Step(name="publish", executor=publish_function),
            ],
        )

        response = workflow.run(
            message="Latest AI and machine learning developments")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.status == RunStatus.completed
        # research + router + publish
        assert len(response.step_responses) == 3

        # Check router output
        router_outputs = response.step_responses[1]
        assert isinstance(router_outputs, list)
        assert len(router_outputs) == 1
        assert router_outputs[0].step_name == "hackernews_research"
        assert "HackerNews research" in router_outputs[0].content

    def test_router_non_tech_topic_non_streaming(self, workflow_storage):
        """Test router with non-tech topic (non-streaming)."""
        research_step = Step(name="research", executor=research_step_function)

        workflow = Workflow(
            name="General Router Workflow",
            storage=workflow_storage,
            steps=[
                research_step,
                Router(
                    name="general_router",
                    selector=tech_topic_router,
                    choices=[],
                    description="Route based on topic type",
                ),
                Step(name="publish", executor=publish_function),
            ],
        )

        response = workflow.run(message="Cooking recipes and nutrition tips")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.status == RunStatus.completed
        # research + router + publish
        assert len(response.step_responses) == 3

        # Check router output
        router_outputs = response.step_responses[1]
        assert isinstance(router_outputs, list)
        assert len(router_outputs) == 1
        assert router_outputs[0].step_name == "web_research"
        assert "Web research" in router_outputs[0].content

    def test_router_multi_step_non_streaming(self, workflow_storage):
        """Test router that returns multiple steps (non-streaming)."""
        research_step = Step(name="research", executor=research_step_function)

        workflow = Workflow(
            name="Multi-Step Router Workflow",
            storage=workflow_storage,
            steps=[
                research_step,
                Router(
                    name="multi_router",
                    selector=multi_step_router,
                    choices=[],
                    description="Route to multiple steps for comprehensive research",
                ),
                Step(name="summarize", executor=summarize_function),
            ],
        )

        response = workflow.run(
            message="Comprehensive analysis of tech trends")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.status == RunStatus.completed
        # research + router + summarize
        assert len(response.step_responses) == 3

        # Check router output - should have multiple steps
        router_outputs = response.step_responses[1]
        assert isinstance(router_outputs, list)
        assert len(router_outputs) == 2
        assert router_outputs[0].step_name == "hackernews_research"
        assert router_outputs[1].step_name == "web_research"

    def test_router_empty_selection_non_streaming(self, workflow_storage):
        """Test router that returns empty list (non-streaming)."""
        research_step = Step(name="research", executor=research_step_function)

        workflow = Workflow(
            name="Empty Router Workflow",
            storage=workflow_storage,
            steps=[
                research_step,
                Router(
                    name="empty_router",
                    selector=empty_router,
                    choices=[],
                    description="Router that selects no steps",
                ),
                Step(name="publish", executor=publish_function),
            ],
        )

        response = workflow.run(message="Any topic")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.status == RunStatus.completed
        # research + router (empty) + publish
        assert len(response.step_responses) == 3

        # Check router output - should be empty
        router_outputs = response.step_responses[1]
        assert isinstance(router_outputs, list)
        assert len(router_outputs) == 0

    def test_router_single_step_return_non_streaming(self, workflow_storage):
        """Test router that returns single Step instead of List[Step] (non-streaming)."""
        research_step = Step(name="research", executor=research_step_function)

        workflow = Workflow(
            name="Single Step Router Workflow",
            storage=workflow_storage,
            steps=[
                research_step,
                Router(
                    name="single_router",
                    selector=single_step_router,
                    choices=[],
                    description="Router that returns single step",
                ),
                Step(name="publish", executor=publish_function),
            ],
        )

        response = workflow.run(message="Any topic")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.status == RunStatus.completed
        # research + router + publish
        assert len(response.step_responses) == 3

        # Check router output
        router_outputs = response.step_responses[1]
        assert isinstance(router_outputs, list)
        assert len(router_outputs) == 1
        assert router_outputs[0].step_name == "web_research"

    def test_router_with_agent_steps(self, workflow_storage, simple_agent):
        """Test router with agent-based steps."""
        hackernews_step = Step(name="hackernews_research", agent=simple_agent)
        web_step = Step(name="web_research", agent=simple_agent)

        def agent_router(step_input: StepInput) -> List[Step]:
            topic = step_input.message or ""
            if "tech" in topic.lower():
                return [hackernews_step]
            return [web_step]

        workflow = Workflow(
            name="Agent Router Workflow",
            storage=workflow_storage,
            steps=[
                Router(
                    name="agent_router",
                    selector=agent_router,
                    choices=[hackernews_step, web_step],
                    description="Route to agent steps",
                ),
            ],
        )

        response = workflow.run(message="Tech developments")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.status == RunStatus.completed

    def test_router_streaming(self, workflow_storage):
        """Test router with streaming enabled."""
        research_step = Step(name="research", executor=research_step_function)

        workflow = Workflow(
            name="Streaming Router Workflow",
            storage=workflow_storage,
            steps=[
                research_step,
                Router(
                    name="streaming_router",
                    selector=tech_topic_router,
                    choices=[],
                    description="Router with streaming",
                ),
                Step(name="publish", executor=publish_function),
            ],
        )

        # Collect streaming events
        events = []
        for event in workflow.run(
            message="AI and machine learning trends",
            stream=True
        ):
            events.append(event)

        # Verify streaming events were generated
        assert len(events) > 0

        # Check for final completion event
        from agno.run.v2.workflow import WorkflowCompletedEvent
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert completed_events[0].content is not None

    def test_router_step_chaining(self, workflow_storage):
        """Test that router properly chains step outputs."""
        def chaining_router(step_input: StepInput) -> List[Step]:
            # First step processes input
            step1 = Step(name="step1", executor=lambda si: StepOutput(
                step_name="step1",
                content=f"Step1: {si.previous_step_content or si.message}"
            ))
            # Second step should receive first step's output
            step2 = Step(name="step2", executor=lambda si: StepOutput(
                step_name="step2",
                content=f"Step2: {si.previous_step_content}"
            ))
            return [step1, step2]

        workflow = Workflow(
            name="Chaining Router Workflow",
            storage=workflow_storage,
            steps=[
                Router(
                    name="chaining_router",
                    selector=chaining_router,
                    choices=[],
                    description="Test step chaining in router",
                ),
            ],
        )

        response = workflow.run(message="Initial message")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.status == RunStatus.completed

        # Check that steps were chained properly
        router_outputs = response.step_responses[0]
        assert isinstance(router_outputs, list)
        assert len(router_outputs) == 2

        # Step 1 should have processed the initial message
        assert "Step1: Initial message" in router_outputs[0].content

        # Step 2 should have received Step 1's output
        assert "Step2: Step1: Initial message" in router_outputs[1].content

    def test_router_error_handling(self, workflow_storage):
        """Test router error handling when selector fails."""
        workflow = Workflow(
            name="Error Router Workflow",
            storage=workflow_storage,
            steps=[
                Router(
                    name="failing_router",
                    selector=failing_router,
                    choices=[],
                    description="Router that fails",
                ),
            ],
        )

        # The workflow should handle the router error gracefully
        response = workflow.run(message="Any topic")

        assert isinstance(response, WorkflowRunResponse)
        # Should fail due to router error
        assert response.status == RunStatus.error

    def test_router_step_error_handling(self, workflow_storage):
        """Test router handling when selected step fails."""
        def failing_step(step_input: StepInput) -> StepOutput:
            raise ValueError("Step failed!")

        def error_router(step_input: StepInput) -> List[Step]:
            return [Step(name="failing_step", executor=failing_step)]

        workflow = Workflow(
            name="Step Error Router Workflow",
            storage=workflow_storage,
            steps=[
                Router(
                    name="error_router",
                    selector=error_router,
                    choices=[],
                    description="Router with failing step",
                ),
                Step(name="final_step", executor=publish_function),
            ],
        )

        response = workflow.run(message="Any topic")

        assert isinstance(response, WorkflowRunResponse)
        # Router should handle step error and continue
        assert len(response.step_responses) >= 1

        # Check that error was captured in router outputs
        router_outputs = response.step_responses[0]
        assert isinstance(router_outputs, list)
        assert len(router_outputs) == 1
        assert router_outputs[0].success == False
        assert "Step failed!" in router_outputs[0].content

    async def test_router_async_non_streaming(self, workflow_storage):
        """Test router with async execution (non-streaming)."""
        research_step = Step(name="research", executor=research_step_function)

        workflow = Workflow(
            name="Async Router Workflow",
            storage=workflow_storage,
            steps=[
                research_step,
                Router(
                    name="async_router",
                    selector=tech_topic_router,
                    choices=[],
                    description="Async router test",
                ),
                Step(name="publish", executor=publish_function),
            ],
        )

        response = await workflow.arun(message="AI developments")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.status == RunStatus.completed

    async def test_router_async_streaming(self, workflow_storage):
        """Test router with async streaming execution."""
        research_step = Step(name="research", executor=research_step_function)

        workflow = Workflow(
            name="Async Streaming Router Workflow",
            storage=workflow_storage,
            steps=[
                research_step,
                Router(
                    name="async_streaming_router",
                    selector=tech_topic_router,
                    choices=[],
                    description="Async streaming router test",
                ),
                Step(name="publish", executor=publish_function),
            ],
        )

        # Collect async streaming events
        events = []
        async for event in await workflow.arun(
            message="Machine learning trends",
            stream=True
        ):
            events.append(event)

        # Verify streaming events were generated
        assert len(events) > 0

        # Check for final completion event
        from agno.run.v2.workflow import WorkflowCompletedEvent
        completed_events = [e for e in events if isinstance(
            e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert completed_events[0].content is not None

    def test_router_with_previous_step_content(self, workflow_storage):
        """Test router using previous step content for routing decision."""
        def content_based_router(step_input: StepInput) -> List[Step]:
            content = step_input.previous_step_content or ""

            hackernews_step = Step(
                name="hackernews_research", executor=hackernews_research_function)
            web_step = Step(name="web_research",
                            executor=web_research_function)

            if "technical" in content.lower():
                return [hackernews_step]
            else:
                return [web_step]

        research_step = Step(
            name="research",
            executor=lambda si: StepOutput(
                step_name="research",
                content="Technical analysis required for this topic"
            )
        )

        workflow = Workflow(
            name="Content-Based Router Workflow",
            storage=workflow_storage,
            steps=[
                research_step,
                Router(
                    name="content_router",
                    selector=content_based_router,
                    choices=[],
                    description="Route based on previous step content",
                ),
            ],
        )

        response = workflow.run(message="Any initial message")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.status == RunStatus.completed

        # Check that router selected HackerNews based on "technical" in previous content
        router_outputs = response.step_responses[1]
        assert isinstance(router_outputs, list)
        assert len(router_outputs) == 1
        assert router_outputs[0].step_name == "hackernews_research"

    def test_nested_routers(self, workflow_storage):
        """Test nested routers within routers."""
        def outer_router(step_input: StepInput) -> List[Step]:
            topic = step_input.message or ""

            def inner_router(inner_input: StepInput) -> List[Step]:
                content = inner_input.previous_step_content or inner_input.message or ""
                if "detailed" in content.lower():
                    return [Step(name="detailed_analysis", executor=lambda si: StepOutput(
                        step_name="detailed_analysis",
                        content="Detailed analysis completed"
                    ))]
                return []

            if "complex" in topic.lower():
                return [
                    Step(name="initial_research", executor=lambda si: StepOutput(
                        step_name="initial_research",
                        content="Initial research with detailed requirements"
                    )),
                    Router(
                        name="inner_router",
                        selector=inner_router,
                        choices=[],
                        description="Inner router for detailed analysis",
                    )
                ]
            return [Step(name="simple_research", executor=research_step_function)]

        workflow = Workflow(
            name="Nested Router Workflow",
            storage=workflow_storage,
            steps=[
                Router(
                    name="outer_router",
                    selector=outer_router,
                    choices=[],
                    description="Outer router with nested routing",
                ),
            ],
        )

        response = workflow.run(message="Complex analysis needed")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.status == RunStatus.completed

        # Check that outer router executed multiple steps including inner router
        router_outputs = response.step_responses[0]
        assert isinstance(router_outputs, list)
        # At least initial_research + inner_router results
        assert len(router_outputs) >= 2

    def test_router_with_workflow_message_access(self, workflow_storage):
        """Test router accessing original workflow message."""
        def message_router(step_input: StepInput) -> List[Step]:
            # Should have access to original workflow message
            workflow_msg = step_input.workflow_message or ""

            if "priority" in workflow_msg.lower():
                return [Step(name="priority_research", executor=lambda si: StepOutput(
                    step_name="priority_research",
                    content="Priority research completed"
                ))]
            return [Step(name="normal_research", executor=research_step_function)]

        # Add an intermediate step to change previous_step_content
        intermediate_step = Step(
            name="intermediate",
            executor=lambda si: StepOutput(
                step_name="intermediate",
                content="Processed input"
            )
        )

        workflow = Workflow(
            name="Workflow Message Router",
            storage=workflow_storage,
            steps=[
                intermediate_step,
                Router(
                    name="message_router",
                    selector=message_router,
                    choices=[],
                    description="Route based on original workflow message",
                ),
            ],
        )

        response = workflow.run(message="Priority analysis required")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.status == RunStatus.completed

        # Check that router selected priority research based on original message
        router_outputs = response.step_responses[1]
        assert isinstance(router_outputs, list)
        assert len(router_outputs) == 1
        assert router_outputs[0].step_name == "priority_research"
