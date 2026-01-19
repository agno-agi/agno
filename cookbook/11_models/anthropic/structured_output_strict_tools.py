"""Example demonstrating strict tool use with Anthropic structured outputs.

Strict tool use ensures that tool parameters strictly follow the input_schema.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools import Function
from pydantic import BaseModel


class WeatherInfo(BaseModel):
    """Structured output schema for weather information."""

    location: str
    temperature: float
    unit: str
    condition: str


def get_weather(location: str, unit: str = "celsius") -> str:
    temp = 72 if unit == "fahrenheit" else 22
    return f"Weather in {location}: {temp}°{unit}, Sunny"


# Create function with strict mode enabled
weather_tool = Function(
    name="get_weather",
    description="Get current weather information for a location",
    parameters={
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "The city and state, e.g. San Francisco, CA",
            },
            "unit": {
                "type": "string",
                "enum": ["celsius", "fahrenheit"],
                "description": "Temperature unit",
            },
        },
        "required": ["location"],
        "additionalProperties": False,
    },
    strict=True,  # Enable strict mode for validated tool parameters
    entrypoint=get_weather,
)

# Agent with both structured outputs and strict tool
agent = Agent(
    model=Claude(id="claude-sonnet-4-5-20250929"),
    tools=[weather_tool],
    output_schema=WeatherInfo,
    description="You help users get weather information.",
)

# The agent will use strict tool validation and return structured output
agent.print_response("What's the weather like in San Francisco?")
