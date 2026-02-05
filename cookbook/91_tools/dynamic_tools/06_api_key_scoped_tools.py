"""
API Key Scoped Tools
====================
This example demonstrates how to create tools that use different API keys
or credentials based on the user context. This is useful for:

- Multi-tenant apps where each tenant has their own API keys
- Applications that use per-user credentials
- Services that need to isolate API usage and billing

Key concepts:
- run_context.dependencies: Contains API keys and credentials
- Tools created with user-specific credentials
- Each user's API calls are isolated to their account
- callable_cache_key: Cache tools per credential set (avoid stale/leaked credentials)
"""

import hashlib
from typing import Any, Dict, List, Union

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit


# ============================================================================
# Mock External Service Client
# ============================================================================


class MockWeatherClient:
    """A mock weather service client that uses an API key."""

    def __init__(self, api_key: str, tier: str = "free"):
        self.api_key = api_key
        self.tier = tier
        # Mask API key for display
        self.masked_key = (
            api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "****"
        )

    def get_weather(self, city: str) -> str:
        """Get weather for a city (mock implementation)."""
        if self.tier == "free":
            return f"Weather in {city}: Sunny, 72F (using free tier, key: {self.masked_key})"
        else:
            return (
                f"Weather in {city}: Sunny, 72F, Humidity 45%, Wind 5mph NW "
                f"(using premium tier, key: {self.masked_key})"
            )

    def get_forecast(self, city: str, days: int = 7) -> str:
        """Get forecast (premium only)."""
        if self.tier == "free":
            return f"Forecast not available on free tier (key: {self.masked_key})"
        return f"{days}-day forecast for {city}: Sunny -> Cloudy -> Rain (key: {self.masked_key})"


# ============================================================================
# Tools Factory with API Key Configuration
# ============================================================================

def get_api_cache_key(run_context: RunContext) -> str:
    """Cache key that scopes tools to the provided credentials.

    Uses a short hash of the API key to avoid storing raw keys as cache keys.
    """
    dependencies = run_context.dependencies or {}
    api_key = str(dependencies.get("weather_api_key", ""))
    tier = str(dependencies.get("tier", "free"))
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else "_no_key_"
    return f"{tier}:{api_key_hash}"


def get_api_tools(
    run_context: RunContext,
) -> List[Union[Toolkit, Function, Dict[str, Any]]]:
    """Create tools with user-specific API credentials.

    The API key and tier come from dependencies, which would typically
    be set by your authentication middleware.

    Args:
        run_context: Runtime context with dependencies containing API credentials

    Returns:
        List of tools configured with user's API credentials.
    """
    dependencies = run_context.dependencies or {}

    # Get API credentials from dependencies
    api_key = dependencies.get("weather_api_key", "default-free-key")
    tier = dependencies.get("tier", "free")

    print(f"Configuring tools with tier: {tier}")

    # Create client with user's credentials
    weather_client = MockWeatherClient(api_key=api_key, tier=tier)

    # Create tools that use this client
    def get_weather(city: str) -> str:
        """Get current weather for a city.

        Args:
            city: The city name to get weather for

        Returns:
            Current weather conditions
        """
        return weather_client.get_weather(city)

    def get_forecast(city: str, days: int = 7) -> str:
        """Get weather forecast for a city (premium tier only).

        Args:
            city: The city name to get forecast for
            days: Number of days to forecast (default 7)

        Returns:
            Weather forecast or error if not premium tier
        """
        return weather_client.get_forecast(city, days)

    tools = [get_weather]

    # Premium users get additional tools
    if tier == "premium":
        tools.append(get_forecast)
        print("Premium tier: forecast tool enabled")
    else:
        print("Free tier: forecast tool disabled")

    return tools


# ============================================================================
# Create the Agent with Callable Tools
# ============================================================================
agent = Agent(
    name="Weather Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=get_api_tools,
    # Cache tools per credential set so different users/tiers don't share clients.
    callable_cache_key=get_api_cache_key,
    instructions="""\
You are a weather assistant that provides weather information.

Your capabilities depend on the user's subscription tier:
- **Free tier**: Current weather only
- **Premium tier**: Current weather + forecasts

Each user has their own API credentials, so their usage is tracked separately.
""",
    markdown=True,
)


# ============================================================================
# Main: Demonstrate API Key Scoped Tools
# ============================================================================
if __name__ == "__main__":
    # Free tier user
    print("=" * 60)
    print("User: Free Tier")
    print("=" * 60)
    agent.print_response(
        "What's the weather in San Francisco? Also, can you get me a forecast?",
        dependencies={
            "weather_api_key": "free-user-abc123xyz",
            "tier": "free",
        },
        stream=True,
    )

    # Premium tier user
    print("\n" + "=" * 60)
    print("User: Premium Tier")
    print("=" * 60)
    agent.print_response(
        "What's the weather in San Francisco? Also, can you get me a 5-day forecast?",
        dependencies={
            "weather_api_key": "premium-user-xyz789abc",
            "tier": "premium",
        },
        stream=True,
    )

    # Different premium user (different API key)
    print("\n" + "=" * 60)
    print("User: Another Premium User (different API key)")
    print("=" * 60)
    agent.print_response(
        "Get me the weather and forecast for Tokyo",
        dependencies={
            "weather_api_key": "premium-user-different-key",
            "tier": "premium",
        },
        stream=True,
    )
