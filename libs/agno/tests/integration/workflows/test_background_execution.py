"""
Integration tests for Workflow background execution functionality.
Tests the background task execution, polling, and status tracking features.
"""

import asyncio

import pytest

from agno.run.base import RunStatus


@pytest.mark.asyncio
async def test_basic_background_execution(simple_workflow):
    """Test basic background execution and polling"""
    # Start background execution
    response = await simple_workflow.arun(input="Test background execution", background=True)

    # Verify initial response
    assert response.status == RunStatus.pending
    assert response.run_id is not None
    assert response.session_id is not None
    assert response.workflow_id is not None

    # Poll for completion
    max_polls = 30  # 30 seconds timeout
    poll_count = 0

    while poll_count < max_polls:
        poll_count += 1
        result = simple_workflow.get_run(response.run_id)

        if result is None:
            await asyncio.sleep(1)
            continue

        if result.has_completed():
            # Verify completed response
            assert result.status == RunStatus.completed
            assert result.run_id == response.run_id
            assert result.session_id == response.session_id
            assert result.content is not None
            assert len(result.step_results) > 0
            break

        await asyncio.sleep(1)

    assert poll_count < max_polls, "Background execution timed out"


@pytest.mark.asyncio
async def test_multi_step_background_execution(multi_step_workflow):
    """Test background execution with multiple steps"""
    # Start background execution
    response = await multi_step_workflow.arun(input="Test multi-step background execution", background=True)

    # Verify initial response
    assert response.status == RunStatus.pending
    assert response.run_id is not None

    # Poll for completion with step tracking
    max_polls = 60  # Longer timeout for multi-step
    poll_count = 0
    completed = False

    while poll_count < max_polls:
        poll_count += 1
        result = multi_step_workflow.get_run(response.run_id)

        if result is None:
            await asyncio.sleep(1)
            continue

        # Track that we saw running status
        if result.status == RunStatus.completed:
            completed = True

        if result.has_completed():
            # Verify completed response
            assert result.status == RunStatus.completed
            assert len(result.step_results) == 2  # Two steps
            assert result.metrics is not None
            assert len(result.metrics.steps) == 2
            break

        await asyncio.sleep(1)

    assert poll_count < max_polls, "Multi-step background execution timed out"
    assert completed, "Should have seen completed status during execution"


@pytest.mark.asyncio
async def test_team_background_execution(team_workflow):
    """Test background execution with team"""
    # Start background execution
    response = await team_workflow.arun(input="Analyze AI trends for team collaboration", background=True)

    # Verify initial response
    assert response.status == RunStatus.pending
    assert response.run_id is not None

    # Poll for completion
    max_polls = 120  # Longer timeout for team execution
    poll_count = 0

    while poll_count < max_polls:
        poll_count += 1
        result = team_workflow.get_run(response.run_id)

        if result is None:
            await asyncio.sleep(1)
            continue

        if result.has_completed():
            # Verify completed response
            assert result.status == RunStatus.completed
            assert result.content is not None
            assert len(result.step_results) > 0
            break

        await asyncio.sleep(1)

    assert poll_count < max_polls, "Team background execution timed out"


@pytest.mark.asyncio
async def test_custom_function_background_execution(custom_function_workflow):
    """Test background execution with custom async function"""
    # Start background execution
    response = await custom_function_workflow.arun(input="Test custom function background", background=True)

    # Verify initial response
    assert response.status == RunStatus.pending
    assert response.run_id is not None

    # Poll for completion
    max_polls = 20  # Shorter timeout for simple function
    poll_count = 0

    while poll_count < max_polls:
        poll_count += 1
        result = custom_function_workflow.get_run(response.run_id)

        if result is None:
            await asyncio.sleep(1)
            continue

        if result.has_completed():
            # Verify completed response
            assert result.status == RunStatus.completed
            assert "Custom function processed" in result.content
            break

        await asyncio.sleep(1)

    assert poll_count < max_polls, "Custom function background execution timed out"


