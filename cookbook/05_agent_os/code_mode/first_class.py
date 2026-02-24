"""
Code Mode — First-Class Agent Feature
======================================
Demonstrates code_mode as a built-in Agent parameter.
No manual CodeModeTool instantiation or instructions needed.

Three patterns:
  1. All tools code-moded (code_mode=True)
  2. Split: some direct, some code-moded (code_mode_tools=[...])
  3. Dual-model: cheap planner + strong code writer (code_model=...)

Run:
  .venvs/demo/bin/python cookbook/05_agent_os/code_mode/first_class.py
"""

import time

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools
from agno.tools.yfinance import YFinanceTools

TASK = (
    "Compare AAPL and MSFT: get current prices and analyst recommendations. "
    "Calculate the average price. Present results in a markdown table."
)


def pattern_1_all_tools():
    """All user tools wrapped in code mode."""
    agent = Agent(
        name="Stock Analyst",
        model=Claude(id="claude-sonnet-4-20250514"),
        tools=[
            YFinanceTools(enable_stock_price=True, enable_analyst_recommendations=True),
            CalculatorTools(),
        ],
        code_mode=True,
        tool_call_limit=3,
        markdown=True,
    )
    return agent.run(TASK)


def pattern_3_dual_model():
    """Cheap planner + strong code writer."""
    agent = Agent(
        name="Stock Analyst",
        model=OpenAIChat(id="gpt-4.1-mini"),
        tools=[
            YFinanceTools(enable_stock_price=True, enable_analyst_recommendations=True),
            CalculatorTools(),
        ],
        code_mode=True,
        code_model=Claude(id="claude-sonnet-4-20250514"),
        tool_call_limit=5,
        markdown=True,
    )
    return agent.run(TASK)


if __name__ == "__main__":
    print("=" * 60)
    print("PATTERN 1: All tools code-moded")
    print("=" * 60)
    t0 = time.time()
    r1 = pattern_1_all_tools()
    print(f"\n{r1.content}\n")
    m = r1.metrics
    if m:
        print(f"Tokens: {m.total_tokens:,} | Duration: {time.time() - t0:.1f}s")

    print("\n" + "=" * 60)
    print("PATTERN 3: Dual-model (OpenAI plans, Claude codes)")
    print("=" * 60)
    t0 = time.time()
    r3 = pattern_3_dual_model()
    print(f"\n{r3.content}\n")
    m = r3.metrics
    if m:
        print(f"Tokens: {m.total_tokens:,} | Duration: {time.time() - t0:.1f}s")
