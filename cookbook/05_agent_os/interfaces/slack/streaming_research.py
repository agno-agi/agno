"""
Streaming Research Agent
========================

A research agent with reasoning and multiple tools, demonstrating rich
plan-block cards in Slack's streaming UI.

Uses o3-mini (reasoning model) so that Slack sees both reasoning cards
and tool-call cards in the plan block.

Requirements:
  - OPENAI_API_KEY with access to o3-mini
  - Slack app with ``assistant:write`` scope
  - Event Subscriptions for ``app_mention``, ``message.im``,
    and ``assistant_thread_started``
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Agent — reasoning model + multiple tools
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="research_sessions", db_file="tmp/research.db")

research_agent = Agent(
    name="Research Agent",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[
        DuckDuckGoTools(),
        HackerNewsTools(),
        YFinanceTools(
            enable_stock_price=True,
            enable_company_info=True,
            enable_analyst_recommendations=True,
            enable_company_news=True,
        ),
    ],
    instructions=[
        "You are a research assistant that gathers information from multiple sources.",
        "Always search the web AND check HackerNews for the latest discussions.",
        "For finance questions, also pull stock data and analyst recommendations.",
        "Synthesize findings into a clear, well-structured summary.",
    ],
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS — streaming with rich plan display
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[research_agent],
    interfaces=[
        Slack(
            agent=research_agent,
            streaming=True,
            reply_to_mentions_only=True,
            loading_messages=[
                "Researching...",
                "Gathering sources...",
                "Analyzing data...",
            ],
            suggested_prompts=[
                {
                    "title": "Tech News",
                    "message": "What are the top tech stories on HackerNews today?",
                },
                {
                    "title": "Stock Analysis",
                    "message": "Analyze NVDA stock - get the price, news, and analyst recommendations",
                },
                {
                    "title": "Research",
                    "message": "Research the latest developments in AI agents",
                },
            ],
        )
    ],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="streaming_research:app", port=8000, reload=True)
