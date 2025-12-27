from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.integrations.discord import DiscordClient
from agno.models.google import Gemini
from agno.tools.duckduckgo import DuckDuckGoTools

db = SqliteDb(db_file="tmp/discord_client_cookbook.db")

personal_agent = Agent(
    name="Basic Agent",
    model=Gemini(id="gemini-2.0-flash"),
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
    db=db,
    enable_agentic_memory=True,
    instructions=dedent("""
        You are a personal AI friend of the user, your purpose is to chat with the user about things and make them feel good.
        First introduce yourself and ask for their name then, ask about themeselves, their hobbies, what they like to do and what they like to talk about.
        Use DuckDuckGo search tool to find latest information about things in the conversations
                        """),
    debug_mode=True,
)

discord_agent = DiscordClient(personal_agent)

if __name__ == "__main__":
    discord_agent.serve()
