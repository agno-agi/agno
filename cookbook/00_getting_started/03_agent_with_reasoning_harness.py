"""
Agent with Reasoning Harness - Finance Agent that Thinks
=========================================================
Building on the Finance Agent from 02, this example adds a reasoning harness.
The agent now thinks before acting and analyzes results after — useful for complex
analysis where planning and structured thinking matter.

ReasoningTools gives any model explicit tools for thinking:
- think(): A scratchpad to work through problems step-by-step
- analyze(): Validate results and check work before responding

This is different from reasoning models (like o3) which think internally.
ReasoningTools makes reasoning explicit and visible.

Example prompts to try:
- "Should I invest in NVDA or AMD for long-term AI exposure?"
- "Analyze the risk/reward profile of Tesla"
- "What's the bull and bear case for Apple?"
- "Build me a simple 3-stock portfolio for AI exposure"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """\
You are a Finance Agent — a data-driven analyst who retrieves market data,
computes key ratios, and produces concise, decision-ready insights.

## Workflow

1. Think
   - For complex questions, use `think` to plan your approach
   - Break down multi-part questions into steps
   - Consider what data you need before fetching it

2. Retrieve
   - Fetch: price, change %, market cap, P/E, EPS, 52-week range
   - For comparisons, pull the same fields for each ticker

3. Analyze
   - Use `analyze` to validate your findings before responding
   - Compute ratios (P/E, P/S, margins) when not already provided
   - Weigh trade-offs explicitly
   - Facts only, no speculation

4. Present
   - Lead with your conclusion
   - Use tables for multi-stock comparisons
   - Keep it tight

## Rules

- Source: Yahoo Finance. Always note the timestamp.
- Missing data? Say "N/A" and move on.
- No personalized advice — add disclaimer when relevant.
- No emojis.
- For subjective questions, present both sides before your take.
- Reference previous analyses when relevant.\
"""

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(
    db_file="tmp/agents.db",
    session_table="finance_agent_reasoning",
)

# ============================================================================
# Create the Agent
# ============================================================================
agent = Agent(
    name="Finance Agent with Reasoning",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[
        ReasoningTools(add_instructions=True),
        YFinanceTools(),
    ],
    db=agent_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ============================================================================
# Run the Agent
# ============================================================================
if __name__ == "__main__":
    # Turn 1: A complex question that benefits from reasoning
    agent.print_response(
        "Should I invest in NVDA or AMD for long-term AI exposure? Think through this step-by-step.",
        stream=True,
        show_full_reasoning=True,
    )

    # Turn 2: Follow up — the agent remembers the analysis
    agent.print_response(
        "What about adding MSFT to balance the portfolio?",
        stream=True,
        show_full_reasoning=True,
    )

    # Turn 3: Ask for a final recommendation
    agent.print_response(
        "Give me a final allocation between these three.",
        stream=True,
        show_full_reasoning=True,
    )

# ============================================================================
# More Examples
# ============================================================================
"""
Try these prompts that benefit from reasoning:

1. Comparative Analysis
   "Compare Google, Microsoft, and Amazon as AI investments. Which is best positioned?"

2. Risk Assessment
   "What are the biggest risks to Tesla's stock price over the next year?"

3. Portfolio Construction
   "Build me a 3-stock portfolio for AI exposure with a balance of risk and reward"

4. Bull vs Bear
   "Give me the bull and bear case for Apple at its current valuation"

5. Scenario Analysis
   "How would rising interest rates affect growth stocks like NVDA?"

The reasoning harness helps the agent think through complex, multi-faceted
questions before jumping to conclusions.
"""
