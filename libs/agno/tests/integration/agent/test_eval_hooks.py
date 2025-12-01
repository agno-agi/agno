"""Integration tests for using Eval classes as Agent hooks."""

import pytest

from agno.agent import Agent
from agno.eval import AccuracyEval, PerformanceEval, ReliabilityEval
from agno.models.openai import OpenAIChat


@pytest.mark.asyncio
async def test_accuracy_eval_as_post_hook_async(shared_db):
    """Test that AccuracyEval works as a post-hook (async)."""
    accuracy_eval = AccuracyEval(
        input="What is 2+2?",
        expected_output="4",
        db=shared_db,
        telemetry=False,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        post_hooks=[accuracy_eval],
        markdown=True,
        telemetry=False,
    )

    result = await agent.arun("What is 2+2?")

    assert result is not None
    assert result.run_id is not None

    # Verify the eval was stored in database
    evals = shared_db.get_eval_runs(eval_id=accuracy_eval.eval_id)

    assert len(evals) == 1

    eval_run = evals[0]

    # Verify eval_id
    assert eval_run.eval_id == accuracy_eval.eval_id

    # Verify run_id is unique and not None
    assert eval_run.run_id is not None
    assert eval_run.run_id != accuracy_eval.eval_id  # run_id should be different from eval_id

    # Verify parent_run_id links to agent run
    assert eval_run.parent_run_id is not None
    assert eval_run.parent_run_id == result.run_id

    # Verify parent_session_id
    assert eval_run.parent_session_id is not None

    # Verify agent_id
    assert eval_run.agent_id == agent.id
    assert eval_run.team_id is None

    # Verify eval_type
    assert eval_run.eval_type.value == "accuracy"

    # Verify eval_input contains all the configuration
    assert eval_run.eval_input is not None
    assert eval_run.eval_input["input"] == "What is 2+2?"
    assert eval_run.eval_input["expected_output"] == "4"
    assert "num_iterations" in eval_run.eval_input

    # Verify eval_data exists (the results)
    assert eval_run.eval_data is not None

    # Verify model info
    assert eval_run.model_id == "gpt-4o-mini"
    assert eval_run.model_provider == "OpenAI"


def test_accuracy_eval_as_post_hook_sync(shared_db):
    """Test that AccuracyEval works as a post-hook (sync)."""
    accuracy_eval = AccuracyEval(
        input="What is the capital of France?",
        expected_output="Paris",
        db=shared_db,
        telemetry=False,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        post_hooks=[accuracy_eval],
        markdown=True,
        telemetry=False,
    )

    result = agent.run("What is the capital of France?")

    assert result is not None
    assert result.run_id is not None

    # Verify the eval was stored
    evals = shared_db.get_eval_runs(eval_id=accuracy_eval.eval_id)

    assert len(evals) >= 1

    eval_run = evals[-1]

    # Verify all critical fields
    assert eval_run.eval_id == accuracy_eval.eval_id
    assert eval_run.run_id is not None
    assert eval_run.run_id != eval_run.eval_id
    assert eval_run.parent_run_id == result.run_id
    assert eval_run.parent_session_id is not None
    assert eval_run.agent_id == agent.id
    assert eval_run.team_id is None
    assert eval_run.eval_type.value == "accuracy"
    assert eval_run.eval_input is not None
    assert eval_run.eval_input["input"] == "What is the capital of France?"
    assert eval_run.eval_input["expected_output"] == "Paris"
    assert eval_run.eval_data is not None
    assert eval_run.model_id == "gpt-4o-mini"
    assert eval_run.model_provider == "OpenAI"


@pytest.mark.asyncio
async def test_performance_eval_as_post_hook_async(shared_db):
    """Test that PerformanceEval works as a post-hook (async)."""

    async def sample_func():
        return sum(range(1000))

    performance_eval = PerformanceEval(
        func=sample_func,
        db=shared_db,
        telemetry=False,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        post_hooks=[performance_eval],
        markdown=True,
        telemetry=False,
    )

    result = await agent.arun("Hello")

    assert result is not None

    # Verify the eval was stored
    evals = shared_db.get_eval_runs(eval_id=performance_eval.eval_id)

    assert len(evals) == 1

    eval_run = evals[0]

    # Verify all critical fields
    assert eval_run.eval_id == performance_eval.eval_id
    assert eval_run.run_id is not None
    assert eval_run.run_id != eval_run.eval_id
    assert eval_run.parent_run_id == result.run_id
    assert eval_run.parent_session_id is not None
    assert eval_run.agent_id == agent.id
    assert eval_run.team_id is None
    assert eval_run.eval_type.value == "performance"
    assert eval_run.eval_data is not None
    assert eval_run.model_id == "gpt-4o-mini"
    assert eval_run.model_provider == "OpenAI"


def test_performance_eval_as_post_hook_sync(shared_db):
    """Test that PerformanceEval works as a post-hook (sync)."""

    def sample_func():
        return sum(range(1000))

    performance_eval = PerformanceEval(
        func=sample_func,
        db=shared_db,
        telemetry=False,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        post_hooks=[performance_eval],
        markdown=True,
        telemetry=False,
    )

    result = agent.run("Hello")

    assert result is not None

    # Verify the eval was stored
    evals = shared_db.get_eval_runs(eval_id=performance_eval.eval_id)

    assert len(evals) >= 1

    eval_run = evals[-1]

    # Verify all critical fields
    assert eval_run.eval_id == performance_eval.eval_id
    assert eval_run.run_id is not None
    assert eval_run.parent_run_id == result.run_id
    assert eval_run.agent_id == agent.id
    assert eval_run.eval_type.value == "performance"
    assert eval_run.eval_data is not None


