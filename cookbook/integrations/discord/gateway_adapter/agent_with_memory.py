"""
Discord Gateway Agent with User Memory
======================================

Remembers facts about each Discord user across conversations. A MemoryManager
captures durable details (name, preferences, projects) from every message,
keyed by the author's Discord user id - so memories follow the user across
channels, threads, and DMs.

Try: mention the bot with "My name is Ray and I prefer short answers", then
DM it "What do you know about me?"

Setup:
  1. Create a Discord application at https://discord.com/developers/applications
  2. Under Bot, enable the "Message Content Intent" (privileged intent toggle).
  3. Set env vars:
       DISCORD_BOT_TOKEN   - Application -> Bot -> Reset Token
  4. Install the gateway dependency: pip install discord.py
  5. Invite the bot to a server with Send Messages, Create Public Threads,
     and Send Messages in Threads permissions.
  6. Run this script, then @mention the bot in a channel or DM it.

Note: keep reload=False - auto-reload reconnects the gateway socket on every
file change, which is noisy and can hit Discord's session limits.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import DiscordGateway

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(
    session_table="discord_sessions", db_file="tmp/discord_gateway_memory.db"
)

memory_manager = MemoryManager(
    model=OpenAIResponses(id="gpt-5.4"),
    db=agent_db,
    memory_capture_instructions=(
        "Capture the user's name, role, preferences, current projects, "
        "and durable likes or dislikes."
    ),
)

discord_agent = Agent(
    name="Discord Gateway Memory Bot",
    model=OpenAIResponses(id="gpt-5.4"),
    db=agent_db,
    memory_manager=memory_manager,
    update_memory_on_run=True,
    instructions=[
        "You are a helpful assistant on Discord.",
        "Use saved user memories when they are relevant.",
        "Do not invent personal details that are not in the conversation or memory.",
        "Keep responses concise - Discord messages are capped at 2000 characters.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[discord_agent],
    interfaces=[DiscordGateway(agent=discord_agent)],
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
    agent_os.serve(app="agent_with_memory:app", reload=False)
