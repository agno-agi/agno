import json
from datetime import datetime, timedelta
from typing import List, Optional

from agno.agent.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools import tool
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel, Field

# =============================================================================
# PYDANTIC MODELS FOR STRUCTURED DATA
# =============================================================================


class DataPoint(BaseModel):
    """A single data point for chart generation.

    Note: Using numeric string aliases ("1", "2", etc.) for flexibility
    in chart libraries that may have different label requirements.
    """

    ts: str = Field(
        ...,
        description="The x axis value representing the timestamp of the data point.",
    )
    v1: float = Field(..., alias="1", description="The y value of the data point.")
    v2: Optional[float] = Field(
        None,
        alias="2",
        description="The secondary y value of the data point. (OPTIONAL)",
    )
    v3: Optional[float] = Field(
        None,
        alias="3",
        description="The tertiary y value of the data point. (OPTIONAL)",
    )

    model_config = {
        "populate_by_name": True,
        "validate_by_name": True,
    }


class ChartData(BaseModel):
    """Chart configuration and data."""

    title: str = Field(..., description="The title of the chart.")
    labels: List[str] = Field(..., description="The labels for the chart data.")
    suffix: str = Field(..., description="The suffix appended to displayed values.")
    data: List[DataPoint] = Field(
        ..., description="The data points used to generate the chart."
    )


# =============================================================================
# EXTERNAL EXECUTION TOOL (FRONTEND RENDERING)
# =============================================================================


@tool(external_execution=True)
def generate_chart(
    title: str,
    labels: list[str],
    suffix: str,
    data: list[DataPoint],
) -> ChartData:
    """
    Generate charts or plots for the user by automatically retrieving raw data
    from available *_raw_data tools.

    IMPORTANT: This tool has external_execution=True, meaning:
    - The actual chart rendering happens on the FRONTEND
    - The backend sends tool call parameters to the frontend
    - The frontend renders the chart and sends back a result
    - This was the source of Issue #5116 (duplicate tool_call_id)

    This tool should:
    - Select the appropriate *_raw_data tool to fetch the underlying dataset
    - Extract KPI data exclusively from properties prefixed with "h_"
    - Use the extracted KPI data to generate the requested chart
    - The frontend will handle the actual rendering

    Args:
        title: The title of the chart
        labels: Labels for the chart data series
        suffix: Suffix to append to values (e.g., "kWh", "units")
        data: The data points to visualize

    Returns:
        ChartData: Structured chart configuration
    """
    pass  # Actual implementation is on the frontend


# =============================================================================
# BACKEND TOOLS (SERVER-SIDE EXECUTION)
# =============================================================================


@tool
def get_date_ranges() -> str:
    """Get common date ranges for today, yesterday, current week, etc.

    This is a standard backend tool that provides date range calculations.
    Useful for time-series data queries.

    Returns:
        JSON string with date ranges
    """
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    return json.dumps(
        {
            "oggi": {
                "from": today_start.isoformat() + "Z",
                "to": now.isoformat() + "Z",
            },
            "ieri": {
                "from": (today_start - timedelta(days=1)).isoformat() + "Z",
                "to": (today_start - timedelta(seconds=1)).isoformat() + "Z",
            },
            "settimana_corrente": {
                "from": today_start.isoformat() + "Z",
                "to": now.isoformat() + "Z",
            },
            "mese_corrente": {
                "from": today_start.replace(day=1).isoformat() + "Z",
                "to": now.isoformat() + "Z",
            },
        }
    )


@tool
def get_consumption_raw_data(start: str, end: str) -> str:
    """Get raw consumption data for the specified time period.

    This backend tool simulates fetching time-series consumption data.
    In production, this would query a database or API.

    Args:
        start: Start timestamp in ISO format
        end: End timestamp in ISO format

    Returns:
        JSON string with consumption data including h_* properties for charts
    """
    # Generate mock hourly data
    data_points = []
    base_time = datetime.fromisoformat(start.replace("Z", ""))

    for i in range(10):
        timestamp = (base_time + timedelta(hours=i)).isoformat() + "Z"
        data_points.append(
            {
                "ts": timestamp,
                "production_machine": round(0.27 + (i * 0.05), 2),
                "service_machine": 0,
            }
        )

    return json.dumps(
        {
            "consumption": 14.37,
            "h_consumption": data_points,  # Properties prefixed with "h_" are for charts
            "h_power": [
                {"ts": dp["ts"], "power_avg": dp["production_machine"] * 3.5}
                for dp in data_points
            ],
        }
    )


# =============================================================================
# AGENT CONFIGURATION
# =============================================================================

agent = Agent(
    name="ChartGenerator",
    # model=OpenAIChat(id="gpt-4o"),
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[
        DuckDuckGoTools(),
        generate_chart,
    ],
    description=(
        "You are a data visualization assistant that helps users create charts "
        "from consumption data."
    ),
    instructions=(
        "When a user asks for a chart:\n"
        "1. Use get_date_ranges to understand time periods\n"
        "2. Use get_consumption_raw_data to fetch the data\n"
        "3. Use generate_chart to create the visualization\n"
        "4. Always extract data from properties prefixed with 'h_' for charts\n"
        "\n"
        "Be concise and focus on generating accurate charts.\n"
        "You can use DuckDuckGo to search for information.\n"
    ),
    markdown=True,
)


# =============================================================================
# AGENTOS SETUP
# =============================================================================

agent_os = AgentOS(agents=[agent], interfaces=[AGUI(agent=agent)])

app = agent_os.get_app()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    """Run the AgentOS with AGUI interface.
    
    USAGE:
        python cookbook/agent_os/interfaces/agui/external_execution_tools.py
        
    ENDPOINTS:
        - AGUI: http://localhost:9001/agui
        - Config: http://localhost:9001/config
        
    TESTING WITH DOJO:
        1. Start this server: python cookbook/agent_os/interfaces/agui/external_execution_tools.py
        2. Start dojo: cd ag-ui/apps/dojo && pnpm dev
        3. Configure dojo to connect to http://localhost:9001/agui
        4. Ask: "Generate an hourly consumption chart for today"
        
    ISSUE #5116 REPRODUCTION:
        Before the fix (in convert_agui_messages_to_agno_messages), if the frontend
        sent duplicate tool result messages for generate_chart, you would see:
        
        ERROR: Invalid parameter: Duplicate value for 'tool_call_id' of 'call_xxx'
        
        After the fix, duplicate tool results are automatically filtered out.
    
    """
    print("=" * 80)
    print("External Execution Tools Example - Issue #5116 Reproduction")
    print("=" * 80)
    print("\nStarting AgentOS with AGUI interface...")
    print("\nEndpoints:")
    print("  - AGUI: http://localhost:9001/agui")
    print("  - Config: http://localhost:9001/config")
    print("\nTesting:")
    print("  Ask: 'Generate an hourly consumption chart for today'")
    print("\nThe agent will:")
    print("  1. Call get_date_ranges (backend)")
    print("  2. Call get_consumption_raw_data (backend)")
    print("  3. Call generate_chart (frontend - external_execution=True)")
    print("\nWith the fix, no duplicate tool_call_id errors should occur.")
    print("=" * 80)
    print()

    agent_os.serve(app="external_execution_tools:app", reload=True, port=9001)
