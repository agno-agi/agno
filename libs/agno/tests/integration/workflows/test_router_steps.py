"""Test Router functionality in workflows."""

import pytest

from agno.run.workflow import (
    RouterExecutionCompletedEvent,
    RouterExecutionStartedEvent,
    StepCompletedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
)
from agno.workflow.cel import CEL_AVAILABLE
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


# ============================================================================
# EARLY TERMINATION / STOP PROPAGATION TESTS
# ============================================================================


def early_stop_step(step_input: StepInput) -> StepOutput:
    """Step that requests early termination."""
    return StepOutput(
        content="Early stop requested",
        success=True,
        stop=True,
    )


def should_not_run_step(step_input: StepInput) -> StepOutput:
    """Step that should not run after early stop."""
    return StepOutput(
        content="This step should not have run",
        success=True,
    )


def normal_step(step_input: StepInput) -> StepOutput:
    """Normal step that doesn't request stop."""
    return StepOutput(
        content="Normal step output",
        success=True,
    )


def test_router_propagates_stop_flag():
    """Test that Router propagates stop flag from inner steps."""
    step_stop = Step(name="stop_step", executor=early_stop_step)
    step_normal = Step(name="normal_step", executor=normal_step)

    def selector(step_input: StepInput):
        return [step_stop]

    router = Router(
        name="Stop Router",
        selector=selector,
        choices=[step_stop, step_normal],
    )
    step_input = StepInput(input="test")

    result = router.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True, "Router should propagate stop=True from inner step"


def test_router_stop_propagation_in_workflow(shared_db):
    """Test that workflow stops when Router's inner step returns stop=True."""
    step_stop = Step(name="stop_step", executor=early_stop_step)
    step_normal = Step(name="normal_step", executor=normal_step)

    def selector(step_input: StepInput):
        return [step_stop]

    workflow = Workflow(
        name="Router Stop Propagation Test",
        db=shared_db,
        steps=[
            Router(
                name="stop_router",
                selector=selector,
                choices=[step_stop, step_normal],
            ),
            should_not_run_step,  # This should NOT execute
        ],
    )

    response = workflow.run(input="test")

    assert isinstance(response, WorkflowRunOutput)
    # Should only have 1 step result (the Router), not 2
    assert len(response.step_results) == 1, "Workflow should stop after Router with stop=True"
    assert response.step_results[0].stop is True


def test_router_stops_inner_steps_on_stop_flag():
    """Test that Router stops executing remaining inner steps when one returns stop=True."""
    step_stop = Step(name="stop_step", executor=early_stop_step)
    step_after = Step(name="after_stop", executor=should_not_run_step)

    def selector(step_input: StepInput):
        return [step_stop, step_after]  # stop_step should stop before after_stop runs

    router = Router(
        name="Inner Stop Router",
        selector=selector,
        choices=[step_stop, step_after],
    )
    step_input = StepInput(input="test")

    result = router.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True
    # Should only have 1 step result (stop_step), not 2
    assert len(result.steps) == 1, "Router should stop after inner step with stop=True"
    assert "Early stop requested" in result.steps[0].content


