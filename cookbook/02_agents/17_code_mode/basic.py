"""
Code Mode — Basic Example with YFinanceTools
==============================================
Demonstrates code_mode=True on an Agent. The LLM writes Python code
that calls multiple YFinance tools in a single exec() pass — loops,
filters, and formatting included.

Compares token usage: Code Mode vs Traditional tool_call mode.

Run:
  .venvs/demo/bin/python cookbook/02_agents/17_code_mode/basic.py
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.yfinance import YFinanceTools

TASK = (
    "Compare AAPL, MSFT, and GOOGL: get each stock's current price and analyst recommendations. "
    "Summarize in a markdown table with columns: Symbol, Price, Recommendation, # of Analysts."
)

if __name__ == "__main__":
    yf = YFinanceTools(
        enable_stock_price=True,
        enable_analyst_recommendations=True,
    )

    print("=" * 70)
    print("CODE MODE (code_mode=True)")
    print("=" * 70)

    code_agent = Agent(
        name="Code Mode Agent",
        model=Claude(id="claude-sonnet-4-20250514"),
        tools=[yf],
        code_mode=True,
        tool_call_limit=3,
        markdown=True,
    )

    code_response = code_agent.run(TASK)
    print(f"\n{code_response.content}\n")
    cm = code_response.metrics

    print("\n" + "=" * 70)
    print("TRADITIONAL MODE")
    print("=" * 70)

    trad_agent = Agent(
        name="Traditional Agent",
        model=Claude(id="claude-sonnet-4-20250514"),
        tools=[yf],
        markdown=True,
    )

    trad_response = trad_agent.run(TASK)
    print(f"\n{trad_response.content}\n")
    tm = trad_response.metrics

    cm_total = cm.total_tokens if cm else 0
    tm_total = tm.total_tokens if tm else 0
    cm_input = cm.input_tokens if cm else 0
    tm_input = tm.input_tokens if tm else 0
    cm_output = cm.output_tokens if cm else 0
    tm_output = tm.output_tokens if tm else 0

    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)
    print(f"{'Metric':<25} {'Code Mode':>15} {'Traditional':>15} {'Savings':>15}")
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
    if tm_total > 0:
        pct = (1 - cm_total / tm_total) * 100
        print(f"{'Reduction':<25} {pct:>14.0f}%")
