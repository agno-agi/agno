"""Test Router functionality in workflows."""

from agno.run.workflow import WorkflowCompletedEvent
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def find_content_in_steps(step_output, search_text):
    """Recursively search for content in step output and its nested steps."""
    if search_text in step_output.content:
        return True
    if step_output.steps:
        return any(find_content_in_steps(nested_step, search_text) for nested_step in step_output.steps)
    return False


# ============================================================================
# TESTS (Fast - No Workflow Overhead)
# ============================================================================


def test_router_direct_execute():
    """Test Router.execute directly without workflow."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Output A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Output B"))

    def simple_selector(step_input: StepInput):
        if "A" in step_input.input:
            return [step_a]
        return [step_b]

    router = Router(
        name="test_router", selector=simple_selector, choices=[step_a, step_b], description="Direct router test"
    )

    # Test routing to step A
    input_a = StepInput(input="Choose A")
    results_a = router.execute(input_a)
    assert isinstance(results_a, StepOutput)
    assert len(results_a.steps) == 1
    assert results_a.steps[0].content == "Output A"
    assert results_a.steps[0].success

    # Test routing to step B
    input_b = StepInput(input="Choose B")
    results_b = router.execute(input_b)
    assert isinstance(results_b, StepOutput)
    assert len(results_b.steps) == 1
    assert results_b.steps[0].content == "Output B"
    assert results_b.steps[0].success


def test_router_direct_multiple_steps():
    """Test Router.execute with multiple steps selection."""
    step_1 = Step(name="step_1", executor=lambda x: StepOutput(content="Step 1"))
    step_2 = Step(name="step_2", executor=lambda x: StepOutput(content="Step 2"))
    step_3 = Step(name="step_3", executor=lambda x: StepOutput(content="Step 3"))

    def multi_selector(step_input: StepInput):
        if "multi" in step_input.input:
            return [step_1, step_2]
        return [step_3]

    router = Router(
        name="multi_router", selector=multi_selector, choices=[step_1, step_2, step_3], description="Multi-step router"
    )

    # Test multiple steps selection
    input_multi = StepInput(input="Choose multi")
    results_multi = router.execute(input_multi)
    assert isinstance(results_multi, StepOutput)
    assert len(results_multi.steps) == 2
    assert results_multi.steps[0].content == "Step 1"
    assert results_multi.steps[1].content == "Step 2"
    assert all(r.success for r in results_multi.steps)

    # Test single step selection
    input_single = StepInput(input="Choose single")
    results_single = router.execute(input_single)
    assert isinstance(results_single, StepOutput)
    assert len(results_single.steps) == 1
    assert results_single.steps[0].content == "Step 3"
    assert results_single.steps[0].success


def test_router_direct_with_steps_component():
    """Test Router.execute with Steps component."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="B"))
    steps_sequence = Steps(name="sequence", steps=[step_a, step_b])

    single_step = Step(name="single", executor=lambda x: StepOutput(content="Single"))

    def sequence_selector(step_input: StepInput):
        if "sequence" in step_input.input:
            return [steps_sequence]
        return [single_step]

    router = Router(
        name="sequence_router",
        selector=sequence_selector,
        choices=[steps_sequence, single_step],
        description="Sequence router",
    )

    # Test routing to Steps sequence
    input_seq = StepInput(input="Choose sequence")
    results_seq = router.execute(input_seq)
    # Steps component returns multiple outputs
    assert isinstance(results_seq, StepOutput)
    assert len(results_seq.steps) >= 1
    # Check that we have content from both steps using recursive search
    assert find_content_in_steps(results_seq, "A")
    assert find_content_in_steps(results_seq, "B")


def test_router_direct_error_handling():
    """Test Router.execute error handling."""

    def failing_executor(step_input: StepInput) -> StepOutput:
        raise ValueError("Test error")

    failing_step = Step(name="failing", executor=failing_executor)
    success_step = Step(name="success", executor=lambda x: StepOutput(content="Success"))

    def error_selector(step_input: StepInput):
        if "fail" in step_input.input:
            return [failing_step]
        return [success_step]

    router = Router(
        name="error_router",
        selector=error_selector,
        choices=[failing_step, success_step],
        description="Error handling router",
    )

    # Test error case
    input_fail = StepInput(input="Make it fail")
    results_fail = router.execute(input_fail)
    assert isinstance(results_fail, StepOutput)
    assert len(results_fail.steps) == 1
    assert not results_fail.steps[0].success
    assert "Test error" in results_fail.steps[0].content

    # Test success case
    input_success = StepInput(input="Make it success")
    results_success = router.execute(input_success)
    assert isinstance(results_success, StepOutput)
    assert len(results_success.steps) == 1
    assert results_success.steps[0].success
    assert results_success.steps[0].content == "Success"


