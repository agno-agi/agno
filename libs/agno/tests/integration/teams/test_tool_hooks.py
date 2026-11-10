"""Tests for tool hooks receiving messages in team runs via run_context.messages."""

from typing import Any, Callable, Dict

import pytest

from agno.agent import Agent
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.run.base import RunContext
from agno.team import Team
from agno.tools import FunctionCall
from agno.tools.decorator import tool

MODEL = "gpt-4o-mini"

captured_messages: Dict[str, Any] = {}


def messages_pre_hook(run_context: RunContext, fc: FunctionCall):
    msgs = run_context.messages
    captured_messages["pre"] = {
        "count": len(msgs) if msgs else 0,
        "has_user": any(m.role == "user" for m in msgs) if msgs else False,
    }


def messages_post_hook(run_context: RunContext, fc: FunctionCall):
    msgs = run_context.messages
    captured_messages["post"] = {
        "count": len(msgs) if msgs else 0,
        "result": fc.result,
    }


def messages_tool_hook(
    run_context: RunContext,
    function_name: str,
    function_call: Callable[..., Any],
    arguments: Dict[str, Any],
) -> Any:
    msgs = run_context.messages
    captured_messages["tool_hook"] = {
        "count": len(msgs) if msgs else 0,
        "has_user": any(m.role == "user" for m in msgs) if msgs else False,
    }
    return function_call(**arguments)


@tool(pre_hook=messages_pre_hook, post_hook=messages_post_hook)
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Sunny, 72F in {city}"


@tool()
def get_time(city: str) -> str:
    """Get the current time for a city."""
    return f"3:00 PM in {city}"


def test_coordinate_mode_member_hooks_receive_messages():
    """Test that member tool hooks receive messages in coordinate mode."""
    captured_messages.clear()
    member = Agent(
        name="Weather Agent",
        role="Get weather information",
        model=OpenAIChat(id=MODEL),
        tools=[get_weather],
        instructions=["Use the get_weather tool to answer."],
    )
    team = Team(
        name="Test Team",
        model=OpenAIChat(id=MODEL),
        members=[member],
        mode="coordinate",
        instructions=["Delegate weather questions to Weather Agent."],
    )

    response = team.run("What is the weather in Cairo?")

    assert response.content is not None
    assert captured_messages["pre"]["count"] > 0
    assert captured_messages["pre"]["has_user"] is True
    assert captured_messages["post"]["count"] > 0
    assert "72F" in captured_messages["post"]["result"]


def test_route_mode_member_hooks_receive_messages():
    """Test that member tool hooks receive messages in route mode."""
    captured_messages.clear()
    member = Agent(
        name="Weather Agent",
        role="Get weather information",
        model=OpenAIChat(id=MODEL),
        tools=[get_weather],
        instructions=["Use the get_weather tool to answer."],
    )
    team = Team(
        name="Test Team",
        model=OpenAIChat(id=MODEL),
        members=[member],
        mode="route",
        instructions=["Delegate weather questions to Weather Agent."],
    )

    response = team.run("What is the weather in Lagos?")

    assert response.content is not None
    assert captured_messages["pre"]["count"] > 0
    assert captured_messages["pre"]["has_user"] is True


def test_member_tool_hook_receives_messages():
    """Test that agent-level tool_hooks on members receive messages."""
    captured_messages.clear()
    member = Agent(
        name="Time Agent",
        role="Get time information",
        model=OpenAIChat(id=MODEL),
        tools=[get_time],
        tool_hooks=[messages_tool_hook],
        instructions=["Use the get_time tool to answer."],
    )
    team = Team(
        name="Test Team",
        model=OpenAIChat(id=MODEL),
        members=[member],
        mode="coordinate",
        instructions=["Delegate time questions to Time Agent."],
    )

    response = team.run("What is the time in Seoul?")

    assert response.content is not None
    assert captured_messages["tool_hook"]["count"] > 0
    assert captured_messages["tool_hook"]["has_user"] is True


def test_mutation_does_not_affect_team_run():
    """Test that mutating run_context.messages in a hook does not corrupt the team run."""

    def mutating_hook(run_context: RunContext, fc: FunctionCall):
        if run_context.messages:
            run_context.messages.clear()
            run_context.messages.append(Message(role="user", content="INJECTED"))

    @tool(pre_hook=mutating_hook)
    def get_temperature(city: str) -> str:
        """Get the temperature for a city."""
        return f"25C in {city}"

    member = Agent(
        name="Temp Agent",
        role="Get temperature information",
        model=OpenAIChat(id=MODEL),
        tools=[get_temperature],
        instructions=["Use the get_temperature tool to answer."],
    )
    team = Team(
        name="Test Team",
        model=OpenAIChat(id=MODEL),
        members=[member],
        mode="coordinate",
        instructions=["Delegate to Temp Agent."],
    )

    response = team.run("What is the temperature in Sydney?")

    assert response.content is not None


@pytest.mark.asyncio
async def test_async_coordinate_mode_hooks_receive_messages():
    """Test that member tool hooks receive messages in async coordinate mode."""
    captured_messages.clear()
    member = Agent(
        name="Weather Agent",
        role="Get weather information",
        model=OpenAIChat(id=MODEL),
        tools=[get_weather],
        instructions=["Use the get_weather tool to answer."],
    )
    team = Team(
        name="Test Team",
        model=OpenAIChat(id=MODEL),
        members=[member],
        mode="coordinate",
        instructions=["Delegate weather questions to Weather Agent."],
    )

    response = await team.arun("What is the weather in Tokyo?")

    assert response.content is not None
    assert captured_messages["pre"]["count"] > 0
    assert captured_messages["pre"]["has_user"] is True
    assert captured_messages["post"]["count"] > 0


@pytest.mark.asyncio
async def test_async_route_mode_hooks_receive_messages():
    """Test that member tool hooks receive messages in async route mode."""
    captured_messages.clear()
    member = Agent(
        name="Weather Agent",
        role="Get weather information",
        model=OpenAIChat(id=MODEL),
        tools=[get_weather],
        instructions=["Use the get_weather tool to answer."],
    )
    team = Team(
        name="Test Team",
        model=OpenAIChat(id=MODEL),
        members=[member],
        mode="route",
        instructions=["Delegate weather questions to Weather Agent."],
    )

    response = await team.arun("What is the weather in Bangkok?")

    assert response.content is not None
    assert captured_messages["pre"]["count"] > 0
    assert captured_messages["pre"]["has_user"] is True
