"""Unit tests for WorkflowTools."""

import os
import tempfile
import uuid
from unittest.mock import MagicMock

import pytest

from agno.db.sqlite import SqliteDb
from agno.run.base import RunContext
from agno.run.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    LoopExecutionCompletedEvent,
    LoopExecutionStartedEvent,
    LoopIterationCompletedEvent,
    LoopIterationStartedEvent,
    ParallelExecutionCompletedEvent,
    ParallelExecutionStartedEvent,
    RouterExecutionCompletedEvent,
    RouterExecutionStartedEvent,
    StepCompletedEvent,
    StepsExecutionCompletedEvent,
    StepsExecutionStartedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowStartedEvent,
)
from agno.tools.workflow import RunWorkflowInput, WorkflowTools
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.parallel import Parallel
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# === Fixtures ===
@pytest.fixture
def temp_storage_db_file():
    """Create a temporary SQLite database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def shared_db(temp_storage_db_file):
    """Create a SQLite storage for sessions."""
    table_name = f"sessions_{uuid.uuid4().hex[:8]}"
    db = SqliteDb(session_table=table_name, db_file=temp_storage_db_file)
    return db


@pytest.fixture
def mock_run_context():
    """Create a mock RunContext for testing."""
    context = MagicMock(spec=RunContext)
    context.stream = True
    context.stream_events = True
    return context


@pytest.fixture
def mock_run_context_no_stream():
    """Create a mock RunContext with streaming disabled."""
    context = MagicMock(spec=RunContext)
    context.stream = False
    context.stream_events = False
    return context


# === Helper Functions for Steps ===
def simple_step(step_input: StepInput) -> StepOutput:
    """Simple step that returns input."""
    return StepOutput(content=f"Processed: {step_input.input}", success=True)


def step_with_previous(step_input: StepInput) -> StepOutput:
    """Step that uses previous step content."""
    prev = step_input.previous_step_content or "none"
    return StepOutput(content=f"Previous was: {prev}", success=True)


def always_true(step_input: StepInput) -> bool:
    """Condition evaluator that always returns True."""
    return True


def always_false(step_input: StepInput) -> bool:
    """Condition evaluator that always returns False."""
    return False


def loop_end_condition(outputs):
    """End loop after first iteration."""
    return len(outputs) >= 1


def select_first_step(step_input: StepInput):
    """Router selector that always selects first step."""
    return [Step(name="selected_step", executor=simple_step)]


# === Test WorkflowTools Initialization ===
def test_basic_init(shared_db):
    """Test basic WorkflowTools initialization."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow)

    assert tools.workflow == workflow
    assert tools._stream is None  # Default is None (inherits from run_context)
    assert "run_workflow" in [f.name for f in tools.functions.values()]


def test_init_with_stream_true(shared_db):
    """Test WorkflowTools with stream=True."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, stream=True)

    assert tools._stream is True
    assert "run_workflow" in [f.name for f in tools.functions.values()]


def test_init_with_stream_false(shared_db):
    """Test WorkflowTools with stream=False."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, stream=False)

    assert tools._stream is False
    assert "run_workflow" in [f.name for f in tools.functions.values()]


def test_init_with_think_enabled(shared_db):
    """Test WorkflowTools with think tool enabled."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, enable_think=True)

    function_names = [f.name for f in tools.functions.values()]
    assert "think" in function_names
    assert "run_workflow" in function_names


def test_init_with_analyze_enabled(shared_db):
    """Test WorkflowTools with analyze tool enabled."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, enable_analyze=True)

    function_names = [f.name for f in tools.functions.values()]
    assert "analyze" in function_names
    assert "run_workflow" in function_names


def test_init_with_all_tools(shared_db):
    """Test WorkflowTools with all tools enabled."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, all=True)

    function_names = [f.name for f in tools.functions.values()]
    assert "think" in function_names
    assert "analyze" in function_names
    assert "run_workflow" in function_names


def test_init_async_mode_deprecated(shared_db):
    """Test WorkflowTools async_mode is deprecated but still works."""
    import warnings

    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        tools = WorkflowTools(workflow=workflow, async_mode=True)

        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "async_mode" in str(w[0].message)

    # Tools should still work
    assert "run_workflow" in [f.name for f in tools.functions.values()]


def test_init_async_mode_with_stream(shared_db):
    """Test WorkflowTools in async mode with streaming."""
    import warnings

    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        tools = WorkflowTools(workflow=workflow, async_mode=True, stream=True)

    assert tools._stream is True


# === Test Think Tool ===
def test_think_records_thought(shared_db):
    """Test that think tool records thoughts in session state."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, enable_think=True)

    session_state = {}
    result = tools.think(session_state, "My first thought")

    assert "workflow_thoughts" in session_state
    assert "My first thought" in session_state["workflow_thoughts"]
    assert "My first thought" in result