def test_router_direct_chaining():
    """Test Router.execute with step chaining (sequential execution)."""

    def step_1_executor(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Step 1: {step_input.input}")

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

    input_test = StepInput(input="Hello")
    results = router.execute(input_test)

    assert isinstance(results, StepOutput)
    assert len(results.steps) == 2
    assert results.steps[0].content == "Step 1: Hello"
    assert results.steps[1].content == "Step 2: Step 1: Hello"
    assert all(r.success for r in results.steps)


# ============================================================================
# EXISTING INTEGRATION TESTS (With Workflow)
# ============================================================================


def test_basic_routing(shared_db):
    """Test basic routing based on input."""
    tech_step = Step(name="tech", executor=lambda x: StepOutput(content="Tech content"))
    general_step = Step(name="general", executor=lambda x: StepOutput(content="General content"))

    def route_selector(step_input: StepInput):
        """Select between tech and general steps."""
        if "tech" in step_input.input.lower():
            return [tech_step]
        return [general_step]

    workflow = Workflow(
        name="Basic Router",
        db=shared_db,
        steps=[
            Router(
                name="router",
                selector=route_selector,
                choices=[tech_step, general_step],
                description="Basic routing",
            )
        ],
    )

    tech_response = workflow.run(input="tech topic")
    assert find_content_in_steps(tech_response.step_results[0], "Tech content")

    general_response = workflow.run(input="general topic")
    assert find_content_in_steps(general_response.step_results[0], "General content")


def test_streaming(shared_db):
    """Test router with streaming."""
    stream_step = Step(name="stream", executor=lambda x: StepOutput(content="Stream content"))
    alt_step = Step(name="alt", executor=lambda x: StepOutput(content="Alt content"))

    def route_selector(step_input: StepInput):
        return [stream_step]

    workflow = Workflow(
        name="Stream Router",
        db=shared_db,
        steps=[
            Router(
                name="router",
                selector=route_selector,
                choices=[stream_step, alt_step],
                description="Stream routing",
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert find_content_in_steps(completed_events[0].step_results[0], "Stream content")


def test_agent_routing(shared_db, test_agent):
    """Test routing to agent steps."""
    agent_step = Step(name="agent_step", agent=test_agent)
    function_step = Step(name="function_step", executor=lambda x: StepOutput(content="Function output"))

    def route_selector(step_input: StepInput):
        return [agent_step]

    workflow = Workflow(
        name="Agent Router",
        db=shared_db,
        steps=[
            Router(
                name="router",
                selector=route_selector,
                choices=[agent_step, function_step],
                description="Agent routing",
            )
        ],
    )

    response = workflow.run(input="test")
    # Check if the router executed successfully (either has success in nested steps or router itself succeeded)
    assert response.step_results[0].success or any(
        step.success for step in response.step_results[0].steps if response.step_results[0].steps
    )


def test_mixed_routing(shared_db, test_agent, test_team):
    """Test routing to mix of function, agent, and team."""
    function_step = Step(name="function", executor=lambda x: StepOutput(content="Function output"))
    agent_step = Step(name="agent", agent=test_agent)
    team_step = Step(name="team", team=test_team)

    def route_selector(step_input: StepInput):
        if "function" in step_input.input:
            return [function_step]
        elif "agent" in step_input.input:
            return [agent_step]
        return [team_step]

    workflow = Workflow(
        name="Mixed Router",
        db=shared_db,
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
    function_response = workflow.run(input="test function")
    assert find_content_in_steps(function_response.step_results[0], "Function output")

    # Test agent route
    agent_response = workflow.run(input="test agent")
    assert agent_response.step_results[0].success or any(
        step.success for step in agent_response.step_results[0].steps if agent_response.step_results[0].steps
    )

    # Test team route
    team_response = workflow.run(input="test team")
    assert team_response.step_results[0].success or any(
        step.success for step in team_response.step_results[0].steps if team_response.step_results[0].steps
    )


def test_multiple_step_routing(shared_db):
    """Test routing to multiple steps."""
    research_step = Step(name="research", executor=lambda x: StepOutput(content="Research output"))
    analysis_step = Step(name="analysis", executor=lambda x: StepOutput(content="Analysis output"))
    summary_step = Step(name="summary", executor=lambda x: StepOutput(content="Summary output"))

    def route_selector(step_input: StepInput):
        if "research" in step_input.input:
            return [research_step, analysis_step]
        return [summary_step]

    workflow = Workflow(
        name="Multiple Steps Router",
        db=shared_db,
        steps=[
            Router(
                name="router",
                selector=route_selector,
                choices=[research_step, analysis_step, summary_step],
                description="Multiple step routing",
            )
        ],
    )

    response = workflow.run(input="test research")
    router_output = response.step_results[0]
    assert len(router_output.steps) == 2
    assert find_content_in_steps(router_output, "Research output")
    assert find_content_in_steps(router_output, "Analysis output")


def test_route_steps(shared_db):
    """Test routing to multiple steps."""
    research_step = Step(name="research", executor=lambda x: StepOutput(content="Research output"))
    analysis_step = Step(name="analysis", executor=lambda x: StepOutput(content="Analysis output"))
    research_sequence = Steps(name="research_sequence", steps=[research_step, analysis_step])

    summary_step = Step(name="summary", executor=lambda x: StepOutput(content="Summary output"))

    def route_selector(step_input: StepInput):
        if "research" in step_input.input:
            return [research_sequence]
        return [summary_step]

    workflow = Workflow(
        name="Multiple Steps Router",
        db=shared_db,
        steps=[
            Router(
                name="router",
                selector=route_selector,
                choices=[research_sequence, summary_step],
                description="Multiple step routing",
            )
        ],
    )

    response = workflow.run(input="test research")

    router_results = response.step_results[0]

    # Check that we got results from both steps in the sequence
    assert isinstance(router_results, StepOutput)
    assert len(router_results.steps) >= 1  # Steps component should have nested results
    assert find_content_in_steps(router_results, "Research output")
    assert find_content_in_steps(router_results, "Analysis output")
