"""
AWS Bedrock Tool Choice
=======================

Control how the model uses tools with tool_choice:
- "auto": Model decides (default)
- "any": Must use at least one tool
- {"tool": {"name": "X"}}: Must use specific tool

Run with:
    python cookbook/90_models/aws/bedrock/tool_choice.py
"""

from agno.agent import Agent
from agno.models.aws import AwsBedrock

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"The weather in {city} is 72F and sunny."


def get_time(timezone: str) -> str:
    """Get the current time in a timezone."""
    return f"The current time in {timezone} is 2:30 PM."


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Auto mode: model decides whether to use tools
auto_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[get_weather, get_time],
    tool_choice="auto",
)

# Any mode: must use at least one tool
any_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[get_weather, get_time],
    tool_choice="any",
)

# Force specific tool by name
forced_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[get_weather, get_time],
    tool_choice="get_weather",
    tool_call_limit=1,
)


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Auto mode - model decides:")
    auto_agent.print_response("What's 2 + 2?")

    print("\nAny mode - must use a tool:")
    any_agent.print_response("Hello!")

    print("\nForced tool - always calls get_weather:")
    forced_agent.print_response("What time is it?")