def test_think_accumulates_thoughts(shared_db):
    """Test that multiple thoughts are accumulated."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, enable_think=True)

    session_state = {}
    tools.think(session_state, "First thought")
    result = tools.think(session_state, "Second thought")

    assert len(session_state["workflow_thoughts"]) == 2
    assert "First thought" in result
    assert "Second thought" in result


@pytest.mark.asyncio
async def test_async_think(shared_db):
    """Test async think tool."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, enable_think=True)

    session_state = {}
    result = await tools.async_think(session_state, "Async thought")

    assert "workflow_thoughts" in session_state
    assert "Async thought" in result


# === Test Analyze Tool ===
def test_analyze_records_analysis(shared_db):
    """Test that analyze tool records analysis in session state."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, enable_analyze=True)

    session_state = {}
    result = tools.analyze(session_state, "My analysis")

    assert "workflow_analysis" in session_state
    assert "My analysis" in session_state["workflow_analysis"]
    assert "My analysis" in result


def test_analyze_accumulates(shared_db):
    """Test that multiple analyses are accumulated."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, enable_analyze=True)

    session_state = {}
    tools.analyze(session_state, "First analysis")
    result = tools.analyze(session_state, "Second analysis")

    assert len(session_state["workflow_analysis"]) == 2
    assert "First analysis" in result
    assert "Second analysis" in result


@pytest.mark.asyncio
async def test_async_analyze(shared_db):
    """Test async analyze tool."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, enable_analyze=True)

    session_state = {}
    result = await tools.async_analyze(session_state, "Async analysis")

    assert "workflow_analysis" in session_state
    assert "Async analysis" in result


# === Test Run Workflow (Non-Streaming) ===
def test_run_workflow_basic(shared_db, mock_run_context_no_stream):
    """Test basic workflow execution."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, stream=False)

    session_state = {}
    input_data = RunWorkflowInput(input_data="test input")
    result = tools.run_workflow(mock_run_context_no_stream, session_state, input_data)

    assert "Processed: test input" in result
    assert "workflow_results" in session_state


def test_run_workflow_with_dict_input(shared_db, mock_run_context_no_stream):
    """Test workflow execution with dict input."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, stream=False)

    session_state = {}
    result = tools.run_workflow(mock_run_context_no_stream, session_state, {"input_data": "dict input"})

    assert "Processed: dict input" in result


def test_run_workflow_stores_results(shared_db, mock_run_context_no_stream):
    """Test that workflow results are stored in session state."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, stream=False)

    session_state = {}
    input_data = RunWorkflowInput(input_data="test")
    tools.run_workflow(mock_run_context_no_stream, session_state, input_data)

    assert "workflow_results" in session_state
    assert len(session_state["workflow_results"]) == 1


def test_run_workflow_multiple_times(shared_db, mock_run_context_no_stream):
    """Test running workflow multiple times accumulates results."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, stream=False)

    session_state = {}
    tools.run_workflow(mock_run_context_no_stream, session_state, RunWorkflowInput(input_data="first"))
    tools.run_workflow(mock_run_context_no_stream, session_state, RunWorkflowInput(input_data="second"))

    assert len(session_state["workflow_results"]) == 2


@pytest.mark.asyncio
async def test_async_run_workflow(shared_db, mock_run_context_no_stream):
    """Test async workflow execution."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, stream=False)

    session_state = {}
    input_data = RunWorkflowInput(input_data="async test")
    result = await tools.async_run_workflow(mock_run_context_no_stream, session_state, input_data)

    assert "Processed: async test" in result


# === Test Run Workflow Stream ===
def test_stream_yields_events(shared_db, mock_run_context):
    """Test that streaming yields workflow events."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[Step(name="test_step", executor=simple_step)],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    input_data = RunWorkflowInput(input_data="stream test")
    events = list(tools.run_workflow(mock_run_context, session_state, input_data))

    assert len(events) > 0

    event_types = [type(e).__name__ for e in events]
    assert "WorkflowStartedEvent" in event_types
    assert "StepStartedEvent" in event_types
    assert "StepCompletedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types


def test_stream_yields_final_content(shared_db, mock_run_context):
    """Test that streaming yields final content as last item."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[Step(name="test_step", executor=simple_step)],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    input_data = RunWorkflowInput(input_data="final content test")
    events = list(tools.run_workflow(mock_run_context, session_state, input_data))

    final_item = events[-1]
    assert isinstance(final_item, str)


