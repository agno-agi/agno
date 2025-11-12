"""Example: Team with External Execution Tools + AGUI (Issue #5401 Investigation)

This cookbook demonstrates using a Team with external_execution tools via AGUI interface.
It investigates Issue #5401: Event state machine errors when Teams emit events.

KEY CONCEPTS:
- Team with multiple specialized agents
- Mix of backend and external_execution tools
- AGUI protocol with Team coordination
- Event ordering and state machine compliance

ISSUE #5401:
"Cannot send TEXT_MESSAGE_START after TOOL_CALL_START: Send TOOL_CALL_END first"

This happens when Team agents execute in parallel and events get interleaved improperly.

TESTING:
1. Run this script: python cookbook/agent_os/interfaces/agui/team_external_tools.py
2. Connect dojo frontend
3. Ask: "Generate a weather chart for Mumbai this week"
4. Watch for event ordering issues in logs
"""

import json
from datetime import datetime, timedelta
from typing import List, Optional

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.team.team import Team
from agno.tools import tool
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel, Field

# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class DataPoint(BaseModel):
    """A single data point for chart generation."""

    ts: str = Field(..., description="Timestamp")
    v1: float = Field(..., alias="1", description="Primary value")
    v2: Optional[float] = Field(
        None, alias="2", description="Secondary value (optional)"
    )

    model_config = {
        "populate_by_name": True,
        "validate_by_name": True,
    }


class ChartData(BaseModel):
    """Chart configuration and data."""

    title: str = Field(..., description="Chart title")
    labels: List[str] = Field(..., description="Data labels")
    suffix: str = Field(..., description="Value suffix (e.g., '°C', 'kWh')")
    data: List[DataPoint] = Field(..., description="Data points")


# =============================================================================
# BACKEND TOOLS (SERVER-SIDE EXECUTION)
# =============================================================================


@tool
def get_date_ranges() -> str:
    """Get common date ranges for today, yesterday, current week, etc."""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    return json.dumps(
        {
            "today": {
                "from": today_start.isoformat() + "Z",
                "to": now.isoformat() + "Z",
            },
            "this_week": {
                "from": (
                    today_start - timedelta(days=today_start.weekday())
                ).isoformat()
                + "Z",
                "to": now.isoformat() + "Z",
            },
            "this_month": {
                "from": today_start.replace(day=1).isoformat() + "Z",
                "to": now.isoformat() + "Z",
            },
        }
    )


@tool
def get_weather_data(location: str, start: str, end: str) -> str:
    """Get weather data for a location and time period.

    Args:
        location: City name
        start: Start timestamp
        end: End timestamp
    """
    # Generate mock weather data
    data_points = []
    base_time = datetime.fromisoformat(start.replace("Z", ""))

    for i in range(7):  # 7 days
        timestamp = (base_time + timedelta(days=i)).isoformat() + "Z"
        data_points.append(
            {
                "ts": timestamp,
                "temperature_high": round(25 + (i % 3) * 2, 1),
                "temperature_low": round(18 + (i % 3), 1),
            }
        )

    return json.dumps(
        {
            "location": location,
            "data": data_points,
            "h_temperature": data_points,  # For chart generation
        }
    )


# =============================================================================
# EXTERNAL EXECUTION TOOL (FRONTEND RENDERING)
# =============================================================================


@tool(external_execution=True)
def generate_weather_chart(
    title: str,
    labels: list[str],
    suffix: str,
    data: list[DataPoint],
) -> ChartData:
    """Generate a weather chart on the frontend.

    IMPORTANT: external_execution=True means this renders on the FRONTEND.

    Args:
        title: Chart title
        labels: Data series labels
        suffix: Unit suffix
        data: Weather data points

    Returns:
        ChartData: Chart configuration
    """
    pass  # Actual rendering happens on frontend


# =============================================================================
# TEAM AGENTS
# =============================================================================

# Data Fetcher Agent - Gets weather data using backend tools
data_agent = Agent(
    name="DataFetcher",
    role="Data Retrieval Specialist",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(),  # For real-time weather lookups
        get_date_ranges,
        get_weather_data,
    ],
    instructions=(
        "You are a data retrieval specialist. Your job is to:\n"
        "1. Search for current weather information using DuckDuckGo\n"
        "2. Get appropriate date ranges\n"
        "3. Fetch structured weather data\n"
        "4. Pass the data to the Visualizer for chart generation\n"
        "\n"
        "Be concise and focus on gathering accurate data."
    ),
    markdown=True,
)

# Visualizer Agent - Creates charts using external execution tool
visualizer_agent = Agent(
    name="Visualizer",
    role="Data Visualization Specialist",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        generate_weather_chart,  # External execution tool
    ],
    instructions=(
        "You are a data visualization specialist. Your job is to:\n"
        "1. Receive weather data from the DataFetcher\n"
        "2. Create clear, informative charts\n"
        "3. Use generate_weather_chart to render on the frontend\n"
        "\n"
        "Always extract data from 'h_temperature' properties for charts."
    ),
    markdown=True,
)


# =============================================================================
# TEAM CONFIGURATION
# =============================================================================

weather_team = Team(
    name="WeatherTeam",
    members=[data_agent, visualizer_agent],  # Team uses 'members' not 'agents'
    model=OpenAIChat(id="gpt-4o"),
    instructions=(
        "You are a weather analysis team. When the user asks for weather information:\n"
        "1. DataFetcher: Search for current weather and fetch historical data\n"
        "2. Visualizer: Create charts to display the weather trends\n"
        "\n"
        "Work together to provide comprehensive weather visualizations."
    ),
    debug_mode=True,
)


# =============================================================================
# AGENTOS SETUP
# =============================================================================

agent_os = AgentOS(teams=[weather_team], interfaces=[AGUI(team=weather_team)])

app = agent_os.get_app()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    """Run the Team with AGUI interface.
    
    USAGE:
        python cookbook/agent_os/interfaces/agui/team_external_tools.py
        
    ENDPOINTS:
        - AGUI: http://localhost:9002/agui
        - Config: http://localhost:9002/config
        
    TESTING:
        Ask: "Generate a weather chart for Mumbai this week"
        
        Watch the logs for:
        - Event ordering (TEXT_MESSAGE_START vs TOOL_CALL_START)
        - Team member coordination
        - Any state machine violations
        
    ISSUE #5401 INVESTIGATION:
        If the error occurs, logs will show which events are emitted in what order,
        helping us identify if Agno's Team event emission violates AG-UI protocol.
    """
    print("=" * 80)
    print("Team with External Execution Tools - Issue #5401 Investigation")
    print("=" * 80)
    print("\nStarting Team with AGUI interface...")
    print("\nEndpoints:")
    print("  - AGUI: http://localhost:9002/agui")
    print("  - Config: http://localhost:9002/config")
    print("\nTest Query:")
    print("  'Generate a weather chart for Mumbai this week'")
    print("\nWhat to Watch:")
    print("  - Event sequence in logs")
    print("  - TEXT_MESSAGE_START during TOOL_CALL_START")
    print("  - Any state machine errors")
    print("=" * 80)
    print()

    agent_os.serve(
        app="team_external_tools:app",
        reload=True,
        port=9001,  # Different port from single agent example
    )
