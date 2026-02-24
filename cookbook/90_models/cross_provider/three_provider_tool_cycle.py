"""
Three-Provider Tool Cycle: Gemini -> OpenAI -> Claude -> Gemini
===============================================================

Demonstrates cycling through all three major providers in a single session
while preserving tool call history.

Flow:
  1. Gemini calculates 42 * 17 + 100
  2. OpenAI divides the result by 7
  3. Claude computes square root of the result
  4. Gemini summarizes all calculations

Requires: GOOGLE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

agent_db = SqliteDb(
    db_file="tmp/cross_provider.db", session_table="three_provider_sessions"
)

tools = [CalculatorTools()]
session_id = "cross-provider-three-way"
instructions = "You are a math assistant. Use the calculator tools to compute results. Always show the final numerical answer."

gemini_agent = Agent(
    name="Math Agent (Gemini)",
    model=Gemini(id="gemini-2.0-flash"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

openai_agent = Agent(
    name="Math Agent (OpenAI)",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

claude_agent = Agent(
    name="Math Agent (Claude)",
    model=Claude(id="claude-sonnet-4-20250514"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

if __name__ == "__main__":
    print("=" * 60)
    print("Turn 1: Gemini calculates 42 * 17, then adds 100")
    print("=" * 60)
    gemini_agent.print_response(
        "What is 42 * 17? Then add 100 to that result.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 2: OpenAI divides the result by 7")
    print("=" * 60)
    openai_agent.print_response(
        "Take the final result from the previous calculation and divide it by 7.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 3: Claude computes square root")
    print("=" * 60)
    claude_agent.print_response(
        "Compute the square root of the result from the last calculation.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 4: Gemini summarizes all calculations")
    print("=" * 60)
    gemini_agent.print_response(
        "Summarize all the calculations we have done across all turns.",
        session_id=session_id,
        stream=True,
    )
