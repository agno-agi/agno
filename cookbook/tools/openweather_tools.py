"""
OpenWeatherMap API Integration Example

This example demonstrates how to use the OpenWeatherTools to get weather data
from the OpenWeatherMap API.

Prerequisites:
1. Get an API key from https://openweathermap.org/api
2. Set the OPENWEATHER_API_KEY environment variable or pass it directly to the tool

Usage:
- Get current weather for a location
- Get weather forecast for a location
- Get air pollution data for a location
- Geocode a location name to coordinates
"""

from agno.agent import Agent
from agno.tools.openweather import OpenWeatherTools

# Create an agent with OpenWeatherTools
agent = Agent(
    tools=[
        OpenWeatherTools(
            units="imperial",  # Options: 'standard', 'metric', 'imperial'
        )
    ],
    # show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

# Example 1: Get current weather for a location
agent.print_response(
    "What's the current weather in Tokyo?",
    markdown=True,
)

# # Example 2: Get weather forecast for a location
# agent.print_response(
#     "Give me a 3-day weather forecast for New York City",
#     markdown=True,
# )

# # Example 3: Get air pollution data for a location
# agent.print_response(
#     "What's the air quality in Beijing right now?",
#     markdown=True,
# )

# # Example 4: Compare weather between multiple cities
# agent.print_response(
#     "Compare the current weather between London, Paris, and Rome",
#     markdown=True,
# )
