"""
Support Team
=============

A WhatsApp support team with a researcher and a writer that collaborate
to answer user questions.

Requires:
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID
  ANTHROPIC_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.team import Team
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

model = Claude(id="claude-sonnet-4-6")
team_db = SqliteDb(db_file="tmp/support_team.db")

researcher = Agent(
    name="Researcher",
    role="Find accurate, up-to-date information on the web",
    model=model,
    tools=[WebSearchTools()],
    instructions=[
        "Search the web for relevant information to answer the user's question.",
        "Return the key facts and sources you found.",
    ],
    markdown=True,
)

writer = Agent(
    name="Writer",
    role="Turn research into clear, friendly WhatsApp replies",
    model=model,
    instructions=[
        "Take the research provided and write a concise, helpful reply.",
        "Keep it short and conversational -- this is a WhatsApp chat.",
        "Use bullet points for lists and bold for emphasis.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

support_team = Team(
    name="Support Team",
    model=model,
    members=[researcher, writer],
    description="A support team that researches questions and writes clear answers.",
    instructions=[
        "When the user asks a question, delegate research to the Researcher.",
        "Then have the Writer compose a friendly WhatsApp-style reply.",
        "Do not use emojis. Keep a professional, neutral tone.",
    ],
    db=team_db,
    add_history_to_context=True,
    num_history_runs=3,
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS setup
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    teams=[support_team],
    interfaces=[Whatsapp(team=support_team)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="support_team:app", reload=True)
