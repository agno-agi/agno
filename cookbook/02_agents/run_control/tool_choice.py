"""
Tool Choice
=============================

Tool Choice Control.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses


def get_weather(city: str) -> str:
    return f"Weather data placeholder for {city}: 72F and clear."


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
no_tools_agent = Agent(
    name="No-Tools Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[get_weather],
    tool_choice="none",
)

auto_tools_agent = Agent(
    name="Auto-Tools Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[get_weather],
    tool_choice="auto",
)

forced_tool_agent = Agent(
    name="Forced-Tool Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[get_weather],
    tool_choice={"type": "function", "name": "get_weather"},
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    prompt = "What is the weather in San Francisco today?"
    no_tools_agent.print_response(prompt, stream=True)
    auto_tools_agent.print_response(prompt, stream=True)
    forced_tool_agent.print_response(prompt, stream=True)
