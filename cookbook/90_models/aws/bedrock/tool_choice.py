"""
AWS Bedrock Tool Choice
=======================

Demonstrates all tool_choice options with AWS Bedrock models.

tool_choice controls how the model uses tools:
- "auto" (default): Model decides whether to call tools
- "any": Model MUST call at least one tool
- {"tool": {"name": "X"}}: Model MUST call the specific tool

Supported input formats:
- String: "auto", "any", "none", or bare tool name
- Bedrock native: {"auto": {}}, {"any": {}}, {"tool": {"name": "X"}}
- Anthropic format: {"type": "auto"}, {"type": "any"}, {"type": "tool", "name": "X"}
- OpenAI format: {"type": "function", "name": "X"} or {"type": "function", "function": {"name": "X"}}

Note: "none" is not supported by Bedrock - it will be ignored with a warning.
Forcing a specific tool is only supported by Claude 3+ and Amazon Nova models.
"""

from agno.agent import Agent
from agno.models.aws import AwsBedrock

# ---------------------------------------------------------------------------
# Define tools
# ---------------------------------------------------------------------------


def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"The weather in {city} is 72F and sunny."


def get_time(timezone: str) -> str:
    """Get the current time in a timezone."""
    return f"The current time in {timezone} is 2:30 PM."


def search_web(query: str) -> str:
    """Search the web for information."""
    return f"Search results for '{query}': Found 10 relevant articles."


# ---------------------------------------------------------------------------
# Example 1: Auto mode (default) - Model decides whether to use tools
# ---------------------------------------------------------------------------

auto_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[get_weather, get_time],
    tool_choice="auto",  # This is the default
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 2: Any mode - Model MUST use at least one tool
# ---------------------------------------------------------------------------

any_tool_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[get_weather, get_time, search_web],
    tool_choice="any",  # Forces tool use, model picks which
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 3: Specific tool - Force a particular tool (string format)
# ---------------------------------------------------------------------------

forced_weather_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[get_weather, get_time],
    tool_choice="get_weather",  # Bare tool name
    tool_call_limit=1,  # Prevent infinite loops
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 4: Specific tool - Bedrock native format
# ---------------------------------------------------------------------------

bedrock_format_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[get_weather, get_time],
    tool_choice={"tool": {"name": "get_weather"}},  # Bedrock native
    tool_call_limit=1,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 5: Specific tool - Anthropic format
# ---------------------------------------------------------------------------

anthropic_format_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[get_weather, get_time],
    tool_choice={"type": "tool", "name": "get_weather"},  # Anthropic format
    tool_call_limit=1,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 6: Specific tool - OpenAI format
# ---------------------------------------------------------------------------

openai_format_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[get_weather, get_time],
    tool_choice={"type": "function", "name": "get_weather"},  # OpenAI format
    tool_call_limit=1,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run examples
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Example 1: Auto mode - Model decides")
    print("=" * 60)
    auto_agent.print_response("What's 2 + 2?")  # Likely no tool call
    print()
    auto_agent.print_response("What's the weather in Tokyo?")  # Will use tool
    print()

    print("=" * 60)
    print("Example 2: Any mode - Must use a tool")
    print("=" * 60)
    any_tool_agent.print_response("Hello!")  # Forces tool even for greeting
    print()

    print("=" * 60)
    print("Example 3: Force specific tool (string format)")
    print("=" * 60)
    forced_weather_agent.print_response("What time is it?")  # Still calls get_weather
    print()

    print("=" * 60)
    print("Example 4: Force specific tool (Bedrock native format)")
    print("=" * 60)
    bedrock_format_agent.print_response(
        "Tell me about Python"
    )  # Still calls get_weather
    print()

    print("=" * 60)
    print("Example 5: Force specific tool (Anthropic format)")
    print("=" * 60)
    anthropic_format_agent.print_response("What's the capital of France?")
    print()

    print("=" * 60)
    print("Example 6: Force specific tool (OpenAI format)")
    print("=" * 60)
    openai_format_agent.print_response("How are you?")
