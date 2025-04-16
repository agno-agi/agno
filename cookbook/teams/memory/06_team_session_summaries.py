"""
This recipe shows how to have the team create summaries of the session.

Steps:
1. Run: `pip install openai sqlalchemy agno` to install dependencies
2. Run: `python cookbook/teams/memory/06_team_session_summaries.py` to run the agent
"""

import asyncio

from agno.agent import Agent
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

memory = Memory(model=OpenAIChat("gpt-4o"))

web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIChat(id="gpt-4o"),
    role="Searches the web for information.",
    tools=[DuckDuckGoTools(cache_results=True)],
    storage=SqliteAgentStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
    memory=memory,
)

team = Team(
    name="Friendly Team",
    mode="coordinate",
    model=OpenAIChat("gpt-4o"),
    storage=SqliteAgentStorage(
        table_name="team_sessions", db_file="tmp/persistent_memory.db"
    ),
    members=[web_searcher],
    instructions=["You can search the web for information."],
    memory=memory,
    # Enable the team to make session summaries
    enable_session_summaries=True,
    show_tool_calls=True,
    markdown=True,
    show_members_responses=True,
)

if __name__ == "__main__":
    user_id = "john_billings"
    session_id_1 = "session_1"

    asyncio.run(
        team.aprint_response(
            "Hi! My name is John Billings and I live in New York City.",
            stream=True,
            stream_intermediate_steps=True,
            session_id=session_id_1,
            user_id=user_id,
        )
    )

    asyncio.run(
        team.aprint_response(
            "How is the weather in New York City?",
            stream=True,
            stream_intermediate_steps=True,
            session_id=session_id_1,
            user_id=user_id,
        )
    )

    session_summary = memory.get_session_summary(
        user_id=user_id, session_id=session_id_1
    )
    print("Session Summary: ", session_summary.summary)

    session_id_2 = "session_2"

    asyncio.run(
        team.aprint_response(
            "Ok, new topic. What is currently happening in the financial markets?",
            stream=True,
            stream_intermediate_steps=True,
            session_id=session_id_2,
            user_id=user_id,
        )
    )

    # You can also get the session summary from the team
    session_summary = team.get_session_summary(user_id=user_id, session_id=session_id_2)
    print("Session Summary: ", session_summary.summary)
