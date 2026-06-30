"""Integration tests for complex combinations of workflow steps."""

import pytest

from agno.run.workflow import WorkflowCompletedEvent, WorkflowRunOutput
from agno.workflow import Condition, Loop, Parallel, Workflow
from agno.workflow.router import Router
from agno.workflow.types import StepInput, StepOutput


def find_content_in_steps(step_output, search_text):
    """Recursively search for content in step output and its nested steps."""
    if search_text in step_output.content:
        return True
    if step_output.steps:
        return any(find_content_in_steps(nested_step, search_text) for nested_step in step_output.steps)
    return False


# Helper functions
def research_step(step_input: StepInput) -> StepOutput:
    """Research step."""
    return StepOutput(content=f"Research: {step_input.input}. Found data showing trends.", success=True)


def analysis_step(step_input: StepInput) -> StepOutput:
    """Analysis step."""
    return StepOutput(content=f"Analysis of: {step_input.previous_step_content}", success=True)


def summary_step(step_input: StepInput) -> StepOutput:
    """Summary step."""
    return StepOutput(content=f"Summary of findings: {step_input.previous_step_content}", success=True)


# Evaluators for conditions
def has_data(step_input: StepInput) -> bool:
    """Check if content contains data."""
    content = step_input.input or step_input.previous_step_content or ""
    return "data" in content.lower()


def needs_more_research(step_input: StepInput) -> bool:
    """Check if more research is needed."""
    content = step_input.previous_step_content or ""
    return len(content) < 200


def router_step(step_input: StepInput) -> StepOutput:
    """Router decision step."""
    return StepOutput(content="Route A" if "data" in step_input.input.lower() else "Route B", success=True)


def route_a_step(step_input: StepInput) -> StepOutput:
    """Route A processing."""
    return StepOutput(content="Processed via Route A", success=True)


def route_b_step(step_input: StepInput) -> StepOutput:
    """Route B processing."""
    return StepOutput(content="Processed via Route B", success=True)


def test_loop_with_parallel(shared_db):
    """Test Loop containing Parallel steps."""
    workflow = Workflow(
        name="Loop with Parallel",
        db=shared_db,
        steps=[
            Loop(
                name="research_loop",
                steps=[Parallel(research_step, analysis_step, name="parallel_research"), summary_step],
                end_condition=lambda outputs: len(outputs) >= 2,
                max_iterations=3,
            )
        ],
    )

    response = workflow.run(input="test topic")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1  # One loop output
    loop_output = response.step_results[0]
    assert isinstance(loop_output, StepOutput)
    assert loop_output.step_type == "Loop"
    assert loop_output.steps is not None
    assert len(loop_output.steps) >= 2  # At least two steps per iteration


def test_loop_with_condition(shared_db):
    """Test Loop containing Condition steps."""
    workflow = Workflow(
        name="Loop with Condition",
        db=shared_db,
        steps=[
            Loop(
                name="research_loop",
                steps=[
                    research_step,
                    Condition(name="analysis_condition", evaluator=has_data, steps=[analysis_step]),
                ],
                end_condition=lambda outputs: len(outputs) >= 2,
                max_iterations=3,
            )
        ],
    )

    response = workflow.run(input="test data")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1
    # Search for "Analysis" in the nested structure
    assert find_content_in_steps(response.step_results[0], "Analysis")


def test_condition_with_loop(shared_db):
    """Test Condition containing Loop steps."""
    workflow = Workflow(
        name="Condition with Loop",
        db=shared_db,
        steps=[
            research_step,
            Condition(
                name="research_condition",
                evaluator=needs_more_research,
                steps=[
                    Loop(
                        name="deep_research",
                        steps=[research_step, analysis_step],
                        end_condition=lambda outputs: len(outputs) >= 2,
                        max_iterations=3,
                    )
                ],
            ),
        ],
    )

    response = workflow.run(input="test topic")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2  # Research + Condition


def test_parallel_with_loops(shared_db):
    """Test Parallel containing multiple Loops."""
    workflow = Workflow(
        name="Parallel with Loops",
        db=shared_db,
        steps=[
            Parallel(
                Loop(
                    name="research_loop",
                    steps=[research_step],
                    end_condition=lambda outputs: len(outputs) >= 2,
                    max_iterations=3,
                ),
                Loop(
                    name="analysis_loop",
                    steps=[analysis_step],
                    end_condition=lambda outputs: len(outputs) >= 2,
                    max_iterations=3,
                ),
                name="parallel_loops",
            )
        ],
    )

    response = workflow.run(input="test topic")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1  # One parallel output
    parallel_output = response.step_results[0]
    assert isinstance(parallel_output, StepOutput)
    assert parallel_output.step_type == "Parallel"


