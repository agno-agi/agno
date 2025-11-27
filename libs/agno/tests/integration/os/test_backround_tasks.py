"""Integration tests for background tasks in AgentOS."""

import asyncio
import json
import time
from typing import Dict
from unittest.mock import AsyncMock, patch

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.run.agent import RunOutput
from fastapi.testclient import TestClient


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
def agent_with_background_hooks(shared_db, execution_tracker):
    """Create an agent with background hooks enabled."""
    
    def pre_hook_log(run_input, agent):
        """Pre-hook that logs request."""
        execution_tracker["pre_hook_executed"] = True
    
    def post_hook_log(run_output: RunOutput, agent: Agent):
        """Post-hook that runs in background."""
        time.sleep(0.5)  # Simulate some work
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
        run_hooks_in_background=True,
    )


@pytest.fixture
def test_os_client_with_background(agent_with_background_hooks):
    """Create a test client with background hooks agent."""
    agent_os = AgentOS(agents=[agent_with_background_hooks])
    app = agent_os.get_app()
    return TestClient(app)


def test_background_hooks_non_streaming(test_os_client_with_background, agent_with_background_hooks, execution_tracker):
    """Test that post-hooks run in background for non-streaming responses."""
    
    response = test_os_client_with_background.post(
        f"/agents/{agent_with_background_hooks.id}/runs",
        data={"message": "Hello, world!", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    
    # Response should be returned immediately
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["run_id"] is not None
    assert response_json["agent_id"] == agent_with_background_hooks.id
    
    # Mark that response was returned
    execution_tracker["response_returned"] = True
    
    # Pre-hooks should have executed (they always block)
    assert execution_tracker["pre_hook_executed"] is True
    
    # Background tasks should have been scheduled but may not be complete yet
    # Wait a bit for background tasks to complete
    time.sleep(1.5)
    
    # Now verify background hooks executed
    assert execution_tracker["post_hook_executed"] is True
    assert execution_tracker["async_post_hook_executed"] is True


def test_background_hooks_streaming(test_os_client_with_background, agent_with_background_hooks, execution_tracker):
    """Test that post-hooks run in background for streaming responses."""
    
    with test_os_client_with_background.stream(
        "POST",
        f"/agents/{agent_with_background_hooks.id}/runs",
        data={"message": "Hello, world!", "stream": "true"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        
        # Collect streaming chunks
        chunks = []
        for line in response.iter_lines():
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
    time.sleep(1.5)
    
    # Verify background hooks executed
    assert execution_tracker["post_hook_executed"] is True
    assert execution_tracker["async_post_hook_executed"] is True


def test_background_hooks_dont_block_response(test_os_client_with_background, agent_with_background_hooks):
    """Test that background hooks don't block the response."""
    
    execution_order = []
    
    def slow_post_hook(run_output: RunOutput):
        """A slow post-hook that should run in background."""
        time.sleep(10)  # Simulate slow operation
        execution_order.append("hook_completed")
    
    # Replace post_hooks with our slow hook
    agent_with_background_hooks.post_hooks = [slow_post_hook]
    
    start_time = time.time()
    
    response = test_os_client_with_background.post(
        f"/agents/{agent_with_background_hooks.id}/runs",
        data={"message": "Hello!", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    
    response_time = time.time() - start_time
    execution_order.append("response_returned")
    
    # Response should be fast (not blocked by 2-second hook)
    assert response.status_code == 200
    assert response_time < 8  # Should be much faster than the 2-second hook
    
    # Verify execution order: response returned before hook completed
    assert execution_order == ["response_returned", "hook_completed"]


def test_background_hooks_with_hook_parameters(test_os_client_with_background, agent_with_background_hooks):
    """Test that background hooks receive correct parameters."""
    
    received_params = {}
    
    def param_checking_hook(run_output: RunOutput, agent: Agent, session, user_id, run_context):
        """Hook that checks it receives expected parameters."""
        received_params["run_output"] = run_output is not None
        received_params["agent"] = agent is not None
        received_params["session"] = session is not None
        received_params["user_id"] = user_id
        received_params["run_context"] = run_context is not None
    
    agent_with_background_hooks.post_hooks = [param_checking_hook]
    
    response = test_os_client_with_background.post(
        f"/agents/{agent_with_background_hooks.id}/runs",
        data={
            "message": "Test parameters",
            "user_id": "test-user-123",
            "stream": "false",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    
    assert response.status_code == 200
    
    # Wait for background task
    time.sleep(0.5)
    
    # Verify all expected parameters were passed
    assert received_params["run_output"] is True
    assert received_params["agent"] is True
    assert received_params["session"] is True
    assert received_params["user_id"] == "test-user-123"
    assert received_params["run_context"] is True


def test_agent_without_background_mode(shared_db):
    """Test that hooks block when background mode is disabled."""
    
    execution_tracker = {"hook_executed": False}
    
    def blocking_post_hook(run_output: RunOutput):
        """Post-hook that should block the response."""
        time.sleep(1)
        execution_tracker["hook_executed"] = True
    
    agent = Agent(
        name="blocking-agent",
        id="blocking-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
        post_hooks=[blocking_post_hook],
        run_hooks_in_background=False,  # Disabled
    )
    
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)
    
    start_time = time.time()
    
    response = client.post(
        f"/agents/{agent.id}/runs",
        data={"message": "Hello!", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    
    response_time = time.time() - start_time
    
    # Response should be slow (blocked by 1-second hook)
    assert response.status_code == 200
    assert response_time >= 1.0  # Should be at least 1 second
    
    # Hook should have already executed
    assert execution_tracker["hook_executed"] is True


def test_background_hooks_with_multiple_hooks(test_os_client_with_background, agent_with_background_hooks):
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
    
    agent_with_background_hooks.post_hooks = [hook1, hook2, hook3]
    
    response = test_os_client_with_background.post(
        f"/agents/{agent_with_background_hooks.id}/runs",
        data={"message": "Test multiple hooks", "stream": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    
    assert response.status_code == 200
    
    # Wait for all background tasks
    time.sleep(1.5)
    
    # All three hooks should have executed
    assert execution_count["count"] == 3

