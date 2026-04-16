"""
Discord Team
============

Multi-agent team on Discord: a Researcher gathers facts, then a Writer
turns them into a concise reply suitable for a Discord thread.

Key concepts:
  - ``Team`` with two specialist ``Agent`` members demonstrates delegation.
  - The team (not individual agents) is passed to the Discord interface.
  - Thread replies (default) keep each question's research trail in its
    own thread. Tool-call status shows which member/tool is running.

Setup: Set DISCORD_PUBLIC_KEY, DISCORD_APP_ID, DISCORD_BOT_TOKEN env vars.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import Discord
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

team_db = SqliteDb(session_table="discord_team_sessions", db_file="tmp/discord_team.db")

researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.4"),
    role="Researches topics and provides detailed factual information.",
    instructions=["Provide well-researched, factual information on the given topic."],
)

writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.4"),
    role="Takes research and writes clear, engaging summaries.",
    instructions=["Write concise, engaging summaries based on the research provided."],
)

discord_team = Team(
    name="Discord Research Team",
    model=OpenAIResponses(id="gpt-5.4"),
    members=[researcher, writer],
    db=team_db,
    instructions=[
        "You coordinate a research team on Discord.",
        "Use the Researcher to gather facts, then the Writer to create the final reply.",
        "Keep the final reply under 2000 characters when possible.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    teams=[discord_team],
    interfaces=[Discord(team=discord_team, reply_in_thread=True)],
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
    agent_os.serve(app="team:app", reload=True)