def test_nested_conditions_and_loops(shared_db):
    """Test nested Conditions and Loops."""
    workflow = Workflow(
        name="Nested Conditions and Loops",
        db=shared_db,
        steps=[
            Condition(
                name="outer_condition",
                evaluator=needs_more_research,
                steps=[
                    Loop(
                        name="research_loop",
                        steps=[
                            research_step,
                            Condition(name="inner_condition", evaluator=has_data, steps=[analysis_step]),
                        ],
                        end_condition=lambda outputs: len(outputs) >= 2,
                        max_iterations=3,
                    )
                ],
            )
        ],
    )

    response = workflow.run(input="test data")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1  # One condition output
    condition_output = response.step_results[0]
    assert isinstance(condition_output, StepOutput)
    assert condition_output.step_type == "Condition"


def test_parallel_with_conditions_and_loops(shared_db):
    """Test Parallel with mix of Conditions and Loops."""
    workflow = Workflow(
        name="Mixed Parallel",
        db=shared_db,
        steps=[
            Parallel(
                Loop(
                    name="research_loop",
                    steps=[research_step],
                    end_condition=lambda outputs: len(outputs) >= 2,
                    max_iterations=3,
                ),
                Condition(name="analysis_condition", evaluator=has_data, steps=[analysis_step]),
                name="mixed_parallel",
            ),
            summary_step,
        ],
    )

    response = workflow.run(input="test data")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2  # Parallel + Summary


@pytest.mark.asyncio
async def test_async_complex_combination(shared_db):
    """Test async execution of complex step combinations."""
    workflow = Workflow(
        name="Async Complex",
        db=shared_db,
        steps=[
            Loop(
                name="outer_loop",
                steps=[
                    Parallel(
                        Condition(name="research_condition", evaluator=needs_more_research, steps=[research_step]),
                        analysis_step,
                        name="parallel_steps",
                    )
                ],
                end_condition=lambda outputs: len(outputs) >= 2,
                max_iterations=3,
            ),
            summary_step,
        ],
    )

    response = await workflow.arun(input="test topic")
    assert isinstance(response, WorkflowRunOutput)
    assert find_content_in_steps(response.step_results[-1], "Summary")


