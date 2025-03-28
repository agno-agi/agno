"""
This recipe shows how to use agentic context to improve the performance of the team.

Steps:
1. Run: `pip install openai sqlalchemy agno` to install dependencies
2. Run: `python cookbook/teams/memory/04_agentic_context.py` to run the agent
"""

from agno.agent import Agent
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.memory.team import TeamMemory
from agno.models.openai import OpenAIChat
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools()],
    storage=SqliteAgentStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
)

web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIChat(id="gpt-4o"),
    role="Searches the web for information on a company.",
    tools=[DuckDuckGoTools()],
    storage=SqliteAgentStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
)

team = Team(
    name="Stock Team",
    mode="coordinate",
    model=OpenAIChat("gpt-4o"),
    storage=SqliteAgentStorage(
        table_name="team_sessions", db_file="tmp/persistent_memory.db"
    ),
    memory=TeamMemory(
        db=SqliteMemoryDb(
            table_name="team_memory",
            db_file="tmp/team_memory.db",
        ),
    ),
    members=[stock_searcher, web_searcher],
    instructions=[
        "You can search the stock market for information about a particular company's stock.",
        "Always add any stock information you find to the team context."
        "You can also search the web for wider company information.",
    ],
    enable_agentic_context=True,
    show_tool_calls=True,
    markdown=True,
    show_members_responses=True,
)


# -*- Share personal information
team.print_response(
    "First find the stock price of apple.Then find any information about the company.",
    stream=True,
    stream_intermediate_steps=True,
)

team.print_response(
    "What is the price of google stock?", stream=True, stream_intermediate_steps=True
)

print("TEAM CONTEXT: ", team.memory.team_context.text)
