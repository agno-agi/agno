"""
Agent With User Memory
======================

A personal assistant that remembers users across conversations using
``MemoryManager``. The agent captures names, hobbies, and preferences,
then uses that context in future chats.

Key concepts:
  - ``MemoryManager`` extracts and stores user facts after each run.
  - ``update_memory_on_run=True`` triggers automatic memory capture.
  - ``memory_capture_instructions`` tell the manager what to look for.

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory.manager import MemoryManager
from agno.models.anthropic.claude import Claude
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/persistent_memory.db")

memory_manager = MemoryManager(
    memory_capture_instructions="""\
                    Collect User's name,
                    Collect Information about user's passion and hobbies,
                    Collect Information about the users likes and dislikes,
                    Collect information about what the user is doing with their life right now
                """,
    model=Claude(id="claude-sonnet-4-20250514"),
)


personal_agent = Agent(
    name="Basic Agent",
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[WebSearchTools()],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
    db=agent_db,
    memory_manager=memory_manager,
    update_memory_on_run=True,
    instructions=dedent("""
        You are a personal AI friend in a Slack chat. Your purpose is to chat with the user and make them feel good.
        First introduce yourself and ask for their name, then ask about themselves, their hobbies, what they like to do and what they like to talk about.
        Use the web search tool to find the latest information about things in the conversation.
        You may sometimes receive messages prepended with "group message" — when that happens, reply to the whole group instead of treating them as from a single user.
                        """),
)


# Setup our AgentOS app
agent_os = AgentOS(
    agents=[personal_agent],
    interfaces=[Slack(agent=personal_agent)],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="agent_with_user_memory:app", reload=True)