@pytest.mark.asyncio
async def test_reliability_eval_as_post_hook_async(shared_db):
    """Test that ReliabilityEval works as a post-hook (async)."""
    reliability_eval = ReliabilityEval(
        expected_tool_calls=["web_search"],
        db=shared_db,
        telemetry=False,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        post_hooks=[reliability_eval],
        markdown=True,
        telemetry=False,
    )

    result = await agent.arun("Search for Python")

    assert result is not None

    # Verify the eval was stored
    evals = shared_db.get_eval_runs(eval_id=reliability_eval.eval_id)

    assert len(evals) == 1

    eval_run = evals[0]

    # Verify all critical fields
    assert eval_run.eval_id == reliability_eval.eval_id
    assert eval_run.run_id is not None
    assert eval_run.parent_run_id == result.run_id
    assert eval_run.parent_session_id is not None
    assert eval_run.agent_id == agent.id
    assert eval_run.team_id is None
    assert eval_run.eval_type.value == "reliability"
    assert eval_run.eval_data is not None


def test_reliability_eval_as_post_hook_sync(shared_db):
    """Test that ReliabilityEval works as a post-hook (sync)."""
    reliability_eval = ReliabilityEval(
        expected_tool_calls=["calculator"],
        db=shared_db,
        telemetry=False,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        post_hooks=[reliability_eval],
        markdown=True,
        telemetry=False,
    )

    result = agent.run("Calculate 5 + 5")

    assert result is not None

    # Verify the eval was stored
    evals = shared_db.get_eval_runs(eval_id=reliability_eval.eval_id)

    assert len(evals) >= 1

    eval_run = evals[-1]

    # Verify all critical fields
    assert eval_run.eval_id == reliability_eval.eval_id
    assert eval_run.run_id is not None
    assert eval_run.parent_run_id == result.run_id
    assert eval_run.agent_id == agent.id
    assert eval_run.eval_type.value == "reliability"
    assert eval_run.eval_data is not None


@pytest.mark.asyncio
async def test_multiple_evals_as_post_hooks(shared_db):
    """Test that multiple eval types can work together as post-hooks."""
    accuracy_eval = AccuracyEval(
        input="What is 10 + 5?",
        expected_output="15",
        db=shared_db,
        telemetry=False,
    )

    async def sample_func():
        return "test"

    performance_eval = PerformanceEval(
        func=sample_func,
        db=shared_db,
        telemetry=False,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        post_hooks=[accuracy_eval, performance_eval],
        markdown=True,
        telemetry=False,
    )

    result = await agent.arun("What is 10 + 5?")

    assert result is not None

    # Verify both evals were stored
    accuracy_evals = shared_db.get_eval_runs(eval_id=accuracy_eval.eval_id)
    performance_evals = shared_db.get_eval_runs(eval_id=performance_eval.eval_id)

    assert len(accuracy_evals) == 1
    assert len(performance_evals) == 1

    accuracy_run = accuracy_evals[0]
    performance_run = performance_evals[0]

    # Verify both evals have correct types
    assert accuracy_run.eval_type.value == "accuracy"
    assert performance_run.eval_type.value == "performance"

    # Verify both share the same parent_run_id (from the agent run)
    assert accuracy_run.parent_run_id == result.run_id
    assert performance_run.parent_run_id == result.run_id
    assert accuracy_run.parent_run_id == performance_run.parent_run_id

    # Verify both share the same parent_session_id
    assert accuracy_run.parent_session_id == performance_run.parent_session_id

    # Verify both have same agent_id
    assert accuracy_run.agent_id == agent.id
    assert performance_run.agent_id == agent.id

    # Verify both have different run_ids
    assert accuracy_run.run_id != performance_run.run_id


@pytest.mark.asyncio
async def test_eval_id_persistence_across_runs(shared_db):
    """Test that the same eval maintains eval_id across multiple runs."""
    accuracy_eval = AccuracyEval(
        input="What is 3+3?",
        expected_output="6",
        db=shared_db,
        telemetry=False,
    )

    eval_id = accuracy_eval.eval_id

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        post_hooks=[accuracy_eval],
        markdown=True,
        telemetry=False,
    )

    # Run multiple times
    await agent.arun("What is 3+3?")
    await agent.arun("What is 3+3?")

    # Verify both runs have same eval_id but different run_ids
    evals = shared_db.get_eval_runs(eval_id=eval_id)

    assert len(evals) == 2

    # Verify both share the same eval_id
    assert evals[0].eval_id == eval_id
    assert evals[1].eval_id == eval_id

    # Verify they have different run_ids (each execution gets unique run_id)
    assert evals[0].run_id != evals[1].run_id

    # Verify they have different parent_run_ids (different agent runs)
    assert evals[0].parent_run_id != evals[1].parent_run_id

    # Verify both have the same agent_id
    assert evals[0].agent_id == agent.id
    assert evals[1].agent_id == agent.id

    # Verify both have eval_data
    assert evals[0].eval_data is not None
    assert evals[1].eval_data is not None
