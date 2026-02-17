"""
Support Team
============

Demonstrates support team.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.team import Team
from agno.tools.slack import SlackTools
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

team_db = SqliteDb(session_table="team_sessions", db_file="tmp/support_team.db")

# Technical Support Agent
tech_support = Agent(
    name="Technical Support",
    role="Code and technical troubleshooting",
    model=OpenAIChat(id="gpt-4o"),
    tools=[WebSearchTools()],
    instructions=[
        "You handle technical questions about code, APIs, and implementation.",
        "Provide code examples when helpful.",
        "Search for current documentation and best practices.",
    ],
    markdown=True,
)

# Documentation Agent
docs_agent = Agent(
    name="Documentation Specialist",
    role="Finding and explaining documentation",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        SlackTools(
            enable_search_messages=True,
            enable_get_thread=True,
        ),
        WebSearchTools(),
    ],
    instructions=[
        "You find relevant documentation and past discussions.",
        "Search Slack for previous answers to similar questions.",
        "Search the web for official documentation.",
        "Explain documentation in simple terms.",
    ],
    markdown=True,
)

# The Team with a coordinator
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
        Slack(
            team=support_team,
            reply_to_mentions_only=True,
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="support_team:app", reload=True)
