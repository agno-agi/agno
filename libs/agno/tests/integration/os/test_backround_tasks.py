"""Integration tests for background tasks in AgentOS.

Note on Testing Background Tasks:
When using httpx.AsyncClient with ASGITransport for testing, the ASGI transport
waits for all background tasks to complete before returning the response. This is
by design in the ASGI specification to ensure background tasks finish before app
shutdown. Therefore, we cannot test timing/non-blocking behavior directly.

Instead, we use mocking to verify that hooks are properly added to FastAPI's
BackgroundTasks when run_hooks_in_background=True, which proves they will run
in the background in production environments.

Note: run_hooks_in_background is configured at the AgentOS level (default=False)
and propagated to agents/teams, rather than being set on individual agents.
"""

import asyncio
import json
import time
from typing import Dict
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.run.agent import RunOutput


@pytest.fixture
def execution_tracker() -> Dict[str, bool]:
    """Shared state to track hook execution."""
    return {
        "pre_hook_executed": False,
        "post_hook_executed": False,
        "async_post_hook_executed": False,
        "response_returned": False,
    }


@pytest.fixture
def agent_with_hooks(shared_db, execution_tracker):
    """Create an agent with hooks (background mode is set by AgentOS)."""

    async def pre_hook_log(run_input, agent):
        """Pre-hook that logs request."""
        execution_tracker["pre_hook_executed"] = True

    async def post_hook_log(run_output: RunOutput, agent: Agent):
        """Post-hook that runs in background."""
        await asyncio.sleep(0.5)  # Simulate some work
        execution_tracker["post_hook_executed"] = True

    async def async_post_hook_log(run_output: RunOutput, agent: Agent):
        """Async post-hook that runs in background."""
        await asyncio.sleep(0.5)  # Simulate async work
        execution_tracker["async_post_hook_executed"] = True

    return Agent(
        name="background-task-agent",
        id="background-task-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
        pre_hooks=[pre_hook_log],
        post_hooks=[post_hook_log, async_post_hook_log],
    )


@pytest.fixture
def test_app_with_background(agent_with_hooks):
    """Create a FastAPI app with background hooks enabled."""
    agent_os = AgentOS(agents=[agent_with_hooks], run_hooks_in_background=True)
    return agent_os.get_app()