def test_router_streaming_propagates_stop(shared_db):
    """Test that streaming Router propagates stop flag and stops workflow."""
    step_stop = Step(name="stop_step", executor=early_stop_step)
    step_normal = Step(name="normal_step", executor=normal_step)

    def selector(step_input: StepInput):
        return [step_stop]

    workflow = Workflow(
        name="Streaming Router Stop Test",
        db=shared_db,
        steps=[
            Router(
                name="stop_router",
                selector=selector,
                choices=[step_stop, step_normal],
            ),
            should_not_run_step,
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    # Verify that the Router completed with stop propagation
    router_completed = [e for e in events if isinstance(e, RouterExecutionCompletedEvent)]
    assert len(router_completed) == 1

    # Check that inner step has stop=True in results
    step_results = router_completed[0].step_results or []
    assert len(step_results) == 1
    assert step_results[0].stop is True

    # Most importantly: verify should_not_run_step was NOT executed
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    step_names = [e.step_name for e in step_events]
    assert "should_not_run_step" not in step_names, "Workflow should have stopped before should_not_run_step"


@pytest.mark.asyncio
async def test_async_router_propagates_stop():
    """Test that async Router propagates stop flag."""
    step_stop = Step(name="stop_step", executor=early_stop_step)
    step_normal = Step(name="normal_step", executor=normal_step)

    def selector(step_input: StepInput):
        return [step_stop]

    router = Router(
        name="Async Stop Router",
        selector=selector,
        choices=[step_stop, step_normal],
    )
    step_input = StepInput(input="test")

    result = await router.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True, "Async Router should propagate stop=True from inner step"


@pytest.mark.asyncio
async def test_async_router_streaming_propagates_stop(shared_db):
    """Test that async streaming Router propagates stop flag and stops workflow."""
    step_stop = Step(name="stop_step", executor=early_stop_step)
    step_normal = Step(name="normal_step", executor=normal_step)

    def selector(step_input: StepInput):
        return [step_stop]

    workflow = Workflow(
        name="Async Streaming Router Stop Test",
        db=shared_db,
        steps=[
            Router(
                name="stop_router",
                selector=selector,
                choices=[step_stop, step_normal],
            ),
            should_not_run_step,
        ],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    # Verify that the Router completed with stop propagation
    router_completed = [e for e in events if isinstance(e, RouterExecutionCompletedEvent)]
    assert len(router_completed) == 1

    # Check that inner step has stop=True in results
    step_results = router_completed[0].step_results or []
    assert len(step_results) == 1
    assert step_results[0].stop is True

    # Most importantly: verify should_not_run_step was NOT executed
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    step_names = [e.step_name for e in step_events]
    assert "should_not_run_step" not in step_names, "Workflow should have stopped before should_not_run_step"


# ============================================================================
# STEP_CHOICES PARAMETER TESTS
# ============================================================================


def test_selector_receives_step_choices():
    """Test that selector function receives step_choices parameter with prepared steps."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Output A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Output B"))

    received_choices = []

    def selector_with_choices(step_input: StepInput, step_choices: list):
        """Selector that captures step_choices for verification."""
        received_choices.extend(step_choices)
        # Select step based on available choices
        step_map = {s.name: s for s in step_choices}
        if "A" in step_input.input:
            return [step_map["step_a"]]
        return [step_map["step_b"]]

    router = Router(
        name="choices_router",
        selector=selector_with_choices,
        choices=[step_a, step_b],
    )

    input_test = StepInput(input="Choose A")
    result = router.execute(input_test)

    # Verify step_choices was passed to selector
    assert len(received_choices) == 2
    assert all(isinstance(s, Step) for s in received_choices)
    assert {s.name for s in received_choices} == {"step_a", "step_b"}

    # Verify correct step was selected
    assert result.steps[0].content == "Output A"


def test_selector_with_step_choices_and_session_state():
    """Test selector that uses both step_choices and session_state."""
    step_1 = Step(name="step_1", executor=lambda x: StepOutput(content="Step 1"))
    step_2 = Step(name="step_2", executor=lambda x: StepOutput(content="Step 2"))

    def selector_with_both(step_input: StepInput, session_state: dict, step_choices: list):
        """Selector using both session_state and step_choices."""
        step_map = {s.name: s for s in step_choices}
        target_step = session_state.get("target_step", "step_1")
        return [step_map[target_step]]

    router = Router(
        name="combined_router",
        selector=selector_with_both,
        choices=[step_1, step_2],
    )

    # Test with session_state selecting step_2
    input_test = StepInput(input="test")
    result = router.execute(input_test, session_state={"target_step": "step_2"})

    assert result.steps[0].content == "Step 2"


def test_selector_without_step_choices_still_works():
    """Test that selectors without step_choices parameter still work (backward compatibility)."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Output A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Output B"))

    def simple_selector(step_input: StepInput):
        """Old-style selector without step_choices."""
        return [step_a]

    router = Router(
        name="simple_router",
        selector=simple_selector,
        choices=[step_a, step_b],
    )

    input_test = StepInput(input="test")
    result = router.execute(input_test)

    assert result.steps[0].content == "Output A"


def test_selector_dynamic_step_selection_from_choices():
    """Test selector that dynamically selects steps based on step_choices names."""
    step_research = Step(name="research", executor=lambda x: StepOutput(content="Research done"))
    step_write = Step(name="write", executor=lambda x: StepOutput(content="Writing done"))
    step_review = Step(name="review", executor=lambda x: StepOutput(content="Review done"))

    def dynamic_selector(step_input: StepInput, step_choices: list):
        """Select steps dynamically based on input keywords and available choices."""
        step_map = {s.name: s for s in step_choices}
        user_input = step_input.input.lower()

        if "research" in user_input:
            return [step_map["research"]]
        elif "write" in user_input:
            return [step_map["write"]]
        elif "full" in user_input:
            # Chain all available steps
            return [step_map["research"], step_map["write"], step_map["review"]]
        return [step_choices[0]]

    router = Router(
        name="dynamic_router",
        selector=dynamic_selector,
        choices=[step_research, step_write, step_review],
    )

    # Test single step selection
    result = router.execute(StepInput(input="do research"))
    assert len(result.steps) == 1
    assert result.steps[0].content == "Research done"

    # Test chaining multiple steps
    result = router.execute(StepInput(input="full workflow"))
    assert len(result.steps) == 3
    assert result.steps[0].content == "Research done"
    assert result.steps[1].content == "Writing done"
    assert result.steps[2].content == "Review done"


@pytest.mark.asyncio
async def test_async_selector_receives_step_choices():
    """Test that async selector receives step_choices parameter."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Async A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Async B"))

    async def async_selector(step_input: StepInput, step_choices: list):
        """Async selector with step_choices."""
        step_map = {s.name: s for s in step_choices}
        return [step_map["step_b"]]

    router = Router(
        name="async_choices_router",
        selector=async_selector,
        choices=[step_a, step_b],
    )

    input_test = StepInput(input="test")
    result = await router.aexecute(input_test)

    assert result.steps[0].content == "Async B"


def test_selector_step_choices_in_workflow(shared_db):
    """Test step_choices parameter works correctly within a workflow."""
    step_fast = Step(name="fast", executor=lambda x: StepOutput(content="Fast path"))
    step_slow = Step(name="slow", executor=lambda x: StepOutput(content="Slow path"))

    def workflow_selector(step_input: StepInput, step_choices: list):
        """Selector that uses step_choices in workflow context."""
        step_map = {s.name: s for s in step_choices}
        if "fast" in step_input.input.lower():
            return [step_map["fast"]]
        return [step_map["slow"]]

    workflow = Workflow(
        name="Step Choices Workflow",
        db=shared_db,
        steps=[
            Router(
                name="choices_router",
                selector=workflow_selector,
                choices=[step_fast, step_slow],
            )
        ],
    )

    # Test fast path
    response = workflow.run(input="take fast route")
    assert find_content_in_steps(response.step_results[0], "Fast path")

    # Test slow path
    response = workflow.run(input="take slow route")
    assert find_content_in_steps(response.step_results[0], "Slow path")


# ============================================================================
# STRING RETURN TYPE TESTS
# ============================================================================


def test_selector_returns_string_step_name():
    """Test that selector can return step name as string."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Output A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Output B"))

    def string_selector(step_input: StepInput):
        """Selector that returns step name as string."""
        if "A" in step_input.input:
            return "step_a"  # Return string name
        return "step_b"  # Return string name

    router = Router(
        name="string_router",
        selector=string_selector,
        choices=[step_a, step_b],
    )

    # Test selecting step_a by name
    result = router.execute(StepInput(input="Choose A"))
    assert result.steps[0].content == "Output A"

    # Test selecting step_b by name
    result = router.execute(StepInput(input="Choose B"))
    assert result.steps[0].content == "Output B"


