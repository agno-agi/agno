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

# Example 1: Enable all OpenWeather functions
agent_all = Agent(
    tools=[
        OpenWeatherTools(
            all=True,  # Enable all OpenWeather functions
            units="imperial",  # Options: 'standard', 'metric', 'imperial'
        )
    ],
    markdown=True,
)

# Example 2: Enable specific OpenWeather functions only
agent_specific = Agent(
    tools=[
        OpenWeatherTools(
            enable_current_weather=True,
            enable_forecast=True,
            enable_air_pollution=True,
            enable_geocoding=True,
            units="metric",
        )
    ],
    markdown=True,
)

# Example 3: Default behavior with all functions enabled
agent = Agent(
    tools=[
        OpenWeatherTools(
            enable_current_weather=True,
            enable_forecast=True,
            enable_air_pollution=True,
            enable_geocoding=True,
            units="imperial",  # Options: 'standard', 'metric', 'imperial'
        )
    ],
    markdown=True,
)

# Example usage with all functions enabled
print("=== Example 1: Using all OpenWeather functions ===")
agent_all.print_response(
    "Give me a comprehensive weather report for Tokyo including current weather, forecast, and air quality",
    markdown=True,
)

# Example usage with specific functions only
print(
    "\n=== Example 2: Using specific OpenWeather functions (current weather + geocoding) ==="
)
agent_specific.print_response(
    "What's the current weather in Tokyo?",
    markdown=True,
)

# Example usage with default configuration
print("\n=== Example 3: Default OpenWeather agent usage ===")
agent.print_response(
    "What's the current weather in Tokyo?",
    markdown=True,
)

# Additional examples (commented out to avoid API calls)
# agent.print_response(
#     "Give me a 3-day weather forecast for New York City",
#     markdown=True,
# )

# agent.print_response(
#     "What's the air quality in Beijing right now?",
#     markdown=True,
# )

# agent.print_response(
#     "Compare the current weather between London, Paris, and Rome",
#     markdown=True,
# )
