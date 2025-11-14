from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory.manager import MemoryManager
from agno.models.anthropic.claude import Claude
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.duckduckgo import DuckDuckGoTools

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/persistent_memory.db")

memory_manager = MemoryManager(
    memory_capture_instructions="""\
                    Collect User's name,
                    Collect Information about user's passion and hobbies,
                    Collect Information about the users likes and dislikes,
                    Collect information about what the user is doing with their life right now
                """,
    model=Claude(id="claude-3-5-sonnet-20241022"),
)


personal_agent = Agent(
    name="Basic Agent",
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
    db=agent_db,
    memory_manager=memory_manager,
    enable_user_memories=True,
    instructions=dedent("""
        You are a personal AI friend in a slack chat, your purpose is to chat with the user about things and make them feel good.
        First introduce yourself and ask for their name then, ask about themeselves, their hobbies, what they like to do and what they like to talk about.
        Use DuckDuckGo search tool to find latest information about things in the conversations
        You may sometimes recieve messages prepenned with group message when that is the message then reply to whole group instead of treating them as from a single user
                        """),
    debug_mode=True,
)


# Setup our AgentOS app
agent_os = AgentOS(
    agents=[personal_agent],
    interfaces=[Slack(agent=personal_agent)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="agent_with_user_memory:app", reload=True)
