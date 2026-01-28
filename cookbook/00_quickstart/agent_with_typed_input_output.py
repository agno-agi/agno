"""
Agent with Typed Input and Output - Full Type Safety
=====================================================
This example shows how to define both input and output schemas for your agent.
You get end-to-end type safety: validate what goes in, guarantee what comes out.

Perfect for building robust pipelines where you need contracts on both ends.
The agent validates inputs and guarantees output structure.

Key concepts:
- input_schema: A Pydantic model defining what the agent accepts
- output_schema: A Pydantic model defining what the agent returns
- Pass input as a dict or Pydantic model — both work

Example inputs to try:
- {"ticker": "NVDA", "analysis_type": "quick", "include_risks": True}
- {"ticker": "TSLA", "analysis_type": "deep", "include_risks": True}
"""

from typing import List, Literal, Optional

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
# Input Schema — what the agent accepts
# ============================================================================
class AnalysisRequest(BaseModel):
    """Structured input for requesting a stock analysis."""

    ticker: str = Field(..., description="Stock ticker symbol (e.g., NVDA, AAPL)")
    analysis_type: Literal["quick", "deep"] = Field(
        default="quick",
        description="quick = summary only, deep = full analysis with drivers/risks",
    )
    include_risks: bool = Field(
        default=True, description="Whether to include risk analysis"
    )


# ============================================================================
# Output Schema — what the agent returns
# ============================================================================
class StockAnalysis(BaseModel):
    """Structured output for stock analysis."""

    ticker: str = Field(..., description="Stock ticker symbol")
    company_name: str = Field(..., description="Full company name")
    current_price: float = Field(..., description="Current stock price in USD")
    summary: str = Field(..., description="One-line summary of the stock")
    key_drivers: Optional[List[str]] = Field(
        None, description="Key growth drivers (if deep analysis)"
    )
    key_risks: Optional[List[str]] = Field(
        None, description="Key risks (if include_risks=True)"
    )
    recommendation: str = Field(
        ..., description="One of: Strong Buy, Buy, Hold, Sell, Strong Sell"
    )


# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """\
You are a Finance Agent that produces structured stock analyses.

## Input Parameters

You receive structured requests with:
- ticker: The stock to analyze
- analysis_type: "quick" (summary only) or "deep" (full analysis)
- include_risks: Whether to include risk analysis

## Workflow

1. Fetch data for the requested ticker
2. If analysis_type is "deep", identify key drivers
3. If include_risks is True, identify key risks
4. Provide a clear recommendation

## Rules

- Source: Yahoo Finance
- Match output to input parameters — don't include drivers for "quick" analysis
- Recommendation must be one of: Strong Buy, Buy, Hold, Sell, Strong Sell\
"""

# ============================================================================
# Create the Agent
# ============================================================================
agent_with_typed_input_output = Agent(
    name="Agent with Typed Input Output",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[YFinanceTools()],
    input_schema=AnalysisRequest,
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
    # Option 1: Pass input as a dict
    response_1 = agent_with_typed_input_output.run(
        input={
            "ticker": "NVDA",
            "analysis_type": "deep",
            "include_risks": True,
        }
    )

    # Access the typed output
    analysis_1: StockAnalysis = response_1.content

    print(f"\n{'=' * 60}")
    print(f"Stock Analysis: {analysis_1.company_name} ({analysis_1.ticker})")
    print(f"{'=' * 60}")
    print(f"Price: ${analysis_1.current_price:.2f}")
    print(f"Summary: {analysis_1.summary}")
    if analysis_1.key_drivers:
        print("\nKey Drivers:")
        for driver in analysis_1.key_drivers:
            print(f"  • {driver}")
    if analysis_1.key_risks:
        print("\nKey Risks:")
        for risk in analysis_1.key_risks:
            print(f"  • {risk}")
    print(f"\nRecommendation: {analysis_1.recommendation}")
    print(f"{'=' * 60}\n")

    # Option 2: Pass input as a Pydantic model
    request = AnalysisRequest(
        ticker="AAPL",
        analysis_type="quick",
        include_risks=False,
    )
    response_2 = agent_with_typed_input_output.run(input=request)

    # Access the typed output
    analysis_2: StockAnalysis = response_2.content

    print(f"\n{'=' * 60}")
    print(f"Stock Analysis: {analysis_2.company_name} ({analysis_2.ticker})")
    print(f"{'=' * 60}")
    print(f"Price: ${analysis_2.current_price:.2f}")
    print(f"Summary: {analysis_2.summary}")
    if analysis_2.key_drivers:
        print("\nKey Drivers:")
        for driver in analysis_2.key_drivers:
            print(f"  • {driver}")
    if analysis_2.key_risks:
        print("\nKey Risks:")
        for risk in analysis_2.key_risks:
            print(f"  • {risk}")
    print(f"\nRecommendation: {analysis_2.recommendation}")
    print(f"{'=' * 60}\n")

# ============================================================================
# More Examples
# ============================================================================
"""
Typed input + output is perfect for:

1. API endpoints
   @app.post("/analyze")
   def analyze(request: AnalysisRequest) -> StockAnalysis:
       return agent.run(input=request).content

2. Batch processing
   requests = [
       AnalysisRequest(ticker="NVDA", analysis_type="quick"),
       AnalysisRequest(ticker="AMD", analysis_type="quick"),
       AnalysisRequest(ticker="INTC", analysis_type="quick"),
   ]
   results = [agent.run(input=r).content for r in requests]

3. Pipeline composition
   # Agent 1 outputs what Agent 2 expects as input
   screening_result = screener_agent.run(input=criteria).content
   analysis_result = analysis_agent.run(input=screening_result).content

Type safety on both ends = fewer bugs, better tooling, clearer contracts.
"""
