"""
Sequential Workflow - Stock Research Pipeline
==============================================
This example shows how to create a workflow with sequential steps.
Each step is handled by a specialized agent, and outputs flow to the next step.

Different from Teams (agents collaborate dynamically), Workflows give you
explicit control over execution order and data flow.

Key concepts:
- Workflow: Orchestrates a sequence of steps
- Step: Wraps an agent with a specific task
- Steps execute in order, each building on the previous

Example prompts to try:
- "Analyze NVDA"
- "Research Tesla for investment"
- "Give me a report on Apple"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools
from agno.workflow import Step, Workflow

# ============================================================================
# Storage Configuration
# ============================================================================
workflow_db = SqliteDb(db_file="tmp/agents.db")

# ============================================================================
# Step 1: Data Gatherer — Fetches raw market data
# ============================================================================
data_agent = Agent(
    name="Data Gatherer",
    model=Gemini(id="gemini-3-flash-preview"),
    tools=[YFinanceTools()],
    instructions="""\
You are a data gathering agent. Your job is to fetch comprehensive market data.

For the requested stock, gather:
- Current price and daily change
- Market cap and volume
- P/E ratio, EPS, and other key ratios
- 52-week high and low
- Recent price trends

Present the raw data clearly. Don't analyze — just gather and organize.\
""",
    db=workflow_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
)

data_step = Step(
    name="Data Gathering",
    agent=data_agent,
    description="Fetch comprehensive market data for the stock",
)

# ============================================================================
# Step 2: Analyst — Interprets the data
# ============================================================================
analyst_agent = Agent(
    name="Analyst",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="""\
You are a financial analyst. You receive raw market data from the data team.

Your job is to:
- Interpret the key metrics (is the P/E high or low for this sector?)
- Identify strengths and weaknesses
- Note any red flags or positive signals
- Compare to typical industry benchmarks

Provide analysis, not recommendations. Be objective and data-driven.\
""",
    db=workflow_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
)

analysis_step = Step(
    name="Analysis",
    agent=analyst_agent,
    description="Analyze the market data and identify key insights",
)

# ============================================================================
# Step 3: Report Writer — Produces final output
# ============================================================================
report_agent = Agent(
    name="Report Writer",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="""\
You are a report writer. You receive analysis from the research team.

Your job is to:
- Synthesize the analysis into a clear investment brief
- Lead with a one-line summary
- Include a recommendation (Buy/Hold/Sell) with rationale
- Keep it concise — max 200 words
- End with key metrics in a small table

Write for a busy investor who wants the bottom line fast.\
""",
    db=workflow_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

report_step = Step(
    name="Report Writing",
    agent=report_agent,
    description="Produce a concise investment brief",
)

# ============================================================================
# Create the Workflow
# ============================================================================
sequential_workflow = Workflow(
    name="Sequential Workflow",
    description="Three-step research pipeline: Data → Analysis → Report",
    steps=[
        data_step,  # Step 1: Gather data
        analysis_step,  # Step 2: Analyze data
        report_step,  # Step 3: Write report
    ],
)

# ============================================================================
# Run the Workflow
# ============================================================================
if __name__ == "__main__":
    sequential_workflow.print_response(
        "Analyze NVIDIA (NVDA) for investment",
        stream=True,
    )

# ============================================================================
# More Examples
# ============================================================================
"""
Workflow vs Team:

- Workflow: Explicit step order, predictable execution, clear data flow
- Team: Dynamic collaboration, leader decides who does what

Use Workflow when:
- Steps must happen in a specific order
- Each step has a clear, specialized role
- You want predictable, repeatable execution
- Output from step N feeds into step N+1

Use Team when:
- Agents need to collaborate dynamically
- The leader should decide who to involve
- Tasks benefit from back-and-forth discussion

Advanced workflow features (not shown here):
- Parallel: Run steps concurrently
- Condition: Run steps only if criteria met
- Loop: Repeat steps until condition met
- Router: Dynamically select which step to run
"""
