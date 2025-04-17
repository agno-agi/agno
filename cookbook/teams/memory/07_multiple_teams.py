"""
This recipe shows how to have multiple teams with one shared memory.

Steps:
1. Run: `pip install openai sqlalchemy agno` to install dependencies
2. Run: `python cookbook/teams/memory/07_multiple_teams.py` to run the agent
"""

import asyncio

from agno.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.anthropic.claude import Claude
from agno.models.google.gemini import Gemini
from agno.models.mistral.mistral import MistralChat
from agno.models.openai import OpenAIChat
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from utils import print_team_memory

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

memory = Memory(model=Gemini(id="gemini-2.0-flash-exp"), db=memory_db)

# Reset the memory for this example
memory.clear()

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

chat_team = Team(
    name="Chat Team",
    mode="coordinate",
    model=OpenAIChat("gpt-4o"),
    storage=SqliteAgentStorage(
        table_name="team_sessions", db_file="tmp/persistent_memory.db"
    ),
    members=[web_searcher],
    instructions=["You can search the web for information."],
    memory=memory,
    enable_user_memories=True,
    show_tool_calls=True,
    markdown=True,
    show_members_responses=True,
)


french_agent = Agent(
    name="French Agent",
    role="You can only answer in French",
    model=MistralChat(id="mistral-large-latest"),
)
german_agent = Agent(
    name="German Agent",
    role="You can only answer in German",
    model=Claude("claude-3-5-sonnet-20241022"),
)

multi_language_team = Team(
    name="Multi Language Team",
    mode="route",
    model=OpenAIChat("gpt-4o"),
    members=[
        french_agent,
        german_agent,
    ],
    show_tool_calls=True,
    markdown=True,
    instructions=[
        "You are a language router that directs questions to the appropriate language agent. You can also answer questions in English.",
        "If the user asks in a language that is not English and is not spoken by any team member, respond in English with:",
        "'I can only answer in the following languages: English, French and German. Please ask your question in one of these languages.'",
        "Always check the language of the user's input before routing to an agent.",
        "For unsupported languages like Italian, respond in English with the above message.",
    ],
    memory=memory,
    enable_user_memories=True,
    show_members_responses=True,
)


if __name__ == "__main__":
    chat_session_id = "friendly_team_session_1"
    multi_language_session_id = "multi_language_team_session_1"
    user_id = "john_billings"

    asyncio.run(
        chat_team.aprint_response(
            "Hi! My name is John Billings and I love anime.",
            stream=True,
            stream_intermediate_steps=True,
            session_id=chat_session_id,
            user_id=user_id,
        )
    )

    asyncio.run(
        multi_language_team.aprint_response(
            "Ich komme aus Deutschland. Wie geht es Ihnen?",
            stream=True,
            stream_intermediate_steps=True,
            session_id=multi_language_session_id,
            user_id=user_id,
        )
    )

    # -*- Print team memory
    print_team_memory(user_id, memory.get_user_memories(user_id))
