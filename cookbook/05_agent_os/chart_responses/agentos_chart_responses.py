"""
AgentOS Chart Responses
=======================

Demonstrates an AgentOS agent that returns chart specs Agno OS can render inline.
"""

from enum import Enum
from textwrap import dedent
from typing import Dict, List, Union

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.config import AgentOSConfig, ChatConfig
from typing_extensions import NotRequired, TypedDict

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/agentos_chart_responses.db")

ChartDataValue = Union[str, int, float]
ChartDataRow = Dict[str, ChartDataValue]


class ChartType(str, Enum):
    """Supported Agno OS inline chart renderers."""

    BAR = "bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    BAR_HORIZONTAL = "bar-horizontal"
    BAR_STACKED = "bar-stacked"
    AREA_STACKED = "area-stacked"


class ChartSeriesConfig(TypedDict):
    """Display metadata for a chart series."""

    # Human-readable label shown in legends and tooltips.
    label: str


class ChartSpec(TypedDict):
    """Chart payload shape for a future SDK chart tool."""

    # Selects the frontend renderer, for example line, bar, area, or pie.
    type: ChartType

    # Flat chart rows. Labels/dates should be strings; measured values should be numbers.
    data: List[ChartDataRow]

    # Series metadata keyed by data field, for example {"revenue": {"label": "Revenue"}}.
    config: Dict[str, ChartSeriesConfig]

    # Optional chart heading shown above the visualization.
    title: NotRequired[str]

    # Optional supporting copy shown with the chart.
    description: NotRequired[str]

    # Cartesian chart category/date key, for example "month" or "date".
    xKey: NotRequired[str]

    # Explicit cartesian series order. If absent, frontend can infer from config keys.
    yKeys: NotRequired[List[str]]

    # Pie chart label key, for example "provider" or "model".
    nameKey: NotRequired[str]

    # Pie chart numeric value key, for example "runs" or "tokens".
    valueKey: NotRequired[str]


class ChartMessagePayload(TypedDict):
    """Future structured payload for SDK tools that emit one or more charts."""

    # One or more chart specs emitted by a future SDK chart tool.
    charts: List[ChartSpec]


CHART_RESPONSE_INSTRUCTIONS = dedent("""\
    You are a data analyst for Agno OS. When a user asks for trends, comparisons,
    usage, costs, performance, conversion, revenue, tokens, runs, or any other
    answer that benefits from a visualization, include a chart block in your
    markdown response.

    Agno OS renders charts from fenced code blocks with the `chart` language.
    The block must contain valid JSON only. Do not add comments, trailing commas,
    markdown, prose, or code inside the JSON block.

    Supported chart schema:

    ```chart
    {
      "type": "bar",
      "title": "Monthly Revenue",
      "description": "Revenue and expenses by month",
      "data": [
        { "month": "Jan", "revenue": 4000, "expenses": 2400 },
        { "month": "Feb", "revenue": 3000, "expenses": 1398 }
      ],
      "config": {
        "revenue": { "label": "Revenue ($)" },
        "expenses": { "label": "Expenses ($)" }
      },
      "xKey": "month",
      "yKeys": ["revenue", "expenses"]
    }
    ```

    Required fields:
    - `type`: one of `bar`, `line`, `area`, `pie`, `bar-horizontal`,
      `bar-stacked`, or `area-stacked`.
    - `data`: an array of flat objects. Use strings for labels and dates, and
      numbers for values. Never stringify numeric values.
    - `config`: an object keyed by each series key. Each key maps to a label and
      optional color.

    Cartesian chart rules:
    - Include `xKey` for the category or date field.
    - Include `yKeys` when there are multiple series. If omitted, Agno OS uses
      the keys from `config`.
    - Keep the data compact enough to inspect in chat. Aggregate or sample if
      the raw dataset is large.

    Pie chart rules:
    - Include `nameKey` for slice labels.
    - Include `valueKey` for numeric slice values.
    - Include matching `config` for `valueKey`.

    Color rules:
    - Omit colors unless the user asks for specific colors. Agno OS assigns
      theme-aware chart colors automatically.

    Response style:
    - Add one short sentence before the chart describing what it shows.
    - Add one short sentence after the chart with the key takeaway.
    - Do not return tables that duplicate the same data unless the user asks.
""")

chart_response_agent = Agent(
    id="chart-response-agent",
    name="Chart Response Agent",
    model=OpenAIChat(id="gpt-5.2"),
    db=db,
    instructions=CHART_RESPONSE_INSTRUCTIONS,
    markdown=True,
)

agent_os = AgentOS(
    id="chart-responses-demo",
    description="AgentOS cookbook for sending chart-ready markdown responses to Agno OS.",
    agents=[chart_response_agent],
    config=AgentOSConfig(
        chat=ChatConfig(
            quick_prompts={
                "chart-response-agent": [
                    "Show a line chart of agent runs for the last 7 days.",
                    "Compare input and output token usage by day.",
                    "Create a pie chart of model runs by provider.",
                ],
            },
        ),
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="agentos_chart_responses:app", port=7777, reload=True)
