"""
Tests for custom member delegation function feature.

This test file validates that the member_delegation_function parameter
allows users to override the default member delegation behavior.
"""

from dataclasses import fields
from typing import AsyncIterator, Iterator, Union

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput, RunOutputEvent
from agno.run.team import TeamRunOutput, TeamRunOutputEvent
from agno.team.team import MemberDelegationContext, Team


# Track delegation calls for testing
delegation_tracker = {"calls": [], "contexts": []}


def clear_delegation_tracker():
    """Clear the delegation tracker for clean tests."""
    delegation_tracker["calls"].clear()
    delegation_tracker["contexts"].clear()


def sync_custom_delegation(
    context: MemberDelegationContext,
) -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent, RunOutput, TeamRunOutput, str]]:
    """Sync custom delegation function for testing."""
    agent_name = context.member_agent.name or "Unknown"
    delegation_tracker["calls"].append(f"sync:{agent_name}")
    delegation_tracker["contexts"].append(context)

    # Run the member agent
    run_response = context.member_agent.run(
        input=context.input,
        user_id=context.user_id,
        session_id=context.session_id,
        session_state=context.session_state,
        images=context.images,
        videos=context.videos,
        audio=context.audio,
        files=context.files,
        stream=False,
        debug_mode=context.debug_mode,
    )

    content = run_response.content
    if isinstance(content, str) and content.strip():
        yield content
    else:
        yield f"No response from {agent_name}"

    yield run_response


async def async_custom_delegation(
    context: MemberDelegationContext,
) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, RunOutput, TeamRunOutput, str]]:
    """Async custom delegation function for testing."""
    agent_name = context.member_agent.name or "Unknown"
    delegation_tracker["calls"].append(f"async:{agent_name}")
    delegation_tracker["contexts"].append(context)

    # Run the member agent asynchronously
    run_response = await context.member_agent.arun(
        input=context.input,
        user_id=context.user_id,
        session_id=context.session_id,
        session_state=context.session_state,
        images=context.images,
        videos=context.videos,
        audio=context.audio,
        files=context.files,
        stream=False,
        debug_mode=context.debug_mode,
    )

    content = run_response.content
    if isinstance(content, str) and content.strip():
        yield content
    else:
        yield f"No response from {agent_name}"

    yield run_response


# ==================== Validation Tests ====================


def test_sync_delegation_with_async_function_raises_error():
    """Test that using an async function with run() raises ValueError early."""
    agent = Agent(
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful assistant.",
    )

    team = Team(
        name="Test Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        member_delegation_function=async_custom_delegation,  # Async function
        instructions="Delegate all tasks to your member agent.",
    )

    with pytest.raises(ValueError) as exc_info:
        team.run("Say hello.")

    assert "async function" in str(exc_info.value).lower()
    assert "run()" in str(exc_info.value) or "sync" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_async_delegation_with_sync_function_raises_error():
    """Test that using a sync function with arun() raises ValueError early."""
    agent = Agent(
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful assistant.",
    )

    team = Team(
        name="Test Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        member_delegation_function=sync_custom_delegation,  # Sync function
        instructions="Delegate all tasks to your member agent.",
    )

    with pytest.raises(ValueError) as exc_info:
        await team.arun("Say hello.")

    assert "sync function" in str(exc_info.value).lower()
    assert "arun()" in str(exc_info.value) or "async" in str(exc_info.value).lower()


# ==================== Structure Tests ====================


def test_member_delegation_context_dataclass():
    """Test that MemberDelegationContext is properly structured."""
    field_names = [f.name for f in fields(MemberDelegationContext)]

    expected_fields = [
        "member_agent",
        "input",
        "user_id",
        "session_id",
        "session_state",
        "images",
        "videos",
        "audio",
        "files",
        "stream",
        "stream_events",
        "debug_mode",
        "dependencies",
        "add_dependencies_to_context",
        "add_session_state_to_context",
        "metadata",
        "knowledge_filters",
        "parent_run_id",
    ]

    for field in expected_fields:
        assert field in field_names, f"Expected field '{field}' not found in MemberDelegationContext"