def test_selector_returns_list_of_strings():
    """Test that selector can return list of step names as strings."""
    step_1 = Step(name="step_1", executor=lambda x: StepOutput(content="Step 1"))
    step_2 = Step(name="step_2", executor=lambda x: StepOutput(content="Step 2"))
    step_3 = Step(name="step_3", executor=lambda x: StepOutput(content="Step 3"))

    def multi_string_selector(step_input: StepInput):
        """Selector that returns multiple step names as strings."""
        if "all" in step_input.input:
            return ["step_1", "step_2", "step_3"]
        return ["step_1"]

    router = Router(
        name="multi_string_router",
        selector=multi_string_selector,
        choices=[step_1, step_2, step_3],
    )

    # Test selecting all steps by name
    result = router.execute(StepInput(input="run all"))
    assert len(result.steps) == 3
    assert result.steps[0].content == "Step 1"
    assert result.steps[1].content == "Step 2"
    assert result.steps[2].content == "Step 3"


def test_selector_returns_mixed_string_and_step():
    """Test that selector can return mixed strings and Step objects."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Output A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Output B"))

    def mixed_selector(step_input: StepInput, step_choices: list):
        """Selector that returns mix of string and Step."""
        step_map = {s.name: s for s in step_choices}
        # Return string for first, Step object for second
        return ["step_a", step_map["step_b"]]

    router = Router(
        name="mixed_router",
        selector=mixed_selector,
        choices=[step_a, step_b],
    )

    result = router.execute(StepInput(input="test"))
    assert len(result.steps) == 2
    assert result.steps[0].content == "Output A"
    assert result.steps[1].content == "Output B"


def test_selector_unknown_string_name_warns():
    """Test that unknown step name logs warning and returns empty."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Output A"))

    def bad_selector(step_input: StepInput):
        return "nonexistent_step"

    router = Router(
        name="bad_router",
        selector=bad_selector,
        choices=[step_a],
    )

    result = router.execute(StepInput(input="test"))
    # Should complete but with no steps executed (steps is None or empty)
    assert result.steps is None or len(result.steps) == 0


