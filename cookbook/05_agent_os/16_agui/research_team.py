"""
Serve a Research Team over AG-UI
================================

Mount an AgentOS Team on AG-UI so member tool calls and the coordinated final
answer share one protocol event stream.

Prerequisites: OPENAI_API_KEY and internet access
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/research_team.py
Try: Request a sourced technology brief at http://localhost:7777/research-team/agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.team import Team
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Research Team
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agui-research-team-db",
    db_file="tmp/agui_research_team.db",
)

researcher = Agent(
    id="agui-researcher",
    name="Researcher",
    role="Find current, relevant source material.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[WebSearchTools()],
    instructions="Search the web, prefer primary sources, and return concise findings with URLs.",
)

writer = Agent(
    id="agui-writer",
    name="Writer",
    role="Turn research into a short, readable brief.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Synthesize supplied research without inventing unsupported facts.",
)

research_team = Team(
    id="agui-research-team",
    name="AG-UI Research Team",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    members=[researcher, writer],
    instructions=[
        "Delegate research to the Researcher and synthesis to the Writer.",
        "Return a concise brief with source links.",
    ],
    show_members_responses=True,
)

agent_os = AgentOS(
    id="agui-research-team-os",
    description="A coordinated research Team served through AG-UI.",
    teams=[research_team],
    interfaces=[AGUI(team=research_team, prefix="/research-team")],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Research Team Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