def test_member_delegation_function_attribute():
    """Test that member_delegation_function attribute is properly set."""
    agent = Agent(
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    # Test with custom function
    team_with_custom = Team(
        name="Custom Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        member_delegation_function=sync_custom_delegation,
    )
    assert team_with_custom.member_delegation_function == sync_custom_delegation

    # Test without custom function
    team_without_custom = Team(
        name="Default Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
    )
    assert team_without_custom.member_delegation_function is None


# ==================== Integration Tests ====================


def test_sync_custom_delegation():
    """Test that sync custom delegation function is called during run()."""
    clear_delegation_tracker()

    agent = Agent(
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful assistant. Keep responses brief.",
    )

    team = Team(
        name="Test Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        member_delegation_function=sync_custom_delegation,
        instructions="Delegate all tasks to your member agent.",
    )

    response = team.run("Say hello in one word.")

    assert response is not None
    assert response.content is not None

    # Verify custom delegation was called
    assert len(delegation_tracker["calls"]) >= 1
    assert any("sync:Test Agent" in call for call in delegation_tracker["calls"])


@pytest.mark.asyncio
async def test_async_custom_delegation():
    """Test that async custom delegation function is called during arun()."""
    clear_delegation_tracker()

    agent = Agent(
        name="Async Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful assistant. Keep responses brief.",
    )

    team = Team(
        name="Async Test Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        member_delegation_function=async_custom_delegation,
        instructions="Delegate all tasks to your member agent.",
    )

    response = await team.arun("Say hello in one word.")

    assert response is not None
    assert response.content is not None

    # Verify async custom delegation was called
    assert len(delegation_tracker["calls"]) >= 1
    assert any("async:Async Test Agent" in call for call in delegation_tracker["calls"])


def test_delegation_context_contains_expected_fields():
    """Test that MemberDelegationContext contains all expected fields when delegation occurs."""
    clear_delegation_tracker()

    agent = Agent(
        name="Context Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful assistant.",
    )

    team = Team(
        name="Context Test Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        member_delegation_function=sync_custom_delegation,
        instructions="Delegate all tasks to your member agent.",
    )

    team.run(
        "Say hello.",
        user_id="test_user",
        session_state={"key": "value"},
        metadata={"meta_key": "meta_value"},
    )

    # Verify context was captured
    assert len(delegation_tracker["contexts"]) >= 1

    context = delegation_tracker["contexts"][0]

    # Check required fields exist
    assert context.member_agent is not None
    assert context.input is not None
    assert context.session_id is not None
    assert context.stream is not None
    assert context.debug_mode is not None
    assert context.add_dependencies_to_context is not None
    assert context.add_session_state_to_context is not None
    assert context.parent_run_id is not None


def test_custom_delegation_with_multiple_members():
    """Test custom delegation with multiple team members."""
    clear_delegation_tracker()

    agent1 = Agent(
        name="Agent One",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are the first agent.",
    )

    agent2 = Agent(
        name="Agent Two",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are the second agent.",
    )

    team = Team(
        name="Multi-Agent Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent1, agent2],
        member_delegation_function=sync_custom_delegation,
        instructions="Delegate tasks to Agent One for greetings and Agent Two for farewells.",
    )

    response = team.run("Say hello and goodbye.")

    assert response is not None
    assert response.content is not None

    # At least one delegation should have occurred
    assert len(delegation_tracker["calls"]) >= 1


def test_custom_delegation_with_delegate_to_all_members():
    """Test custom delegation with delegate_to_all_members=True."""
    clear_delegation_tracker()

    agent1 = Agent(
        name="Research Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You provide research insights.",
    )

    agent2 = Agent(
        name="Analysis Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You provide analysis.",
    )

    team = Team(
        name="Parallel Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent1, agent2],
        member_delegation_function=sync_custom_delegation,
        delegate_to_all_members=True,
        instructions="Forward the task to all members.",
    )

    response = team.run("What is 2+2?")

    assert response is not None
    assert response.content is not None

    # Both agents should have been delegated to
    assert len(delegation_tracker["calls"]) == 2
    agent_names = [call.split(":")[1] for call in delegation_tracker["calls"]]
    assert "Research Agent" in agent_names
    assert "Analysis Agent" in agent_names


@pytest.mark.asyncio
async def test_async_custom_delegation_with_delegate_to_all_members():
    """Test async custom delegation with delegate_to_all_members=True."""
    clear_delegation_tracker()

    agent1 = Agent(
        name="Async Research Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You provide research insights.",
    )

    agent2 = Agent(
        name="Async Analysis Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You provide analysis.",
    )

    team = Team(
        name="Async Parallel Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent1, agent2],
        member_delegation_function=async_custom_delegation,
        delegate_to_all_members=True,
        instructions="Forward the task to all members.",
    )

    response = await team.arun("What is 2+2?")

    assert response is not None
    assert response.content is not None

    # Both agents should have been delegated to
    assert len(delegation_tracker["calls"]) == 2
    agent_names = [call.split(":")[1] for call in delegation_tracker["calls"]]
    assert "Async Research Agent" in agent_names
    assert "Async Analysis Agent" in agent_names


def test_default_delegation_when_no_custom_function():
    """Test that default delegation is used when no custom function is provided."""
    agent = Agent(
        name="Default Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful assistant.",
    )

    team = Team(
        name="Default Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        # No member_delegation_function provided
        instructions="Delegate all tasks to your member agent.",
    )

    response = team.run("Say hello in one word.")

    assert response is not None
    assert response.content is not None
    # Should work without custom function
