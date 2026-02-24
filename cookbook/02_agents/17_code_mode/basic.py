"""
Code Mode — Real-World Example with YFinanceTools
==================================================
Demonstrates ToolExecuteMode wrapping a real Agno toolkit.
The LLM writes Python code that calls multiple YFinance tools
in a single exec() pass — loops, filters, and formatting included.

Compares token usage: Code Mode vs Traditional tool_call mode.

Run:
  .venvs/demo/bin/python cookbook/02_agents/17_code_mode/basic.py
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tool_execute_mode import ToolExecuteMode
from agno.tools.yfinance import YFinanceTools

TASK = (
    "Compare AAPL, MSFT, and GOOGL: get each stock's current price and analyst recommendations. "
    "Summarize in a markdown table with columns: Symbol, Price, Recommendation, # of Analysts."
)

CODE_MODE_INSTRUCTIONS = (
    "You solve tasks by writing Python code using the run_code tool.\n\n"
    "CRITICAL RULES:\n"
    "1. Write ONE COMPLETE Python program per run_code call. NEVER make multiple small calls.\n"
    "2. Your code should handle the ENTIRE task: fetch data, loop, filter, format.\n"
    "3. Call functions DIRECTLY: get_current_stock_price(symbol='AAPL'). No prefix.\n"
    "4. json and math are pre-loaded. Do NOT write import statements.\n"
    "5. All functions return JSON strings. Always use json.loads() to parse results.\n"
    "6. Store your final answer in `result` as a formatted markdown string.\n\n"
    "PATTERN:\n"
    "  price_data = json.loads(get_current_stock_price(symbol='AAPL'))\n"
    "  recs = json.loads(get_analyst_recommendations(symbol='AAPL'))\n"
    "  result = '| Symbol | Price |\\n' + rows"
)

if __name__ == "__main__":
    yf = YFinanceTools(
        enable_stock_price=True,
        enable_analyst_recommendations=True,
    )

    print("=" * 70)
    print("CODE MODE")
    print("=" * 70)

    code_agent = Agent(
        name="Code Mode Agent",
        model=Claude(id="claude-sonnet-4-20250514"),
        tools=[ToolExecuteMode(tools=[yf])],
        tool_call_limit=3,
        instructions=CODE_MODE_INSTRUCTIONS,
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
        instructions="You are a financial analyst. Use the available tools to answer questions.",
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
