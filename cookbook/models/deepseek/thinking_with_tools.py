"""
DeepSeek Thinking Mode with Tool Calls

This example demonstrates DeepSeek's thinking mode which supports tool calls.
When enabled, the model can engage in multiple turns of reasoning and tool calls
before providing the final answer, improving response quality for complex tasks.

Run: pip install agno
Set: export DEEPSEEK_API_KEY=your_api_key

For more information: https://api-docs.deepseek.com/guides/thinking_with_tools
"""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.tools import tool


@tool
def get_current_date() -> str:
    """Get the current date in YYYY-MM-DD format."""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d")


@tool
def get_weather(location: str, date: str) -> str:
    """Get weather for a location on a specific date.

    Args:
        location: The city name
        date: The date in format YYYY-MM-DD
    """
    # In production, integrate with a real weather API
    return f"Weather in {location} on {date}: Cloudy, 7-13°C"


@tool
def calculate(expression: str) -> str:
    """Calculate a mathematical expression.

    Args:
        expression: A mathematical expression to evaluate (e.g., "2 + 2", "(7 + 13) / 2")
    """
    try:
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {e}"


# Create agent with DeepSeek thinking mode enabled
agent = Agent(
    model=DeepSeek(
        id="deepseek-chat",
        # Enable thinking mode for enhanced reasoning with tool calls
        extra_body={"thinking": {"type": "enabled"}},
    ),
    tools=[get_current_date, get_weather, calculate],
    instructions=[
        "You are a helpful assistant with access to date, weather, and calculation tools.",
        "Think through problems step by step before responding.",
        "Use tools to gather information and verify calculations.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    # This question requires multiple tool calls with reasoning:
    # 1. Get current date to determine tomorrow
    # 2. Get weather for the location
    # 3. Calculate the average temperature
    agent.print_response(
        "What's the weather in Hangzhou tomorrow? Also, calculate the average "
        "of the temperature range.",
        stream=True,
    )

