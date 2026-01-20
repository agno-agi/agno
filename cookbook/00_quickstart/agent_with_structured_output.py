"""
Agent with Structured Output - Finance Agent with Typed Responses
==================================================================
This example shows how to get structured, typed responses from your agent.
Instead of free-form text, you get a Pydantic model you can trust.

Perfect for building pipelines, UIs, or integrations where you need
predictable data shapes. Parse it, store it, display it — no regex required.

Key concepts:
- output_schema: A Pydantic model defining the response structure
- The agent's response will always match this schema
- Access structured data via response.content

Example prompts to try:
- "Analyze NVDA"
- "Give me a report on Tesla"
- "What's the investment case for Apple?"
"""

from typing import List, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools
from pydantic import BaseModel, Field

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/agents.db")


# ============================================================================
# Structured Output Schema
# ============================================================================
class StockAnalysis(BaseModel):
    """Structured output for stock analysis."""

    ticker: str = Field(..., description="Stock ticker symbol (e.g., NVDA)")
    company_name: str = Field(..., description="Full company name")
    current_price: float = Field(..., description="Current stock price in USD")
    market_cap: str = Field(..., description="Market cap (e.g., '3.2T' or '150B')")
    pe_ratio: Optional[float] = Field(None, description="P/E ratio, if available")
    week_52_high: float = Field(..., description="52-week high price")
    week_52_low: float = Field(..., description="52-week low price")
    summary: str = Field(..., description="One-line summary of the stock")
    key_drivers: List[str] = Field(..., description="2-3 key growth drivers")
    key_risks: List[str] = Field(..., description="2-3 key risks")
    recommendation: str = Field(
        ..., description="One of: Strong Buy, Buy, Hold, Sell, Strong Sell"
    )


# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """\
You are a Finance Agent — a data-driven analyst who retrieves market data,
computes key ratios, and produces concise, decision-ready insights.

## Workflow

1. Retrieve
   - Fetch: price, change %, market cap, P/E, EPS, 52-week range
   - Get all required fields for the analysis

2. Analyze
   - Identify 2-3 key drivers (what's working)
   - Identify 2-3 key risks (what could go wrong)
   - Facts only, no speculation

3. Recommend
   - Based on the data, provide a clear recommendation
   - Be decisive but note this is not personalized advice

## Rules

- Source: Yahoo Finance
- Missing data? Use null for optional fields, estimate for required
- Recommendation must be one of: Strong Buy, Buy, Hold, Sell, Strong Sell\
"""

# ============================================================================
# Create the Agent
# ============================================================================
agent_with_structured_output = Agent(
    name="Agent with Structured Output",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[YFinanceTools()],
    output_schema=StockAnalysis,
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
    # Get structured output
    response = agent_with_structured_output.run("Analyze NVIDIA")

    # Access the typed data
    analysis: StockAnalysis = response.content

    # Use it programmatically
    print(f"\n{'=' * 60}")
    print(f"Stock Analysis: {analysis.company_name} ({analysis.ticker})")
    print(f"{'=' * 60}")
    print(f"Price: ${analysis.current_price:.2f}")
    print(f"Market Cap: {analysis.market_cap}")
    print(f"P/E Ratio: {analysis.pe_ratio or 'N/A'}")
    print(f"52-Week Range: ${analysis.week_52_low:.2f} - ${analysis.week_52_high:.2f}")
    print(f"\nSummary: {analysis.summary}")
    print("\nKey Drivers:")
    for driver in analysis.key_drivers:
        print(f"  • {driver}")
    print("\nKey Risks:")
    for risk in analysis.key_risks:
        print(f"  • {risk}")
    print(f"\nRecommendation: {analysis.recommendation}")
    print(f"{'=' * 60}\n")

# ============================================================================
# More Examples
# ============================================================================
"""
Structured output is perfect for:

1. Building UIs
   analysis = agent.run("Analyze TSLA").content
   render_stock_card(analysis)

2. Storing in databases
   db.insert("analyses", analysis.model_dump())

3. Comparing stocks
   nvda = agent.run("Analyze NVDA").content
   amd = agent.run("Analyze AMD").content
   if nvda.pe_ratio < amd.pe_ratio:
       print(f"{nvda.ticker} is cheaper by P/E")

4. Building pipelines
   tickers = ["AAPL", "GOOGL", "MSFT"]
   analyses = [agent.run(f"Analyze {t}").content for t in tickers]

The schema guarantees you always get the fields you expect.
No parsing, no surprises.
"""
