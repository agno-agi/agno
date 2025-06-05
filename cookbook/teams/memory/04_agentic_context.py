"""
This recipe shows how to use agentic context to improve the performance of the team.

Steps:
1. Run: `pip install openai sqlalchemy agno` to install dependencies
2. Run: `python cookbook/teams/memory/04_agentic_context.py` to run the agent
"""

from agno.agent import Agent
from agno.memory.v2.memory import Memory
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

memory = Memory(model=Gemini(id="gemini-2.0-flash-exp"))

stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools(cache_results=True)],
    storage=SqliteAgentStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
    memory=memory,
)

web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIChat(id="gpt-4o"),
    role="Searches the web for information on a company.",
    tools=[DuckDuckGoTools(cache_results=True)],
    storage=SqliteAgentStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
    memory=memory,
)

team = Team(
    name="Stock Team",
    mode="coordinate",
    model=OpenAIChat("gpt-4o"),
    storage=SqliteAgentStorage(
        table_name="team_sessions", db_file="tmp/persistent_memory.db"
    ),
    members=[stock_searcher, web_searcher],
    instructions=[
        "You can search the stock market for information about a particular company's stock.",
        "You can also search the web for wider company information.",
        "Always add ALL stock or company information you get from team members to the shared team context.",
    ],
    memory=memory,
    enable_agentic_context=True,
    show_tool_calls=True,
    markdown=True,
    show_members_responses=True,
)

session_id = "stock_team_session_1"


team.print_response(
    "First find the stock price of apple. Then find any information about the company.",
    stream=True,
    stream_intermediate_steps=True,
    session_id=session_id,
)

team.print_response(
    "What is the price of google stock?",
    stream=True,
    stream_intermediate_steps=True,
    session_id=session_id,
)
print("Team Context: ", memory.team_context[session_id].text)
for interaction in memory.team_context[session_id].member_interactions:
    print(
        "Member Interactions: ",
        f"{interaction.member_name}: {interaction.task} - {interaction.response.content}",
    )