def test_complex_streaming(shared_db):
    """Test streaming with complex step combinations."""
    workflow = Workflow(
        name="Complex Streaming",
        db=shared_db,
        steps=[
            Loop(
                name="main_loop",
                steps=[
                    Parallel(
                        Condition(name="research_condition", evaluator=has_data, steps=[research_step]),
                        Loop(
                            name="analysis_loop",
                            steps=[analysis_step],
                            end_condition=lambda outputs: len(outputs) >= 2,
                            max_iterations=2,
                        ),
                        name="parallel_steps",
                    )
                ],
                end_condition=lambda outputs: len(outputs) >= 2,
                max_iterations=2,
            )
        ],
    )

    events = list(workflow.run(input="test data", stream=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1


def test_router_with_loop(shared_db):
    """Test Router with Loop in routes."""
    from agno.workflow.step import Step

    research_loop = Loop(
        name="research_loop",
        steps=[research_step, analysis_step],
        end_condition=lambda outputs: len(outputs) >= 2,
        max_iterations=3,
    )

    def route_selector(step_input: StepInput):
        """Select between research loop and summary."""
        if "data" in step_input.input.lower():
            return [research_loop]
        return [Step(name="summary", executor=summary_step)]

    workflow = Workflow(
        name="Router with Loop",
        db=shared_db,
        steps=[
            Router(
                name="research_router",
                selector=route_selector,
                choices=[research_loop, Step(name="summary", executor=summary_step)],
                description="Routes between deep research and summary",
            )
        ],
    )

    response = workflow.run(input="test data")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1
    # Search for "Research" in the nested structure
    assert find_content_in_steps(response.step_results[0], "Research")


def test_loop_with_router(shared_db):
    """Test Loop containing Router."""
    from agno.workflow.step import Step

    def route_selector(step_input: StepInput):
        """Select between analysis and summary."""
        if "data" in step_input.previous_step_content.lower():
            return [Step(name="analysis", executor=analysis_step)]
        return [Step(name="summary", executor=summary_step)]

    router = Router(
        name="process_router",
        selector=route_selector,
        choices=[Step(name="analysis", executor=analysis_step), Step(name="summary", executor=summary_step)],
        description="Routes between analysis and summary",
    )

    workflow = Workflow(
        name="Loop with Router",
        db=shared_db,
        steps=[
            Loop(
                name="main_loop",
                steps=[
                    research_step,
                    router,
                ],
                end_condition=lambda outputs: len(outputs) >= 2,
                max_iterations=3,
            )
        ],
    )

    response = workflow.run(input="test data")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1
    loop_output = response.step_results[0]
    assert isinstance(loop_output, StepOutput)
    assert loop_output.step_type == "Loop"


def test_parallel_with_routers(shared_db):
    """Test Parallel execution of multiple Routers."""
    from agno.workflow.step import Step

    def research_selector(step_input: StepInput):
        """Select research path."""
        return (
            [Step(name="research", executor=research_step)]
            if "data" in step_input.input.lower()
            else [Step(name="analysis", executor=analysis_step)]
        )

    def summary_selector(step_input: StepInput):
        """Select summary path."""
        return (
            [Step(name="summary", executor=summary_step)]
            if "complete" in step_input.input.lower()
            else [Step(name="analysis", executor=analysis_step)]
        )

    workflow = Workflow(
        name="Parallel Routers",
        db=shared_db,
        steps=[
            Parallel(
                Router(
                    name="research_router",
                    selector=research_selector,
                    choices=[
                        Step(name="research", executor=research_step),
                        Step(name="analysis", executor=analysis_step),
                    ],
                    description="Routes research process",
                ),
                Router(
                    name="summary_router",
                    selector=summary_selector,
                    choices=[
                        Step(name="summary", executor=summary_step),
                        Step(name="analysis", executor=analysis_step),
                    ],
                    description="Routes summary process",
                ),
                name="parallel_routers",
            )
        ],
    )

    response = workflow.run(input="test data complete")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1
    parallel_output = response.step_results[0]
    assert isinstance(parallel_output, StepOutput)
    assert parallel_output.step_type == "Parallel"


def test_router_with_condition_and_loop(shared_db):
    """Test Router with Condition and Loop in routes."""
    research_loop = Loop(
        name="research_loop",
        steps=[research_step],
        end_condition=lambda outputs: len(outputs) >= 2,
        max_iterations=3,
    )
    analysis_condition = Condition(name="analysis_condition", evaluator=has_data, steps=[analysis_step])

    def route_selector(step_input: StepInput):
        """Select between research loop and conditional analysis."""
        if "research" in step_input.input.lower():
            return [research_loop]
        return [analysis_condition]

    workflow = Workflow(
        name="Complex Router",
        db=shared_db,
        steps=[
            Router(
                name="complex_router",
                selector=route_selector,
                choices=[research_loop, analysis_condition],
                description="Routes between research loop and conditional analysis",
            ),
            summary_step,
        ],
    )

    response = workflow.run(input="test research data")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2


def test_nested_routers(shared_db):
    """Test nested Routers."""
    from agno.workflow.step import Step

    def inner_selector(step_input: StepInput):
        """Select inner route."""
        if "data" in step_input.previous_step_content.lower():
            return [Step(name="analysis", executor=analysis_step)]
        return [Step(name="summary", executor=summary_step)]

    inner_router = Router(
        name="inner_router",
        selector=inner_selector,
        choices=[Step(name="analysis", executor=analysis_step), Step(name="summary", executor=summary_step)],
        description="Routes between analysis and summary",
    )

    def outer_selector(step_input: StepInput):
        """Select outer route."""
        if "research" in step_input.input.lower():
            return [Step(name="research", executor=research_step), inner_router]
        return [Step(name="summary", executor=summary_step)]

    workflow = Workflow(
        name="Nested Routers",
        db=shared_db,
        steps=[
            Router(
                name="outer_router",
                selector=outer_selector,
                choices=[
                    Step(name="research", executor=research_step),
                    inner_router,
                    Step(name="summary", executor=summary_step),
                ],
                description="Routes research process with nested routing",
            )
        ],
    )

    response = workflow.run(input="test research data")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1
    router_output = response.step_results[0]
    assert isinstance(router_output, StepOutput)
    assert router_output.step_type == "Router"


def test_router_streaming(shared_db):
    """Test streaming with Router combinations."""
    parallel_research = Parallel(research_step, analysis_step, name="parallel_research")
    research_loop = Loop(
        name="research_loop",
        steps=[parallel_research],
        end_condition=lambda outputs: len(outputs) >= 2,
        max_iterations=2,
    )
    analysis_condition = Condition(name="analysis_condition", evaluator=has_data, steps=[analysis_step])

    def route_selector(step_input: StepInput):
        """Select between research loop and conditional analysis."""
        if "research" in step_input.input.lower():
            return [research_loop]
        return [analysis_condition]

    workflow = Workflow(
        name="Streaming Router",
        db=shared_db,
        steps=[
            Router(
                name="stream_router",
                selector=route_selector,
                choices=[research_loop, analysis_condition],
                description="Routes between research loop and analysis",
            )
        ],
    )

    events = list(workflow.run(input="test research data", stream=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
