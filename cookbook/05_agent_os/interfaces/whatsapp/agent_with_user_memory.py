from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory.manager import MemoryManager
from agno.models.google import Gemini
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.duckduckgo import DuckDuckGoTools

agent_db = SqliteDb(db_file="tmp/persistent_memory.db")

memory_manager = MemoryManager(
    memory_capture_instructions="""\
                    Collect User's name,
                    Collect Information about user's passion and hobbies,
                    Collect Information about the users likes and dislikes,
                    Collect information about what the user is doing with their life right now
                """,
    model=Gemini(id="gemini-2.0-flash"),
)


personal_agent = Agent(
    name="Basic Agent",
    model=Gemini(id="gemini-2.0-flash"),
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
    db=agent_db,
    memory_manager=memory_manager,
    enable_agentic_memory=True,
    instructions=dedent("""
        You are a personal AI friend of the user, your purpose is to chat with the user about things and make them feel good.
        First introduce yourself and ask for their name then, ask about themeselves, their hobbies, what they like to do and what they like to talk about.
        Use DuckDuckGo search tool to find latest information about things in the conversations
    """),
    debug_mode=True,
)


# Setup our AgentOS app
agent_os = AgentOS(
    agents=[personal_agent],
    interfaces=[Whatsapp(agent=personal_agent)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="agent_with_user_memory:app", reload=True)
