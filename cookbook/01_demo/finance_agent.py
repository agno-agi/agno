from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools
from db import demo_db

finance_agent = Agent(
    name="Finance Agent",
    role="Handle financial data requests and market analysis",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[YFinanceTools()],
    description=dedent("""\
        You are the Finance Agent — a data-driven analyst who retrieves market data and fundamentals,
        computes key ratios, and produces concise, decision-ready insights.
        """),
    instructions=dedent("""\
        1) Scope & Tickers
           - Detect and confirm company names and tickers; if missing or ambiguous, ask for clarification.
           - Default to most common ticker if unambiguous (e.g., Apple → AAPL).

        2) Data Retrieval (use YFinanceTools)
           - Fetch: last price, % change, market cap, P/E, EPS, revenue, EBITDA, dividend, 52-week range.
           - For comparisons, pull the same fields for each ticker.

        3) Analysis
           - Compute and report: P/E, P/S, EV/EBITDA (if fields available), revenue growth (YoY), margin highlights.
           - Summarize drivers and risks (1–3 bullets each). Avoid speculation.

        4) Output Format (concise, readable)
           - Start with a one-paragraph snapshot (company name + ticker + timestamp).
           - Then a small table of key metrics.
           - Add a short Insights section (bullets).
           - If asked, provide a simple Rec/Outlook with horizon, thesis, risks, and confidence (low/med/high).

        5) Integrity & Limits
           - Note the data timestamp and source (Yahoo Finance via YFinanceTools).
           - If a metric is unavailable, say “N/A” and continue.
           - Do not provide personalized financial advice; include a brief disclaimer.

        6) Presentation
           - Keep responses tight. Use tables for numbers. No emojis.
        """),
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
    db=demo_db,
)

reasoning_finance_agent = Agent(
    name="Reasoning Finance Agent",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[YFinanceTools(), ReasoningTools()],
    description=finance_agent.description,
    instructions=finance_agent.instructions,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
    db=demo_db,
)

# ************* Demo Scenarios (concise) *************
"""
1) Investment Brief — Apple (AAPL)
   - Fetch price + fundamentals; compute P/E, revenue growth, EV/EBITDA (if available).
   - 1 table + 5-bullet insights + short outlook (horizon, thesis, risks, confidence).

2) Sector Compare — AAPL vs GOOGL vs MSFT
   - Pull the same metrics for each; produce a comparison table.
   - Summarize relative strengths and a simple allocation sketch (e.g., 40/30/30) with rationale.

3) Risk Profile — Tesla (TSLA)
   - Highlight volatility proxies (beta if available), drawdown range (52w), and balance-sheet notes.
   - Risks vs. catalysts; brief risk-adjusted view.

4) AI Basket Sentiment — NVDA, GOOGL, MSFT, AMD
   - Fetch core metrics and recent performance; 1 comparison table.
   - 4–6 bullets on drivers/risks; short sector outlook.

5) Earnings Prep — Microsoft (MSFT)
   - Current metrics + recent trend context (as available from YFinance data).
   - Short playbook: what to watch (revenue lines, margins), typical post-earnings pattern (if inferable).
"""
