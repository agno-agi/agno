"""
Support Team
============

Multi-agent team on Discord that routes questions to specialists.

Prerequisites:
    export DISCORD_BOT_TOKEN="your-bot-token"
    export DISCORD_PUBLIC_KEY="your-public-key"
    export DISCORD_APPLICATION_ID="your-app-id"
    export OPENAI_API_KEY="your-openai-key"

Run:
    python cookbook/05_agent_os/interfaces/discord/support_team.py

Then expose via ngrok:
    ngrok http 7777

Set the Interactions Endpoint URL in the Discord Developer Portal to:
    https://<ngrok-url>/discord/interactions
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.discord import Discord
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

team_db = SqliteDb(session_table="team_sessions", db_file="tmp/discord_support_team.db")

tech_support = Agent(
    name="Technical Support",
    role="Code and technical troubleshooting",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "You handle technical questions about code, APIs, and implementation.",
        "Provide code examples when helpful.",
        "Search for current documentation and best practices.",
    ],
    markdown=True,
)

docs_agent = Agent(
    name="Documentation Specialist",
    role="Finding and explaining documentation",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "You find relevant documentation and references.",
        "Search the web for official documentation.",
        "Explain documentation in simple terms.",
    ],
    markdown=True,
)

support_team = Team(
    name="Support Team",
    model=OpenAIChat(id="gpt-4o"),
    members=[tech_support, docs_agent],
    description="A support team that routes questions to the right specialist.",
    instructions=[
        "You coordinate support requests.",
        "Route technical/code questions to Technical Support.",
        "Route 'how do I' or 'where is' questions to Documentation Specialist.",
        "For complex questions, consult both agents.",
    ],
    db=team_db,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(
    teams=[support_team],
    interfaces=[
        Discord(
            team=support_team,
            reply_in_thread=True,
        )
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="support_team:app", reload=True)
