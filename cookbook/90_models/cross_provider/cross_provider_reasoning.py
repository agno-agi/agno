"""
Cross-Provider Reasoning: Thinking Models Across Providers
==========================================================

Demonstrates reasoning/thinking models across provider switches.
Each provider uses its native thinking configuration, and the
conversation history (including reasoning_content) is preserved
across switches.

Flow:
  1. Claude with thinking enabled solves a math problem
  2. OpenAI continues with a follow-up calculation
  3. Gemini summarizes the full conversation history

Requires: GOOGLE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

agent_db = SqliteDb(db_file="tmp/cross_provider.db", session_table="reasoning_sessions")

tools = [CalculatorTools()]
session_id = "cross-provider-reasoning"
instructions = """\
You are a math tutor. Show your reasoning step by step. Use the calculator
for arithmetic operations. Explain each step clearly.\
"""

claude_agent = Agent(
    name="Math Tutor (Claude Thinking)",
    model=Claude(
        id="claude-sonnet-4-20250514",
        thinking={"type": "enabled", "budget_tokens": 2048},
    ),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

openai_agent = Agent(
    name="Math Tutor (OpenAI)",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

gemini_agent = Agent(
    name="Math Tutor (Gemini)",
    model=Gemini(id="gemini-2.0-flash"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

if __name__ == "__main__":
    print("=" * 60)
    print("Turn 1: Claude (with thinking) solves a problem")
    print("=" * 60)
    claude_agent.print_response(
        "A store has a 25% off sale. If an item originally costs $84, "
        "what is the sale price? Then calculate the tax at 8.5%.",
        session_id=session_id,
        stream=True,
        show_full_reasoning=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 2: OpenAI continues with follow-up")
    print("=" * 60)
    openai_agent.print_response(
        "If I buy 3 of those items at the sale price (with tax), "
        "how much do I spend total? How much did I save compared to "
        "buying 3 at full price (with tax)?",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 3: Gemini summarizes all calculations")
    print("=" * 60)
    gemini_agent.print_response(
        "Summarize all the calculations from our conversation. "
        "Present a clear breakdown of the original price, discounts, "
        "taxes, and total savings.",
        session_id=session_id,
        stream=True,
    )
