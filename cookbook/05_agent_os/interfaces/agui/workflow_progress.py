"""
AG-UI Workflow Progress Demo
============================
Demonstrates workflow step streaming via STATE_DELTA + STEP_STARTED/STEP_FINISHED events.

The frontend receives:
1. STATE_DELTA events with workflow_progress updates (JSON patch)
2. STEP_STARTED/STEP_FINISHED events for native step tracking
3. RAW events with full workflow event details (metrics, executor info)

Run: .venvs/demo/bin/python cookbook/05_agent_os/interfaces/agui/workflow_progress.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools.yfinance import YFinanceTools
from agno.workflow import Step, Workflow

# ---------------------------------------------------------------------------
# Step 1: Data Gatherer
# ---------------------------------------------------------------------------
data_agent = Agent(
    name="Data Gatherer",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[YFinanceTools(all=True)],
    instructions="""\
You are a data gathering agent. Fetch market data for the requested stock:
- Current price and daily change
- Market cap and volume
- Key ratios (P/E, EPS)

Present the raw data clearly. Don't analyze, just gather.\
""",
)

data_step = Step(
    name="Data Gathering",
    agent=data_agent,
    description="Fetch market data for the stock",
)

# ---------------------------------------------------------------------------
# Step 2: Analyst
# ---------------------------------------------------------------------------
analyst_agent = Agent(
    name="Analyst",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="""\
You are a financial analyst. Interpret the market data:
- Is the P/E high or low for this sector?
- Identify strengths and weaknesses
- Note any red flags or positive signals

Be objective and data-driven.\
""",
)

analysis_step = Step(
    name="Analysis",
    agent=analyst_agent,
    description="Analyze market data and identify insights",
)

# ---------------------------------------------------------------------------
# Step 3: Report Writer
# ---------------------------------------------------------------------------
report_agent = Agent(
    name="Report Writer",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="""\
You are a report writer. Create a concise investment brief:
- One-line summary
- Recommendation (Buy/Hold/Sell) with rationale
- Max 150 words
- End with key metrics table

Write for a busy investor.\
""",
    markdown=True,
)

report_step = Step(
    name="Report Writing",
    agent=report_agent,
    description="Produce investment brief",
)

# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
stock_research_workflow = Workflow(
    name="Stock Research",
    description="Three-step research pipeline: Data -> Analysis -> Report",
    steps=[data_step, analysis_step, report_step],
)

# ---------------------------------------------------------------------------
# AgentOS with AGUI interface
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    workflows=[stock_research_workflow],
    interfaces=[
        AGUI(workflow=stock_research_workflow, prefix="/workflow"),
    ],
)

app = agent_os.get_app()

if __name__ == "__main__":
    print("Workflow Progress Demo")
    print("Endpoint: POST /workflow/agui")
    agent_os.serve(app="workflow_progress:app", reload=True, port=8765)
