"""Test Router functionality in workflows."""

from agno.run.v2.workflow import WorkflowCompletedEvent
from agno.workflow.v2.router import Router
from agno.workflow.v2.step import Step
from agno.workflow.v2.steps import Steps
from agno.workflow.v2.types import StepInput, StepOutput
from agno.workflow.v2.workflow import Workflow

# ============================================================================
# TESTS (Fast - No Workflow Overhead)
# ============================================================================


def test_router_direct_execute():
    """Test Router.execute directly without workflow."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Output A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Output B"))

    def simple_selector(step_input: StepInput):
        if "A" in step_input.message:
            return [step_a]
        return [step_b]

    router = Router(
        name="test_router", selector=simple_selector, choices=[step_a, step_b], description="Direct router test"
    )

    # Test routing to step A
    input_a = StepInput(message="Choose A")
    results_a = router.execute(input_a)
    assert len(results_a) == 1
    assert results_a[0].content == "Output A"
    assert results_a[0].success

    # Test routing to step B
    input_b = StepInput(message="Choose B")
    results_b = router.execute(input_b)
    assert len(results_b) == 1
    assert results_b[0].content == "Output B"
    assert results_b[0].success


def test_router_direct_multiple_steps():
    """Test Router.execute with multiple steps selection."""
    step_1 = Step(name="step_1", executor=lambda x: StepOutput(content="Step 1"))
    step_2 = Step(name="step_2", executor=lambda x: StepOutput(content="Step 2"))
    step_3 = Step(name="step_3", executor=lambda x: StepOutput(content="Step 3"))

    def multi_selector(step_input: StepInput):
        if "multi" in step_input.message:
            return [step_1, step_2]
        return [step_3]

    router = Router(
        name="multi_router", selector=multi_selector, choices=[step_1, step_2, step_3], description="Multi-step router"
    )

    # Test multiple steps selection
    input_multi = StepInput(message="Choose multi")
    results_multi = router.execute(input_multi)
    assert len(results_multi) == 2
    assert results_multi[0].content == "Step 1"
    assert results_multi[1].content == "Step 2"
    assert all(r.success for r in results_multi)

    # Test single step selection
    input_single = StepInput(message="Choose single")
    results_single = router.execute(input_single)
    assert len(results_single) == 1
    assert results_single[0].content == "Step 3"
    assert results_single[0].success


def test_router_direct_with_steps_component():
    """Test Router.execute with Steps component."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="B"))
    steps_sequence = Steps(name="sequence", steps=[step_a, step_b])

    single_step = Step(name="single", executor=lambda x: StepOutput(content="Single"))

    def sequence_selector(step_input: StepInput):
        if "sequence" in step_input.message:
            return [steps_sequence]
        return [single_step]

    router = Router(
        name="sequence_router",
        selector=sequence_selector,
        choices=[steps_sequence, single_step],
        description="Sequence router",
    )

    # Test routing to Steps sequence
    input_seq = StepInput(message="Choose sequence")
    results_seq = router.execute(input_seq)
    # Steps component returns multiple outputs
    assert len(results_seq) >= 1
    # Check that we have content from both steps
    all_content = " ".join([r.content for r in results_seq])
    assert "A" in all_content
    assert "B" in all_content

    # Test routing to single step
    input_single = StepInput(message="Choose single")
    results_single = router.execute(input_single)
    assert len(results_single) == 1
    assert results_single[0].content == "Single"


def test_router_direct_error_handling():
    """Test Router.execute error handling."""

    def failing_executor(step_input: StepInput) -> StepOutput:
        raise ValueError("Test error")

    failing_step = Step(name="failing", executor=failing_executor)
    success_step = Step(name="success", executor=lambda x: StepOutput(content="Success"))

    def error_selector(step_input: StepInput):
        if "fail" in step_input.message:
            return [failing_step]
        return [success_step]

    router = Router(
        name="error_router",
        selector=error_selector,
        choices=[failing_step, success_step],
        description="Error handling router",
    )

    # Test error case
    input_fail = StepInput(message="Make it fail")
    results_fail = router.execute(input_fail)
    assert len(results_fail) == 1
    assert not results_fail[0].success
    assert "Test error" in results_fail[0].content

    # Test success case
    input_success = StepInput(message="Make it success")
    results_success = router.execute(input_success)
    assert len(results_success) == 1
    assert results_success[0].success
    assert results_success[0].content == "Success"


