"""
Agent with Structured Output - Finance Agent with Typed Responses
==================================================================
This example shows how to get structured, typed responses from your agent.
Instead of free-form text, a successful run returns a validated Pydantic model.
The schema validates shape and types; tools and source checks establish facts.

Perfect for building pipelines, UIs, or integrations where you need
predictable data shapes. Parse it, store it, display it — no regex required.

Key concepts:
- output_schema: A Pydantic model defining the response structure
- Successful responses are parsed and validated against this schema
- Access structured data via response.content

Example prompts to try:
- "Analyze NVDA"
- "Give me a report on Tesla"
- "What's the investment case for Apple?"
"""

from typing import List, Literal, Optional

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Structured Output Schema
# ---------------------------------------------------------------------------
class StockAnalysis(BaseModel):
    """Structured output for stock analysis."""

    ticker: str = Field(
        ...,
        min_length=1,
        max_length=10,
        pattern=r"^[A-Za-z][A-Za-z0-9.-]*$",
        description="Stock ticker symbol (e.g., NVDA)",
    )
    company_name: str = Field(..., description="Full company name")
    current_price: Optional[float] = Field(
        None, ge=0, description="Current stock price in USD, if available"
    )
    market_cap: Optional[str] = Field(
        None, description="Market cap (e.g., '3.2T' or '150B'), if available"
    )
    pe_ratio: Optional[float] = Field(None, description="P/E ratio, if available")
    week_52_high: Optional[float] = Field(
        None, ge=0, description="52-week high price, if available"
    )
    week_52_low: Optional[float] = Field(
        None, ge=0, description="52-week low price, if available"
    )
    summary: str = Field(..., description="One-line summary of the stock")
    key_drivers: List[str] = Field(..., description="2-3 key growth drivers")
    key_risks: List[str] = Field(..., description="2-3 key risks")
    recommendation: Literal["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"] = Field(
        ..., description="Research outlook based on the available data"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
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
- Missing market data? Use null. Never estimate or invent a value.
- Recommendation must be one of: Strong Buy, Buy, Hold, Sell, Strong Sell\
"""

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent_with_structured_output = Agent(
    name="Agent with Structured Output",
    model=Gemini(id="gemini-3.6-flash"),
    instructions=instructions,
    tools=[
        YFinanceTools(
            enable_company_info=True,
            enable_stock_fundamentals=True,
        )
    ],
    output_schema=StockAnalysis,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Get structured output
    response = agent_with_structured_output.run("Analyze NVIDIA")

    # Access the typed data
    analysis: StockAnalysis = response.content

    # Use it programmatically
    print(f"\n{'=' * 60}")
    print(f"Stock Analysis: {analysis.company_name} ({analysis.ticker})")
    print(f"{'=' * 60}")
    price = (
        f"${analysis.current_price:.2f}"
        if analysis.current_price is not None
        else "N/A"
    )
    pe_ratio = analysis.pe_ratio if analysis.pe_ratio is not None else "N/A"
    week_52_range = (
        f"${analysis.week_52_low:.2f} - ${analysis.week_52_high:.2f}"
        if analysis.week_52_low is not None and analysis.week_52_high is not None
        else "N/A"
    )
    print(f"Price: {price}")
    print(f"Market Cap: {analysis.market_cap or 'N/A'}")
    print(f"P/E Ratio: {pe_ratio}")
    print(f"52-Week Range: {week_52_range}")
    print(f"\nSummary: {analysis.summary}")
    print("\nKey Drivers:")
    for driver in analysis.key_drivers:
        print(f"  • {driver}")
    print("\nKey Risks:")
    for risk in analysis.key_risks:
        print(f"  • {risk}")
    print(f"\nRecommendation: {analysis.recommendation}")
    print(f"{'=' * 60}\n")

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
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
   if (
       nvda.pe_ratio is not None
       and amd.pe_ratio is not None
       and nvda.pe_ratio < amd.pe_ratio
   ):
       print(f"{nvda.ticker} is cheaper by P/E")

4. Building pipelines
   tickers = ["AAPL", "GOOGL", "MSFT"]
   analyses = [agent.run(f"Analyze {t}").content for t in tickers]

The schema removes ad-hoc parsing and makes missing values explicit.
It does not make model-generated facts correct, so keep source validation.
"""
