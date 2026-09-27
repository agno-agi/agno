"""
Analyst Mode: Statements, Insiders, Earnings, Filings
======================================================
By default FinanceTools registers the seven "market brief" tools. Analyst
work needs the long tail too: financial statements, insider trades, earnings
history and SEC filings. Turn them on with `all=True`, or one at a time
(`financials=True`, `insider_trades=True`, `earnings=True`, `sec_filings=True`).

Tools registered here (yfinance provider):
    search_symbols, get_quote, get_price_history, get_company_profile,
    get_key_metrics, get_news, get_analyst_recommendations, get_financials,
    get_insider_trades, get_earnings, get_sec_filings

Prompts to try:
- "Deep dive on NVDA: revenue and margins for the last 4 quarters, insider activity, next earnings date, latest 8-K."
- "Compare the free cash flow of MSFT and GOOGL over the last 3 fiscal years."
"""

from agno.agent import Agent
from agno.tools.finance import FinanceTools

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are an equity research analyst.
- Start with a two-line thesis, then the evidence in tables.
- For statements, name the reporting period and currency of every figure.
- Compute margins and growth yourself from the statement line items when they are not provided.
- Flag data you could not retrieve as N/A. Never estimate a missing number.
- Close with the next scheduled earnings date if available.
"""

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Equity Analyst",
    model="openai:gpt-5.6",
    tools=[FinanceTools(all=True)],
    instructions=instructions,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Deep dive on NVDA: revenue and net margin for the last 4 quarters, notable insider activity, "
        "the next earnings date, and the most recent 8-K.",
        stream=True,
    )