def test_router_direct_chaining():
    """Test Router.execute with step chaining (sequential execution)."""

    def step_1_executor(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Step 1: {step_input.message}")

    def step_2_executor(step_input: StepInput) -> StepOutput:
        # Should receive output from step 1
        return StepOutput(content=f"Step 2: {step_input.previous_step_content}")

    step_1 = Step(name="step_1", executor=step_1_executor)
    step_2 = Step(name="step_2", executor=step_2_executor)

    def chain_selector(step_input: StepInput):
        return [step_1, step_2]

    router = Router(
        name="chain_router", selector=chain_selector, choices=[step_1, step_2], description="Chaining router"
    )

    input_test = StepInput(message="Hello")
    results = router.execute(input_test)

    assert len(results) == 2
    assert results[0].content == "Step 1: Hello"
    assert results[1].content == "Step 2: Step 1: Hello"
    assert all(r.success for r in results)


# ============================================================================
# EXISTING INTEGRATION TESTS (With Workflow)
# ============================================================================


def test_basic_routing(workflow_storage):
    """Test basic routing based on input."""
    tech_step = Step(name="tech", executor=lambda x: StepOutput(content="Tech content"))
    general_step = Step(name="general", executor=lambda x: StepOutput(content="General content"))

    def route_selector(step_input: StepInput):
        """Select between tech and general steps."""
        if "tech" in step_input.message.lower():
            return [tech_step]
        return [general_step]

    workflow = Workflow(
        name="Basic Router",
        storage=workflow_storage,
        steps=[
            Router(
                name="router",
                selector=route_selector,
                choices=[tech_step, general_step],
                description="Basic routing",
            )
        ],
    )

    tech_response = workflow.run(message="tech topic")
    assert tech_response.step_responses[0][0].content == "Tech content"

    general_response = workflow.run(message="general topic")
    assert general_response.step_responses[0][0].content == "General content"


def test_streaming(workflow_storage):
    """Test router with streaming."""
    stream_step = Step(name="stream", executor=lambda x: StepOutput(content="Stream content"))
    alt_step = Step(name="alt", executor=lambda x: StepOutput(content="Alt content"))

    def route_selector(step_input: StepInput):
        return [stream_step]

    workflow = Workflow(
        name="Stream Router",
        storage=workflow_storage,
        steps=[
            Router(
                name="router",
                selector=route_selector,
                choices=[stream_step, alt_step],
                description="Stream routing",
            )
        ],
    )

    events = list(workflow.run(message="test", stream=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert "Stream content" in completed_events[0].content


def test_agent_routing(workflow_storage, test_agent):
    """Test routing to agent steps."""
    agent_step = Step(name="agent_step", agent=test_agent)
    function_step = Step(name="function_step", executor=lambda x: StepOutput(content="Function output"))

    def route_selector(step_input: StepInput):
        return [agent_step]

    workflow = Workflow(
        name="Agent Router",
        storage=workflow_storage,
        steps=[
            Router(
                name="router",
                selector=route_selector,
                choices=[agent_step, function_step],
                description="Agent routing",
            )
        ],
    )

    response = workflow.run(message="test")
    assert response.step_responses[0][0].success


def test_mixed_routing(workflow_storage, test_agent, test_team):
    """Test routing to mix of function, agent, and team."""
    function_step = Step(name="function", executor=lambda x: StepOutput(content="Function output"))
    agent_step = Step(name="agent", agent=test_agent)
    team_step = Step(name="team", team=test_team)

    def route_selector(step_input: StepInput):
        if "function" in step_input.message:
            return [function_step]
        elif "agent" in step_input.message:
            return [agent_step]
        return [team_step]

    workflow = Workflow(
        name="Mixed Router",
        storage=workflow_storage,
        steps=[
            Router(
                name="router",
                selector=route_selector,
                choices=[function_step, agent_step, team_step],
                description="Mixed routing",
            )
        ],
    )

    # Test function route
    function_response = workflow.run(message="test function")
    assert "Function output" in function_response.step_responses[0][0].content

    # Test agent route
    agent_response = workflow.run(message="test agent")
    assert agent_response.step_responses[0][0].success

    # Test team route
    team_response = workflow.run(message="test team")
    assert team_response.step_responses[0][0].success


def test_multiple_step_routing(workflow_storage):
    """Test routing to multiple steps."""
    research_step = Step(name="research", executor=lambda x: StepOutput(content="Research output"))
    analysis_step = Step(name="analysis", executor=lambda x: StepOutput(content="Analysis output"))
    summary_step = Step(name="summary", executor=lambda x: StepOutput(content="Summary output"))

    def route_selector(step_input: StepInput):
        if "research" in step_input.message:
            return [research_step, analysis_step]
        return [summary_step]

    workflow = Workflow(
        name="Multiple Steps Router",
        storage=workflow_storage,
        steps=[
            Router(
                name="router",
                selector=route_selector,
                choices=[research_step, analysis_step, summary_step],
                description="Multiple step routing",
            )
        ],
    )

    response = workflow.run(message="test research")
    assert len(response.step_responses[0]) == 2
    assert "Research output" in response.step_responses[0][0].content
    assert "Analysis output" in response.step_responses[0][1].content


def test_route_steps(workflow_storage):
    """Test routing to multiple steps."""
    research_step = Step(name="research", executor=lambda x: StepOutput(content="Research output"))
    analysis_step = Step(name="analysis", executor=lambda x: StepOutput(content="Analysis output"))
    research_sequence = Steps(name="research_sequence", steps=[research_step, analysis_step])

    summary_step = Step(name="summary", executor=lambda x: StepOutput(content="Summary output"))

    def route_selector(step_input: StepInput):
        if "research" in step_input.message:
            return [research_sequence]
        return [summary_step]

    workflow = Workflow(
        name="Multiple Steps Router",
        storage=workflow_storage,
        steps=[
            Router(
                name="router",
                selector=route_selector,
                choices=[research_sequence, summary_step],
                description="Multiple step routing",
            )
        ],
    )

    response = workflow.run(message="test research")

    router_results = response.step_responses[0]

    # Check that we got results from both steps in the sequence
    assert len(router_results) == 2
    assert "Research output" in router_results[0].content
    assert "Analysis output" in router_results[1].content
