"""Integration tests for complex combinations of workflow steps."""

import pytest

from agno.run.v2.workflow import WorkflowCompletedEvent, WorkflowRunResponse
from agno.workflow.v2 import Condition, Loop, Parallel, Workflow
from agno.workflow.v2.router import Router
from agno.workflow.v2.types import StepInput, StepOutput


# Helper functions
def research_step(step_input: StepInput) -> StepOutput:
    """Research step."""
    return StepOutput(content=f"Research: {step_input.message}. Found data showing trends.", success=True)


def analysis_step(step_input: StepInput) -> StepOutput:
    """Analysis step."""
    return StepOutput(content=f"Analysis of: {step_input.previous_step_content}", success=True)


def summary_step(step_input: StepInput) -> StepOutput:
    """Summary step."""
    return StepOutput(content=f"Summary of findings: {step_input.previous_step_content}", success=True)


# Evaluators for conditions
def has_data(step_input: StepInput) -> bool:
    """Check if content contains data."""
    content = step_input.message or step_input.previous_step_content or ""
    return "data" in content.lower()


def needs_more_research(step_input: StepInput) -> bool:
    """Check if more research is needed."""
    content = step_input.previous_step_content or ""
    return len(content) < 200


def router_step(step_input: StepInput) -> StepOutput:
    """Router decision step."""
    return StepOutput(content="Route A" if "data" in step_input.message.lower() else "Route B", success=True)


def route_a_step(step_input: StepInput) -> StepOutput:
    """Route A processing."""
    return StepOutput(content="Processed via Route A", success=True)


def route_b_step(step_input: StepInput) -> StepOutput:
    """Route B processing."""
    return StepOutput(content="Processed via Route B", success=True)


def test_loop_with_parallel(workflow_storage):
    """Test Loop containing Parallel steps."""
    workflow = Workflow(
        name="Loop with Parallel",
        storage=workflow_storage,
        steps=[
            Loop(
                name="research_loop",
                steps=[Parallel(research_step, analysis_step, name="parallel_research"), summary_step],
                end_condition=lambda outputs: len(outputs) >= 2,
                max_iterations=3,
            )
        ],
    )

    response = workflow.run(message="test topic")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 1  # One loop output
    loop_outputs = response.step_responses[0]
    assert isinstance(loop_outputs, list)
    assert len(loop_outputs) >= 2  # At least two iterations


