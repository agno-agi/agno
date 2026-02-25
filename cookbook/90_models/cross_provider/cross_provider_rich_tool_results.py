"""
Rich Tool Results: Complex JSON Across Providers
=================================================

Stresses content serialization with deeply nested tool results. Uses
YFinanceTools.get_company_info() which returns 20+ fields including nested
objects, and DuckDuckGoTools which returns arrays of search result dicts.

This directly validates that json.dumps() (not Python str()) is used when
tool results contain dicts, because str({"key": "value"}) produces
{'key': 'value'} (single quotes) which is invalid JSON.

Flow:
  1. Gemini fetches full company info for AAPL (large nested JSON)
  2. OpenAI fetches MSFT company info + does a web search
  3. Claude compares the two companies using all prior tool results

Requires: GOOGLE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

agent_db = SqliteDb(
    db_file="tmp/cross_provider.db", session_table="rich_results_sessions"
)

tools = [
    YFinanceTools(),
    DuckDuckGoTools(),
]
session_id = "rich-tool-results"
instructions = (
    "You are a financial research assistant. Use all available tools to "
    "gather comprehensive data. Always cite specific numbers and data points."
)

gemini_agent = Agent(
    name="Research Agent (Gemini)",
    model=Gemini(id="gemini-2.0-flash"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

openai_agent = Agent(
    name="Research Agent (OpenAI)",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=instructions,
    tools=tools,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

claude_agent = Agent(
    name="Research Agent (Claude)",
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
    print("Turn 1: Gemini fetches AAPL company info (large nested JSON)")
    print("=" * 60)
    gemini_agent.print_response(
        "Get the full company info and stock fundamentals for AAPL.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 2: OpenAI fetches MSFT info + web search")
    print("=" * 60)
    openai_agent.print_response(
        "Get the full company info for MSFT. Also search the web for recent MSFT news.",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 3: Claude compares both companies")
    print("=" * 60)
    claude_agent.print_response(
        "Compare AAPL and MSFT using the data gathered above. "
        "Which has better fundamentals? Cite specific metrics.",
        session_id=session_id,
        stream=True,
    )
