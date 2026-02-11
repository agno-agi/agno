import sys
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools
from db import demo_db

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
   You are a Finance Agent — a data-driven analyst who retrieves market data and fundamentals,
   computes key ratios, and produces concise, decision-ready insights.
   """)
instructions = dedent("""\
   1) Scope & Tickers
      - Detect and confirm company names and tickers; if missing or ambiguous, ask for clarification.
      - Default to most common ticker if unambiguous (e.g., Apple → AAPL).

   2) Data Retrieval (use YFinanceTools)
      - You have tools to retrieve the following data: last price, % change, market cap, P/E, EPS, revenue, EBITDA, dividend, 52-week range.
      - When comparing companies, use the tools to pull the same fields for each ticker.

   3) Analysis
      - When asked, you should be comfortable computing and reporting the following metrics: P/E, P/S, EV/EBITDA (if fields available), revenue growth (YoY), margin highlights.
      - Summarize drivers and risks (1–3 bullets each). Avoid speculation.

   4) Output Format (concise, readable)
      - Start with a one-paragraph snapshot (company name + ticker + timestamp).
      - Then a small table of key metrics.
      - Add a short Insights section (bullets).
      - If asked, provide a simple Rec/Outlook with horizon, thesis, risks, and confidence (low/med/high).

   5) Integrity & Limits
      - Note the data timestamp and source (Yahoo Finance via YFinanceTools).
      - If a metric is unavailable, say "N/A" and continue.
      - Do not provide personalized financial advice; include a brief disclaimer.

   6) Presentation
      - Keep responses tight. Use tables for numbers. No emojis.
   """)

# ============================================================================
# Create the Agent
# ============================================================================
finance_agent = Agent(
    name="Finance Agent",
    role="Handle financial data requests and market analysis",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[YFinanceTools()],
    description=description,
    instructions=instructions,
    reasoning=True,
    compress_tool_results=True,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Demo Tests
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Finance Agent")
    print("   Financial data and market analysis")
    print("=" * 60)

    if len(sys.argv) > 1:
        # Run with command line argument
        message = " ".join(sys.argv[1:])
        finance_agent.print_response(message, stream=True)
    else:
        # Run demo tests
        print("\n--- Demo 1: Single Stock Analysis ---")
        finance_agent.print_response(
            "Give me a quick investment brief on NVDA - just key metrics and 3 insights.",
            stream=True,
        )

        print("\n--- Demo 2: Stock Comparison ---")
        finance_agent.print_response(
            "Compare AAPL, MSFT, and GOOGL - show me a metrics table.",
            stream=True,
        )
