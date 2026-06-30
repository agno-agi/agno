"""
Message History In Tool Hooks
=============================

Access the current run's message history inside tool hooks in a team
via run_context.messages.
"""

from typing import Any, Callable, Dict

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunContext
from agno.team import Team
from agno.tools import FunctionCall, tool

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------


def context_aware_hook(
    run_context: RunContext,
    function_name: str,
    function_call: Callable,
    arguments: Dict[str, Any],
):
    """Log conversation context before executing a member's tool."""
    msgs = run_context.messages
    count = len(msgs) if msgs else 0
    print(f"[hook] {function_name} - {count} messages in run")
    return function_call(**arguments)


def pre_hook(run_context: RunContext, fc: FunctionCall):
    msgs = run_context.messages
    count = len(msgs) if msgs else 0
    print(f"[pre-hook] {fc.function.name} - {count} messages in run")


@tool(pre_hook=pre_hook)
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Sunny, 72F in {city}"


weather_agent = Agent(
    name="Weather Agent",
    role="Get weather information for cities",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_weather],
    tool_hooks=[context_aware_hook],
    instructions=["Use the tools to help the user."],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Travel Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[weather_agent],
    mode="coordinate",
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response("What is the weather in Tokyo?")
