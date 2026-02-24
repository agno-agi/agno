"""
Streaming Team
==============

Demonstrates streaming a multi-agent team in Slack.
The Stock Research Team has two members that use YFinanceTools,
so each request triggers multiple tool calls across multiple agents.

Requirements:
  - Your Slack app must have the ``assistant:write`` scope enabled.
  - Event Subscriptions must be configured for ``app_mention``, ``message.im``,
    and ``assistant_thread_started`` (for suggested prompts).
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.team import Team
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Team Members
# ---------------------------------------------------------------------------

stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIResponses(id="gpt-5-mini"),
    role="Searches for stock prices and analyst recommendations.",
    tools=[
        YFinanceTools(enable_stock_price=True, enable_analyst_recommendations=True),
    ],
)

company_info_agent = Agent(
    name="Company Info",
    model=OpenAIResponses(id="gpt-5-mini"),
    role="Searches for company info and recent news.",
    tools=[
        YFinanceTools(
            enable_stock_price=False, enable_company_info=True, enable_company_news=True
        ),
    ],
)

# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

stock_team = Team(
    name="Stock Research Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[stock_searcher, company_info_agent],
    markdown=True,
    show_members_responses=False,
    db=SqliteDb(db_file="tmp/stock_team.db"),
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# AgentOS with Slack streaming
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    teams=[stock_team],
    interfaces=[
        Slack(
            team=stock_team,
            streaming=True,
            reply_to_mentions_only=True,
            suggested_prompts=[
                {
                    "title": "NVDA",
                    "message": "What is the current stock price and latest news for NVDA?",
                },
                {"title": "TSLA", "message": "Give me a full analysis of TSLA"},
                {
                    "title": "Compare",
                    "message": "Compare AAPL and MSFT stock performance",
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
    agent_os.serve(app="streaming_team:app", port=8000, reload=True)