def test_stream_workflow_started_event(shared_db, mock_run_context):
    """Test WorkflowStartedEvent is yielded."""
    workflow = Workflow(
        name="TestWorkflow",
        db=shared_db,
        steps=[Step(name="test_step", executor=simple_step)],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    started_events = [e for e in events if isinstance(e, WorkflowStartedEvent)]
    assert len(started_events) == 1
    assert started_events[0].workflow_name == "TestWorkflow"


def test_stream_workflow_completed_event(shared_db, mock_run_context):
    """Test WorkflowCompletedEvent is yielded."""
    workflow = Workflow(
        name="TestWorkflow",
        db=shared_db,
        steps=[Step(name="test_step", executor=simple_step)],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1


def test_stream_step_events(shared_db, mock_run_context):
    """Test StepStartedEvent and StepCompletedEvent are yielded."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[
            Step(name="step1", executor=simple_step),
            Step(name="step2", executor=step_with_previous),
        ],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    started_events = [e for e in events if isinstance(e, StepStartedEvent)]
    completed_events = [e for e in events if isinstance(e, StepCompletedEvent)]

    assert len(started_events) == 2
    assert len(completed_events) == 2
    assert started_events[0].step_name == "step1"
    assert started_events[1].step_name == "step2"


@pytest.mark.asyncio
async def test_async_stream_yields_events(shared_db, mock_run_context):
    """Test async streaming yields workflow events."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[Step(name="test_step", executor=simple_step)],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    input_data = RunWorkflowInput(input_data="async stream test")

    events = []
    result = await tools.async_run_workflow(mock_run_context, session_state, input_data)
    # Result is an async iterator when streaming
    async for event in result:
        events.append(event)

    assert len(events) > 0
    event_types = [type(e).__name__ for e in events]
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types


# === Test Streaming with Condition Steps ===
def test_condition_true_events(shared_db, mock_run_context):
    """Test streaming events when condition is True."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[
            Condition(
                name="test_condition",
                evaluator=always_true,
                steps=[Step(name="conditional_step", executor=simple_step)],
            )
        ],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    started_events = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    completed_events = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]

    assert len(started_events) == 1
    assert len(completed_events) == 1
    assert started_events[0].condition_result is True


def test_condition_false_events(shared_db, mock_run_context):
    """Test streaming events when condition is False."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[
            Condition(
                name="test_condition",
                evaluator=always_false,
                steps=[Step(name="conditional_step", executor=simple_step)],
            )
        ],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    started_events = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    completed_events = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]

    assert len(started_events) == 1
    assert len(completed_events) == 1
    assert started_events[0].condition_result is False


# === Test Streaming with Loop Steps ===
def test_loop_events(shared_db, mock_run_context):
    """Test streaming events for loop execution."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[
            Loop(
                name="test_loop",
                steps=[Step(name="loop_step", executor=simple_step)],
                end_condition=loop_end_condition,
                max_iterations=2,
            )
        ],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    loop_started = [e for e in events if isinstance(e, LoopExecutionStartedEvent)]
    loop_completed = [e for e in events if isinstance(e, LoopExecutionCompletedEvent)]
    iteration_started = [e for e in events if isinstance(e, LoopIterationStartedEvent)]
    iteration_completed = [e for e in events if isinstance(e, LoopIterationCompletedEvent)]

    assert len(loop_started) == 1
    assert len(loop_completed) == 1
    assert len(iteration_started) >= 1
    assert len(iteration_completed) >= 1


# === Test Streaming with Parallel Steps ===
def test_parallel_events(shared_db, mock_run_context):
    """Test streaming events for parallel execution."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[
            Parallel(
                Step(name="parallel_step1", executor=simple_step),
                Step(name="parallel_step2", executor=simple_step),
                name="test_parallel",
            )
        ],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    parallel_started = [e for e in events if isinstance(e, ParallelExecutionStartedEvent)]
    parallel_completed = [e for e in events if isinstance(e, ParallelExecutionCompletedEvent)]

    assert len(parallel_started) == 1
    assert len(parallel_completed) == 1


# === Test Streaming with Router Steps ===
def test_router_events(shared_db, mock_run_context):
    """Test streaming events for router execution."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[
            Router(
                name="test_router",
                selector=select_first_step,
                choices=[
                    Step(name="choice1", executor=simple_step),
                    Step(name="choice2", executor=simple_step),
                ],
            )
        ],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    router_started = [e for e in events if isinstance(e, RouterExecutionStartedEvent)]
    router_completed = [e for e in events if isinstance(e, RouterExecutionCompletedEvent)]

    assert len(router_started) == 1
    assert len(router_completed) == 1


# === Test Streaming with Steps (Sequential Group) ===
def test_steps_events(shared_db, mock_run_context):
    """Test streaming events for Steps (sequential group) execution."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[
            Steps(
                name="test_steps",
                steps=[
                    Step(name="grouped_step1", executor=simple_step),
                    Step(name="grouped_step2", executor=simple_step),
                ],
            )
        ],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    steps_started = [e for e in events if isinstance(e, StepsExecutionStartedEvent)]
    steps_completed = [e for e in events if isinstance(e, StepsExecutionCompletedEvent)]

    assert len(steps_started) == 1
    assert len(steps_completed) == 1


