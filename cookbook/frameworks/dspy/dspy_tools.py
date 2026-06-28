"""
DSPy ReAct agent with tools, wrapped in Agno's DSPyAgent.

DSPy's ReAct module supports tool use via plain Python functions.
The agent will reason, call tools, observe results, and produce a final answer.

Requirements:
    pip install dspy

Usage:
    .venvs/demo/bin/python cookbook/frameworks/dspy/dspy_tools.py
"""

import dspy
from agno.agents.dspy import DSPyAgent


# ----- Define tools as plain Python functions -----
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    weather_data = {
        "new york": "72F, partly cloudy",
        "london": "58F, rainy",
        "tokyo": "80F, sunny",
        "paris": "65F, overcast",
    }
    return weather_data.get(city.lower(), f"Weather data not available for {city}")


def search_web(query: str) -> str:
    """Search the web for information."""
    return f"Search results for '{query}': This is a mock search result with relevant information."


# ----- Configure DSPy (must be set on the main thread) -----
lm = dspy.LM("openai/gpt-5.4")
dspy.configure(lm=lm)

# ----- ReAct agent with tools -----
react_program = dspy.ReAct(
    signature="question -> answer",
    tools=[get_weather, search_web],
    max_iters=5,
)

agent = DSPyAgent(
    name="DSPy ReAct Agent",
    program=react_program,
)

# Run with tools
agent.print_response("What's the weather in Tokyo and London?", stream=True)
