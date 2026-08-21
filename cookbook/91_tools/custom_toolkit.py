"""
Custom Toolkit with Enable Params
=================================

Demonstrates creating a custom toolkit with enable_* style params.

Key points:
- Custom toolkits (not in agno.tools.*) keep their enable_* params as-is
- The backcompat mechanism only applies to built-in agno toolkits
- You can name params however you like in custom toolkits

This pattern is useful when you want to:
- Selectively enable/disable tools based on configuration
- Follow the same convention as built-in toolkits
- Create reusable toolkits with configurable features
"""

from typing import Any, Callable, List

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import Toolkit


class WeatherToolkit(Toolkit):
    """Custom toolkit for weather-related tools with enable params.

    Note: This is a USER-DEFINED toolkit (not in agno.tools.*), so the
    enable_* params work exactly as defined - no automatic remapping.
    """

    def __init__(
        self,
        api_key: str = "demo-key",
        enable_current_weather: bool = True,
        enable_forecast: bool = True,
        enable_alerts: bool = False,
        enable_historical: bool = False,
        **kwargs: Any,
    ):
        """Initialize WeatherToolkit.

        Args:
            api_key: Weather API key.
            enable_current_weather: Enable get_current_weather tool. Defaults to True.
            enable_forecast: Enable get_forecast tool. Defaults to True.
            enable_alerts: Enable get_weather_alerts tool. Defaults to False.
            enable_historical: Enable get_historical_weather tool. Defaults to False.
        """
        self.api_key = api_key

        # Build tools list based on enable flags
        tools: List[Callable] = []
        if enable_current_weather:
            tools.append(self.get_current_weather)
        if enable_forecast:
            tools.append(self.get_forecast)
        if enable_alerts:
            tools.append(self.get_weather_alerts)
        if enable_historical:
            tools.append(self.get_historical_weather)

        super().__init__(name="weather_toolkit", tools=tools, **kwargs)

    def get_current_weather(self, city: str) -> str:
        """Get current weather for a city."""
        return f"Current weather in {city}: 72F, Sunny (demo data)"

    def get_forecast(self, city: str, days: int = 5) -> str:
        """Get weather forecast for a city."""
        return f"{days}-day forecast for {city}: Mostly sunny (demo data)"

    def get_weather_alerts(self, city: str) -> str:
        """Get active weather alerts for a city."""
        return f"No active weather alerts for {city} (demo data)"

    def get_historical_weather(self, city: str, date: str) -> str:
        """Get historical weather for a city on a specific date."""
        return f"Weather in {city} on {date}: 68F, Partly cloudy (demo data)"


if __name__ == "__main__":
    print("=== Custom Toolkit with Enable Params ===")
    print()

    # Example 1: Default config (current + forecast enabled)
    print("1. Default config:")
    toolkit1 = WeatherToolkit()
    tool_names = [t.__name__ for t in toolkit1.tools]
    print(f"   Tools: {tool_names}")
    print()

    # Example 2: Enable alerts
    print("2. With alerts enabled:")
    toolkit2 = WeatherToolkit(enable_alerts=True)
    tool_names = [t.__name__ for t in toolkit2.tools]
    print(f"   Tools: {tool_names}")
    print()

    # Example 3: Only current weather
    print("3. Only current weather:")
    toolkit3 = WeatherToolkit(
        enable_current_weather=True,
        enable_forecast=False,
        enable_alerts=False,
        enable_historical=False,
    )
    tool_names = [t.__name__ for t in toolkit3.tools]
    print(f"   Tools: {tool_names}")
    print()

    # Example 4: Use with an agent
    print("4. Using with an agent:")
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        tools=[WeatherToolkit(enable_alerts=True)],
        markdown=True,
    )
    print(f"   Agent tools: {[t.name for t in agent.tools]}")
    print()

    # Run a quick test
    print("5. Running agent:")
    agent.print_response("What's the weather like in San Francisco?")
