"""
AgentOS Chart Responses
=======================

Demonstrates an AgentOS agent that renders inline charts using the ChartTools toolkit.

The toolkit owns the chart schema, validation, and formatting: the agent calls the
`create_chart` tool with structured data, and the tool returns a fenced ```chart block
that Agno OS renders inline. No chart-schema prompt engineering is needed — the
toolkit ships its own usage instructions.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AgentOSConfig, ChatConfig
from agno.tools.chart import ChartTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/agentos_chart_responses.db")

chart_response_agent = Agent(
    id="chart-response-agent",
    name="Chart Response Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[ChartTools()],
    instructions="You are a data analyst for Agno OS.",
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
