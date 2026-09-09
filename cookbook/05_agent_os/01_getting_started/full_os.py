"""
Full AgentOS Tour
=================

Mount one agent, team, workflow, and knowledge base on a single AgentOS. The
server exposes their catalogs and run endpoints under /agents, /teams, and
/workflows; knowledge management under /knowledge; shared history under
/sessions; and the complete discovery document at /config.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/01_getting_started/full_os.py
Try: Run run_over_http.py from this folder in another terminal
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.vectordb.chroma import ChromaDb
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Database and Knowledge
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="getting-started-db",
    db_file="tmp/getting_started.db",
)

knowledge = Knowledge(
    name="Getting Started Knowledge",
    description="Documents uploaded during the getting-started lesson.",
    contents_db=db,
    vector_db=ChromaDb(
        path="tmp/getting_started_chroma",
        collection="getting_started",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Create Agent, Team, and Workflow
# ---------------------------------------------------------------------------

assistant = Agent(
    id="getting-started-agent",
    name="Getting Started Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    knowledge=knowledge,
    search_knowledge=True,
    instructions="Answer clearly and use the knowledge base when it is relevant.",
    markdown=True,
)

assistant_team = Team(
    id="getting-started-team",
    name="Getting Started Team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[assistant],
    instructions="Coordinate the available specialist and return one concise answer.",
    markdown=True,
)

answer_workflow = Workflow(
    id="getting-started-workflow",
    name="Getting Started Workflow",
    description="Run the assistant as a reusable workflow step.",
    steps=[Step(name="Answer Question", agent=assistant)],
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="getting-started-os",
    description="One AgentOS exposing every core runtime primitive.",
    db=db,
    agents=[assistant],
    teams=[assistant_team],
    workflows=[answer_workflow],
    knowledge=[knowledge],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="full_os:app", reload=True)