def test_loop_with_condition(workflow_storage):
    """Test Loop containing Condition steps."""
    workflow = Workflow(
        name="Loop with Condition",
        storage=workflow_storage,
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

    response = workflow.run(message="test data")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 1
    assert "Analysis" in response.content


def test_condition_with_loop(workflow_storage):
    """Test Condition containing Loop steps."""
    workflow = Workflow(
        name="Condition with Loop",
        storage=workflow_storage,
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

    response = workflow.run(message="test topic")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2  # Research + Condition


def test_parallel_with_loops(workflow_storage):
    """Test Parallel containing multiple Loops."""
    workflow = Workflow(
        name="Parallel with Loops",
        storage=workflow_storage,
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

    response = workflow.run(message="test topic")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 1  # One parallel output


def test_nested_conditions_and_loops(workflow_storage):
    """Test nested Conditions and Loops."""
    workflow = Workflow(
        name="Nested Conditions and Loops",
        storage=workflow_storage,
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

    response = workflow.run(message="test data")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 1  # One condition output


def test_parallel_with_conditions_and_loops(workflow_storage):
    """Test Parallel with mix of Conditions and Loops."""
    workflow = Workflow(
        name="Mixed Parallel",
        storage=workflow_storage,
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

    response = workflow.run(message="test data")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2  # Parallel + Summary


@pytest.mark.asyncio
async def test_async_complex_combination(workflow_storage):
    """Test async execution of complex step combinations."""
    workflow = Workflow(
        name="Async Complex",
        storage=workflow_storage,
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

    response = await workflow.arun(message="test topic")
    assert isinstance(response, WorkflowRunResponse)
    assert "Summary" in response.content


def test_complex_streaming(workflow_storage):
    """Test streaming with complex step combinations."""
    workflow = Workflow(
        name="Complex Streaming",
        storage=workflow_storage,
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

    events = list(workflow.run(message="test data", stream=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1


def test_router_with_loop(workflow_storage):
    """Test Router with Loop in routes."""
    research_loop = Loop(
        name="research_loop",
        steps=[research_step, analysis_step],
        end_condition=lambda outputs: len(outputs) >= 2,
        max_iterations=3,
    )

    def route_selector(step_input: StepInput):
        """Select between research loop and summary."""
        if "data" in step_input.message.lower():
            return [research_loop]
        return [summary_step]

    workflow = Workflow(
        name="Router with Loop",
        storage=workflow_storage,
        steps=[
            Router(
                name="research_router",
                selector=route_selector,
                choices=[research_loop, summary_step],
                description="Routes between deep research and summary",
            )
        ],
    )

    response = workflow.run(message="test data")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 1
    assert "Research" in response.content


def test_loop_with_router(workflow_storage):
    """Test Loop containing Router."""

    def route_selector(step_input: StepInput):
        """Select between analysis and summary."""
        if "data" in step_input.previous_step_content.lower():
            return [analysis_step]
        return [summary_step]

    router = Router(
        name="process_router",
        selector=route_selector,
        choices=[analysis_step, summary_step],
        description="Routes between analysis and summary",
    )

    workflow = Workflow(
        name="Loop with Router",
        storage=workflow_storage,
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

    response = workflow.run(message="test data")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 1
    assert isinstance(response.step_responses[0], list)


def test_parallel_with_routers(workflow_storage):
    """Test Parallel execution of multiple Routers."""

    def research_selector(step_input: StepInput):
        """Select research path."""
        return [research_step] if "data" in step_input.message.lower() else [analysis_step]

    def summary_selector(step_input: StepInput):
        """Select summary path."""
        return [summary_step] if "complete" in step_input.message.lower() else [analysis_step]

    workflow = Workflow(
        name="Parallel Routers",
        storage=workflow_storage,
        steps=[
            Parallel(
                Router(
                    name="research_router",
                    selector=research_selector,
                    choices=[research_step, analysis_step],
                    description="Routes research process",
                ),
                Router(
                    name="summary_router",
                    selector=summary_selector,
                    choices=[summary_step, analysis_step],
                    description="Routes summary process",
                ),
                name="parallel_routers",
            )
        ],
    )

    response = workflow.run(message="test data complete")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 1


def test_router_with_condition_and_loop(workflow_storage):
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
        if "research" in step_input.message.lower():
            return [research_loop]
        return [analysis_condition]

    workflow = Workflow(
        name="Complex Router",
        storage=workflow_storage,
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

    response = workflow.run(message="test research data")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2


def test_nested_routers(workflow_storage):
    """Test nested Routers."""

    def outer_selector(step_input: StepInput):
        """Select outer route."""
        if "research" in step_input.message.lower():
            return [research_step, inner_router]
        return [summary_step]

    def inner_selector(step_input: StepInput):
        """Select inner route."""
        if "data" in step_input.previous_step_content.lower():
            return [analysis_step]
        return [summary_step]

    inner_router = Router(
        name="inner_router",
        selector=inner_selector,
        choices=[analysis_step, summary_step],
        description="Routes between analysis and summary",
    )

    workflow = Workflow(
        name="Nested Routers",
        storage=workflow_storage,
        steps=[
            Router(
                name="outer_router",
                selector=outer_selector,
                choices=[research_step, inner_router, summary_step],
                description="Routes research process with nested routing",
            )
        ],
    )

    response = workflow.run(message="test research data")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 1


def test_router_streaming(workflow_storage):
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
        if "research" in step_input.message.lower():
            return [research_loop]
        return [analysis_condition]

    workflow = Workflow(
        name="Streaming Router",
        storage=workflow_storage,
        steps=[
            Router(
                name="stream_router",
                selector=route_selector,
                choices=[research_loop, analysis_condition],
                description="Routes between research loop and analysis",
            )
        ],
    )

    events = list(workflow.run(message="test research data", stream=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