# === Test Event Order ===
def test_workflow_events_order(shared_db, mock_run_context):
    """Test that events are in correct order."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[Step(name="test_step", executor=simple_step)],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    workflow_started_idx = None
    step_started_idx = None
    step_completed_idx = None
    workflow_completed_idx = None

    for i, e in enumerate(events):
        if isinstance(e, WorkflowStartedEvent):
            workflow_started_idx = i
        elif isinstance(e, StepStartedEvent):
            step_started_idx = i
        elif isinstance(e, StepCompletedEvent):
            step_completed_idx = i
        elif isinstance(e, WorkflowCompletedEvent):
            workflow_completed_idx = i

    assert workflow_started_idx is not None
    assert step_started_idx is not None
    assert step_completed_idx is not None
    assert workflow_completed_idx is not None

    assert workflow_started_idx < step_started_idx
    assert step_started_idx < step_completed_idx
    assert step_completed_idx < workflow_completed_idx


# === Test Error Handling ===
def test_run_workflow_error_handling(shared_db, mock_run_context_no_stream):
    """Test error handling in run_workflow."""

    def failing_step(step_input: StepInput) -> StepOutput:
        raise ValueError("Step failed")

    workflow = Workflow(name="Test", db=shared_db, steps=[failing_step])
    tools = WorkflowTools(workflow=workflow, stream=False)

    session_state = {}
    result = tools.run_workflow(mock_run_context_no_stream, session_state, RunWorkflowInput(input_data="test"))

    assert "Error" in result or "error" in result.lower()


def test_stream_error_handling(shared_db, mock_run_context):
    """Test error handling in streaming mode."""

    def failing_step(step_input: StepInput) -> StepOutput:
        raise ValueError("Step failed")

    workflow = Workflow(name="Test", db=shared_db, steps=[failing_step])
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    assert len(events) > 0
    last_event = events[-1]
    assert isinstance(last_event, str)
    assert "Error" in last_event or "error" in last_event.lower()


# === Test Input Validation ===
def test_run_workflow_input_model():
    """Test RunWorkflowInput model validation."""
    input_model = RunWorkflowInput(input_data="test", additional_data={"key": "value"})

    assert input_model.input_data == "test"
    assert input_model.additional_data == {"key": "value"}


def test_run_workflow_input_without_additional_data():
    """Test RunWorkflowInput without additional_data."""
    input_model = RunWorkflowInput(input_data="test")

    assert input_model.input_data == "test"
    assert input_model.additional_data is None


# === Test _should_stream helper ===
def test_should_stream_with_explicit_setting(shared_db, mock_run_context):
    """Test _should_stream uses explicit setting when provided."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, stream=False)

    # Even with run_context.stream=True, explicit setting takes precedence
    assert tools._should_stream(mock_run_context) is False


def test_should_stream_inherits_from_context(shared_db, mock_run_context):
    """Test _should_stream inherits from run_context when not explicitly set."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow)  # stream=None

    assert tools._should_stream(mock_run_context) is True


def test_should_stream_defaults_to_true(shared_db):
    """Test _should_stream defaults to True when no context."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow)  # stream=None

    assert tools._should_stream(None) is True


# === Test _should_stream_events helper ===
def test_should_stream_events_with_explicit_setting(shared_db, mock_run_context):
    """Test _should_stream_events uses explicit setting when provided."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow, stream_events=False)

    # Even with run_context.stream_events=True, explicit setting takes precedence
    assert tools._should_stream_events(mock_run_context) is False


def test_should_stream_events_inherits_from_context(shared_db, mock_run_context):
    """Test _should_stream_events inherits from run_context when not explicitly set."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow)  # stream_events=None

    assert tools._should_stream_events(mock_run_context) is True


def test_should_stream_events_defaults_to_true(shared_db):
    """Test _should_stream_events defaults to True when no context."""
    workflow = Workflow(name="Test", db=shared_db, steps=[simple_step])
    tools = WorkflowTools(workflow=workflow)  # stream_events=None

    assert tools._should_stream_events(None) is True