# ============================================================================
# NESTED CHOICES TESTS
# ============================================================================


def test_nested_list_in_choices_becomes_steps_container():
    """Test that nested list in choices becomes a Steps container."""
    from agno.workflow.steps import Steps

    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Output A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Output B"))
    step_c = Step(name="step_c", executor=lambda x: StepOutput(content="Output C"))

    def nested_selector(step_input: StepInput, step_choices: list):
        """Select from nested choices."""
        # step_choices[0] = step_a
        # step_choices[1] = Steps container with [step_b, step_c]
        if "single" in step_input.input:
            return step_choices[0]
        return step_choices[1]  # Returns the Steps container

    router = Router(
        name="nested_router",
        selector=nested_selector,
        choices=[step_a, [step_b, step_c]],  # Nested list
    )

    # Verify step_choices structure after preparation
    router._prepare_steps()
    assert len(router.steps) == 2
    assert isinstance(router.steps[0], Step)
    assert isinstance(router.steps[1], Steps)

    # Test selecting single step
    result = router.execute(StepInput(input="single"))
    assert len(result.steps) == 1
    assert result.steps[0].content == "Output A"

    # Test selecting Steps container (runs step_b then step_c)
    result = router.execute(StepInput(input="sequence"))
    # Steps container should execute both nested steps
    assert find_content_in_steps(result, "Output B")
    assert find_content_in_steps(result, "Output C")