def test_sync_background_execution_raises_error(simple_workflow):
    """Test that sync run with background=True raises an error"""
    with pytest.raises(RuntimeError, match="Background execution is not supported for sync run"):
        simple_workflow.run(input="This should fail", background=True)


@pytest.mark.asyncio
async def test_condition_background_execution(condition_workflow):
    """Test background execution with conditional steps"""
    # Test with content that should trigger fact-checking
    response = await condition_workflow.arun(
        input="Recent study shows that AI research has increased by 300% according to data", background=True
    )

    # Verify initial response
    assert response.status == RunStatus.pending
    assert response.run_id is not None

    # Poll for completion
    max_polls = 120  # Longer timeout for conditional execution
    poll_count = 0

    while poll_count < max_polls:
        poll_count += 1
        result = condition_workflow.get_run(response.run_id)

        if result is None:
            await asyncio.sleep(1)
            continue

        if result.has_completed():
            # Verify completed response
            assert result.status == RunStatus.completed
            assert result.content is not None
            # Should have at least 3 steps: Initial Research + Fact Check + Final Summary
            assert len(result.step_results) >= 3
            break

        await asyncio.sleep(1)

    assert poll_count < max_polls, "Conditional background execution timed out"


@pytest.mark.asyncio
async def test_parallel_background_execution(parallel_workflow):
    """Test background execution with parallel steps"""
    response = await parallel_workflow.arun(
        input="Analyze the latest developments in artificial intelligence", background=True
    )

    # Verify initial response
    assert response.status == RunStatus.pending
    assert response.run_id is not None

    # Poll for completion
    max_polls = 120  # Longer timeout for parallel execution
    poll_count = 0

    while poll_count < max_polls:
        poll_count += 1
        result = parallel_workflow.get_run(response.run_id)

        if result is None:
            await asyncio.sleep(1)
            continue

        if result.has_completed():
            # Verify completed response
            assert result.status == RunStatus.completed
            assert result.content is not None
            # Should have parallel steps + writer step
            assert len(result.step_results) >= 2
            break

        await asyncio.sleep(1)

    assert poll_count < max_polls, "Parallel background execution timed out"


@pytest.mark.asyncio
async def test_router_background_execution(router_workflow):
    """Test background execution with router"""
    response = await router_workflow.arun(
        input="Latest developments in machine learning and AI programming", background=True
    )

    # Verify initial response
    assert response.status == RunStatus.pending
    assert response.run_id is not None

    # Poll for completion
    max_polls = 45
    poll_count = 0

    while poll_count < max_polls:
        poll_count += 1
        result = router_workflow.get_run(response.run_id)

        if result is None:
            await asyncio.sleep(1)
            continue

        if result.has_completed():
            # Verify completed response
            assert result.status == RunStatus.completed
            assert result.content is not None
            # Should have router step + writer step
            assert len(result.step_results) >= 2
            break

        await asyncio.sleep(1)

    assert poll_count < max_polls, "Router (tech) background execution timed out"


@pytest.mark.asyncio
async def test_loop_background_execution(loop_workflow):
    """Test background execution with loop"""
    response = await loop_workflow.arun(input="Research sustainable energy solutions", background=True)

    # Verify initial response
    assert response.status == RunStatus.pending
    assert response.run_id is not None

    # Poll for completion
    max_polls = 120  # Longer timeout for loop execution
    poll_count = 0

    while poll_count < max_polls:
        poll_count += 1
        result = loop_workflow.get_run(response.run_id)

        if result is None:
            await asyncio.sleep(1)
            continue

        if result.has_completed():
            # Verify completed response
            assert result.status == RunStatus.completed
            assert result.content is not None
            # Should have loop iterations + content creator step
            assert len(result.step_results) >= 2
            break

        await asyncio.sleep(1)

    assert poll_count < max_polls, "Loop background execution timed out"