@pytest.mark.asyncio
async def test_background_hooks_non_streaming(test_app_with_background, agent_with_hooks, execution_tracker):
    """Test that post-hooks run in background for non-streaming responses."""

    async with httpx.AsyncClient(
        transport=ASGITransport(app=test_app_with_background), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/agents/{agent_with_hooks.id}/runs",
            data={"message": "Hello, world!", "stream": "false"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        # Response should be returned immediately
        assert response.status_code == 200
        response_json = response.json()
        assert response_json["run_id"] is not None
        assert response_json["agent_id"] == agent_with_hooks.id

        # Mark that response was returned
        execution_tracker["response_returned"] = True

        # Pre-hooks should have executed (they always block)
        assert execution_tracker["pre_hook_executed"] is True

        # Background tasks should have been scheduled but may not be complete yet
        # Wait a bit for background tasks to complete
        await asyncio.sleep(1.5)

        # Now verify background hooks executed
        assert execution_tracker["post_hook_executed"] is True
        assert execution_tracker["async_post_hook_executed"] is True


@pytest.mark.asyncio
async def test_background_hooks_streaming(test_app_with_background, agent_with_hooks, execution_tracker):
    """Test that post-hooks run in background for streaming responses."""

    async with httpx.AsyncClient(
        transport=ASGITransport(app=test_app_with_background), base_url="http://test"
    ) as client:
        async with client.stream(
            "POST",
            f"/agents/{agent_with_hooks.id}/runs",
            data={"message": "Hello, world!", "stream": "true"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

            # Collect streaming chunks
            chunks = []
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]  # Remove 'data: ' prefix
                    if data != "[DONE]":
                        chunks.append(json.loads(data))

            # Verify we received data
            assert len(chunks) > 0

            # Mark that response was returned
            execution_tracker["response_returned"] = True

            # Pre-hooks should have executed
            assert execution_tracker["pre_hook_executed"] is True

        # Wait for background tasks to complete
        await asyncio.sleep(1.5)

        # Verify background hooks executed
        assert execution_tracker["post_hook_executed"] is True
        assert execution_tracker["async_post_hook_executed"] is True


@pytest.mark.asyncio
async def test_background_hooks_are_added_as_background_tasks(agent_with_hooks):
    """Test that hooks are added to FastAPI background tasks when run_hooks_in_background=True."""

    tasks_added = []

    async def tracked_post_hook(run_output: RunOutput):
        """A post-hook that we can track."""
        tasks_added.append("tracked_post_hook")

    # Replace post_hooks with our tracked hook
    agent_with_hooks.post_hooks = [tracked_post_hook]

    # Mock BackgroundTasks at the FastAPI level
    original_add_task = None

    def mock_add_task(self, func, *args, **kwargs):
        """Mock add_task to track what's being added."""
        tasks_added.append(func.__name__)
        # Call the original to maintain functionality
        if original_add_task:
            return original_add_task(self, func, *args, **kwargs)

    # Patch BackgroundTasks.add_task method
    from fastapi import BackgroundTasks

    original_add_task = BackgroundTasks.add_task

    with patch.object(BackgroundTasks, "add_task", mock_add_task):
        # Create app after patching with background hooks enabled
        agent_os = AgentOS(agents=[agent_with_hooks], run_hooks_in_background=True)
        app = agent_os.get_app()

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/agents/{agent_with_hooks.id}/runs",
                data={"message": "Hello!", "stream": "false"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            # Response should succeed
            assert response.status_code == 200

            # Verify that hooks were added as background tasks
            # The hook function should have been added to tasks
            assert len(tasks_added) > 0, "At least one background task should be added"
            assert "tracked_post_hook" in tasks_added, "Our tracked hook should be in background tasks"


@pytest.mark.asyncio
async def test_background_hooks_with_hook_parameters(test_app_with_background, agent_with_hooks):
    """Test that background hooks receive correct parameters."""

    received_params = {}

    async def param_checking_hook(run_output: RunOutput, agent: Agent, session, user_id, run_context):
        """Hook that checks it receives expected parameters."""
        received_params["run_output"] = run_output is not None
        received_params["agent"] = agent is not None
        received_params["session"] = session is not None
        received_params["user_id"] = user_id
        received_params["run_context"] = run_context is not None

    agent_with_hooks.post_hooks = [param_checking_hook]

    async with httpx.AsyncClient(
        transport=ASGITransport(app=test_app_with_background), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/agents/{agent_with_hooks.id}/runs",
            data={
                "message": "Test parameters",
                "user_id": "test-user-123",
                "stream": "false",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        assert response.status_code == 200

        # Wait for background task
        await asyncio.sleep(0.5)

        # Verify all expected parameters were passed
        assert received_params["run_output"] is True
        assert received_params["agent"] is True
        assert received_params["session"] is True
        assert received_params["user_id"] == "test-user-123"
        assert received_params["run_context"] is True


@pytest.mark.asyncio
async def test_agent_without_background_mode(shared_db):
    """Test that hooks execute synchronously when background mode is disabled on AgentOS."""

    execution_tracker = {"hook_executed": False}
    tasks_added = []

    async def blocking_post_hook(run_output: RunOutput):
        """Post-hook that executes synchronously."""
        execution_tracker["hook_executed"] = True

    agent = Agent(
        name="blocking-agent",
        id="blocking-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
        post_hooks=[blocking_post_hook],
    )

    # Mock add_task to track if hooks are added as background tasks
    original_add_task = None

    def mock_add_task(self, func, *args, **kwargs):
        """Mock add_task to track what's being added."""
        tasks_added.append(func.__name__)
        if original_add_task:
            return original_add_task(self, func, *args, **kwargs)

    from fastapi import BackgroundTasks

    original_add_task = BackgroundTasks.add_task

    with patch.object(BackgroundTasks, "add_task", mock_add_task):
        # Disable background hooks at the AgentOS level
        agent_os = AgentOS(agents=[agent], run_hooks_in_background=False)
        app = agent_os.get_app()

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/agents/{agent.id}/runs",
                data={"message": "Hello!", "stream": "false"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            # Response should succeed
            assert response.status_code == 200

            # Hook should have executed
            assert execution_tracker["hook_executed"] is True

            # Verify that our post hook was NOT added to background tasks
            # When run_hooks_in_background=False on AgentOS, hooks execute synchronously
            assert "blocking_post_hook" not in tasks_added, "Hook should not be added as background task when disabled"


@pytest.mark.asyncio
async def test_background_hooks_with_multiple_hooks(test_app_with_background, agent_with_hooks):
    """Test that multiple background hooks all execute."""

    execution_count = {"count": 0}

    def hook1(run_output: RunOutput):
        time.sleep(0.3)
        execution_count["count"] += 1

    def hook2(run_output: RunOutput):
        time.sleep(0.3)
        execution_count["count"] += 1

    async def hook3(run_output: RunOutput):
        await asyncio.sleep(0.3)
        execution_count["count"] += 1

    agent_with_hooks.post_hooks = [hook1, hook2, hook3]

    async with httpx.AsyncClient(
        transport=ASGITransport(app=test_app_with_background), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/agents/{agent_with_hooks.id}/runs",
            data={"message": "Test multiple hooks", "stream": "false"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        assert response.status_code == 200

        # Wait for all background tasks
        await asyncio.sleep(1.5)

        # All three hooks should have executed
        assert execution_count["count"] == 3


@pytest.mark.asyncio
async def test_agentos_propagates_background_setting_to_agents(shared_db):
    """Test that AgentOS correctly propagates run_hooks_in_background to agents."""

    agent = Agent(
        name="test-agent",
        id="test-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
    )

    # By default, _run_hooks_in_background should be False on the agent
    assert agent._run_hooks_in_background is None

    # When AgentOS is created with run_hooks_in_background=True (default)
    agent_os = AgentOS(agents=[agent], run_hooks_in_background=True)
    agent_os.get_app()

    # The agent's _run_hooks_in_background should now be True
    assert agent._run_hooks_in_background is True


@pytest.mark.asyncio
async def test_agentos_propagates_background_setting_disabled(shared_db):
    """Test that AgentOS correctly propagates run_hooks_in_background=False to agents."""

    agent = Agent(
        name="test-agent",
        id="test-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
    )

    # When AgentOS is created with run_hooks_in_background=False
    agent_os = AgentOS(agents=[agent], run_hooks_in_background=False)
    agent_os.get_app()

    # The agent's _run_hooks_in_background should remain False
    assert agent._run_hooks_in_background is False