def test_multiple_nested_lists_in_choices():
    """Test multiple nested lists in choices."""
    step_1 = Step(name="step_1", executor=lambda x: StepOutput(content="Step 1"))
    step_2 = Step(name="step_2", executor=lambda x: StepOutput(content="Step 2"))
    step_3 = Step(name="step_3", executor=lambda x: StepOutput(content="Step 3"))
    step_4 = Step(name="step_4", executor=lambda x: StepOutput(content="Step 4"))

    def selector(step_input: StepInput, step_choices: list):
        if "first" in step_input.input:
            return step_choices[0]  # Steps container [step_1, step_2]
        return step_choices[1]  # Steps container [step_3, step_4]

    router = Router(
        name="multi_nested_router",
        selector=selector,
        choices=[[step_1, step_2], [step_3, step_4]],
    )

    # Test first group
    result = router.execute(StepInput(input="first group"))
    assert find_content_in_steps(result, "Step 1")
    assert find_content_in_steps(result, "Step 2")

    # Test second group
    result = router.execute(StepInput(input="second group"))
    assert find_content_in_steps(result, "Step 3")
    assert find_content_in_steps(result, "Step 4")


@pytest.mark.asyncio
async def test_async_selector_returns_string():
    """Test async selector returning string step name."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Async A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Async B"))

    async def async_string_selector(step_input: StepInput):
        return "step_b"

    router = Router(
        name="async_string_router",
        selector=async_string_selector,
        choices=[step_a, step_b],
    )

    result = await router.aexecute(StepInput(input="test"))
    assert result.steps[0].content == "Async B"


def test_string_selector_in_workflow(shared_db):
    """Test string-returning selector in workflow context."""
    tech_step = Step(name="Tech Research", executor=lambda x: StepOutput(content="Tech content"))
    biz_step = Step(name="Business Research", executor=lambda x: StepOutput(content="Business content"))
    general_step = Step(name="General Research", executor=lambda x: StepOutput(content="General content"))

    def route_by_topic(step_input: StepInput):
        topic = step_input.input.lower()
        if "tech" in topic:
            return "Tech Research"
        elif "business" in topic:
            return "Business Research"
        return "General Research"

    workflow = Workflow(
        name="String Selector Workflow",
        db=shared_db,
        steps=[
            Router(
                name="Topic Router",
                selector=route_by_topic,
                choices=[tech_step, biz_step, general_step],
            )
        ],
    )

    # Test tech routing
    response = workflow.run(input="tech trends")
    assert find_content_in_steps(response.step_results[0], "Tech content")

    # Test business routing
    response = workflow.run(input="business analysis")
    assert find_content_in_steps(response.step_results[0], "Business content")

    # Test general routing
    response = workflow.run(input="random topic")
    assert find_content_in_steps(response.step_results[0], "General content")


# ============================================================================
# CEL EXPRESSION TESTS
# ============================================================================


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_router_basic_ternary():
    """Test CEL router with basic ternary expression."""
    video_step = Step(name="video_step", executor=lambda x: StepOutput(content="Video processing"))
    image_step = Step(name="image_step", executor=lambda x: StepOutput(content="Image processing"))

    router = Router(
        name="CEL Ternary Router",
        selector='input.contains("video") ? "video_step" : "image_step"',
        choices=[video_step, image_step],
    )

    # Should route to video_step
    result_video = router.execute(StepInput(input="Process this video file"))
    assert len(result_video.steps) == 1
    assert "Video processing" in result_video.steps[0].content

    # Should route to image_step
    result_image = router.execute(StepInput(input="Process this image file"))
    assert len(result_image.steps) == 1
    assert "Image processing" in result_image.steps[0].content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_router_additional_data():
    """Test CEL router using additional_data for routing."""
    fast_step = Step(name="fast_step", executor=lambda x: StepOutput(content="Fast processing"))
    normal_step = Step(name="normal_step", executor=lambda x: StepOutput(content="Normal processing"))

    router = Router(
        name="CEL Additional Data Router",
        selector="additional_data.route",
        choices=[fast_step, normal_step],
    )

    # Route to fast_step
    result_fast = router.execute(StepInput(input="test", additional_data={"route": "fast_step"}))
    assert len(result_fast.steps) == 1
    assert "Fast processing" in result_fast.steps[0].content

    # Route to normal_step
    result_normal = router.execute(StepInput(input="test", additional_data={"route": "normal_step"}))
    assert len(result_normal.steps) == 1
    assert "Normal processing" in result_normal.steps[0].content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_router_session_state():
    """Test CEL router using session_state for routing."""
    premium_step = Step(name="premium_step", executor=lambda x: StepOutput(content="Premium service"))
    basic_step = Step(name="basic_step", executor=lambda x: StepOutput(content="Basic service"))

    router = Router(
        name="CEL Session State Router",
        selector='session_state.user_tier == "premium" ? "premium_step" : "basic_step"',
        choices=[premium_step, basic_step],
    )

    # Route to premium_step
    result_premium = router.execute(
        StepInput(input="test"),
        session_state={"user_tier": "premium"},
    )
    assert len(result_premium.steps) == 1
    assert "Premium service" in result_premium.steps[0].content

    # Route to basic_step
    result_basic = router.execute(
        StepInput(input="test"),
        session_state={"user_tier": "free"},
    )
    assert len(result_basic.steps) == 1
    assert "Basic service" in result_basic.steps[0].content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_router_compound_condition():
    """Test CEL router with compound condition."""
    urgent_step = Step(name="urgent_step", executor=lambda x: StepOutput(content="Urgent handling"))
    normal_step = Step(name="normal_step", executor=lambda x: StepOutput(content="Normal handling"))

    router = Router(
        name="CEL Compound Router",
        selector='additional_data.priority == "high" && input.contains("urgent") ? "urgent_step" : "normal_step"',
        choices=[urgent_step, normal_step],
    )

    # Both conditions met - route to urgent
    result_urgent = router.execute(StepInput(input="This is urgent!", additional_data={"priority": "high"}))
    assert len(result_urgent.steps) == 1
    assert "Urgent handling" in result_urgent.steps[0].content

    # Only one condition met - route to normal
    result_normal = router.execute(StepInput(input="This is urgent!", additional_data={"priority": "low"}))
    assert len(result_normal.steps) == 1
    assert "Normal handling" in result_normal.steps[0].content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_router_previous_step_content():
    """Test CEL router using previous_step_content."""
    error_handler = Step(name="error_handler", executor=lambda x: StepOutput(content="Error handled"))
    success_handler = Step(name="success_handler", executor=lambda x: StepOutput(content="Success processed"))

    router = Router(
        name="CEL Previous Content Router",
        selector='previous_step_content.contains("error") ? "error_handler" : "success_handler"',
        choices=[error_handler, success_handler],
    )

    # Route based on error in previous content
    result_error = router.execute(StepInput(input="test", previous_step_content="An error occurred in processing"))
    assert len(result_error.steps) == 1
    assert "Error handled" in result_error.steps[0].content

    # Route to success when no error
    result_success = router.execute(StepInput(input="test", previous_step_content="Processing completed successfully"))
    assert len(result_success.steps) == 1
    assert "Success processed" in result_success.steps[0].content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_router_input_size():
    """Test CEL router using input size for routing."""
    detailed_step = Step(name="detailed_step", executor=lambda x: StepOutput(content="Detailed analysis"))
    quick_step = Step(name="quick_step", executor=lambda x: StepOutput(content="Quick analysis"))

    router = Router(
        name="CEL Input Size Router",
        selector='input.size() > 50 ? "detailed_step" : "quick_step"',
        choices=[detailed_step, quick_step],
    )

    # Long input - detailed analysis
    result_detailed = router.execute(
        StepInput(input="This is a very long input that contains more than fifty characters for sure")
    )
    assert len(result_detailed.steps) == 1
    assert "Detailed analysis" in result_detailed.steps[0].content

    # Short input - quick analysis
    result_quick = router.execute(StepInput(input="Short input"))
    assert len(result_quick.steps) == 1
    assert "Quick analysis" in result_quick.steps[0].content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_router_unknown_step_name():
    """Test CEL router with unknown step name returns empty."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Step A"))

    router = Router(
        name="CEL Unknown Step Router",
        selector='"nonexistent_step"',  # Returns a step name that doesn't exist
        choices=[step_a],
    )

    result = router.execute(StepInput(input="test"))
    # Should complete but with no steps executed (unknown step name)
    assert result.steps is None or len(result.steps) == 0


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_router_in_workflow(shared_db):
    """Test CEL router within a workflow."""
    tech_step = Step(name="tech_step", executor=lambda x: StepOutput(content="Tech content"))
    general_step = Step(name="general_step", executor=lambda x: StepOutput(content="General content"))

    workflow = Workflow(
        name="CEL Router Workflow",
        db=shared_db,
        steps=[
            Router(
                name="cel_router",
                selector='input.contains("tech") ? "tech_step" : "general_step"',
                choices=[tech_step, general_step],
            )
        ],
    )

    # Route to tech_step
    response_tech = workflow.run(input="tech topic discussion")
    assert find_content_in_steps(response_tech.step_results[0], "Tech content")

    # Route to general_step
    response_general = workflow.run(input="general topic discussion")
    assert find_content_in_steps(response_general.step_results[0], "General content")


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_router_streaming(shared_db):
    """Test CEL router with streaming."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Step A output"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Step B output"))

    workflow = Workflow(
        name="CEL Streaming Router",
        db=shared_db,
        steps=[
            Router(
                name="cel_stream_router",
                selector='"step_a"',
                choices=[step_a, step_b],
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    router_started = [e for e in events if isinstance(e, RouterExecutionStartedEvent)]
    router_completed = [e for e in events if isinstance(e, RouterExecutionCompletedEvent)]

    assert len(router_started) == 1
    assert len(router_completed) == 1
    assert "step_a" in router_started[0].selected_steps


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
@pytest.mark.asyncio
async def test_cel_router_async():
    """Test CEL router with async execution."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Async Step A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Async Step B"))

    router = Router(
        name="CEL Async Router",
        selector='input.contains("option_a") ? "step_a" : "step_b"',
        choices=[step_a, step_b],
    )

    result = await router.aexecute(StepInput(input="Select option_a please"))

    assert len(result.steps) == 1
    assert "Async Step A" in result.steps[0].content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_router_with_steps_component():
    """Test CEL router routing to a Steps component."""
    step_1 = Step(name="step_1", executor=lambda x: StepOutput(content="Step 1"))
    step_2 = Step(name="step_2", executor=lambda x: StepOutput(content="Step 2"))
    sequence = Steps(name="sequence", steps=[step_1, step_2])
    single = Step(name="single", executor=lambda x: StepOutput(content="Single"))

    router = Router(
        name="CEL Steps Router",
        selector='input.contains("multi") ? "sequence" : "single"',
        choices=[sequence, single],
    )

    # Route to sequence
    result_multi = router.execute(StepInput(input="multi step request"))
    assert find_content_in_steps(result_multi, "Step 1")
    assert find_content_in_steps(result_multi, "Step 2")

    # Route to single
    result_single = router.execute(StepInput(input="simple request"))
    assert len(result_single.steps) == 1
    assert "Single" in result_single.steps[0].content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_router_nested_additional_data():
    """Test CEL router with nested additional_data access."""
    step_a = Step(name="step_a", executor=lambda x: StepOutput(content="Step A"))
    step_b = Step(name="step_b", executor=lambda x: StepOutput(content="Step B"))

    router = Router(
        name="CEL Nested Data Router",
        selector='additional_data.config.mode == "advanced" ? "step_a" : "step_b"',
        choices=[step_a, step_b],
    )

    # Route based on nested config
    result_advanced = router.execute(StepInput(input="test", additional_data={"config": {"mode": "advanced"}}))
    assert len(result_advanced.steps) == 1
    assert "Step A" in result_advanced.steps[0].content

    result_basic = router.execute(StepInput(input="test", additional_data={"config": {"mode": "basic"}}))
    assert len(result_basic.steps) == 1
    assert "Step B" in result_basic.steps[0].content
