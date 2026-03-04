"""
Tool Execution — Multi-Toolkit Data Pipeline (36 tools)
=========================================================
Combines DuckDbTools(13) + YFinanceTools(9) + CalculatorTools(8) + FileTools(6)
into a single tool execution agent with 36 functions. Discovery mode auto-triggers
at this scale, so the LLM uses search_tools to find relevant functions
from across all four toolkits, then writes one code block that pipelines:
  fetch stock data -> load into DuckDB -> run analytics -> calculate -> save report

Compares token usage and tool call count: Tool Execution vs Traditional.

Run:
  .venvs/demo/bin/python cookbook/02_agents/17_tool_execution/data_pipeline.py
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.calculator import CalculatorTools
from agno.tools.duckdb import DuckDbTools
from agno.tools.file import FileTools
from agno.tools.yfinance import YFinanceTools

TASK = (
    "Build a tech stock comparison report for AAPL, MSFT, GOOGL, NVDA, and META.\n\n"
    "Steps:\n"
    "1. Fetch each stock's current price and key financials (P/E ratio, market cap, etc).\n"
    "2. Create a DuckDB table called 'tech_stocks' and load the data.\n"
    "3. Run SQL queries to find: highest P/E, largest market cap, best performing stock.\n"
    "4. Calculate the average P/E ratio and total combined market cap.\n"
    "5. Save the final analysis report to /tmp/tech_stock_report.md\n\n"
    "Include a markdown table comparing all 5 stocks and a summary section with key findings."
)

TRAD_INSTRUCTIONS = (
    "You are a data analyst. Use the available tools to complete the task. "
    "Fetch data, create tables, run queries, and save results using the tools provided."
)

if __name__ == "__main__":
    yf = YFinanceTools(
        enable_stock_price=True,
        enable_company_info=True,
        enable_analyst_recommendations=True,
        enable_stock_fundamentals=True,
        enable_income_statements=True,
        enable_historical_prices=True,
        enable_key_financial_ratios=True,
        enable_technical_indicators=True,
        enable_company_news=True,
    )
    duckdb = DuckDbTools()
    calc = CalculatorTools()
    files = FileTools(base_dir=Path("/tmp"))

    all_tools = [yf, duckdb, calc, files]

    print("=" * 70)
    print("TOOL EXECUTION (36 tools, discovery mode)")
    print("=" * 70)

    code_agent = Agent(
        name="Tool Execution Agent",
        model=Claude(id="claude-sonnet-4-20250514"),
        tools=all_tools,
        enable_tool_execution=True,
        markdown=True,
    )

    code_response = code_agent.run(TASK)
    print(f"\n{code_response.content}\n")
    cm_metrics = code_response.metrics

    print("\n" + "=" * 70)
    print("TRADITIONAL MODE (36 tools, direct tool calls)")
    print("=" * 70)

    trad_agent = Agent(
        name="Traditional Agent",
        model=Claude(id="claude-sonnet-4-20250514"),
        tools=all_tools,
        instructions=TRAD_INSTRUCTIONS,
        markdown=True,
    )

    trad_response = trad_agent.run(TASK)
    print(f"\n{trad_response.content}\n")
    tm_metrics = trad_response.metrics

    cm_total = cm_metrics.total_tokens if cm_metrics else 0
    tm_total = tm_metrics.total_tokens if tm_metrics else 0
    cm_input = cm_metrics.input_tokens if cm_metrics else 0
    tm_input = tm_metrics.input_tokens if tm_metrics else 0
    cm_output = cm_metrics.output_tokens if cm_metrics else 0
    tm_output = tm_metrics.output_tokens if tm_metrics else 0
    cm_msgs = len(code_response.messages or [])
    tm_msgs = len(trad_response.messages or [])

    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)
    print(f"{'Metric':<25} {'Tool Exec':>15} {'Traditional':>15} {'Savings':>15}")
    print("-" * 70)
    print(
        f"{'Input tokens':<25} {cm_input:>15,} {tm_input:>15,} {tm_input - cm_input:>15,}"
    )
    print(
        f"{'Output tokens':<25} {cm_output:>15,} {tm_output:>15,} {tm_output - cm_output:>15,}"
    )
    print(
        f"{'Total tokens':<25} {cm_total:>15,} {tm_total:>15,} {tm_total - cm_total:>15,}"
    )
    print(
        f"{'Model turns (messages)':<25} {cm_msgs:>15,} {tm_msgs:>15,} {tm_msgs - cm_msgs:>15,}"
    )
    if tm_total > 0:
        pct = (1 - cm_total / tm_total) * 100
        print(f"{'Token reduction':<25} {pct:>14.0f}%")
