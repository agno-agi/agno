"""
Code Mode + code_model — Dual-Model Pattern
=============================================
Uses a cheap/fast planning model (GPT-4o) as the agent's main model,
while a specialized code_model (Claude) writes and executes Python code
internally. The planning model just describes tasks in plain English.

Benefits:
  - Planning model never writes code (no code-generation failures)
  - Code model gets full tool stubs (no discovery needed)
  - Internal retries are invisible to the agent (no token snowball)
  - Works with ANY model as the planning model (even non-coding models)

Run:
  .venvs/demo/bin/python cookbook/02_agents/17_code_mode/code_model.py
"""

import time

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools
from agno.tools.yfinance import YFinanceTools

TASK = (
    "Compare the stock performance of AAPL, MSFT, and GOOGL.\n"
    "Get current prices and analyst recommendations for each.\n"
    "Calculate the average price across all three.\n"
    "Present a markdown table: Symbol | Price | Recommendation | vs Average"
)

if __name__ == "__main__":
    yf = YFinanceTools(
        enable_stock_price=True,
        enable_analyst_recommendations=True,
        enable_stock_fundamentals=True,
    )
    calc = CalculatorTools()

    print("=" * 70)
    print("CODE MODEL DEMO")
    print("Planning model: GPT-4o (describes tasks in English)")
    print("Code model:     Claude Sonnet 4 (writes Python code)")
    print("=" * 70)

    agent = Agent(
        name="Stock Analyst",
        model=OpenAIChat(id="gpt-4o"),
        tools=[yf, calc],
        code_mode=True,
        code_model=Claude(id="claude-sonnet-4-20250514"),
        tool_call_limit=5,
        markdown=True,
    )

    t0 = time.time()
    response = agent.run(TASK)
    elapsed = time.time() - t0

    print(f"\n{response.content}\n")

    m = response.metrics
    if m:
        print("-" * 50)
        print(f"Input tokens:  {m.input_tokens:,}")
        print(f"Output tokens: {m.output_tokens:,}")
        print(f"Total tokens:  {m.total_tokens:,}")
        print(f"Duration:      {elapsed:.1f}s")
        print(f"Messages:      {len(response.messages or [])}")
