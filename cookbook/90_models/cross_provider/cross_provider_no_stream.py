"""
Non-Streaming Cross-Provider: Sync Path Validation
====================================================

All other cross-provider cookbooks use stream=True. This one uses
stream=False to exercise the synchronous invoke() path, which has
a separate code path for message formatting.

Also tests the reverse direction: Claude -> OpenAI -> Gemini.

Flow:
  1. Claude calculates compound interest (no streaming)
  2. OpenAI does a follow-up calculation (no streaming)
  3. Gemini summarizes all results (no streaming)

Requires: GOOGLE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

agent_db = SqliteDb(db_file="tmp/cross_provider.db", session_table="no_stream_sessions")

tools = [CalculatorTools()]
session_id = "cross-provider-no-stream"
instructions = "You are a math assistant. Use the calculator for all arithmetic. Show exact numbers."

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

if __name__ == "__main__":
    print("=" * 60)
    print("Turn 1: Claude calculates compound interest (no stream)")
    print("=" * 60)
    response = claude_agent.run(
        "Calculate compound interest on $10,000 at 5% annual rate "
        "for 3 years, compounded monthly. What is the final amount?",
        session_id=session_id,
        stream=False,
    )
    print(response.content)

    print("\n")
    print("=" * 60)
    print("Turn 2: OpenAI does follow-up calculation (no stream)")
    print("=" * 60)
    response = openai_agent.run(
        "Using the final amount from above, if I withdraw 20% as tax, "
        "how much do I keep? What was my net profit?",
        session_id=session_id,
        stream=False,
    )
    print(response.content)

    print("\n")
    print("=" * 60)
    print("Turn 3: Gemini summarizes (no stream)")
    print("=" * 60)
    response = gemini_agent.run(
        "Summarize all the financial calculations from this conversation.",
        session_id=session_id,
        stream=False,
    )
    print(response.content)
