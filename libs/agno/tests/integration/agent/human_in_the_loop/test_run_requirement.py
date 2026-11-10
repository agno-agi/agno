"""Tests for the RunRequirement class, used to handle HITL flows"""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.decorator import tool


def test_run_requirement_needs_confirmation_flag(shared_db):
    """Test that needs_confirmation flag is set correctly"""

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")
    requirement = response.active_requirements[0]

    assert requirement.needs_confirmation is True
    assert requirement.needs_user_input is False
    assert requirement.needs_external_execution is False


def test_run_requirement_needs_user_input_flag(shared_db):
    """Test that needs_user_input flag is set correctly"""

    @tool(requires_user_input=True)
    def get_user_preference(preference_type: str) -> str:
        return f"User preference for {preference_type}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_user_preference],
        db=shared_db,
        telemetry=False,
    )

    response = agent.run("What is my food preference?")
    requirement = response.active_requirements[0]

    assert requirement.needs_confirmation is False
    assert requirement.needs_user_input is True
    assert requirement.needs_external_execution is False


def test_run_requirement_confirm_method(shared_db):
    """Test that requirement.confirm() correctly marks the tool as confirmed"""

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")
    assert response.is_paused
    assert len(response.active_requirements) == 1

    requirement = response.active_requirements[0]
    assert requirement.needs_confirmation is True
    assert requirement.confirmation is None
    assert requirement.is_resolved() is False

    requirement.confirm()

    # Verify the requirement was confirmed and the tool was updated
    assert requirement.confirmation is True
    assert requirement.tool_execution and requirement.tool_execution.confirmed is True
    assert requirement.is_resolved() is True


def test_run_requirement_reject_method(shared_db):
    """Test that requirement.reject() correctly marks the tool as rejected"""

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")
    assert response.is_paused
    assert len(response.active_requirements) == 1

    requirement = response.active_requirements[0]
    assert requirement.needs_confirmation is True
    assert requirement.confirmation is None
    assert requirement.is_resolved() is False

    requirement.reject()

    # Verify the requirement was rejected and the tool was updated
    assert requirement.confirmation is False
    assert requirement.tool_execution and requirement.tool_execution.confirmed is False
    assert requirement.is_resolved() is True


def test_run_requirement_confirm_raises_error_when_not_needed(shared_db):
    """Test that calling confirm() on a requirement that doesn't need confirmation raises ValueError"""

    @tool(requires_user_input=True)
    def get_user_preference(preference_type: str) -> str:
        return f"User preference for {preference_type}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_user_preference],
        db=shared_db,
        telemetry=False,
    )

    response = agent.run("What is my food preference?")
    assert response.is_paused
    assert len(response.active_requirements) == 1

    requirement = response.active_requirements[0]
    assert requirement.needs_confirmation is False
    assert requirement.needs_user_input is True

    # Calling confirm() should raise ValueError
    with pytest.raises(ValueError, match="This requirement does not require confirmation"):
        requirement.confirm()


def test_run_requirement_reject_raises_error_when_not_needed(shared_db):
    """Test that calling reject() on a requirement that doesn't need confirmation raises ValueError"""

    @tool(requires_user_input=True)
    def get_user_preference(preference_type: str) -> str:
        return f"User preference for {preference_type}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_user_preference],
        db=shared_db,
        telemetry=False,
    )

    response = agent.run("What is my food preference?")
    assert response.is_paused
    assert len(response.active_requirements) == 1

    requirement = response.active_requirements[0]
    assert requirement.needs_confirmation is False

    # Calling reject() should raise ValueError
    with pytest.raises(ValueError, match="This requirement does not require confirmation"):
        requirement.reject()


@pytest.mark.asyncio
async def test_run_requirement_async_context(shared_db):
    """Test that RunRequirement works correctly in async context"""

    @tool(requires_confirmation=True)
    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=shared_db,
        telemetry=False,
    )

    response = await agent.arun("What is the weather in Tokyo?")
    assert response.is_paused
    assert len(response.active_requirements) == 1

    requirement = response.active_requirements[0]
    assert requirement.is_resolved() is False

    requirement.confirm()

    # Verify confirmation works in async context
    assert requirement.confirmation is True
    assert requirement.is_resolved() is True
