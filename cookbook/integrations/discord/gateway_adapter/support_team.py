"""
Discord Gateway Support Team
============================

A multi-agent support team behind fluid chat. Mention the bot with a support
question and the coordinator routes it: Technical Support handles code and
API questions; Documentation Specialist searches past Discord discussions and
the web for existing answers. Follow-ups continue in the same thread.

Key concepts:
  - ``Team`` with a coordinator model routes questions to the best member.
  - Documentation Specialist uses ``DiscordTools`` to pull past threads and
    channel messages for prior answers.
  - Both members use ``WebSearchTools`` for external documentation.

Setup: Set DISCORD_BOT_TOKEN, enable the Message Content Intent under Bot
settings, and install discord.py. Grant the bot **Read Message History** and
**View Channels** so the Documentation Specialist can search past
discussions. No public URL or tunnel needed.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import DiscordGateway
from agno.team import Team
from agno.tools.discord import DiscordTools
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

team_db = SqliteDb(
    session_table="discord_support_sessions", db_file="tmp/discord_gw_support_team.db"
)

tech_support = Agent(
    name="Technical Support",
    role="Handles code and technical troubleshooting",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[WebSearchTools()],
    instructions=[
        "You handle technical questions about code, APIs, and implementation.",
        "Provide concise code examples when helpful.",
        "Search the web for current documentation and best practices.",
    ],
    markdown=True,
)

docs_agent = Agent(
    name="Documentation Specialist",
    role="Finds and explains existing documentation and past answers",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        DiscordTools(
            enable_list_channels=True,
            enable_get_channel_messages=True,
            enable_get_channel_info=True,
            enable_send_message=False,
            enable_delete_message=False,
        ),
        WebSearchTools(),
    ],
    instructions=[
        "You find relevant documentation and past discussions in the Discord server.",
        "Your context includes ``discord_guild_id`` and ``discord_channel_id`` -",
        "use those to scope lookups to the current server and channel.",
        "Prefer linking to existing Discord threads or posts when you find a prior answer.",
        "Fall back to web search for official external documentation.",
    ],
    markdown=True,
)

support_team = Team(
    name="Discord Support Team",
    model=OpenAIResponses(id="gpt-5.4"),
    members=[tech_support, docs_agent],
    description="A support team that routes questions to the right specialist.",
    instructions=[
        "You coordinate support requests on Discord.",
        "Route technical/code questions to Technical Support.",
        "Route 'how do I' or 'where is' questions to Documentation Specialist.",
        "For complex questions, consult both members and synthesize.",
        "Keep the final reply concise (under 2000 characters per chunk).",
    ],
    db=team_db,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(
    teams=[support_team],
    interfaces=[DiscordGateway(team=support_team)],
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
    agent_os.serve(app="support_team:app", reload=False)
