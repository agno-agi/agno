"""
Tool Execution — Portfolio Analyzer (20-Stock Stress Test)
===========================================================
Head-to-head comparison: tool execution vs traditional tool_call mode
on a task requiring 60+ sequential tool calls.

Without tool execution: the model makes ~60 individual tool calls across ~60 turns.
Each turn re-reads all previous tool results -> O(N^2) token growth.

With tool execution: the model writes ONE program with a loop -> 1-2 turns total.

No API keys needed (YFinance is free).

Run: .venvs/demo/bin/python cookbook/02_agents/17_tool_execution/portfolio_analyzer.py
"""

import time

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.yfinance import YFinanceTools

STOCKS = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "NFLX",
    "AMD",
    "CRM",
    "ORCL",
    "ADBE",
    "INTC",
    "QCOM",
    "AVGO",
    "UBER",
    "SHOP",
    "SQ",
    "SNOW",
    "PLTR",
]

TASK = (
    f"Analyze these {len(STOCKS)} stocks: {', '.join(STOCKS)}.\n"
    "For EACH stock, get: current price, analyst recommendations, and key financial ratios.\n"
    "Then build a comprehensive markdown comparison table with columns:\n"
    "Stock | Price | P/E Ratio | Recommendation | Target Price\n"
    "Sort by P/E ratio (lowest first). Add a summary of the top 3 value picks."
)

MODEL = "claude-sonnet-4-20250514"


def build_yfinance():
    return YFinanceTools(
        enable_stock_price=True,
        enable_analyst_recommendations=True,
        enable_key_financial_ratios=True,
    )


def run_tool_execution():
    agent = Agent(
        model=Claude(id=MODEL),
        tools=[build_yfinance()],
        enable_tool_execution=True,
        markdown=True,
        tool_call_limit=5,
    )
    return agent.run(TASK)


def run_traditional():
    agent = Agent(
        model=Claude(id=MODEL),
        tools=[build_yfinance()],
        markdown=True,
        tool_call_limit=80,
    )
    return agent.run(TASK)


def print_metrics(label, response, elapsed):
    m = response.metrics
    content = response.content or ""
    tool_calls = len(response.tools) if response.tools else 0

    print(f"\n--- {label} ---")
    print(f"Content: {len(content)} chars")
    print(f"Tool calls: {tool_calls}")
    print(f"Messages: {len(response.messages or [])}")
    if m:
        print(f"Input tokens:  {m.input_tokens:>10,}")
        print(f"Output tokens: {m.output_tokens:>10,}")
        print(f"Total tokens:  {m.total_tokens:>10,}")
    print(f"Duration: {elapsed:.1f}s")
    return m


if __name__ == "__main__":
    print("=" * 70)
    print(f"PORTFOLIO ANALYZER — {len(STOCKS)} stocks, ~60 tool calls")
    print("=" * 70)

    # Tool execution
    print("\n[1/2] Running TOOL EXECUTION...")
    t0 = time.time()
    code_resp = run_tool_execution()
    code_time = time.time() - t0
    cm = print_metrics("TOOL EXECUTION", code_resp, code_time)

    # Traditional
    print("\n[2/2] Running TRADITIONAL MODE...")
    t0 = time.time()
    trad_resp = run_traditional()
    trad_time = time.time() - t0
    tm = print_metrics("TRADITIONAL", trad_resp, trad_time)

    # Comparison
    cm_total = cm.total_tokens if cm else 0
    tm_total = tm.total_tokens if tm else 0
    cm_input = cm.input_tokens if cm else 0
    tm_input = tm.input_tokens if tm else 0

    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)
    print(f"{'Metric':<25} {'Tool Exec':>15} {'Traditional':>15} {'Savings':>15}")
    print("-" * 70)
    print(
        f"{'Input tokens':<25} {cm_input:>15,} {tm_input:>15,} {tm_input - cm_input:>15,}"
    )
    print(
        f"{'Total tokens':<25} {cm_total:>15,} {tm_total:>15,} {tm_total - cm_total:>15,}"
    )
    print(
        f"{'Duration':<25} {code_time:>14.1f}s {trad_time:>14.1f}s {trad_time - code_time:>14.1f}s"
    )

    cm_calls = len(code_resp.tools) if code_resp.tools else 0
    tm_calls = len(trad_resp.tools) if trad_resp.tools else 0
    print(f"{'Tool calls':<25} {cm_calls:>15} {tm_calls:>15}")
    print(
        f"{'Messages':<25} {len(code_resp.messages or []):>15} {len(trad_resp.messages or []):>15}"
    )

    if tm_total > 0 and cm_total > 0:
        pct = (1 - cm_total / tm_total) * 100
        ratio = tm_total / cm_total
        print(f"\nToken reduction: {pct:.0f}% ({ratio:.1f}x fewer tokens)")

    # Quality check
    code_content = (code_resp.content or "").lower()
    trad_content = (trad_resp.content or "").lower()
    code_stocks_found = sum(1 for s in STOCKS if s.lower() in code_content)
    trad_stocks_found = sum(1 for s in STOCKS if s.lower() in trad_content)
    print(
        f"\nStocks in output: tool_exec={code_stocks_found}/{len(STOCKS)}, traditional={trad_stocks_found}/{len(STOCKS)}"
    )

    print(
        f"\nSTATUS: {'PASS' if cm_total < tm_total and code_stocks_found >= 5 else 'FAIL'}"
    )
