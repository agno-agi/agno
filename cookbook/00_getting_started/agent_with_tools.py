"""
Agent with Tools - Finance Agent
=================================
Your first Agno agent: a data-driven financial analyst that retrieves
market data, computes key metrics, and delivers concise insights.

This example shows how to give an agent tools to interact with external
data sources. The agent uses YFinanceTools to fetch real-time market data.

Example prompts to try:
- "What's the current price of AAPL?"
- "Compare NVDA and AMD — which looks stronger?"
- "Give me a quick investment brief on Microsoft"
- "What's Tesla's P/E ratio and how does it compare to the industry?"
- "Show me the key metrics for the FAANG stocks"
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools

# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """\
You are a Finance Agent — a data-driven analyst who retrieves market data,
computes key ratios, and produces concise, decision-ready insights.

## Workflow

1. Clarify
   - Identify tickers from company names (e.g., Apple → AAPL)
   - If ambiguous, ask

2. Retrieve
   - Fetch: price, change %, market cap, P/E, EPS, 52-week range
   - For comparisons, pull the same fields for each ticker

3. Analyze
   - Compute ratios (P/E, P/S, margins) when not already provided
   - Key drivers and risks — 2-3 bullets max
   - Facts only, no speculation

4. Present
   - Lead with a one-line summary
   - Use tables for multi-stock comparisons
   - Keep it tight

## Rules

- Source: Yahoo Finance. Always note the timestamp.
- Missing data? Say "N/A" and move on.
- No personalized advice — add disclaimer when relevant.
- No emojis.\
"""

# ============================================================================
# Create the Agent
# ============================================================================
agent_with_tools = Agent(
    name="Agent with Tools",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[YFinanceTools()],
    add_datetime_to_context=True,
    markdown=True,
)

# ============================================================================
# Run the Agent
# ============================================================================
if __name__ == "__main__":
    agent_with_tools.print_response(
        "Give me a quick investment brief on NVIDIA", stream=True
    )

# ============================================================================
# More Examples
# ============================================================================
"""
Try these prompts:

1. Single Stock Analysis
   "What's Apple's current valuation? Is it expensive?"

2. Comparison
   "Compare Google and Microsoft as investments"

3. Sector Overview
   "Show me key metrics for the top AI stocks: NVDA, AMD, GOOGL, MSFT"

4. Quick Check
   "What's Tesla trading at today?"

5. Deep Dive
   "Break down Amazon's financials — revenue, margins, and growth"
"""
